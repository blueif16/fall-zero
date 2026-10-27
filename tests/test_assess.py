"""The cards: a strapped piece holds, a fix's preview matches doing it, and answered questions go away."""

from dataclasses import asdict

from fall_zero.assess import assess, item_hazard, trajectory
from fall_zero.furniture import TopItem, presets


def entry(key: str, **estimate) -> dict:
    """A report entry for a preset, as analyze() would produce it."""
    label, d = presets()[key]
    est = {"preset": key, "depth_is_guess": True, "items_on_top": [], "nearby_bed_or_crib": None,
           "size_basis": "test"} | estimate  # fmt: skip
    return {"piece": {"name": label}, "template": {k: v for k, v in asdict(d).items() if k != "notes"}, "estimate": est}


def test_tall_chest_tips_and_asks_about_the_strap():
    card = assess(entry("chest_tall_6"))
    assert card["status"] == "tips"
    assert card["questions"][0]["key"] == "anchored"
    assert card["fixes"][0]["key"] == "anchor"


def test_strap_makes_everything_hold():
    """Regression: a held strap balances the moments exactly, which once read as a tip."""
    card = assess(entry("chest_tall_6"), {"anchored": "yes"})
    assert card["status"] == "holds"
    assert {r["status"] for r in card["risks"].values()} == {"holds"}
    assert not card["questions"]
    assert card["fixes"][0]["done"]


def test_fix_preview_matches_doing_it():
    e = entry("chest_tall_6")
    for fix in assess(e)["fixes"]:
        if fix["after"]:
            done = assess(e, fix["answer"])
            assert fix["after"] == {k: r["status"] for k, r in done["risks"].items()}, fix["key"]


def test_answered_questions_are_not_asked_again():
    keys = [q["key"] for q in assess(entry("chest_tall_6"), {"anchored": "no"})["questions"]]
    assert "anchored" not in keys


def test_soft_or_light_things_on_top_are_never_the_fix():
    """A plush toy can't hurt anyone and light books won't do real harm; a ceramic pot and a TV can."""
    items = (
        TopItem("beige bunny plush", "decor", mass=0.3, width=0.2, height=0.2, x=-0.3, short="bunny", hard=False),
        TopItem("children's books", "books", mass=0.8, width=0.2, height=0.15, x=-0.05, short="books"),
        TopItem("ceramic plant pot", "plant", mass=1.2, width=0.15, height=0.2, x=0.15, short="plant", breakable=True),
    )
    e = entry("dresser_3")
    e["template"]["top_items"] = [asdict(i) for i in items]
    e["items"] = [{"name": i.name, "kind": i.kind, "box": None} for i in items]
    card = assess(e)
    levels = {i["short"]: i["level"] for i in card["items"]}
    assert levels == {"bunny": "fine", "books": "fine", "plant": "caution"}
    move = next(f for f in card["fixes"] if f["key"] == "moved")
    assert move["title"] == "Move the plant somewhere low"
    assert move["answer"] == {"moved": [2]}


def test_a_tv_on_top_is_always_a_danger():
    tv = TopItem("flat-screen TV", "tv", mass=4.0, width=0.7, depth=0.2, height=0.45, short="TV")
    assert item_hazard(presets()["dresser_3"][1], tv, None)["level"] == "danger"


def test_the_viewer_gets_every_body_every_frame():
    trace = trajectory(entry("chest_tall_6"), {}, "child", "as_is", seed=1)
    assert trace["geoms"] and len(trace["frames"]) > 100
    assert all(len(f) == 7 * trace["nbody"] for f in trace["frames"])
    assert trace["load_geoms"] == ["weight"] and trace["events"]  # the 60 lb weight tips it over
