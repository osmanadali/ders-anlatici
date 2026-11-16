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
    hips: pick("hips"), spine: pick("spine"), neck: pick("neck"), head: pick("head"),
    L: { upper: pick("upperarm", "L"), fore: pick("forearm", "L"), hand: pick("hand", "L"),
         thigh: pick("upleg", "L"), shin: pick("leg", "L"), foot: pick("foot", "L") },
    R: { upper: pick("upperarm", "R"), fore: pick("forearm", "R"), hand: pick("hand", "R"),
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
function twoBone(a, b, c, target, pole, k = 0.35) {
  const A = a.getWorldPosition(new THREE.Vector3());
  const la = a.userData.len || (a.userData.len = A.distanceTo(b.getWorldPosition(new THREE.Vector3())));
  const lb = b.userData.len || (b.userData.len = b.getWorldPosition(new THREE.Vector3()).distanceTo(c.getWorldPosition(new THREE.Vector3())));
  const toT = _w.copy(target).sub(A);
  const d = Math.min(Math.max(toT.length(), 0.05), (la + lb) * 0.999);
  const dir = toT.normalize();
  const pv = pole.clone().sub(dir.clone().multiplyScalar(pole.dot(dir)));
  if (pv.lengthSq() < 1e-6) pv.set(0, -1, 0); else pv.normalize();
  const cosA = THREE.MathUtils.clamp((la * la + d * d - lb * lb) / (2 * la * d), -1, 1);
  const elbow = A.clone().addScaledVector(dir, la * cosA).addScaledVector(pv, la * Math.sqrt(1 - cosA * cosA));
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

  const debug = { B, last: null };
  return {
    root, headObj, debug, info: { bones: count, morphs: morphs.mouth.length > 0 },
    pose(p, dt) {
      root.updateMatrixWorld(true);
      bob.position.y = p.bob;
      // gövde ve baş
      if (B.spine) turn(B.spine, root, new THREE.Euler(p.lean, 0, p.sway), 0.15);
      turn(B.head, root, new THREE.Euler(p.head.x, p.head.y, p.head.z), 0.15);
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
        return shoulderPos(side).add(rootDir(sx * (0.07 + g * 0.1), -0.555 + g * 0.3, 0.04 + g * 0.28 + swing * sx * -0.15));
      };
      if (p.reachR) {
        twoBone(B.R.upper, B.R.fore, B.R.hand, p.reachR, rootDir(0.3, -1, -0.5), 0.4);
        twoBone(B.L.upper, B.L.fore, B.L.hand, relaxTarget("L", 0, 0), rootDir(0, -0.3, -1), 0.15);
      } else if (p.think) {
        const chin = headObj.getWorldPosition(new THREE.Vector3()).add(rootDir(-0.02, -0.08, 0.12));
        twoBone(B.R.upper, B.R.fore, B.R.hand, chin, rootDir(0.2, -1, 0.2), 0.25);
        twoBone(B.L.upper, B.L.fore, B.L.hand, relaxTarget("L", 0, 0), rootDir(0, -0.3, -1), 0.15);
      } else {
        twoBone(B.R.upper, B.R.fore, B.R.hand, relaxTarget("R", p.talkR, p.swing), rootDir(0, -0.3, -1), 0.15);
        twoBone(B.L.upper, B.L.fore, B.L.hand, relaxTarget("L", p.talkL, p.swing), rootDir(0, -0.3, -1), 0.15);
      }

      // ağız ve göz kırpma (şekil anahtarı varsa); yoksa konuşurken başı hafifçe sallanır
      for (const [o, i] of morphs.mouth) o.morphTargetInfluences[i] = THREE.MathUtils.damp(o.morphTargetInfluences[i], p.mouth, 18, dt);
      for (const [o, i] of morphs.blink) o.morphTargetInfluences[i] = p.blink ? 1 : 0;
      if (!morphs.mouth.length && p.mouth > 0.05) turn(B.head, root, new THREE.Euler(p.head.x + p.mouth * 0.06, p.head.y, p.head.z), 0.3);
    },
  };
}
