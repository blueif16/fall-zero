"""Quasi-static tip-over physics and the test scenarios.

A free-standing piece tips forward when the moments about its front support edge turn
forward. That is exact for slow loads like the ASTM tests and a luggage-scale pull, so the
statics here give the verdicts and margins, and MuJoCo (sim.py) confirms them and renders them.
"""

import math
from dataclasses import dataclass, field

from fall_zero.furniture import (
    ANCHOR_RATING_N,
    CARPET_BLOCK_M,
    CHILD_WEIGHT_N,
    HORIZONTAL_FORCE_N,
    MAX_HANDHOLD_M,
    Dresser,
)

G = 9.81


@dataclass(frozen=True)
class Scenario:
    key: str
    title: str
    open_drawers: frozenset[int]
    fill: bool = False
    block: float = 0.0  # carpet block under the rear supports, m
    vertical_N: float = 0.0  # downward, on the top edge of `load_drawer`'s front
    horizontal_N: float = 0.0  # outward, at `horizontal_z`
    horizontal_z: float = 0.0
    load_drawer: int | None = None  # None: the horizontal force acts on the carcass front
    anchored: bool = False
    standard: str = ""  # where the numbers come from
    assumption: str = ""  # set when no standard backs the numbers


@dataclass(frozen=True)
class Statics:
    restoring_Nm: float
    overturning_Nm: float
    anchor_needed_N: float = 0.0  # strap tension that would hold it (anchored scenarios)
    extras: dict = field(default_factory=dict)

    @property
    def margin(self) -> float:
        """Restoring / overturning moment. Below 1 it tips."""
        return math.inf if self.overturning_Nm <= 0 else self.restoring_Nm / self.overturning_Nm

    @property
    def tips(self) -> bool:
        return self.overturning_Nm > self.restoring_Nm * (1 + 1e-9)

    @property
    def anchor_holds(self) -> bool:
        return self.anchor_needed_N <= ANCHOR_RATING_N


def tilt_angle(d: Dresser, block: float) -> float:
    return math.asin(block / (d.front_support_y - d.rear_support_y)) if block else 0.0


def statics(d: Dresser, s: Scenario) -> Statics:
    """Moments about the front support edge, with the unit tilted forward by the carpet block."""
    phi = tilt_angle(d, s.block)
    y_e = d.front_support_y
    c, sn = math.cos(phi), math.sin(phi)

    def forward_offset(y: float, z: float) -> float:  # horizontal distance in front of the edge
        return (y - y_e) * c + z * sn

    def height(y: float, z: float) -> float:
        return z * c - (y - y_e) * sn

    over = restore = 0.0
    for p in d.parts(open_drawers=s.open_drawers, fill=s.fill):
        m = p.mass * G * forward_offset(p.center[1], p.center[2])
        over, restore = (over + m, restore) if m > 0 else (over, restore - m)

    if s.vertical_N or s.horizontal_N:
        drawer = d.drawers()[s.load_drawer] if s.load_drawer is not None else None
        y_load = d.depth / 2 + (d.travel(drawer) if drawer and drawer.index in s.open_drawers else 0.0)
        if s.vertical_N:
            m = s.vertical_N * forward_offset(y_load, drawer.z_top if drawer else d.height)
            over, restore = (over + m, restore) if m > 0 else (over, restore - m)
        if s.horizontal_N:
            over += s.horizontal_N * height(y_load, s.horizontal_z)

    anchor_needed = 0.0
    if s.anchored:
        strap_z = height(-d.depth / 2, d.height - 0.05)
        anchor_needed = max(0.0, (over - restore) / strap_z)
        restore += min(anchor_needed, ANCHOR_RATING_N) * strap_z
    return Statics(restore, over, anchor_needed, {"tilt_deg": math.degrees(phi)})


def rocking_threshold_g(d: Dresser, fill: bool = True) -> float:
    """Floor acceleration (in g) at which shaking starts to rock it forward: setback of the
    center of gravity behind the front edge over its height. Weight up high lowers this."""
    parts = d.parts(fill=fill)
    m = sum(p.mass for p in parts)
    y = sum(p.mass * p.center[1] for p in parts) / m
    z = sum(p.mass * p.center[2] for p in parts) / m
    return (d.front_support_y - y) / z


def tip_force(d: Dresser, height: float, fill: bool = False) -> float:
    """Horizontal pull at `height` that just lifts the rear: the luggage-scale pull test."""
    base = statics(d, Scenario("pull", "pull", frozenset(), fill=fill))
    return (base.restoring_Nm - base.overturning_Nm) / height


# --- Scenarios ---------------------------------------------------------------

F2057 = "ASTM F2057-23 §9.2"


def f2057_tests(d: Dresser, anchored: bool = False, only_open: frozenset[int] | None = None) -> list[Scenario]:
    """The three child stability tests. `only_open` models drawer interlocks (only those open)."""
    all_open = frozenset(range(len(d.drawers()))) if only_open is None else only_open
    top = d.top_drawer()
    load = top.index if top.index in all_open else max(all_open, key=lambda i: d.drawers()[i].z_top)
    hold_z = min(d.drawers()[load].z_top, MAX_HANDHOLD_M)
    return [
        Scenario("clothing_load", "Clothing load, all drawers open", all_open, fill=True,
                 anchored=anchored, standard=f"{F2057}.1: 8.5 lb/ft³ fill, all drawers open, 30 s"),
        Scenario("horizontal_force", "Child pulling on the top drawer", all_open,
                 horizontal_N=HORIZONTAL_FORCE_N, horizontal_z=hold_z, load_drawer=load, anchored=anchored,
                 standard=f"{F2057}.2: 10 lbf outward at the highest handhold ≤ 56 in, all drawers open"),
        Scenario("child_on_drawer", "60 lb child on an open drawer, on carpet", all_open, block=CARPET_BLOCK_M,
                 vertical_N=CHILD_WEIGHT_N, load_drawer=load, anchored=anchored,
                 standard=f"{F2057}.3: 0.43 in block under the rear, 60 lb on the open drawer front, 30 s"),
    ]  # fmt: skip


# No standard covers an adult grabbing furniture for balance. Until we source measured grab
# forces, judge against this range and say so in the report.
GRAB_FORCE_RANGE_N = (100.0, 300.0)
HAND_HEIGHT_M = 0.95


def elderly_test(d: Dresser, force_N: float = GRAB_FORCE_RANGE_N[1], anchored: bool = False) -> Scenario:
    return Scenario(
        "elderly_grab", "Adult grabbing the top for balance", frozenset(), fill=True,
        horizontal_N=force_N, horizontal_z=min(HAND_HEIGHT_M, d.height), anchored=anchored,
        assumption=f"grab force {GRAB_FORCE_RANGE_N[0]:.0f}–{GRAB_FORCE_RANGE_N[1]:.0f} N at "
        f"{HAND_HEIGHT_M} m with clothes in closed drawers; no standard exists",
    )  # fmt: skip
