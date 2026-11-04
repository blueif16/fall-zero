"""The web app (`web/`, served at /) and its HTTP API.

uv run fall-zero serve   # http://localhost:8011, API docs at /docs
"""

import asyncio
import base64
import json
import os
import re
import tempfile
import threading
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import Annotated, Literal

from fastapi import Body, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from fall_zero import agent, meta, room, store, voice
from fall_zero.analyze import VIDEO_SUFFIXES, analyze
from fall_zero.assess import CARD_STATUSES, assess_all, card, trajectory, warm
from fall_zero.clients import NotConfigured, chat, providers
from fall_zero.furniture import catalog

ROOT = store.ROOT
# Each analyzed upload is a run: web/<run>/ holds the photo, still.jpg and report.json; saved chats are
# threads/<id>.json. Both live in the store (fall_zero/store.py): out/ locally, Vercel Blob when deployed.
DEPLOYED = bool(os.environ.get("VERCEL"))


@asynccontextmanager
async def lifespan(_: FastAPI):
    asyncio.get_running_loop().run_in_executor(None, warm)  # the earthquake workers, in the background
    yield


app = FastAPI(title="Fall-Zero", lifespan=lifespan)


@app.exception_handler(NotConfigured)
async def not_configured(_, exc: NotConfigured) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": str(exc)})


@app.get("/api/health")
def health() -> dict[str, bool]:
    """Which providers have credentials in .env."""
    return {name: p.configured for name, p in providers().items()}


PAGE_CATALOGS = ("handoffs", "household")  # what the page itself reads of skill/catalog/


@app.get("/api/catalog/{name}")
def page_catalog(name: str) -> dict:
    """handoffs: the messages for when someone else has to say yes or do the work; household: the "Who's
    home" chips and what each answer changes."""
    if name not in PAGE_CATALOGS:
        raise HTTPException(404, "no such catalog")
    return catalog(name)


class ChatIn(BaseModel):
    prompt: str
    provider: str = "meta"
    model: str | None = None


class ImageIn(BaseModel):
    prompt: str
    size: str | None = None


async def _save(upload: UploadFile, tmp: str) -> Path:
    path = Path(tmp) / (upload.filename or "upload")
    path.write_bytes(await upload.read())
    return path


if not DEPLOYED:  # model playgrounds for local work; deployed they'd hand anyone the Meta key

    @app.post("/api/chat")
    def chat_route(body: ChatIn) -> dict:
        return {"text": chat(body.prompt, provider=body.provider, model=body.model)}

    @app.post("/api/image")
    def image_route(body: ImageIn) -> dict:
        png = meta.generate_image(body.prompt, size=body.size)
        return {"image": f"data:image/png;base64,{base64.b64encode(png).decode()}"}

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
    frame_at_s: Annotated[float | None, Form()] = None,
) -> StreamingResponse:
    """One chat turn, streamed as NDJSON events:
    step {text} ... report {run, still, cards, report} ... delta {text} ... done {response_id} | error {text}.
    With `media` (a photo or video) the pipeline runs first; without it the agent just answers.
    `context` is the page's current cards (after the user's taps), so follow-ups see them.
    The page sends a video as its sharpest frame, and `frame_at_s` is where in the video it was."""
    upload = None
    if media and media.filename:
        suffix = Path(media.filename).suffix.lower()
        is_video = (media.content_type or "").startswith("video/") or suffix in VIDEO_SUFFIXES
        if not (is_video or (media.content_type or "").startswith("image/")):
            return StreamingResponse(iter([_line(type="error", text="Send a photo or a video.")]))
        run = store.LOCAL / "web" / uuid.uuid4().hex[:12]
        run.mkdir(parents=True)
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
                if frame_at_s is not None:
                    report["frame_at_s"] = frame_at_s
                kept = [f"web/{upload.parent.name}/{f}" for f in (upload.name, image.name, "report.json")]
                await run_in_threadpool(store.keep, *kept)
                yield _line(type="step", text="Shaking it in simulated earthquakes · MuJoCo")
                cards = await run_in_threadpool(assess_all, report, True)
                _prepare_scenes(report, cards)
                others = [p["piece"]["name"] for p in report["pieces"] if p["status"] not in CARD_STATUSES]
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


RISKS = ("child", "adult", "quake")


def _prepare_scenes(report: dict, cards: list[dict]) -> None:
    """Simulate the whole room in the background while the reply is written, worst scenario first: it
    is the one the page opens with."""
    if not cards:
        return
    worst = next((k for k in RISKS if any(c["risks"][k]["status"] == "tips" for c in cards)), "quake")
    answers = [c["answers"] for c in cards]
    order = [worst] + [k for k in RISKS if k != worst]
    threading.Thread(target=lambda: [room.scene(report, answers, k) for k in order], daemon=True).start()


class AssessIn(BaseModel):
    run: str
    piece: int  # index among the carded pieces, as in the report event's `cards`
    answers: dict = {}


def _run_file(run: str, name: str) -> Path:
    if not (re.fullmatch(r"[0-9a-f]{12}", run) and re.fullmatch(r"[\w-]+\.\w+", name)):
        raise HTTPException(404, "unknown file")
    if not (path := store.local(f"web/{run}/{name}")):
        raise HTTPException(404, "unknown file")
    return path


def _report(run: str) -> dict:
    return json.loads(_run_file(run, "report.json").read_text())


@app.get("/files/{run}/{name}")
def run_file(run: str, name: str) -> FileResponse:
    """A run's photo and still; they never change once written."""
    return FileResponse(_run_file(run, name), headers={"Cache-Control": "private, max-age=31536000, immutable"})


def _entry(run: str, piece: int) -> dict:
    carded = [p for p in _report(run)["pieces"] if p["status"] in CARD_STATUSES]
    if not 0 <= piece < len(carded):
        raise HTTPException(404, "unknown piece")
    return carded[piece]


@app.post("/api/assess")
def assess_route(body: AssessIn) -> dict:
    """Re-check one card after the user answers a question or marks a fix done."""
    return card(_entry(body.run, body.piece), body.answers, simulate_quakes=True)


class SimulateIn(AssessIn):
    scenario: Literal["quake", "child", "adult"] = "quake"
    variant: Literal["as_is", "anchor", "locks", "moved"] = "as_is"
    seed: int = 1


@app.post("/api/simulate")
def simulate_route(body: SimulateIn) -> dict:
    """The motion of one simulation, for the card's 3D viewer to play."""
    entry = _entry(body.run, body.piece)
    if entry["status"] != "analyzed":
        raise HTTPException(404, "this piece was judged, not simulated")
    return trajectory(entry, body.answers, body.scenario, body.variant, body.seed)


class SceneIn(BaseModel):
    run: str
    answers: list[dict] = []  # each carded piece's answers, a previewed fix's answer added
    scenario: Literal["quake", "child", "adult"] = "quake"
    focus: int | None = None  # in the child and adult tests, only this piece is loaded


@app.post("/api/scene")
def scene_route(body: SceneIn) -> dict:
    """The whole room in one simulation, every piece placed as in the photo, for the panel's viewer."""
    return room.scene(_report(body.run), body.answers, body.scenario, body.focus)


Owner = Annotated[str, Header(alias="X-Owner")]


def _folder(owner: str) -> str:
    """Deployed, each browser keeps its chats under its own id (X-Owner, kept in its localStorage), so no one
    lists anyone else's; locally they're all yours, in one folder."""
    if not store.REMOTE:
        return "threads/"
    if not re.fullmatch(r"[0-9a-f]{32}", owner):
        raise HTTPException(400, "no owner")
    return f"threads/{owner}/"


def _thread_name(tid: str, owner: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{12}", tid):
        raise HTTPException(404, "unknown thread")
    return f"{_folder(owner)}{tid}.json"


@app.get("/api/threads")
def list_threads(owner: Owner = "") -> list[dict]:
    """Saved chats, newest first, without their messages."""
    threads = [json.loads(body) for n in store.names(_folder(owner)) if n.endswith(".json") and (body := store.read(n))]
    keep = ("id", "title", "updated", "thumb", "status")
    return sorted(({k: t.get(k) for k in keep} for t in threads), key=lambda t: t["updated"] or "", reverse=True)


@app.get("/api/threads/{tid}")
def get_thread(tid: str, owner: Owner = "") -> dict:
    if (body := store.read(_thread_name(tid, owner))) is None:
        raise HTTPException(404, "unknown thread")
    return json.loads(body)


@app.put("/api/threads/{tid}")
def save_thread(tid: str, thread: Annotated[dict, Body()], owner: Owner = "") -> dict:
    """The page saves the whole chat after every turn and every tap: messages, cards and answers."""
    thread |= {"id": tid, "updated": datetime.now(UTC).isoformat()}
    store.write(_thread_name(tid, owner), json.dumps(thread).encode())
    return {"updated": thread["updated"]}


@app.delete("/api/threads/{tid}")
def delete_thread(tid: str, owner: Owner = "") -> dict:
    store.delete(_thread_name(tid, owner))
    return {"deleted": tid}


class Revalidated(StaticFiles):
    """The page's own files: the browser asks again on every load (a 304 when unchanged), so it never
    runs a stale script after an update."""

    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


app.mount("/samples", StaticFiles(directory=ROOT / "samples"), name="samples")
app.mount("/", Revalidated(directory=ROOT / "web", html=True), name="web")  # last: catches every other path
