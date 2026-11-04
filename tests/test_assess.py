"""The cards: a strapped piece holds, a fix's preview matches doing it, and answered questions go away."""

from dataclasses import asdict

from fall_zero.assess import HOW, ICONS, assess, configure, item_hazard, judged_card, trajectory
from fall_zero.furniture import Case, TopItem, catalog, examples
from fall_zero.knowledge import tidy


def entry(key: str, **estimate) -> dict:
    """A report entry for a preset, as analyze() would produce it."""
    label, d = examples()[key]
    est = {"example": key, "depth_is_guess": True, "on_it": [], "nearby": None, "size_basis": "test"} | estimate
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
    assert trace["phases"] == {"settle": 1.0, "ramp": 2.0} and trace["events"][0][0] > 1.0  # after it settled


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


def test_a_judged_question_goes_once_a_fix_settles_it():
    """Clipped to the wall, "Is it clipped to the wall?" can't change anything any more."""
    assert not judged_card(judged_entry(), {"fix_0": True})["questions"]


def test_the_drawers_question_counts_what_they_hold_in_every_test():
    """Full drawers pulled open put weight out front; empty ones leave the piece lighter. Asked only where it
    changes what a climbing child or a grabbing adult does, and answered it fills the drawers that much."""
    e = entry("dresser_hardwood_9")
    asked = next(q for q in assess(e)["questions"] if q["key"] == "drawers")
    assert [o["value"] for o in asked["options"]] == ["full", "half", "empty"]
    full, empty = assess(e, {"drawers": "full"}), assess(e, {"drawers": "empty"})
    assert full["risks"]["child"]["status"] != empty["risks"]["child"]["status"]
    assert not any(q["key"] == "drawers" for q in full["questions"])
    assert full["details"]["mass_kg"] == empty["details"]["mass_kg"] == empty["details"]["mass_full_kg"]
    assert (
        full["details"]["holds"][0]["what"] == "clothes"
        and full["details"]["mass_full_kg"] > full["details"]["mass_kg"]
    )
    d, _, _ = configure(Case.from_dict(e["template"]), True, {"drawers": "half"})
    assert d.contents_known and d.mass() == Case.from_dict(e["template"]).mass()  # the empty weight stays empty
    assert sum(p.mass for p in d.parts() if p.kind == "fill") > 0  # but the clothes count with the drawers shut
    assert not any(q["key"] == "drawers" for q in assess(entry("ikea_billy_80"))["questions"])  # nothing to ask


def test_every_fix_carries_its_practical_advice_from_the_catalog():
    """What to buy, the cost and the steps come from skill/catalog/fixes.toml; the anchor is the one the describe
    step named (a range's bracket), or for older reports read from its title."""
    fixes = catalog("fixes")
    toy = TopItem("toy car", mass=0.3, width=0.15, height=0.1, x=0.2, short="toy car", tempting=True)
    cards = []
    for key, est in [("chest_tall_6", {"brand_model": "IKEA HEMNES"}), ("range_30in", {"anchor": "bracket"}),
                     ("range_30in", {"anchor_fix": "Fit the anti-tip bracket"}), ("hutch_kitchen", {})]:  # fmt: skip
        e = entry(key, **est)
        e["template"]["top_items"] = [asdict(toy)]
        cards.append(assess(e))
    for c in cards:
        for f in c["fixes"]:
            assert f["icon"] in ICONS and f["kind"] in fixes, f
            assert f["how"] == {k: fixes[f["kind"]].get(k, [] if k in ("tools", "steps") else "") for k in HOW}
        info = [i for i, f in enumerate(c["fixes"]) if "answer" not in f]
        assert info == list(range(len(c["fixes"]) - len(info), len(c["fixes"])))  # information-only ones last
    kinds = [{f["kind"] for f in c["fixes"]} for c in cards]
    assert {"strap", "recall", "tempting", "heavy_low"} <= kinds[0] and "bracket" in kinds[1] and "bracket" in kinds[2]
    assert "latches" in kinds[3]
    judged = judged_card(judged_entry())["fixes"][0]
    assert judged["kind"] == "strap" and judged["how"]["steps"]


def test_a_toy_up_high_is_a_fix_for_the_child_and_its_preview_matches_doing_it():
    e = entry("chest_tall_6")
    toy = TopItem("toy car", mass=0.3, width=0.15, height=0.1, x=0.2, short="toy car", tempting=True)
    e["template"]["top_items"] = [asdict(toy)]
    e["items"] = [{"name": toy.name, "kind": "block", "box": None}]
    card = assess(e)
    assert card["items"][0] | {"where": "top", "tempting": True} == card["items"][0] and card["items"][0]["kg"] == 0.3
    fix = next(f for f in card["fixes"] if f["key"] == "tempting")
    assert fix["icon"] == "toy" and fix["answer"] == {"moved": [0]}
    done = assess(e, fix["answer"])
    assert next(f for f in done["fixes"] if f["key"] == "tempting")["done"]
    assert (fix["after"] or card["risks"] and {k: r["status"] for k, r in card["risks"].items()}) == {
        k: r["status"] for k, r in done["risks"].items()
    }


# The describe step once returned this, 2,524 characters long, as a vase's short name
GARBLED = (
    "vaseria_leafy_short_name vaseeucalyptuseucalyptuseucalyptusvasemasevasewitheucalyptus_vasethease_d1b7f0e3-"
    "ca7a-42f1-a90f-308de8491f40as vase?eucalyptus vase wi vase_with_eucalyptuslain_propsvase "
) * 12


def test_garbled_or_rambling_text_from_the_model_never_reaches_the_page():
    """A garbled short name gives way to the survey's name for the thing, clipped to a few words; a rambling anchor
    title to the catalog's; a judged fix's garbled title to the catalog's for its icon, and a garbled answer drops."""
    e = entry("chest_tall_6", anchor="strap", anchor_fix="Strap it " * 30, nearby="crib_crib_crib")
    vase = TopItem("small vase with eucalyptus on the top", mass=1.5, width=0.12, height=0.3, short=GARBLED,
                   breakable=True)  # fmt: skip
    e["template"]["top_items"] = [asdict(vase)]
    e["items"] = [{"name": vase.name, "kind": "block", "box": None}]
    card = assess(e)
    assert card["items"][0]["short"] == "small vase with eucalyptus"
    texts = [card["name"], *(f["title"] for f in card["fixes"]), *(h["what"] for h in card["details"]["holds"])]
    assert all(t and len(t) <= 80 and "_" not in t for t in texts), texts
    assert card["fixes"][0]["title"] == catalog("fixes")["strap"]["label"]
    assert next(f for f in card["fixes"] if f["key"] == "distance")["title"].startswith("Keep beds")
    assert tidy(e)["template"]["top_items"][0]["short"] == "small vase with eucalyptus"  # the scene's events too

    j = judged_entry()
    j["judgment"]["fixes"][0]["title"] = GARBLED
    j["judgment"]["question"]["options"].append({"label": GARBLED, "after": j["judgment"]["fixes"][0]["after"]})
    j["judgment"]["child"]["says"] = ""
    judged = judged_card(j)
    assert judged["fixes"][0]["title"] == catalog("fixes")["strap"]["label"]
    assert [o["label"] for o in judged["questions"][0]["options"]] == ["Yes", "No"]
    assert judged["risks"]["child"]["says"] == "Can fall over"
