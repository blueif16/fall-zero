"""The whole room as one scene: pieces placed as the photo shows them, simulated together."""

from fall_zero.furniture import Case, Zone
from fall_zero.physics import f2057_tests
from fall_zero.room import STANDING, layout
from fall_zero.sim import Placed, quake_scenario, shake_scene, simulate_scene

TALL = Case(0.80, 0.48, 1.23, zones=(Zone(rows=6),))  # tall, narrow particleboard chest
BOOKCASE = Case(0.80, 0.28, 2.02, zones=(Zone("open", shelves=5, contents="books", fill=0.5),))
CONSOLE = Case(1.60, 0.42, 0.45, zones=(Zone(rows=1, cols=2),))


def test_pieces_stand_in_the_photos_order_against_one_wall():
    """The living-room sample: console, bookcase and a mirror the engine doesn't build, by their outlines."""
    entries = [{"box": (501, 548, 1115, 835)}, {"box": (90, 0, 507, 912)}, {"box": (1052, 122, 1254, 679)}]
    spots = layout(entries, [CONSOLE, BOOKCASE, None])
    xs = [x for x, *_ in spots]
    assert xs[1] > xs[0] > xs[2]  # seen from the front the photo's left is +x: bookcase, console, mirror
    row = sorted(spots)
    assert all(a[0] + a[2] / 2 < b[0] - b[2] / 2 for a, b in zip(row, row[1:], strict=False))  # nothing overlaps
    assert len({round(y - depth / 2, 6) for _, y, _, depth, _ in spots}) == 1  # backs against one wall
    assert 1.0 < spots[2][4] < 1.6  # the mirror's height, from its outline at the others' scale


def test_the_child_test_loads_only_the_piece_it_is_on():
    child = next(s for s in f2057_tests(TALL) if s.key == "child_on_drawer")
    pieces = [Placed(TALL, child, x=0.6, prefix="p0_"), Placed(TALL, STANDING, x=-0.6, prefix="p1_")]
    climbed, beside = simulate_scene(pieces, trace=True)
    assert climbed.tipped and not beside.tipped
    assert [e[2] for e in climbed.trace["events"]] == [0]


def test_a_room_shakes_together_and_each_piece_keeps_its_own_fix():
    """Two tall chests side by side on an upper floor: the loose one falls in at least one of three
    simulated earthquakes, the strapped one in none; each has its own strap and tag in the trace."""
    runs = [shake_scene([Placed(TALL, quake_scenario(TALL), x=0.6, prefix="p0_"),
                         Placed(TALL, quake_scenario(TALL, anchored=True), x=-0.6, prefix="p1_")],
                        seed=s, building_hz=1.5, trace=s == 1) for s in (1, 2, 3)]  # fmt: skip
    assert any(loose.fell_at for loose, _ in runs)
    assert not any(strapped.fell_at for _, strapped in runs)
    trace = runs[0][0].trace
    assert len(trace["pieces"]) == 2 and len(trace["straps"][0]) == 6
    assert trace["phases"] == {"quiet": 1.0} and all(t > 1.0 for t, *_ in trace["events"])  # after it starts
