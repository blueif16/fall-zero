"""The whole room as one scene: every piece placed as the photo shows it, simulated together.

The cards judge each piece on its own (statics over 300 sizes, three simulated earthquakes). The room
scene is what people watch: the pieces stand side by side against one wall, in the order and with the
spacing of their outlines in the photo, and each scenario plays on all of them at once, so a piece
knocking into its neighbour shows up too. Pieces the engine can't build (a leaning mirror) stand in
their place as ghosts.
"""

import json
import statistics
import threading
from collections import defaultdict

from fall_zero.assess import CARD_STATUSES, QUAKE_SEEDS, UPPER_FLOOR_HZ, child_test, configure, quakes
from fall_zero.furniture import Case
from fall_zero.knowledge import tidy
from fall_zero.physics import Scenario, elderly_test
from fall_zero.sim import Ghost, Placed, quake_scenario, shake_scene, simulate_scene

GAP_M = (0.03, 1.2)  # the space between neighbours, as the photo shows it, kept within this
M_PER_PX = 0.002  # when no piece has a known width: about 3 m across a 1600 px photo
STANDING = Scenario("stand", "", frozenset())  # in place, nothing pushing on it
TITLES = {"child": ("A child climbs it", "A child climbs each piece"),
          "adult": ("Someone grabs it for balance", "Someone grabs each piece for balance")}  # fmt: skip

_cache: dict[str, dict] = {}
_busy: defaultdict[str, threading.Lock] = defaultdict(threading.Lock)  # one run per scene; others wait for it


def layout(entries: list[dict], cases: list[Case | None]) -> list[tuple[float, float, float, float, float]]:
    """Where each piece stands: (x, y, width, depth, height) in metres, in the photo's order seen from
    the front, backs against one wall. An outline's scale comes from its piece's known width; the gaps between
    outlines, and the size of a piece that isn't built, use the median scale."""
    scales = [c.width / (e["box"][2] - e["box"][0]) for e, c in zip(entries, cases, strict=True) if c and e.get("box")]
    k = statistics.median(scales) if scales else M_PER_PX
    sizes = []
    for e, c in zip(entries, cases, strict=True):
        if c:
            sizes.append((c.width, c.depth, c.height))
        elif box := e.get("box"):
            w, h = (box[2] - box[0]) * k, (box[3] - box[1]) * k
            sizes.append((w, min(0.4, 0.4 * w), h))
        else:
            sizes.append((0.5, 0.3, 1.0))
    # left to right by the outlines' centers; a piece without an outline goes at the end
    boxes = [e.get("box") for e in entries]
    order = sorted(range(len(entries)), key=lambda i: (boxes[i] is None, sum(boxes[i][::2]) if boxes[i] else 0))
    x, left, prev = {}, 0.0, None
    for i in order:
        box = boxes[i]
        if prev is not None:
            gap = (box[0] - prev[2]) * k if box and prev else GAP_M[1] / 4
            left += min(max(gap, GAP_M[0]), GAP_M[1])
        x[i] = left + sizes[i][0] / 2
        left += sizes[i][0]
        prev = box
    middle = left / 2
    deepest = max(s[1] for s in sizes)
    # facing a piece's front (+y) you look along -y, so the photo's left is +x
    return [(middle - x[i], (s[1] - deepest) / 2, *s) for i, s in enumerate(sizes)]


def _seed(variants: list[tuple[Case, bool, bool]], hz: float | None) -> int:
    """The simulated earthquake to show: the one in which the most pieces do what they do in most runs
    (each piece's runs are cached from its card)."""
    runs = quakes(variants, hz)

    def agrees(seed: int) -> int:
        return sum(bool(next(r for r in q["seeds"] if r["seed"] == seed)["fell_at"]) == (q["fell"] * 2 > q["runs"])
                   for q in runs)  # fmt: skip

    return max(QUAKE_SEEDS, key=agrees)


def scene(report: dict, answers: list[dict], scenario: str, focus: int | None = None) -> dict:
    """The room's simulation for the page's viewer. `answers` holds each carded piece's answers (a fix
    previewed is just its answer added); `focus` loads only that piece in the child and adult tests.
    Pieces and events are numbered by their index among the cards."""
    entries = [tidy(e) for e in report["pieces"] if e["status"] in CARD_STATUSES]  # its events name the things
    answers = (list(answers) + [{}] * len(entries))[: len(entries)]
    key = json.dumps([report["image"], answers, scenario, focus], sort_keys=True)
    with _busy[key]:
        if key not in _cache:
            if len(_cache) > 64:
                _cache.pop(next(iter(_cache)))
            _cache[key] = _scene(entries, answers, scenario, focus)
    return _cache[key]


def _scene(entries: list[dict], answers: list[dict], scenario: str, focus: int | None) -> dict:
    built: list[tuple[Case, float, float] | None] = [
        configure(Case.from_dict(e["template"]), e["estimate"]["depth_is_guess"], a)
        if e["status"] == "analyzed" else None
        for e, a in zip(entries, answers, strict=True)
    ]  # fmt: skip
    spots = layout(entries, [b[0] if b else None for b in built])

    placed, ghosts, index, ghost_index, quake_variants = [], [], [], [], []
    for i, (b, a, (x, y, w, dp, h)) in enumerate(zip(built, answers, spots, strict=True)):
        if b is None:
            ghosts.append(Ghost(x, y, w, dp, h))
            ghost_index.append(i)
            continue
        d, size, depth = b
        anchored, locks = a.get("anchored") == "yes", bool(a.get("locks"))
        if scenario == "quake":
            s = quake_scenario(d, anchored, locks)
            quake_variants.append((d, anchored, locks))
        elif focus is not None and focus != i:
            s = STANDING
        elif scenario == "adult":
            s = elderly_test(d, anchored=anchored)
        else:
            s = child_test(d, size, depth, anchored, locks)
        placed.append(Placed(d, s, x, y, prefix=f"p{i}_"))
        index.append(i)

    if not placed:
        trace = {}
    elif scenario == "quake":
        hz = None if any(a.get("floor") == "ground" for a in answers) else UPPER_FLOOR_HZ
        seed = _seed(quake_variants, hz)
        trace = shake_scene(placed, seed=seed, building_hz=hz, trace=True, ghosts=tuple(ghosts))[0].trace or {}
    else:
        one, every = TITLES[scenario]
        trace = simulate_scene(placed, trace=True, title=one if focus is not None or len(entries) == 1 else every,
                               room=True, ghosts=tuple(ghosts))[0].trace or {}  # fmt: skip
    if trace:
        trace["pieces"] = [{**p, "index": i} for p, i in zip(trace["pieces"], index, strict=True)]
        trace["ghosts"] = [{**g, "index": i} for g, i in zip(trace["ghosts"], ghost_index, strict=True)]
        trace["events"] = [(t, text, *(index[k] for k in who)) for t, text, *who in trace["events"]]
    return trace
