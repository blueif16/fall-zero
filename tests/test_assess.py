"""The cards: a strapped piece holds, a fix's preview matches doing it, and answered questions go away."""

from dataclasses import asdict

from fall_zero.assess import assess, item_hazard, judged_card, trajectory
from fall_zero.furniture import Case, TopItem, examples


def entry(key: str, **estimate) -> dict:
    """A report entry for a preset, as analyze() would produce it."""
    label, d = examples()[key]
    est = {"example": key, "depth_is_guess": True, "items_on_top": [], "nearby": None,
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
    assert item_hazard(examples()["dresser_3"][1], tv, None)["level"] == "danger"


def test_the_viewer_gets_every_body_every_frame():
    trace = trajectory(entry("chest_tall_6"), {}, "child", "as_is", seed=1)
    assert trace["geoms"] and len(trace["frames"]) > 100
    assert all(len(f) == 7 * trace["nbody"] for f in trace["frames"])
    assert trace["load_geoms"] == ["weight"] and trace["events"]  # the 60 lb weight tips it over


def test_every_worked_example_gets_a_card():
    """Each example in the skill's catalog builds, runs every test and comes back as a card."""
    for key in examples():
        card = assess(entry(key))
        assert card["status"] in ("tips", "maybe", "holds"), key
        assert set(card["risks"]) == {"child", "adult", "quake"}, key


def test_reports_saved_before_zones_still_load():
    old = {"width": 1.0, "depth": 0.55, "height": 1.9, "rows": 2, "cols": 1, "door_zone": 0.75, "doors": 2,
           "shelves": 1, "hanging": True, "material": "particleboard"}  # fmt: skip
    d = Case.from_dict(old)
    assert len(d.drawers()) == 2 and len(d.door_list()) == 2
    assert d.zones[1].contents == "hanging_clothes"


def judged_entry() -> dict:
    after_strap = {"child": "holds", "adult": "holds", "quake": "holds"}
    return {
        "status": "judged",
        "piece": {"name": "floor mirror", "family": "leaning floor mirror"},
        "judgment": {
            "child": {"status": "tips", "says": "A child pulling the frame brings it down"},
            "adult": {"status": "maybe", "says": "Could slide if leaned on"},
            "quake": {"status": "tips", "says": "Falls forward when the floor shakes"},
            "fixes": [{"title": "Clip it to the wall", "why": "Mirror clips hold the top.", "icon": "strap",
                       "after": after_strap}],
            "question": {"title": "Is it clipped to the wall?",
                         "options": [{"label": "Yes", "after": after_strap},
                                     {"label": "No", "after": {"child": "tips", "adult": "maybe", "quake": "tips"}}]},
            "basis": "other-hazards: leaning floor mirrors",
        },
    }  # fmt: skip


def test_a_judged_piece_updates_with_its_fix_and_answer():
    card = judged_card(judged_entry())
    assert card["status"] == "tips" and card["judged"] and card["questions"][0]["key"] == "judged"
    assert judged_card(judged_entry(), {"fix_0": True})["status"] == "holds"
    answered = judged_card(judged_entry(), {"judged": "Yes"})
    assert answered["status"] == "holds" and not answered["questions"]
