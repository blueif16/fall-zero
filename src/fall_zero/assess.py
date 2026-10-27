"""What the user sees: each analyzed piece as verdicts, fixes and questions instead of numbers.

Every risk (a climbing child, an adult grabbing it, an earthquake) gets one of three answers:
tips, maybe, or holds. Each fix carries what the risks become once it's done, checked by re-running
the physics. When something is "maybe", the card asks the questions whose answers would settle it.

The child and adult answers come from statics over the plausible sizes (well under a second). The
earthquake answer comes from simulated earthquakes (`sim.shake`), several per variant, in parallel
and cached; without `simulate` it falls back to the rocking threshold.

Each thing on top is judged on its own: is it hard, how hard would it hit (weight x fall height),
and does it fall in the simulated earthquake. Only things that would hurt someone go in the fix.
"""

import multiprocessing
import os
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace

from fall_zero.analyze import child_verdicts, elderly_verdict, plausible, verdict
from fall_zero.furniture import Dresser, TopItem
from fall_zero.physics import G, elderly_test, f2057_tests, rocking_threshold_g, statics
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

DEPTH_ANSWERS = {"shallow": 0.38, "standard": 0.45, "deep": 0.55}
MATERIAL_ANSWERS = {"hardwood": "solid_hardwood", "softwood": "solid_softwood", "board": "particleboard"}
STATUS = {"pass": "holds", "uncertain": "maybe", "fail": "tips"}
ITEM_WORD = {"tv": "TV", "box": "boxes", "basket": "basket", "lamp": "lamp", "plant": "plant", "books": "books",
             "decor": "decoration", "other": "item"}  # fmt: skip

# What each child test means when it fails, worst first
CHILD_SAYS = {
    "child_on_drawer": "A child standing on an open drawer pulls it over",
    "horizontal_force": "A child tugging the top drawer pulls it over",
    "clothing_load": "Full drawers pulled open tip it on their own",
}


def configure(d: Dresser, depth_is_guess: bool, answers: dict) -> tuple[Dresser, float, float]:
    """The template after the user's answers, with how far its width/height and depth may still be off."""
    size, depth = 0.10, 0.15 if depth_is_guess else 0.05
    if answers.get("depth") in DEPTH_ANSWERS:
        d, depth = replace(d, depth=DEPTH_ANSWERS[answers["depth"]]), 0.08
    if m := answers.get("measured"):
        d = replace(d, width=m["width_cm"] / 100, depth=m["depth_cm"] / 100, height=m["height_cm"] / 100)
        size = depth = 0.03
    if answers.get("material") in MATERIAL_ANSWERS:
        d = replace(d, material=MATERIAL_ANSWERS[answers["material"]])
    moved = set(answers.get("moved", [])) | (set(range(len(d.top_items))) if answers.get("cleared_top") else set())
    if moved:
        d = replace(d, top_items=tuple(it for i, it in enumerate(d.top_items) if i not in moved))
    return d, size, depth


# --- simulated earthquakes ----------------------------------------------------------------

_pool: ProcessPoolExecutor | None = None
_quake_cache: dict[str, dict] = {}


def _shake_one(job: tuple[Dresser, bool, float | None, int]) -> dict:
    d, anchored, hz, seed = job
    q = shake(d, anchored=anchored, seed=seed, building_hz=hz)
    items = {name: s["label"] for s in q.stages for name in s["items_fell"]}
    return {"seed": seed, "fell_at": q.fell_at, "items": items}


def quakes(variants: list[tuple[Dresser, bool]], hz: float | None) -> list[dict]:
    """Shake each (template, anchored) variant with the same simulated earthquakes, all in parallel.
    Per variant: {"runs", "fell" (how many it fell over in), "seeds" (each run's outcome)}."""
    global _pool
    keys = [repr((d, anchored, hz)) for d, anchored in variants]
    todo = [(d, anchored, hz, seed) for (d, anchored), k in zip(variants, keys, strict=True)
            if k not in _quake_cache for seed in QUAKE_SEEDS]  # fmt: skip
    if todo:
        # spawn, not fork: the server is multithreaded
        _pool = _pool or ProcessPoolExecutor(min(12, os.cpu_count() or 4), multiprocessing.get_context("spawn"))
        runs = list(_pool.map(_shake_one, todo))
        for d, anchored in variants:
            k = repr((d, anchored, hz))
            if k not in _quake_cache:
                mine = [r for (dd, aa, _, _), r in zip(todo, runs, strict=True) if (dd, aa) == (d, anchored)]
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


def risks(d: Dresser, size: float, depth: float, anchored: bool = False, locks: bool = False,
          quake: dict | None = None) -> dict[str, dict]:  # fmt: skip
    variants = plausible(d, depth, size)
    only_open = frozenset({d.top_drawer().index}) if locks else None
    child = child_verdicts(variants, anchored=anchored, only_open=only_open)
    worst = next((k for k in CHILD_SAYS if child[k]["verdict"] == "fail"), None)
    unsure = next((k for k in CHILD_SAYS if child[k]["verdict"] == "uncertain"), None)
    if worst:
        child_risk = {"status": "tips", "says": CHILD_SAYS[worst], "test": worst}
    elif unsure:
        child_risk = {"status": "maybe", "says": CHILD_SAYS[unsure].replace(" pulls", " might pull")
                      .replace(" tip it", " might tip it"), "test": unsure}  # fmt: skip
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
    return it.short or ITEM_WORD.get(it.kind, "item")


def item_hazard(d: Dresser, it: TopItem, falls: str | None) -> dict:
    """Would it hurt someone? Hard or soft, and how hard it would hit: weight x height it falls from."""
    drop = d.height + it.z + it.height / 2
    energy = it.mass * G * drop
    if it.kind == "tv" or (it.hard and energy >= SERIOUS_J):
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
    return {"level": level, "why": why, "energy_J": round(energy, 1), "falls": falls}


# --- the card ---------------------------------------------------------------------------------


def assess(entry: dict, answers: dict | None = None, simulate_quakes: bool = False) -> dict:
    """One analyzed piece of the report (`analyze()`'s `pieces[i]`) as a card."""
    a = answers or {}
    est = entry["estimate"]
    base = Dresser(**entry["template"])
    d, size, depth = configure(base, est["depth_is_guess"], a)
    anchored, locks = a.get("anchored") == "yes", bool(a.get("locks"))
    moved = set(a.get("moved", [])) | (set(range(len(base.top_items))) if a.get("cleared_top") else set())
    upper = a.get("floor") != "ground"
    hz = UPPER_FLOOR_HZ if upper else None

    # Which things on top would hurt someone if they fell: moving those is the fix
    first_pass = {i: item_hazard(base, it, None) for i, it in enumerate(base.top_items)}
    to_move = [i for i, h in first_pass.items() if h["level"] != "fine"]

    # Every variant the card shows, shaken by the same simulated earthquakes in one parallel batch
    variants = {"now": (d, anchored)}
    if not anchored:
        variants["anchor"] = (d, True)
    if to_move and not set(to_move) <= moved:
        variants["moved"] = (configure(base, est["depth_is_guess"], a | {"moved": sorted(moved | set(to_move))})[0],
                             anchored)  # fmt: skip
    q = dict(zip(variants, quakes(list(variants.values()), hz), strict=True)) if simulate_quakes else {}
    floor_known = "floor" in a

    def quake_for(key: str) -> dict | None:
        if key not in q:
            return None
        return quake_risk(q[key], variants[key][1], floor_known, upper)

    def after(key: str, **changes) -> dict[str, str]:
        dd, sz, dp = configure(base, est["depth_is_guess"], a | changes)
        is_anchored = changes.get("anchored", a.get("anchored")) == "yes"
        already = (key == "anchor" and anchored) or (key == "moved" and set(to_move) <= moved)
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
                      "moved": i in moved, **item_hazard(base, it, falls)})  # fmt: skip

    fixes = []
    if status != "holds" or anchored:
        fixes.append({
            "key": "anchor", "icon": "strap", "title": "Strap it to the wall",
            "why": "Check behind the top for a strap; if there's none, add one. About $15, 10 minutes."
            if a.get("anchored") == "unsure" else "An anti-tip strap screwed into the wall. About $15, 10 minutes.",
            "after": after("anchor", anchored="yes"), "answer": {"anchored": "yes"}, "done": anchored,
        })  # fmt: skip
    if not anchored and current["child"] != "holds" and d.rows * d.cols > 1:
        with_locks = after("now", locks=True)
        if with_locks != current or locks:
            fixes.append({"key": "locks", "icon": "lock", "title": "Let only one drawer open at a time",
                          "why": "Drawer interlocks stop several open drawers from pulling it forward.",
                          "after": with_locks, "answer": {"locks": True}, "done": locks})  # fmt: skip
    if to_move:
        # worst first: the TV and the heaviest hits lead the title
        to_move.sort(key=lambda i: (items[i]["level"] != "danger", -items[i]["energy_J"]))
        hits = [items[i] for i in to_move]
        listed = " and ".join(h["short"] for h in hits[:2]) + (f" and {len(hits) - 2} more" if len(hits) > 2 else "")
        falling = [h["short"] for h in hits if h["falls"]]
        why = hits[0]["why"].split(";")[0] + ". " if len(hits) == 1 else \
            f"{sum(base.top_items[i].mass for i in to_move):.1f} kg of hard things, {d.height:.1f} m up. "  # fmt: skip
        if falling:
            why += f"In the simulated earthquakes the {' and '.join(falling)} fell off."
        elif any(base.top_items[i].breakable for i in to_move):
            why += "If the dresser tips or gets bumped, it comes down and shatters."
        else:
            why += "If the dresser tips, it comes down first, onto whoever is in front."
        target = sorted(moved | set(to_move))
        with_moved = after("moved", moved=target)
        fixes.append({"key": "moved", "icon": "top", "title": f"Move the {listed} somewhere low", "why": why,
                      "after": with_moved if with_moved != current else None, "answer": {"moved": target},
                      "done": set(to_move) <= moved})  # fmt: skip
    if status != "holds":
        near = est.get("nearby_bed_or_crib")
        fixes.append({"key": "distance", "icon": "distance",
                      "title": f"Keep the {near} {fall_m:.1f} m away" if near else
                      f"Keep beds and play mats {fall_m:.1f} m away",
                      "why": f"If it falls, its top lands about {d.height:.1f} m out.", "after": None})  # fmt: skip
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
    if current["child"] == "maybe" and not anchored:
        measured = "measured" in a
        if est["depth_is_guess"] and "depth" not in a and not measured:
            questions.append({"key": "depth", "title": "How deep is it, front to back?",
                              "hint": "A photo can't show this well.",
                              "options": [{"label": "Under 40 cm", "sub": "16 in", "value": "shallow"},
                                          {"label": "40–50 cm", "sub": "16–20 in", "value": "standard"},
                                          {"label": "Over 50 cm", "sub": "20 in", "value": "deep"},
                                          {"label": "Not sure", "value": "unsure"}]})  # fmt: skip
        if "material" not in a and not measured:
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

    return {
        "name": entry["piece"]["name"],
        "box": entry.get("box"),
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
            "top_load_kg": round(d.top_load_kg, 1),
            "preset": est["preset"],
            "material": d.material,
            "size_basis": est["size_basis"],
            "rocking_starts_g": round(rocking_threshold_g(d), 2),
            "spread": {"size": size, "depth": depth},
            "quakes": {k: {"fell": v["fell"], "runs": v["runs"]} for k, v in q.items()},
            "floor": "upper" if upper else "ground",
        },  # fmt: skip
    }


def _shown_seed(q: dict | None) -> int:
    """The simulated earthquake to show: one whose outcome matches most runs."""
    if not q:
        return QUAKE_SEEDS[0]
    fell_most = q["fell"] * 2 > q["runs"]
    return next((r["seed"] for r in q["seeds"] if bool(r["fell_at"]) == fell_most), QUAKE_SEEDS[0])


def assess_all(report: dict, simulate_quakes: bool = False) -> list[dict]:
    return [assess(e, simulate_quakes=simulate_quakes) for e in report["pieces"] if e["status"] == "analyzed"]


# --- motion for the page's 3D viewer ----------------------------------------------------------


def trajectory(entry: dict, answers: dict, scenario: str, variant: str, seed: int) -> dict:
    """The simulation the card's viewer plays: `scenario` is quake, child or adult; `variant` is as_is,
    anchor (strapped) or moved (the hard things off the top)."""
    est = entry["estimate"]
    base = Dresser(**entry["template"])
    a = dict(answers)
    if variant == "anchor":
        a["anchored"] = "yes"
    if variant == "moved":
        hazards = [i for i, it in enumerate(base.top_items) if item_hazard(base, it, None)["level"] != "fine"]
        a["moved"] = sorted(set(a.get("moved", [])) | set(hazards))
    d, *_ = configure(base, est["depth_is_guess"], a)
    anchored = a.get("anchored") == "yes"
    if scenario == "quake":
        hz = None if a.get("floor") == "ground" else UPPER_FLOOR_HZ
        return shake(d, anchored=anchored, seed=seed, building_hz=hz, trace=True).trace or {}
    if scenario == "adult":
        s = elderly_test(d, anchored=anchored)
    else:
        test = risks(d, *configure(base, est["depth_is_guess"], a)[1:], anchored=anchored)["child"]["test"]
        s = next(t for t in f2057_tests(d, anchored=anchored) if t.key == test)
    return simulate(d, s, trace=True).trace or {}
