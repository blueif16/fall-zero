"""Photo or video -> per-piece verdicts, ranked fixes, and scenario videos.

    uv run fall-zero analyze samples/nursery_tall_dresser.png

0. A video is reduced to its sharpest frame; photos are turned upright and downscaled.
1. Muse Spark lists the pieces that could tip and the things standing on each, with noun phrases for SAM.
2. SAM 3.1 outlines all of them at once. Each item is measured in metres against its piece's width.
3. Muse Spark matches each piece to the closest preset (presets.toml), overrides what it can see,
   and weighs the items on top (a TV's weight comes from its measured size instead).
4. The template runs every scenario across the plausible range of sizes and densities,
   so an uncertain estimate gives a range, not a falsely precise verdict.
5. Fixes are re-run through the same physics, and MuJoCo renders before/after videos.
"""

import asyncio
import io
import json
import random
import subprocess
import time
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from contextlib import nullcontext
from dataclasses import asdict, replace
from pathlib import Path
from typing import Literal

import numpy as np
from PIL import Image, ImageFilter, ImageOps
from pydantic import BaseModel
from rich.console import Console

from fall_zero import meta
from fall_zero.furniture import ANCHOR_RATING_N, IN, Dresser, TopItem, presets
from fall_zero.physics import (
    GRAB_FORCE_RANGE_N,
    HAND_HEIGHT_M,
    Scenario,
    elderly_test,
    f2057_tests,
    rocking_threshold_g,
    statics,
    tip_force,
)
from fall_zero.sim import simulate

console = Console()
TEMPLATE_KINDS = {"dresser", "chest_of_drawers", "nightstand"}
SAMPLES = 300
# Under WSL each rendered frame waits ~65 ms on the GPU copy; 4 processes roughly halve the wait
RENDER_WORKERS = 4
VIDEO_SUFFIXES = {".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi"}
MAX_SIDE = 1600  # px; phone photos are 4000+ px and every model call uploads the image


def key_frame(video: Path, n: int = 8) -> tuple[Image.Image, float]:
    """Sharpest of n evenly spaced frames (by edge variance), so a phone pan doesn't hand SAM a
    blurred frame. Returns the frame and its time in seconds."""
    probe = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(video)]
    try:
        duration = float(subprocess.run(probe, capture_output=True, text=True, check=True).stdout)
    except ValueError:  # container without a duration: take the first frame
        duration, n = 0.0, 1
    best: tuple[float, float, Image.Image] | None = None
    for i in range(n):
        t = duration * (i + 0.5) / n
        cmd = ["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", str(video), "-frames:v", "1", "-f", "image2pipe",
               "-vcodec", "png", "-"]  # fmt: skip
        png = subprocess.run(cmd, capture_output=True, check=True).stdout
        if not png:
            continue
        frame = Image.open(io.BytesIO(png)).convert("RGB")
        gray = frame.convert("L")
        gray.thumbnail((800, 800))
        sharpness = float(np.asarray(gray.filter(ImageFilter.FIND_EDGES), dtype=np.float32).var())
        if best is None or sharpness > best[0]:
            best = (sharpness, t, frame)
    if best is None:
        raise ValueError(f"no frames could be read from {video.name}")
    return best[2], best[1]


def still(media: Path, out_dir: Path) -> tuple[Path, float | None]:
    """The image every model call reads: the photo upright and at most MAX_SIDE px, or a video's
    sharpest frame. Returns its path and, for a video, the frame time."""
    at = None
    if media.suffix.lower() in VIDEO_SUFFIXES:
        img, at = key_frame(media)
    else:
        img = ImageOps.exif_transpose(Image.open(media)).convert("RGB")
    img.thumbnail((MAX_SIDE, MAX_SIDE))
    dst = out_dir / "still.jpg"
    img.save(dst, quality=90)
    return dst, at


class OnTop(BaseModel):
    name: str
    sam_concept: str
    kind: Literal["tv", "box", "basket", "lamp", "plant", "books", "decor", "other"]


class Piece(BaseModel):
    name: str
    sam_concept: str  # short noun phrase for SAM, e.g. "white dresser"
    kind: Literal["dresser", "chest_of_drawers", "nightstand", "bookcase", "tv_stand", "wardrobe", "tv", "other"]
    on_top: list[OnTop]  # things standing on it


class Pieces(BaseModel):
    pieces: list[Piece]


class ItemInfo(BaseModel):
    """What Muse Spark judges about an item on top, so the fix can target what would hurt someone."""

    name: str
    short_name: str  # one or two plain words: "plant pot", "bunny", "books"
    material: Literal["ceramic", "glass", "metal", "wood", "plastic", "electronics", "books_or_paper",
                      "fabric_or_plush", "plant_and_soil", "other"]  # fmt: skip
    hard: bool  # would it hurt if it hit a child's head? A plush, cushion or empty basket is not hard
    breakable: bool  # glass or ceramic that breaks into sharp pieces
    kg: float


# A photo shows an item's width and height; its depth and, except for TVs, its weight are guesses
ITEM_DEPTH_M = {"tv": 0.22, "box": 0.35, "basket": 0.30, "lamp": 0.20, "plant": 0.25, "books": 0.22,
                "decor": 0.15, "other": 0.25}  # fmt: skip
ITEM_KG = {"tv": 8.0, "box": 2.0, "basket": 1.5, "lamp": 2.0, "plant": 3.0, "books": 3.0, "decor": 1.0, "other": 2.0}


class Estimate(BaseModel):
    preset: str  # closest key from presets.toml
    drawer_rows: int
    drawer_cols: int
    width_cm: float
    height_cm: float
    depth_cm: float
    depth_is_guess: bool
    base: Literal["plinth", "legs"]
    material: Literal["particleboard", "mdf", "solid_softwood", "solid_hardwood"]
    brand_model: str | None
    size_basis: str  # what the size estimate leans on
    items_on_top: list[ItemInfo]  # one per listed item, in the order given
    nearby_bed_or_crib: str | None  # what sleeps or plays in front of it, if visible


async def segment_all(image: Path, concepts: list[str]) -> list[list[meta.Segment]]:
    """SAM 3.1 on every phrase at once; each call takes a few seconds, so in parallel they cost one."""
    return await asyncio.gather(*(meta.segment_image(image, c, include_confidence=True) for c in concepts))


def identify(image: Path) -> list[Piece]:
    prompt = (
        "List every piece of furniture in this room that could tip over onto a person: dressers, chests, "
        "nightstands, bookcases, TV stands, wardrobes, and TVs standing on their own. For each, give a short "
        "noun phrase that names it uniquely for an image segmentation model (e.g. 'white dresser'). Under "
        "on_top, list every separate thing standing on top of it (a TV, each box or stack of boxes, baskets, "
        "lamps, plants, books), each with its own short noun phrase. Something standing on a piece goes in "
        "that piece's on_top, never in the main list."
    )
    pieces = meta.respond_json(prompt, Pieces, images=[image], effort="low").pieces
    if any(t.kind == "tv" for p in pieces for t in p.on_top):  # a TV listed twice: keep it on its piece
        pieces = [p for p in pieces if p.kind != "tv"]
    return pieces


def _box_text(box) -> str:
    return "({},{})-({},{})".format(*(round(v) for v in box))


def estimate(image: Path, piece: Piece, box: tuple[float, ...], items: list[tuple[OnTop, tuple | None]]) -> Estimate:
    w, h = Image.open(image).size
    x1, y1, x2, y2 = (round(v) for v in box)
    on_top = "; ".join(f"{i + 1}. {t.name}" + (f" at {_box_text(b)}" if b else "") for i, (t, b) in enumerate(items))
    library = "\n".join(
        f"- {key}: {label} ({d.width * 100:.0f} x {d.depth * 100:.0f} x {d.height * 100:.0f} cm, {d.material})"
        for key, (label, d) in presets().items()
    )
    prompt = (
        f"This {w}x{h} photo shows a {piece.name} inside the pixel box ({x1},{y1})-({x2},{y2}). "
        f"Pick the closest preset from this library:\n{library}\n"
        "Then estimate its real dimensions in cm using objects of known size in the room (doors ~203 cm tall, "
        "outlet plates ~11.4 cm, beds and cribs of standard size), its drawer grid (rows x columns), whether "
        "it stands on a solid plinth or on legs, its likely panel material, and the brand or model if "
        "recognizable. Depth is rarely visible: give your best guess and set depth_is_guess. Name any bed or "
        "crib in front of it in two or three plain words ('crib', 'toddler bed'). "
        + (f"For each item standing on top, in this order, as items_on_top: {on_top}. Give a one- or "
           "two-word short_name, its main material, whether it is hard (would it hurt if it fell on a "
           "child's head? plush toys, cushions and fabric are not), whether it breaks into sharp pieces, "
           "and its weight in kg including contents (a pot with soil, a full box)."
           if items else "Nothing stands on top: return an empty items_on_top.")
    )  # fmt: skip
    return meta.respond_json(prompt, Estimate, images=[image], effort="medium")


def on_top_box(piece_box, segments) -> tuple[float, ...] | None:
    """Union of the matches that stand on the piece: centered over it, bottom edge near its top edge.
    (A phrase like "stacked boxes" comes back as one match per box; matches elsewhere in the room drop out.)"""
    px1, py1, px2, py2 = piece_box
    ph = py2 - py1
    hits = [s.box for s in segments
            if px1 <= (s.box[0] + s.box[2]) / 2 <= px2 and py1 - 0.6 * ph <= s.box[3] <= py1 + 0.25 * ph]  # fmt: skip
    if not hits:
        return None
    return (min(b[0] for b in hits), min(b[1] for b in hits), max(b[2] for b in hits), max(b[3] for b in hits))


def tv_kg(width_m: float) -> float:
    """A flat-screen with its stand weighs about 0.0045 kg per square inch of diagonal (32" ~5 kg,
    55" ~14 kg, 65" ~19 kg). The screen is 16:9, so the diagonal is 1.147 x its width."""
    return 0.0045 * (1.147 * width_m / IN) ** 2


def measure_items(d: Dresser, piece_box, items: list[tuple[OnTop, tuple | None]], infos: list[ItemInfo]):
    """Each item's size and place on the top in metres, scaled by the piece's known width. An item
    whose outline sits on another item's (a box on a basket) stands on it."""
    m_per_px = d.width / (piece_box[2] - piece_box[0])
    cx = (piece_box[0] + piece_box[2]) / 2
    placed: list[tuple[int, TopItem, tuple | None]] = []
    # lowest outline first, so supports are placed before what stands on them
    for i, (thing, box) in sorted(enumerate(items), key=lambda t: -(t[1][1][3] if t[1][1] else 0)):
        info = infos[i] if i < len(infos) else None
        kg = info.kg if info and info.kg > 0 else ITEM_KG[thing.kind]
        traits = {"short": info.short_name, "hard": info.hard, "breakable": info.breakable} if info else {}
        depth = min(ITEM_DEPTH_M[thing.kind], d.depth)
        if box is None:
            placed.append((i, TopItem(thing.name, thing.kind, kg, 0.3, depth, 0.3, **traits), None))
            continue
        w = min((box[2] - box[0]) * m_per_px, d.width)
        h = (box[3] - box[1]) * m_per_px
        x = max(-(d.width - w) / 2, min((d.width - w) / 2, ((box[0] + box[2]) / 2 - cx) * m_per_px))
        z = 0.0
        for _, below, b in placed:
            if b is None:
                continue
            overlap = min(box[2], b[2]) - max(box[0], b[0])
            above = box[3] < b[3] - 0.25 * (b[3] - b[1])  # its bottom is well above the other's
            if overlap > 0.3 * min(box[2] - box[0], b[2] - b[0]) and above:
                z = max(z, below.z + below.height)
                h = min(h, max((b[1] - box[1]) * m_per_px, 0.05))  # only the part above its support
        if thing.kind == "tv":
            kg = tv_kg(w)
        placed.append((i, TopItem(thing.name, thing.kind, kg, w, depth, h, x, 0.0, z, **traits), box))
    return separate(d, [item for _, item, _ in sorted(placed, key=lambda p: p[0])])


def separate(d: Dresser, items: list[TopItem]) -> list[TopItem]:
    """Outlines measured from a photo overlap a little; solid bodies can't. Push items standing side by
    side apart across the top, and if the top is too narrow, stand the later one in front of the other."""
    items = list(items)
    for i in range(len(items)):
        for j in range(i):
            a, b = items[j], items[i]
            if a.z + a.height <= b.z or b.z + b.height <= a.z:
                continue  # one stands on the other
            overlap = (a.width + b.width) / 2 - abs(a.x - b.x) + 0.01
            if overlap <= 0:
                continue
            side = 1 if b.x >= a.x else -1
            limit_a, limit_b = (d.width - a.width) / 2, (d.width - b.width) / 2
            a = replace(a, x=max(-limit_a, min(limit_a, a.x - side * overlap / 2)))
            b = replace(b, x=max(-limit_b, min(limit_b, b.x + side * overlap / 2)))
            if (a.width + b.width) / 2 - abs(a.x - b.x) > 0:  # no room side by side: one behind the other
                da, db = min(a.depth, d.depth / 2), min(b.depth, d.depth / 2)
                a, b = replace(a, depth=da, y=-(d.depth - da) / 2), replace(b, depth=db, y=(d.depth - db) / 2)
            items[j], items[i] = a, b
    return items


def to_template(e: Estimate) -> Dresser:
    """The preset, overridden by what the photo shows. A guessed depth keeps the preset's."""
    library = presets()
    if e.preset not in library:  # fall back to the preset nearest in size
        e.preset = min(library, key=lambda k: abs(library[k][1].height * 100 - e.height_cm)
                       + abs(library[k][1].width * 100 - e.width_cm))  # fmt: skip
    base = library[e.preset][1]
    return replace(
        base,
        width=e.width_cm / 100,
        height=e.height_cm / 100,
        depth=base.depth if e.depth_is_guess else e.depth_cm / 100,
        rows=max(1, e.drawer_rows),
        cols=max(1, e.drawer_cols),
        base=e.base,
        material=e.material,
    )


def plausible(d: Dresser, depth: float, size: float = 0.10, n: int = SAMPLES, seed: int = 0) -> list[Dresser]:
    """Width and height within ±`size`, depth within ±`depth`, density ±15%, top items ±30%.
    From a photo: size 0.10, depth 0.15 when guessed (0.05 when visible)."""
    rng = random.Random(seed)
    out = []
    for _ in range(n):
        w, h, dp = (rng.uniform(1 - size, 1 + size), rng.uniform(1 - size, 1 + size),
                    rng.uniform(1 - depth, 1 + depth))  # fmt: skip
        k, top = rng.uniform(0.85, 1.15), rng.uniform(0.7, 1.3)
        items = tuple(replace(i, mass=i.mass * top) for i in d.top_items)
        out.append(replace(d, width=d.width * w, height=d.height * h, depth=d.depth * dp, density_scale=k,
                           top_items=items))  # fmt: skip
    return out


def verdict(tip_share: float) -> str:
    return "pass" if tip_share <= 0.05 else "fail" if tip_share >= 0.95 else "uncertain"


def child_verdicts(variants: list[Dresser], **kw) -> dict[str, dict]:
    out = {}
    for i, s in enumerate(f2057_tests(variants[0], **kw)):
        results = [statics(v, f2057_tests(v, **kw)[i]) for v in variants]
        margins = [r.margin for r in results]
        share = sum(r.tips for r in results) / len(results)  # not margin < 1: a held strap balances exactly
        out[s.key] = {"title": s.title, "verdict": verdict(share), "tip_share": share,
                      "margin_range": [min(margins), max(margins)], "standard": s.standard}  # fmt: skip
    return out


def elderly_verdict(variants: list[Dresser]) -> dict:
    forces = [tip_force(v, min(HAND_HEIGHT_M, v.height), fill=True) for v in variants]
    lo, hi = GRAB_FORCE_RANGE_N
    v = "fail" if max(forces) < lo else "pass" if min(forces) > hi else "uncertain"
    return {"title": "Adult grabbing it for balance", "verdict": v, "tip_force_N": [min(forces), max(forces)],
            "assumption": elderly_test(variants[0]).assumption}  # fmt: skip


def fixes(d: Dresser) -> list[dict]:
    """Each fix re-runs the physics on the nominal estimate."""
    base = {s.key: statics(d, s).tips for s in f2057_tests(d)}
    failing = [k for k, tipped in base.items() if tipped]
    out = []

    anchored = [statics(d, s) for s in f2057_tests(d, anchored=True) + [elderly_test(d, anchored=True)]]
    need = max(st.anchor_needed_N for st in anchored)
    out.append({"fix": "Anchor it to the wall with an anti-tip strap (ASTM F3096, under $20)",
                "fixes": failing, "detail": f"worst case loads the strap to {need:.0f} N of its "
                f"{ANCHOR_RATING_N:.0f} N rating", "works": need <= ANCHOR_RATING_N})  # fmt: skip

    one = frozenset({d.top_drawer().index})
    locked = {s.key: statics(d, s).tips for s in f2057_tests(d, only_open=one)}
    out.append({"fix": "Fit drawer locks so only one drawer opens at a time",
                "fixes": [k for k in failing if not locked[k]], "works": not any(locked.values())})  # fmt: skip

    if d.top_items:
        cleared = replace(d, top_items=())
        before, after = rocking_threshold_g(d), rocking_threshold_g(cleared)
        out.append({"fix": f"Move the {d.top_load_kg:.0f} kg on top somewhere low",
                    "fixes": [], "works": True,
                    "detail": f"shaking needed to start it rocking rises from {before:.2f} g to {after:.2f} g; "
                    "the items themselves can no longer fall"})  # fmt: skip

    fall = d.height + 0.3
    out.append({"fix": f"Keep beds, cribs and play areas more than {fall:.1f} m from its front",
                "fixes": [], "works": True,
                "detail": f"if it tips, its top lands about {d.height:.1f} m out"})  # fmt: skip
    return sorted(out, key=lambda f: (-len(f["fixes"]), not f["works"]))


def analyze(
    media: Path, out_dir: Path | None = None, video: bool = True, on_step: Callable[[str], None] | None = None
) -> dict:
    """`on_step` receives each progress message instead of the terminal spinner and the printed report."""
    out_dir = out_dir or Path("out") / media.stem
    out_dir.mkdir(parents=True, exist_ok=True)
    start = time.perf_counter()

    def status(msg: str):
        if on_step:
            on_step(msg)
            return nullcontext()
        return console.status(msg)

    with status("Picking the sharpest frame" if media.suffix.lower() in VIDEO_SUFFIXES else "Looking at the photo"):
        image, frame_at = still(media, out_dir)
    report: dict = {"image": str(image), "size": Image.open(image).size, "frame_at_s": frame_at, "pieces": [],
                    "seconds": {}}  # fmt: skip
    secs = report["seconds"]

    def lap(stage: str, t0: float) -> None:
        secs[stage] = secs.get(stage, 0.0) + time.perf_counter() - t0

    t0 = time.perf_counter()
    with status("Finding furniture that could tip · Muse Spark"):
        pieces = identify(image)
    lap("identify", t0)

    t0 = time.perf_counter()
    things = [t for p in pieces for t in p.on_top]
    concepts = [p.sam_concept for p in pieces] + [t.sam_concept for t in things]
    with status(f"Outlining {len(concepts)} object{'s' * (len(concepts) != 1)} · SAM 3.1"):
        found = asyncio.run(segment_all(image, concepts))
    lap("segment", t0)

    jobs, thing_segments = [], iter(found[len(pieces) :])
    for piece, segments in zip(pieces, found, strict=False):
        entry: dict = {"piece": piece.model_dump()}
        report["pieces"].append(entry)
        own = [next(thing_segments) for _ in piece.on_top]
        if piece.kind not in TEMPLATE_KINDS:
            entry["status"] = "cannot determine: no template for this kind yet"
            continue
        if not segments:
            entry["status"] = "cannot determine: SAM found no match"
            continue
        box = max(segments, key=lambda s: (s.box[2] - s.box[0]) * (s.box[3] - s.box[1])).box
        entry["box"] = box
        items = [(t, on_top_box(box, segs)) for t, segs in zip(piece.on_top, own, strict=True)]
        jobs.append((entry, piece, box, items))

    t0 = time.perf_counter()
    names = jobs[0][1].name if len(jobs) == 1 else f"{len(jobs)} pieces"
    with status(f"Measuring the {names} · Muse Spark"), ThreadPoolExecutor() as pool:
        estimates = list(pool.map(lambda j: estimate(image, *j[1:]), jobs))
    lap("estimate", t0)

    t0 = time.perf_counter()
    if jobs and on_step:
        on_step(f"Testing a climbing child, an adult and an earthquake · physics, {SAMPLES} sizes")
    for (entry, _, box, items), est in zip(jobs, estimates, strict=True):
        d = to_template(est)
        d = replace(d, top_items=tuple(measure_items(d, box, items, est.items_on_top)))
        variants = plausible(d, depth=0.15 if est.depth_is_guess else 0.05)
        entry |= {
            "estimate": est.model_dump(),
            "template": {k: v for k, v in asdict(d).items() if k != "notes"},
            "items": [
                {"name": t.name, "kind": t.kind, "box": b, "kg": item.mass}
                for (t, b), item in zip(items, d.top_items, strict=True)
            ],  # fmt: skip
            "mass_kg": {"empty": d.mass(), "with_clothes": d.mass(fill=True)},
            "child": child_verdicts(variants),
            "elderly": elderly_verdict(variants),
            "earthquake": {
                "rocking_starts_at_g": rocking_threshold_g(d),
                "note": "the cards' verdict comes from simulated earthquakes (assess.quakes)",
            },  # fmt: skip
            "pull_test_prediction_N": tip_force(d, d.height),
            "fixes": fixes(d),
            "status": "analyzed",
            "_template": d,
        }
    lap("physics", t0)

    # Verdicts and fixes first; videos are the slow part
    report["seconds"]["verdict"] = time.perf_counter() - start
    if not on_step:
        print_report(report)
    if video:
        t0 = time.perf_counter()
        analyzed = [e for e in report["pieces"] if e["status"] == "analyzed"]
        with status(f"Rendering videos for {len(analyzed)} piece(s) · MuJoCo"):
            jobs = [(e["_template"], e["piece"]["sam_concept"]) for e in analyzed]
            for entry, videos in zip(analyzed, render_videos(jobs, out_dir), strict=True):
                entry["videos"] = videos
        lap("videos", t0)
        report["seconds"]["with_videos"] = time.perf_counter() - start
    for entry in report["pieces"]:
        entry.pop("_template", None)
    (out_dir / "report.json").write_text(json.dumps(report, indent=2, default=float))
    if not on_step:
        stages = ", ".join(f"{k} {v:.1f}s" for k, v in secs.items())
        console.print(f"\nReport: {out_dir / 'report.json'}\nTiming: {stages}")
    return report


def _render(job: tuple[Dresser, Scenario, Path]):
    return simulate(*job[:2], video=job[2])


def render_videos(pieces: list[tuple[Dresser, str]], out_dir: Path) -> list[dict]:
    """Every scenario as-is, plus the anchored version of anything statics says tips (the
    simulation agrees with statics in every tested case), all rendered in parallel."""
    jobs, slots = [], []
    for i, (d, name) in enumerate(pieces):
        for s in f2057_tests(d) + [elderly_test(d)]:
            stem = f"{name}_{s.key}".replace(" ", "_")
            jobs.append((d, s, out_dir / f"{stem}.mp4"))
            slots.append((i, s.key, "as_is"))
            if statics(d, s).tips:
                jobs.append((d, replace(s, anchored=True), out_dir / f"{stem}_anchored.mp4"))
                slots.append((i, s.key, "anchored"))
    with ProcessPoolExecutor(RENDER_WORKERS) as pool:
        results = list(pool.map(_render, jobs))
    videos: list[dict] = [{} for _ in pieces]
    for (i, key, version), r in zip(slots, results, strict=True):
        clip = videos[i].setdefault(key, {})
        clip[version] = str(r.video)
        clip["tipped" if version == "as_is" else "anchored_tipped"] = r.tipped
    return videos


def print_report(report: dict) -> None:
    colors = {"pass": "green", "fail": "red", "uncertain": "yellow"}
    for p in report["pieces"]:
        console.rule(p["piece"]["name"])
        if p["status"] != "analyzed":
            console.print(f"[yellow]{p['status']}[/]")
            continue
        e, t = p["estimate"], p["template"]
        console.print(
            f"Preset {e['preset']}: {t['width'] * 100:.0f} x {t['depth'] * 100:.0f}"
            f"{' (preset depth)' if e['depth_is_guess'] else ''} x {t['height'] * 100:.0f} cm, "
            f"{t['rows']}x{t['cols']} drawers, {t['material']}, ~{p['mass_kg']['empty']:.0f} kg empty "
            f"({p['mass_kg']['with_clothes']:.0f} kg with clothes). Size from: {e['size_basis']}"
        )
        for r in p["child"].values():
            c = colors[r["verdict"]]
            lo, hi = r["margin_range"]
            console.print(f"  [{c}]{r['verdict'].upper():9s}[/] {r['title']} (margin {lo:.2f}–{hi:.2f}; <1 tips)")
        el = p["elderly"]
        console.print(
            f"  [{colors[el['verdict']]}]{el['verdict'].upper():9s}[/] {el['title']}: tips at "
            f"{el['tip_force_N'][0]:.0f}–{el['tip_force_N'][1]:.0f} N pulled at hand height (assumption: "
            f"{el['assumption']})"
        )
        console.print(f"  Earthquake: starts rocking at {p['earthquake']['rocking_starts_at_g']:.2f} g floor shaking")
        console.print("  Fixes:")
        for f in p["fixes"]:
            fixed = f" fixes {', '.join(f['fixes'])}" if f["fixes"] else ""
            console.print(f"   - {f['fix']}{fixed}{'; ' + f['detail'] if f.get('detail') else ''}")
