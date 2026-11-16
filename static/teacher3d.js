/* 3B sınıf ve hoca.
   - Tahta: mevcut el yazısı tahtası (HTML) CSS3DRenderer ile 3B sahnede duvara yerleştirilir; yazı animasyonları aynen çalışır.
   - Hoca: kod ile kurulmuş, eklemli (omuz, dirsek, kalça, diz) özgün bir karakter. Durumlar:
       talking   → sınıfa dönük, el-kol hareketleri, ağız sese göre
       writing   → tahtaya yürür, sırtı öğrenciye döner, eli kalemin yazdığı noktayı izler
       listening → öğrenciye döner, başı hafif yana eğik
       thinking  → eli çenesinde, yukarı bakar
       idle      → tahtanın yanında bekler
     Konuşurken ara sıra öğrenciye (kameraya) doğru yürür, sonra geri döner.
   - Kamera hocayı yumuşakça takip eder. */
import * as THREE from "three";
import { CSS3DRenderer, CSS3DObject } from "three/addons/renderers/CSS3DRenderer.js";

const BOARD_W = 3.2, BOARD_H = 1.92, BOARD_Y = 1.62;      // metre
const BOARD_PX_W = 760, BOARD_PX_H = 456;                  // tahtanın HTML boyutu
const HOME = new THREE.Vector3(1.8, 0, 1.0);               // tahtanın sağında bekleme yeri
const UPPER = 0.3, FORE = 0.28;                            // kol uzunlukları

const lerp = (a, b, t) => a + (b - a) * t;
const damp = (a, b, k, dt) => lerp(a, b, 1 - Math.exp(-k * dt));
function dampAngle(a, b, k, dt) {
  let d = ((b - a + Math.PI) % (2 * Math.PI)) - Math.PI;
  if (d < -Math.PI) d += 2 * Math.PI;
  return a + d * (1 - Math.exp(-k * dt));
}

// ------------------------------------------------------------------ karakter
function mat(color, rough = 0.75) { return new THREE.MeshStandardMaterial({ color, roughness: rough, metalness: 0 }); }

function buildTeacher() {
  const M = {
    skin: mat(0xefc6a3, 0.6), hair: mat(0x3b3029, 0.9), gray: mat(0x8d8a86, 0.9), jacket: mat(0x5f4e3f),
    lapel: mat(0x4c3e32), shirt: mat(0xf4f1ea), tie: mat(0xa23b3b), pants: mat(0x34383f), shoe: mat(0x1d1f23, 0.4),
    dark: mat(0x2a211b, 0.4), frame: mat(0x26231f, 0.3), mouth: mat(0x5b2a26, 0.8), chalk: mat(0xf5f2e6, 0.9),
  };
  const mesh = (geo, m, parent, [x, y, z] = [0, 0, 0]) => {
    const o = new THREE.Mesh(geo, m); o.position.set(x, y, z); o.castShadow = true; parent.add(o); return o;
  };
  const root = new THREE.Group();
  const body = new THREE.Group(); root.add(body);              // nefes/eğilme için

  // bacaklar (kalça → diz)
  const legs = [];
  for (const sx of [-1, 1]) {
    const hip = new THREE.Group(); hip.position.set(0.1 * sx, 0.92, 0); body.add(hip);
    mesh(new THREE.CapsuleGeometry(0.075, 0.34, 6, 12), M.pants, hip, [0, -0.22, 0]);
    const knee = new THREE.Group(); knee.position.set(0, -0.45, 0); hip.add(knee);
    mesh(new THREE.CapsuleGeometry(0.065, 0.34, 6, 12), M.pants, knee, [0, -0.21, 0]);
    const shoe = mesh(new THREE.BoxGeometry(0.12, 0.07, 0.27), M.shoe, knee, [0, -0.43, 0.05]);
    shoe.geometry.translate(0, 0, 0);
    legs.push({ hip, knee });
  }

  // gövde
  const torso = new THREE.Group(); torso.position.set(0, 0.95, 0); body.add(torso);
  const jacket = mesh(new THREE.CylinderGeometry(0.2, 0.18, 0.62, 20), M.jacket, torso, [0, 0.31, 0]);
  jacket.scale.set(1.12, 1, 0.72);
  mesh(new THREE.SphereGeometry(0.21, 20, 12, 0, Math.PI * 2, 0, Math.PI / 2), M.jacket, torso, [0, 0.6, 0]).scale.set(1.12, 0.45, 0.72);
  const shirt = mesh(new THREE.ConeGeometry(0.09, 0.3, 3), M.shirt, torso, [0, 0.47, 0.135]);
  shirt.rotation.set(Math.PI, 0, 0); shirt.scale.set(1, 1, 0.2);
  mesh(new THREE.BoxGeometry(0.045, 0.26, 0.01), M.tie, torso, [0, 0.45, 0.15]);
  for (const sx of [-1, 1]) {
    const l = mesh(new THREE.BoxGeometry(0.06, 0.32, 0.012), M.lapel, torso, [0.07 * sx, 0.45, 0.142]);
    l.rotation.z = -0.35 * sx;
  }
  for (const y of [0.24, 0.13]) mesh(new THREE.SphereGeometry(0.012, 8, 6), M.dark, torso, [0, y, 0.146]);

  // kollar (omuz → dirsek → el)
  const arms = {};
  for (const [name, sx] of [["L", -1], ["R", 1]]) {
    const shoulder = new THREE.Group(); shoulder.position.set(0.25 * sx, 0.56, 0); torso.add(shoulder);
    mesh(new THREE.CapsuleGeometry(0.06, UPPER - 0.06, 6, 12), M.jacket, shoulder, [0, -UPPER / 2, 0]);
    const elbow = new THREE.Group(); elbow.position.set(0, -UPPER, 0); shoulder.add(elbow);
    mesh(new THREE.CapsuleGeometry(0.052, FORE - 0.06, 6, 12), M.jacket, elbow, [0, -FORE / 2, 0]);
    const hand = mesh(new THREE.SphereGeometry(0.055, 14, 10), M.skin, elbow, [0, -FORE - 0.02, 0]);
    if (name === "R") { const c = mesh(new THREE.CylinderGeometry(0.009, 0.009, 0.07, 8), M.chalk, hand, [0.01, -0.045, 0.02]); c.rotation.x = 0.6; }
    arms[name] = { shoulder, elbow, hand };
  }

  // boyun ve baş
  mesh(new THREE.CylinderGeometry(0.055, 0.06, 0.1, 12), M.skin, torso, [0, 0.67, 0]);
  const head = new THREE.Group(); head.position.set(0, 0.74, 0); torso.add(head);
  const skull = mesh(new THREE.SphereGeometry(0.115, 28, 20), M.skin, head, [0, 0.11, 0]); skull.scale.set(0.92, 1.12, 1);
  mesh(new THREE.SphereGeometry(0.121, 28, 14, 0, Math.PI * 2, 0, Math.PI * 0.42), M.hair, head, [0, 0.13, -0.01]).scale.set(0.95, 1.05, 1.03);
  for (const sx of [-1, 1]) {
    mesh(new THREE.SphereGeometry(0.03, 10, 8), M.skin, head, [0.105 * sx, 0.1, 0]).scale.set(0.5, 1, 0.8);
    mesh(new THREE.SphereGeometry(0.035, 10, 8), M.gray, head, [0.1 * sx, 0.16, -0.02]).scale.set(0.4, 1, 1.2);
  }
  const eyes = [];
  for (const sx of [-1, 1]) {
    eyes.push(mesh(new THREE.SphereGeometry(0.013, 10, 8), M.dark, head, [0.04 * sx, 0.115, 0.1]));
    const rim = mesh(new THREE.TorusGeometry(0.028, 0.004, 6, 20), M.frame, head, [0.042 * sx, 0.115, 0.112]);
    rim.scale.set(1.15, 0.85, 1);
    mesh(new THREE.BoxGeometry(0.035, 0.007, 0.006), M.hair, head, [0.042 * sx, 0.155, 0.11]).rotation.z = 0.12 * sx;
  }
  mesh(new THREE.BoxGeometry(0.025, 0.004, 0.004), M.frame, head, [0, 0.12, 0.114]);
  const nose = mesh(new THREE.ConeGeometry(0.016, 0.045, 10), M.skin, head, [0, 0.085, 0.118]); nose.rotation.x = Math.PI / 2.2;
  mesh(new THREE.SphereGeometry(0.075, 18, 10, 0, Math.PI * 2, Math.PI * 0.55, Math.PI * 0.45), M.hair, head, [0, 0.07, 0.02]).scale.set(0.95, 0.9, 1.08);
  const mouth = mesh(new THREE.SphereGeometry(0.022, 14, 8), M.mouth, head, [0, 0.045, 0.108]); mouth.scale.set(1.2, 0.15, 0.4);

  return { root, body, torso, head, legs, arms, eyes, mouth };
}

// Kolu dünya koordinatındaki bir hedefe uzatır (iki kemikli analitik IK).
const _v = new THREE.Vector3(), _q = new THREE.Quaternion(), _down = new THREE.Vector3(0, -1, 0);
function reach(arm, worldTarget, bendSign = 1) {
  const sh = arm.shoulder;
  sh.parent.updateMatrixWorld(true);
  const local = sh.parent.worldToLocal(_v.copy(worldTarget)).sub(sh.position);
  let d = local.length();
  const dir = local.normalize();
  d = Math.min(Math.max(d, 0.08), UPPER + FORE - 0.005);
  const cosE = (UPPER * UPPER + FORE * FORE - d * d) / (2 * UPPER * FORE);
  const elbowBend = Math.PI - Math.acos(Math.min(1, Math.max(-1, cosE)));
  const cosS = (UPPER * UPPER + d * d - FORE * FORE) / (2 * UPPER * d);
  const shoulderOff = Math.acos(Math.min(1, Math.max(-1, cosS)));
  _q.setFromUnitVectors(_down, dir);
  sh.quaternion.slerp(_q.clone().multiply(new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(1, 0, 0), -shoulderOff * bendSign)), 0.35);
  arm.elbow.rotation.set(lerp(arm.elbow.rotation.x, elbowBend * bendSign, 0.35), 0, 0);
}
function relaxArm(arm, sx, t, gesture = 0) {
  const g = gesture * (0.5 + 0.5 * Math.sin(t * 2.1 + sx));
  const target = new THREE.Euler(-0.15 - g * 0.9, 0, (0.12 + g * 0.25) * -sx);
  arm.shoulder.quaternion.slerp(_q.setFromEuler(target), 0.12);
  arm.elbow.rotation.x = lerp(arm.elbow.rotation.x, -0.25 - g * 1.1, 0.12);
}

// Kodla çizilmiş hoca için ortak "pose" arayüzü (GLB modelle aynı)
function proceduralRig() {
  const T = buildTeacher();
  return {
    root: T.root, headObj: T.head,
    pose(p, dt) {
      const sw = p.walking ? Math.sin(p.walkPhase) * 0.5 : 0;
      T.legs[0].hip.rotation.x = sw; T.legs[1].hip.rotation.x = -sw;
      T.legs[0].knee.rotation.x = Math.max(0, -Math.sin(p.walkPhase - 0.6)) * (p.walking ? 0.8 : 0);
      T.legs[1].knee.rotation.x = Math.max(0, Math.sin(p.walkPhase - 0.6)) * (p.walking ? 0.8 : 0);
      T.body.position.y = p.bob;
      T.torso.rotation.z = damp(T.torso.rotation.z, p.sway, 6, dt);
      T.torso.rotation.x = damp(T.torso.rotation.x, p.lean, 4, dt);
      T.head.rotation.x = damp(T.head.rotation.x, p.head.x, 5, dt);
      T.head.rotation.y = damp(T.head.rotation.y, p.head.y, 5, dt);
      T.head.rotation.z = damp(T.head.rotation.z, p.head.z, 5, dt);
      if (p.reachR) {
        reach(T.arms.R, p.reachR, -1);
        relaxArm(T.arms.L, -1, p.t, 0);
      } else if (p.think) {
        T.head.updateMatrixWorld(true);
        reach(T.arms.R, T.head.localToWorld(new THREE.Vector3(0.0, 0.0, 0.12)), -1);
        relaxArm(T.arms.L, -1, p.t, 0);
      } else {
        relaxArm(T.arms.R, 1, p.t, p.talkR);
        relaxArm(T.arms.L, -1, p.t + 1.7, p.talkL);
        T.arms.R.shoulder.rotation.x += -p.swing * 0.5; T.arms.L.shoulder.rotation.x += p.swing * 0.5;
      }
      T.mouth.scale.y = damp(T.mouth.scale.y, 0.15 + p.mouth * 1.1, 18, dt);
      T.eyes.forEach((e) => (e.scale.y = p.blink ? 0.1 : 1));
    },
  };
}

// ------------------------------------------------------------------ sahne
export function mount({ root, board, teacher2d, onError }) {
  const boardEl = document.getElementById("board");
  root.classList.add("three");

  const css = new CSS3DRenderer();
  css.domElement.className = "layer-css";
  const gl = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  gl.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
  gl.shadowMap.enabled = true;
  gl.shadowMap.type = THREE.PCFSoftShadowMap;
  gl.outputColorSpace = THREE.SRGBColorSpace;
  gl.domElement.className = "layer-gl";
  root.appendChild(css.domElement);
  root.appendChild(gl.domElement);

  const scene = new THREE.Scene();
  const cssScene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(36, 1.6, 0.1, 50);
  camera.position.set(0.3, 1.55, 5.7);

  // duvar + tahta (HTML) — CSS3D
  const wall = document.createElement("div"); wall.className = "wall3d";
  const wallObj = new CSS3DObject(wall); wallObj.position.set(0, 2.2, -0.02); wallObj.scale.setScalar(0.01); cssScene.add(wallObj);
  boardEl.style.width = BOARD_PX_W + "px"; boardEl.style.height = BOARD_PX_H + "px";
  const boardObj = new CSS3DObject(boardEl);
  boardObj.position.set(0, BOARD_Y, 0);
  boardObj.scale.setScalar(BOARD_W / BOARD_PX_W);
  cssScene.add(boardObj);

  // ışıklar, zemin, tebeşir rafı, masa — WebGL
  scene.add(new THREE.HemisphereLight(0xfff6e8, 0x6b5440, 1.1));
  const sun = new THREE.DirectionalLight(0xffffff, 1.6);
  sun.position.set(2.5, 5, 4); sun.castShadow = true; sun.shadow.mapSize.set(1024, 1024);
  Object.assign(sun.shadow.camera, { left: -4, right: 4, top: 4, bottom: -1, near: 0.5, far: 15 });
  scene.add(sun);
  const floor = new THREE.Mesh(new THREE.PlaneGeometry(14, 9), new THREE.MeshStandardMaterial({ color: 0x9c7a55, roughness: 0.85 }));
  floor.rotation.x = -Math.PI / 2; floor.position.set(0, 0, 4.5); floor.receiveShadow = true; scene.add(floor);
  const tray = new THREE.Mesh(new THREE.BoxGeometry(BOARD_W + 0.1, 0.04, 0.08), new THREE.MeshStandardMaterial({ color: 0x5b4a36 }));
  tray.position.set(0, BOARD_Y - BOARD_H / 2 - 0.02, 0.04); tray.castShadow = true; scene.add(tray);
  const desk = new THREE.Group();
  const wood = new THREE.MeshStandardMaterial({ color: 0x6b4e33, roughness: 0.7 });
  const top = new THREE.Mesh(new THREE.BoxGeometry(1.2, 0.05, 0.6), wood); top.position.y = 0.75; desk.add(top);
  for (const [x, z] of [[-0.55, -0.25], [0.55, -0.25], [-0.55, 0.25], [0.55, 0.25]]) {
    const leg = new THREE.Mesh(new THREE.BoxGeometry(0.05, 0.75, 0.05), wood); leg.position.set(x, 0.375, z); desk.add(leg);
  }
  const books = new THREE.Mesh(new THREE.BoxGeometry(0.3, 0.08, 0.22), new THREE.MeshStandardMaterial({ color: 0x2f6f5e }));
  books.position.set(0.2, 0.82, 0); desk.add(books);
  desk.traverse((o) => { if (o.isMesh) { o.castShadow = true; o.receiveShadow = true; } });
  desk.position.set(-2.7, 0, 1.2); scene.add(desk);

  // Hoca: önce kodla çizilen; veri/ klasöründe GLB model varsa (Tripo vb.) yüklenince onunla değiştirilir
  let rig = proceduralRig();
  rig.root.position.copy(HOME);
  scene.add(rig.root);
  const T = { get root() { return rig.root; }, get head() { return rig.headObj; } };
  fetch("/api/teacher-model", { method: "HEAD" }).then(async (r) => {
    if (!r.ok) return;
    const { loadGlbRig } = await import("/static/teacher_glb.js");
    let flip = false;
    try { flip = localStorage.getItem("ders.hocaCevir") === "1"; } catch {}
    const g = await loadGlbRig("/api/teacher-model?v=" + (r.headers.get("etag") || Date.now()), { flip });
    g.root.position.copy(rig.root.position); g.root.rotation.copy(rig.root.rotation);
    scene.remove(rig.root); scene.add(g.root); rig = g;
    window.__hocaRig = g;  // tanılama için
  }).catch((e) => { console.warn("Hoca modeli yüklenemedi:", e); onError?.(e); });

  // ---------------- durum
  const S = { state: "idle", yaw: 0, walkPhase: 0, approach: null, approachUntil: 0, nextBlink: 2, blinkUntil: 0,
              lastState: "idle", stateSince: 0, head: { x: 0, y: 0, z: 0 } };
  const target = new THREE.Vector3().copy(HOME);
  const hand = new THREE.Vector3();

  function penWorld() {
    // Kalemin (ya da en son çizilen öğenin) tahtadaki yeri → dünya koordinatı
    const page = board.pages[board.view];
    if (!page) return null;
    let px, py;
    const pen = page._pen;
    if (pen && getComputedStyle(pen).opacity !== "0") {
      const cs = getComputedStyle(pen);
      px = parseFloat(cs.left); py = parseFloat(cs.top) - page.scrollTop;
    } else {
      const items = page.querySelectorAll(":scope > .b-item");
      const it = items[items.length - 1];
      if (!it) return null;
      const t = performance.now() / 1000;
      px = it.offsetLeft + it.offsetWidth * (0.5 + 0.45 * Math.sin(t * 1.3));
      py = it.offsetTop - page.scrollTop + it.offsetHeight * (0.5 + 0.35 * Math.sin(t * 2.3));
    }
    const bw = boardEl.clientWidth || BOARD_PX_W, bh = boardEl.clientHeight || BOARD_PX_H;
    px = Math.min(bw, Math.max(0, px + 10)); py = Math.min(bh, Math.max(0, py + 10));
    return new THREE.Vector3((px / bw - 0.5) * BOARD_W, BOARD_Y + (0.5 - py / bh) * BOARD_H, 0.02);
  }

  function setState(s) {
    if (s === S.state) return;
    S.lastState = S.state; S.state = s; S.stateSince = clock.elapsedTime;
    if (s === "talking" && Math.random() < 0.35) {
      // ara sıra öğrenciye doğru yaklaş
      S.approach = new THREE.Vector3(lerp(-0.6, 0.9, Math.random()), 0, 2.6);
      S.approachUntil = clock.elapsedTime + 4 + Math.random() * 3;
    }
    if (s !== "talking") S.approach = null;
  }

  // ---------------- döngü
  const clock = new THREE.Clock();
  const camPos = camera.position.clone(), camLook = new THREE.Vector3(0.2, 1.4, 0);
  let running = true;
  function frame() {
    if (!running) return;
    const dt = Math.min(0.05, clock.getDelta()), t = clock.elapsedTime;
    const st = S.state;
    const level = teacher2d.level || 0;

    // hedef konum
    let faceYaw = 0;  // 0 = öğrenciye dönük, π = tahtaya dönük
    const pen = st === "writing" ? penWorld() : null;
    if (pen) {
      target.set(THREE.MathUtils.clamp(pen.x + 0.26, -1.7, 1.9), 0, 0.36);  // kol (~0.58 m) tahtaya yetişsin
      faceYaw = Math.PI;
    } else if (st === "talking" && S.approach && t < S.approachUntil) {
      target.copy(S.approach);
    } else if (st === "talking" || st === "listening" || st === "thinking") {
      if (S.approach && t >= S.approachUntil) S.approach = null;
      target.copy(HOME);
    } else {
      target.copy(HOME);
    }
    const pos = T.root.position;
    const toTarget = new THREE.Vector3().subVectors(target, pos); toTarget.y = 0;
    const dist = toTarget.length();
    const walking = dist > 0.06;
    if (walking) {
      const speed = Math.min(1.25, dist * 2.2);
      pos.addScaledVector(toTarget.normalize(), speed * dt);
      S.walkPhase += dt * speed * 7.5;
      const walkYaw = Math.atan2(toTarget.x, toTarget.z);
      S.yaw = dampAngle(S.yaw, dist > 0.35 ? walkYaw : faceYaw, 6, dt);
    } else {
      S.walkPhase = damp(S.walkPhase, Math.round(S.walkPhase / Math.PI) * Math.PI, 8, dt);
      // konuşurken kameraya, dinlerken öğrenciye dön
      let yaw = faceYaw;
      if (!pen) yaw = Math.atan2(camera.position.x - pos.x, camera.position.z - pos.z) * 0.85;
      S.yaw = dampAngle(S.yaw, yaw, 5, dt);
    }
    T.root.rotation.y = S.yaw;

    // poz: ne yapılacağını hesapla, iskelete (kodla çizilen ya da GLB) uygula
    let headX = 0, headZ = 0, headY = 0;
    if (st === "listening") { headZ = 0.14; headX = 0.06; }
    if (st === "thinking") { headX = -0.18; headZ = -0.06; }
    if (st === "talking") { headX = Math.sin(t * 2.3) * 0.05; headY = Math.sin(t * 0.9) * 0.12; }
    if (pen) { headX = (pen.y - 1.55) * -0.35; headZ = 0.05; }
    S.head.x = damp(S.head.x, headX, 5, dt); S.head.y = damp(S.head.y, headY, 5, dt); S.head.z = damp(S.head.z, headZ, 5, dt);
    const talkingNow = st === "talking" || st === "writing";
    const talk = st === "talking" && !walking ? 0.35 + level * 0.6 : 0;
    if (t > S.nextBlink) { S.blinkUntil = t + 0.11; S.nextBlink = t + 2.5 + Math.random() * 3.5; }
    rig.pose({
      t, walking, walkPhase: S.walkPhase,
      bob: walking ? Math.abs(Math.cos(S.walkPhase)) * 0.025 : Math.sin(t * 1.6) * 0.004,
      sway: walking ? Math.sin(S.walkPhase) * 0.03 : 0,
      lean: st === "listening" ? 0.06 : 0,
      head: S.head,
      reachR: pen && dist < 0.45 ? hand.copy(pen).add(new THREE.Vector3(Math.sin(t * 19) * 0.012, Math.cos(t * 23) * 0.01, 0.04)) : null,
      think: st === "thinking",
      talkR: st === "listening" ? 0 : talk, talkL: st === "listening" ? 0 : talk * 0.6,
      swing: walking ? Math.sin(S.walkPhase) * 0.35 : 0,
      mouth: talkingNow ? level : 0,
      blink: t < S.blinkUntil,
    }, dt);

    // kamera: hocayı ve yazılan yeri yumuşakça takip et
    const head = T.head.getWorldPosition(new THREE.Vector3());
    let wantPos, wantLook;
    if (pen) {
      wantPos = new THREE.Vector3(pen.x * 0.45 + 0.4, 1.6, 5.3);
      wantLook = new THREE.Vector3(pen.x * 0.7, lerp(1.45, pen.y, 0.4), 0);
    } else if (S.approach && st === "talking") {
      wantPos = new THREE.Vector3(pos.x * 0.4 + 0.2, 1.62, 5.6);
      wantLook = new THREE.Vector3(pos.x * 0.6, lerp(1.4, head.y, 0.5), pos.z * 0.6);
    } else {
      wantPos = new THREE.Vector3(0.5, 1.55, 5.9);
      wantLook = new THREE.Vector3(0.4, 1.4, 0);
    }
    wantPos.x += Math.sin(t * 0.31) * 0.05; wantPos.y += Math.sin(t * 0.43) * 0.025;  // elde tutulmuş hafif salınım
    camPos.lerp(wantPos, 1 - Math.exp(-1.6 * dt));
    camLook.lerp(wantLook, 1 - Math.exp(-2.2 * dt));
    camera.position.copy(camPos);
    camera.lookAt(camLook);

    gl.render(scene, camera);
    css.render(cssScene, camera);
    requestAnimationFrame(frame);
  }

  function resize() {
    const w = root.clientWidth, h = root.clientHeight;
    if (!w || !h) return;
    camera.aspect = w / h;
    // dar ekranda (telefon) biraz geri çekil ki tahta sığsın
    camera.fov = w / h < 1.1 ? 52 : 36;
    camera.updateProjectionMatrix();
    gl.setSize(w, h); css.setSize(w, h);
  }
  new ResizeObserver(resize).observe(root);
  resize();
  requestAnimationFrame(frame);

  // 2B hocayla aynı arayüz: uygulamanın geri kalanı değişmeden çalışır
  return {
    setState(s) { setState(s); teacher2d.setState(s); },
    unlock() { teacher2d.unlock(); },
    attachAudio(a) { return teacher2d.attachAudio(a); },
    get fakeTalk() { return teacher2d.fakeTalk; },
    set fakeTalk(v) { teacher2d.fakeTalk = v; },
    get state() { return S.state; },
    destroy() {
      running = false;
      root.classList.remove("three");
      boardEl.style.width = boardEl.style.height = boardEl.style.transform = boardEl.style.position = "";
      root.insertBefore(boardEl, root.firstChild);
      css.domElement.remove(); gl.domElement.remove(); gl.dispose();
    },
  };
}
