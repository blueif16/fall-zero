"""Photo or video -> per-piece verdicts, ranked fixes, and scenario videos.

    uv run fall-zero analyze samples/nursery_tall_dresser.png

0. A video is reduced to its sharpest frame; photos are turned upright and downscaled.
1. Muse Spark lists the pieces that could tip and the things standing on each (on top or on an open
   shelf), with noun phrases for SAM.
2. SAM 3.1 outlines all of them at once while Muse Spark matches each piece to the closest worked
   example (skill/catalog/examples.toml), overrides what it can see, and weighs the things on it.
3. Each thing is measured in metres against its piece's outline (a TV's weight comes from that size),
   and a thing on a shelf is set on the shelf its outline's bottom edge is nearest to.
4. The template runs every scenario across the plausible range of sizes and densities,
   so an uncertain estimate gives a range, not a falsely precise verdict.
5. Fixes are re-run through the same physics, and MuJoCo renders before/after videos.
"""

import asyncio
import io
import json
import logging
import random
import re
import subprocess
import time
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from contextlib import nullcontext
from dataclasses import asdict, replace
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter, ImageOps
from pydantic import ValidationError
from rich.console import Console

from fall_zero import knowledge, meta
from fall_zero.clients import NotConfigured
from fall_zero.furniture import ANCHOR_RATING_N, IN, Case, TopItem, Zone, examples, with_mass
from fall_zero.knowledge import CaseSpec, ItemSpec, Judgment, Spotted, Thing, zones_text
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
log = logging.getLogger(__name__)
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


# A photo shows an item's width and height; when the model gives no depth or weight, these stand in
ITEM_DEPTH_M, ITEM_KG = 0.25, 2.0
RUNNER_FRICTION = {"metal_slides": 0.05, "wood_runners": 0.25}  # see Case.runner_friction


SAM_TRIES = 2  # a call that fails (a mask payload that can't be decoded, a dropped stream) is tried once more


async def segment_all(image: Path, concepts: list[str], segment=meta.segment_image) -> list[list[meta.Segment]]:
    """SAM 3.1 on every phrase at once; each call takes a few seconds, so in parallel they cost one. A phrase
    whose call fails twice comes back with no matches: that piece or thing goes without an outline, and the
    photo still gets its cards."""

    async def one(concept: str) -> list[meta.Segment]:
        for attempt in range(1, SAM_TRIES + 1):
            try:
                return await segment(image, concept, include_confidence=True)
            except NotConfigured:
                raise
            except Exception as exc:
                log.warning("SAM 3.1 failed on %r (try %d of %d): %s: %s", concept, attempt, SAM_TRIES,
                            type(exc).__name__, exc)  # fmt: skip
        return []

    return await asyncio.gather(*(one(c) for c in concepts))


def _iou(a, b) -> float:
    w = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    h = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - w * h
    return w * h / union if union else 0.0


def assign_outlines(per_piece: list[list[meta.Segment]]) -> list[meta.Segment | None]:
    """One outline per piece. Each takes its largest match, but two pieces can't share one: a phrase
    like "small wooden cabinet" also matches the big hutch beside it, so the piece with fewer matches
    (then the surer one) chooses first and the other takes its next match. A piece left with only taken
    matches gets none."""
    chosen: dict[int, meta.Segment] = {}

    def surest(i: int) -> float:
        return max((s.confidence or 0.0 for s in per_piece[i]), default=0.0)

    def area(s: meta.Segment) -> float:
        return (s.box[2] - s.box[0]) * (s.box[3] - s.box[1])

    for i in sorted(range(len(per_piece)), key=lambda i: (len(per_piece[i]), -surest(i))):
        free = [s for s in sorted(per_piece[i], key=area, reverse=True)
                if all(_iou(s.box, c.box) < 0.6 for c in chosen.values())]  # fmt: skip
        if free:
            chosen[i] = free[0]
    return [chosen.get(i) for i in range(len(per_piece))]


def _simplify(points: np.ndarray, tolerance: float) -> np.ndarray:
    """Douglas-Peucker: the fewest points of an open line that stay within `tolerance` of it."""
    keep = np.zeros(len(points), bool)
    keep[[0, -1]] = True
    stack = [(0, len(points) - 1)]
    while stack:
        a, b = stack.pop()
        if b - a < 2:
            continue
        chord, rel = points[b] - points[a], points[a + 1 : b] - points[a]
        length = np.hypot(*chord)
        dist = np.abs(chord[0] * rel[:, 1] - chord[1] * rel[:, 0]) / length if length else np.hypot(*rel.T)
        i = int(np.argmax(dist))
        if dist[i] > tolerance:
            keep[a + 1 + i] = True
            stack += [(a, a + 1 + i), (a + 1 + i, b)]
    return points[keep]


def outline(segments: list[meta.Segment], tolerance: float = 1.5) -> str | None:
    """SAM's masks as one light SVG path in photo pixels, for the page to draw the object's real shape.
    SAM's own path steps along every pixel edge (76 kB for a bookcase); each ring is simplified to
    within `tolerance` px. Specks and holes (the books inside a bookcase's frame) are dropped, so the
    shape reads as one solid silhouette."""
    rings = []
    for seg in segments:
        b, raster = seg.mask.bounds, seg.mask.mask
        scale = ((b.right - b.left) / raster.width, (b.bottom - b.top) / raster.height)
        own = []
        for ring in seg.svg_path.split("M")[1:]:
            xy = np.array(re.findall(r"-?\d+(?:\.\d+)?", ring), float).reshape(-1, 2) * scale + (b.left, b.top)
            area = abs(np.dot(xy[:, 0], np.roll(xy[:, 1], 1)) - np.dot(xy[:, 1], np.roll(xy[:, 0], 1))) / 2
            if len(xy) >= 8 and area >= 0.002 * (b.right - b.left) * (b.bottom - b.top):
                own.append(xy)
        for xy in own:
            lo, hi = xy.min(0), xy.max(0)
            if any((o.min(0) < lo).all() and (o.max(0) > hi).all() for o in own if o is not xy):
                continue  # inside another ring: a hole
            far = int(np.argmax(np.hypot(*(xy - xy[0]).T)))  # a closed ring simplifies as two halves
            back = _simplify(np.vstack([xy[far:], xy[:1]]), tolerance)[1:-1]
            pts = np.vstack([_simplify(xy[: far + 1], tolerance), back])
            rings.append("M" + "L".join(f"{x:.0f} {y:.0f}" for x, y in pts) + "Z")
    return "".join(rings) or None


def read_piece(image: Path, piece: Spotted, room: str, people: str) -> CaseSpec | Judgment:
    """What the engine builds, or a verdict from the references. A piece the survey thought
    buildable but whose description doesn't hold together is judged instead."""
    if piece.engine == "case":
        try:
            spec = knowledge.describe(image, piece, room)
            if spec.zones and spec.width_cm > 0 and spec.height_cm > 0:
                return spec
        except (ValidationError, ValueError):
            pass
    return knowledge.judge(image, piece, room, people)


def on_top(piece_box, segments: list[meta.Segment]) -> list[meta.Segment]:
    """The matches that stand on the piece: centered over it, bottom edge near its top edge. (A phrase
    like "stacked boxes" comes back as one match per box; matches elsewhere in the room drop out.)"""
    px1, py1, px2, py2 = piece_box
    ph = py2 - py1
    return [s for s in segments
            if px1 <= (s.box[0] + s.box[2]) / 2 <= px2 and py1 - 0.6 * ph <= s.box[3] <= py1 + 0.25 * ph]  # fmt: skip


def on_shelf(piece_box, segments: list[meta.Segment]) -> list[meta.Segment]:
    """The match that stands on one of the piece's shelves: the surest one inside its outline, centered
    across it and its bottom edge within it. Not the piece itself, and only one: a plant on a shelf is one
    thing, and other matches of the phrase sit on other shelves or elsewhere in the room."""
    px1, py1, px2, py2 = piece_box
    inside = [s for s in segments if px1 <= (s.box[0] + s.box[2]) / 2 <= px2
              and py1 < s.box[3] <= py2 + 0.02 * (py2 - py1) and _iou(s.box, piece_box) < 0.5]  # fmt: skip
    return sorted(inside, key=lambda s: -(s.confidence or 0.0))[:1]


def union_box(segments: list[meta.Segment]) -> tuple[float, ...] | None:
    if not segments:
        return None
    boxes = [s.box for s in segments]
    return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))


def tv_kg(width_m: float) -> float:
    """A flat-screen with its stand weighs about 0.0045 kg per square inch of diagonal (32" ~5 kg,
    55" ~14 kg, 65" ~19 kg). The screen is 16:9, so the diagonal is 1.147 x its width."""
    return 0.0045 * (1.147 * width_m / IN) ** 2


def measure_items(d: Case, piece_box, items: list[tuple[Thing, tuple | None]], infos: list[ItemSpec]):
    """Each thing's size and place on the piece in metres, scaled by the piece's outline: across by its
    known width, up by its height. A thing on a shelf stands on the open shelf nearest its outline's bottom
    edge (or the one the describe step named, without an outline). On top, a thing whose outline sits on
    another's (a box on a basket) stands on it."""
    if piece_box is None:  # no outline of the piece: nothing to measure against
        items = [(t, None) for t, _ in items]
        piece_box = (0, 0, 1, 1)
    m_per_px = d.width / (piece_box[2] - piece_box[0])
    up_per_px = d.height / (piece_box[3] - piece_box[1])
    cx = (piece_box[0] + piece_box[2]) / 2
    levels = d.shelf_levels(("open",))
    placed: list[tuple[int, TopItem, tuple | None]] = []
    # lowest outline first, so supports are placed before what stands on them
    for i, (thing, box) in sorted(enumerate(items), key=lambda t: -(t[1][1][3] if t[1][1] else 0)):
        info = infos[i] if i < len(infos) else None
        kg = info.kg if info and info.kg > 0 else ITEM_KG
        traits = {"short": info.short_name, "hard": info.hard, "breakable": info.breakable,
                  "tempting": info.tempting} if info else {}  # fmt: skip
        shape = info.shape if info else "block"
        depth = min(info.depth_cm / 100 if info and info.depth_cm > 0 else ITEM_DEPTH_M, d.depth)
        shelf = None
        if levels and (thing.where == "shelf" or (info and info.shelf_from_top > 0)):
            if box is not None:  # the surface its bottom edge is nearest to, the top included
                above_floor = (piece_box[3] - box[3]) * up_per_px
                k = min(range(len(levels) + 1), key=lambda k: abs([*levels, d.height][k] - above_floor))
                shelf = k if k < len(levels) else None
            else:
                shelf = max(0, len(levels) - max(1, info.shelf_from_top if info else 1))
        if box is None:
            placed.append((i, TopItem(thing.name, shape, kg, 0.3, depth, 0.3, shelf=shelf, **traits), None))
            continue
        w = min((box[2] - box[0]) * m_per_px, d.width)
        h = (box[3] - box[1]) * (m_per_px if shelf is None else up_per_px)
        # the photo looks at the front (+y), along -y: the photo's left is +x
        x = max(-(d.width - w) / 2, min((d.width - w) / 2, (cx - (box[0] + box[2]) / 2) * m_per_px))
        if shelf is not None:
            kg = tv_kg(w) if shape == "screen" else kg
            placed.append((i, TopItem(thing.name, shape, kg, w, depth, h, x, shelf=shelf, **traits), box))
            continue
        z = 0.0
        for _, below, b in placed:
            if b is None or below.shelf is not None:
                continue
            overlap = min(box[2], b[2]) - max(box[0], b[0])
            above = box[3] < b[3] - 0.25 * (b[3] - b[1])  # its bottom is well above the other's
            if overlap > 0.3 * min(box[2] - box[0], b[2] - b[0]) and above:
                z = max(z, below.z + below.height)
                h = min(h, max((b[1] - box[1]) * m_per_px, 0.05))  # only the part above its support
        if shape == "screen":
            kg = tv_kg(w)
        placed.append((i, TopItem(thing.name, shape, kg, w, depth, h, x, 0.0, z, **traits), box))
    return separate(d, [item for _, item, _ in sorted(placed, key=lambda p: p[0])])


def separate(d: Case, items: list[TopItem]) -> list[TopItem]:
    """Outlines measured from a photo overlap a little; solid bodies can't. Push items standing side by
    side on the same surface apart across it, and if the top is too narrow, stand the later one in front
    of the other. A shelf keeps one row (its things stand at its front edge): the later one narrows."""
    items = list(items)
    for i in range(len(items)):
        for j in range(i):
            a, b = items[j], items[i]
            if a.shelf != b.shelf or a.z + a.height <= b.z or b.z + b.height <= a.z:
                continue  # on different surfaces, or one stands on the other
            overlap = (a.width + b.width) / 2 - abs(a.x - b.x) + 0.01
            if overlap <= 0:
                continue
            side = 1 if b.x >= a.x else -1
            limit_a, limit_b = (d.width - a.width) / 2, (d.width - b.width) / 2
            a = replace(a, x=max(-limit_a, min(limit_a, a.x - side * overlap / 2)))
            b = replace(b, x=max(-limit_b, min(limit_b, b.x + side * overlap / 2)))
            if (rest := (a.width + b.width) / 2 - abs(a.x - b.x)) > 0:  # no room side by side
                if a.shelf is not None:
                    b = replace(b, width=max(0.03, b.width - rest - 0.01), x=b.x + side * (rest + 0.01) / 2)
                else:  # one behind the other
                    da, db = min(a.depth, d.depth / 2), min(b.depth, d.depth / 2)
                    a, b = replace(a, depth=da, y=-(d.depth - da) / 2), replace(b, depth=db, y=(d.depth - db) / 2)
            items[j], items[i] = a, b
    return items


def to_template(e: CaseSpec) -> Case:
    """The closest worked example, changed to what the photo shows. A guessed depth keeps the
    example's; a known weight scales the panels to match it, and otherwise the example's own
    calibration to its real weight stays."""
    library = examples()
    if e.example not in library:  # none fits: start from the example nearest in size
        e.example = min(library, key=lambda k: abs(library[k][1].height * 100 - e.height_cm)
                        + abs(library[k][1].width * 100 - e.width_cm))  # fmt: skip
    base = library[e.example][1]
    zones = tuple(Zone(z.kind, max(z.share, 0.05), max(z.rows, 1), max(z.cols, 1), max(z.shelves, 0), z.hinge,
                       z.contents, min(max(z.fill, 0.0), 1.0)) for z in e.zones)  # fmt: skip
    d = replace(
        base,
        width=e.width_cm / 100,
        height=e.height_cm / 100,
        depth=base.depth if e.depth_is_guess else e.depth_cm / 100,
        zones=zones or base.zones,
        base=e.base,
        base_height=e.base_height_cm / 100 if e.base_height_cm > 0 else base.base_height,
        material=e.material,
        runner_friction=RUNNER_FRICTION.get(e.drawer_runners, base.runner_friction),
    )  # the example's panel calibration (honeycomb board, a known weight) carries over
    return with_mass(d, e.known_mass_kg)


def plausible(d: Case, depth: float, size: float = 0.10, n: int = SAMPLES, seed: int = 0) -> list[Case]:
    """Width and height within ±`size`, depth within ±`depth`, density ±15%, top items ±30%.
    From a photo: size 0.10, depth 0.15 when guessed (0.05 when visible)."""
    rng = random.Random(seed)
    out = []
    for _ in range(n):
        w, h, dp = (rng.uniform(1 - size, 1 + size), rng.uniform(1 - size, 1 + size),
                    rng.uniform(1 - depth, 1 + depth))  # fmt: skip
        k, top = rng.uniform(0.85, 1.15), rng.uniform(0.7, 1.3)
        items = tuple(replace(i, mass=i.mass * top) for i in d.top_items)
        out.append(replace(d, width=d.width * w, height=d.height * h, depth=d.depth * dp,
                           density_scale=d.density_scale * k, top_items=items))  # fmt: skip
    return out


def verdict(tip_share: float) -> str:
    return "pass" if tip_share <= 0.05 else "fail" if tip_share >= 0.95 else "uncertain"


def child_verdicts(variants: list[Case], **kw) -> dict[str, dict]:
    out, tests = {}, [f2057_tests(v, **kw) for v in variants]
    for i, s in enumerate(tests[0]):
        results = [statics(v, t[i]) for v, t in zip(variants, tests, strict=True)]
        margins = [r.margin for r in results]
        share = sum(r.tips for r in results) / len(results)  # not margin < 1: a held strap balances exactly
        out[s.key] = {"title": s.title, "verdict": verdict(share), "tip_share": share,
                      "margin_range": [min(margins), max(margins)], "standard": s.standard}  # fmt: skip
    return out


def elderly_verdict(variants: list[Case]) -> dict:
    forces = [tip_force(v, min(HAND_HEIGHT_M, v.height), fill=True) for v in variants]
    lo, hi = GRAB_FORCE_RANGE_N
    v = "fail" if max(forces) < lo else "pass" if min(forces) > hi else "uncertain"
    return {"title": "Adult grabbing it for balance", "verdict": v, "tip_force_N": [min(forces), max(forces)],
            "assumption": elderly_test(variants[0]).assumption}  # fmt: skip


def fixes(d: Case) -> list[dict]:
    """Each fix re-runs the physics on the nominal estimate."""
    base = {s.key: statics(d, s).tips for s in f2057_tests(d)}
    failing = [k for k, tipped in base.items() if tipped]
    out = []

    anchored = [statics(d, s) for s in f2057_tests(d, anchored=True) + [elderly_test(d, anchored=True)]]
    need = max(st.anchor_needed_N for st in anchored)
    out.append({"fix": "Anchor it to the wall with an anti-tip strap (ASTM F3096, under $20)",
                "fixes": failing, "detail": f"worst case loads the strap to {need:.0f} N of its "
                f"{ANCHOR_RATING_N:.0f} N rating", "works": need <= ANCHOR_RATING_N})  # fmt: skip

    if (top := d.top_drawer()) and len(d.drawers()) > 1:
        locked = {s.key: statics(d, s).tips for s in f2057_tests(d, only_open=frozenset({top.index}))}
        out.append({"fix": "Fit drawer locks so only one drawer opens at a time",
                    "fixes": [k for k in failing if not locked[k]], "works": not any(locked.values())})  # fmt: skip

    if d.top_items:
        cleared = replace(d, top_items=())
        before, after = rocking_threshold_g(d), rocking_threshold_g(cleared)
        out.append({"fix": f"Move the {d.top_load_kg:.0f} kg standing on it somewhere low",
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
    with status("Looking for anything that could tip · Muse Spark"):
        found = knowledge.survey(image)
    lap("survey", t0)
    report |= {"room": found.room, "people": found.people}
    pieces = found.pieces

    # Each piece is described for the engine (or judged) by name, so Muse Spark reads every piece
    # while SAM outlines everything
    things = [t for p in pieces for t in p.on_it]
    concepts = [p.sam_concept for p in pieces] + [t.sam_concept for t in things]
    outlining = f"Outlining {len(concepts)} object{'s' * (len(concepts) != 1)}"
    if pieces:
        names = pieces[0].name if len(pieces) == 1 else f"{len(pieces)} pieces"
        outlining += f" and sizing up the {names} · SAM 3.1, Muse Spark"
    else:
        outlining += " · SAM 3.1"
    t0 = time.perf_counter()
    with status(outlining), ThreadPoolExecutor() as pool:
        reading = [pool.submit(read_piece, image, p, found.room, found.people) for p in pieces]
        outlines = asyncio.run(segment_all(image, concepts))
        lap("segment", t0)
        read = [job.result() for job in reading]
    lap("describe", t0)  # overlaps "segment"

    jobs, thing_segments = [], iter(outlines[len(pieces) :])
    chosen = assign_outlines(outlines[: len(pieces)])
    for piece, match, spec in zip(pieces, chosen, read, strict=False):
        entry: dict = {"piece": piece.model_dump()}
        report["pieces"].append(entry)
        own = [next(thing_segments) for _ in piece.on_it]
        box = match.box if match else None
        entry |= {"box": box, "outline": outline([match]) if match else None}
        if isinstance(spec, Judgment):
            entry |= {"status": "judged", "judgment": spec.model_dump()}
            continue
        hits = [((on_top if t.where == "top" else on_shelf)(box, segs) if box else [])
                for t, segs in zip(piece.on_it, own, strict=True)]  # fmt: skip
        items = [(t, union_box(h)) for t, h in zip(piece.on_it, hits, strict=True)]
        jobs.append((entry, box, items, spec, [outline(h) for h in hits]))

    t0 = time.perf_counter()
    if jobs and on_step:
        on_step(f"Testing a climbing child, an adult and an earthquake · physics, {SAMPLES} sizes")
    for entry, box, items, est, shapes in jobs:
        d = to_template(est)
        d = replace(d, top_items=tuple(measure_items(d, box, items, est.on_it)))
        variants = plausible(d, depth=0.15 if est.depth_is_guess else 0.05)
        seen = [{"name": t.name, "kind": item.kind, "box": b, "kg": item.mass, "outline": shape,
                 "where": "top" if item.shelf is None else "shelf"}
                for (t, b), item, shape in zip(items, d.top_items, shapes, strict=True)]  # fmt: skip
        entry |= {
            "estimate": est.model_dump(),
            "template": {k: v for k, v in asdict(d).items() if k != "notes"},
            "items": seen,
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
    # what the model wrote, held to what the page can show
    report["pieces"] = [knowledge.tidy(e) for e in report["pieces"]]
    report["room"] = knowledge.label(report["room"], "", knowledge.NAME)

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


def _render(job: tuple[Case, Scenario, Path]):
    return simulate(*job[:2], video=job[2])


def render_videos(pieces: list[tuple[Case, str]], out_dir: Path) -> list[dict]:
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
        if p["status"] == "judged":
            j = p["judgment"]
            for risk in ("child", "adult", "quake"):
                console.print(f"  [bold]{j[risk]['status'].upper():9s}[/] {risk}: {j[risk]['says']}")
            console.print(f"  Judged from: {j['basis']}")
            continue
        if p["status"] != "analyzed":
            console.print(f"[yellow]{p['status']}[/]")
            continue
        e, t = p["estimate"], p["template"]
        console.print(
            f"Like {e['example']}: {t['width'] * 100:.0f} x {t['depth'] * 100:.0f}"
            f"{' (depth guessed)' if e['depth_is_guess'] else ''} x {t['height'] * 100:.0f} cm, "
            f"{zones_text(Case.from_dict(t).zones)}, {t['material']}, ~{p['mass_kg']['empty']:.0f} kg empty "
            f"({p['mass_kg']['with_clothes']:.0f} kg loaded). Size from: {e['size_basis']}"
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
