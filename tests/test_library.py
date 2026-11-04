"""The room library, Fall 0's memory of a home: every checked room is kept with a breakdown of what was
found; a new photo of a known room matches its pieces, carries over what was answered and done, and says
what changed."""

import pytest

from fall_zero import library, store

CALM = {"child": "holds", "adult": "holds", "quake": "holds"}
TIPS = {"child": "tips", "adult": "maybe", "quake": "tips"}


def report(*pieces, room="living room", width=1000):
    """A report with pieces given as (name, family, x of the center as a share of the width)."""
    return {"room": room, "size": [width, 600], "still": "still.jpg", "pieces": [
        {"piece": {"name": n, "family": f}, "box": [x * width - 50, 100, x * width + 50, 500], "status": "analyzed"}
        for n, f, x in pieces]}  # fmt: skip


def strap(done=False):
    return {"key": "anchor", "kind": "strap", "title": "Strap it to the wall", "answer": {"anchored": "yes"},
            "done": done, "after": CALM}  # fmt: skip


def card(name, now=TIPS, fixes=(), questions=(), items=(), answers=None):
    return {"name": name, "risks": {k: {"status": s, "says": f"{k}: {s}"} for k, s in now.items()},
            "fixes": list(fixes), "questions": list(questions), "items": list(items), "answers": answers or {}}  # fmt: skip


LIVING = report(("tall white bookcase", "bookcase", 0.2), ("low TV stand", "TV stand", 0.5), ("floor mirror", "mirror", 0.8))


@pytest.fixture
def local(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "LOCAL", tmp_path)
    return tmp_path


def test_a_checked_room_is_kept_with_a_breakdown_of_each_piece():
    cards = [card("tall white bookcase", CALM, [strap(done=True)], answers={"anchored": "yes"}),
             card("low TV stand", items=[{"short": "TV", "level": "danger"}, {"short": "plush toy", "level": "fine"}]),
             card("floor mirror", questions=[{"key": "judged", "title": "Is it fixed to the wall?"}])]  # fmt: skip
    rec = library.record(LIVING, cards, run="run1", now="2026-11-02T10:00:00+00:00")
    assert rec["name"] == "living room" and rec["run"] == "run1"
    bd = rec["breakdown"]
    assert bd["status"] == TIPS  # the worst of each scenario across the room
    book, stand, mirror = bd["pieces"]
    assert book["status"] == CALM and book["done"] == ["Strap it to the wall"]
    assert stand["falls"] == ["TV"]  # only what would hurt someone
    assert mirror["open"] == ["Is it fixed to the wall?"]
    assert len({p["id"] for p in bd["pieces"]}) == 3
    assert [p["id"] for p in rec["pieces"]] == [p["id"] for p in bd["pieces"]]


def test_each_check_of_a_room_keeps_one_dated_snapshot():
    cards = [card("tall white bookcase"), card("low TV stand"), card("floor mirror")]
    first = library.record(LIVING, cards, run="run1", now="2026-11-02T10:00:00+00:00")
    tapped = library.record(LIVING, cards, run="run1", previous=first, now="2026-11-02T10:05:00+00:00")
    assert [h["run"] for h in tapped["history"]] == ["run1"]  # a tap re-saves the same check
    later = library.record(LIVING, cards, run="run2", previous=tapped, now="2026-11-09T09:00:00+00:00")
    assert [h["run"] for h in later["history"]] == ["run1", "run2"] and later["created"] == first["created"]


def test_the_library_keeps_rooms_until_one_is_removed(local):
    rec = library.record(LIVING, [card("tall white bookcase"), card("low TV stand"), card("floor mirror")], run="run1")
    library.save("", rec)
    assert [r["name"] for r in library.rooms("")] == ["living room"]
    assert library.get("", rec["id"])["breakdown"] == rec["breakdown"]
    library.remove("", rec["id"])
    assert library.rooms("") == [] and library.get("", rec["id"]) is None


def test_each_browser_keeps_its_own_home_when_deployed(monkeypatch):
    assert library.folder("") == "homes/local/"
    monkeypatch.setattr(store, "REMOTE", True)
    assert library.folder("0" * 32) == f"homes/{'0' * 32}/"
    with pytest.raises(ValueError):
        library.folder("../../threads")


def test_the_pieces_of_a_new_photo_are_matched_by_name_and_place():
    before = library.record(LIVING, [card("tall white bookcase"), card("low TV stand"), card("floor mirror")], run="r1")
    ids = {p["name"]: p["id"] for p in before["pieces"]}
    now = report(("light wood TV stand", "TV stand", 0.45), ("white bookcase", "bookcase", 0.25), ("toy chest", "chest", 0.9))
    assert library.match_pieces(before, now) == {0: ids["low TV stand"], 1: ids["tall white bookcase"]}  # the chest is new


def test_what_was_answered_and_done_carries_over_but_not_what_belongs_to_one_photo():
    book = card("tall white bookcase", CALM, [strap(done=True)],
                answers={"anchored": "yes", "drawers": "full", "moved": [0], "floor": "upper"})  # fmt: skip
    before = library.record(LIVING, [book, card("low TV stand"), card("floor mirror")], run="r1")
    now = report(("white bookcase", "bookcase", 0.25), ("low TV stand", "TV stand", 0.5))
    carried = library.carry(before, library.match_pieces(before, now), now)
    assert carried[0] == {"anchored": "yes", "drawers": "full", "floor": "upper"}  # `moved` named items of one photo
    assert carried[1] == {"floor": "upper"}  # the floor is the room's


def test_a_judged_piece_keeps_its_done_fix_by_kind():
    mirror = card("floor mirror", CALM, [{"key": "fix_0", "kind": "strap", "title": "Strap it", "answer": {"fix_0": True},
                                          "done": True, "after": CALM}], answers={"fix_0": True})  # fmt: skip
    before = library.record(report(("floor mirror", "mirror", 0.5)), [mirror], run="r1")
    now = report(("tall floor mirror", "mirror", 0.5))
    now["pieces"][0] |= {"status": "judged", "judgment": {"fixes": [{"icon": "distance"}, {"icon": "strap"}]}}
    assert library.carry(before, library.match_pieces(before, now), now) == {0: {"fix_1": True}}


def test_what_changed_since_last_time():
    before = library.record(LIVING, [card("tall white bookcase", CALM, [strap(done=True)]),
                                     card("low TV stand", CALM), card("floor mirror")], run="r1")  # fmt: skip
    ids = {p["name"]: p["id"] for p in before["pieces"]}
    now = report(("low TV stand", "TV stand", 0.15), ("tall white bookcase", "bookcase", 0.5), ("toy chest", "chest", 0.9))
    after = library.record(now, [card("low TV stand", TIPS, items=[{"short": "TV", "level": "danger"}]),
                                 card("tall white bookcase", CALM, [strap(done=True)]), card("toy chest")],
                           run="r2", previous=before, ids={0: ids["low TV stand"], 1: ids["tall white bookcase"]})  # fmt: skip
    kinds = {(c["kind"], c["name"]) for c in library.changes(before["breakdown"], after["breakdown"])}
    assert ("new", "toy chest") in kinds and ("gone", "floor mirror") in kinds
    assert ("moved", "low TV stand") in kinds and ("worse", "low TV stand") in kinds
    assert ("added", "low TV stand") in kinds  # the TV now on it
    assert ("kept", "tall white bookcase") in kinds  # the strap still in place
    assert not any(k == "worse" and n == "tall white bookcase" for k, n in kinds)
    worse = next(c for c in library.changes(before["breakdown"], after["breakdown"]) if c["kind"] == "worse")
    assert worse["scenarios"] == ["child", "adult", "quake"]  # the page shows only those that count for the home
