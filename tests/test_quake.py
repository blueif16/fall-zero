"""Items on top and the staged earthquake."""

from dataclasses import replace

from fall_zero.analyze import separate
from fall_zero.furniture import Case, TopItem, Zone
from fall_zero.physics import rocking_threshold_g
from fall_zero.sim import STAGES, ground_motion, shake

TV = TopItem("TV", "tv", mass=3.5, width=0.62, depth=0.22, height=0.40, x=-0.14)
BOXES = TopItem("boxes", "box", mass=3.0, width=0.32, depth=0.35, height=0.34, x=0.26)
# The nursery sample: a tall particleboard chest with a TV and boxes on top
NURSERY = Case(0.90, 0.48, 1.20, zones=(Zone(rows=6),), top_items=tuple(separate(Case(0.90, 0.48, 1.20), [TV, BOXES])))


def test_items_on_top_never_overlap():
    a, b = NURSERY.top_items
    side_by_side = (a.width + b.width) / 2 <= abs(a.x - b.x)
    front_to_back = (a.depth + b.depth) / 2 <= abs(a.y - b.y)
    assert side_by_side or front_to_back


def test_items_on_top_raise_the_center_of_gravity():
    assert rocking_threshold_g(NURSERY) < rocking_threshold_g(replace(NURSERY, top_items=()))


def test_each_stage_peaks_at_its_acceleration():
    t, acc, _ = ground_motion()
    start = 1.0
    for stage in STAGES:
        window = (t >= start + 0.6) & (t < start + stage.seconds)
        assert abs(abs(acc[window, 1]).max() - stage.pga_g) < 0.01
        start += stage.seconds


def test_upper_floor_quake_topples_the_loaded_chest_but_not_when_strapped():
    """On an upper floor (building swaying at 1.5 Hz) the chest falls in at least one of three
    simulated earthquakes; strapped to the wall it never does."""
    runs = [shake(NURSERY, seed=s, building_hz=1.5) for s in (1, 2, 3)]
    assert any(r.fell_at for r in runs)
    assert not any(shake(NURSERY, anchored=True, seed=s, building_hz=1.5).fell_at for s in (1, 2, 3))


def test_drawers_slide_out_and_topple_the_chest_unless_interlocked():
    """On the ground floor the shut drawers slide out on their rollers and the chest falls in at least
    one of three simulated earthquakes; with interlocks at most one drawer opens and it stays up."""
    runs = [shake(NURSERY, seed=s) for s in (1, 2, 3)]
    assert all(r.drawers_out_at for r in runs)
    assert any(r.fell_at for r in runs)
    locked = [shake(NURSERY, seed=s, locks=True) for s in (1, 2, 3)]
    assert all(sum(len(st["drawers_out"]) for st in r.stages) <= 1 for r in locked)
    assert not any(r.fell_at for r in locked)
