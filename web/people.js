// The people the engine's test load stands for, drawn as faceless mannequins: a child of about five
// (1.10 m, the 60 lb test child) and an older adult (1.66 m).
//
// Nothing is animated joint by joint. Each frame an actor script says where the feet and hands must
// be (pinned to points on the simulated bodies, so they ride a sliding drawer or a tilting carcass)
// and how the torso would like to lean; `solve` then places the pelvis, leans the torso (crouching if
// it must) until the hands are in reach, and bends each limb with two-bone IK: knees forward, elbows
// back and out. Every bone is a capsule laid between its two joints.
//
// All positions are in MuJoCo's frame (z up, metres), the frame of the viewer's room group. A person
// faces the piece: the piece's front is +y, so they look along -y and their right is -x. Pieces stand
// square to the wall, so ledges are found with world-aligned boxes.

import * as THREE from "three";

const UP = new THREE.Vector3(0, 0, 1);
const Y_AXIS = new THREE.Vector3(0, 1, 0);
const clamp = (x, a, b) => Math.min(b, Math.max(a, x));
const smooth = (x) => ((x = clamp(x, 0, 1)), x * x * (3 - 2 * x));
const easeOut = (x) => 1 - (1 - clamp(x, 0, 1)) ** 2;
const lerp = (a, b, t) => a + (b - a) * t;
const v3 = (x = 0, y = 0, z = 0) => new THREE.Vector3(x, y, z);
const mix = (a, b, t) => a.clone().lerp(b, t);

export const WALK_S = 1.5; // the walk-in before the trace plays
export const REACT_S = 1.4; // how long a reaction to a tip runs
export const LET_GO_DEG = 10; // tilted this far past where it settled, the piece is going: let go
const PUSH_IN = 0.07, PUSH_OUT = 0.025; // m a frame: how fast what falls can shove a person, and lets go

// Body sizes (m) and looks. `pelvis` and `chest` are lathe profiles [height above the hip joints,
// radius]; the torso is squashed front to back by `depth`. `head` radii: side, front-back, up.
const KINDS = {
  child: {
    height: 1.1, ankle: 0.05, shin: 0.245, thigh: 0.255, hip: 0.058, spine: 0.3, shoulder: 0.118,
    neck: 0.045, head: [0.084, 0.093, 0.104], upper: 0.18, fore: 0.155, hand: 0.055, foot: 0.15,
    r: { thigh: 0.05, shin: 0.037, upper: 0.034, fore: 0.028, hand: 0.03, foot: 0.03, neck: 0.033 },
    pelvis: [[-0.078, 0], [-0.074, 0.05], [-0.05, 0.086], [-0.01, 0.1], [0.06, 0.096], [0.13, 0.092]],
    chest: [[0.06, 0.084], [0.1, 0.099], [0.18, 0.106], [0.25, 0.114], [0.3, 0.104], [0.335, 0.072], [0.352, 0.03], [0.356, 0]],
    depth: 0.74, sleeves: "short", shorts: true, hairCap: 0.56, stoop: 0,
    colors: { top: "#6f9fcf", bottom: "#41618c", skin: "#efdcc9", hair: "#6e5646", shoes: "#3a3d48" },
    // walking: step length (m), steps a second, foot lift (m), arm swing (rad); `sit`: hip height
    // sitting on the floor; `rise`: the highest step up the legs take at once
    step: 0.34, cadence: 2.7, lift: 0.05, swing: 0.34, sit: 0.085, rise: 0.47,
  },
  adult: {
    height: 1.66, ankle: 0.07, shin: 0.4, thigh: 0.42, hip: 0.088, spine: 0.47, shoulder: 0.185,
    neck: 0.06, head: [0.079, 0.096, 0.107], upper: 0.29, fore: 0.25, hand: 0.075, foot: 0.24,
    r: { thigh: 0.074, shin: 0.05, upper: 0.045, fore: 0.037, hand: 0.038, foot: 0.04, neck: 0.045 },
    pelvis: [[-0.1, 0], [-0.096, 0.08], [-0.065, 0.142], [-0.01, 0.16], [0.09, 0.15], [0.19, 0.138]],
    chest: [[0.1, 0.125], [0.17, 0.142], [0.28, 0.155], [0.38, 0.168], [0.45, 0.158], [0.5, 0.11], [0.525, 0.05], [0.53, 0]],
    depth: 0.64, sleeves: "long", shorts: false, hairCap: 0.6, stoop: 0.07,
    colors: { top: "#a08fbf", bottom: "#5a5d6c", skin: "#efdcc9", hair: "#d9d8de", shoes: "#3a3d48" },
    step: 0.5, cadence: 1.9, lift: 0.045, swing: 0.24, sit: 0.11, rise: 0.4,
  },
};
for (const k of Object.values(KINDS)) {
  k.leg = k.thigh + k.shin;
  k.arm = k.upper + k.fore + 0.5 * k.hand;
  k.standHip = k.ankle + 0.985 * k.leg;
}

// The pose of body `b` at a fractional frame, eased between frames: {p, q} in the room's frame.
export function poser(trace) {
  const n = trace.frames.length, qa = new THREE.Quaternion(), qb = new THREE.Quaternion();
  return (b, ft, p = v3(), q = new THREE.Quaternion()) => {
    if (!b) return { p: p.set(0, 0, 0), q: q.identity() };
    ft = clamp(ft, 0, n - 1);
    const f = Math.floor(ft), u = ft - f, A = trace.frames[f], B = trace.frames[Math.min(n - 1, f + 1)], k = (b - 1) * 7;
    p.set(lerp(A[k], B[k], u), lerp(A[k + 1], B[k + 1], u), lerp(A[k + 2], B[k + 2], u));
    qa.set(A[k + 4], A[k + 5], A[k + 6], A[k + 3]);
    qb.set(B[k + 4], B[k + 5], B[k + 6], B[k + 3]);
    return { p, q: q.slerpQuaternions(qa, qb, u) };
  };
}

// How far body `b` leans from upright at frame f, in degrees
export function tiltDeg(trace, b, f) {
  const k = (b - 1) * 7, [, x, y] = trace.frames[f].slice(k + 3, k + 6);
  return THREE.MathUtils.radToDeg(Math.acos(clamp(1 - 2 * (x * x + y * y), -1, 1)));
}

// --- The mannequin --------------------------------------------------------------------------------

export class Person {
  constructor(kind) {
    const k = (this.k = KINDS[kind]);
    this.group = new THREE.Group();
    this.geometries = [];
    this.materials = [];
    const mat = (color) => {
      const m = new THREE.MeshStandardMaterial({ color, roughness: 0.82, metalness: 0 });
      m.userData.opacity = 1;
      this.materials.push(m);
      return m;
    };
    const M = Object.fromEntries(Object.entries(k.colors).map(([name, c]) => [name, mat(c)]));
    const add = (geo, m, parent = this.group) => {
      this.geometries.push(geo);
      const mesh = new THREE.Mesh(geo, m);
      mesh.castShadow = true;
      parent.add(mesh);
      return mesh;
    };
    const capsule = (r, len, m) => add(new THREE.CapsuleGeometry(r, Math.max(0.001, len), 6, 16), m);
    const lathe = (pts, m) => add(new THREE.LatheGeometry(pts.map(([y, r]) => new THREE.Vector2(r, y)), 32), m);
    const pair = (make) => [make(), make()];
    this.pelvis = lathe(k.pelvis, M.bottom);
    this.chest = lathe(k.chest, M.top);
    this.neck = capsule(k.r.neck, k.neck + 0.03, M.skin);
    this.head = add(new THREE.SphereGeometry(1, 32, 22), M.skin);
    this.hair = add(new THREE.SphereGeometry(1, 32, 14, 0, 2 * Math.PI, 0, Math.PI * k.hairCap), M.hair, this.head);
    this.hair.scale.setScalar(1.045);
    this.hair.rotation.x = 0.42; // the cap sits back on the head: the face stays bare
    this.thigh = pair(() => capsule(k.r.thigh, k.thigh, M.bottom));
    this.shin = pair(() => capsule(k.r.shin, k.shin, k.shorts ? M.skin : M.bottom));
    this.foot = pair(() => capsule(k.r.foot, k.foot - 2 * k.r.foot, M.shoes));
    this.upper = pair(() => capsule(k.r.upper, k.upper, M.top));
    this.fore = pair(() => capsule(k.r.fore, k.fore, k.sleeves === "long" ? M.top : M.skin));
    this.hand = pair(() => add(new THREE.SphereGeometry(1, 18, 12), M.skin));
    this.group.traverse((o) => o.isMesh && (o.userData.person = true));
  }

  // Lay every bone between its joints (from `solve`)
  place(J) {
    const k = this.k;
    orient(this.pelvis, J.right, J.upT, J.P).scale.set(1, 1, k.depth);
    orient(this.chest, J.right, J.upT, J.P).scale.set(1, 1, k.depth);
    bone(this.neck, J.S, J.headC);
    orient(this.head, J.headR, J.headU, J.headC).scale.set(k.head[0], k.head[2], k.head[1]);
    for (let i = 0; i < 2; i++) {
      bone(this.thigh[i], J.hips[i], J.knees[i]);
      bone(this.shin[i], J.knees[i], J.ankles[i]);
      const d = J.footDir[i], u = J.footUp[i];
      this.foot[i].position.copy(J.ankles[i]).addScaledVector(d, 0.27 * k.foot).addScaledVector(u, k.r.foot - k.ankle);
      this.foot[i].quaternion.setFromUnitVectors(Y_AXIS, d);
      bone(this.upper[i], J.shoulders[i], J.elbows[i]);
      bone(this.fore[i], J.elbows[i], J.wrists[i]);
      const h = J.handDir[i], side = v3().crossVectors(h, J.upT);
      if (side.lengthSq() < 1e-6) side.copy(J.right);
      side.normalize();
      orient(this.hand[i], side, h, J.palms[i]).scale.set(k.r.hand * 1.05, k.hand * 0.6, k.r.hand * 0.72);
    }
  }

  dispose() {
    this.group.removeFromParent();
    this.geometries.forEach((g) => g.dispose());
    this.materials.forEach((m) => m.dispose());
  }
}

const _m = new THREE.Matrix4();
function orient(mesh, x, y, pos) {
  const z = v3().crossVectors(x, y);
  _m.makeBasis(x, y, z);
  mesh.quaternion.setFromRotationMatrix(_m);
  mesh.position.copy(pos);
  return mesh;
}

function bone(mesh, a, b) {
  mesh.position.addVectors(a, b).multiplyScalar(0.5);
  const d = v3().subVectors(b, a);
  if (d.lengthSq() > 1e-10) mesh.quaternion.setFromUnitVectors(Y_AXIS, d.normalize());
}

// --- Solving a pose ---------------------------------------------------------------------------------

// The middle joint of a two-bone limb from `a` toward `t`, bent toward `pole`. Returns [mid, end]; the
// end stops short when the target is out of reach.
function ik(a, t, l1, l2, pole) {
  const d = v3().subVectors(t, a);
  let len = d.length();
  const dir = len > 1e-6 ? d.divideScalar(len) : v3(0, 0, -1);
  len = clamp(len, Math.abs(l1 - l2) + 1e-3, (l1 + l2) * 0.9995);
  const x = (l1 * l1 - l2 * l2 + len * len) / (2 * len), h = Math.sqrt(Math.max(0, l1 * l1 - x * x));
  const perp = pole.clone().addScaledVector(dir, -pole.dot(dir));
  if (perp.lengthSq() < 1e-8) perp.set(-dir.y, dir.x, 0.3);
  perp.normalize();
  const mid = a.clone().addScaledVector(dir, x).addScaledVector(perp, h);
  return [mid, a.clone().addScaledVector(dir, len)];
}

const torsoUp = (fwd, th) => UP.clone().multiplyScalar(Math.cos(th)).addScaledVector(fwd, Math.sin(th));

/* A pose spec: {
     fwd: the way the person faces (horizontal unit),
     ankles: [left, right] ankle points; planted: [bool, bool] (does the foot carry the pelvis),
     P: the hip centre (optional: otherwise it sits as high as the planted legs allow, over `weight`
        between the feet, moved `shift` along fwd, lowered by `drop`),
     theta: torso lean forward (rad), reach: lean (at most maxLean) or crouch until the hands are in
        reach (default true),
     hands: [left, right] palm points or null for a free arm, swing: free arms' swing forward (rad),
     footDir: [left, right] toe directions (default fwd), look: a point to look at } */
export function solve(k, s) {
  const fwd = s.fwd, right = v3().crossVectors(fwd, UP).normalize();
  const side = [right.clone().negate(), right];
  const hands = s.hands || [null, null];
  let P, theta = s.theta ?? 0;
  if (s.P) P = s.P.clone();
  else {
    const w = s.weight ?? 0.5;
    P = v3(lerp(s.ankles[0].x, s.ankles[1].x, w), lerp(s.ankles[0].y, s.ankles[1].y, w), 0);
    if (s.shift) P.addScaledVector(fwd, s.shift);
    P.z = legHeight(k, P, side, s.ankles, s.planted || [true, true]) - (s.drop || 0);
  }
  if (s.reach !== false && (hands[0] || hands[1])) [P, theta] = fitReach(k, P, theta, fwd, side, hands, s.drop || 0, s.maxLean);

  const upT = torsoUp(fwd, theta), S = P.clone().addScaledVector(upT, k.spine);
  const hips = side.map((d) => P.clone().addScaledVector(d, k.hip));
  const shoulders = side.map((d) => S.clone().addScaledVector(d, k.shoulder));
  const J = { P, S, theta, right, upT, hips, shoulders, knees: [], ankles: [], footDir: [], footUp: [], elbows: [], wrists: [], palms: [], handDir: [] };
  for (let i = 0; i < 2; i++) {
    // knees forward on the floor; with the foot up on a ledge, forward and up over it, or (when the
    // piece is in the way, as with a stack of open drawers) up and out to the side
    const raised = smooth((s.ankles[i].z - P.z + k.leg * 0.85) / 0.25) * (s.climbing ? 1 : 0);
    const poles = [fwd.clone().addScaledVector(UP, 0.45 + 0.7 * raised).addScaledVector(side[i], 0.14 + 0.16 * raised)];
    if (raised > 0) {
      poles.push(fwd.clone().multiplyScalar(0.2).addScaledVector(UP, 1).addScaledVector(side[i], 0.6));
      poles.push(fwd.clone().multiplyScalar(-0.35).addScaledVector(UP, 0.8).addScaledVector(side[i], 0.9));
    }
    let knee, ankle;
    for (const pole of poles) {
      [knee, ankle] = ik(hips[i], s.ankles[i], k.thigh, k.shin, pole);
      if (!s.clear || s.clear(hips[i], knee, ankle)) break;
    }
    J.knees.push(knee);
    J.ankles.push(ankle);
    const d = (s.footDir?.[i] || fwd).clone().normalize();
    const u = UP.clone().addScaledVector(d, -UP.dot(d));
    J.footDir.push(d);
    J.footUp.push(u.lengthSq() > 1e-6 ? u.normalize() : fwd.clone().negate());

    let elbow, wrist, hdir;
    if (hands[i]) {
      const toHand = v3().subVectors(hands[i], shoulders[i]);
      const wristT = hands[i].clone().addScaledVector(toHand.normalize(), -0.5 * k.hand);
      const apole = fwd.clone().multiplyScalar(-0.7).addScaledVector(side[i], 0.75).addScaledVector(UP, -0.45);
      [elbow, wrist] = ik(shoulders[i], wristT, k.upper, k.fore, apole);
      hdir = v3().subVectors(wrist, elbow).normalize();
    } else {
      const a = (s.swing?.[i] || 0) + 0.04, flex = 0.22 + Math.max(0, a) * 0.6;
      const d1 = UP.clone().multiplyScalar(-Math.cos(a)).addScaledVector(fwd, Math.sin(a)).addScaledVector(side[i], 0.13).normalize();
      elbow = shoulders[i].clone().addScaledVector(d1, k.upper);
      hdir = UP.clone().multiplyScalar(-Math.cos(a + flex)).addScaledVector(fwd, Math.sin(a + flex)).addScaledVector(side[i], 0.08).normalize();
      wrist = elbow.clone().addScaledVector(hdir, k.fore);
    }
    J.elbows.push(elbow);
    J.wrists.push(wrist);
    J.handDir.push(hdir);
    J.palms.push(wrist.clone().addScaledVector(hdir, 0.5 * k.hand));
  }

  // the head stays nearer upright than the torso, and turns toward what it looks at
  const neckUp = upT.clone().add(UP.clone().multiplyScalar(0.7)).normalize();
  const headC = S.clone().addScaledVector(neckUp, k.neck + 0.85 * k.head[2]).addScaledVector(fwd, 0.012 + k.stoop * 0.25);
  let look = s.look ? v3().subVectors(s.look, headC) : fwd.clone();
  look.normalize();
  const flat = fwd.clone().multiplyScalar(Math.cos(theta)).addScaledVector(UP, -Math.sin(theta) * 0.3).normalize();
  look = flat.lerp(look, 0.75).normalize();
  look.z = clamp(look.z, -0.75, 0.75);
  look.normalize();
  const headR = v3().crossVectors(look, neckUp);
  if (headR.lengthSq() < 1e-6) headR.copy(right);
  headR.normalize();
  J.headC = headC;
  J.headR = headR;
  J.headU = v3().crossVectors(headR, look).normalize();
  return J;
}

// As high as the planted legs allow, knees just soft
function legHeight(k, P, side, ankles, planted) {
  let z = Infinity;
  for (let i = 0; i < 2; i++) {
    if (!planted[i]) continue;
    const hx = P.x + side[i].x * k.hip - ankles[i].x, hy = P.y + side[i].y * k.hip - ankles[i].y;
    const reach = 0.985 * k.leg;
    z = Math.min(z, ankles[i].z + Math.sqrt(Math.max(0, reach * reach - hx * hx - hy * hy)));
  }
  return Number.isFinite(z) ? z : P.z;
}

// Lean the torso the least from its preferred angle (then crouch the least, then step the hips toward
// the hands) so both hands are within reach
function fitReach(k, P, pref, fwd, side, hands, drop0, maxLean = 1.15) {
  const reach = 0.965 * k.arm, lo = -0.7, hi = Math.max(pref, maxLean);
  const err = (Q, th) => {
    const up = torsoUp(fwd, th);
    let e = -Infinity;
    for (let i = 0; i < 2; i++) {
      if (!hands[i]) continue;
      const sh = Q.clone().addScaledVector(up, k.spine).addScaledVector(side[i], k.shoulder);
      e = Math.max(e, sh.distanceTo(hands[i]) - reach);
    }
    return e;
  };
  const scan = (Q) => {
    if (err(Q, pref) <= 0) return pref;
    for (let d = 0.04; d <= hi - lo; d += 0.04) {
      for (const sg of [1, -1]) {
        const th = pref + sg * d;
        if (th < lo || th > hi || err(Q, th) > 0) continue;
        let a = pref + sg * (d - 0.04), b = th; // a fails, b reaches: close in on the boundary
        for (let j = 0; j < 7; j++) {
          const m = (a + b) / 2;
          if (err(Q, m) <= 0) b = m;
          else a = m;
        }
        return b;
      }
    }
    return null;
  };
  let th = scan(P);
  if (th != null) return [P, th];
  const down = (d) => P.clone().addScaledVector(UP, -d);
  const maxDrop = Math.max(0, 0.5 * k.leg - drop0);
  if (scan(down(maxDrop)) != null) {
    let a = 0, b = maxDrop;
    for (let j = 0; j < 9; j++) {
      const m = (a + b) / 2;
      if (scan(down(m)) != null) b = m;
      else a = m;
    }
    const Q = down(b);
    return [Q, scan(Q)];
  }
  // still short: the hips go toward low hands; high ones stay out of reach, arms stretched up
  const Q = down(maxDrop), toward = v3();
  hands.forEach((h) => h && toward.add(h));
  toward.multiplyScalar(1 / ((hands[0] ? 1 : 0) + (hands[1] ? 1 : 0)));
  if (toward.z < P.z + k.spine) {
    toward.sub(Q).setZ(0);
    const far = toward.length();
    if (far > 1e-6) toward.divideScalar(far);
    for (let d = 0.02; d < 0.4; d += 0.02) {
      const R = Q.clone().addScaledVector(toward, d);
      const t2 = scan(R);
      if (t2 != null) return [R, t2];
    }
  }
  let best = pref;
  for (let th = lo; th <= hi; th += 0.05) if (err(P, th) < err(P, best)) best = th;
  return [P, best];
}

// --- Where to put hands and feet ----------------------------------------------------------------------

// The boxes of a piece as world boxes at frame 0, with the body each rides on: its boards (`kind`
// "board": no contents, items, wall or test load), the loose contents of its shelves ("stuff") or the
// things standing on top ("item")
function boards(trace, pose, prefix, kind = "board") {
  const out = [];
  for (const g of trace.geoms) {
    if (g.type !== "box" || !g.name.startsWith(prefix) || g.rgba[3] === 0) continue;
    const name = g.name.slice(prefix.length);
    if (kind === "board" ? /^(stuff_|item_|wall|carpet_block|weight|pull)/.test(name) : !name.startsWith(`${kind}_`)) continue;
    const { p, q } = pose(g.body, 0);
    const gq = new THREE.Quaternion(g.quat[1], g.quat[2], g.quat[3], g.quat[0]);
    const box = new THREE.Box3();
    for (let c = 0; c < 8; c++) {
      const corner = v3(c & 1 ? g.size[0] : -g.size[0], c & 2 ? g.size[1] : -g.size[1], c & 4 ? g.size[2] : -g.size[2]);
      box.expandByPoint(corner.applyQuaternion(gq).add(v3(...g.pos)).applyQuaternion(q).add(p));
    }
    out.push({ body: g.body, box, name: g.name });
  }
  return out;
}

// Everything in the room a person could collide with (every piece's boards and the things on top, the
// stand-ins for pieces the engine can't build; not loose contents, walls or the test load), as boxes in
// their bodies' frames, to be posed at any frame
function solids(trace) {
  return trace.geoms.filter((g) => g.type === "box" && g.rgba[3] > 0 && /^(p\d+_|ghost_)/.test(g.name)
    && !/^p\d+_(stuff_|wall|carpet_block|weight|pull)/.test(g.name))
    .map((g) => ({ body: g.body, pos: v3(...g.pos), q: new THREE.Quaternion(g.quat[1], g.quat[2], g.quat[3], g.quat[0]), half: v3(...g.size) }));
}

// Arcs for a hand or foot moving between holds: up first, then in, clear of the edges it passes
function arc(a, b, s, fwd, lift, back) {
  const v = smooth(s / 0.7), h = smooth((s - 0.25) / 0.75), bump = Math.sin(Math.PI * clamp(s, 0, 1));
  return v3(lerp(a.x, b.x, h), lerp(a.y, b.y, h), lerp(a.z, b.z, v)).addScaledVector(UP, lift * bump).addScaledVector(fwd, -back * bump);
}

const BALANCE = { balance: true }; // a free hand held out to the side for balance (standing up high)

// --- An actor: one person's whole part in a scene -----------------------------------------------------

export class Actor {
  // `a`: the trace's actor; `piece`: its entry in trace.pieces; `pose`: a poser(trace);
  // `start`: the frame the load starts; `tip`: the frame the piece passed LET_GO_DEG, or null
  constructor(trace, a, { piece, pose, start, tip }) {
    this.a = a;
    this.trace = trace;
    this.k = KINDS[a.kind] || KINDS.child;
    this.person = new Person(a.kind in KINDS ? a.kind : "child");
    this.index = piece.index;
    this.pose = pose;
    this.fps = trace.fps;
    this.n = trace.frames.length;
    this.start = start;
    this.ramp = trace.phases?.ramp ?? 2; // s: the load comes on over this long
    const { q: cq } = pose(a.carcass, 0);
    this.ahead = v3(0, -1, 0).applyQuaternion(cq).setZ(0).normalize(); // into the piece
    this.away = this.ahead.clone().negate();
    const prefix = `p${piece.index}_`;
    this.boards = boards(trace, pose, prefix);
    this.stuff = boards(trace, pose, prefix, "stuff"); // books on a shelf: in the way of a foot
    this.items = boards(trace, pose, prefix, "item"); // a TV on top: something to hold on to
    this.solids = solids(trace);
    this.front = piece.y + piece.depth / 2;
    this.face = this.ahead.clone();
    this.lastP = null;
    this.crowd = []; // the other people in the scene (set by the viewer)
    (this[`plan_${a.action}`] || this.plan_watch).call(this, piece);
    this.tip = this.letGo(tip);
    this.planWalk();
  }

  // a point on body b, fixed in that body (given in world at frame 0)
  pin(world, b) {
    if (!b) return { b: 0, l: world.clone() };
    const { p, q } = this.pose(b, 0);
    return { b, l: world.clone().sub(p).applyQuaternion(q.clone().invert()) };
  }

  at(pin, ft) {
    if (!pin.b) return pin.l.clone();
    const { p, q } = this.pose(pin.b, ft);
    return pin.l.clone().applyQuaternion(q).add(p);
  }

  sideOf(i) {
    const r = v3().crossVectors(this.face, UP).normalize();
    return i ? r : r.negate();
  }

  // the furthest anything of the piece sticks out at this x below height z (open drawers, doors)
  frontAt(x, z = 0.6, half = 0.25) {
    let y = this.front;
    for (const { box } of this.boards) if (box.min.z < z && box.max.x > x - half && box.min.x < x + half) y = Math.max(y, box.max.y);
    return y;
  }

  stanceAt(C) {
    this.stance = C.clone().setZ(0);
    this.stanceFeet = [0, 1].map((i) => this.pin(this.stance.clone().addScaledVector(this.sideOf(i), this.k.hip * 1.15).setZ(this.k.ankle), 0));
  }

  restHand(i) {
    const k = this.k;
    return this.stance.clone().addScaledVector(this.sideOf(i), k.shoulder + 0.04).addScaledVector(this.face, 0.03)
      .setZ(k.standHip + k.spine - 0.94 * k.arm);
  }

  // Ledges a hand or foot can use at this x: top faces of boards that reach the front, with nothing in
  // front of them just above (a drawer's bottom is behind its own front)
  ledges(x, half) {
    const covers = ({ box }) => box.min.x <= x - half && box.max.x >= x + half;
    const mine = this.boards.filter(covers);
    return mine.filter(({ box }) => box.max.y >= this.front - 0.05)
      .filter(({ box }) => !mine.some((o) => o.box.max.y > box.max.y + 0.01 && o.box.min.z < box.max.z + 0.05 && o.box.max.z > box.max.z + 0.01))
      .map(({ box, body }) => ({ z: box.max.z, y: box.max.y, depth: box.max.y - box.min.y, body, box }))
      .sort((p, q) => p.z - q.z);
  }

  // Is there something just above this ledge's front (the next drawer of a flush stack, books)? Then a
  // foot only fits on its edge, turned out
  blocked(x, e) {
    return [...this.boards, ...this.stuff].some(({ box }) => box !== e.box && box.min.x < x + 0.1 && box.max.x > x - 0.1
      && box.min.z > e.z - 0.03 && box.min.z < e.z + 0.2 && box.max.y > e.y - 0.1);
  }

  // Both feet on a ledge: on an open step the foot's middle over the board (the ball of the foot on a
  // drawer's front edge, the whole foot on a deep shelf); out on the edge, toes along it, when the
  // space above is taken
  footholds(x, e) {
    const k = this.k, edge = this.blocked(x, e);
    const inset = Math.min(e.depth / 2, 0.6 * k.foot); // the foot's middle this far behind the front
    return [0, 1].map((i) => {
      const base = v3(x, e.y, e.z + k.ankle).addScaledVector(this.sideOf(i), k.hip * (edge ? 1.5 : 1.1));
      const pin = this.pin(edge ? base.addScaledVector(this.face, -0.012) : base.addScaledVector(this.face, inset - 0.27 * k.foot), e.body);
      pin.dir = edge ? this.face.clone().multiplyScalar(0.55).addScaledVector(this.sideOf(i), 0.84).normalize() : this.face.clone();
      pin.edge = edge;
      return pin;
    });
  }

  // Where the hands hold when the feet are at height L: a ledge about a hand's height above them or, up
  // on the step itself (`last`), the top of something standing on the piece (a TV). Null when there is
  // none: nothing to hold up there.
  grip(x, L, feetY, last = false) {
    const k = this.k, H = k.height, up = 0.92 * (k.standHip + k.spine + k.arm - k.ankle);
    const holds = this.ledges(x, 0.16).map((e) => ({ ...e, x }));
    for (const { box, body } of last ? this.items : []) {
      const w = box.max.x - box.min.x;
      if (box.max.x < x - 0.3 || box.min.x > x + 0.3 || w < 0.12 || box.max.z - box.min.z < 0.08) continue;
      // its top, unless something else stands on it (a TV's foot under its screen)
      if (this.items.some((o) => o.box !== box && o.box.min.z > box.max.z - 0.01 && o.box.min.z < box.max.z + 0.06
        && o.box.min.x < box.max.x && o.box.max.x > box.min.x && o.box.min.y < box.max.y && o.box.max.y > box.min.y)) continue;
      const hx = w > 2 * k.shoulder + 0.1 ? clamp(x, box.min.x + k.shoulder + 0.05, box.max.x - k.shoulder - 0.05) : (box.min.x + box.max.x) / 2;
      holds.push({ z: box.max.z, y: box.max.y, depth: box.max.y - box.min.y, body, box, x: hx, item: true });
    }
    // about a hand's height above the feet, and not far behind them
    const cost = (e) => Math.abs(e.z - L - 0.62 * H) + 1.2 * Math.max(0, feetY - e.y - 0.05);
    const pick = holds.filter((e) => e.z >= L + 0.3 && e.z <= L + up).sort((p, q) => cost(p) - cost(q))[0];
    if (!pick) return null;
    const half = pick.item ? Math.min(k.shoulder * 1.05, (pick.box.max.x - pick.box.min.x) / 2 - 0.03) : k.shoulder * 1.05;
    return [0, 1].map((i) => this.pin(v3(pick.x, pick.y - 0.015, pick.z + 0.022).addScaledVector(this.sideOf(i), half), pick.body));
  }

  // the ledge a load point sits on (the drawer front or shelf board right under it)
  ledgeAt(p, body) {
    const under = this.boards.filter(({ box }) => box.min.x - 0.01 <= p.x && box.max.x + 0.01 >= p.x && Math.abs(box.max.z - p.z) < 0.05
      && box.min.y - 0.03 <= p.y && box.max.y + 0.03 >= p.y).sort((u, w) => w.box.max.y - u.box.max.y)[0];
    if (!under) return { z: p.z, y: p.y, depth: 0.03, body, box: null };
    const { box } = under;
    return { z: box.max.z, y: box.max.y, depth: box.max.y - box.min.y, body: under.body, box };
  }

  // A child standing on the load point: hands first, then one foot up, then the other, ledge by ledge,
  // the hands moving up to the next hold (or out for balance, up where there is nothing to hold)
  plan_stand() {
    const k = this.k, a = this.a;
    const step = this.at({ b: a.body, l: v3(...a.at) }, 0);
    const x = step.x;
    this.stanceAt(v3(x, this.frontAt(x, 0.5) + 0.77 * k.foot + 0.03, 0));
    // a ladder of ledges up to the step, none higher than a stride above the last
    const rungs = this.ledges(x, 0.1).filter((e) => e.z > 0.12 && e.z < step.z - 0.1);
    const ladder = [];
    let level = 0;
    while (step.z - level > k.rise) {
      const reachable = rungs.filter((e) => e.z > level + 0.1 && e.z <= level + k.rise);
      const next = reachable.length ? reachable[reachable.length - 1] : rungs.find((e) => e.z > level + 0.1);
      if (!next) break;
      ladder.push({ z: next.z, y: next.y, feet: this.footholds(x, next) });
      level = next.z;
    }
    const top = this.ledgeAt(step, a.body);
    ladder.push({ z: top.z, y: top.y, feet: this.footholds(x, top) });
    let hands = this.grip(x, 0, this.stance.y) || [null, null];
    // a foot up, then the other as the body rises and the hands move up; w: how long each move takes,
    // relative to the others
    this.keys = [{ feet: this.stanceFeet, hands: [null, null] }, { feet: this.stanceFeet, hands, w: 1 }];
    let feet = this.stanceFeet;
    ladder.forEach((rung, r) => {
      const lead = r % 2 ? 0 : 1, last = r === ladder.length - 1;
      this.keys.push({ feet: [0, 1].map((i) => (i === lead ? rung.feet[i] : feet[i])), hands, w: 1 });
      feet = rung.feet;
      hands = this.grip(x, rung.z, rung.y, last) || (last ? [BALANCE, BALANCE] : hands);
      this.keys.push({ feet, hands, w: 1.15 });
    });
    this.top = top.z + k.height;
    this.mode = "climb";
  }

  // A child hanging from the free edge of an open door: reach, then lift the feet
  plan_hang() {
    const k = this.k, a = this.a;
    const g = this.at({ b: a.body, l: v3(...a.at) }, 0);
    this.stanceAt(v3(g.x, Math.max(g.y, this.frontAt(g.x, 0.5, 0.1)) + 0.75 * k.foot + 0.06, 0));
    const hands = [0, 1].map((i) => this.pin(g.clone().addScaledVector(this.sideOf(i), 0.035).addScaledVector(UP, 0.02 * (i ? 1 : -1)), a.body));
    this.keys = [{ feet: this.stanceFeet, hands: [null, null] }, { feet: this.stanceFeet, hands }];
    this.top = Math.max(g.z + 0.15, k.height);
    this.mode = "hang";
  }

  // Hands on the load point, leaning back: a child tugging, or an older adult grabbing for balance
  plan_pull() {
    const k = this.k, a = this.a;
    const g = this.at({ b: a.body, l: v3(...a.at) }, 0);
    const shoulderZ = k.standHip + k.spine - 0.02, dz = shoulderZ - g.z, r = 0.9 * k.arm;
    const out = dz < r ? Math.sqrt(r * r - dz * dz) - 0.2 * k.spine : 0;
    this.stanceAt(v3(g.x, Math.max(this.frontAt(g.x, 0.5), g.y) + Math.max(0.7 * k.foot + 0.05, out), 0));
    const hands = [0, 1].map((i) => this.pin(g.clone().addScaledVector(this.sideOf(i), k.shoulder * 0.95).addScaledVector(UP, 0.018), a.body));
    this.keys = [{ feet: this.stanceFeet, hands: [null, null] }, { feet: this.stanceFeet, hands }];
    this.top = k.height;
    this.mode = "pull";
  }

  // Every drawer pulled open: the child stands beside it and watches
  plan_watch(piece) {
    const k = this.k;
    const corner = v3(piece.x, this.front, 0).addScaledVector(this.sideOf(1), piece.width / 2 + 0.24);
    const C = corner.addScaledVector(this.away, 0.3);
    this.face = v3(piece.x, this.front, 0).sub(C).setZ(0).normalize().lerp(this.ahead, 0.35).normalize();
    this.stanceAt(C);
    this.keys = [{ feet: this.stanceFeet, hands: [null, null] }];
    this.top = k.height;
    this.mode = "watch";
    this.lookAt = this.pin(v3(piece.x, this.front, piece.height * 0.6), this.a.carcass);
  }

  // The frame the person lets go: when the piece tips (from the viewer), or sooner when what they hold
  // or stand on (a TV on top) starts to fall on its own
  letGo(tip) {
    const held = new Set();
    for (const K of this.keys) for (const p of [...K.feet, ...K.hands]) if (p?.b && p.b !== this.a.carcass) held.add(p.b);
    const f0 = Math.max(0, this.start - 1);
    let first = tip;
    for (const b of held) {
      const base = tiltDeg(this.trace, b, f0);
      for (let f = f0; f < this.n && (first == null || f < first); f++) {
        if (tiltDeg(this.trace, b, f) - base > LET_GO_DEG) {
          first = f;
          break;
        }
      }
    }
    return first;
  }

  // Footsteps from the front-right to the stance, at the person's own step length and pace: the first
  // step from standing, full strides, then a closing step beside the other foot
  planWalk() {
    const k = this.k;
    const steps = Math.max(3, Math.round(WALK_S * k.cadence)), n = steps - 1;
    const right = v3().crossVectors(this.ahead, UP).normalize();
    const start = this.stance.clone().addScaledVector(right.multiplyScalar(0.42).addScaledVector(this.away, 0.91).normalize(), n * k.step);
    const path = v3().subVectors(this.stance, start);
    const yaw0 = Math.atan2(path.y, path.x), yaw1 = Math.atan2(this.face.y, this.face.x);
    let dyaw = yaw1 - yaw0;
    dyaw = Math.atan2(Math.sin(dyaw), Math.cos(dyaw));
    const yawAt = (j) => yaw0 + dyaw * smooth((j - n + 1.6) / 1.6);
    const print = (j, i) => {
      const yaw = yawAt(j), f = v3(Math.cos(yaw), Math.sin(yaw), 0), r = v3().crossVectors(f, UP);
      return { p: start.clone().addScaledVector(path, j / n).addScaledVector(r, (i ? 1 : -1) * k.hip * 1.15), yaw };
    };
    const feet = [print(0, 0), print(0, 1)];
    const plan = [];
    for (let j = 1; j <= n + 1; j++) {
      const i = j % 2; // the right foot leads
      const to = print(Math.min(j, n), i);
      plan.push({ i, from: feet[i], to, other: feet[1 - i] });
      feet[i] = to;
    }
    this.walk = { steps: plan, dt: WALK_S / plan.length, start };
  }

  // --- each frame ---

  // `clock`: {walk: seconds into the walk-in} or {ft: fractional trace frame, may run past the end}
  update(clock) {
    const s = clock.walk != null ? this.walkSpec(clock.walk) : this.specAt(clock.ft);
    const J = solve(this.k, s);
    this.person.place(J);
    this.lastP = J.P;
  }

  // A walking pose: the swinging foot lifts and moves over the middle of its step, both feet down at
  // either end; the hips travel at an even pace (speeding up from the start, slowing to the stance),
  // swaying a little over the standing foot; the arms swing opposite the legs.
  walkSpec(t) {
    const k = this.k, { steps, dt } = this.walk, T = steps.length * dt;
    const j = clamp(Math.floor(t / dt), 0, steps.length - 1), s = clamp(t / dt - j, 0, 1), st = steps[j];
    const last = j === steps.length - 1;
    // the swing, inside the step: the foot lifts, travels, then sets down (never skimming the floor)
    const u = clamp((s - 0.08) / 0.82, 0, 1), h = smooth((u - 0.1) / 0.78);
    const swingP = mix(st.from.p, st.to.p, h).setZ(k.ankle).addScaledVector(UP, k.lift * Math.sin(Math.PI * u) * (last ? 0.6 : 1));
    const ankles = [];
    ankles[st.i] = swingP;
    ankles[1 - st.i] = st.other.p.clone().setZ(k.ankle);
    const footDir = [];
    const turn = (a, b, x) => a + Math.atan2(Math.sin(b - a), Math.cos(b - a)) * x;
    const dirOf = (yaw) => v3(Math.cos(yaw), Math.sin(yaw), 0);
    footDir[st.i] = dirOf(turn(st.from.yaw, st.to.yaw, h));
    footDir[1 - st.i] = dirOf(st.other.yaw);
    const fwd = dirOf(turn(st.from.yaw, st.to.yaw, smooth(s)));
    // the hips: half a step a step at the start and end, a whole one in between, at an even pace
    const before = mix(st.from.p, st.other.p, 0.5), after = mix(st.to.p, st.other.p, 0.5);
    const e = j === 0 ? s * s : last ? s * (2 - s) : s;
    const P = mix(before, after, e);
    const lat = v3().crossVectors(fwd, UP).normalize();
    P.addScaledVector(lat, lat.dot(v3().subVectors(st.other.p, P)) * 0.2 * Math.sin(Math.PI * s) * (last ? 0.4 : 1));
    const planted = [true, true];
    planted[st.i] = u < 0.15 || u > 0.95; // carries weight until it is well off the floor
    const env = smooth(t / (0.8 * dt)) * (1 - smooth((t - T + 1.3 * dt) / (1.2 * dt)));
    const a = k.swing * env * -Math.cos((Math.PI * t) / dt); // the arm opposite the swinging foot comes forward
    const spec = { fwd, ankles, planted, footDir, swing: [a, -a], theta: 0.05 + k.stoop };
    const side = [v3().crossVectors(fwd, UP).negate(), v3().crossVectors(fwd, UP)];
    spec.P = P.setZ(Math.min(legHeight(k, P, side, ankles, planted), k.standHip));
    return spec;
  }

  // the pose the scenario asks for at trace frame ft, then the reaction once the piece goes
  specAt(ft) {
    if (this.tip != null && ft >= this.tip) return this.reaction(ft);
    return this.scripted(ft);
  }

  load(ft) {
    return smooth(clamp((ft - this.start) / (this.ramp * this.fps), 0, 1)); // the server ramps the load in
  }

  // Which two keys the pose is between at frame ft, and how far (0..1, even in time). The hands reach
  // for their first hold just before the load starts; a climb's moves then fill the load's ramp.
  phase(ft) {
    const keys = this.keys, t = ft / this.fps, t0 = this.start / this.fps;
    if (keys.length < 2) return [0, 0];
    const r0 = Math.max(0, t0 - 0.8), r1 = Math.max(r0 + 0.3, t0 - 0.1);
    if (t < r1 || this.mode !== "climb") return [0, clamp((t - r0) / (r1 - r0), 0, 1)];
    if (keys.length === 2) return [0, 1];
    // up before most of the load is on, and a moment before the piece goes
    const tipT = this.tip == null ? Infinity : this.tip / this.fps - 0.4;
    const end = clamp(tipT, t0 + 0.45 * this.ramp, t0 + 0.85 * this.ramp);
    const w = keys.slice(2).map((K) => K.w || 1), total = w.reduce((x, y) => x + y, 0);
    let x = (clamp((t - r1) / (end - r1), 0, 1)) * total;
    for (let i = 0; i < w.length; i++) {
      if (x <= w[i]) return [i + 1, x / w[i]];
      x -= w[i];
    }
    return [keys.length - 2, 1];
  }

  // a hand held out for balance, from where the feet are
  balanceHand(j, ankles) {
    const k = this.k, side = this.sideOf(j);
    const S = mix(ankles[0], ankles[1], 0.5).addScaledVector(UP, k.standHip + k.spine - k.ankle - 0.03);
    return S.addScaledVector(side, k.shoulder + 0.2 * k.arm / 0.36).addScaledVector(UP, -0.62 * k.arm).addScaledVector(this.face, 0.1 * k.arm / 0.36);
  }

  scripted(ft) {
    const k = this.k, keys = this.keys;
    const c = this.load(ft);
    const [i, s] = this.phase(ft);
    const A = keys[i], B = keys[Math.min(i + 1, keys.length - 1)];
    const ankles = [0, 1].map((j) => {
      const a = this.at(A.feet[j], ft), b = this.at(B.feet[j], ft);
      return A.feet[j] === B.feet[j] ? a : arc(a, b, s, this.face, 0.07, 0.07);
    });
    const hold = (pin, j) => (pin === BALANCE ? this.balanceHand(j, ankles) : this.at(pin, ft));
    const hands = [0, 1].map((j) => {
      if (!B.hands[j]) return null;
      const b = hold(B.hands[j], j);
      if (A.hands[j] === B.hands[j]) return b;
      const a = A.hands[j] ? hold(A.hands[j], j) : this.restHand(j);
      return arc(a, b, s, this.face, 0.05, 0.08);
    });
    const moving = [0, 1].map((j) => A.feet[j] !== B.feet[j]);
    const up = Math.max(ankles[0].z, ankles[1].z) - k.ankle > 0.08;
    const onEdge = (K) => ((K.feet[0].edge ? 1 : 0) + (K.feet[1].edge ? 1 : 0)) / 2;
    const footDir = [0, 1].map((j) => (A.feet[j].dir || this.face).clone().lerp(B.feet[j].dir || this.face, smooth(s)).normalize());
    const held = hands.filter((h, j) => h && B.hands[j] !== BALANCE);
    const spec = {
      fwd: this.face, ankles, hands, planted: moving.map((m) => !m || s < 0.05), footDir,
      weight: moving[0] ? 0.8 : moving[1] ? 0.2 : 0.5,
      shift: -lerp(onEdge(A), onEdge(B), s) * 0.14 * (k.height / 1.1) - (up ? 0.03 : 0),
      theta: (up ? -0.02 : 0.06) + k.stoop, climbing: this.mode === "climb",
      look: held.length ? mix(held[0], held.at(-1), 0.5).addScaledVector(UP, 0.1) : null,
    };
    if (spec.climbing) spec.clear = this.clear;
    if (this.mode === "pull") {
      spec.maxLean = 0.75; // a low hold: bend the knees rather than fold over it
      if (ft >= this.start) {
        spec.theta = lerp(0.05 + k.stoop, -0.3, c);
        spec.drop = 0.06 * c * (k.height / 1.1);
      }
    }
    if (this.mode === "hang" && ft >= this.start) this.hang(spec, smooth(c / 0.65), ft);
    if (this.mode === "watch") {
      spec.look = this.at(this.lookAt, ft);
      spec.swing = [0.05, 0.05];
    }
    return spec;
  }

  // Is a leg (hip, knee, ankle) clear of the piece's boards as they stood? Used to pick where a knee
  // goes on a high step.
  clear = (hip, knee, ankle) => {
    const r = this.k.r.shin;
    const pts = [knee, mix(hip, knee, 0.5), mix(knee, ankle, 0.35)];
    return !this.boards.some(({ box }) => pts.some((p) => p.x > box.min.x - r && p.x < box.max.x + r
      && p.y > box.min.y - r && p.y < box.max.y + r && p.z > box.min.z - r && p.z < box.max.z + r));
  };

  // the body lifts off the floor to hang from (or lean over) the door edge
  hang(spec, h, ft) {
    const k = this.k, fwd = this.face;
    const g = mix(spec.hands[0], spec.hands[1], 0.5);
    const below = g.z >= k.standHip + k.spine - 0.05; // a high hold: hang under it; a low one: lean over it
    const th = below ? 0.04 : 0.42;
    const S = below ? g.clone().addScaledVector(UP, -0.9 * k.arm).addScaledVector(fwd, -0.07)
      : g.clone().addScaledVector(UP, 0.86 * k.arm).addScaledVector(fwd, -0.13);
    const Ph = S.clone().addScaledVector(torsoUp(fwd, th), -k.spine);
    const P0 = this.stance.clone().setZ(k.standHip - 0.01);
    spec.P = mix(P0, Ph, h);
    spec.theta = lerp(spec.theta, th, h);
    spec.reach = false;
    const right = v3().crossVectors(fwd, UP).normalize();
    spec.ankles = spec.ankles.map((a, i) => {
      const hip = spec.P.clone().addScaledVector(right, (i ? 1 : -1) * k.hip);
      const dangle = hip.clone().addScaledVector(UP, -0.94 * k.leg).addScaledVector(fwd, below ? 0.03 : -0.1);
      if (dangle.z < k.ankle + 0.08) dangle.setZ(k.ankle + 0.08).addScaledVector(fwd, -0.12);
      return mix(a, dangle, h);
    });
    spec.planted = [h < 0.02, h < 0.02];
    spec.footDir = [0, 1].map(() => fwd.clone().addScaledVector(UP, -1.2 * h).normalize());
  }

  // --- the reaction when the piece tips ---

  base() {
    if (!this._base) {
      const J = solve(this.k, this.scripted(this.tip));
      this._base = { P: J.P.clone(), theta: J.theta, ankles: J.ankles.map((a) => a.clone()), palms: J.palms.map((p) => p.clone()) };
      // the floor each box covers from now on, low enough to land on someone there (a falling piece
      // sweeps the floor in front of it; one left standing covers its own footprint), as a rectangle
      // across (to the person's right) and out (away from their piece)
      const p = v3(), q = new THREE.Quaternion(), c = v3(), right = this.sideOf(1);
      this._base.floor = this.solids.map(() => [Infinity, -Infinity, Infinity, -Infinity]);
      for (let f = this.tip; f < this.n; f += f + 2 < this.n ? 2 : 1) {
        this.solids.forEach((s, j) => {
          const r = this._base.floor[j];
          this.pose(s.body, f, p, q);
          for (let n = 0; n < 8; n++) {
            c.set(n & 1 ? s.half.x : -s.half.x, n & 2 ? s.half.y : -s.half.y, n & 4 ? s.half.z : -s.half.z)
              .applyQuaternion(s.q).add(s.pos).applyQuaternion(q).add(p);
            if (c.z > 1) continue;
            const l = c.dot(right), a = c.dot(this.away);
            r[0] = Math.min(r[0], l); r[1] = Math.max(r[1], l); r[2] = Math.min(r[2], a); r[3] = Math.max(r[3], a);
          }
        });
      }
    }
    return this._base;
  }

  // Is this floor rectangle [across0, across1, out0, out1] clear of everything that comes down?
  clearOf(b, r) {
    return !b.floor.some((f) => f[0] < r[1] && f[1] > r[0] && f[2] < r[3] && f[3] > r[2]);
  }

  // The nearest place out of the way, as {back, lat} (m, along `away` and to the person's right) from
  // where they are: `area(back, lat)` is the floor they would cover there, `price` ranks the free spots
  // (by default the nearest, a little in favour of their right: away from the camera's line to the
  // piece, as it looks from the room's front-right). Null when none is free.
  spot(b, area, backs, lats, price = (back, lat) => Math.hypot(back, lat) + 0.3 * Math.max(0, -lat), avoid = []) {
    let best = null, cost = Infinity;
    for (const back of backs) {
      for (const lat of lats) {
        const c = price(back, lat), r = area(back, lat);
        if (c < cost && this.clearOf(b, r) && !avoid.some((f) => f[0] < r[1] && f[1] > r[0] && f[2] < r[3] && f[3] > r[2])) {
          [best, cost] = [{ back, lat }, c];
        }
      }
    }
    return best;
  }

  // Where a standing person steps to, out of the way of what falls: straight back, back and aside, or
  // out past the piece's side, whichever is nearest; the furthest back they can go when nothing is clear
  escape(b) {
    const k = this.k, right = this.sideOf(1), w = 0.22;
    const a0 = (b.ankles[0].dot(this.away) + b.ankles[1].dot(this.away)) / 2, l0 = (b.ankles[0].dot(right) + b.ankles[1].dot(right)) / 2;
    const area = (back, lat) => [l0 + lat - w, l0 + lat + w, a0 + back - 0.77 * k.foot - 0.05, a0 + back + 0.12];
    const range = (lo, hi, d) => Array.from({ length: Math.round((hi - lo) / d) + 1 }, (_, i) => lo + i * d);
    // the others in the scene, and the floor in front of them they may step back onto
    const crowd = this.crowd.map((o) => {
      const l = o.stance.dot(right), a = o.stance.dot(this.away);
      return [l - 0.32, l + 0.32, a - 0.3, a + 1.5];
    });
    const backs = range(0.35, 1.6, 0.05), lats = range(-1.2, 1.2, 0.1);
    this._escape ??= this.spot(b, area, backs, lats, undefined, crowd) || this.spot(b, area, backs, lats) || { back: 1.3, lat: 0 };
    return this._escape;
  }

  // A child lets go and falls back to sit on the floor; an adult staggers back, hands up in front.
  // Both end clear of where the piece lands, and are pushed clear when it reaches them on the way.
  reaction(ft) {
    const raw = this.reactRaw(ft), push = this.pushAt(ft);
    if (push > 0) {
      const d = this.pushDir().clone().multiplyScalar(push);
      raw.P.add(d);
      raw.ankles.forEach((a) => a.add(d));
      raw.hands.forEach((h) => h && h.add(d));
    }
    return raw;
  }

  // the way the person gets out of the way: where an adult steps to, back (and aside) for a falling child
  pushDir() {
    if (!this._pushDir) {
      const b = this.base(), { back, lat } = this.a.kind === "adult" ? this.escape(b) : this.landing(b);
      this._pushDir = this.away.clone().multiplyScalar(back).addScaledVector(this.sideOf(1), lat).normalize();
    }
    return this._pushDir;
  }

  reactRaw(ft) {
    const k = this.k, b = this.base(), tau = (ft - this.tip) / this.fps, fwd = this.face;
    const right = v3().crossVectors(fwd, UP).normalize(), side = [right.clone().negate(), right];
    const look = this.at({ b: this.a.carcass, l: v3(0, this.a.front, this.a.top * 0.6) }, ft);
    if (this.a.kind === "adult") {
      // in two to four hurried steps, back far enough that the toes end clear of where it lands or, when
      // that is further than stepping out to one side, back and aside
      const { back, lat } = this.escape(b);
      const D = Math.hypot(back, lat), move = this.away.clone().multiplyScalar(back).addScaledVector(right, lat).divideScalar(D);
      const n = D <= 0.45 ? 2 : D <= 0.9 ? 3 : 4, dur = 0.3, gap = 0.22, lead = lat < -0.05 ? 0 : 1;
      const ankles = b.ankles.map((a) => a.clone().setZ(Math.max(a.z, k.ankle)));
      const planted = [true, true];
      for (let m = 0; m < n; m++) {
        const i = m % 2 ? 1 - lead : lead, t0 = 0.04 + m * gap, u = clamp((tau - t0) / dur, 0, 1);
        if (u <= 0) continue;
        const to = b.ankles[i].clone().setZ(k.ankle).addScaledVector(move, Math.min(D, (D * (m + 1)) / (n - 1)))
          .addScaledVector(this.away, m === n - 1 ? -0.12 : 0);
        const from = ankles[i].clone();
        ankles[i] = mix(from, to, smooth(u)).addScaledVector(UP, 0.07 * Math.sin(Math.PI * u));
        if (u < 1) planted[i] = false;
      }
      const T = 0.04 + (n - 1) * gap + dur;
      const P = b.P.clone().addScaledVector(move, D * easeOut(tau / T)).addScaledVector(this.away, -0.06 * easeOut(tau / T));
      const startle = smooth(tau / 0.22), settle = smooth((tau - T) / 0.6);
      const theta = lerp(lerp(b.theta, -0.16, startle), 0.1, settle);
      const S = P.clone().addScaledVector(torsoUp(fwd, theta), k.spine);
      const hands = [0, 1].map((i) => {
        const guard = S.clone().addScaledVector(fwd, 0.3).addScaledVector(UP, 0.04).addScaledVector(side[i], 0.17);
        const rest = S.clone().addScaledVector(fwd, 0.2).addScaledVector(UP, -0.3).addScaledVector(side[i], 0.2);
        return mix(mix(b.palms[i], guard, smooth(tau / 0.2)), rest, settle);
      });
      const spec = { fwd, ankles, planted, hands, theta, reach: false, look };
      spec.P = P.setZ(Math.min(legHeight(k, P, side, ankles, planted), k.standHip) - 0.02);
      return spec;
    }
    // the child falls back onto the floor, the drop timed by gravity, landing with the feet clear of
    // where the piece comes down (as far as a fall back can carry them)
    const hipZ = k.sit, T = Math.max(0.36, Math.sqrt((2 * Math.max(0, b.P.z - hipZ)) / 9.81));
    const u = clamp(tau / T, 0, 1);
    const { back, lat } = this.landing(b);
    const Psit = b.P.clone().addScaledVector(this.away, back).addScaledVector(right, lat).setZ(hipZ);
    const P = v3(lerp(b.P.x, Psit.x, easeOut(u)), lerp(b.P.y, Psit.y, easeOut(u)), lerp(b.P.z, hipZ, u * u));
    const land = smooth((tau - T) / 0.35);
    const theta = lerp(lerp(b.theta, -0.55, smooth(u)), -0.3, land);
    const ankles = [0, 1].map((i) => {
      const to = Psit.clone().addScaledVector(fwd, 0.8 * k.leg).addScaledVector(side[i], k.hip * 1.6).setZ(k.ankle + 0.01);
      return mix(b.ankles[i], to, smooth(u * 1.1)).addScaledVector(UP, 0.12 * Math.sin(Math.PI * u));
    });
    const S = P.clone().addScaledVector(torsoUp(fwd, theta), k.spine);
    const hands = [0, 1].map((i) => {
      // arms fly up as they let go, then reach back to catch the fall: palms on the floor behind
      const flail = S.clone().addScaledVector(UP, 0.14).addScaledVector(fwd, 0.16).addScaledVector(side[i], 0.16);
      const prop = P.clone().addScaledVector(fwd, -0.16).addScaledVector(side[i], k.hip + 0.12).setZ(0.03);
      return mix(mix(b.palms[i], flail, smooth(tau / 0.22)), prop, smooth((tau - 0.6 * T) / (0.4 * T + 0.25)));
    });
    const toes = fwd.clone().addScaledVector(UP, 1.2 * smooth(u)).normalize();
    return { fwd, P, theta, ankles, hands, reach: false, footDir: [toes, toes], look };
  }

  // Where a child falling back off the piece sits down: as far back as the height carries them, further
  // (a little aside at most) when that is where the piece comes down
  landing(b) {
    if (!b.land) {
      const k = this.k, right = this.sideOf(1), a0 = b.P.dot(this.away), l0 = b.P.dot(right);
      const natural = 0.2 + 0.22 * clamp((b.P.z - k.standHip) / 0.8, 0, 1);
      const area = (back, lat) => [l0 + lat - 0.17, l0 + lat + 0.17, a0 + back - 0.82 * k.leg - 0.1, a0 + back + 0.2];
      const range = (lo, hi, d) => Array.from({ length: Math.round((hi - lo) / d) + 1 }, (_, i) => lo + i * d);
      b.land = this.spot(b, area, range(natural, natural + 0.6, 0.05), range(-0.3, 0.3, 0.05), (back, lat) => back + 2 * Math.abs(lat))
        || { back: natural + 0.45, lat: 0 };
    }
    return b.land;
  }

  // How far what falls pushes the person on, on their way out: as much as it takes to keep them out of
  // it, gaining at most PUSH_IN a frame (so it reads as a shove) and easing off by PUSH_OUT once their
  // own steps have taken them clear
  pushAt(ft) {
    this.pushes ??= [];
    const f = Math.floor(ft);
    while (this.pushes.length <= f - this.tip + 1) {
      const g = this.tip + this.pushes.length, prev = this.pushes.at(-1) || 0;
      this.pushes.push(g < this.n ? clamp(this.overlap(g), Math.max(0, prev - PUSH_OUT), prev + PUSH_IN) : prev);
    }
    const i = f - this.tip, a = this.pushes[i], b = this.pushes[i + 1] ?? a;
    return lerp(a, b, ft - f);
  }

  // How far along pushDir the body (head, chest, hips, knees, feet; not the hands, which were on the
  // piece) must move at frame g to be out of every box in the room
  overlap(g) {
    const k = this.k, J = solve(k, this.reactRaw(g)), dir0 = this.pushDir();
    const pts = [[J.P, 0.08], [J.S, 0.09], [J.headC, k.head[2]], ...J.knees.map((p) => [p, k.r.thigh]),
      ...J.ankles.map((p) => [p, k.r.foot]), ...J.ankles.map((p, i) => [p.clone().addScaledVector(J.footDir[i], 0.6 * k.foot), k.r.foot])];
    const boxes = this.solids.map((s) => {
      const p = v3(), q = new THREE.Quaternion();
      this.pose(s.body, g, p, q);
      const qi = q.clone().invert(), si = s.q.clone().invert();
      return { s, p, qi, si, dir: dir0.clone().applyQuaternion(qi).applyQuaternion(si) };
    });
    const l = v3();
    let total = 0;
    for (let round = 0; round < 4; round++) { // moving out of one box can move into another
      let need = 0;
      for (const { s, p, qi, si, dir } of boxes) {
        for (const [pt, r] of pts) {
          l.copy(pt).addScaledVector(dir0, total).sub(p).applyQuaternion(qi).sub(s.pos).applyQuaternion(si);
          const h = s.half;
          if (Math.abs(l.x) >= h.x + r || Math.abs(l.y) >= h.y + r || Math.abs(l.z) >= h.z + r) continue;
          let exit = Infinity;
          for (const ax of ["x", "y", "z"]) {
            if (dir[ax] > 1e-6) exit = Math.min(exit, (h[ax] + r - l[ax]) / dir[ax]);
            else if (dir[ax] < -1e-6) exit = Math.min(exit, (-h[ax] - r - l[ax]) / dir[ax]);
          }
          if (Number.isFinite(exit)) need = Math.max(need, exit + 0.005);
        }
      }
      if (need === 0 || total > 1.5) break;
      total += need;
    }
    return Math.min(total, 1.5);
  }

  // the reaction still running after the trace ends (s)
  get tail() {
    return this.tip == null ? 0 : Math.max(0, this.tip / this.fps + REACT_S - (this.n - 1) / this.fps);
  }

  // points to keep in frame: where they stand, how high they get, and where the reaction leaves them
  // (room frame)
  framePoints() {
    const p = this.stance, k = this.k;
    const out = [p.clone().addScaledVector(this.away, 0.15), p.clone().setZ(this.top), p.clone().addScaledVector(this.ahead, 0.2).setZ(this.top)];
    if (this.tip != null) {
      const end = this.reaction(this.tip + REACT_S * this.fps).P.clone();
      out.push(end.clone().addScaledVector(this.away, 0.2).setZ(0), end.setZ(end.z + k.spine + k.neck + 2 * k.head[2]));
    }
    return out;
  }
}
