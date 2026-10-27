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
    load_drawer: int | None = None  # None: the force acts on the carcass front (or `load_door`)
    anchored: bool = False
    open_doors: frozenset[int] = frozenset()
    load_door: int | None = None  # the vertical load hangs on this open door's free edge
    vertical_at: tuple[float, float] | None = None  # (y, z) of a vertical load on the carcass: a shelf edge
    element: str = "drawer"  # what the child loads: drawer | door | shelf
    loose_drawers: frozenset[int] = frozenset()  # shut drawers free on their runners (earthquake), not held
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
    for p in d.parts(open_drawers=s.open_drawers, fill=s.fill, open_doors=s.open_doors):
        m = p.mass * G * forward_offset(p.center[1], p.center[2])
        over, restore = (over + m, restore) if m > 0 else (over, restore - m)

    if s.vertical_N or s.horizontal_N:
        y_load, z_load = load_point(d, s)
        if s.vertical_N:
            m = s.vertical_N * forward_offset(y_load, z_load)
            over, restore = (over + m, restore) if m > 0 else (over, restore - m)
        if s.horizontal_N:
            over += s.horizontal_N * height(y_load, s.horizontal_z)

    anchor_needed = 0.0
    if s.anchored:
        strap_z = height(-d.depth / 2, d.height - 0.05)
        anchor_needed = max(0.0, (over - restore) / strap_z)
        restore += min(anchor_needed, ANCHOR_RATING_N) * strap_z
    return Statics(restore, over, anchor_needed, {"tilt_deg": math.degrees(phi)})


def load_point(d: Dresser, s: Scenario) -> tuple[float, float]:
    """(y, z) where the test load acts, with the drawers and doors as the scenario sets them."""
    if s.load_drawer is not None:
        drawer = d.drawers()[s.load_drawer]
        return d.depth / 2 + (d.travel(drawer) if drawer.index in s.open_drawers else 0.0), drawer.z_top
    if s.load_door is not None:
        door = d.door_list()[s.load_door]
        z = min(door.z_top, MAX_HANDHOLD_M) if door.hinge == "side" else door.z_bottom
        return d.depth / 2 + door.reach, z
    return s.vertical_at or (d.depth / 2, d.height)


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


PULLED = {"drawer": "the top drawer", "door": "an open door", "shelf": "a shelf"}
OUT_OF_SCOPE = ("; bookcases and TV stands are outside F2057's scope, so its child tests are borrowed "
                "(UL 1678 loads a TV stand's doors and drawers with 50 lb)")  # fmt: skip


def f2057_tests(d: Dresser, anchored: bool = False, only_open: frozenset[int] | None = None) -> list[Scenario]:
    """The three child stability tests, with every drawer and door open. `only_open` models drawer
    interlocks (only those drawers open). The child's weight goes where it tips the piece most: the
    top drawer's front, an open door's free edge, or, on open shelves, the highest shelf's edge in reach."""
    drawers, doors = d.drawers(), d.door_list()
    all_open = frozenset(range(len(drawers))) if only_open is None else only_open
    doors_open = frozenset(range(len(doors)))
    # open shelves (a bookcase, a TV stand) or a fold-down door (an oven) put it outside F2057's scope
    note = OUT_OF_SCOPE if any(z.kind == "open" for z in d.zones) or any(x.hinge == "bottom" for x in doors) else ""
    common = {"open_drawers": all_open, "open_doors": doors_open, "anchored": anchored}

    # Handholds and load points: (y when open, z, what), the drawer or door, worst last
    holds: list[tuple[float, float, str, dict]] = []
    if all_open:
        top = d.top_drawer()
        load = top.index if top and top.index in all_open else max(all_open, key=lambda i: drawers[i].z_top)
        holds.append((d.depth / 2 + d.travel(drawers[load]), drawers[load].z_top, "drawer", {"load_drawer": load}))
    for door in doors:  # an open side door's free edge, or a fold-down door the child stands on
        z = min(door.z_top, MAX_HANDHOLD_M) if door.hinge == "side" else door.z_bottom
        holds.append((d.depth / 2 + door.reach, z, "door", {"load_door": door.index}))
    if levels := [z for z in d.shelf_levels(("open",)) if z <= MAX_HANDHOLD_M]:
        y = d.depth / 2 - d.mat.panel - 0.01
        holds.append((y, max(levels), "shelf", {"vertical_at": (y, max(levels))}))
    if not holds:  # nothing to open or stand on: the child pulls on the top
        holds.append((d.depth / 2, min(d.height, MAX_HANDHOLD_M), "shelf", {"vertical_at": (d.depth / 2, d.height)}))
    step = max(holds, key=lambda h: (h[0], h[1]))  # where standing tips it most
    grab = max(holds, key=lambda h: h[1])  # the highest handhold
    grab_at = grab[3] if grab[2] == "drawer" else {}  # a pull on a door or shelf acts on the carcass

    tests = []
    if all_open or doors:
        fill = d.drawer_share > 0.5
        opened = " and ".join(w for w, n in (("drawers", all_open), ("doors", doors)) if n)
        tests.append(Scenario("clothing_load", f"All {opened} open{', full' if fill else ''}",
                              fill=fill, element="door" if doors and not all_open else "drawer",
                              standard=f"{F2057}.1: 8.5 lb/ft³ fill when over half the storage pulls out, "
                              "every drawer and door open, 30 s" + note, **common))  # fmt: skip
    tests += [
        Scenario("horizontal_force", f"Child pulling on {PULLED[grab[2]]}", horizontal_N=HORIZONTAL_FORCE_N,
                 horizontal_z=grab[1], element=grab[2], **grab_at, **common,
                 standard=f"{F2057}.2: 10 lbf outward at the highest handhold ≤ 56 in, all drawers open" + note),
        Scenario("child_on_drawer", f"60 lb child on {'the' if step[2] == 'shelf' else 'an open'} {step[2]}, "
                 "on carpet", block=CARPET_BLOCK_M, vertical_N=CHILD_WEIGHT_N, element=step[2], **step[3],
                 **common, standard=f"{F2057}.3: 0.43 in block under the rear, 60 lb on the door or drawer most "
                 "likely to tip it, 30 s" + note),
    ]  # fmt: skip
    return tests


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
