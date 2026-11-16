/* Konuşmalı ders modu: mikrofon sürekli açık, birebir özel ders gibi.
   - Ses etkinliği algılama (VAD): konuşmaya başladığını ve bitirdiğini enerji seviyesinden anlar.
   - Hoca konuşurken sen konuşursan anında susar (söz kesme), soruyu dinler, cevaplar.
   - Kayıt ham PCM'den WAV'a çevrilir; konuşmanın ilk heceleri kaybolmasın diye 0,5 sn geriye dönük tampon tutulur. */
(function () {
  const WORKLET = `
    class Tap extends AudioWorkletProcessor {
      process(inputs) { const ch = inputs[0] && inputs[0][0]; if (ch) this.port.postMessage(ch.slice(0)); return true; }
    }
    registerProcessor("tap", Tap);`;

  function encodeWav(samples, rate) {
    const buf = new ArrayBuffer(44 + samples.length * 2), v = new DataView(buf);
    const w = (o, s) => { for (let i = 0; i < s.length; i++) v.setUint8(o + i, s.charCodeAt(i)); };
    w(0, "RIFF"); v.setUint32(4, 36 + samples.length * 2, true); w(8, "WAVE"); w(12, "fmt ");
    v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true); v.setUint32(24, rate, true);
    v.setUint32(28, rate * 2, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true); w(36, "data");
    v.setUint32(40, samples.length * 2, true);
    for (let i = 0; i < samples.length; i++) v.setInt16(44 + i * 2, Math.max(-1, Math.min(1, samples[i])) * 0x7fff, true);
    return new Blob([buf], { type: "audio/wav" });
  }

  class Conversation {
    /* hooks: isTutorSpeaking(), onSpeechStart(), onUtterance(wavBlob), onFalseStart(), onLevel(level, state) */
    constructor(hooks) {
      this.hooks = hooks;
      this.active = false;
      this.sensitivity = 1; // 0.6 (az hassas) – 1.6 (çok hassas)
    }

    async start() {
      if (this.active) return;
      this.stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 },
      });
      this.ctx = new AudioContext(); // Firefox farklı örnekleme hızına izin vermediği için cihazın hızı kullanılır
      this.rate = this.ctx.sampleRate;
      const url = URL.createObjectURL(new Blob([WORKLET], { type: "application/javascript" }));
      await this.ctx.audioWorklet.addModule(url);
      const src = this.ctx.createMediaStreamSource(this.stream);
      this.node = new AudioWorkletNode(this.ctx, "tap");
      src.connect(this.node);
      const mute = this.ctx.createGain(); mute.gain.value = 0; this.node.connect(mute).connect(this.ctx.destination);

      this.ring = [];           // son ~0,6 sn (konuşma öncesi tampon)
      this.rec = null;          // kaydedilen konuşma parçaları
      this.floor = 0.006;       // ortam gürültüsü tahmini
      this.above = 0;           // eşik üstünde geçen süre (ms)
      this.silence = 0;         // konuşma sırasında sessizlik süresi (ms)
      this.speechMs = 0;
      this.state = "idle";      // idle | speaking
      this.node.port.onmessage = (e) => this._frame(e.data);
      this.active = true;
    }

    stop() {
      this.active = false;
      try { this.node?.disconnect(); } catch {}
      this.stream?.getTracks().forEach((t) => t.stop());
      this.ctx?.close().catch(() => {});
      this.state = "idle";
      this.rec = null;
    }

    _frame(f) {
      if (!this.active) return;
      const ms = (f.length / this.rate) * 1000;
      let sum = 0;
      for (let i = 0; i < f.length; i++) sum += f[i] * f[i];
      const rms = Math.sqrt(sum / f.length);
      const tutor = this.hooks.isTutorSpeaking();

      // Hoca konuşurken hoparlör sesi mikrofona sızabilir: eşiği ve gereken süreyi yükselt.
      const k = this.sensitivity;
      const thr = Math.max(0.012, this.floor * 3.2) * (tutor ? 2.2 : 1) / k;
      const needMs = tutor ? 380 : 200;

      this.ring.push(f);
      if (this.ring.length > Math.ceil((0.6 * this.rate) / f.length)) this.ring.shift();

      if (this.state === "idle") {
        if (!tutor && rms < thr) this.floor = this.floor * 0.995 + rms * 0.005; // gürültü tabanını öğren
        this.above = rms > thr ? this.above + ms : Math.max(0, this.above - ms * 2);
        if (this.above >= needMs) {
          this.state = "speaking";
          this.rec = this.ring.slice();
          this.speechMs = this.above;
          this.silence = 0;
          this.hooks.onSpeechStart?.();
        }
      } else {
        this.rec.push(f);
        this.speechMs += ms;
        this.silence = rms > thr * 0.7 ? 0 : this.silence + ms;
        const endAfter = 850; // bu kadar sessizlik = cümle bitti
        if (this.silence >= endAfter || this.speechMs > 45000) this._finish();
      }
      this.hooks.onLevel?.(Math.min(1, rms / (thr * 2.5)), this.state);
    }

    _finish() {
      const parts = this.rec || [];
      this.rec = null;
      this.state = "idle";
      this.above = 0;
      const voiced = this.speechMs - this.silence;
      if (voiced < 450) { this.hooks.onFalseStart?.(); return; } // öksürük, tık sesi vb.
      const n = parts.reduce((a, p) => a + p.length, 0), all = new Float32Array(n);
      let o = 0;
      for (const p of parts) { all.set(p, o); o += p.length; }
      this.hooks.onUtterance?.(encodeWav(all, this.rate));
    }
  }

  window.Conversation = Conversation;
})();

/* Tarayıcının kendi konuşma tanıması (Edge/Chrome): ücretsiz, anında, model indirmez.
   Konuşmalı derste varsayılan budur; yoksa ya da hata verirse yukarıdaki Whisper yoluna geçilir. */
(function () {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  const norm = (t) => (t || "").toLocaleLowerCase("tr-TR").replace(/[^\p{L}\p{N}\s]/gu, " ").split(/\s+/).filter(Boolean);

  class BrowserConversation {
    /* hooks: isTutorSpeaking(), tutorText() → hocanın şu an söylediği, onSpeechStart(), onText(text),
              onFalseStart(), onLevel(level, state), onFail(reason) */
    constructor(hooks) { this.hooks = hooks; this.active = false; this.sensitivity = 1; }
    static available() { return !!SR; }

    // Hoparlörden mikrofona sızan hoca sesi: duyulan kelimelerin çoğu hocanın cümlesindeyse yankıdır.
    isEcho(text) {
      const heard = norm(text);
      if (!heard.length) return true;
      const said = new Set(norm(this.hooks.tutorText?.() || ""));
      if (!said.size) return false;
      const hit = heard.filter((w) => said.has(w)).length;
      return hit / heard.length >= 0.6;
    }

    async start() {
      if (!SR) throw new Error("Bu tarayıcıda konuşma tanıma yok");
      this.active = true;
      this.speaking = false;
      this._fails = 0;
      this._spin();
    }

    _spin() {
      if (!this.active) return;
      const r = new SR();
      r.lang = "tr-TR";
      r.continuous = true;
      r.interimResults = true;
      r.maxAlternatives = 1;
      this.rec = r;
      r.onresult = (ev) => {
        this._fails = 0;
        for (let i = ev.resultIndex; i < ev.results.length; i++) {
          const res = ev.results[i], text = res[0].transcript.trim();
          if (!text) continue;
          const tutor = this.hooks.isTutorSpeaking();
          const words = norm(text).length;
          if (!res.isFinal) {
            // Söz kesme: hoca konuşurken en az 2 kelime (yankı değilse) → hemen sus
            if (!this.speaking && (!tutor || (words >= 2 / this.sensitivity && !this.isEcho(text)))) {
              this.speaking = true;
              this.hooks.onSpeechStart?.();
            }
            this.hooks.onLevel?.(0.8, "speaking");
            continue;
          }
          this.hooks.onLevel?.(0, "idle");
          const wasSpeaking = this.speaking;
          this.speaking = false;
          if ((tutor || wasSpeaking) && this.isEcho(text)) { this.hooks.onFalseStart?.(); continue; }
          if (norm(text).join("").length < 2) { this.hooks.onFalseStart?.(); continue; }
          this.hooks.onText?.(text);
        }
      };
      r.onerror = (e) => {
        if (e.error === "no-speech" || e.error === "aborted") return;
        if (e.error === "not-allowed" || e.error === "service-not-allowed") { this.active = false; this.hooks.onFail?.("Mikrofon izni verilmedi."); return; }
        if (e.error === "network" || ++this._fails > 3) { this.active = false; this.hooks.onFail?.("Tarayıcının konuşma tanıması çalışmadı (" + e.error + ")."); }
      };
      r.onend = () => { if (this.active) setTimeout(() => this._spin(), 150); };  // tarayıcı sessizlikte durdurur: yeniden başlat
      try { r.start(); } catch (e) { setTimeout(() => this._spin(), 500); }
    }

    stop() {
      this.active = false;
      try { this.rec?.abort(); } catch {}
    }
  }

  window.BrowserConversation = BrowserConversation;
})();
