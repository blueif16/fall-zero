"""MuJoCo simulation and video of a template under a scenario, and the staged earthquake.

Load tests: start with the drawers already open (the standard's setup), settle, ramp the load in
(the standard asks for >= 5 s; 2 s is still quasi-static here), then hold. Opening drawers inside
the sim would add a dynamic jolt the static test doesn't have; a loaded tall dresser can tip from
that alone, which is a separate scenario. The piece "tipped" if it ends up rotated more than
TIP_DEG past where it settled.

Things standing on it (a TV on top, a plant on a shelf) and the books on open shelves are loose bodies:
they ride along, slide, topple and fall. The trace for the page's viewer says who is pushing (`actors`):
the child or adult the load stands for, and where they hold on.

Earthquake (`shake`): the floor shakes harder stage by stage. Rather than move the floor, the
simulation runs in the floor's frame, where shaking is the same as an extra sideways gravity on
everything; the video camera moves against the floor so the room is seen to shake.
"""

import math
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

# Vercel has no OpenGL at all (importing mujoco would fail looking for libEGL), and the web app only simulates
os.environ.setdefault("MUJOCO_GL", "disable" if os.environ.get("VERCEL") else "egl")

import mujoco  # noqa: E402
import numpy as np  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from fall_zero.furniture import DOOR_OPEN_RAD, Dresser, TopItem, contents  # noqa: E402
from fall_zero.physics import Scenario, load_point, tilt_angle  # noqa: E402

SETTLE, RAMP, HOLD = 1.0, 2.0, 4.0
TIP_DEG = 5.0
FPS = 30
# 2 ms steps and no noslip pass: 5-10x faster than 1 ms with noslip_iterations=10, whose constraint
# projection was 70% of a step once shelves held loose books (a quake took up to 40 s; now under 3 s). Over
# the 64 worked examples the load tests give the same verdict in 485 of 486, and of 384 quakes (3 seeds, both
# floors) as many fall (202 vs 200), spill (63 vs 62) and slide or rock as far as before. 22 runs flip either
# way, about as many as a 0.01% change in weight flips (11-18): borderline pieces in violent shaking, such as
# the kitchen hutch on seed 1, which falls on seeds 2 and 3 with every solver setting tried.
OPTION = '<option timestep="0.002" integrator="implicitfast"/>'
SIGNAL_DT = 0.001  # the ground motion is made at this step whatever the model's, so a seed is one quake

COLORS = {"panel": ".78 .62 .45 1", "front": ".92 .88 .80 1", "leg": ".45 .33 .22 1",
          "fill": ".55 .70 .90 1", "load": ".62 .68 .78 1", "tv": ".07 .07 .08 1"}  # fmt: skip
ITEM_DROP_M = 0.25  # an item "fell" once its center is this far below where it stood


@dataclass
class SimResult:
    tipped: bool
    max_tilt_deg: float
    final_tilt_deg: float
    video: Path | None = None
    fallen: list[str] = field(default_factory=list)  # items on top that ended up off it
    trace: dict | None = None  # the motion, for the page's 3D viewer (`Trace`)


@dataclass(frozen=True)
class Placed:
    """One piece in a scene: its template, what happens to it, and where its center stands on the
    floor. Every name in its MJCF starts with `prefix`, so a whole room can share one model."""

    d: Dresser
    s: Scenario
    x: float = 0.0
    y: float = 0.0
    prefix: str = ""


@dataclass(frozen=True)
class Ghost:
    """A piece the engine can't build (a leaning mirror, a floor lamp): drawn in its place, not simulated."""

    x: float
    y: float
    width: float
    depth: float
    height: float


def _loose(body: str) -> bool:
    return body.startswith(("item_", "stuff_"))


# Nothing loose in a room moves faster than this: a thing falling 2.5 m lands at 7 m/s. A light thing caught
# between a falling piece and the floor can be squeezed out far faster by the soft contacts (a vase shot out at
# 37 m/s and slid 212 m); a real one would break where it is.
LOOSE_MAX_MS, LOOSE_MAX_RAD_S = 8.0, 40.0


class _Loose:
    """The free joints of every loose body in a model, to keep their speed physical after each step."""

    def __init__(self, model: mujoco.MjModel):
        names = [model.body(model.jnt_bodyid[j]).name for j in range(model.njnt)]
        dofs = [model.jnt_dofadr[j] for j, name in enumerate(names) if model.jnt_type[j] == mujoco.mjtJoint.mjJNT_FREE
                and (_loose(name) or _loose(name.split("_", 1)[-1]))]  # a piece's prefix first, in a room  # fmt: skip
        self.lin = np.array(dofs, dtype=int)
        self.idx = (self.lin[:, None] + np.arange(6)).ravel()
        self.most_sq = np.array([LOOSE_MAX_MS, LOOSE_MAX_RAD_S]) ** 2

    def cap(self, data: mujoco.MjData) -> None:
        if not len(self.lin):
            return
        v = data.qvel[self.idx].reshape(-1, 2, 3)  # per body: linear, angular
        sq = np.einsum("bkj,bkj->bk", v, v)
        if (sq <= self.most_sq).all():  # nearly every step
            return
        scale = np.minimum(1.0, np.sqrt(self.most_sq / np.maximum(sq, 1e-12)))
        data.qvel[self.idx] = (v * scale[:, :, None]).ravel()


def _vec(v) -> str:
    return " ".join(f"{x:.5f}" for x in v)


def _at(x: float, y: float) -> str:
    """Where a piece's own frame sits; a piece alone stays at "0 0", as it always was."""
    return "0 0" if x == y == 0 else f"{x:.5f} {y:.5f}"


def _x(x: float) -> str:
    return "0" if x == 0 else f"{x:.4f}"


def _piece(p: Placed, room: bool, own_wall: bool = True) -> tuple[str, str, str, list[str]]:
    """One piece's MJCF: (world geoms and sites, its bodies, its strap, its actuators). `own_wall`
    gives it a wall of its own; pieces in a room share one instead."""
    d, s, n = p.d, p.s, p.prefix
    phi = tilt_angle(d, s.block)
    lift = d.front_support_y * math.sin(phi) + 0.0005
    quat = (math.cos(-phi / 2), math.sin(-phi / 2), 0, 0)

    # a loose body's frame sits at its own center of mass, not at the piece's origin up to 2 m away
    loose: dict[str, list] = {}
    for part in d.parts(fill=s.fill):
        if _loose(part.body):
            loose.setdefault(part.body, []).append(part)
    centers = {b: np.average([q.center for q in ps], axis=0, weights=[max(q.mass, 1e-6) for q in ps])
               for b, ps in loose.items()}  # fmt: skip

    bodies: dict[str, list[str]] = {}
    for part in d.parts(fill=s.fill):
        contact = 'contype="1" conaffinity="1"' if part.body in ("carcass",) or part.kind == "load" else \
            'contype="2" conaffinity="0"'  # fmt: skip
        if part.kind == "fill":  # contents ride with their drawer, or are loose on an open shelf
            contact = 'contype="1" conaffinity="1"' if _loose(part.body) else 'contype="0" conaffinity="0"'
        color = part.color or COLORS["tv" if "_tv" in part.name else part.kind]
        bodies.setdefault(part.body, []).append(
            f'<geom name="{n}{part.name}" type="box" pos="{_vec(np.subtract(part.center, centers.get(part.body, 0)))}" '
            f'size="{_vec(np.array(part.size) / 2)}" '
            f'mass="{part.mass:.4f}" rgba="{color}" {contact} friction="0.6"/>'
        )

    # Things on it and the contents of open shelves are their own loose bodies, set down 2 mm above
    # where they stand (tilted with the piece on a carpet block)
    def placed(c) -> tuple[float, float, float]:
        cy, cz = c[1] * math.cos(-phi) - c[2] * math.sin(-phi), c[1] * math.sin(-phi) + c[2] * math.cos(-phi)
        return p.x + c[0], p.y + cy, lift + 0.002 + cz

    items = "".join(
        f'<body name="{n}{b}" pos="{_vec(placed(centers[b]))}" quat="{_vec(quat)}"><freejoint/>'
        f'{"".join(g)}</body>' for b, g in bodies.items() if _loose(b)
    )  # fmt: skip

    drawers, actuators = [], []
    drawer_kg = {}
    for part in d.parts(fill=s.fill):
        drawer_kg[part.body] = drawer_kg.get(part.body, 0.0) + part.mass
    for dr in d.drawers():
        name = f"drawer_{dr.index}"
        extra = ""
        if dr.index == s.load_drawer:
            y, z = d.depth / 2, dr.z_top
            extra = (
                f'<site name="{n}load_point" pos="{_vec((dr.x, y, z))}" size="0.01"/>'
                # the 60 lb test weight and the pull, drawn only while they act
                f'<geom name="{n}weight" type="box" pos="{_vec((dr.x, y + 0.07, z - 0.18))}" size="0.12 0.05 0.16" '
                f'mass="0.001" rgba=".85 .15 .15 0" contype="0" conaffinity="0"/>'
                f'<geom name="{n}pull" type="capsule" fromto="{_vec((dr.x, y, z))} {_vec((dr.x, y + 0.35, z))}" '
                f'size="0.012" mass="0.001" rgba=".85 .15 .15 0" contype="0" conaffinity="0"/>'
            )
        if dr.index in s.loose_drawers:  # only the runners' friction holds it; the stop at full travel catches it
            slide = f'frictionloss="{d.runner_friction * drawer_kg[name] * 9.81:.3f}" damping="2"'
        else:
            slide = 'damping="40"'
            actuators.append(
                f'<position name="{n}open_{dr.index}" joint="{n}slide_{dr.index}" kp="20000" dampratio="1" '
                f'ctrlrange="0 {d.travel(dr):.4f}"/>'
            )
        drawers.append(
            f'<body name="{n}{name}"><joint name="{n}slide_{dr.index}" type="slide" axis="0 1 0" '
            f'range="0 {d.travel(dr):.4f}" {slide}/>{"".join(bodies[name])}{extra}</body>'
        )

    # Doors hinge about their outer edge (a wardrobe) or their bottom edge (an oven), held shut, or
    # open at 90 degrees for the tests (MJCF ranges are in degrees; qpos and ctrl in radians)
    for door in d.door_list():
        name = f"door_{door.index}"
        if door.hinge == "side":
            pivot, axis = (door.hinge_x, d.depth / 2, (door.z_bottom + door.z_top) / 2), (0, 0, -door.side)
            edge, weight_size = (door.hinge_x - door.side * door.width, d.depth / 2), "0.05 0.12 0.16"
        else:
            pivot, axis = (door.x, d.depth / 2, door.z_bottom), (-1, 0, 0)
            edge, weight_size = (door.x, d.depth / 2), "0.12 0.16 0.05"
        extra = ""
        if door.index == s.load_door:  # the weight hangs from the free edge (shut-door frame)
            x, y, z = *edge, door.z_top if door.hinge == "bottom" else load_point(d, s)[1]
            extra = (f'<site name="{n}load_point" pos="{_vec((x, y, z))}" size="0.01"/>'
                     f'<geom name="{n}weight" type="box" pos="{_vec((x, y, z - 0.18))}" size="{weight_size}" '
                     'mass="0.001" rgba=".85 .15 .15 0" contype="0" conaffinity="0"/>')  # fmt: skip
        drawers.append(
            f'<body name="{n}{name}"><joint name="{n}hinge_{door.index}" type="hinge" pos="{_vec(pivot)}" '
            f'axis="{_vec(axis)}" range="0 {math.degrees(DOOR_OPEN_RAD):.2f}" damping="5"/>'
            f"{''.join(bodies[name])}{extra}</body>"
        )
        actuators.append(
            f'<position name="{n}swing_{door.index}" joint="{n}hinge_{door.index}" kp="3000" dampratio="1" '
            f'ctrlrange="0 {DOOR_OPEN_RAD:.4f}"/>'
        )

    carcass_extra = ""
    if s.load_drawer is None and s.load_door is None and (s.horizontal_N or s.vertical_N):
        y, z = (d.depth / 2, s.horizontal_z) if s.horizontal_N else load_point(d, s)
        carcass_extra = (
            f'<site name="{n}load_point" pos="0 {y:.4f} {z:.4f}" size="0.01"/>'
            f'<geom name="{n}pull" type="capsule" fromto="0 {y:.4f} {z:.4f} 0 {y + 0.35:.4f} {z:.4f}" size="0.012" '
            f'mass="0.001" rgba=".85 .15 .15 0" contype="0" conaffinity="0"/>'
            f'<geom name="{n}weight" type="box" pos="0 {y + 0.07:.4f} {z - 0.18:.4f}" size="0.12 0.05 0.16" '
            f'mass="0.001" rgba=".85 .15 .15 0" contype="0" conaffinity="0"/>'
        )
    world, tendon = "", ""
    if s.block:
        w, yb = d.width + 0.04, d.rear_support_y
        world += (
            f'<geom name="{n}carpet_block" type="box" pos="{_x(p.x)} {p.y + yb + 0.025:.4f} {s.block / 2:.5f}" '
            f'size="{w / 2:.4f} 0.03 {s.block / 2:.5f}" rgba=".3 .3 .35 1" contype="1" conaffinity="3"/>'
        )
    if room and not s.anchored and own_wall:
        wall_y = p.y - d.depth / 2 - 0.03
        world += (
            f'<geom name="{n}wall" type="box" pos="{_x(p.x)} {wall_y - 0.01:.4f} 1.2" size="2 0.01 1.2" '
            'rgba=".93 .93 .9 1" contype="1" conaffinity="1"/>'
        )
    if s.anchored:
        # Fit the strap where the unit stands, tilt included, with 1 mm of slack
        strap_z = d.height - 0.05
        unit_y = -d.depth / 2 * math.cos(phi) + strap_z * math.sin(phi) + p.y
        unit_z = d.depth / 2 * math.sin(phi) + strap_z * math.cos(phi) + lift
        wall_y = unit_y - 0.03
        if own_wall:
            world += (
                f'<geom name="{n}wall" type="box" pos="{_x(p.x)} {wall_y - 0.01:.4f} 1.2" size="2 0.01 1.2" '
                f'rgba=".93 .93 .9 1" contype="{int(room)}" conaffinity="{int(room)}"/>'
            )
        world += f'<site name="{n}strap_wall" pos="{_x(p.x)} {wall_y:.4f} {unit_z:.4f}" size="0.012"/>'
        carcass_extra += f'<site name="{n}strap_unit" pos="0 {-d.depth / 2:.4f} {strap_z:.4f}" size="0.012"/>'
        tendon = (
            f'<spatial name="{n}strap" limited="true" range="0 0.031" width="0.006" rgba=".2 .2 .2 1">'
            f'<site site="{n}strap_wall"/><site site="{n}strap_unit"/></spatial>'
        )

    body = (
        f'<body name="{n}carcass" pos="{_at(p.x, p.y)} {lift:.5f}" quat="{_vec(quat)}">\n'
        f"      <freejoint/>\n"
        f"      {''.join(bodies['carcass'])}{carcass_extra}\n"
        f"      {''.join(drawers)}\n"
        f"    </body>\n"
        f"    {items}"
    )
    return world, body, tendon, actuators


def build_mjcf(d: Dresser, s: Scenario, room: bool = False) -> str:
    """`room` adds a solid back wall 3 cm behind the piece, as in a real room."""
    return scene_mjcf([Placed(d, s)], room)


def scene_mjcf(placed: list[Placed], room: bool = False, ghosts: tuple[Ghost, ...] = ()) -> str:
    """Every piece in one model. Pieces in a room stand against one shared wall."""
    alone = len(placed) == 1
    parts = [_piece(p, room, own_wall=alone) for p in placed]
    world = "".join(w for w, _, _, _ in parts)
    if room and not alone:
        left = min(p.x - p.d.width / 2 for p in placed)
        right = max(p.x + p.d.width / 2 for p in placed)
        wall_y = min(p.y - p.d.depth / 2 for p in placed) - 0.03
        world += (
            f'<geom name="wall" type="box" pos="{(left + right) / 2:.4f} {wall_y - 0.01:.4f} 1.2" '
            f'size="{(right - left) / 2 + 1:.4f} 0.01 1.2" rgba=".93 .93 .9 1" contype="1" conaffinity="1"/>'
        )
    for i, g in enumerate(ghosts):
        world += (
            f'<geom name="ghost_{i}" type="box" pos="{g.x:.4f} {g.y:.4f} {g.height / 2:.4f}" '
            f'size="{g.width / 2:.4f} {g.depth / 2:.4f} {g.height / 2:.4f}" rgba=".62 .64 .7 .28" '
            'contype="0" conaffinity="0"/>'
        )
    bodies = "\n    ".join(b for _, b, _, _ in parts)
    spatials = "".join(t for _, _, t, _ in parts)
    tendon = f"<tendon>{spatials}</tendon>" if spatials else ""
    actuators = "".join(a for _, _, _, acts in parts for a in acts)

    return f"""
<mujoco model="fall-zero">
  {OPTION}
  <visual><global offwidth="1280" offheight="720"/><quality shadowsize="2048"/></visual>
  <asset>
    <texture name="sky" type="skybox" builtin="gradient" rgb1=".95 .96 .98" rgb2=".72 .78 .86" width="512"
             height="512"/>
    <texture name="grid" type="2d" builtin="checker" rgb1=".86 .85 .82" rgb2=".80 .79 .76" width="512" height="512"/>
    <material name="floor" texture="grid" texrepeat="10 10"/>
  </asset>
  <worldbody>
    <light pos="1.5 2 3" dir="-0.4 -0.6 -1" directional="true" castshadow="true" diffuse=".8 .8 .8"/>
    <geom name="floor" type="plane" size="6 6 0.1" material="floor" contype="1" conaffinity="3" friction="0.6"/>
    {world}
    {bodies}
  </worldbody>
  {tendon}
  <actuator>{actuators}</actuator>
</mujoco>"""


def _smooth(x: float) -> float:
    x = min(max(x, 0.0), 1.0)
    return x * x * (3 - 2 * x)


def _tilt_deg(data: mujoco.MjData, body: int) -> float:
    return math.degrees(math.acos(np.clip(data.xmat[body][8], -1, 1)))


def _camera(d: Dresser) -> mujoco.MjvCamera:
    """Front three-quarter view, aimed a little forward so the landing zone stays in frame."""
    cam = mujoco.MjvCamera()
    top = d.top_height
    cam.lookat[:] = (0, d.depth / 2 + 0.35 * d.height, 0.45 * top)
    cam.distance, cam.azimuth, cam.elevation = max(2.4, 2.0 * top), -125, -16
    return cam


def _frame_every(model: mujoco.MjModel) -> int:
    """Steps between frames: about FPS frames a second (`_fps` is the exact rate)."""
    return max(1, round(1 / FPS / model.opt.timestep))


def _fps(model: mujoco.MjModel) -> float:
    return round(1 / (_frame_every(model) * model.opt.timestep), 3)


class _Recorder:
    """Renders frames into an H.264 file through ffmpeg."""

    def __init__(self, model: mujoco.MjModel, video: Path, size=(640, 480)):
        video.parent.mkdir(parents=True, exist_ok=True)
        self.renderer = mujoco.Renderer(model, size[1], size[0])
        self.ffmpeg = subprocess.Popen(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
             "-s", f"{size[0]}x{size[1]}", "-r", str(_fps(model)), "-i", "-", "-c:v", "libx264", "-pix_fmt",
             "yuv420p", str(video)],
            stdin=subprocess.PIPE,
        )  # fmt: skip

    def frame(self, data: mujoco.MjData, cam: mujoco.MjvCamera, caption: list[tuple[str, str]] | None = None):
        self.renderer.update_scene(data, camera=cam)
        pixels = self.renderer.render()
        if caption:
            pixels = _caption(pixels, caption)
        self.ffmpeg.stdin.write(pixels.tobytes())

    def close(self):
        self.ffmpeg.stdin.close()
        self.ffmpeg.wait()
        self.renderer.close()


def _caption(pixels: np.ndarray, lines: list[tuple[str, str]]) -> np.ndarray:
    img = Image.fromarray(pixels)
    draw = ImageDraw.Draw(img)
    y = 12
    for i, (text, color) in enumerate(lines):
        font = ImageFont.load_default(size=26 if i == 0 else 18)
        draw.text((16, y), text, font=font, fill=color, stroke_width=3, stroke_fill="white")
        y += 34 if i == 0 else 24
    return np.asarray(img)


GEOM_KINDS = {int(mujoco.mjtGeom.mjGEOM_BOX): "box", int(mujoco.mjtGeom.mjGEOM_CAPSULE): "capsule"}


class Trace:
    """The motion for the page's 3D viewer: every geom once (box or capsule, in its body's frame), then
    each body's world pose per frame. Far smaller and faster than a video: the browser draws it.
    `pieces` says where each piece is (its carcass body, or a ghost's place), so the page can label them."""

    def __init__(self, model: mujoco.MjModel, placed: list[Placed] = (), ghosts: tuple[Ghost, ...] = ()):
        self.model = model
        self.geoms = []
        for g in range(model.ngeom):
            kind = GEOM_KINDS.get(int(model.geom_type[g]))
            if kind is None:
                continue  # the floor plane: the viewer draws its own
            self.geoms.append({
                "name": model.geom(g).name, "type": kind, "body": int(model.geom_bodyid[g]),
                "size": model.geom_size[g].round(4).tolist(), "pos": model.geom_pos[g].round(4).tolist(),
                "quat": model.geom_quat[g].round(4).tolist(), "rgba": model.geom_rgba[g].round(3).tolist(),
            })  # fmt: skip
        names = {model.site(i).name: i for i in range(model.nsite)}
        # every strap in the scene: its wall end and its furniture end
        self.strap = [i for n, unit in names.items() if n.endswith("strap_unit")
                      for i in (names[n.removesuffix("unit") + "wall"], unit)]  # fmt: skip
        self.frames, self.straps, self.loads, self.shift = [], [], [], []
        self.load_geoms: list[str] = []  # the test weight or pull arrow, drawn while the load acts
        self.captions: list[tuple[float, str]] = []
        self.events: list[tuple] = []  # (time, text, piece[, other piece])
        # where each piece stands (x, y: its center on the floor; front: +y), so the viewer can label it and
        # draw where it would land
        self.pieces = [{"body": model.body(f"{p.prefix}carcass").id, "height": round(p.d.height, 3),
                        "x": round(p.x, 3), "y": round(p.y, 3), "width": round(p.d.width, 3),
                        "depth": round(p.d.depth, 3)} for p in placed]  # fmt: skip
        self.ghosts = [{"pos": [round(g.x, 3), round(g.y, 3)], "height": round(g.height, 3)} for g in ghosts]
        self.actors = [a for k, p in enumerate(placed) if (a := _actor(model, p, k))]
        # how long each opening phase lasts, in seconds: {"settle", "ramp"} for a load test (the load starts
        # after `settle` and is all on `ramp` later), {"quiet"} before an earthquake's shaking, so the page
        # can say "it fell 1.2 s after the child started climbing"
        self.phases: dict[str, float] = {}

    def add(self, data: mujoco.MjData, load: float = 0.0, ground=(0.0, 0.0)):
        self.frames.append(np.hstack([data.xpos[1:], data.xquat[1:]]).round(4).ravel().tolist())
        self.loads.append(round(float(load), 3))  # how far the load has ramped in, 0 to 1
        self.shift.append([round(float(ground[0]), 4), round(float(ground[1]), 4)])
        if self.strap:
            self.straps.append(np.hstack([data.site_xpos[i] for i in self.strap]).round(4).tolist())

    def caption(self, t: float, text: str):
        if not self.captions or self.captions[-1][1] != text:
            self.captions.append((round(t, 3), text))

    def event(self, t: float, text: str, *pieces: int):
        self.events.append((round(float(t), 3), text, *pieces))

    def to_dict(self) -> dict:
        return {"fps": _fps(self.model), "nbody": self.model.nbody - 1, "geoms": self.geoms, "frames": self.frames,
                "loads": self.loads, "load_geoms": self.load_geoms, "shift": self.shift, "straps": self.straps or None,
                "captions": self.captions, "events": self.events, "pieces": self.pieces,
                "ghosts": self.ghosts, "actors": self.actors, "phases": self.phases}  # fmt: skip


def _actor(model: mujoco.MjModel, p: Placed, k: int) -> dict | None:
    """Who the load stands for, for the viewer to draw: a child standing on the open drawer or shelf
    (`stand`), hanging on a door's edge (`hang`) or pulling (`pull`), an adult grabbing it for balance
    (`pull`), or a child who pulled every drawer open (`watch`). `body` and `at` place the load point
    (a body id, and the point in that body's frame); the viewer works out hands and feet from it."""
    d, s = p.d, p.s
    if not (s.vertical_N or s.horizontal_N or s.key == "clothing_load"):
        return None
    out = {"piece": k, "kind": "adult" if s.key == "elderly_grab" else "child",
           "carcass": model.body(f"{p.prefix}carcass").id, "width": round(d.width, 3), "front": round(d.depth / 2, 3),
           "top": round(d.height, 3)}  # fmt: skip
    if s.vertical_N:
        side_door = s.load_door is not None and d.door_list()[s.load_door].hinge == "side"
        out["action"] = "hang" if side_door else "stand"
    else:
        out["action"] = "pull" if s.horizontal_N else "watch"
    if out["action"] != "watch":
        site = model.site(f"{p.prefix}load_point").id
        out |= {"body": int(model.site_bodyid[site]), "at": model.site_pos[site].round(4).tolist()}
    return out


def _item_bodies(model: mujoco.MjModel, p: Placed) -> dict[int, TopItem]:
    return {model.body(f"{p.prefix}item_{i}").id: item for i, item in enumerate(p.d.top_items)}


def _stuff_bodies(model: mujoco.MjModel, p: Placed) -> dict[int, str]:
    """The contents of open shelves, as loose bodies: {body: what it is ("books")}."""
    kinds = {part.body: part.name for part in p.d.parts() if part.body.startswith("stuff_")}
    out = {}
    for body in kinds:
        zone = p.d.zones[int(body.split("_")[1])]
        kept = contents()[zone.contents]
        out[model.body(f"{p.prefix}{body}").id] = kept.short or zone.contents
    return out


def _spilled(data: mujoco.MjData, stuff: dict[int, str], start_z: dict[int, float]) -> set[str]:
    return {what for b, what in stuff.items() if data.xipos[b][2] < start_z[b] - ITEM_DROP_M}


def _fallen(data: mujoco.MjData, items: dict[int, TopItem], start_z: dict[int, float]) -> list[TopItem]:
    return [item for b, item in items.items() if data.xipos[b][2] < start_z[b] - ITEM_DROP_M]


class _Bumps:
    """Pieces knocking into each other: a contact between the bodies of two different pieces (an item
    falling off one counts as that piece). Reported once per pair, the more tilted piece first."""

    def __init__(self, model: mujoco.MjModel, placed: list[Placed]):
        owner = {}
        for k, p in enumerate(placed):
            owner[model.body(f"{p.prefix}carcass").id] = k
            owner |= dict.fromkeys(_item_bodies(model, p), k) | dict.fromkeys(_stuff_bodies(model, p), k)
        self.piece = np.array([owner.get(int(model.body_rootid[model.geom_bodyid[g]]), -1) for g in range(model.ngeom)])
        self.carcasses = [model.body(f"{p.prefix}carcass").id for p in placed]
        self.seen: set[frozenset[int]] = set()

    def check(self, data: mujoco.MjData, t: float, tracer: "Trace | None"):
        if not data.ncon:
            return
        a, b = self.piece[data.contact.geom1], self.piece[data.contact.geom2]
        for i, j in zip(a, b, strict=True):
            pair = frozenset((int(i), int(j)))
            if i < 0 or j < 0 or i == j or pair in self.seen:
                continue
            self.seen.add(pair)
            first, second = sorted(pair, key=lambda k: -_tilt_deg(data, self.carcasses[k]))
            if tracer:
                tracer.event(t, "knocked into", first, second)


def _open(model: mujoco.MjModel, data: mujoco.MjData, p: Placed) -> None:
    """Start with the drawers and doors the scenario opens already open."""
    n, d, s = p.prefix, p.d, p.s
    for dr in d.drawers():
        if dr.index in s.open_drawers:
            data.qpos[model.jnt_qposadr[model.joint(f"{n}slide_{dr.index}").id]] = d.travel(dr)
            data.ctrl[model.actuator(f"{n}open_{dr.index}").id] = d.travel(dr)
    for door in d.door_list():
        if door.index in s.open_doors:
            data.qpos[model.jnt_qposadr[model.joint(f"{n}hinge_{door.index}").id]] = DOOR_OPEN_RAD
            data.ctrl[model.actuator(f"{n}swing_{door.index}").id] = DOOR_OPEN_RAD


def simulate(d: Dresser, s: Scenario, video: Path | None = None, size=(640, 480), trace: bool = False) -> SimResult:
    return simulate_scene([Placed(d, s)], video, size, trace)[0]


def simulate_scene(placed: list[Placed], video: Path | None = None, size=(640, 480), trace: bool = False,
                   title: str = "", room: bool = False, ghosts: tuple[Ghost, ...] = ()) -> list[SimResult]:  # fmt: skip
    """Every piece under its own scenario's load at the same time, in one model: one result each."""
    model = mujoco.MjModel.from_xml_string(scene_mjcf(placed, room, ghosts))
    data = mujoco.MjData(model)
    alone = len(placed) == 1
    carcasses = [model.body(f"{p.prefix}carcass").id for p in placed]
    loads, shown = [], []  # the load sites; the weights and pull arrows, drawn while the loads act
    for p in placed:
        s = p.s
        if s.vertical_N or s.horizontal_N:
            site = model.site(f"{p.prefix}load_point").id
            loads.append((site, model.site_bodyid[site], s.horizontal_N, s.vertical_N))
        shown += [f"{p.prefix}weight"] * bool(s.vertical_N) + [f"{p.prefix}pull"] * bool(s.horizontal_N)
        _open(model, data, p)
    vis = [model.geom(n).id for n in shown]
    mujoco.mj_forward(model, data)
    loose = _Loose(model)
    items = [_item_bodies(model, p) for p in placed]
    start_z = [{b: data.xipos[b][2] for b in its} for its in items]
    recorder = _Recorder(model, video, size) if video else None
    tracer = Trace(model, placed, ghosts) if trace else None
    if tracer:
        tracer.load_geoms = shown
        tracer.phases = {"settle": SETTLE, "ramp": RAMP}
    bumps = None if alone else _Bumps(model, placed)
    cam = _camera(placed[0].d)
    title = title or placed[0].s.title

    steps = int((SETTLE + RAMP + HOLD) / model.opt.timestep)
    frame_every = _frame_every(model)
    settled, max_tilt, fell = [0.0] * len(placed), [0.0] * len(placed), [False] * len(placed)
    for i in range(steps):
        t = i * model.opt.timestep
        load = _smooth((t - SETTLE) / RAMP)
        data.qfrc_applied[:] = 0
        if load > 0:
            for site, body, horizontal_N, vertical_N in loads:
                force = (0, horizontal_N * load, -vertical_N * load)
                mujoco.mj_applyFT(model, data, force, (0, 0, 0), data.site_xpos[site], body, data.qfrc_applied)
        for g in vis:
            model.geom_rgba[g][3] = 1.0 if load > 0 else 0.0
        mujoco.mj_step(model, data)
        loose.cap(data)

        for k, carcass in enumerate(carcasses):
            tilt = _tilt_deg(data, carcass)
            if t < SETTLE:
                settled[k] = tilt
            else:
                max_tilt[k] = max(max_tilt[k], tilt - settled[k])
                if tracer and not fell[k] and tilt - settled[k] > FELL_DEG:
                    fell[k] = True
                    tracer.event(t, "It tipped over" if alone else "tipped over", k)
        if bumps and t >= SETTLE and i % 10 == 0:
            bumps.check(data, t, tracer)
        if i % frame_every == 0:
            if recorder:
                recorder.frame(data, cam)
            if tracer:
                tracer.add(data, load=load)
                tracer.caption(t, "Settling" if load <= 0 else title)

    if recorder:
        recorder.close()
    results = []
    for k, carcass in enumerate(carcasses):
        final = _tilt_deg(data, carcass) - settled[k]
        if tracer and final > TIP_DEG and not fell[k]:
            tracer.event(steps * model.opt.timestep, "It tipped over" if alone else "tipped over", k)
        results.append(SimResult(final > TIP_DEG, max_tilt[k], final, video,
                                 [it.name for it in _fallen(data, items[k], start_z[k])]))  # fmt: skip
    trace_out = tracer.to_dict() if tracer else None
    for r in results:
        r.trace = trace_out
    return results


# --- Earthquake ----------------------------------------------------------------


@dataclass(frozen=True)
class Stage:
    label: str
    pga_g: float  # peak floor acceleration
    seconds: float


# Peak floor acceleration at the USGS ShakeMap intensity levels VI (strong) to IX (violent)
STAGES = (
    Stage("Strong shaking", 0.15, 5.0),
    Stage("Very strong shaking", 0.30, 5.0),
    Stage("Severe shaking", 0.50, 5.0),
    Stage("Violent shaking", 0.80, 5.0),
)
QUIET_BEFORE, QUIET_AFTER, RAMP_S = 1.0, 2.5, 0.6
FELL_DEG = 45.0  # tilted this far, the piece has fallen over
DRAWER_OUT_M = 0.05  # a shut drawer slid this far out has "slid open"


@dataclass
class QuakeResult:
    stages: list[dict]  # per stage: label, pga_g, piece_fell, items_fell, drawers_out
    fell_at: str | None  # the stage at which the piece fell over, if it did
    drawers_out_at: str | None = None  # the stage at which the first drawer slid open
    video: Path | None = None
    trace: dict | None = None


# Kanai-Tajimi ground filter with the Clough-Penzien high-pass, firm-to-soft soil values: the
# textbook stochastic model of strong ground motion. Most energy sits around 1-3 Hz; the high-pass
# keeps the floor from drifting away.
SOIL_HZ, SOIL_DAMPING, HIGHPASS_HZ, HIGHPASS_DAMPING = 2.0, 0.6, 0.25, 0.6


def _filtered_noise(rng: np.random.Generator, n: int, dt: float, building_hz: float | None = None):
    """Acceleration and displacement shapes (unscaled) of one horizontal component. `building_hz`
    adds the sway of a building at that natural frequency (5% damping), i.e. the motion of an upper
    floor rather than the ground."""
    w = 2 * np.pi * np.fft.rfftfreq(n, dt)
    wg, zg, wf, zf = 2 * np.pi * SOIL_HZ, SOIL_DAMPING, 2 * np.pi * HIGHPASS_HZ, HIGHPASS_DAMPING
    soil = (wg**2 + 2j * zg * wg * w) / (wg**2 - w**2 + 2j * zg * wg * w)
    highpass = w**2 / (wf**2 - w**2 + 2j * zf * wf * w)
    spectrum = np.fft.rfft(rng.standard_normal(n)) * soil * highpass
    if building_hz:
        wb, zb = 2 * np.pi * building_hz, 0.05
        spectrum *= (wb**2 + 2j * zb * wb * w) / (wb**2 - w**2 + 2j * zb * wb * w)
    accel = np.fft.irfft(spectrum, n)
    with np.errstate(divide="ignore", invalid="ignore"):
        disp = np.fft.irfft(np.where(w > 0, -spectrum / w**2, 0), n)
    return accel, disp


def ground_motion(stages=STAGES, dt: float = SIGNAL_DT, seed: int = 1, building_hz: float | None = None):
    """Synthetic floor shaking (`_filtered_noise`), scaled so each stage peaks at its acceleration,
    with short ramps between stages. Returns time (n,), acceleration (n, 2) in g across and front to
    back, and displacement (n, 2) in m for the video. Front to back, the direction furniture tips,
    gets the full shaking; across gets 60%. Made at SIGNAL_DT and sampled every `dt`."""
    rng = np.random.default_rng(seed)
    starts = QUIET_BEFORE + np.cumsum([0.0] + [s.seconds for s in stages])
    total = starts[-1] + QUIET_AFTER
    every, dt = max(1, round(dt / SIGNAL_DT)), SIGNAL_DT
    t = np.arange(0.0, total, dt)
    acc, disp = np.zeros((len(t), 2)), np.zeros((len(t), 2))
    for axis, share in ((0, 0.6), (1, 1.0)):
        shape, shape_disp = _filtered_noise(rng, len(t), dt, building_hz)
        knots_t, knots_a = [0.0, starts[0]], [0.0, 0.0]
        for s, a, b in zip(stages, starts[:-1], starts[1:], strict=True):
            peak = np.abs(shape[(t >= a + RAMP_S) & (t < b)]).max()
            knots_t += [a + RAMP_S, b]
            knots_a += [s.pga_g / peak] * 2
        knots_t += [starts[-1] + RAMP_S, total]
        knots_a += [0.0, 0.0]
        env = share * np.interp(t, knots_t, knots_a)
        acc[:, axis] = env * shape
        disp[:, axis] = env * shape_disp * 9.81
    return t[::every], acc[::every], disp[::every]


def quake_scenario(d: Dresser, anchored: bool = False, locks: bool = False) -> Scenario:
    """Drawers shut and full of clothes, held by nothing but their runners' friction, so they can slide
    out and shift the weight forward. With drawer interlocks (`locks`) only the top one can."""
    top = d.top_drawer()
    loose = frozenset({top.index}) if locks and top else frozenset(dr.index for dr in d.drawers())
    return Scenario("earthquake", "Earthquake", frozenset(), fill=True, anchored=anchored, loose_drawers=loose)


def shake(
    d: Dresser,
    anchored: bool = False,
    video: Path | None = None,
    size=(640, 480),
    seed: int = 1,
    building_hz: float | None = None,
    trace: bool = False,
    locks: bool = False,
) -> QuakeResult:
    """Shake the piece against a wall through STAGES (`quake_scenario`)."""
    return shake_scene([Placed(d, quake_scenario(d, anchored, locks))], video, size, seed, building_hz, trace)[0]


def shake_scene(
    placed: list[Placed],
    video: Path | None = None,
    size=(640, 480),
    seed: int = 1,
    building_hz: float | None = None,
    trace: bool = False,
    ghosts: tuple[Ghost, ...] = (),
) -> list[QuakeResult]:
    """Shake every piece in one room through STAGES, each under its own `quake_scenario`: one result
    each. Pieces stand against a shared wall and can knock into each other."""
    model = mujoco.MjModel.from_xml_string(scene_mjcf(placed, room=True, ghosts=ghosts))
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    loose = _Loose(model)
    alone = len(placed) == 1
    carcasses = [model.body(f"{p.prefix}carcass").id for p in placed]
    items = [_item_bodies(model, p) for p in placed]
    start_z = [{b: data.xipos[b][2] for b in its} for its in items]
    stuff = [_stuff_bodies(model, p) for p in placed]
    stuff_z = [{b: data.xipos[b][2] for b in st} for st in stuff]
    slides = [{dr.index: model.jnt_qposadr[model.joint(f"{p.prefix}slide_{dr.index}").id] for dr in p.d.drawers()}
              for p in placed]  # fmt: skip
    t, acc, disp = ground_motion(dt=model.opt.timestep, seed=seed, building_hz=building_hz)
    starts = QUIET_BEFORE + np.cumsum([0.0] + [st.seconds for st in STAGES])
    stage_at = np.clip(np.searchsorted(starts, t, side="right") - 1, -1, len(STAGES) - 1)

    recorder = _Recorder(model, video, size) if video else None
    tracer = Trace(model, placed, ghosts) if trace else None
    if tracer:
        tracer.phases = {"quiet": QUIET_BEFORE}
    bumps = None if alone else _Bumps(model, placed)
    cam = _camera(placed[0].d)
    lookat = cam.lookat.copy()
    frame_every = _frame_every(model)
    results = [[{"label": st.label, "pga_g": st.pga_g, "piece_fell": False, "items_fell": [], "drawers_out": []}
                for st in STAGES] for _ in placed]  # fmt: skip
    fell_at: list[str | None] = [None] * len(placed)
    drawers_at: list[str | None] = [None] * len(placed)
    seen: list[set[str]] = [set() for _ in placed]
    spilled: list[set[str]] = [set() for _ in placed]
    out: list[set[int]] = [set() for _ in placed]
    events = []  # the video's captions
    g = -model.opt.gravity[2]
    for i in range(len(t)):
        model.opt.gravity[:] = (-acc[i, 0] * g, -acc[i, 1] * g, -g)
        mujoco.mj_step(model, data)
        loose.cap(data)
        k = int(stage_at[i])
        if k >= 0 and i % 10 == 0:
            for j, p in enumerate(placed):
                if fell_at[j] is None and _tilt_deg(data, carcasses[j]) > FELL_DEG:
                    fell_at[j] = STAGES[k].label
                    results[j][k]["piece_fell"] = True
                    events.append(f"It fell over at {STAGES[k].pga_g:.2f} g")
                    if tracer:
                        tracer.event(t[i], "It fell over" if alone else "fell over", j)
                for drawer, adr in slides[j].items():
                    if drawer not in out[j] and data.qpos[adr] > DRAWER_OUT_M:
                        out[j].add(drawer)
                        results[j][k]["drawers_out"].append(drawer)
                        if drawers_at[j] is None:
                            drawers_at[j] = STAGES[k].label
                            what = "Drawers slid open" if len(p.s.loose_drawers) > 1 else "A drawer slid open"
                            events.append(f"{what} at {STAGES[k].pga_g:.2f} g")
                            if tracer:
                                tracer.event(t[i], what if alone else what.lower(), j)
                for what in sorted(_spilled(data, stuff[j], stuff_z[j]) - spilled[j]):
                    spilled[j].add(what)
                    events.append(f"{what[0].upper()}{what[1:]} fell at {STAGES[k].pga_g:.2f} g")
                    if tracer:
                        tracer.event(t[i], f"{what[0].upper()}{what[1:]} fell off the shelves" if alone
                                     else f"{what} fell off the shelves", j)  # fmt: skip
                for item in _fallen(data, items[j], start_z[j]):
                    if item.name not in seen[j]:
                        seen[j].add(item.name)
                        results[j][k]["items_fell"].append(item.name)
                        name = item.name if alone else item.short or item.name
                        events.append(f"{name[0].upper()}{name[1:]} fell at {STAGES[k].pga_g:.2f} g")
                        if tracer:
                            tracer.event(t[i], f"{name[0].upper()}{name[1:]} fell" if alone else f"{name} fell", j)
            if bumps:
                bumps.check(data, t[i], tracer)
        if (recorder or tracer) and i % frame_every == 0:
            if t[i] < starts[0]:
                title = "Before the earthquake"
            elif t[i] >= starts[-1]:
                title = "After the shaking"
            else:
                title = f"{k + 1}/{len(STAGES)}  {STAGES[k].label}  {STAGES[k].pga_g:.2f} g"
            if tracer:
                tracer.add(data, ground=disp[i])
                tracer.caption(float(t[i]), title)
            if recorder:
                cam.lookat[:] = lookat - (disp[i, 0], disp[i, 1], 0)
                subtitle = ("Strapped to the wall", "#15803d") if placed[0].s.anchored else ("Not strapped", "#6b6b76")
                recorder.frame(data, cam, [(title, "#16161a"), subtitle] + [(e, "#c0392b") for e in events])
    model.opt.gravity[:] = (0, 0, -g)
    if recorder:
        recorder.close()
    trace_out = tracer.to_dict() if tracer else None
    return [QuakeResult(results[j], fell_at[j], drawers_at[j], video, trace_out) for j in range(len(placed))]
