/* Hoca karakteri (SVG). Durumlar: idle, talking, writing, listening, thinking.
   Ağız, çalan sesin seviyesine göre açılıp kapanır (WebAudio analizörü). */
(function () {
  const SVG = `
<svg viewBox="0 0 220 440" xmlns="http://www.w3.org/2000/svg" class="teacher-svg" aria-label="Hoca">
  <defs>
    <linearGradient id="tJacket" x1="0" x2="1"><stop offset="0" stop-color="#5a4a3c"/><stop offset="1" stop-color="#6e5a48"/></linearGradient>
  </defs>
  <ellipse cx="112" cy="428" rx="70" ry="8" fill="rgba(0,0,0,.25)"/>
  <g class="t-body">
    <!-- bacaklar -->
    <path d="M78 300 L74 412 L100 412 L106 318 L118 318 L124 412 L150 412 L146 300 Z" fill="#34383f"/>
    <ellipse cx="86" cy="416" rx="20" ry="7" fill="#1d1f23"/><ellipse cx="139" cy="416" rx="20" ry="7" fill="#1d1f23"/>
    <!-- gövde -->
    <path d="M60 162 Q112 140 164 162 L170 300 Q112 312 54 300 Z" fill="url(#tJacket)"/>
    <path d="M96 150 L112 210 L128 150 Z" fill="#f4f1ea"/>
    <path d="M108 160 L116 160 L119 205 L112 216 L105 205 Z" fill="#a23b3b"/>
    <path d="M96 150 L112 210 L102 232 L86 160 Z" fill="#4c3e32"/><path d="M128 150 L112 210 L122 232 L138 160 Z" fill="#4c3e32"/>
    <circle cx="112" cy="250" r="2.5" fill="#2c241d"/><circle cx="112" cy="272" r="2.5" fill="#2c241d"/>
    <!-- sağ kol (dinlenme) -->
    <g class="t-arm-r">
      <path d="M160 166 Q178 220 172 292 L156 292 Q160 230 148 178 Z" fill="#5f4e3f"/>
      <circle cx="164" cy="298" r="10" fill="#e9bf9c"/>
    </g>
    <!-- sol kol (tahtaya uzanan, tebeşirli) -->
    <g class="t-arm-l">
      <path d="M66 166 Q48 220 54 290 L70 290 Q66 230 78 178 Z" fill="#5f4e3f"/>
      <circle cx="62" cy="296" r="10" fill="#e9bf9c"/>
      <rect x="56" y="300" width="5" height="13" rx="1.5" fill="#f5f2e6" transform="rotate(-20 58 306)"/>
    </g>
    <!-- baş -->
    <g class="t-head">
      <rect x="102" y="128" width="20" height="24" rx="6" fill="#e2b592"/>
      <ellipse cx="80" cy="96" rx="7" ry="10" fill="#e2b592"/><ellipse cx="144" cy="96" rx="7" ry="10" fill="#e2b592"/>
      <ellipse cx="112" cy="92" rx="33" ry="41" fill="#efc6a3"/>
      <path d="M78 84 Q76 46 112 44 Q150 44 147 84 Q140 62 112 62 Q86 62 78 84 Z" fill="#3b3029"/>
      <path d="M79 80 Q80 66 88 60" stroke="#8d8a86" stroke-width="3" fill="none" stroke-linecap="round"/>
      <path d="M145 80 Q144 66 136 60" stroke="#8d8a86" stroke-width="3" fill="none" stroke-linecap="round"/>
      <path class="t-brow-l" d="M89 79 Q97 74 105 78" stroke="#3b3029" stroke-width="3" fill="none" stroke-linecap="round"/>
      <path class="t-brow-r" d="M119 78 Q127 74 135 79" stroke="#3b3029" stroke-width="3" fill="none" stroke-linecap="round"/>
      <g class="t-eyes"><circle cx="97" cy="91" r="3.4" fill="#2a211b"/><circle cx="127" cy="91" r="3.4" fill="#2a211b"/></g>
      <rect x="85" y="82" width="24" height="18" rx="7" fill="rgba(255,255,255,.12)" stroke="#2e2a28" stroke-width="2.4"/>
      <rect x="115" y="82" width="24" height="18" rx="7" fill="rgba(255,255,255,.12)" stroke="#2e2a28" stroke-width="2.4"/>
      <path d="M109 90 L115 90" stroke="#2e2a28" stroke-width="2.4"/>
      <path d="M112 98 Q108 108 112 111 Q115 112 117 110" stroke="#c99472" stroke-width="2.2" fill="none" stroke-linecap="round"/>
      <path d="M92 118 Q112 140 132 118 Q130 132 112 134 Q94 132 92 118 Z" fill="#5b4a3f" opacity=".55"/>
      <path d="M101 118 Q112 115 123 118" stroke="#4a3a30" stroke-width="2.6" fill="none" stroke-linecap="round"/>
      <ellipse class="t-mouth" cx="112" cy="121" rx="8" ry="1.5" fill="#5b2a26"/>
    </g>
  </g>
  <g class="t-bubble t-think"><circle cx="160" cy="44" r="4" /><circle cx="172" cy="30" r="6"/><ellipse cx="192" cy="14" rx="18" ry="11"/><text x="192" y="18" text-anchor="middle">…</text></g>
  <g class="t-bubble t-listen"><path d="M152 84 q8 10 0 20 M160 78 q14 16 0 32 M168 72 q20 22 0 44" stroke-width="3" fill="none" stroke-linecap="round"/></g>
</svg>`;

  class Teacher {
    constructor(el) {
      this.el = el;
      el.insertAdjacentHTML("afterbegin", SVG);
      this.svg = el.querySelector("svg");
      this.mouth = el.querySelector(".t-mouth");
      this.eyes = el.querySelector(".t-eyes");
      this.state = "idle";
      this.level = 0;
      this.analyser = null;
      this.data = null;
      this.ctx = null;
      this.nextBlink = performance.now() + 2500;
      this.fakeTalk = false;
      requestAnimationFrame((t) => this._tick(t));
    }

    setState(s) {
      if (this.state === s) return;
      this.state = s;
      this.el.dataset.state = s;
    }

    // Tarayıcı ses politikası: AudioContext ancak kullanıcı etkileşiminden sonra çalışır.
    unlock() {
      if (!this.ctx) {
        try { this.ctx = new AudioContext(); } catch { return; }
        this.analyser = this.ctx.createAnalyser();
        this.analyser.fftSize = 512;
        this.data = new Uint8Array(this.analyser.fftSize);
        this.analyser.connect(this.ctx.destination);
      }
      if (this.ctx.state === "suspended") this.ctx.resume().catch(() => {});
    }

    // Çalınacak ses öğesini analizöre bağlar (ağız hareketi için).
    attachAudio(audio) {
      if (!this.ctx || this.ctx.state !== "running" || audio._tapped) return false;
      try {
        const src = this.ctx.createMediaElementSource(audio);
        src.connect(this.analyser);
        audio._tapped = true;
        return true;
      } catch { return false; }
    }

    _audioLevel() {
      if (!this.analyser) return 0;
      this.analyser.getByteTimeDomainData(this.data);
      let s = 0;
      for (let i = 0; i < this.data.length; i++) { const v = (this.data[i] - 128) / 128; s += v * v; }
      return Math.min(1, Math.sqrt(s / this.data.length) * 5);
    }

    _tick(t) {
      const talking = this.state === "talking" || this.state === "writing";
      let target = talking ? this._audioLevel() : 0;
      if (talking && this.fakeTalk) target = 0.25 + 0.55 * Math.abs(Math.sin(t / 85)) * (0.6 + 0.4 * Math.sin(t / 310));
      this.level += (target - this.level) * (target > this.level ? 0.55 : 0.25);
      this.mouth.setAttribute("ry", (1.5 + this.level * 8).toFixed(2));
      this.mouth.setAttribute("rx", (8 - this.level * 1.5).toFixed(2));

      if (t > this.nextBlink) {
        this.eyes.style.transform = "scaleY(0.1)";
        setTimeout(() => (this.eyes.style.transform = ""), 120);
        this.nextBlink = t + 2500 + Math.random() * 3500;
      }
      requestAnimationFrame((tt) => this._tick(tt));
    }
  }

  window.Teacher = Teacher;
})();
