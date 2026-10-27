"""Parametric furniture: one template for every case piece. A case is a box (sides, top, bottom, back)
on a plinth or legs whose front is a stack of zones, bottom to top. Each zone holds drawers, doors
(hinged at the side like a wardrobe's, or at the bottom like an oven's), or open shelves, and what
is kept inside. A dresser is one drawer zone; a wardrobe a drawer zone under a door zone; a bookcase
one open zone with shelves; a range a drawer under a bottom-hinged door.

The template turns a handful of measurements into every panel, drawer, door and shelf, which gives
both the physics model and the mass estimate. Materials and contents come from the skill's catalogs
(skill/catalog/*.toml), so new ones are config, not code.

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
DOOR_OPEN_RAD = 1.5708  # doors open to 90 degrees for the tests

SKILL_DIR = Path(__file__).with_name("skill")


def catalog(name: str) -> dict:
    """One of the skill's catalogs (skill/catalog/<name>.toml) as a dict of tables."""
    return _catalog(name)


@cache
def _catalog(name: str) -> dict:
    return tomllib.loads((SKILL_DIR / "catalog" / f"{name}.toml").read_text())


@dataclass(frozen=True)
class Material:
    density: float  # kg/m^3 of the carcass and front panels
    panel: float  # carcass panel thickness, m
    back: float  # back panel thickness, m (usually hardboard)
    back_density: float = 850.0
    drawer_box: float = 0.012  # drawer side/back thickness
    drawer_bottom: float = 0.003
    label: str = ""


@cache
def materials() -> dict[str, Material]:
    return {key: Material(**cfg) for key, cfg in catalog("materials").items()}


@dataclass(frozen=True)
class Contents:
    """What is kept in a zone: by volume (kg per m^3 of the space it takes) or, for clothes on a
    rail, by length (kg per m of rail)."""

    label: str
    kg_m3: float = 0.0
    kg_per_m: float = 0.0
    color: str = ".55 .70 .90 1"
    source: str = ""


@cache
def contents() -> dict[str, Contents]:
    return {key: Contents(**cfg) for key, cfg in catalog("contents").items()}


@dataclass(frozen=True)
class Part:
    name: str
    body: str  # "carcass", "drawer_<i>", "door_<i>" or "item_<i>"
    center: tuple[float, float, float]
    size: tuple[float, float, float]  # full extents
    mass: float
    kind: str = "panel"  # panel | front | fill | load | leg
    color: str = ""  # for contents, from the catalog


@dataclass(frozen=True)
class Zone:
    """One band of the front, counted from the bottom."""

    kind: str = "drawers"  # drawers | doors | open
    share: float = 1.0  # its share of the inside height; the zones are scaled to fill it
    rows: int = 1  # drawers: rows
    cols: int = 1  # drawers: columns; doors: leaves side by side; open: compartments across
    shelves: int = 0  # doors or open: shelf boards inside
    hinge: str = "side"  # doors: side (a wardrobe) or bottom (an oven, a drop-front desk)
    contents: str = ""  # a key of the contents catalog; empty: drawers hold clothes, the rest nothing
    fill: float = 1.0  # share of the space the contents take


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
    zone: int = 0


@dataclass(frozen=True)
class Door:
    index: int
    hinge: str  # side | bottom
    x: float  # center when shut
    width: float
    z_bottom: float
    z_top: float
    side: int = 0  # side hinges: -1 hinged on its left edge, +1 on its right

    @property
    def hinge_x(self) -> float:
        return self.x + self.side * self.width / 2

    @property
    def reach(self) -> float:
        """How far its free edge stands out in front when open."""
        return self.width if self.hinge == "side" else self.z_top - self.z_bottom


@dataclass(frozen=True)
class TopItem:
    """Something standing on the top (a TV, boxes, a lamp), sized from its SAM outline."""

    name: str
    kind: str = "block"  # screen (or tv): a flat panel on a small foot | anything else: a solid block
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

    @property
    def is_screen(self) -> bool:
        return self.kind in ("screen", "tv")

    def parts(self, i: int, top_z: float) -> list[Part]:
        body, name = f"item_{i}", f"item_{i}_{'tv' if self.is_screen else 'block'}"
        top_z += self.z
        if not self.is_screen:
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


LEGACY_KEYS = ("rows", "cols", "door_zone", "doors", "shelves", "books", "hanging")


@dataclass(frozen=True)
class Case:
    width: float
    depth: float
    height: float
    zones: tuple[Zone, ...] = (Zone(rows=3),)  # bottom to top
    base: str = "plinth"  # plinth: sides run to the floor | legs: carcass on four legs
    base_height: float = 0.05  # plinth or leg height
    material: str = "particleboard"
    extension: float = 2 / 3  # open drawers travel this fraction of their box depth
    # Friction of the drawer runners, as a share of the drawer's weight; what keeps shut drawers from
    # sliding out in an earthquake. Assumed: metal roller slides ~0.05, wood-on-wood runners ~0.25.
    runner_friction: float = 0.05
    top_items: tuple[TopItem, ...] = ()  # things standing on top, e.g. a TV
    density_scale: float = 1.0  # scales every panel; set to match a known weight, varied in sweeps
    leg_inset: float = 0.03
    notes: tuple[str, ...] = field(default=(), compare=False)

    def __post_init__(self):  # accept zones and items as dicts, as they come back from report.json
        zones = tuple(z if isinstance(z, Zone) else Zone(**z) for z in self.zones)
        items = tuple(i if isinstance(i, TopItem) else TopItem(**i) for i in self.top_items)
        object.__setattr__(self, "zones", zones)
        object.__setattr__(self, "top_items", items)

    @classmethod
    def from_dict(cls, cfg: dict) -> "Case":
        """From a catalog entry or a saved report, including ones saved before zones existed
        (rows/cols of drawers, then doors or shelves above them)."""
        cfg = {k: v for k, v in cfg.items() if k != "label"}
        old = {k: cfg.pop(k) for k in LEGACY_KEYS if k in cfg}
        if old and "zones" not in cfg:
            rows, cols = old.get("rows", 3), old.get("cols", 1)
            doors, shelves, share = old.get("doors", 0), old.get("shelves", 0), old.get("door_zone", 0.0)
            zones = [Zone(rows=rows, cols=cols)] if rows else []
            if not rows or share > 0:
                upper = Zone("doors" if doors else "open", share / (1 - share) if rows else 1.0,
                             cols=doors or (cols if not rows else 1), shelves=shelves,
                             contents="hanging_clothes" if old.get("hanging") else "books" if old.get("books") else "",
                             fill=old.get("books") or 1.0)  # fmt: skip
                zones.append(upper)
            cfg["zones"] = tuple(zones)
        return cls(**cfg)

    @property
    def top_load_kg(self) -> float:
        return sum(i.mass for i in self.top_items)

    @property
    def top_height(self) -> float:
        """Height of the tallest thing, the piece itself included."""
        return self.height + max((i.z + i.height for i in self.top_items), default=0.0)

    @property
    def mat(self) -> Material:
        return materials()[self.material]

    @property
    def front_support_y(self) -> float:
        """The edge it tips forward over."""
        return self.depth / 2 - (self.leg_inset if self.base == "legs" else 0.0)

    @property
    def rear_support_y(self) -> float:
        return -self.depth / 2 + (self.leg_inset if self.base == "legs" else 0.0)

    def bands(self) -> list[tuple[Zone, float, float]]:
        """Each zone with its bottom and top inside the carcass, bottom first; a panel separates them."""
        t = self.mat.panel
        z0, z1 = self.base_height + t, self.height - t
        usable = z1 - z0 - (len(self.zones) - 1) * t
        total = sum(z.share for z in self.zones) or 1.0
        out, z = [], z0
        for zone in self.zones:
            h = usable * zone.share / total
            out.append((zone, z, z + h))
            z += h + t
        return out

    def drawers(self) -> list[Drawer]:
        """Every drawer, top row first."""
        t, tb = self.mat.panel, self.mat.back
        out: list[Drawer] = []
        for zi, (zone, lo, hi) in reversed(list(enumerate(self.bands()))):
            if zone.kind != "drawers" or zone.rows < 1:
                continue
            row_h = (hi - lo) / zone.rows
            col_w = (self.width - 2 * t - (zone.cols - 1) * t) / zone.cols
            box_depth = self.depth - t - tb - 0.01
            rows_above = len({d.row for d in out})
            for row in range(zone.rows):
                for col in range(zone.cols):
                    x = -self.width / 2 + t + col * (col_w + t) + col_w / 2
                    top = hi - row * row_h
                    out.append(Drawer(len(out), rows_above + row, col, x, col_w, top - row_h, top, box_depth, zi))
        return out

    def travel(self, drawer: Drawer) -> float:
        return self.extension * drawer.box_depth

    def door_list(self) -> list[Door]:
        """Every door. Side-hinged leaves hinge on the side nearer their own outer edge."""
        out: list[Door] = []
        for zone, lo, hi in self.bands():
            if zone.kind != "doors":
                continue
            n = max(zone.cols, 1)
            w = self.width / n
            for i in range(n):
                x = -self.width / 2 + (i + 0.5) * w
                side = (-1 if x <= 0 else 1) if zone.hinge == "side" else 0
                out.append(Door(len(out), zone.hinge, x, w - 0.003, lo, hi, side))
        return out

    def shelf_levels(self, kinds: tuple[str, ...] = ("open", "doors")) -> list[float]:
        """Heights of the surfaces things stand on inside the open or door zones: each zone's floor
        and every shelf's top."""
        out = []
        for zone, lo, hi in self.bands():
            if zone.kind in kinds:
                step = (hi - lo) / (zone.shelves + 1)
                out += [lo + i * step for i in range(zone.shelves + 1)]
        return out

    def parts(self, open_drawers: frozenset[int] = frozenset(), fill: bool = False,
              open_doors: frozenset[int] = frozenset()) -> list[Part]:  # fmt: skip
        """Every panel as a solid box. Drawers in `open_drawers` are pulled out by `travel`; doors in
        `open_doors` stand open at 90 degrees. `fill` adds what each zone holds."""
        m, k = self.mat, self.density_scale
        W, D, H, t, tb, bh = self.width, self.depth, self.height, m.panel, m.back, self.base_height
        rho, rho_back = m.density * k, m.back_density * k
        c_bottom = bh if self.base == "legs" else 0.0  # where the side panels start
        stuff = contents()

        def box(name, body, center, size, density, kind="panel", color=""):
            return Part(name, body, center, size, size[0] * size[1] * size[2] * density, kind, color)

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
        for i, item in enumerate(self.top_items):
            parts += item.parts(i, H)

        inner_w = W - 2 * t
        shelf_d = D - tb - t - 0.01  # set back behind the doors
        y_shelf = -D / 2 + tb + shelf_d / 2
        for zi, (zone, lo, hi) in enumerate(self.bands()):
            if zi:  # the panel under each zone but the lowest
                parts.append(box(f"zone_{zi}_floor", "carcass", (0, y_shelf, lo - t / 2), (inner_w, shelf_d, t), rho))
            if zone.kind != "doors" and zone.cols > 1:
                col_w = (inner_w - (zone.cols - 1) * t) / zone.cols
                for c in range(1, zone.cols):
                    x = -W / 2 + t + c * (col_w + t) - t / 2
                    parts.append(box(f"zone_{zi}_divider_{c}", "carcass", (x, tb / 2, (lo + hi) / 2),
                                     (t, D - tb, hi - lo), rho))  # fmt: skip
            if zone.kind == "drawers":
                continue
            step = (hi - lo) / (zone.shelves + 1)
            for s in range(1, zone.shelves + 1):
                z = lo + s * step
                shelf = (0, y_shelf, z - t / 2)
                parts.append(box(f"zone_{zi}_shelf_{s}", "carcass", shelf, (inner_w, shelf_d, t), rho))
            kept = stuff.get(zone.contents)
            if fill and kept and zone.fill > 0:
                if kept.kg_per_m:  # on a rail near the top, hanging about a metre
                    hang = min(1.0, hi - lo - 0.08)
                    size = (inner_w * min(zone.fill, 1.0), min(0.50, shelf_d), hang)
                    parts.append(Part(f"zone_{zi}_{zone.contents}", "carcass", (0, y_shelf, hi - 0.08 - hang / 2),
                                      size, kept.kg_per_m * size[0], "fill", kept.color))  # fmt: skip
                else:  # on each shelf, pushed to the front
                    cw, cd, ch = inner_w * min(zone.fill, 1.0), min(shelf_d - 0.01, 0.30), min(step - t - 0.03, 0.32)
                    y = D / 2 - t - 0.01 - cd / 2
                    for s in range(zone.shelves + 1):
                        z = lo + s * step
                        parts.append(box(f"zone_{zi}_{zone.contents}_{s}", "carcass", (0, y, z + ch / 2),
                                         (cw, cd, ch), kept.kg_m3, "fill", kept.color))  # fmt: skip

        for door in self.door_list():
            h = door.z_top - door.z_bottom
            zc = door.z_bottom + h / 2
            if door.index not in open_doors:
                center, size = (door.x, D / 2 - t / 2, zc), (door.width, t, h)
            elif door.hinge == "side":  # swung out about its hinge, square to the front
                center, size = (door.hinge_x - door.side * t / 2, D / 2 + door.width / 2, zc), (t, door.width, h)
            else:  # folded down about its bottom edge, level
                center, size = (door.x, D / 2 + h / 2, door.z_bottom + t / 2), (door.width, h, t)
            parts.append(box(f"door_{door.index}_panel", f"door_{door.index}", center, size, rho, "front"))

        dt, db = m.drawer_box, m.drawer_bottom
        zones = self.zones
        for d in self.drawers():
            body = f"drawer_{d.index}"
            dy = self.travel(d) if d.index in open_drawers else 0.0
            h = d.z_top - d.z_bottom
            box_h, box_w, depth = h - 0.03, d.width - 0.02, d.box_depth
            y_box = D / 2 - t - depth / 2 + dy
            z_box = d.z_bottom + 0.005 + box_h / 2
            z_floor = d.z_bottom + 0.005  # underside of the drawer bottom
            inner = box_w - 2 * dt
            parts += [
                box(f"{body}_front", body, (d.x, D / 2 - t / 2 + dy, d.z_bottom + h / 2),
                    (d.width - 0.003, t, h - 0.003), rho, "front"),
                box(f"{body}_side_l", body, (d.x - box_w / 2 + dt / 2, y_box, z_box), (dt, depth, box_h), rho),
                box(f"{body}_side_r", body, (d.x + box_w / 2 - dt / 2, y_box, z_box), (dt, depth, box_h), rho),
                box(f"{body}_back", body, (d.x, y_box - depth / 2 + dt / 2, z_box), (inner, dt, box_h), rho),
                box(f"{body}_bottom", body, (d.x, y_box, z_floor + db / 2), (inner, depth - dt, db), rho_back),
            ]  # fmt: skip
            zone = zones[d.zone]
            kept = stuff.get(zone.contents or "clothes")
            if fill and kept and zone.fill > 0:
                # F2057 volume: inside the box, up to 1/8 in below the drawer above
                fill_h = (box_h - db - 0.003) * min(zone.fill, 1.0)
                size = (inner, depth - dt, fill_h)
                center = (d.x, y_box + dt / 2, z_floor + db + fill_h / 2)
                parts.append(box(f"{body}_fill", body, center, size, kept.kg_m3, "fill", kept.color))
        return parts

    def mass(self, fill: bool = False) -> float:
        return sum(p.mass for p in self.parts(fill=fill) if p.kind != "load")

    def top_drawer(self) -> Drawer | None:
        """Highest drawer whose top edge is within reach (<= 56 in); the F2057 load point."""
        reachable = [d for d in self.drawers() if d.z_top <= MAX_HANDHOLD_M] or self.drawers()
        return max(reachable, key=lambda d: d.z_top, default=None)

    @property
    def drawer_share(self) -> float:
        """Share of the storage volume that pulls out: F2057 fills the clothing-load test only above 1/2."""
        inner_w, d = self.width - 2 * self.mat.panel, self.depth
        drawers = sum((hi - lo) * inner_w * d for z, lo, hi in self.bands() if z.kind == "drawers")
        rest = sum((hi - lo) * inner_w * d for z, lo, hi in self.bands() if z.kind != "drawers")
        return drawers / (drawers + rest) if drawers + rest else 0.0


Dresser = Case  # the name before doors and shelves


@cache
def examples() -> dict[str, tuple[str, Case]]:
    """{key: (label, template)}: the worked examples in skill/catalog/examples.toml, which the model
    compares a photographed piece against."""
    out = {}
    for key, cfg in catalog("examples").items():
        cfg = dict(cfg)
        kg = cfg.pop("mass_kg", None)
        out[key] = (cfg["label"], with_mass(Case.from_dict(cfg), kg))
    return out


presets = examples


def with_mass(d: Case, kg: float | None) -> Case:
    """The template scaled so its empty weight matches a known one (a product page, a spec sheet)."""
    return replace(d, density_scale=d.density_scale * kg / d.mass()) if kg and kg > 0 else d
