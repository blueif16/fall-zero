"""Muse Voice Transcribe: file transcription over HTTP and live streaming over WebSocket.

Audio must be mono 16-bit PCM at 16 or 24 kHz; `to_wav` converts anything ffmpeg can read.
Modes: PUSH_TO_TALK (one turn, default), ENDPOINTING (model finds turns), DIARIZATION (speaker labels).
"""

import asyncio
import json
import subprocess
import uuid
import wave
from collections.abc import AsyncIterator, Callable
from pathlib import Path

import httpx
import websockets

from fall_zero.config import get_settings

REALTIME_URL = "wss://api.meta.ai/v1/asr/realtime"
RATE = 24_000
FRAME_BYTES = RATE * 80 // 1000 * 2  # 80 ms of int16 samples


def _ready(path: Path) -> bool:
    try:
        with wave.open(str(path)) as w:
            return (w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getcomptype()) == (1, 2, RATE, "NONE")
    except (wave.Error, EOFError):
        return False


def to_wav(src: str | Path, dst: str | Path | None = None) -> Path:
    """Convert any audio/video file to the 24 kHz mono PCM WAV the API accepts. The web page already
    records one (there's no ffmpeg on Vercel), and that is used as it is."""
    src = Path(src)
    if _ready(src):
        return src
    dst = Path(dst) if dst else src.with_suffix(".24k.wav")
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(src),
            "-ac",
            "1",
            "-ar",
            str(RATE),
            "-c:a",
            "pcm_s16le",
            "-map_metadata",
            "-1",
            str(dst),
        ],
        check=True,
    )
    return dst


def transcribe_file(
    wav: str | Path,
    mode: str = "PUSH_TO_TALK",
    keywords: list[str] | None = None,
    language_bias: list[str] | None = None,
) -> dict:
    """Transcribe a WAV (max 10 min / 32 MB). Returns {"transcript", "turns", "audioDurationMs", ...}."""
    s = get_settings()
    request: dict[str, object] = {"mode": mode, "model": s.meta_asr_model, "audioEncoding": "WAV"}
    if keywords:
        request["keywords"] = keywords
    if language_bias:
        request["languageBias"] = language_bias
    with open(wav, "rb") as f:
        resp = httpx.post(
            f"{s.meta_base_url}/asr/transcribe",
            params={"sessionId": f"file-{uuid.uuid4()}"},
            headers={"Authorization": f"Bearer {s.model_api_key}"},
            files={
                "request": (None, json.dumps(request), "application/json"),
                "audio": (Path(wav).name, f, "audio/wav"),
            },
            timeout=300,
        )
    resp.raise_for_status()
    return resp.json()


async def stream_transcribe(
    audio: AsyncIterator[bytes],
    mode: str = "ENDPOINTING",
    on_event: Callable[[dict], None] | None = None,
    keywords: list[str] | None = None,
) -> list[str]:
    """Stream raw 24 kHz int16 PCM chunks and return the completed transcripts.

    `on_event` sees every server event: `transcript` partials, `speechStart`/`speechEnd`,
    `speechComplete` (the final text of a turn), and `speaker` in DIARIZATION mode.
    """
    s = get_settings()
    handshake: dict[str, object] = {
        "authorization": {"accessToken": f"Bearer {s.model_api_key}"},  # header auth is ignored here
        "audioEncoding": "PCM_24KHZ",
        "model": s.meta_asr_model,
        "mode": mode,
        "partialMode": "CUMULATIVE",
        "emitAudioProgress": False,
    }
    if keywords:
        handshake["keywords"] = keywords

    finals: list[str] = []
    async with websockets.connect(f"{REALTIME_URL}?sessionId=rt-{uuid.uuid4()}", open_timeout=30) as ws:
        await ws.send(json.dumps(handshake))
        ack = json.loads(await ws.recv())
        if "sessionId" not in ack:
            raise RuntimeError(f"ASR handshake failed: {ack}")

        async def receive() -> None:
            async for message in ws:
                if isinstance(message, bytes):
                    continue
                event = json.loads(message)
                if on_event:
                    on_event(event)
                if event.get("type") == "error":
                    raise RuntimeError(event.get("message"))
                if event.get("type") == "speechComplete" or (
                    mode == "PUSH_TO_TALK" and event.get("type") == "transcript" and event.get("final")
                ):
                    finals.append(event["transcript"])

        receiver = asyncio.create_task(receive())
        async for chunk in audio:
            await ws.send(chunk)
        await ws.send(json.dumps({"type": "endStream"}))
        await receiver  # the server closes the socket after the last transcript
    return finals


async def wav_chunks(wav: str | Path, realtime: bool = True) -> AsyncIterator[bytes]:
    """Yield 80 ms PCM frames from a 24 kHz mono WAV, paced like a live mic when `realtime`."""
    with wave.open(str(wav), "rb") as w:
        if (w.getframerate(), w.getnchannels(), w.getsampwidth()) != (RATE, 1, 2):
            raise ValueError("expected 24 kHz mono 16-bit WAV; run to_wav() first")
        pcm = w.readframes(w.getnframes())
    for i in range(0, len(pcm), FRAME_BYTES):
        yield pcm[i : i + FRAME_BYTES]
        if realtime:
            await asyncio.sleep(0.08)
