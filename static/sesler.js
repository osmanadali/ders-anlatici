/* Sınıf sesleri: yalnızca hocayla ilgili, Web Audio ile kodla üretilir (dosya indirilmez).
   Tebeşir yazısı, silgi, tahtaya işaret, hocanın adımları ve pomodoro zili.
   Ayarlar: localStorage "ders.sinifSes" ("1"/"0", varsayılan açık) ve "ders.sinifSesVol" (0-1, varsayılan 0.35).
   Hoca konuşurken seslerin düzeyi 12 dB düşer (konuşmanın üstüne binmez). */
(function () {
  const lg = (k) => { try { return localStorage.getItem("ders." + k); } catch { return null; } };
  const DUCK = 0.25; // -12 dB
  let ctx = null, master = null, noiseBuf = null;
  let konusuyor = false, bastirma = false;
  let chalk = null; // çalışan tebeşir sesi

  function acik() { return lg("sinifSes") !== "0" && !bastirma; }
  function vol() { const v = parseFloat(lg("sinifSesVol")); return Number.isFinite(v) ? Math.min(1, Math.max(0, v)) : 0.35; }
  function hedefKazanc() { const v = vol(); return v * v * 0.9 * (konusuyor ? DUCK : 1); }

  function hazir() {
    if (!ctx) {
      const AC = window.AudioContext || window.webkitAudioContext;
      if (!AC) return false;
      try {
        ctx = new AC();
        master = ctx.createGain();
        master.gain.value = hedefKazanc();
        master.connect(ctx.destination);
        const n = Math.floor(ctx.sampleRate * 2);
        noiseBuf = ctx.createBuffer(1, n, ctx.sampleRate);
        const d = noiseBuf.getChannelData(0);
        for (let i = 0; i < n; i++) d[i] = Math.random() * 2 - 1;
      } catch { ctx = null; return false; }
    }
    if (ctx.state === "suspended") ctx.resume().catch(() => {});
    return true;
  }
  function guncelle() { if (master) master.gain.setTargetAtTime(hedefKazanc(), ctx.currentTime, 0.05); }
  function gurultu() {
    const s = ctx.createBufferSource();
    s.buffer = noiseBuf; s.loop = true;
    s.loopStart = Math.random(); // her seferinde farklı yerden başla
    return s;
  }

  // ---- tebeşirle yazma: kısa vuruşlar halinde hafif cızırtı
  function yaz(ms) {
    if (!acik() || !hazir()) return null;
    yazDur();
    const sn = Math.min(Math.max(ms, 150), 12000) / 1000, t0 = ctx.currentTime + 0.01;
    const src = gurultu(), hp = ctx.createBiquadFilter(), bp = ctx.createBiquadFilter(), g = ctx.createGain();
    hp.type = "highpass"; hp.frequency.value = 1500;
    bp.type = "bandpass"; bp.frequency.value = 3600; bp.Q.value = 0.7;
    g.gain.value = 0;
    src.connect(hp); hp.connect(bp); bp.connect(g); g.connect(master);
    let t = t0;
    while (t < t0 + sn) {
      const len = 0.09 + Math.random() * 0.16, amp = 0.05 + Math.random() * 0.07;
      g.gain.setValueAtTime(0.0001, t);
      g.gain.linearRampToValueAtTime(amp, t + 0.02);
      g.gain.linearRampToValueAtTime(amp * 0.5, t + len * 0.7);
      g.gain.linearRampToValueAtTime(0.0001, t + len);
      bp.frequency.setValueAtTime(3000 + Math.random() * 1800, t);
      t += len + 0.025 + Math.random() * 0.07;
    }
    src.start(t0); src.stop(t0 + sn + 0.1);
    chalk = { src, g };
    src.onended = () => { if (chalk && chalk.src === src) chalk = null; };
    return chalk;
  }
  function yazDur() {
    if (!chalk) return;
    const c = chalk; chalk = null;
    try { c.g.gain.cancelScheduledValues(ctx.currentTime); c.g.gain.setTargetAtTime(0.0001, ctx.currentTime, 0.03); c.src.stop(ctx.currentTime + 0.15); } catch {}
  }

  // ---- silgi: üç hafif sürtme
  function sil() {
    if (!acik() || !hazir()) return;
    const t0 = ctx.currentTime + 0.01;
    const src = gurultu(), lp = ctx.createBiquadFilter(), g = ctx.createGain();
    lp.type = "lowpass"; lp.frequency.value = 1100; lp.Q.value = 0.5;
    g.gain.value = 0.0001;
    src.connect(lp); lp.connect(g); g.connect(master);
    for (let i = 0; i < 3; i++) {
      const t = t0 + i * 0.17;
      g.gain.setValueAtTime(0.0001, t);
      g.gain.linearRampToValueAtTime(0.16, t + 0.05);
      g.gain.linearRampToValueAtTime(0.0001, t + 0.15);
      lp.frequency.setValueAtTime(700 + i * 150, t);
    }
    src.start(t0); src.stop(t0 + 0.7);
  }

  // ---- tahtaya işaret / vurgu: yumuşak "tık"
  function isaret() {
    if (!acik() || !hazir()) return;
    const t = ctx.currentTime + 0.005;
    const o = ctx.createOscillator(), g = ctx.createGain();
    o.type = "triangle"; o.frequency.setValueAtTime(820, t); o.frequency.exponentialRampToValueAtTime(380, t + 0.07);
    g.gain.setValueAtTime(0.0001, t); g.gain.linearRampToValueAtTime(0.35, t + 0.005); g.gain.exponentialRampToValueAtTime(0.0001, t + 0.1);
    o.connect(g); g.connect(master); o.start(t); o.stop(t + 0.12);
    const s = gurultu(), hp = ctx.createBiquadFilter(), gn = ctx.createGain();
    hp.type = "highpass"; hp.frequency.value = 2500;
    gn.gain.setValueAtTime(0.18, t); gn.gain.exponentialRampToValueAtTime(0.0001, t + 0.03);
    s.connect(hp); hp.connect(gn); gn.connect(master); s.start(t); s.stop(t + 0.05);
  }

  // ---- hocanın adımları: çok hafif, alçak tok sesler
  function adim(n = 3) {
    if (!acik() || !hazir()) return;
    for (let i = 0; i < n; i++) {
      const t = ctx.currentTime + 0.01 + i * 0.36;
      const o = ctx.createOscillator(), g = ctx.createGain(), lp = ctx.createBiquadFilter();
      o.type = "sine"; o.frequency.setValueAtTime(95 - (i % 2) * 12, t); o.frequency.exponentialRampToValueAtTime(55, t + 0.09);
      lp.type = "lowpass"; lp.frequency.value = 400;
      g.gain.setValueAtTime(0.0001, t); g.gain.linearRampToValueAtTime(0.22, t + 0.008); g.gain.exponentialRampToValueAtTime(0.0001, t + 0.13);
      o.connect(lp); lp.connect(g); g.connect(master); o.start(t); o.stop(t + 0.16);
    }
  }

  // ---- pomodoro zili: iki yumuşak nota (sınıf sesi kapalıysa bile bildirim için çalar; ses 0 ise çalmaz)
  function zil() {
    if (vol() <= 0 || !hazir()) return;
    [[660, 0], [880, 0.28], [1100, 0.56]].forEach(([f, dt]) => {
      const t = ctx.currentTime + 0.02 + dt, o = ctx.createOscillator(), g = ctx.createGain();
      o.type = "sine"; o.frequency.value = f;
      g.gain.setValueAtTime(0.0001, t); g.gain.linearRampToValueAtTime(0.28, t + 0.02); g.gain.exponentialRampToValueAtTime(0.0001, t + 1.3);
      o.connect(g); g.connect(ctx.destination); o.start(t); o.stop(t + 1.4);
    });
  }

  window.Sesler = {
    yaz, yazDur, sil, isaret, adim, zil,
    ac() { hazir(); },                           // kullanıcı etkileşiminde sesi uyandır
    konusuyor(b) { konusuyor = !!b; guncelle(); }, // hoca konuşurken -12 dB
    sustur(b) { bastirma = !!b; if (b) yazDur(); },  // yürürken ders gibi ekransız modlarda
    ayarDegisti() { guncelle(); if (!acik()) yazDur(); },
    ornek() { isaret(); },
  };
  ["pointerdown", "keydown"].forEach((e) => document.addEventListener(e, () => { if (ctx && ctx.state === "suspended") ctx.resume().catch(() => {}); }, { capture: true }));
})();
