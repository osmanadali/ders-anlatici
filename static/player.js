/* Oynatıcı: anlatım adımlarını sıraya alır, her adımın sesini çalarken tahta işlemlerini
   sesin süresine yayarak canlandırır. Ses gelmezse tarayıcının Türkçe sesiyle konuşur. */
(function () {
  const WRITE_SHARE = 0.9; // tahta yazımı sesin bu oranında biter

  class Player {
    constructor(board, hooks = {}) {
      this.board = board;
      this.hooks = hooks; // onStep(step), onIdle(), onState(state)
      this.queue = [];
      this.rate = 1;
      this.paused = false;
      this.busy = false;
      this.current = null; // {step, audio, utter}
      this.streamOpen = false;
      this.generation = 0; // stop() sonrası eski döngüleri geçersiz kılar
    }

    get state() { return this.busy ? (this.paused ? "paused" : "playing") : "idle"; }
    _emit() { this.hooks.onState?.(this.state); }

    enqueue(step) {
      this.queue.push(step);
      this._prefetch();
      if (!this.busy) this._loop();
    }

    _prefetch() {
      // Önümüzdeki 3 adımın sesini şimdiden indirmeye başla (sunucu üretimi beklerken tahta akmaya devam eder).
      this.queue.slice(0, 3).forEach((s) => {
        if (s.audio && !s._audio) {
          const a = new Audio();
          a.preload = "auto";
          a.src = s.audio;
          s._audio = a;
        }
      });
    }

    async _loop() {
      const gen = this.generation;
      this.busy = true;
      this._emit();
      while (this.queue.length && gen === this.generation) {
        const step = this.queue.shift();
        this._prefetch();
        await this._play(step, gen);
      }
      if (gen !== this.generation) return;
      this.busy = false;
      this.current = null;
      this._emit();
      this.hooks.onIdle?.();
    }

    async _waitUnpaused(gen) {
      while (this.paused && gen === this.generation) await new Promise((r) => setTimeout(r, 120));
    }

    async _play(step, gen) {
      await this._waitUnpaused(gen);
      if (gen !== this.generation) return;
      this.current = { step };
      let audio = step.audio ? step._audio || new Audio(step.audio) : null;
      let durMs = 0;
      if (audio) {
        const ok = await new Promise((res) => {
          if (audio.readyState >= 1 && Number.isFinite(audio.duration)) return res(true);
          const t = setTimeout(() => res(false), 90000);
          audio.addEventListener("loadedmetadata", () => { clearTimeout(t); res(true); }, { once: true });
          audio.addEventListener("error", () => { clearTimeout(t); res(false); }, { once: true });
        });
        if (gen !== this.generation) return;
        if (ok && Number.isFinite(audio.duration)) durMs = audio.duration * 1000;
        else { this.hooks.onAudioError?.(step.audio); audio = null; }
      }
      await this._waitUnpaused(gen);
      if (gen !== this.generation) return;
      this.hooks.onStep?.(step);

      let speechDone;
      if (audio) {
        this.current.audio = audio;
        this.hooks.onAudio?.(audio);
        audio.playbackRate = this.rate;
        speechDone = new Promise((res) => {
          audio.onended = res;
          audio.onerror = res;
          this.current.cancel = res;
        });
        try { await audio.play(); } catch (e) { console.warn("ses çalınamadı", e); }
      } else if (step.say) {
        durMs = Math.max(1200, step.say.length * 62);
        this.hooks.onAudio?.(null);
        speechDone = this._browserSpeak(step.say, durMs);
      } else {
        durMs = 900;
        speechDone = Promise.resolve();
      }
      const hasDrawing = (step.board || []).some((o) => o && o.op && o.op !== "newpage");
      this.hooks.onSpeak?.(true, hasDrawing);
      const drawing = this.board.render(step.board, durMs * WRITE_SHARE).then(() => this.hooks.onSpeak?.(true, false));
      await Promise.all([speechDone, drawing]);
      this.hooks.onSpeak?.(false, false);
    }

    _browserSpeak(text, estMs) {
      return new Promise((res) => {
        const synth = window.speechSynthesis;
        if (!synth) return setTimeout(res, estMs / this.rate);
        const u = new SpeechSynthesisUtterance(text);
        u.lang = "tr-TR";
        u.rate = this.rate;
        const tr = synth.getVoices().find((v) => v.lang && v.lang.toLowerCase().startsWith("tr"));
        if (tr) u.voice = tr;
        u.onend = u.onerror = res;
        this.current.utter = u;
        this.current.cancel = res;
        synth.speak(u);
      });
    }

    pause() {
      if (!this.busy) return;
      this.paused = true;
      this.current?.audio?.pause();
      window.speechSynthesis?.pause();
      this.board.pause();
      this._emit();
    }
    resume() {
      if (!this.paused) return;
      this.paused = false;
      this.current?.audio?.play().catch(() => {});
      window.speechSynthesis?.resume();
      this.board.resume();
      this._emit();
    }
    toggle() { this.paused ? this.resume() : this.pause(); }

    setRate(r) {
      this.rate = r;
      if (this.current?.audio) this.current.audio.playbackRate = r;
      this.board.setRate(r);
    }

    // Kalan her şeyi iptal et; tahtada yazılmakta olanı anında tamamla.
    stop() {
      this.generation++;
      this.queue.forEach((s) => s._audio && (s._audio.src = ""));
      this.queue = [];
      if (this.current?.audio) { this.current.audio.pause(); }
      window.speechSynthesis?.cancel();
      this.current?.cancel?.();
      this.board.resume();
      this.board.finishAll();
      this.paused = false;
      this.busy = false;
      this.current = null;
      this._emit();
    }

    get currentSay() { return this.current?.step?.say || ""; }
  }

  window.Player = Player;
})();
