"""Parametric furniture templates. A template turns a handful of measurements into every panel
and drawer of the piece, which gives both the physics model and the mass estimate.

Frame: x across the width, y front-to-back with the front face at +depth/2, z up from the floor.
Units are SI (m, kg) throughout.
"""

import tomllib
from dataclasses import dataclass, field, replace
from functools import cache
from pathlib import Path

# ASTM F2057-23 constants, converted from imperial
LB, LBF, IN, FT3 = 0.45359237, 4.4482216, 0.0254, 0.0283168
CLOTHING_FILL_KG_M3 = 8.5 * LB / FT3  # 136 kg/m^3 of drawer volume
CHILD_WEIGHT_N = 60 * LB * 9.81
HORIZONTAL_FORCE_N = 10 * LBF
MAX_HANDHOLD_M = 56 * IN
CARPET_BLOCK_M = 0.43 * IN
ANCHOR_RATING_N = 50 * LBF  # tip restraint static load in ASTM F3096


@dataclass(frozen=True)
class Material:
    density: float  # kg/m^3 of the carcass and drawer-front panels
    panel: float  # carcass panel thickness, m
    back: float  # back panel thickness, m (usually hardboard)
    back_density: float = 850.0
    drawer_box: float = 0.012  # drawer side/back thickness
    drawer_bottom: float = 0.003


MATERIALS = {
    "particleboard": Material(density=650, panel=0.016, back=0.003),
    "mdf": Material(density=750, panel=0.018, back=0.003),
    "solid_softwood": Material(density=500, panel=0.020, back=0.006, back_density=600),
    "solid_hardwood": Material(density=720, panel=0.020, back=0.006, back_density=600),
}


@dataclass(frozen=True)
class Part:
    name: str
    body: str  # "carcass" or "drawer_<i>"
    center: tuple[float, float, float]
    size: tuple[float, float, float]  # full extents
    mass: float
    kind: str = "panel"  # panel | front | fill | load | leg


@dataclass(frozen=True)
class Drawer:
    index: int
    row: int  # 0 = top
    col: int
    x: float  # center
    width: float
    z_bottom: float
    z_top: float
    box_depth: float

    @property
    def front_top(self) -> float:
        return self.z_top


@dataclass(frozen=True)
class TopItem:
    """Something standing on the top (a TV, boxes, a lamp), sized from its SAM outline."""

    name: str
    kind: str = "other"  # tv: a screen on a small foot | anything else: a solid block
    mass: float = 1.0
    width: float = 0.3
    depth: float = 0.2
    height: float = 0.3
    x: float = 0.0  # center offset across the top
    y: float = 0.0  # center offset front to back, + toward the front
    z: float = 0.0  # height of its base above the top, when it stands on another item
    short: str = ""  # one or two words for the page: "plant pot", "bunny"
    hard: bool = True  # a soft thing (a plush, a cushion) can fall without hurting anyone
    breakable: bool = False  # glass or ceramic: breaks into sharp pieces

    def parts(self, i: int, top_z: float) -> list[Part]:
        body, name = f"item_{i}", f"item_{i}_{self.kind}"
        top_z += self.z
        if self.kind != "tv":
            center = (self.x, self.y, top_z + self.height / 2)
            return [Part(name, body, center, (self.width, self.depth, self.height), self.mass, "load")]
        # A flat-screen on its stand: most of the weight in a thin panel above a narrow foot,
        # which is why TVs topple so easily
        foot_h, screen_d = 0.03, min(0.06, self.depth)
        screen_h = max(self.height - foot_h - 0.04, 0.05)
        foot = Part(
            f"{name}_foot",
            body,
            (self.x, self.y, top_z + foot_h / 2),
            (min(self.width, 0.6) * 0.6, self.depth, foot_h),
            0.3 * self.mass,
            "load",
        )
        screen = Part(f"{name}_screen", body, (self.x, self.y, top_z + self.height - screen_h / 2),
                      (self.width, screen_d, screen_h), 0.7 * self.mass, "load")  # fmt: skip
        return [foot, screen]


@dataclass(frozen=True)
class Dresser:
    width: float
    depth: float
    height: float
    rows: int = 3
    cols: int = 1
    base: str = "plinth"  # plinth: sides run to the floor | legs: carcass on four legs
    base_height: float = 0.05  # plinth or leg height
    material: str = "particleboard"
    extension: float = 2 / 3  # open drawers travel this fraction of their box depth
    top_items: tuple[TopItem, ...] = ()  # things standing on top, e.g. a TV
    density_scale: float = 1.0  # for uncertainty sweeps
    leg_inset: float = 0.03
    notes: tuple[str, ...] = field(default=(), compare=False)

    def __post_init__(self):  # accept items as dicts, as they come back from report.json
        items = tuple(i if isinstance(i, TopItem) else TopItem(**i) for i in self.top_items)
        object.__setattr__(self, "top_items", items)

    @property
    def top_load_kg(self) -> float:
        return sum(i.mass for i in self.top_items)

    @property
    def top_height(self) -> float:
        """Height of the tallest thing, the piece itself included."""
        return self.height + max((i.z + i.height for i in self.top_items), default=0.0)

    @property
    def mat(self) -> Material:
        return MATERIALS[self.material]

    @property
    def front_support_y(self) -> float:
        """The edge it tips forward over."""
        return self.depth / 2 - (self.leg_inset if self.base == "legs" else 0.0)

    @property
    def rear_support_y(self) -> float:
        return -self.depth / 2 + (self.leg_inset if self.base == "legs" else 0.0)

    def scaled(self, **changes) -> "Dresser":
        return replace(self, **changes)

    def drawers(self) -> list[Drawer]:
        t, tb = self.mat.panel, self.mat.back
        z0, z1 = self.base_height + t, self.height - t
        row_h = (z1 - z0) / self.rows
        col_w = (self.width - 2 * t - (self.cols - 1) * t) / self.cols
        box_depth = self.depth - t - tb - 0.01
        out = []
        for row in range(self.rows):
            for col in range(self.cols):
                x = -self.width / 2 + t + col * (col_w + t) + col_w / 2
                top = z1 - row * row_h
                out.append(Drawer(len(out), row, col, x, col_w, top - row_h, top, box_depth))
        return out

    def travel(self, drawer: Drawer) -> float:
        return self.extension * drawer.box_depth

    def parts(self, open_drawers: frozenset[int] = frozenset(), fill: bool = False) -> list[Part]:
        """Every panel as a solid box. Drawers in `open_drawers` are pulled out by `travel`."""
        m, k = self.mat, self.density_scale
        W, D, H, t, tb, bh = self.width, self.depth, self.height, m.panel, m.back, self.base_height
        rho, rho_back = m.density * k, m.back_density * k
        c_bottom = bh if self.base == "legs" else 0.0  # where the side panels start

        def box(name, body, center, size, density, kind="panel"):
            return Part(name, body, center, size, size[0] * size[1] * size[2] * density, kind)

        side_h = H - c_bottom
        parts = [
            box("side_left", "carcass", (-W / 2 + t / 2, 0, c_bottom + side_h / 2), (t, D, side_h), rho),
            box("side_right", "carcass", (W / 2 - t / 2, 0, c_bottom + side_h / 2), (t, D, side_h), rho),
            box("top", "carcass", (0, 0, H - t / 2), (W - 2 * t, D, t), rho),
            box("bottom", "carcass", (0, tb / 2, bh + t / 2), (W - 2 * t, D - tb, t), rho),
            box("back", "carcass", (0, -D / 2 + tb / 2, c_bottom + side_h / 2), (W - 2 * t, tb, side_h), rho_back),
        ]
        if self.base == "plinth":
            parts.append(box("plinth", "carcass", (0, D / 2 - 0.03 - t / 2, bh / 2), (W - 2 * t, t, bh), rho))
        else:
            leg, y_f, y_r = 0.04, self.front_support_y - 0.02, self.rear_support_y + 0.02
            for i, (x, y) in enumerate([(-1, y_f), (1, y_f), (-1, y_r), (1, y_r)]):
                xc = x * (W / 2 - self.leg_inset - leg / 2)
                parts.append(box(f"leg_{i}", "carcass", (xc, y, bh / 2), (leg, leg, bh), 650 * k, "leg"))
        inner_h = H - t - (bh + t)
        for i in range(1, self.cols):
            x = -W / 2 + t + i * ((W - 2 * t - (self.cols - 1) * t) / self.cols + t) - t / 2
            parts.append(box(f"divider_{i}", "carcass", (x, tb / 2, bh + t + inner_h / 2), (t, D - tb, inner_h), rho))
        for i, item in enumerate(self.top_items):
            parts += item.parts(i, H)

        dt, db = m.drawer_box, m.drawer_bottom
        for d in self.drawers():
            body = f"drawer_{d.index}"
            dy = self.travel(d) if d.index in open_drawers else 0.0
            h = d.z_top - d.z_bottom
            box_h, box_w, depth = h - 0.03, d.width - 0.02, d.box_depth
            y_box = D / 2 - t - depth / 2 + dy
            z_box = d.z_bottom + 0.005 + box_h / 2
            z_floor = d.z_bottom + 0.005  # underside of the drawer bottom
            inner_w = box_w - 2 * dt
            parts += [
                box(f"{body}_front", body, (d.x, D / 2 - t / 2 + dy, d.z_bottom + h / 2),
                    (d.width - 0.003, t, h - 0.003), rho, "front"),
                box(f"{body}_side_l", body, (d.x - box_w / 2 + dt / 2, y_box, z_box), (dt, depth, box_h), rho),
                box(f"{body}_side_r", body, (d.x + box_w / 2 - dt / 2, y_box, z_box), (dt, depth, box_h), rho),
                box(f"{body}_back", body, (d.x, y_box - depth / 2 + dt / 2, z_box), (inner_w, dt, box_h), rho),
                box(f"{body}_bottom", body, (d.x, y_box, z_floor + db / 2), (inner_w, depth - dt, db), rho_back),
            ]  # fmt: skip
            if fill:
                # F2057 volume: inside the box, up to 1/8 in below the drawer above
                fill_h = box_h - db - 0.003
                size = (inner_w, depth - dt, fill_h)
                center = (d.x, y_box + dt / 2, z_floor + db + fill_h / 2)
                kg = size[0] * size[1] * size[2] * CLOTHING_FILL_KG_M3
                parts.append(Part(f"{body}_fill", body, center, size, kg, "fill"))
        return parts

    def mass(self, fill: bool = False) -> float:
        return sum(p.mass for p in self.parts(fill=fill) if p.kind not in ("load",))

    def top_drawer(self) -> Drawer:
        """Highest drawer whose top edge is within reach (<= 56 in); the F2057 load point."""
        reachable = [d for d in self.drawers() if d.z_top <= MAX_HANDHOLD_M] or self.drawers()
        return max(reachable, key=lambda d: d.z_top)


PRESETS_FILE = Path(__file__).with_name("presets.toml")


@cache
def presets() -> dict[str, tuple[str, Dresser]]:
    """{key: (label, template)} from presets.toml."""
    raw = tomllib.loads(PRESETS_FILE.read_text())
    return {key: (cfg.pop("label"), Dresser(**cfg)) for key, cfg in raw.items()}
