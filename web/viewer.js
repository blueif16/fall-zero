// Plays a simulation recorded by the server (sim.Trace): the geometry once, then every body's pose per
// frame. MuJoCo is z-up; three.js is y-up, so the whole room sits in a group turned -90° about x.
// In an earthquake the room group follows the floor's displacement, so the camera sees it shake.

import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

const zUp = ([x, y, z]) => new THREE.Vector3(x, z, -y);

export class SimViewer {
  constructor(host) {
    this.host = host;
    this.renderer = new THREE.WebGLRenderer({ antialias: true });
    this.renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    host.prepend(this.renderer.domElement);

    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color("#f3f4f7");
    this.camera = new THREE.PerspectiveCamera(32, 16 / 9, 0.05, 60);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.maxPolarAngle = Math.PI / 2 - 0.05;

    this.scene.add(new THREE.HemisphereLight("#ffffff", "#c9c4bb", 1.6));
    const sun = new THREE.DirectionalLight("#ffffff", 2.2);
    sun.position.set(2.5, 5, 3.5);
    sun.castShadow = true;
    sun.shadow.mapSize.set(2048, 2048);
    Object.assign(sun.shadow.camera, { left: -4, right: 4, top: 4, bottom: -4 });
    this.scene.add(sun);

    this.room = new THREE.Group(); // shakes with the floor
    this.room.rotation.x = -Math.PI / 2;
    this.scene.add(this.room);
    const floor = new THREE.Mesh(new THREE.PlaneGeometry(14, 14), new THREE.MeshStandardMaterial({ color: "#e9e6e0", roughness: 0.95 }));
    floor.receiveShadow = true;
    this.room.add(floor);
    const grid = new THREE.GridHelper(14, 28, "#d6d2ca", "#dedad3");
    grid.rotation.x = Math.PI / 2;
    grid.position.z = 0.001;
    this.room.add(grid);

    this.onFrame = null;
    this.playing = false;
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

  load(trace) {
    this.bodies?.forEach((b) => this.room.remove(b));
    this.statics?.forEach((m) => this.room.remove(m));
    this.strap && this.room.remove(this.strap);
    this.trace = trace;
    this.bodies = Array.from({ length: trace.nbody }, () => new THREE.Group());
    this.bodies.forEach((b) => this.room.add(b));
    this.statics = [];
    this.loadGeoms = [];
    for (const g of trace.geoms) {
      const [r, gr, b, a] = g.rgba;
      const isLoad = (trace.load_geoms || []).includes(g.name);
      if (a === 0 && !isLoad) continue;
      let geo;
      if (g.type === "box") geo = new THREE.BoxGeometry(2 * g.size[0], 2 * g.size[1], 2 * g.size[2]);
      else geo = new THREE.CylinderGeometry(g.size[0], g.size[0], 2 * g.size[1], 12).rotateX(Math.PI / 2);
      const mat = new THREE.MeshStandardMaterial({ color: new THREE.Color(r, gr, b), roughness: 0.75 });
      const mesh = new THREE.Mesh(geo, mat);
      mesh.position.set(...g.pos);
      mesh.quaternion.set(g.quat[1], g.quat[2], g.quat[3], g.quat[0]);
      mesh.castShadow = mesh.receiveShadow = true;
      if (isLoad) {
        mat.color.set("#d92d20");
        this.loadGeoms.push(mesh);
      }
      if (g.body === 0) {
        this.room.add(mesh);
        this.statics.push(mesh);
      } else this.bodies[g.body - 1].add(mesh);
    }
    if (trace.straps) {
      this.strap = new THREE.Mesh(new THREE.CylinderGeometry(0.008, 0.008, 1, 8), new THREE.MeshStandardMaterial({ color: "#1d1d1f" }));
      this.room.add(this.strap);
    } else this.strap = null;
    this.setFrame(0);
    this.frameCamera();
    this.play();
  }

  frameCamera() {
    // front three-quarter view, aimed a little forward so the landing zone stays in frame
    const box = new THREE.Box3();
    this.bodies.forEach((b) => box.expandByObject(b));
    const size = box.getSize(new THREE.Vector3());
    const top = size.y;
    const front = box.min.z; // -y in MuJoCo is the back wall, so the front is the smallest z here
    const target = new THREE.Vector3(0, 0.45 * top, front - 0.35 * top);
    const dist = Math.max(2.6, 2.1 * top);
    const dir = zUp([0.551, 0.787, 0.276]).normalize();
    this.camera.position.copy(target).addScaledVector(dir, dist);
    this.controls.target.copy(target);
    this.controls.update();
  }

  setFrame(f) {
    const t = this.trace;
    const pose = t.frames[f];
    this.bodies.forEach((b, i) => {
      const k = i * 7;
      b.position.set(pose[k], pose[k + 1], pose[k + 2]);
      b.quaternion.set(pose[k + 4], pose[k + 5], pose[k + 6], pose[k + 3]);
    });
    const [ux, uy] = t.shift[f];
    this.room.position.copy(zUp([ux, uy, 0]));
    this.loadGeoms.forEach((m) => (m.visible = !!t.loads[f]));
    if (this.strap) {
      const s = t.straps[f];
      const a = new THREE.Vector3(s[0], s[1], s[2]), b = new THREE.Vector3(s[3], s[4], s[5]);
      this.strap.position.copy(a).add(b).multiplyScalar(0.5);
      this.strap.scale.set(1, a.distanceTo(b), 1);
      this.strap.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), b.clone().sub(a).normalize());
    }
    this.frame = f;
    this.onFrame?.(f / t.fps, f / (t.frames.length - 1));
  }

  play() {
    this.started = performance.now();
    this.playing = true;
  }

  draw() {
    if (this.trace && this.playing) {
      const f = Math.floor(((performance.now() - this.started) / 1000) * this.trace.fps);
      if (f >= this.trace.frames.length) {
        this.setFrame(this.trace.frames.length - 1);
        this.playing = false;
        this.onEnd?.();
      } else if (f !== this.frame) this.setFrame(f);
    }
    this.controls.update();
    this.renderer.render(this.scene, this.camera);
  }
}
