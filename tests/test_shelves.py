"""Things standing on a piece's open shelves: each on the shelf its outline rests on, and the shelf's own
contents (rows of books) packed around them and the dividers, never through them."""

from dataclasses import replace

from fall_zero.analyze import measure_items
from fall_zero.assess import item_hazard
from fall_zero.furniture import Case, TopItem, Zone, examples, runs
from fall_zero.knowledge import ItemSpec, Thing

BILLY = examples()["ikea_billy_80"][1]  # 80 x 28 x 202 cm, six surfaces from 10 cm to 169 cm
LEVELS = BILLY.shelf_levels(("open",))
PIECE = (100, 0, 500, 1010)  # its outline: 400 px across 0.80 m, 1010 px up 2.02 m, 2 mm a pixel


def row(z: float) -> float:
    """The photo row of a height above the floor, in PIECE's outline."""
    return 1010 - z / 0.002


def spec(name: str, shelf_from_top: int = 0, **kw) -> ItemSpec:
    base = {"short_name": name, "shape": "block", "material": "", "hard": True, "breakable": False,
            "tempting": False, "kg": 2.0, "depth_cm": 20, "shelf_from_top": shelf_from_top}  # fmt: skip
    return ItemSpec(**base | kw)


def test_things_on_shelves_stand_on_the_shelf_their_outline_rests_on():
    """The living-room sample's bookcase: a plant pot on the highest shelf, a basket in the middle, a flat stack
    of books low down, a vase on top; a toy SAM missed goes where the describe step said."""

    def on(name: str, where: str = "shelf") -> Thing:
        return Thing(name=name, sam_concept=name, where=where)

    things = [
        (on("plant pot"), (380, row(LEVELS[5]) - 60, 440, row(LEVELS[5]) + 4)),
        (on("wicker basket"), (130, row(LEVELS[3]) - 40, 200, row(LEVELS[3]) - 6)),
        (on("stack of books"), (330, row(LEVELS[1]) - 50, 450, row(LEVELS[1]))),
        (on("vase", "top"), (200, -80, 240, 2)),
        (on("toy"), None),
        (on("clock"), (300, -50, 340, 3)),  # said to be on a shelf, but it rests on the top
    ]
    infos = [spec("plant"), spec("basket"), spec("books"), spec("vase"), spec("toy", shelf_from_top=2), spec("clock")]
    items = measure_items(BILLY, PIECE, things, infos)
    assert [it.shelf for it in items] == [5, 3, 1, None, 4, None]
    assert [BILLY.base_of(it) for it in items[:3]] == [LEVELS[5], LEVELS[3], LEVELS[1]]
    basket, books = items[1], items[2]
    assert basket.x > 0 > books.x  # the photo's left is +x, seen from the front
    assert abs(basket.width - 0.14) < 0.01 and abs(basket.height - 0.068) < 0.01


def test_shelf_contents_pack_around_things_and_dividers():
    """On every surface the loose blocks of contents never overlap each other, a thing standing there or a
    divider, and they fill the share of the free room the zone says."""
    cube = Case(1.47, 0.39, 1.465, zones=(Zone("open", cols=4, shelves=3, contents="books", fill=0.5),),
                top_items=(TopItem("basket", width=0.25, height=0.2, x=0.2, shelf=1),
                           TopItem("plant", width=0.12, height=0.25, x=-0.55, shelf=3),
                           TopItem("radio", width=0.2, height=0.12)))  # fmt: skip
    for d in (cube, BILLY):
        parts = d.parts()
        walls = [(p.center[0] - p.size[0] / 2, p.center[0] + p.size[0] / 2) for p in parts if "divider" in p.name]
        for z in d.shelf_levels(("open",)):
            here = [p for p in parts if p.kind in ("fill", "load") and abs(p.center[2] - p.size[2] / 2 - z) < 0.002]
            spans = sorted((p.center[0] - p.size[0] / 2, p.center[0] + p.size[0] / 2) for p in here) + walls
            spans.sort()
            assert all(a[1] <= b[0] + 1e-9 for a, b in zip(spans, spans[1:], strict=False)), (d.width, z, spans)
            assert all(p.size[2] > 0.03 for p in here)
    assert abs(sum(b - a for a, b in runs(-0.4, 0.4, [], 0.3)) - 0.3) < 0.01  # 30 cm of books on an 80 cm shelf
    around = runs(-0.4, 0.4, [(-0.1, 0.1)], 0.3)  # a 20 cm basket in the middle: books both sides, 1 cm clear
    assert all(b <= -0.11 or a >= 0.11 for a, b in around) and {a < 0 for a, _ in around} == {True, False}


def test_a_thing_low_on_a_shelf_falls_from_lower_down():
    vase = TopItem("vase", mass=1.5, width=0.12, height=0.25, x=0.2, breakable=True)
    low, high = (item_hazard(BILLY, replace(vase, shelf=s), None) for s in (1, 5))
    on_top = item_hazard(BILLY, vase, None)
    assert low["drop_m"] < high["drop_m"] < on_top["drop_m"]
    assert abs(low["drop_m"] - (LEVELS[1] + 0.125)) < 0.01
    assert low["level"] == "caution" and on_top["level"] == "danger"


def test_a_thing_squeezed_under_a_falling_piece_is_not_shot_across_the_room():
    """Each loose thing's frame sits at its own center, and no loose thing moves faster than a fall could make it
    (a vase caught between a falling bookcase and the floor was shot out at 37 m/s and slid 212 m)."""
    import mujoco
    import numpy as np

    from fall_zero.sim import LOOSE_MAX_MS, Placed, _Loose, quake_scenario, scene_mjcf

    d = replace(BILLY, top_items=(TopItem("vase", mass=0.5, width=0.12, depth=0.1, height=0.25, shelf=4),))
    model = mujoco.MjModel.from_xml_string(scene_mjcf([Placed(d, quake_scenario(d), prefix="p0_")], room=True))
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    vase = model.body("p0_item_0").id
    assert np.allclose(data.xpos[vase], data.xipos[vase], atol=1e-6)  # its frame is its center
    assert abs(data.xipos[vase][2] - (LEVELS[4] + 0.125)) < 0.01  # on the shelf it was put on

    loose = _Loose(model)
    dof = model.jnt_dofadr[model.body_jntadr[vase]]
    data.qvel[dof : dof + 3] = (0, 30.0, 0)
    loose.cap(data)
    assert np.linalg.norm(data.qvel[dof : dof + 3]) <= LOOSE_MAX_MS + 1e-9
