"""What the user sees: each analyzed piece as verdicts, fixes and questions instead of numbers.

Every risk (a climbing child, an adult grabbing it, an earthquake) gets one of three answers:
tips, maybe, or holds. Each fix carries what the risks become once it's done, checked by re-running
the physics. When something is "maybe", the card asks the questions whose answers would settle it.

The child and adult answers come from statics over the plausible sizes (well under a second). The
earthquake answer comes from simulated earthquakes (`sim.shake`), several per variant, in parallel
and cached; without `simulate` it falls back to the rocking threshold.

Each thing on it (on top or on an open shelf) is judged on its own: is it hard, how hard would it hit
(weight x fall height), and does it fall in the simulated earthquake. Only things that would hurt someone
go in the fix.

What to do in practice (what to buy, the cost, the steps, the renter's option) comes from the skill's
fixes catalog (skill/catalog/fixes.toml): every fix carries its `kind` there and its `how`.
"""

import multiprocessing
import os
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace

from fall_zero.analyze import child_verdicts, elderly_verdict, plausible, verdict
from fall_zero.furniture import Case, TopItem, catalog, contents
from fall_zero.knowledge import SHORT, label, tidy
from fall_zero.physics import G, Scenario, elderly_test, f2057_tests, rocking_threshold_g, statics
from fall_zero.sim import shake, simulate

# Peak floor acceleration at the USGS ShakeMap intensity boundaries: from 0.34 g shaking is
# "severe" (MMI VIII), from 0.65 g "violent" (IX). Up to 0.34 g is still "very strong" (VII).
STRONG_QUAKE_G, SEVERE_QUAKE_G = 0.34, 0.65
QUAKE_SEEDS = (1, 2, 3)  # the simulated earthquakes every variant is shaken by
UPPER_FLOOR_HZ = 1.5  # an upper floor sways with the building, about 1-2 Hz in low-rise homes

# Assumption until sourced: the impact energy (weight x fall height) at which a hard object hitting a
# child's head is a concern (about 1 kg from 0.8 m) and a serious danger (2 kg from 1 m). Glass and
# ceramic count from half the energy, because they shatter. No standard covers this; TVs always count.
HURT_J, SERIOUS_J = 8.0, 20.0

# Depth answers relative to the piece's guessed depth: a 28 cm bookcase and a 48 cm dresser get their own ranges
DEPTH_ANSWERS = {"shallow": 0.8, "standard": 1.0, "deep": 1.2}
DEPTH_BANDS = (0.9, 1.1)  # the options' edges, as shares of the guess
MATERIAL_ANSWERS = {"hardwood": "solid_hardwood", "softwood": "solid_softwood", "board": "particleboard"}
WOODS = {"particleboard", "mdf", "plywood", "solid_softwood", "solid_hardwood"}  # the material question's scope
STATUS = {"pass": "holds", "uncertain": "maybe", "fail": "tips"}
RISK_KEYS = ("child", "adult", "quake")
CARD_STATUSES = ("analyzed", "judged")  # report entries that become cards
ITEM_WORD = {"tv": "TV", "screen": "TV"}  # when the model gave no short name
# What's in the drawers, as the share of each drawer it fills
DRAWER_FILL = {"full": 1.0, "half": 0.5, "empty": 0.0}
# Assumption: what a toddler reaches standing. A thing a child wants that stands higher is climbed for.
CHILD_REACH_M = 0.75
ICONS = ("strap", "lock", "top", "distance", "tv", "toy", "weight", "hand", "latch", "search")  # the page draws these
HOW = ("label", "buy", "item", "count", "cost_usd", "minutes", "tools", "steps", "avoid", "renter", "source", "check", "stuck")

# What each child test means when it fails, worst first, by what the child loads
CHILD_SAYS = {
    "child_on_drawer": {"drawer": "A child standing on an open drawer pulls it over",
                        "door": "A child hanging on an open door pulls it over",
                        "shelf": "A child climbing the shelves pulls it over"},
    "horizontal_force": {"drawer": "A child tugging the top drawer pulls it over",
                         "door": "A child tugging an open door pulls it over",
                         "shelf": "A child tugging a shelf pulls it over"},
    "clothing_load": {"drawer": "Full drawers pulled open tip it on their own",
                      "door": "With its doors open it tips on its own"},
}  # fmt: skip


def configure(d: Case, depth_is_guess: bool, answers: dict) -> tuple[Case, float, float]:
    """The template after the user's answers, with how far its width/height and depth may still be off."""
    size, depth = 0.10, 0.15 if depth_is_guess else 0.05
    if answers.get("depth") in DEPTH_ANSWERS:
        d, depth = replace(d, depth=d.depth * DEPTH_ANSWERS[answers["depth"]]), 0.08
    if m := answers.get("measured"):
        d = replace(d, width=m["width_cm"] / 100, depth=m["depth_cm"] / 100, height=m["height_cm"] / 100)
        size = depth = 0.03
    if answers.get("material") in MATERIAL_ANSWERS:
        d = replace(d, material=MATERIAL_ANSWERS[answers["material"]])
    if (share := DRAWER_FILL.get(answers.get("drawers"))) is not None:  # counted in every test from now on
        zones = tuple(replace(z, fill=share, contents="" if z.contents == "none" else z.contents)
                      if z.kind == "drawers" else z for z in d.zones)  # fmt: skip
        d = replace(d, zones=zones, contents_known=True)
    moved = set(answers.get("moved", [])) | (set(range(len(d.top_items))) if answers.get("cleared_top") else set())
    if moved:
        d = replace(d, top_items=tuple(it for i, it in enumerate(d.top_items) if i not in moved))
    return d, size, depth


# --- simulated earthquakes ----------------------------------------------------------------

_pool: ProcessPoolExecutor | None = None
_quake_cache: dict[str, dict] = {}
# A Vercel function has one CPU and no shared memory for a process pool: there they run one after another
# (a room's ~50 earthquakes take ~15 s)
WORKERS = 1 if os.environ.get("VERCEL") else min(12, os.cpu_count() or 4)


def pool() -> ProcessPoolExecutor:
    global _pool
    # spawn, not fork: the server is multithreaded
    _pool = _pool or ProcessPoolExecutor(WORKERS, multiprocessing.get_context("spawn"))
    return _pool


def _map(fn, jobs: list) -> list:
    return list(pool().map(fn, jobs)) if WORKERS > 1 else [fn(j) for j in jobs]


def _ready(_) -> int:
    return os.getpid()


def warm() -> None:
    """Start every worker (each imports MuJoCo, ~1.5 s) before the first photo needs them."""
    if WORKERS > 1:
        list(pool().map(_ready, range(WORKERS)))


def _shake_one(job: tuple[Case, bool, bool, float | None, int]) -> dict:
    d, anchored, locks, hz, seed = job
    q = shake(d, anchored=anchored, seed=seed, building_hz=hz, locks=locks)
    items = {name: s["label"] for s in q.stages for name in s["items_fell"]}
    return {"seed": seed, "fell_at": q.fell_at, "items": items}


def quakes(variants: list[tuple[Case, bool, bool]], hz: float | None) -> list[dict]:
    """Shake each (template, anchored, locks) variant with the same simulated earthquakes, all in
    parallel. Per variant: {"runs", "fell" (how many it fell over in), "seeds" (each run's outcome)}."""
    keys = [repr((*v, hz)) for v in variants]
    new = {k: v for v, k in zip(variants, keys, strict=True) if k not in _quake_cache}  # the same variant once
    todo = [(*v, hz, seed) for v in new.values() for seed in QUAKE_SEEDS]
    if todo:
        runs = _map(_shake_one, todo)
        for k, v in new.items():
            mine = [r for job, r in zip(todo, runs, strict=True) if job[:3] == v]
            _quake_cache[k] = {"runs": len(mine), "fell": sum(bool(r["fell_at"]) for r in mine), "seeds": mine}
    return [_quake_cache[k] for k in keys]


def quake_risk(q: dict, anchored: bool, floor_known: bool, upper: bool) -> dict:
    where = ("Upper floor: " if upper else "Ground floor: ") if floor_known else "On an upper floor, "
    n, fell = q["runs"], q["fell"]
    if fell:
        stage = Counter(r["fell_at"] for r in q["seeds"] if r["fell_at"]).most_common(1)[0][0].lower()
        says = f"{where}it fell over in {fell} of {n} simulated earthquakes ({stage})"
        return {"status": "tips" if fell * 2 > n else "maybe", "says": says, "simulated": True}
    held = "the strap held it" if anchored else "it stayed up"
    return {"status": "holds", "says": f"{where}{held} in all {n} simulated earthquakes", "simulated": True}


# --- risks ------------------------------------------------------------------------------------


def risks(d: Case, size: float, depth: float, anchored: bool = False, locks: bool = False,
          quake: dict | None = None) -> dict[str, dict]:  # fmt: skip
    variants = plausible(d, depth, size)
    top = d.top_drawer()
    only_open = frozenset({top.index}) if locks and top else None
    child = child_verdicts(variants, anchored=anchored, only_open=only_open)
    says = {s.key: CHILD_SAYS[s.key][s.element] for s in f2057_tests(d, only_open=only_open)}
    worst = next((k for k in CHILD_SAYS if k in child and child[k]["verdict"] == "fail"), None)
    unsure = next((k for k in CHILD_SAYS if k in child and child[k]["verdict"] == "uncertain"), None)
    if worst:
        child_risk = {"status": "tips", "says": says[worst], "test": worst}
    elif unsure:
        child_risk = {"status": "maybe", "says": says[unsure].replace(" pulls", " might pull")
                      .replace(" tip it", " might tip it").replace(" it tips", " it might tip"),
                      "test": unsure}  # fmt: skip
    else:
        child_risk = {"status": "holds", "says": "Holds a climbing child", "test": "child_on_drawer"}

    if anchored:  # the strap takes the grab; tips only if it would need more than its rating
        share = sum(statics(v, elderly_test(v, anchored=True)).tips for v in variants) / len(variants)
        adult = STATUS[verdict(share)]
    else:
        adult = STATUS[elderly_verdict(variants)["verdict"]]
    adult_says = {"tips": "Tips if someone grabs it to steady themselves",
                  "maybe": "Could tip if someone leans hard on it",
                  "holds": "Holds an adult leaning on it"}[adult]  # fmt: skip

    if quake is None:  # no simulation: judge by how much shaking starts it rocking
        g = rocking_threshold_g(d)
        if anchored:
            quake = {"status": "holds", "says": "The strap holds it while the floor shakes"}
        elif g < STRONG_QUAKE_G:
            quake = {"status": "tips", "says": "Starts rocking in a strong earthquake and can topple"}
        elif g < SEVERE_QUAKE_G:
            quake = {"status": "maybe", "says": "Could rock over in a severe earthquake"}
        else:
            quake = {"status": "holds", "says": "Stays put in all but violent shaking"}
    return {"child": child_risk, "adult": {"status": adult, "says": adult_says}, "quake": quake}


def overall(rs: dict[str, dict]) -> str:
    statuses = {r["status"] for r in rs.values()}
    return "tips" if "tips" in statuses else "maybe" if "maybe" in statuses else "holds"


# --- things on top ----------------------------------------------------------------------------


def item_name(it: TopItem) -> str:
    return label(it.short) or ITEM_WORD.get(it.kind) or label(it.name, "", SHORT) or "item"


def item_hazard(d: Case, it: TopItem, falls: str | None) -> dict:
    """Would it hurt someone? Hard or soft, and how hard it would hit: weight x height it falls from (its
    middle, standing on the top or on its shelf)."""
    drop = d.base_of(it) + it.z + it.height / 2
    energy = it.mass * G * drop
    if it.is_screen or (it.hard and energy >= SERIOUS_J):
        level = "danger"
    elif it.hard and (energy >= HURT_J or (it.breakable and energy >= HURT_J / 2)) or it.mass >= 5:
        level = "caution"
    else:
        level = "fine"
    what = "Soft" if not it.hard else "Glass or ceramic" if it.breakable else "Hard"
    why = f"{what}, about {it.mass:.1f} kg, {drop:.1f} m up"
    if it.breakable and level != "fine":
        why += ": breaks into sharp pieces"
    if falls:
        why += f"; falls off in {falls.lower()}"
    if level == "fine":
        why = "Soft: it can't hurt anyone" if not it.hard else f"Light ({it.mass:.1f} kg): won't do real harm"
    return {"level": level, "why": why, "energy_J": round(energy, 1), "drop_m": round(drop, 2), "falls": falls}


def hazards(d: Case) -> list[int]:
    """The things on it that would hurt someone if they fell: moving those is the fix."""
    return [i for i, it in enumerate(d.top_items) if item_hazard(d, it, None)["level"] != "fine"]


def tempting(d: Case) -> list[int]:
    """The things a child would climb for: something they want, standing out of their reach."""
    return [i for i, it in enumerate(d.top_items) if it.tempting and d.base_of(it) >= CHILD_REACH_M]


def holds(d: Case) -> list[dict]:
    """What it holds, by kind of contents and thing standing on it: [{"what": "books", "kg": 38.2}, ...]."""
    out: dict[str, float] = {}
    for key, kg in d.held().items():
        what = contents()[key].short or key if key in contents() else key
        out[what] = out.get(what, 0.0) + kg
    for it in d.top_items:
        out[item_name(it)] = out.get(item_name(it), 0.0) + it.mass
    return [{"what": what, "kg": round(kg, 1)} for what, kg in out.items() if kg >= 0.05]


# --- what to do, from the fixes catalog -------------------------------------------------------


def how(kind: str) -> dict:
    """The practical advice for a kind of fix, straight from the catalog."""
    entry = catalog("fixes")[kind]
    return {k: entry.get(k, [] if k in ("tools", "steps", "stuck") else "") for k in HOW}


def fix(key: str, kind: str, **card) -> dict:
    """A fix of a kind from the catalog: its icon, title and why unless the card gives its own."""
    entry = catalog("fixes")[kind]
    return {"key": key, "kind": kind, "icon": entry["icon"], "title": entry["label"], "why": entry.get("why", ""),
            "how": how(kind), "after": None} | card  # fmt: skip


# Habits that only need saying, by who they are for (`when` in the catalog), and whether a card needs one:
# `facts` are the card's statuses, whether it holds contents, has doors, and a brand and model
HABITS = {
    "contents": lambda f: f["contents"] and (f["child"] != "holds" or f["quake"] != "holds"),
    "adult": lambda f: f["adult"] != "holds",
    "quake": lambda f: f["doors"] and f["quake"] != "holds",
    "brand": lambda f: bool(f["brand"]),
}


def anchor_kind(est: dict) -> str:
    """How this piece is held down (a strap, a range's bracket): the describe step names it. Reports from
    before it did only have the fix's title."""
    kinds = [k for k, v in catalog("fixes").items() if v.get("anchors")]
    if est.get("anchor") in kinds:
        return est["anchor"]
    return next((k for k in kinds if k in (est.get("anchor_fix") or "").lower()), kinds[0])


# --- the card ---------------------------------------------------------------------------------


def assess(entry: dict, answers: dict | None = None, simulate_quakes: bool = False) -> dict:
    """One analyzed piece of the report (`analyze()`'s `pieces[i]`) as a card."""
    a = answers or {}
    entry = tidy(entry)  # a report saved before the model's text was checked
    est = entry["estimate"]
    base = Case.from_dict(entry["template"])
    d, size, depth = configure(base, est["depth_is_guess"], a)
    anchored, locks = a.get("anchored") == "yes", bool(a.get("locks"))
    moved = set(a.get("moved", [])) | (set(range(len(base.top_items))) if a.get("cleared_top") else set())
    upper = a.get("floor") != "ground"
    hz = UPPER_FLOOR_HZ if upper else None

    # Which things on it would hurt someone if they fell (moving those is a fix), and which a child would
    # climb for (moving those is another)
    to_move, wanted = hazards(base), tempting(base)

    def without(ids) -> Case:
        return configure(base, est["depth_is_guess"], a | {"moved": sorted(moved | set(ids))})[0]

    # Every variant the card shows, shaken by the same simulated earthquakes in one parallel batch
    variants = {"now": (d, anchored, locks)}
    if not anchored:
        variants["anchor"] = (d, True, locks)
        if not locks and len(d.drawers()) > 1:
            variants["locks"] = (d, False, True)
    if to_move and not set(to_move) <= moved:
        variants["moved"] = (without(to_move), anchored, locks)
    if wanted and not set(wanted) <= moved:
        variants["tempting"] = (without(wanted), anchored, locks)
    q = dict(zip(variants, quakes(list(variants.values()), hz), strict=True)) if simulate_quakes else {}
    floor_known = "floor" in a

    def quake_for(key: str) -> dict | None:
        if key not in q:
            return None
        return quake_risk(q[key], variants[key][1], floor_known, upper)

    def after(key: str, **changes) -> dict[str, str]:
        dd, sz, dp = configure(base, est["depth_is_guess"], a | changes)
        is_anchored = changes.get("anchored", a.get("anchored")) == "yes"
        already = (key == "anchor" and anchored) or (key == "locks" and locks) or \
            (key == "moved" and set(to_move) <= moved) or (key == "tempting" and set(wanted) <= moved)  # fmt: skip
        rs = risks(dd, sz, dp, is_anchored, bool(changes.get("locks", locks)), quake_for("now" if already else key))
        return {k: r["status"] for k, r in rs.items()}

    now = risks(d, size, depth, anchored, locks, quake_for("now"))
    status = overall(now)
    current = {k: r["status"] for k, r in now.items()}
    fall_m = d.height + 0.3

    # Items, judged on their own; "falls" from the simulated earthquakes as things stand
    fell_items = Counter(n for r in (q["now"]["seeds"] if "now" in q else []) for n in r["items"])
    stage_of = {n: s for r in (q["now"]["seeds"] if "now" in q else []) for n, s in r["items"].items()}
    items = []
    for i, (it, seen) in enumerate(zip(base.top_items, entry.get("items", []), strict=False)):
        falls = stage_of.get(it.name) if fell_items[it.name] * 2 >= len(QUAKE_SEEDS) else None
        items.append({"name": it.name, "short": item_name(it), "kind": it.kind, "box": seen.get("box"),
                      "outline": seen.get("outline"), "moved": i in moved, "where": "top" if it.shelf is None
                      else "shelf", "kg": round(it.mass, 1), "tempting": it.tempting,
                      **item_hazard(base, it, falls)})  # fmt: skip

    fixes = []
    if status != "holds" or anchored:
        unsure = a.get("anchored") == "unsure"
        fixes.append(fix(
            "anchor", anchor_kind(est), title=est.get("anchor_fix") or "Strap it to the wall",
            why="Check behind the top for a strap; if there's none, add one." if unsure else
            est.get("anchor_how") or catalog("fixes")[anchor_kind(est)].get("why", ""),
            after=after("anchor", anchored="yes"), answer={"anchored": "yes"}, done=anchored,
        ))  # fmt: skip
    if not anchored and len(d.drawers()) > 1:
        with_locks = after("locks", locks=True)
        if with_locks != current or locks:
            fixes.append(fix("locks", "locks", title="Let only one drawer open at a time", after=with_locks,
                             answer={"locks": True}, done=locks))  # fmt: skip
    if to_move:
        # worst first: the TV and the heaviest hits lead the title
        to_move.sort(key=lambda i: (items[i]["level"] != "danger", -items[i]["energy_J"]))
        hits = [items[i] for i in to_move]
        listed = " and ".join(h["short"] for h in hits[:2]) + (f" and {len(hits) - 2} more" if len(hits) > 2 else "")
        falling = [h["short"] for h in hits if h["falls"]]
        kg, high = sum(base.top_items[i].mass for i in to_move), max(h["drop_m"] for h in hits)
        one = hits[0]["why"].split(";")[0] + ". "
        why = one if len(hits) == 1 else f"{kg:.1f} kg of hard things, {high:.1f} m up. "
        if falling:
            why += f"In the simulated earthquakes the {' and '.join(falling)} fell off."
        elif any(base.top_items[i].breakable for i in to_move):
            why += "If the furniture tips or gets bumped, it comes down and shatters."
        else:
            why += "If the furniture tips, it comes down first, onto whoever is in front."
        target = sorted(moved | set(to_move))
        with_moved = after("moved", moved=target)
        fixes.append(fix("moved", "moved", title=f"Move the {listed} somewhere low", why=why,
                         after=with_moved if with_moved != current else None, answer={"moved": target},
                         done=set(to_move) <= moved))  # fmt: skip
    if wanted and (current["child"] != "holds" or set(wanted) <= moved):
        target = sorted(moved | set(wanted))
        with_moved = after("tempting", moved=target)
        names = " and ".join(dict.fromkeys(item_name(base.top_items[i]) for i in wanted))
        fixes.append(fix("tempting", "tempting", why=f"The {names}: " + catalog("fixes")["tempting"]["why"].lower(),
                         after=with_moved if with_moved != current else None, answer={"moved": target},
                         done=set(wanted) <= moved))  # fmt: skip
    if status != "holds":
        near = est.get("nearby", est.get("nearby_bed_or_crib"))
        fixes.append(fix("distance", "distance", title=f"Keep the {near} {fall_m:.1f} m away" if near else
                         f"Keep beds and play mats {fall_m:.1f} m away",
                         why=f"If it falls, its top lands about {d.height:.1f} m out."))  # fmt: skip
    facts = current | {"contents": bool(d.held()), "doors": bool(d.door_list()), "brand": est.get("brand_model")}
    for kind, entry_ in catalog("fixes").items():
        if entry_.get("when") in HABITS and HABITS[entry_["when"]](facts):
            fixes.append(fix(kind, kind))
    # the fixes that clear the most risks first; information-only ones last
    fixes.sort(key=lambda f: ("answer" not in f, -sum(s == "holds" for s in (f["after"] or {}).values())))

    questions = []
    if status != "holds" and "anchored" not in a:
        questions.append({"key": "anchored", "title": "Is it already strapped to the wall?",
                          "options": [{"label": "Yes", "value": "yes"}, {"label": "No", "value": "no"},
                                      {"label": "Not sure", "value": "unsure"}]})  # fmt: skip
    if simulate_quakes and not floor_known and not anchored and (current["quake"] != "holds" or fell_items):
        questions.append({"key": "floor", "title": "Which floor is this room on?",
                          "hint": "Upper floors sway with the building and shake furniture far harder.",
                          "options": [{"label": "Ground floor", "value": "ground"},
                                      {"label": "Upper floor", "value": "upper"}]})  # fmt: skip
    if "drawers" not in a and not anchored and d.drawers() and drawers_matter(base, est["depth_is_guess"], a):
        questions.append({"key": "drawers", "title": "What's in the drawers?",
                          "hint": "Full drawers make it heavier.",
                          "options": [{"label": "Full", "value": "full"}, {"label": "About half", "value": "half"},
                                      {"label": "Nearly empty", "value": "empty"}]})  # fmt: skip
    if current["child"] == "maybe" and not anchored:
        measured = "measured" in a
        if est["depth_is_guess"] and "depth" not in a and not measured:
            lo, hi = (round(d.depth * k * 100) for k in DEPTH_BANDS)
            questions.append({"key": "depth", "title": "How deep is it, front to back?",
                              "hint": "A photo can't show this well.",
                              "options": [{"label": f"Under {lo} cm", "sub": f"{lo / 2.54:.0f} in", "value": "shallow"},
                                          {"label": f"{lo}–{hi} cm", "sub": f"{lo / 2.54:.0f}–{hi / 2.54:.0f} in",
                                           "value": "standard"},
                                          {"label": f"Over {hi} cm", "sub": f"{hi / 2.54:.0f} in", "value": "deep"},
                                          {"label": "Not sure", "value": "unsure"}]})  # fmt: skip
        if "material" not in a and not measured and d.material in WOODS:
            questions.append({"key": "material", "title": "What is it made of?",
                              "hint": "Heavier furniture is harder to pull over.",
                              "options": [{"label": "Solid hardwood", "sub": "oak, maple", "value": "hardwood"},
                                          {"label": "Pine", "sub": "light solid wood", "value": "softwood"},
                                          {"label": "Particleboard", "sub": "flat-pack, MDF", "value": "board"},
                                          {"label": "Not sure", "value": "unsure"}]})  # fmt: skip
        if not measured and ("depth" in a or "material" in a or not est["depth_is_guess"]):
            questions.append({"key": "measured", "title": "Got a tape measure?", "kind": "measure",
                              "hint": "Exact size settles it.",
                              "guess": {"width_cm": round(d.width * 100), "depth_cm": round(d.depth * 100),
                                        "height_cm": round(d.height * 100)}})  # fmt: skip

    note = None
    if status == "maybe" and not questions:
        note = "Too close to call from here. Treat it as a tip risk and strap it."

    held = holds(d)
    return {
        "name": entry["piece"]["name"],
        "box": entry.get("box"),
        "outline": entry.get("outline"),
        "items": items,
        "status": status,
        "headline": {"tips": "Can tip over", "maybe": "Might tip over", "holds": "Stable"}[status]
        if not (anchored and status == "holds")
        else "Strapped and stable",
        "risks": now,
        "fixes": fixes,
        "questions": questions,
        "note": note,
        "answers": a,
        "quake_seed": _shown_seed(q.get("now")),
        "details": {
            "size_cm": [round(d.width * 100), round(d.depth * 100), round(d.height * 100)],
            "depth_guessed": est["depth_is_guess"] and "depth" not in a and "measured" not in a,
            "mass_kg": round(d.mass()),
            "mass_with_clothes_kg": round(d.mass(fill=True)),
            # with everything it holds: its contents and the things standing on it (`holds`)
            "mass_full_kg": round(d.mass() + sum(h["kg"] for h in held)),
            "holds": held,
            "top_load_kg": round(d.top_load_kg, 1),
            "preset": est.get("example", est.get("preset")),
            "material": d.material,
            "size_basis": est["size_basis"],
            "rocking_starts_g": round(rocking_threshold_g(d), 2),
            "spread": {"size": size, "depth": depth},
            "quakes": {k: {"fell": v["fell"], "runs": v["runs"]} for k, v in q.items()},
            "floor": "upper" if upper else "ground",
        },  # fmt: skip
    }


def drawers_matter(base: Case, depth_is_guess: bool, a: dict) -> bool:
    """Would full drawers or empty ones change what a climbing child or a grabbing adult does to it?"""
    seen = set()
    for fill in ("full", "empty"):
        d, size, depth = configure(base, depth_is_guess, a | {"drawers": fill})
        rs = risks(d, size, depth, locks=bool(a.get("locks")))
        seen.add((rs["child"]["status"], rs["adult"]["status"]))
    return len(seen) > 1


def _shown_seed(q: dict | None) -> int:
    """The simulated earthquake to show: one whose outcome matches most runs."""
    if not q:
        return QUAKE_SEEDS[0]
    fell_most = q["fell"] * 2 > q["runs"]
    return next((r["seed"] for r in q["seeds"] if bool(r["fell_at"]) == fell_most), QUAKE_SEEDS[0])


def card(entry: dict, answers: dict | None = None, simulate_quakes: bool = False) -> dict:
    """The card for any piece: tested by the engine, or judged from the skill's references."""
    if entry["status"] == "judged":
        return judged_card(entry, answers)
    return assess(entry, answers, simulate_quakes)


def assess_all(report: dict, simulate_quakes: bool = False) -> list[dict]:
    return [card(e, simulate_quakes=simulate_quakes) for e in report["pieces"] if e["status"] in CARD_STATUSES]


# --- pieces the engine can't build ------------------------------------------------------------

RANK = {"holds": 0, "maybe": 1, "tips": 2}
SAYS_NOW = {"holds": "Holds once that's done", "maybe": "Could still fall", "tips": "Can still fall"}
# the headline, and what a risk says when the judge's own words were garbled
FALLS = {"tips": "Can fall over", "maybe": "Might fall over", "holds": "Stable"}
# A judged fix whose icon clearly is a catalog kind gets that kind's practical advice: tying it to the wall,
# clearing where it lands. Others ("Hang it instead") stay the judge's own words.
JUDGED_KINDS = {"strap": "strap", "distance": "distance"}


def judged_card(entry: dict, answers: dict | None = None) -> dict:
    """A piece judged from the references (a mirror, a lamp, a safe). Each fix and each answer to its
    question carries the statuses expected afterwards, so tapping still updates the verdict."""
    a = answers or {}
    entry = tidy(entry)
    j = entry["judgment"]
    first = {k: j[k]["status"] for k in RISK_KEYS}
    q = j.get("question")
    chosen = next((o for o in q["options"] if o["label"] == a.get("judged")), None) if q else None

    def settled(start: dict) -> dict:  # what the fixes done so far leave
        out = dict(start)
        for i, f in enumerate(j["fixes"]):
            if a.get(f"fix_{i}"):
                out = {k: min(out[k], f["after"][k], key=RANK.__getitem__) for k in out}
        return out

    now = settled(chosen["after"] if chosen else first)
    rs = {k: {"status": now[k], "says": j[k]["says"] or FALLS[now[k]] if now[k] == first[k] else SAYS_NOW[now[k]],
              "judged": True} for k in RISK_KEYS}  # fmt: skip
    status = overall(rs)
    fixes = []
    for i, f in enumerate(j["fixes"]):
        icon = f["icon"] if f["icon"] in ICONS else "top" if f["icon"] == "move" else "strap"
        kind = {"kind": JUDGED_KINDS[icon], "how": how(JUDGED_KINDS[icon])} if icon in JUDGED_KINDS else {}
        fixes.append({"key": f"fix_{i}", "icon": icon, "title": f["title"], "why": f["why"], "after": f["after"],
                      "answer": {f"fix_{i}": True}, "done": bool(a.get(f"fix_{i}"))} | kind)  # fmt: skip
    questions = []
    # asked only while an answer could still change something: once a fix settles it ("Is it fixed to the
    # wall?" after strapping it), every answer leads to the same statuses
    if q and "judged" not in a and any(settled(o["after"]) != now for o in q["options"]):
        questions.append({"key": "judged", "title": q["title"],
                          "options": [{"label": o["label"], "value": o["label"]} for o in q["options"]]})  # fmt: skip
    return {
        "name": entry["piece"]["name"],
        "box": entry.get("box"),
        "outline": entry.get("outline"),
        "items": [],
        "status": status,
        "headline": FALLS[status],
        "risks": rs,
        "fixes": fixes,
        "questions": questions,
        "note": None,
        "answers": a,
        "judged": True,
        "details": {"judged": j["basis"], "family": entry["piece"].get("family", "")},
    }


# --- motion for the page's 3D viewer ----------------------------------------------------------


def trajectory(entry: dict, answers: dict, scenario: str, variant: str, seed: int) -> dict:
    """The simulation the card's viewer plays: `scenario` is quake, child or adult; `variant` is as_is,
    anchor (strapped), locks (one drawer at a time) or moved (the hard things off the top)."""
    entry = tidy(entry)
    est = entry["estimate"]
    base = Case.from_dict(entry["template"])
    a = dict(answers)
    if variant == "anchor":
        a["anchored"] = "yes"
    if variant == "locks":
        a["locks"] = True
    if variant == "moved":
        a["moved"] = sorted(set(a.get("moved", [])) | set(hazards(base)))
    d, size, depth = configure(base, est["depth_is_guess"], a)
    anchored, locks = a.get("anchored") == "yes", bool(a.get("locks"))
    if scenario == "quake":
        hz = None if a.get("floor") == "ground" else UPPER_FLOOR_HZ
        return shake(d, anchored=anchored, seed=seed, building_hz=hz, trace=True, locks=locks).trace or {}
    s = elderly_test(d, anchored=anchored) if scenario == "adult" else child_test(d, size, depth, anchored, locks)
    return simulate(d, s, trace=True).trace or {}


def child_test(d: Case, size: float, depth: float, anchored: bool, locks: bool) -> Scenario:
    """The child test the card's verdict rests on: the worst one that fails, or might."""
    test = risks(d, size, depth, anchored=anchored, locks=locks)["child"]["test"]
    top = d.top_drawer()
    only_open = frozenset({top.index}) if locks and top else None
    return next(t for t in f2057_tests(d, anchored=anchored, only_open=only_open) if t.key == test)
