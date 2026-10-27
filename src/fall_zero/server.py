"""The web app (`web/`, served at /) and its HTTP API.

uv run fall-zero serve   # http://localhost:8011, API docs at /docs
"""

import asyncio
import base64
import json
import re
import tempfile
import uuid
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import Annotated, Literal

from fastapi import Body, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from fall_zero import agent, meta, voice
from fall_zero.analyze import VIDEO_SUFFIXES, analyze
from fall_zero.assess import assess, assess_all, trajectory
from fall_zero.clients import NotConfigured, chat, providers

ROOT = Path(__file__).resolve().parents[2]
RUNS = ROOT / "out" / "web"  # one folder per analyzed upload: the photo, still.jpg, report.json
RUNS.mkdir(parents=True, exist_ok=True)
THREADS = ROOT / "out" / "threads"  # saved chats, one JSON file each, so they can be reopened
THREADS.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Fall-Zero")


@app.exception_handler(NotConfigured)
async def not_configured(_, exc: NotConfigured) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": str(exc)})


@app.get("/api/health")
def health() -> dict[str, bool]:
    """Which providers have credentials in .env."""
    return {name: p.configured for name, p in providers().items()}


class ChatIn(BaseModel):
    prompt: str
    provider: str = "meta"
    model: str | None = None


@app.post("/api/chat")
def chat_route(body: ChatIn) -> dict:
    return {"text": chat(body.prompt, provider=body.provider, model=body.model)}


class ImageIn(BaseModel):
    prompt: str
    size: str | None = None


@app.post("/api/image")
def image_route(body: ImageIn) -> dict:
    png = meta.generate_image(body.prompt, size=body.size)
    return {"image": f"data:image/png;base64,{base64.b64encode(png).decode()}"}


async def _save(upload: UploadFile, tmp: str) -> Path:
    path = Path(tmp) / (upload.filename or "upload")
    path.write_bytes(await upload.read())
    return path


@app.post("/api/segment")
async def segment_route(image: Annotated[UploadFile, File()], concept: Annotated[str, Form()]) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        segments = await meta.segment_image(await _save(image, tmp), concept, include_confidence=True)
    return {
        "segments": [
            {"id": s.object_id, "box": s.box, "confidence": s.confidence, "svg_path": s.svg_path} for s in segments
        ]
    }


@app.post("/api/transcribe")
async def transcribe_route(audio: Annotated[UploadFile, File()], mode: Annotated[str, Form()] = "PUSH_TO_TALK") -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        wav = await run_in_threadpool(voice.to_wav, await _save(audio, tmp))
        return await run_in_threadpool(voice.transcribe_file, wav, mode=mode)


def _line(**event) -> str:
    return json.dumps(event, default=float) + "\n"


async def _analyze_with_steps(media: Path, out_dir: Path):
    """Run the blocking pipeline in a thread; yield ("step", message) as it goes, then ("report", report)."""
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    work = partial(analyze, media, out_dir, video=False,
                   on_step=lambda msg: loop.call_soon_threadsafe(queue.put_nowait, ("step", msg)))  # fmt: skip
    done = loop.run_in_executor(None, work)
    done.add_done_callback(lambda f: queue.put_nowait(("finished", f)))
    while (item := await queue.get())[0] == "step":
        yield item
    yield "report", item[1].result()


@app.post("/api/turn")
async def turn(
    text: Annotated[str, Form()] = "",
    previous_response_id: Annotated[str, Form()] = "",
    context: Annotated[str, Form()] = "",
    media: Annotated[UploadFile | None, File()] = None,
) -> StreamingResponse:
    """One chat turn, streamed as NDJSON events:
    step {text} ... report {run, still, cards, report} ... delta {text} ... done {response_id} | error {text}.
    With `media` (a photo or video) the pipeline runs first; without it the agent just answers.
    `context` is the page's current cards (after the user's taps), so follow-ups see them."""
    upload = None
    if media and media.filename:
        suffix = Path(media.filename).suffix.lower()
        is_video = (media.content_type or "").startswith("video/") or suffix in VIDEO_SUFFIXES
        if not (is_video or (media.content_type or "").startswith("image/")):
            return StreamingResponse(iter([_line(type="error", text="Send a photo or a video.")]))
        run = RUNS / uuid.uuid4().hex[:12]
        run.mkdir()
        upload = run / f"upload{suffix or ('.mp4' if is_video else '.jpg')}"
        upload.write_bytes(await media.read())

    async def events():
        try:
            report, image, cards, others = {}, None, None, []
            if upload:
                async for kind, value in _analyze_with_steps(upload, upload.parent):
                    if kind == "step":
                        yield _line(type="step", text=value)
                    else:
                        report, image = value, Path(value["image"])
                yield _line(type="step", text="Shaking it in simulated earthquakes · MuJoCo")
                cards = await run_in_threadpool(assess_all, report, True)
                others = [p["piece"]["name"] for p in report["pieces"] if p["status"] != "analyzed"]
                files = f"/files/{upload.parent.name}"
                yield _line(type="report", run=upload.parent.name, still=f"{files}/{image.name}",
                            upload=f"{files}/{upload.name}", size=report["size"], frame_at_s=report["frame_at_s"],
                            cards=cards, others=others, report=report)  # fmt: skip
            yield _line(type="step", text="Writing it up · Muse Spark")
            async for kind, value in agent.reply(text, image, cards, others, context, previous_response_id or None):
                yield _line(type=kind, text=value) if kind == "delta" else _line(type="done", response_id=value)
        except Exception as exc:  # the page shows it in the chat instead of hanging
            yield _line(type="error", text=f"{type(exc).__name__}: {exc}")

    return StreamingResponse(events(), media_type="application/x-ndjson")


class AssessIn(BaseModel):
    run: str
    piece: int  # index among the analyzed pieces, as in the report event's `cards`
    answers: dict = {}


def _entry(run: str, piece: int) -> dict:
    if not re.fullmatch(r"[0-9a-f]{12}", run) or not (RUNS / run / "report.json").exists():
        raise HTTPException(404, "unknown run")
    report = json.loads((RUNS / run / "report.json").read_text())
    analyzed = [p for p in report["pieces"] if p["status"] == "analyzed"]
    if not 0 <= piece < len(analyzed):
        raise HTTPException(404, "unknown piece")
    return analyzed[piece]


@app.post("/api/assess")
def assess_route(body: AssessIn) -> dict:
    """Re-check one card after the user answers a question or marks a fix done."""
    return assess(_entry(body.run, body.piece), body.answers, simulate_quakes=True)


class SimulateIn(AssessIn):
    scenario: Literal["quake", "child", "adult"] = "quake"
    variant: Literal["as_is", "anchor", "moved"] = "as_is"
    seed: int = 1


@app.post("/api/simulate")
def simulate_route(body: SimulateIn) -> dict:
    """The motion of one simulation, for the card's 3D viewer to play."""
    return trajectory(_entry(body.run, body.piece), body.answers, body.scenario, body.variant, body.seed)


def _thread_file(tid: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{12}", tid):
        raise HTTPException(404, "unknown thread")
    return THREADS / f"{tid}.json"


@app.get("/api/threads")
def list_threads() -> list[dict]:
    """Saved chats, newest first, without their messages."""
    threads = [json.loads(f.read_text()) for f in THREADS.glob("*.json")]
    keep = ("id", "title", "updated", "thumb", "status")
    return sorted(({k: t.get(k) for k in keep} for t in threads), key=lambda t: t["updated"] or "", reverse=True)


@app.get("/api/threads/{tid}")
def get_thread(tid: str) -> dict:
    path = _thread_file(tid)
    if not path.exists():
        raise HTTPException(404, "unknown thread")
    return json.loads(path.read_text())


@app.put("/api/threads/{tid}")
def save_thread(tid: str, thread: Annotated[dict, Body()]) -> dict:
    """The page saves the whole chat after every turn and every tap: messages, cards and answers."""
    thread |= {"id": tid, "updated": datetime.now(UTC).isoformat()}
    _thread_file(tid).write_text(json.dumps(thread))
    return {"updated": thread["updated"]}


@app.delete("/api/threads/{tid}")
def delete_thread(tid: str) -> dict:
    _thread_file(tid).unlink(missing_ok=True)
    return {"deleted": tid}


app.mount("/files", StaticFiles(directory=RUNS), name="files")
app.mount("/samples", StaticFiles(directory=ROOT / "samples"), name="samples")
app.mount("/", StaticFiles(directory=ROOT / "web", html=True), name="web")  # last: catches every other path
