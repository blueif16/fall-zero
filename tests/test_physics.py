from dataclasses import replace

import pytest

from fall_zero.furniture import ANCHOR_RATING_N, Case, TopItem, Zone
from fall_zero.physics import Scenario, elderly_test, f2057_tests, rocking_threshold_g, statics, tip_force
from fall_zero.sim import simulate

TALL = Case(0.80, 0.48, 1.23, zones=(Zone(rows=6),))  # tall, narrow particleboard chest
WIDE = Case(1.60, 0.48, 0.78, zones=(Zone(rows=3, cols=2),))  # wide, low 6-drawer, MALM-sized
LOW_HARDWOOD = Case(1.00, 0.55, 0.75, material="solid_hardwood")
BOOKCASE = Case(0.80, 0.28, 2.02, zones=(Zone("open", shelves=5, contents="books", fill=0.5),))  # BILLY-sized
WARDROBE = Case(1.00, 0.55, 1.90, zones=(Zone(share=0.25, rows=2), Zone("doors", 0.75, cols=2, shelves=1)))
RANGE = Case(0.76, 0.66, 0.91, material="steel", density_scale=4.0,
             zones=(Zone(share=0.18), Zone("doors", 0.62, hinge="bottom"), Zone("open", 0.20)))  # fmt: skip
DRESSERS = {"tall": TALL, "wide": WIDE, "low_hardwood": LOW_HARDWOOD, "bookcase": BOOKCASE, "wardrobe": WARDROBE,
            "range": RANGE}  # fmt: skip


def all_scenarios(d: Case) -> list[Scenario]:
    base = f2057_tests(d) + [elderly_test(d)]
    return base + [replace(s, anchored=True) for s in base]


@pytest.mark.parametrize("name", DRESSERS)
def test_mujoco_agrees_with_statics(name):
    """An independent physics engine reaches the same verdict wherever the margin isn't razor thin."""
    d = DRESSERS[name]
    for s in all_scenarios(d):
        st = statics(d, s)
        if abs(st.margin - 1) < 0.05 and not s.anchored:
            continue
        assert simulate(d, s).tipped == st.tips, f"{s.key} anchored={s.anchored} margin={st.margin:.2f}"


@pytest.mark.parametrize("name", DRESSERS)
def test_pull_test_prediction_brackets_mujoco(name):
    """The luggage-scale pull: just under the predicted force it stands, just over it tips."""
    d = DRESSERS[name]
    f = tip_force(d, d.height)
    pull = Scenario("pull", "pull", frozenset(), horizontal_z=d.height)
    assert not simulate(d, replace(pull, horizontal_N=0.9 * f)).tipped
    assert simulate(d, replace(pull, horizontal_N=1.1 * f)).tipped


def test_unanchored_tall_and_wide_fail_the_child_test():
    for d in (TALL, WIDE):
        child = next(s for s in f2057_tests(d) if s.key == "child_on_drawer")
        assert statics(d, child).tips


def test_wall_strap_fixes_every_failure():
    for d in DRESSERS.values():
        for s in f2057_tests(d, anchored=True) + [elderly_test(d, anchored=True)]:
            st = statics(d, s)
            assert not st.tips and st.anchor_needed_N < ANCHOR_RATING_N


def test_tv_on_top_steadies_it_against_pulls_but_not_shaking():
    """A centered TV adds weight behind the tipping edge, so slow pulls need more force. It also
    raises the center of gravity, so less shaking starts it rocking."""
    tv = replace(WIDE, top_items=(TopItem("TV", "tv", mass=20, width=1.2, depth=0.25, height=0.75),))
    for s in f2057_tests(WIDE):
        assert statics(tv, s).margin > statics(WIDE, s).margin
    assert rocking_threshold_g(tv) < rocking_threshold_g(WIDE)


def test_tip_force_grows_with_mass():
    heavier = replace(TALL, density_scale=1.2)
    assert tip_force(heavier, 1.0) > tip_force(TALL, 1.0)
