/* İskeletli GLB hoca modeli (ör. Tripo, Mixamo) için sürücü.
   Kemik adları üreticiye göre değiştiğinden (LeftArm, upperarm_l, mixamorig:LeftForeArm, L_UpperArm…)
   adlar esnek biçimde eşleştirilir. Kollar ve bacaklar "hedefe yönelt" (iki kemikli IK) ile sürülür:
   kemiklerin yerel eksenleri ne olursa olsun, kemik kendi dinlenme yönünden hedefe doğru döndürülür. */
import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";

const HEIGHT = 1.8;

function norm(name) {
  return (name || "").toLowerCase().replace(/mixamorig|armature|def[-_]|bip0?0?1|[:_\-. ]/g, "");
}
function sideOf(raw) {
  const n = (raw || "").toLowerCase();
  if (/left/.test(n) || /(^|[_.\-\s:])l([_.\-\s:]|$)/.test(n) || /[_.]l$/.test(n) || /^l[_.]/.test(n)) return "L";
  if (/right/.test(n) || /(^|[_.\-\s:])r([_.\-\s:]|$)/.test(n) || /[_.]r$/.test(n) || /^r[_.]/.test(n)) return "R";
  return "";
}
const PARTS = {
  hips: (n) => /^(hips|pelvis|hip|root)$/.test(n),
  spine: (n) => /(spine|chest)/.test(n),
  neck: (n) => /neck/.test(n),
  head: (n) => /head$/.test(n) && !/top|end|nub/.test(n),
  upperarm: (n) => /(upperarm|arm)(l|r|left|right)?$/.test(n.replace(/^(left|right)/, "")) && !/fore|lower|hand|finger/.test(n),
  forearm: (n) => /(forearm|lowerarm|elbow)/.test(n),
  hand: (n) => /hand(l|r)?$/.test(n.replace(/^(left|right)/, "")) && !/thumb|index|middle|ring|pinky|finger/.test(n),
  clav: (n) => /(shoulder|clavicle|collar)/.test(n),
  jaw: (n) => /jaw/.test(n) && !/end/.test(n),
  upleg: (n) => /(upleg|thigh|upperleg)/.test(n),
  leg: (n) => /(leg|calf|shin|lowerleg|knee)(l|r)?$/.test(n.replace(/^(left|right)/, "")) && !/up|upper|thigh/.test(n),
  foot: (n) => /(foot|ankle)(l|r)?$/.test(n.replace(/^(left|right)/, "")),
};

function findBones(model) {
  const bones = [];
  model.traverse((o) => { if (o.isBone || o.type === "Bone") bones.push(o); });
  const pick = (part, side) => {
    const c = bones.filter((b) => PARTS[part](norm(b.name).replace(/(left|right)/, "")) && (!side || sideOf(b.name) === side));
    if (part === "spine") {  // en üstteki omurga (göğüs) kemiği: boyna en yakın olan
      return c.sort((a, b) => b.getWorldPosition(new THREE.Vector3()).y - a.getWorldPosition(new THREE.Vector3()).y)[0];
    }
    return c[0];
  };
  const B = {
    hips: pick("hips"), spine: pick("spine"), neck: pick("neck"), head: pick("head"), jaw: pick("jaw"),
    L: { clav: pick("clav", "L"), upper: pick("upperarm", "L"), fore: pick("forearm", "L"), hand: pick("hand", "L"),
         thigh: pick("upleg", "L"), shin: pick("leg", "L"), foot: pick("foot", "L") },
    R: { clav: pick("clav", "R"), upper: pick("upperarm", "R"), fore: pick("forearm", "R"), hand: pick("hand", "R"),
         thigh: pick("upleg", "R"), shin: pick("leg", "R"), foot: pick("foot", "R") },
  };
  const missing = [];
  for (const k of ["head"]) if (!B[k]) missing.push(k);
  for (const s of ["L", "R"]) for (const k of ["upper", "fore", "hand"]) if (!B[s][k]) missing.push(s + "." + k);
  return { B, missing, count: bones.length };
}

// Sağ ele tebeşir: avuçta, parmak yönünde. Kemiğin ölçeği ne olursa olsun dünyada ~7 cm.
function addChalk(hand) {
  if (!hand) return;
  hand.updateMatrixWorld(true);
  const ws = hand.getWorldScale(new THREE.Vector3()).x || 1;
  const finger = hand.children.find((c) => c.isBone || c.type === "Bone");
  const dir = finger ? finger.position.clone() : new THREE.Vector3(0, 1, 0).multiplyScalar(0.08 / ws);
  const len = dir.length() || 0.08 / ws;
  dir.normalize();
  const chalk = new THREE.Mesh(new THREE.CylinderGeometry(0.0075 / ws, 0.0075 / ws, 0.07 / ws, 8),
                               new THREE.MeshStandardMaterial({ color: 0xf5f2e6, roughness: 0.9 }));
  chalk.position.copy(dir).multiplyScalar(len * 0.85);
  chalk.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), dir);
  chalk.rotateX(1.1);  // parmaklar arasında, tahtaya doğru eğik
  chalk.name = "tebesir";
  hand.add(chalk);
}

const _q = new THREE.Quaternion(), _q2 = new THREE.Quaternion(), _v = new THREE.Vector3(), _w = new THREE.Vector3();

// Kemiği dünya koordinatındaki bir noktaya yönelt (dinlenme yönünü koruyarak)
function aim(bone, child, worldPoint, k = 1) {
  const rest = bone.userData.rest;
  const restDir = bone.userData.restDir || (bone.userData.restDir = child.position.clone().normalize());
  const parentDir = restDir.clone().applyQuaternion(rest);
  bone.parent.updateWorldMatrix(true, false);
  const p = bone.parent.worldToLocal(_v.copy(worldPoint)).sub(bone.position);
  if (p.lengthSq() < 1e-8) return;
  _q.setFromUnitVectors(parentDir, p.normalize()).multiply(rest);
  bone.quaternion.slerp(_q, k);
  bone.updateMatrixWorld(true);
}

// İki kemikli IK: omuz→dirsek→el (ya da kalça→diz→ayak); pole: dirseğin/dizin gideceği yön (dünya)
function twoBone(a, b, c, target, pole, k = 0.35, keep = null) {
  const A = a.getWorldPosition(new THREE.Vector3());
  const la = a.userData.len || (a.userData.len = A.distanceTo(b.getWorldPosition(new THREE.Vector3())));
  const lb = b.userData.len || (b.userData.len = b.getWorldPosition(new THREE.Vector3()).distanceTo(c.getWorldPosition(new THREE.Vector3())));
  const toT = _w.copy(target).sub(A);
  const d = Math.min(Math.max(toT.length(), 0.05), (la + lb) * 0.999);
  const dir = toT.normalize();
  const pv = pole.clone().sub(dir.clone().multiplyScalar(pole.dot(dir)));
  if (pv.lengthSq() < 1e-6) pv.set(0, -1, 0); else pv.normalize();
  const cosA = THREE.MathUtils.clamp((la * la + d * d - lb * lb) / (2 * la * d), -1, 1);
  let elbow = A.clone().addScaledVector(dir, la * cosA).addScaledVector(pv, la * Math.sqrt(1 - cosA * cosA));
  if (keep) {  // dirsek ve ön kol gövdeye girmesin: dışarı it, kol uzunluğunu koru
    const H = A.clone().addScaledVector(dir, d);
    for (let i = 0; i < 6; i++) {
      elbow = keep(elbow);
      elbow = A.clone().add(elbow.sub(A).setLength(la));
      // ön kolun ortası (ve el tarafı) gövdedeyse dirseği o yönde dışarı taşı
      const orta = elbow.clone().lerp(H, 0.5), itilmis = keep(orta.clone());
      if (itilmis.distanceToSquared(orta) < 1e-6) break;
      elbow.add(itilmis.sub(orta).multiplyScalar(2));
    }
  }
  aim(a, b, elbow, k);
  aim(b, c, A.clone().addScaledVector(dir, d), k);
}

// Kemiği karakterin (kök) eksenlerinde verilen açılarla döndür
function turn(bone, root, euler, k = 0.2) {
  const rest = bone.userData.rest;
  root.updateWorldMatrix(true, false);
  bone.parent.updateWorldMatrix(true, false);
  const qRoot = root.getWorldQuaternion(new THREE.Quaternion());
  const qPar = bone.parent.getWorldQuaternion(new THREE.Quaternion());
  const delta = new THREE.Quaternion().setFromEuler(euler);
  // kök uzayındaki dönüşü ebeveyn uzayına taşı: inv(qPar)·qRoot·delta·inv(qRoot)·qPar
  _q2.copy(qPar).invert().multiply(qRoot).multiply(delta).multiply(qRoot.clone().invert()).multiply(qPar);
  bone.quaternion.slerp(_q2.multiply(rest), k);
}

export async function loadGlbRig(url, { flip = false } = {}) {
  const gltf = await new GLTFLoader().loadAsync(url);
  const model = gltf.scene;
  model.traverse((o) => { if (o.isMesh) { o.castShadow = true; o.frustumCulled = false; } });

  const root = new THREE.Group();
  const yawFix = new THREE.Group(); yawFix.rotation.y = flip ? Math.PI : 0;
  const bob = new THREE.Group();
  root.add(yawFix); yawFix.add(bob); bob.add(model);
  root.updateMatrixWorld(true);

  const { B, missing, count } = findBones(model);
  if (!count) throw new Error("Bu modelde iskelet (kemik) yok: Tripo'da 'Rig' adımını çalıştırıp tekrar indir.");
  if (missing.length) throw new Error("Modelin iskeletinde bulunamayan kemikler: " + missing.join(", "));
  // Boyutu ve yere basmayı kemiklerden ölç (iskeletli modellerde kutu ölçümü ölçeği yanlış verir)
  const wy = (o) => o.getWorldPosition(new THREE.Vector3()).y;
  const headY = wy(B.head);
  const feet = [B.L.foot, B.R.foot, B.L.shin, B.R.shin].filter(Boolean);
  const ankleY = feet.length ? Math.min(...feet.map(wy)) : new THREE.Box3().setFromObject(model).min.y;
  const span = Math.max(headY - ankleY, 1e-4);
  const s = (HEIGHT * 0.86) / span;  // baş kemiği ~boyun %90'ında, ayak bileği ~%4'ünde
  model.scale.multiplyScalar(s);
  root.updateMatrixWorld(true);
  addChalk(B.R.hand);
  const hp = B.hips ? B.hips.getWorldPosition(new THREE.Vector3()) : B.head.getWorldPosition(new THREE.Vector3());
  model.position.x -= hp.x; model.position.z -= hp.z;
  root.updateMatrixWorld(true);
  const ankle2 = feet.length ? Math.min(...feet.map(wy)) : 0;
  model.position.y += 0.08 - ankle2;
  root.updateMatrixWorld(true);
  model.traverse((o) => { if (o.isBone) o.userData.rest = o.quaternion.clone(); });

  // Ağız/göz için şekil anahtarları (varsa)
  const morphs = { mouth: [], blink: [] };
  model.traverse((o) => {
    const dict = o.morphTargetDictionary;
    if (!dict) return;
    for (const [name, i] of Object.entries(dict)) {
      const n = name.toLowerCase();
      if (/jawopen|mouthopen|viseme_?aa|^aa$|mouth_?open|open_?mouth/.test(n)) morphs.mouth.push([o, i]);
      if (/blink|eyesclosed|eye_?close/.test(n)) morphs.blink.push([o, i]);
    }
  });

  const headObj = B.head;
  const up = new THREE.Vector3(), fwd = new THREE.Vector3();

  function rootDir(x, y, z) { return new THREE.Vector3(x, y, z).applyQuaternion(root.getWorldQuaternion(new THREE.Quaternion())); }
  function shoulderPos(side) { return B[side].upper.getWorldPosition(new THREE.Vector3()); }
  // Gövde kapsülü (dünya): kalça → göğüs ekseni; yarıçaplar omuz ve kalça eklem aralığından
  function govdeKapsulu() {
    const wp = (o) => o.getWorldPosition(new THREE.Vector3());
    const sL = wp(B.L.upper), sR = wp(B.R.upper);
    const gogus = sL.clone().add(sR).multiplyScalar(0.5).addScaledVector(rootDir(0, 1, 0), -0.06);
    const kalca = B.hips ? wp(B.hips) : gogus.clone().addScaledVector(rootDir(0, 1, 0), -0.45);
    const omuz = sL.distanceTo(sR);
    const kalcaG = (B.L.thigh && B.R.thigh) ? wp(B.L.thigh).distanceTo(wp(B.R.thigh)) : omuz * 0.6;
    return { alt: kalca.addScaledVector(rootDir(0, 1, 0), -0.12), ust: gogus,
             rGogus: omuz * 0.42, rKalca: Math.max(kalcaG * 0.5 + 0.1, omuz * 0.45) };
  }

  // ---- Canlı hareket (Mixamo kaydı olmadan, prosedürel): jest sırası, nefes, baş onayı, ağırlık aktarımı.
  // Çıktıların hepsi yumuşatılır (damp); fizik sınırı kol IK'sinde uygulanır.
  let DT = 1 / 60;
  const dmp = (a, b, lam) => THREE.MathUtils.damp(a, b, lam, DT);
  const C = { env: 0, loud: 0, nod: 0, nodT: 9, nextNod: 2, jest: "dinlen", jestUntil: 0, jestSeed: 0, isaret: 0, silent: 0,
              el: { L: new THREE.Vector3(0.11, -0.53, 0.07), R: new THREE.Vector3(-0.11, -0.53, 0.07) },
              govdeZ: 0, egil: 0, omuz: { L: 0, R: 0 }, basX: 0, basY: 0, basZ: 0, agirlik: 0, nefes: 0, hold: 0 };
  function canli(p, dt, konusuyor) {
    dt = Math.min(Math.max(dt || 0.016, 1e-3), 0.1); DT = dt;
    const t = p.t || 0, lam = (k) => 1 - Math.exp(-k * dt);
    // konuşma seviyesinin zarfı (hızlı yükselir, yavaş düşer)
    const lv = p.mouth || 0;
    C.env += (lv - C.env) * lam(lv > C.env ? 18 : 3.5);
    // cümle sonu: yeterince uzun konuşmadan sonra sessizlik → başla hafif onay/eğilme
    if (C.env > 0.22) { C.loud += dt; C.silent = 0; } else { C.silent += dt; }
    if (C.loud > 0.8 && C.silent > 0.18) { C.nodT = 0; C.nod = 0.9; C.loud = 0; }
    // arada (konuşurken ya da dinlerken) küçük onay başı sallama
    C.nextNod -= dt;
    if (C.nextNod <= 0) {
      C.nextNod = 3 + Math.random() * 4;
      if (konusuyor || p.state === "listening") { C.nodT = 0; C.nod = konusuyor ? 0.5 : 0.8; }
    }
    C.nodT += dt;
    const nod = Math.exp(-3.2 * C.nodT) * Math.sin(C.nodT * 9) * C.nod;
    // jest seçimi
    if (konusuyor && t > C.jestUntil && !debug.zorla) {
      const liste = ["acik", "say", "sag", "sol", "acik", "dinlen"];
      if (p.pointAt) liste.push("isaret", "isaret");
      C.jest = liste[Math.floor(Math.random() * liste.length)];
      C.jestSeed = Math.random() * 6;
      C.jestUntil = t + 1.8 + Math.random() * 2.6;
    }
    if (p.pointNow && p.pointAt) { C.jest = "isaret"; C.jestUntil = t + 2.4; }  // vurgu: yazılan öğeyi göster
    if (!konusuyor && !debug.zorla) C.jest = "dinlen";
    const a = 0.55 + C.env * 0.9;                 // konuşma yüksekse jestler büyür
    const nb = Math.sin(t * 5.2 + C.jestSeed) * 0.02 * a;
    const sol = { x: 0.11, y: -0.53, z: 0.07 }, sag = { x: -0.11, y: -0.53, z: 0.07 };
    let L = sol, R = sag, isr = 0;
    switch (C.jest) {
      case "acik":   // iki elle avuç yukarı açıklama
        L = { x: 0.2 + 0.03 * a, y: -0.13 + nb, z: 0.3 }; R = { x: -0.2 - 0.03 * a, y: -0.13 - nb, z: 0.3 }; break;
      case "say": {  // sayma: sağ elde vurgu vuruşları, sol el açık
        const adim = Math.floor(t * 1.6 + C.jestSeed) % 3;
        R = { x: -0.12, y: -0.1 + adim * 0.06 + Math.abs(Math.sin(t * 3.2)) * 0.03, z: 0.32 }; L = { x: 0.16, y: -0.3, z: 0.2 }; break;
      }
      case "sag": R = { x: -0.26, y: -0.1 + nb, z: 0.3 }; L = { x: 0.1, y: -0.52, z: 0.08 }; break;
      case "sol": L = { x: 0.26, y: -0.1 + nb, z: 0.3 }; R = { x: -0.1, y: -0.52, z: 0.08 }; break;
      case "isaret": isr = 1; R = { x: -0.2, y: -0.15, z: 0.3 }; break;
      default: L = { x: sol.x, y: sol.y + (konusuyor ? nb * 0.5 : 0), z: sol.z }; R = { x: sag.x, y: sag.y - (konusuyor ? nb * 0.5 : 0), z: sag.z };
    }
    for (const [k, h] of [["L", L], ["R", R]]) {
      C.el[k].x = dmp(C.el[k].x, h.x, 5); C.el[k].y = dmp(C.el[k].y, h.y, 5); C.el[k].z = dmp(C.el[k].z, h.z, 5);
    }
    C.isaret = dmp(C.isaret, isr, 6);
    const ritim = konusuyor ? C.env : 0;
    const dinliyor = p.state === "listening", dusunuyor = !!p.think;
    // baş: konuşma ritmine bağlı hafif vurgu + onay; dinlerken yana eğim (teacher3d'den) + yavaş sallanma
    const bx = ritim * 0.045 * Math.sin(t * 7.3) + nod * 0.09 + (konusuyor ? Math.sin(t * 1.7) * 0.015 : 0);
    const by = konusuyor ? Math.sin(t * 0.8 + 1) * 0.05 : (dinliyor ? Math.sin(t * 0.5) * 0.03 : 0);
    const bz = konusuyor ? Math.sin(t * 1.3) * 0.03 * (0.4 + C.env) : (dinliyor ? Math.sin(t * 0.6) * 0.02 : 0);
    C.basX = dmp(C.basX, bx, 12); C.basY = dmp(C.basY, by, 4); C.basZ = dmp(C.basZ, bz, 4);
    C.egil = dmp(C.egil, nod * 0.025 + (konusuyor ? C.env * 0.012 : 0), 8);
    C.govdeZ = dmp(C.govdeZ, konusuyor ? Math.sin(t * 1.1) * 0.012 * (0.5 + C.env) : 0, 3);
    const omz = konusuyor ? C.env * 0.03 : 0;  // vurguda omuzlar hafif kalkar
    C.omuz.L = dmp(C.omuz.L, omz + (C.jest === "sol" ? 0.03 : 0), 5); C.omuz.R = dmp(C.omuz.R, omz + (C.jest === "sag" || C.jest === "say" ? 0.03 : 0), 5);
    // ağırlık aktarımı: yavaş, ara sıra yön değiştirir (yürürken yok); düşünürken belirgin
    const ag = p.walking ? 0 : Math.sin(t * (dusunuyor ? 0.55 : 0.33)) * (dusunuyor ? 1 : 0.7);
    C.agirlik = dmp(C.agirlik, ag, 1.5);
    C.nefes = Math.sin(t * 1.45);
    const rest = (k, r) => Math.abs(C.el[k].x - r.x) + Math.abs(C.el[k].y - r.y) + Math.abs(C.el[k].z - r.z);
    const jestVar = rest("L", sol) > 0.035 || rest("R", sag) > 0.035 || C.isaret > 0.02;
    return { ...C, nefes: C.nefes, agirlik: C.agirlik, omuz: C.omuz, jestVar };
  }

  const debug = { B, last: null };
  return {
    root, headObj, debug, info: { bones: count, morphs: morphs.mouth.length > 0 },
    pose(p, dt) {
      root.updateMatrixWorld(true);
      const t = p.t || 0;
      const konusuyor = (p.talkR || 0) > 0 && !p.walking;
      if (debug.zorla) { C.jest = debug.zorla; C.jestUntil = Infinity; }
      const G = canli(p, dt, konusuyor || !!debug.zorla);
      bob.position.y = p.bob + G.nefes * 0.003;
      bob.position.x = G.agirlik * 0.012;  // ağırlık aktarımı: gövde hafifçe yana kayar
      // kalça (ağırlık aktarımı), gövde (nefes + konuşma ritmi), omuzlar, baş
      if (B.hips) turn(B.hips, root, new THREE.Euler(0, 0, G.agirlik * 0.035), 0.1);
      if (B.spine) turn(B.spine, root, new THREE.Euler(p.lean + G.nefes * 0.008 + G.egil, 0, p.sway - G.agirlik * 0.03 + G.govdeZ), 0.15);
      for (const [side, sg] of [["L", 1], ["R", -1]]) {  // omuz kemikleri: nefes ve vurguda hafif kalkar
        const c = B[side].clav;
        if (c) turn(c, root, new THREE.Euler(0, 0, sg * (G.nefes * 0.012 + G.omuz[side])), 0.2);
      }
      turn(B.head, root, new THREE.Euler(p.head.x + G.basX, p.head.y + G.basY, p.head.z + G.basZ), 0.18);
      if (B.neck) turn(B.neck, root, new THREE.Euler(G.basX * 0.5, G.basY * 0.4, G.basZ * 0.3), 0.18);
      if (B.jaw) turn(B.jaw, root, new THREE.Euler(Math.min(0.32, p.mouth * 0.34), 0, 0), 0.5);  // çene kemiği konuşma seviyesiyle açılır
      root.updateMatrixWorld(true);

      // bacaklar (adım): ayak hedefi kalçanın altında, adım açısıyla öne/arkaya
      for (const [side, sgn] of [["L", 1], ["R", -1]]) {
        const L = B[side];
        if (!L.thigh || !L.shin || !L.foot) continue;
        const hip = L.thigh.getWorldPosition(new THREE.Vector3());
        const legLen = (L.thigh.userData.len || hip.distanceTo(L.shin.getWorldPosition(new THREE.Vector3()))) +
                       (L.shin.userData.len || L.shin.getWorldPosition(new THREE.Vector3()).distanceTo(L.foot.getWorldPosition(new THREE.Vector3())));
        const a = p.walking ? Math.sin(p.walkPhase) * 0.45 * sgn : 0;
        const lift = p.walking ? Math.max(0, Math.sin(p.walkPhase + (sgn > 0 ? 0 : Math.PI) - 0.6)) * 0.08 : 0;
        const foot = hip.clone().add(rootDir(0, -legLen * 0.985 * Math.cos(a) + lift, legLen * Math.sin(a)));
        twoBone(L.thigh, L.shin, L.foot, foot, rootDir(0, 0, 1), 0.5);
      }

      // kollar
      const relaxTarget = (side, g, swing) => {
        const sx = side === "L" ? 1 : -1;  // modelin solu karakterin +X'i (kameraya bakarken ekranın sağı)
        return shoulderPos(side).add(rootDir(sx * (0.11 + g * 0.1), -0.53 + g * 0.3, 0.07 + g * 0.28 + swing * sx * -0.15));
      };
      // Basit fizik: gövde bir kapsül; el ve dirsek hedefi içine düşerse yüzeyine itilir (içinden geçmez)
      const govde = govdeKapsulu();
      const tahtaZ = (pt) => { if (pt.z < 0.045) pt.z = 0.045; return pt; };  // tahta düzleminin arkasına geçme
      const disari = (pt) => tahtaZ(disari0(pt));
      const disari0 = (pt) => {
        const ax = govde.alt, ust = govde.ust;
        const yon = ust.clone().sub(ax), uz = yon.length(); yon.normalize();
        const t = THREE.MathUtils.clamp(pt.clone().sub(ax).dot(yon), 0, uz);
        const merkez = ax.clone().addScaledVector(yon, t);
        const fark = pt.clone().sub(merkez);
        // yarıçap: kalça hizasında daha geniş (ceket/kalça), göğüste omuz genişliğine göre
        // Kesit elips: yanlara r, önden arkaya r*0.6 (göğüs yanlara göre ince)
        const r = THREE.MathUtils.lerp(govde.rKalca, govde.rGogus, t / uz) + 0.035;
        const ex = rootDir(1, 0, 0), ez = rootDir(0, 0, 1);
        const fx = fark.dot(ex), fz = fark.dot(ez), rz = r * 0.6;
        const e = Math.sqrt((fx / r) ** 2 + (fz / rz) ** 2);
        if (e >= 1) return pt;
        if (e < 1e-4) return merkez.addScaledVector(ez, rz);  // tam eksende: öne çıkar
        const k = 1 / e;  // elipsin yüzeyine aynı yönde ölçekle
        return pt.clone().addScaledVector(ex, fx * (k - 1)).addScaledVector(ez, fz * (k - 1));
      };
      // Kolun GERÇEK konumundaki ihlal: el, dirsek ve ön kol (3 nokta) gövdede mi, tahtanın arkasında mı (m)
      const ihlal = (L) => {
        const E = L.fore.getWorldPosition(new THREE.Vector3()), H = L.hand.getWorldPosition(new THREE.Vector3());
        let m = 0, z = 9;
        for (const f of [0, 0.33, 0.66, 1]) {
          const q = E.clone().lerp(H, f);
          m = Math.max(m, disari0(q.clone()).distanceTo(q), 0.045 - q.z);
          z = Math.min(z, q.z);
        }
        return { m, z };
      };
      const kol = (side, target, pole, k) => {
        const L = B[side];
        const hedef = disari(target);
        twoBone(L.upper, L.fore, L.hand, hedef, pole, k, disari);
        // Yumuşatma (slerp) eski pozdan yeni poza giderken kol gövdeden ya da tahtadan geçebilir: geçiyorsa bu karede
        // sınırlı çözüme doğrudan otur. Hâlâ geçiyorsa hedefi gövdeden biraz daha uzağa (öne) alıp yeniden çöz.
        let v = ihlal(L);
        for (let i = 0; i < 6 && v.m > 0.004; i++) {
          // kol göğsün önünden çapraz geçiyorsa: hedefi kolun kendi tarafına ve biraz öne kaydır
          if (i > 0) hedef.addScaledVector(rootDir(side === "L" ? 1 : -1, 0, 0), 0.05).addScaledVector(rootDir(0, 0, 1), 0.02);
          twoBone(L.upper, L.fore, L.hand, disari(hedef), pole, 1, disari);
          v = ihlal(L);
        }
        if (v.m > 0.01 && debug.kayit) debug.kayit.push({ side, m: +v.m.toFixed(3), z: +v.z.toFixed(3), reach: !!p.reachR, think: !!p.think });
        debug.pen = Math.max(debug.pen || 0, v.m); debug.minZ = Math.min(debug.minZ ?? 9, v.z);
        debug.last = { side, pen: v.m, handZ: v.z };
      };
      if (p.reachR) {
        kol("R", p.reachR, rootDir(0.3, -1, -0.5), 0.4);
        kol("L", relaxTarget("L", 0, 0), rootDir(0, -0.3, -1), 0.15);
      } else if (p.think) {
        // Çeneye el: el çenenin önünde, dirsek öne-aşağı ve hafif dışa (ön kol göğsün önünden geçer)
        const chin = headObj.getWorldPosition(new THREE.Vector3()).add(rootDir(-0.02, -0.13, 0.2));
        kol("R", chin, rootDir(-0.2, -1, 0.45), 0.25);
        kol("L", relaxTarget("L", 0, 0), rootDir(0, -0.3, -1), 0.15);
      } else if ((konusuyor || G.jestVar || debug.zorla) && !p.walking) {
        // Açıklama jestleri: eller kök uzayında yumuşakça (damping) hedefe gider, hedef her an fizik sınırından geçer
        for (const side of ["L", "R"]) {
          const o = G.el[side];
          const hedef = shoulderPos(side).add(rootDir(o.x, o.y, o.z));
          if (G.isaret && side === "R" && p.pointAt) {  // tahtadaki son öğeyi işaret et (kol uzanır, temas yok)
            const yon = p.pointAt.clone().sub(shoulderPos("R")); yon.y *= 0.6; yon.normalize();
            const om = shoulderPos("R");
            hedef.copy(om).addScaledVector(yon, 0.35 * G.isaret);
            hedef.z = Math.max(hedef.z, p.pointAt.z + 0.2, om.z - 0.08);   // kamera yönündeyken kol omzun arkasına bükülmesin
            hedef.lerp(shoulderPos(side).add(rootDir(o.x, o.y, o.z)), 1 - G.isaret);
          }
          kol(side, hedef, rootDir(side === "L" ? 0.25 : -0.25, -0.3, -1), 0.2);
        }
      } else {
        kol("R", relaxTarget("R", p.talkR, p.swing), rootDir(0, -0.3, -1), 0.15);
        kol("L", relaxTarget("L", p.talkL, p.swing), rootDir(0, -0.3, -1), 0.15);
      }

      // ağız ve göz kırpma (şekil anahtarı varsa); yoksa konuşurken başı hafifçe sallanır
      for (const [o, i] of morphs.mouth) o.morphTargetInfluences[i] = THREE.MathUtils.damp(o.morphTargetInfluences[i], p.mouth, 18, dt);
      for (const [o, i] of morphs.blink) o.morphTargetInfluences[i] = p.blink ? 1 : 0;
    },
  };
}
