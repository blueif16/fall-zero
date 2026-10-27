"""MuJoCo simulation and video of a template under a scenario, and the staged earthquake.

Load tests: start with the drawers already open (the standard's setup), settle, ramp the load in
(the standard asks for >= 5 s; 2 s is still quasi-static here), then hold. Opening drawers inside
the sim would add a dynamic jolt the static test doesn't have; a loaded tall dresser can tip from
that alone, which is a separate scenario. The piece "tipped" if it ends up rotated more than
TIP_DEG past where it settled.

Things standing on top (TV, boxes) are loose bodies: they ride along, slide, topple and fall.

Earthquake (`shake`): the floor shakes harder stage by stage. Rather than move the floor, the
simulation runs in the floor's frame, where shaking is the same as an extra sideways gravity on
everything; the video camera moves against the floor so the room is seen to shake.
"""

import math
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

os.environ.setdefault("MUJOCO_GL", "egl")

import mujoco  # noqa: E402
import numpy as np  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from fall_zero.furniture import DOOR_OPEN_RAD, Dresser  # noqa: E402
from fall_zero.physics import Scenario, load_point, tilt_angle  # noqa: E402

SETTLE, RAMP, HOLD = 1.0, 2.0, 4.0
TIP_DEG = 5.0
FPS = 30

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


def _vec(v) -> str:
    return " ".join(f"{x:.5f}" for x in v)


def build_mjcf(d: Dresser, s: Scenario, room: bool = False) -> str:
    """`room` adds a solid back wall 3 cm behind the piece, as in a real room."""
    phi = tilt_angle(d, s.block)
    lift = d.front_support_y * math.sin(phi) + 0.0005
    quat = (math.cos(-phi / 2), math.sin(-phi / 2), 0, 0)

    bodies: dict[str, list[str]] = {}
    for p in d.parts(fill=s.fill):
        contact = 'contype="1" conaffinity="1"' if p.body in ("carcass",) or p.kind == "load" else \
            'contype="2" conaffinity="0"'  # fmt: skip
        if p.kind == "fill":  # contents ride with their drawer or shelf
            contact = 'contype="0" conaffinity="0"'
        color = p.color or COLORS["tv" if "_tv" in p.name else p.kind]
        bodies.setdefault(p.body, []).append(
            f'<geom name="{p.name}" type="box" pos="{_vec(p.center)}" size="{_vec(np.array(p.size) / 2)}" '
            f'mass="{p.mass:.4f}" rgba="{color}" {contact} friction="0.6"/>'
        )
    # Items on top are their own loose bodies, set down 2 mm above where they stand
    items = "".join(
        f'<body name="{b}" pos="0 0 {lift + 0.002:.5f}" quat="{_vec(quat)}"><freejoint/>{"".join(g)}</body>'
        for b, g in bodies.items() if b.startswith("item_")
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
                f'<site name="load_point" pos="{_vec((dr.x, y, z))}" size="0.01"/>'
                # the 60 lb test weight and the pull, drawn only while they act
                f'<geom name="weight" type="box" pos="{_vec((dr.x, y + 0.07, z - 0.18))}" size="0.12 0.05 0.16" '
                f'mass="0.001" rgba=".85 .15 .15 0" contype="0" conaffinity="0"/>'
                f'<geom name="pull" type="capsule" fromto="{_vec((dr.x, y, z))} {_vec((dr.x, y + 0.35, z))}" '
                f'size="0.012" mass="0.001" rgba=".85 .15 .15 0" contype="0" conaffinity="0"/>'
            )
        if dr.index in s.loose_drawers:  # only the runners' friction holds it; the stop at full travel catches it
            slide = f'frictionloss="{d.runner_friction * drawer_kg[name] * 9.81:.3f}" damping="2"'
        else:
            slide = 'damping="40"'
            actuators.append(
                f'<position name="open_{dr.index}" joint="slide_{dr.index}" kp="20000" dampratio="1" '
                f'ctrlrange="0 {d.travel(dr):.4f}"/>'
            )
        drawers.append(
            f'<body name="{name}"><joint name="slide_{dr.index}" type="slide" axis="0 1 0" '
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
            extra = (f'<site name="load_point" pos="{_vec((x, y, z))}" size="0.01"/>'
                     f'<geom name="weight" type="box" pos="{_vec((x, y, z - 0.18))}" size="{weight_size}" '
                     'mass="0.001" rgba=".85 .15 .15 0" contype="0" conaffinity="0"/>')  # fmt: skip
        drawers.append(
            f'<body name="{name}"><joint name="hinge_{door.index}" type="hinge" pos="{_vec(pivot)}" '
            f'axis="{_vec(axis)}" range="0 {math.degrees(DOOR_OPEN_RAD):.2f}" damping="5"/>'
            f"{''.join(bodies[name])}{extra}</body>"
        )
        actuators.append(
            f'<position name="swing_{door.index}" joint="hinge_{door.index}" kp="3000" dampratio="1" '
            f'ctrlrange="0 {DOOR_OPEN_RAD:.4f}"/>'
        )

    carcass_extra = ""
    if s.load_drawer is None and s.load_door is None and (s.horizontal_N or s.vertical_N):
        y, z = (d.depth / 2, s.horizontal_z) if s.horizontal_N else load_point(d, s)
        carcass_extra = (
            f'<site name="load_point" pos="0 {y:.4f} {z:.4f}" size="0.01"/>'
            f'<geom name="pull" type="capsule" fromto="0 {y:.4f} {z:.4f} 0 {y + 0.35:.4f} {z:.4f}" size="0.012" '
            f'mass="0.001" rgba=".85 .15 .15 0" contype="0" conaffinity="0"/>'
            f'<geom name="weight" type="box" pos="0 {y + 0.07:.4f} {z - 0.18:.4f}" size="0.12 0.05 0.16" '
            f'mass="0.001" rgba=".85 .15 .15 0" contype="0" conaffinity="0"/>'
        )
    world_extra, tendon = "", ""
    if s.block:
        w, yb = d.width + 0.04, d.rear_support_y
        world_extra += (
            f'<geom name="carpet_block" type="box" pos="0 {yb + 0.025:.4f} {s.block / 2:.5f}" '
            f'size="{w / 2:.4f} 0.03 {s.block / 2:.5f}" rgba=".3 .3 .35 1" contype="1" conaffinity="3"/>'
        )
    if room and not s.anchored:
        wall_y = -d.depth / 2 - 0.03
        world_extra += (
            f'<geom name="wall" type="box" pos="0 {wall_y - 0.01:.4f} 1.2" size="2 0.01 1.2" rgba=".93 .93 .9 1" '
            'contype="1" conaffinity="1"/>'
        )
    if s.anchored:
        # Fit the strap where the unit stands, tilt included, with 1 mm of slack
        strap_z = d.height - 0.05
        unit_y = -d.depth / 2 * math.cos(phi) + strap_z * math.sin(phi)
        unit_z = d.depth / 2 * math.sin(phi) + strap_z * math.cos(phi) + lift
        wall_y = unit_y - 0.03
        world_extra += (
            f'<geom name="wall" type="box" pos="0 {wall_y - 0.01:.4f} 1.2" size="2 0.01 1.2" rgba=".93 .93 .9 1" '
            f'contype="{int(room)}" conaffinity="{int(room)}"/>'
            f'<site name="strap_wall" pos="0 {wall_y:.4f} {unit_z:.4f}" size="0.012"/>'
        )
        carcass_extra += f'<site name="strap_unit" pos="0 {-d.depth / 2:.4f} {strap_z:.4f}" size="0.012"/>'
        tendon = (
            '<tendon><spatial name="strap" limited="true" range="0 0.031" width="0.006" rgba=".2 .2 .2 1">'
            '<site site="strap_wall"/><site site="strap_unit"/></spatial></tendon>'
        )

    return f"""
<mujoco model="fall-zero">
  <option timestep="0.001" integrator="implicitfast" noslip_iterations="10"/>
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
    {world_extra}
    <body name="carcass" pos="0 0 {lift:.5f}" quat="{_vec(quat)}">
      <freejoint/>
      {"".join(bodies["carcass"])}{carcass_extra}
      {"".join(drawers)}
    </body>
    {items}
  </worldbody>
  {tendon}
  <actuator>{"".join(actuators)}</actuator>
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


class _Recorder:
    """Renders frames into an H.264 file through ffmpeg."""

    def __init__(self, model: mujoco.MjModel, video: Path, size=(640, 480)):
        video.parent.mkdir(parents=True, exist_ok=True)
        self.renderer = mujoco.Renderer(model, size[1], size[0])
        self.ffmpeg = subprocess.Popen(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
             "-s", f"{size[0]}x{size[1]}", "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-pix_fmt", "yuv420p",
             str(video)],
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
    each body's world pose per frame. Far smaller and faster than a video: the browser draws it."""

    def __init__(self, model: mujoco.MjModel):
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
        self.strap = [names["strap_wall"], names["strap_unit"]] if "strap_unit" in names else None
        self.frames, self.straps, self.loads, self.shift = [], [], [], []
        self.load_geoms: list[str] = []  # the test weight or pull arrow, drawn while the load acts
        self.captions: list[tuple[float, str]] = []
        self.events: list[tuple[float, str]] = []

    def add(self, data: mujoco.MjData, load_on: bool = False, ground=(0.0, 0.0)):
        self.frames.append(np.hstack([data.xpos[1:], data.xquat[1:]]).round(4).ravel().tolist())
        self.loads.append(int(load_on))
        self.shift.append([round(float(ground[0]), 4), round(float(ground[1]), 4)])
        if self.strap:
            self.straps.append(np.hstack([data.site_xpos[i] for i in self.strap]).round(4).tolist())

    def caption(self, t: float, text: str):
        if not self.captions or self.captions[-1][1] != text:
            self.captions.append((round(t, 3), text))

    def to_dict(self) -> dict:
        return {"fps": FPS, "nbody": self.model.nbody - 1, "geoms": self.geoms, "frames": self.frames,
                "loads": self.loads, "load_geoms": self.load_geoms, "shift": self.shift, "straps": self.straps or None,
                "captions": self.captions, "events": self.events}  # fmt: skip


def _item_bodies(model: mujoco.MjModel, d: Dresser) -> dict[int, str]:
    return {model.body(f"item_{i}").id: item.name for i, item in enumerate(d.top_items)}


def _fallen(data: mujoco.MjData, items: dict[int, str], start_z: dict[int, float]) -> list[str]:
    return [name for b, name in items.items() if data.xipos[b][2] < start_z[b] - ITEM_DROP_M]


def simulate(d: Dresser, s: Scenario, video: Path | None = None, size=(640, 480), trace: bool = False) -> SimResult:
    model = mujoco.MjModel.from_xml_string(build_mjcf(d, s))
    data = mujoco.MjData(model)
    carcass = model.body("carcass").id
    site = model.site("load_point").id if s.vertical_N or s.horizontal_N else None
    load_body = model.site_bodyid[site] if site is not None else None
    shown = ["weight"] * bool(s.vertical_N) + ["pull"] * bool(s.horizontal_N)  # drawn while the load acts
    vis = [model.geom(n).id for n in shown]
    for dr in d.drawers():
        if dr.index in s.open_drawers:
            data.qpos[model.jnt_qposadr[model.joint(f"slide_{dr.index}").id]] = d.travel(dr)
            data.ctrl[model.actuator(f"open_{dr.index}").id] = d.travel(dr)
    for door in d.door_list():
        if door.index in s.open_doors:
            data.qpos[model.jnt_qposadr[model.joint(f"hinge_{door.index}").id]] = DOOR_OPEN_RAD
            data.ctrl[model.actuator(f"swing_{door.index}").id] = DOOR_OPEN_RAD
    mujoco.mj_forward(model, data)
    items = _item_bodies(model, d)
    start_z = {b: data.xipos[b][2] for b in items}
    recorder = _Recorder(model, video, size) if video else None
    tracer = Trace(model) if trace else None
    if tracer:
        tracer.load_geoms = shown
    cam = _camera(d)

    steps = int((SETTLE + RAMP + HOLD) / model.opt.timestep)
    frame_every = round(1 / FPS / model.opt.timestep)
    settled = max_tilt = 0.0
    for i in range(steps):
        t = i * model.opt.timestep
        load = _smooth((t - SETTLE) / RAMP)
        data.qfrc_applied[:] = 0
        if site is not None and load > 0:
            force = (0, s.horizontal_N * load, -s.vertical_N * load)
            mujoco.mj_applyFT(model, data, force, (0, 0, 0), data.site_xpos[site], load_body, data.qfrc_applied)
        for g in vis:
            model.geom_rgba[g][3] = 1.0 if load > 0 else 0.0
        mujoco.mj_step(model, data)

        tilt = _tilt_deg(data, carcass)
        if t < SETTLE:
            settled = tilt
        else:
            max_tilt = max(max_tilt, tilt - settled)
        if i % frame_every == 0:
            if recorder:
                recorder.frame(data, cam)
            if tracer:
                tracer.add(data, load_on=load > 0)
                tracer.caption(t, "Settling" if load <= 0 else s.title)

    if recorder:
        recorder.close()
    final = _tilt_deg(data, carcass) - settled
    if tracer and final > TIP_DEG:
        tracer.events.append((round(steps * model.opt.timestep, 3), "It tipped over"))
    return SimResult(final > TIP_DEG, max_tilt, final, video, _fallen(data, items, start_z),
                     tracer.to_dict() if tracer else None)  # fmt: skip


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


def ground_motion(stages=STAGES, dt: float = 0.001, seed: int = 1, building_hz: float | None = None):
    """Synthetic floor shaking (`_filtered_noise`), scaled so each stage peaks at its acceleration,
    with short ramps between stages. Returns time (n,), acceleration (n, 2) in g across and front to
    back, and displacement (n, 2) in m for the video. Front to back, the direction furniture tips,
    gets the full shaking; across gets 60%."""
    rng = np.random.default_rng(seed)
    starts = QUIET_BEFORE + np.cumsum([0.0] + [s.seconds for s in stages])
    total = starts[-1] + QUIET_AFTER
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
    return t, acc, disp


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
    """Shake the piece, drawers shut and full of clothes, against a wall, through STAGES. Nothing holds
    the drawers shut but their runners' friction, so they can slide out and shift the weight forward.
    With drawer interlocks (`locks`) only one can: the top one."""
    top = d.top_drawer()
    loose = frozenset({top.index}) if locks and top else frozenset(dr.index for dr in d.drawers())
    s = Scenario("earthquake", "Earthquake", frozenset(), fill=True, anchored=anchored, loose_drawers=loose)
    model = mujoco.MjModel.from_xml_string(build_mjcf(d, s, room=True))
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    carcass = model.body("carcass").id
    items = _item_bodies(model, d)
    start_z = {b: data.xipos[b][2] for b in items}
    slides = {dr.index: model.jnt_qposadr[model.joint(f"slide_{dr.index}").id] for dr in d.drawers()}
    t, acc, disp = ground_motion(dt=model.opt.timestep, seed=seed, building_hz=building_hz)
    starts = QUIET_BEFORE + np.cumsum([0.0] + [st.seconds for st in STAGES])
    stage_at = np.clip(np.searchsorted(starts, t, side="right") - 1, -1, len(STAGES) - 1)

    recorder = _Recorder(model, video, size) if video else None
    tracer = Trace(model) if trace else None
    cam = _camera(d)
    lookat = cam.lookat.copy()
    frame_every = round(1 / FPS / model.opt.timestep)
    results = [{"label": st.label, "pga_g": st.pga_g, "piece_fell": False, "items_fell": [], "drawers_out": []}
               for st in STAGES]  # fmt: skip
    fell_at, drawers_at, seen, out, events = None, None, set(), set(), []
    g = -model.opt.gravity[2]
    for i in range(len(t)):
        model.opt.gravity[:] = (-acc[i, 0] * g, -acc[i, 1] * g, -g)
        mujoco.mj_step(model, data)
        k = int(stage_at[i])
        if k >= 0 and i % 10 == 0:
            if fell_at is None and _tilt_deg(data, carcass) > FELL_DEG:
                fell_at = STAGES[k].label
                results[k]["piece_fell"] = True
                events.append(f"It fell over at {STAGES[k].pga_g:.2f} g")
                if tracer:
                    tracer.events.append((round(float(t[i]), 3), "It fell over"))
            for j, adr in slides.items():
                if j not in out and data.qpos[adr] > DRAWER_OUT_M:
                    out.add(j)
                    results[k]["drawers_out"].append(j)
                    if drawers_at is None:
                        drawers_at = STAGES[k].label
                        what = "Drawers slid open" if len(loose) > 1 else "A drawer slid open"
                        events.append(f"{what} at {STAGES[k].pga_g:.2f} g")
                        if tracer:
                            tracer.events.append((round(float(t[i]), 3), what))
            for name in _fallen(data, items, start_z):
                if name not in seen:
                    seen.add(name)
                    results[k]["items_fell"].append(name)
                    events.append(f"{name[0].upper()}{name[1:]} fell at {STAGES[k].pga_g:.2f} g")
                    if tracer:
                        tracer.events.append((round(float(t[i]), 3), f"{name[0].upper()}{name[1:]} fell"))
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
                subtitle = ("Strapped to the wall", "#15803d") if anchored else ("Not strapped", "#6b6b76")
                recorder.frame(data, cam, [(title, "#16161a"), subtitle] + [(e, "#c0392b") for e in events])
    model.opt.gravity[:] = (0, 0, -g)
    if recorder:
        recorder.close()
    return QuakeResult(results, fell_at, drawers_at, video, tracer.to_dict() if tracer else None)
