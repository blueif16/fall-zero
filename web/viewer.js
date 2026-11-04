// Plays a simulation recorded by the server (sim.Trace): the geometry once, then every body's pose per
// frame, eased between frames. MuJoCo is z-up; three.js is y-up, so the whole room sits in a group
// turned -90° about x. In an earthquake the room group follows the floor's displacement.
//
// A room scene holds several pieces (their geoms are named p<i>_..., ghosts ghost_<k>). Each piece gets a
// numbered tag that floats above it; focusing a piece flies the camera to it and fades the others, with
// their people and fall zones.
//
// The engine's test load is drawn as the person it stands for (people.js): a child or an older adult
// walks in from the front-right while the scene holds its first frame, then climbs, hangs or pulls as
// the load ramps in, and lets go when the piece tips. A piece that may tip shows where it would land:
// a soft tinted area on the floor in front of it.
//
// Callbacks (all optional):
//   onFrame(t, progress)  t: seconds into the trace (0 during the walk-in); progress: 0..1 over the
//                         whole playback, walk-in included
//   onEnd()               the playback (and any reaction still running) finished
//   onTag(index)          a piece's tag was tapped
//   onTip(index, seconds) piece `index` passed 45°: seconds since the load began (in an earthquake,
//                         since the shaking began). Once per piece per playback.

import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { mergeGeometries } from "three/addons/utils/BufferGeometryUtils.js";
import { Actor, WALK_S, LET_GO_DEG, poser, tiltDeg } from "./people.js";

const zUp = ([x, y, z]) => new THREE.Vector3(x, z, -y);
const ease = (x) => 1 - Math.pow(1 - x, 3);
const smooth = (x) => ((x = Math.min(1, Math.max(0, x))), x * x * (3 - 2 * x));
const FELL_DEG = 45; // the server's "tipped over"
const LOAD_GEOM = /^(p\d+_)?(weight|pull)$/;
const STATUS_COLORS = { tips: ["--tips", "#dc2626"], maybe: ["--maybe", "#b45309"] };

export class SimViewer {
  constructor(host) {
    this.host = host;
    this.renderer = new THREE.WebGLRenderer({ antialias: true });
    this.renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    host.prepend(this.renderer.domElement);
    this.tagLayer = host.querySelector(".tags");

    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color("#f3f4f7");
    this.camera = new THREE.PerspectiveCamera(32, 16 / 9, 0.05, 80);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.maxPolarAngle = Math.PI / 2 - 0.05;
    this.controls.addEventListener("start", () => (this.flight = null)); // a drag takes over from a flight

    this.scene.add(new THREE.HemisphereLight("#ffffff", "#c9c4bb", 1.6));
    const sun = new THREE.DirectionalLight("#ffffff", 2.2);
    sun.position.set(2.5, 5, 3.5);
    sun.castShadow = true;
    sun.shadow.mapSize.set(2048, 2048);
    sun.shadow.bias = -0.0004;
    Object.assign(sun.shadow.camera, { left: -5, right: 5, top: 5, bottom: -5 });
    this.scene.add(sun);

    this.room = new THREE.Group(); // shakes with the floor
    this.room.rotation.x = -Math.PI / 2;
    this.scene.add(this.room);
    const floor = new THREE.Mesh(new THREE.PlaneGeometry(16, 16), new THREE.MeshStandardMaterial({ color: "#e9e6e0", roughness: 0.95 }));
    floor.receiveShadow = true;
    this.room.add(floor);
    const grid = new THREE.GridHelper(16, 32, "#d6d2ca", "#dedad3");
    grid.rotation.x = Math.PI / 2;
    grid.position.z = 0.001;
    this.room.add(grid);

    this.onFrame = null;
    this.onTag = null; // a tag was tapped: called with the piece's index
    this.onTip = null; // a piece fell: called with its index and the seconds since the load began
    this.playing = false;
    this.tags = [];
    this.owned = []; // everything a trace built, disposed on the next load
    this.actors = [];
    this.zones = [];
    new ResizeObserver(() => this.resize()).observe(host);
    this.visible = true;
    new IntersectionObserver(([e]) => (this.visible = e.isIntersecting)).observe(host);
    const tick = () => {
      requestAnimationFrame(tick);
      if (this.visible) this.draw();
    };
    tick();
  }

  resize() {
    const w = this.host.clientWidth, h = this.host.clientHeight;
    if (!w || !h) return;
    this.renderer.setSize(w, h, false);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
  }

  clear() {
    for (const o of this.owned) {
      o.removeFromParent();
      o.traverse((m) => {
        if (!m.isMesh) return;
        m.geometry.dispose();
        for (const mat of [m.material].flat()) {
          mat.map?.dispose();
          mat.dispose();
        }
      });
    }
    this.actors.forEach((a) => a.person.dispose());
    this.tags.forEach((t) => t.el.remove());
    this.owned = [];
    this.actors = [];
    this.zones = [];
    this.tags = [];
  }

  own(o, parent = this.room) {
    parent.add(o);
    this.owned.push(o);
    return o;
  }

  // `labels`: piece index -> {n, status}; `focus`: the piece to show, or null for the whole room;
  // `reframe`: fly the camera to it (otherwise a new run of the same view keeps where the user looked)
  load(trace, { labels = {}, focus = null, reframe = true } = {}) {
    this.clear();
    this.trace = trace;
    this.pose = poser(trace);
    this.bodies = Array.from({ length: trace.nbody }, () => this.own(new THREE.Group()));
    this.pieceOf = new Map(); // mesh -> piece index
    const ghostIndex = (trace.ghosts || []).map((g) => g.index);
    const loadGeoms = new Set(trace.load_geoms || []);
    for (const g of trace.geoms) {
      const [r, gr, b, a] = g.rgba;
      if (a === 0 || loadGeoms.has(g.name) || LOAD_GEOM.test(g.name)) continue; // the test load is drawn as a person
      const own = /^p(\d+)_(.*)$/.exec(g.name);
      const color = new THREE.Color(r, gr, b);
      let geo, mat;
      if (own && own[2].startsWith("stuff_")) {
        geo = spines(g, color);
        mat = new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.8 });
      } else {
        geo = g.type === "box" ? new THREE.BoxGeometry(2 * g.size[0], 2 * g.size[1], 2 * g.size[2])
          : new THREE.CylinderGeometry(g.size[0], g.size[0], 2 * g.size[1], 12).rotateX(Math.PI / 2);
        mat = new THREE.MeshStandardMaterial({ color, roughness: 0.75 });
      }
      if (a < 1) Object.assign(mat, { transparent: true, opacity: a, depthWrite: false });
      mat.userData.opacity = mat.opacity;
      const mesh = new THREE.Mesh(geo, mat);
      mesh.position.set(...g.pos);
      mesh.quaternion.set(g.quat[1], g.quat[2], g.quat[3], g.quat[0]);
      mesh.castShadow = mesh.receiveShadow = a === 1;
      // a piece's own geoms, not the wall or carpet block it may bring along
      const piece = own && !["wall", "carpet_block"].includes(own[2]) ? own[1]
        : /^ghost_\d+$/.test(g.name) ? ghostIndex[+g.name.slice(6)] : null;
      if (piece != null) this.pieceOf.set(mesh, +piece);
      // the camera frames a piece by its own boards (not what was on it or in it, which may fly off)
      mesh.userData.frame = piece != null && !(own && /^(stuff|item)_/.test(own[2]));
      if (g.body === 0) this.own(mesh);
      else this.bodies[g.body - 1].add(mesh);
    }
    // where anything can sensibly be: around the pieces, on the floor. A body outside (a box that slid off
    // across the room in an earthquake) is hidden and never framed.
    const places = [...(trace.pieces || []).map((p) => [p.x, p.y, p.width / 2]), ...(trace.ghosts || []).map((g) => [g.pos[0], g.pos[1], 0.5])];
    this.bounds = new THREE.Box3(new THREE.Vector3(-4, -2, -0.5), new THREE.Vector3(4, 5, 4));
    if (places.length) {
      this.bounds.min.set(Math.min(...places.map(([x, , w]) => x - w)) - 3, Math.min(...places.map(([, y]) => y)) - 2, -0.5);
      this.bounds.max.set(Math.max(...places.map(([x, , w]) => x + w)) + 3, Math.max(...places.map(([, y]) => y)) + 4, 4);
    }
    const nStraps = trace.straps ? trace.straps[0].length / 6 : 0;
    this.straps = Array.from({ length: nStraps }, () =>
      this.own(new THREE.Mesh(new THREE.CylinderGeometry(0.008, 0.008, 1, 8), new THREE.MeshStandardMaterial({ color: "#1d1d1f" }))));

    // When each piece let go and fell, from its tilt past where it settled
    const n = trace.frames.length;
    this.start = trace.loads.findIndex((l) => l > 0);
    this.quake = this.start < 0 && !(trace.actors || []).length;
    if (this.start < 0) this.start = Math.min(n - 1, Math.round(trace.fps)); // no load: the settle is 1 s
    const settled = this.quake ? 0 : Math.max(0, this.start - 1);
    this.falls = (trace.pieces || []).map((p) => {
      const base = tiltDeg(trace, p.body, settled);
      let letGo = null, fell = null;
      for (let f = settled; f < n && fell == null; f++) {
        const d = tiltDeg(trace, p.body, f) - base;
        if (letGo == null && d > LET_GO_DEG) letGo = f;
        if (d > FELL_DEG) fell = f;
      }
      return { index: p.index, letGo, fell };
    });

    // The people, and where a piece that may tip would land
    for (const a of trace.actors || []) {
      const piece = (trace.pieces || []).find((p) => p.body === a.carcass);
      if (!piece) continue;
      const fall = this.falls.find((x) => x.index === piece.index);
      const actor = new Actor(trace, a, { piece, pose: this.pose, start: this.start, tip: fall?.letGo ?? null });
      this.room.add(actor.person.group);
      actor.person.group.traverse((m) => m.isMesh && this.pieceOf.set(m, piece.index));
      this.actors.push(actor);
      const status = labels[piece.index]?.status;
      if (STATUS_COLORS[status] && !this.zones.some((z) => z.index === piece.index)) this.zones.push(this.zone(piece, status));
    }
    for (const a of this.actors) a.crowd = this.actors.filter((o) => o !== a);
    this.preroll = this.actors.length ? WALK_S : 0;
    this.tail = Math.max(0, ...this.actors.map((a) => a.tail));

    // a tag floats above each piece, carried by its body, or above a ghost where it stands
    const anchor = (parent, pos) => {
      const o = new THREE.Object3D();
      o.position.set(...pos);
      parent.add(o);
      return o;
    };
    const spots = [
      ...(trace.pieces || []).map((p) => ({ index: p.index, at: anchor(this.bodies[p.body - 1], [0, 0, p.height + 0.14]) })),
      ...(trace.ghosts || []).map((g) => ({ index: g.index, at: this.own(anchor(this.room, [g.pos[0], g.pos[1], g.height + 0.14])) })),
    ];
    this.tags = spots.filter((s) => labels[s.index]).map((s) => {
      const el = document.createElement("button");
      el.type = "button";
      el.className = `tag3d ${labels[s.index].status}`;
      el.textContent = labels[s.index].n;
      el.onclick = () => this.onTag?.(s.index);
      this.tagLayer?.append(el);
      return { ...s, el };
    });
    this.show(0);
    this.focus(focus, { frame: reframe || !this.framed, instant: !this.framed });
    this.framed = true;
    this.play();
  }

  // A soft tinted area on the floor from the piece's front out to about its height
  zone(piece, status) {
    const [token, fallback] = STATUS_COLORS[status];
    const color = getComputedStyle(document.documentElement).getPropertyValue(token).trim() || fallback;
    const reach = Math.max(0.5, piece.height * 1.02), pad = 0.12;
    const w = piece.width + 2 * pad, d = reach + pad;
    const canvas = document.createElement("canvas");
    canvas.width = 256;
    canvas.height = Math.round(256 * Math.min(4, d / w));
    const c = canvas.getContext("2d"), px = canvas.width / w, blur = pad * px * 0.7;
    // canvas top is the far end (it maps to +y); the piece's edge is at the bottom
    const rgb = new THREE.Color(color).convertLinearToSRGB().toArray().map((x) => Math.round(x * 255)).join(",");
    const grad = c.createLinearGradient(0, 0, 0, canvas.height);
    grad.addColorStop(0, `rgba(${rgb},0.45)`);
    grad.addColorStop(1, `rgba(${rgb},1)`);
    c.filter = `blur(${blur.toFixed(1)}px)`;
    c.fillStyle = grad;
    c.beginPath();
    c.roundRect(pad * px, pad * px * 0.6, canvas.width - 2 * pad * px, canvas.height - pad * px * 0.6, 0.08 * px);
    c.fill();
    const tex = new THREE.CanvasTexture(canvas);
    tex.colorSpace = THREE.SRGBColorSpace;
    const mat = new THREE.MeshBasicMaterial({ map: tex, transparent: true, depthWrite: false, opacity: 0, polygonOffset: true, polygonOffsetFactor: -2 });
    const mesh = this.own(new THREE.Mesh(new THREE.PlaneGeometry(w, d), mat));
    const front = piece.y + piece.depth / 2;
    mesh.position.set(piece.x, front + d / 2 - pad * 0.4, 0.003);
    mesh.renderOrder = 1;
    return { index: piece.index, mesh, strength: status === "tips" ? 0.32 : 0.22 };
  }

  // Fade every piece but `index` (none when it's null), and fly to it
  focus(index, { frame = true, instant = false } = {}) {
    this.focused = index;
    this.scene.updateMatrixWorld(true); // the bodies were just posed; measure them where they stand
    const pts = []; // what must be in view (world)
    const corners = (b) => {
      for (let c = 0; c < 8; c++) pts.push(new THREE.Vector3(c & 1 ? b.max.x : b.min.x, c & 2 ? b.max.y : b.min.y, c & 4 ? b.max.z : b.min.z));
    };
    const meshes = [];
    this.room.traverse((o) => o.isMesh && this.pieceOf.has(o) && meshes.push(o));
    const part = new THREE.Box3(), inRoom = new THREE.Box3(), toRoom = this.room.matrixWorld.clone().invert();
    for (const m of meshes) {
      const mine = index == null || this.pieceOf.get(m) === index;
      // the pieces' own boards where they are now (not a stray body, nor what was on them)
      if (mine && m.userData.frame && m.parent.visible) {
        part.setFromObject(m);
        const ok = [part.min.x, part.min.y, part.min.z, part.max.x, part.max.y, part.max.z].every(Number.isFinite);
        if (ok && this.bounds.intersectsBox(inRoom.copy(part).applyMatrix4(toRoom))) corners(part);
      }
      const base = m.material.userData.opacity;
      m.material.transparent = base < 1 || !mine;
      m.material.opacity = mine ? base : Math.min(base, 0.18);
      m.material.depthWrite = base === 1 && mine;
    }
    this.tags.forEach((t) => t.el.classList.toggle("dim", index != null && t.index !== index));
    if (!pts.length) corners(new THREE.Box3().setFromCenterAndSize(this.room.localToWorld(new THREE.Vector3()), new THREE.Vector3(1, 1, 1)));
    const room = (x, y, z) => this.room.localToWorld(new THREE.Vector3(x, y, z));
    // the floor in front of a piece still standing, out to most of its height: where it would land (any
    // piece may come down in an earthquake)
    for (const p of this.trace.pieces || []) {
      if (index != null && p.index !== index) continue;
      if (tiltDeg(this.trace, p.body, Math.floor(this.ft ?? 0)) > 20) continue;
      const out = p.y + p.depth / 2 + (this.quake ? 0.9 : 0.6) * p.height;
      pts.push(room(p.x - p.width / 2, out, 0), room(p.x + p.width / 2, out, 0));
    }
    // where the people stand, how high they climb and where they end up
    for (const a of this.actors) {
      if (index != null && a.index !== index) continue;
      for (const p of a.framePoints()) pts.push(this.room.localToWorld(p.clone()));
    }
    // the tinted floor where a piece would land
    for (const z of this.zones) {
      if (index != null && z.index !== index) continue;
      const { width, height } = z.mesh.geometry.parameters;
      for (const sx of [-0.5, 0.5]) pts.push(z.mesh.localToWorld(new THREE.Vector3(sx * width, 0.5 * height, 0)));
    }
    // the tags over the pieces shown
    const tags = this.tags.filter((t) => index == null || t.index === index).map((t) => t.at.getWorldPosition(new THREE.Vector3()))
      .filter((v) => Number.isFinite(v.x + v.y + v.z));
    this.updateZones();
    if (frame) this.frame(pts, instant, tags);
  }

  // Front three-quarter view of the pieces, the floor in front where they would land, the people and
  // the tags over the pieces (`pts`, `tags`: world points), fitted to the canvas: clear of the caption at
  // the top (the tags well below it), the fix pills at the bottom and the sides
  frame(pts, instant, tags = []) {
    const all = new THREE.Box3().setFromPoints(pts);
    const size = all.getSize(new THREE.Vector3());
    const w = this.host.clientWidth || 800, h = this.host.clientHeight || 500;
    const px = (n) => (2 * n) / h;
    const top = px(Math.min(52, 0.14 * h)), tagTop = px(Math.min(100, 0.26 * h)), bottom = px(Math.min(54, 0.14 * h));
    const side = (2 * Math.min(24, 0.04 * w)) / w;
    const dir = zUp(size.x > 1.6 * size.y ? [0.32, 0.92, 0.26] : [0.551, 0.787, 0.276]).normalize();
    const cam = this.camera.clone();
    cam.aspect = w / h;
    cam.updateProjectionMatrix();
    const v = new THREE.Vector3();
    // the points' extent on screen (NDC), the tags counted by their tops
    const extent = (target, d) => {
      cam.position.copy(target).addScaledVector(dir, d);
      cam.lookAt(target);
      cam.updateMatrixWorld();
      const e = { x0: Infinity, x1: -Infinity, y0: Infinity, y1: -Infinity };
      const add = (p, lift) => {
        v.copy(p).project(cam);
        e.x0 = Math.min(e.x0, v.x); e.x1 = Math.max(e.x1, v.x);
        e.y0 = Math.min(e.y0, v.y); e.y1 = Math.max(e.y1, v.y + lift);
      };
      pts.forEach((p) => add(p, 0));
      tags.forEach((p) => add(p, tagTop - top)); // a tag needs more room above it than the rest
      return e;
    };
    const roomX = 2 - 2 * side, roomY = 2 - top - bottom;
    const fits = (target, d) => {
      const e = extent(target, d);
      return e.x1 - e.x0 <= roomX && e.y1 - e.y0 <= roomY;
    };
    const target = all.getCenter(new THREE.Vector3());
    target.y = Math.max(0, 0.4 * size.y + all.min.y);
    const tanY = Math.tan(THREE.MathUtils.degToRad(cam.fov) / 2);
    // the nearest distance at which it all fits, then centre it in the room left for it, and again
    const fit = () => {
      let lo = 1.2, hi = 60;
      if (fits(target, lo)) return 2;
      for (let j = 0; j < 24 && hi - lo > 0.01; j++) {
        const m = (lo + hi) / 2;
        if (fits(target, m)) hi = m;
        else lo = m;
      }
      return Math.max(2, hi);
    };
    let dist = fit();
    for (let round = 0; round < 5; round++) {
      const e = extent(target, dist);
      const dx = (e.x0 + e.x1) / 2, dy = (e.y0 + e.y1) / 2 - (bottom - top) / 2;
      if (Math.abs(dx) < 0.02 && Math.abs(dy) < 0.02) break;
      const right = new THREE.Vector3().setFromMatrixColumn(cam.matrixWorld, 0), up = new THREE.Vector3().setFromMatrixColumn(cam.matrixWorld, 1);
      const depth = cam.position.distanceTo(all.getCenter(v));
      target.addScaledVector(right, dx * depth * tanY * cam.aspect).addScaledVector(up, dy * depth * tanY);
      dist = fit();
    }
    const to = target.clone().addScaledVector(dir, dist);
    if (instant) {
      this.camera.position.copy(to);
      this.controls.target.copy(target);
      this.flight = null;
    } else {
      this.flight = { t0: performance.now(), from: this.camera.position.clone(), fromTarget: this.controls.target.clone(), to, target };
    }
    this.controls.update();
  }

  // Pose every body at a fractional frame
  show(ft) {
    const t = this.trace;
    ft = Math.min(Math.max(0, ft), t.frames.length - 1);
    this.bodies.forEach((b, i) => {
      this.pose(i + 1, ft, b.position, b.quaternion);
      b.visible = Number.isFinite(b.position.x + b.position.y + b.position.z) && this.bounds.containsPoint(b.position);
    });
    const f = Math.floor(ft), g = Math.min(t.frames.length - 1, f + 1), u = ft - f;
    const [ux, uy] = t.shift[f], [vx, vy] = t.shift[g];
    this.room.position.copy(zUp([ux + (vx - ux) * u, uy + (vy - uy) * u, 0]));
    this.straps.forEach((m, j) => {
      const s = t.straps[f].slice(6 * j, 6 * j + 6), e = t.straps[g].slice(6 * j, 6 * j + 6);
      const a = new THREE.Vector3(...s.slice(0, 3)).lerp(new THREE.Vector3(...e.slice(0, 3)), u);
      const b = new THREE.Vector3(...s.slice(3)).lerp(new THREE.Vector3(...e.slice(3)), u);
      m.position.copy(a).add(b).multiplyScalar(0.5);
      m.scale.set(1, a.distanceTo(b), 1);
      m.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), b.clone().sub(a).normalize());
    });
    this.ft = ft;
  }

  // kept for callers that step frames themselves
  setFrame(f) {
    this.show(f);
    this.people(f);
    this.frame_ = f;
    this.onFrame?.(f / this.trace.fps, f / (this.trace.frames.length - 1));
  }

  people(ft, walk = null) {
    for (const a of this.actors) a.update(walk != null ? { walk } : { ft });
    this.updateZones(ft);
  }

  updateZones(ft = this.ft ?? 0) {
    const shown = this.quake ? 0 : smooth((ft - this.start) / (0.8 * this.trace.fps));
    for (const z of this.zones) {
      const mine = this.focused == null || this.focused === z.index;
      z.mesh.material.opacity = z.strength * shown * (mine ? 1 : 0.3);
      z.mesh.visible = shown > 0;
    }
  }

  play() {
    this.started = performance.now();
    this.playing = true;
    this.told = new Set(); // pieces whose fall was reported
    this.frame_ = -1;
  }

  // Jump to `seconds` after play() (walk-in included); `play` false holds the picture there
  seek(seconds, play = true) {
    this.started = performance.now() - seconds * 1000;
    this.told = new Set(this.falls.filter((f) => f.fell != null && this.fallTime(f) < seconds - this.preroll).map((f) => f.index));
    this.playing = true;
    this.advance(seconds);
    this.playing = play;
  }

  fallTime(f) {
    return (f.fell - (this.quake ? 0 : this.start)) / this.trace.fps;
  }

  get duration() {
    return this.preroll + (this.trace.frames.length - 1) / this.trace.fps;
  }

  advance(clock) {
    const t = this.trace, n = t.frames.length, fps = t.fps;
    const walk = clock < this.preroll ? clock : null;
    const ft = walk != null ? 0 : (clock - this.preroll) * fps;
    const done = ft >= n - 1 + this.tail * fps;
    if (walk == null || ft !== this.ft) this.show(ft);
    this.people(ft, walk);
    for (const f of this.falls) {
      if (f.fell == null || ft < f.fell || this.told.has(f.index)) continue;
      this.told.add(f.index);
      this.onTip?.(f.index, Math.round(this.fallTime(f) * 10) / 10);
    }
    const frame = walk != null ? -1 - Math.floor(walk * fps) : Math.min(n - 1, Math.floor(ft));
    if (frame !== this.frame_) {
      this.frame_ = frame;
      this.onFrame?.(Math.max(0, frame) / fps, Math.min(1, clock / this.duration));
    }
    if (done && this.playing) {
      this.playing = false;
      this.onEnd?.();
    }
  }

  draw() {
    if (this.trace && this.playing) this.advance((performance.now() - this.started) / 1000);
    if (this.flight) {
      const k = ease(Math.min(1, (performance.now() - this.flight.t0) / 900));
      this.camera.position.lerpVectors(this.flight.from, this.flight.to, k);
      this.controls.target.lerpVectors(this.flight.fromTarget, this.flight.target, k);
      if (k === 1) this.flight = null;
    }
    this.controls.update();
    this.renderer.render(this.scene, this.camera);
    if (this.tags.length) {
      const w = this.host.clientWidth, h = this.host.clientHeight, v = new THREE.Vector3();
      for (const t of this.tags) {
        t.at.getWorldPosition(v).project(this.camera);
        t.el.hidden = v.z > 1;
        t.el.style.transform = `translate(${((v.x + 1) / 2) * w}px, ${((1 - v.y) / 2) * h}px) translate(-50%, -100%)`;
      }
    }
  }
}

// The loose contents of an open shelf (a run of books, dishes, toys): upright spines of slightly varied
// height, thickness and shade of the run's own color, standing on the shelf across the run's width
function spines(g, color) {
  let seed = 2166136261;
  for (const ch of g.name) seed = Math.imul(seed ^ ch.charCodeAt(0), 16777619);
  const rand = () => ((seed = Math.imul(seed ^ (seed >>> 15), 2246822507) ^ Math.imul(seed ^ (seed >>> 13), 3266489909)) >>> 0) / 4294967296;
  const [sx, sy, sz] = g.size, hsl = color.getHSL({});
  const parts = [];
  for (let x = -sx; x < sx - 0.004;) {
    const t = Math.min(sx - x, 0.014 + rand() * 0.026 * Math.max(1, sz / 0.12));
    const h = 2 * sz * (0.74 + rand() * 0.26), d = 2 * sy * (0.82 + rand() * 0.18);
    const box = new THREE.BoxGeometry(Math.max(0.004, t - 0.0015), h, d).toNonIndexed();
    box.rotateX(Math.PI / 2); // three's box is y-up; the geom's frame is z-up
    box.translate(x + t / 2, sy - d / 2 - rand() * 0.006, -sz + h / 2);
    const c = new THREE.Color().setHSL(hsl.h + (rand() - 0.5) * 0.04, Math.min(1, hsl.s * (0.75 + rand() * 0.4)), Math.min(0.9, Math.max(0.12, hsl.l + (rand() - 0.55) * 0.24)));
    const cols = new Float32Array(box.attributes.position.count * 3);
    for (let i = 0; i < cols.length; i += 3) cols.set([c.r, c.g, c.b], i);
    box.setAttribute("color", new THREE.BufferAttribute(cols, 3));
    parts.push(box);
    x += t;
  }
  const merged = mergeGeometries(parts);
  parts.forEach((p) => p.dispose());
  return merged;
}
