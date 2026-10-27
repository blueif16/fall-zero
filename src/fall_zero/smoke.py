"""Hit every service once and report which ones work. Unconfigured providers are skipped.

uv run fall-zero smoke                  # everything
uv run fall-zero smoke meta-sam glimmer # just these checks
"""

import asyncio
import subprocess
import time
from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel
from rich.console import Console
from rich.table import Table

from fall_zero import meta, voice
from fall_zero.clients import chat, providers

OUT = Path("out")
IMAGE = OUT / "smoke.png"
MESH = OUT / "smoke.glb"
WAV = OUT / "smoke.wav"
SPOKEN = "Testing the Muse Voice Transcribe model for our hackathon."

console = Console()


class Skip(Exception):
    pass


def _needs(provider: str) -> None:
    if not providers()[provider].configured:
        raise Skip(f"{provider} not configured in .env")


def _needs_image() -> None:
    if not IMAGE.exists():
        raise Skip("needs meta-image to run first")


def _needs_wav() -> None:
    if not WAV.exists():
        OUT.mkdir(exist_ok=True)
        subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-f",
                "lavfi",
                "-i",
                f"flite=text='{SPOKEN}':voice=slt",
                "-ac",
                "1",
                "-ar",
                "24000",
                "-c:a",
                "pcm_s16le",
                "-map_metadata",
                "-1",
                str(WAV),
            ],
            check=True,
        )


def check_spark() -> str:
    _needs("meta")
    return meta.respond("Reply with exactly: ok", effort="minimal").output_text


def check_wonder() -> str:
    _needs("meta")
    return meta.respond("Reply with exactly: ok", model="muse-wonder-1.0", effort="minimal").output_text


def check_image() -> str:
    _needs("meta")
    OUT.mkdir(exist_ok=True)
    IMAGE.write_bytes(meta.generate_image("a small white three-drawer dresser in a toddler's bedroom, phone photo"))
    return f"saved {IMAGE}"


def check_vision() -> str:
    _needs("meta")
    _needs_image()
    return meta.respond("List the furniture in this image, comma-separated.", images=[IMAGE], effort="low").output_text


class ProductSpec(BaseModel):
    product: str
    weight_kg: float | None
    height_cm: float | None
    recalled: bool
    source_url: str | None


def check_grounded_json() -> str:
    _needs("meta")
    spec = meta.respond_json(
        "Look up the IKEA MALM 6-drawer dresser (the one recalled in 2016): its shipping or product weight, "
        "its height, and whether it was recalled. Use web search.",
        ProductSpec,
        web_search=True,
        effort="low",
    )
    return spec.model_dump_json()


def check_sam() -> str:
    _needs("meta")
    _needs_image()
    segments = asyncio.run(meta.segment_image(IMAGE, "dresser"))
    if not segments:
        return "0 matches (valid, but expected a dresser)"
    box = ", ".join(f"{v:.0f}" for v in segments[0].box)
    return f"{len(segments)} match(es); first box [{box}]"


def check_voice_file() -> str:
    _needs("meta")
    _needs_wav()
    return voice.transcribe_file(WAV)["transcript"]


def check_voice_realtime() -> str:
    _needs("meta")
    _needs_wav()
    return " | ".join(asyncio.run(voice.stream_transcribe(voice.wav_chunks(WAV), mode="ENDPOINTING")))


def check_sam3d() -> str:
    import modal

    from fall_zero.reconstruct import APP_NAME, CLS_NAME, reconstruct

    _needs("meta")
    _needs_image()
    try:
        modal.Cls.from_name(APP_NAME, CLS_NAME).hydrate()
    except Exception as e:
        raise Skip(f"deploy modal_apps/sam3d.py first ({type(e).__name__})") from None
    segments = asyncio.run(meta.segment_image(IMAGE, "dresser"))
    if not segments:
        raise Skip("SAM found no dresser to reconstruct")
    out = reconstruct(IMAGE, segments[0])
    MESH.write_bytes(out["glb"])
    return f"saved {MESH} ({len(out['glb']) // 1024} KB); scale={out['scale']}"


def check_mujoco() -> str:
    """A 0.5 x 0.4 x 1.2 m, 30 kg box pushed near the top for 1 s with 120 N must tip.

    Statics says it lifts at 30 * 9.81 * 0.2 / 1.15 = 51 N and slides only above 0.8 * 294 = 235 N.
    """
    import mujoco

    xml = """
    <mujoco>
      <option timestep="0.002"/>
      <worldbody>
        <geom type="plane" size="5 5 0.1" friction="0.8"/>
        <body name="dresser" pos="0 0 0.6">
          <freejoint/>
          <geom type="box" size="0.25 0.2 0.6" mass="30" friction="0.8"/>
        </body>
      </worldbody>
    </mujoco>"""
    model = mujoco.MjModel.from_xml_string(xml)
    data = mujoco.MjData(model)
    body = model.body("dresser").id
    for step in range(1500):  # 3 s: push for the first 1 s, then let it fall
        data.qfrc_applied[:] = 0
        if step < 500:
            top = data.xpos[body] + data.xmat[body].reshape(3, 3) @ [0, 0, 0.55]  # moves with the box
            mujoco.mj_applyFT(model, data, [0, 120, 0], [0, 0, 0], top, body, data.qfrc_applied)
        mujoco.mj_step(model, data)
    tilt = 1 - 2 * (data.xquat[body][1] ** 2 + data.xquat[body][2] ** 2)  # cos of angle from vertical
    if tilt > 0.5:
        raise AssertionError(f"box should have tipped; cos(tilt)={tilt:.2f}")
    return f"mujoco {mujoco.__version__}: box tipped (cos tilt {tilt:.2f})"


# Muse Spark Open reasons at xhigh by default; keep the smoke test cheap.
_OPEN_WEIGHT_KWARGS = {
    "baseten": {"reasoning_effort": "low"},
    "fireworks": {"reasoning_effort": "low"},
    "modal": {"reasoning_effort": "low"},
    "glimmer": {},  # Glimmer takes "Reasoning strength: low" in the system prompt instead
}


def _open_weights(provider: str) -> Callable[[], str]:
    def check() -> str:
        _needs(provider)
        messages = [{"role": "user", "content": "Reply with exactly: ok"}]
        if provider == "glimmer":
            messages.insert(0, {"role": "system", "content": "Reasoning strength: low"})
        return chat(messages, provider=provider, max_tokens=4096, **_OPEN_WEIGHT_KWARGS[provider])

    return check


CHECKS: dict[str, tuple[str, Callable[[], str]]] = {
    "meta-spark": ("Muse Spark 1.3 (Meta API)", check_spark),
    "meta-wonder": ("Muse Wonder 1.0 (Meta API)", check_wonder),
    "meta-image": ("Muse Image 1.0 (Meta API)", check_image),
    "meta-vision": ("Muse Spark vision (Meta API)", check_vision),
    "meta-search-json": ("Muse Spark web search + JSON (Meta API)", check_grounded_json),
    "meta-sam": ("SAM 3.1 (Meta API)", check_sam),
    "meta-voice-file": ("Voice Transcribe, file (Meta API)", check_voice_file),
    "meta-voice-realtime": ("Voice Transcribe, realtime (Meta API)", check_voice_realtime),
    "baseten": ("Muse Spark Open (Baseten)", _open_weights("baseten")),
    "fireworks": ("Muse Spark Open (Fireworks)", _open_weights("fireworks")),
    "modal": ("Muse Spark Open (Modal endpoint)", _open_weights("modal")),
    "glimmer": ("Muse Glimmer 30B (self-hosted on Modal)", _open_weights("glimmer")),
    "sam3d": ("SAM 3D Objects (self-hosted on Modal)", check_sam3d),
    "mujoco": ("MuJoCo physics (local)", check_mujoco),
}


def run(names: list[str]) -> int:
    unknown = set(names) - CHECKS.keys()
    if unknown:
        console.print(f"[red]Unknown checks: {', '.join(sorted(unknown))}[/]. Choose from: {', '.join(CHECKS)}")
        return 2

    table = Table("check", "service", "result", "time", "detail")
    failed = 0
    for name in names or CHECKS:
        label, fn = CHECKS[name]
        start = time.perf_counter()
        with console.status(f"{label}..."):
            try:
                status, detail = "[green]pass[/]", fn()
            except Skip as e:
                status, detail = "[yellow]skip[/]", str(e)
            except Exception as e:  # report and keep going
                status, detail = "[red]FAIL[/]", f"{type(e).__name__}: {e}"
                failed += 1
        elapsed = f"{time.perf_counter() - start:.1f}s"
        table.add_row(name, label, status, elapsed, " ".join(str(detail).split())[:120])
    console.print(table)
    return 1 if failed else 0
