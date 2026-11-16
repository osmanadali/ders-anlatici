/* Tahta: anlatım adımlarındaki işlemleri el yazısıyla yazılıyormuş gibi canlandırır.
   Metinler soldan sağa açılır (kalem ucu eşlik eder), çizgiler/eğriler çizgi çizgi çizilir. */
(function () {
  const NS = "http://www.w3.org/2000/svg";
  const COLORS = ["white", "yellow", "red", "blue", "green", "orange"];
  const MS_PER_WEIGHT = 75; // yazma hızı tavanı: ağırlık başına en fazla bu kadar ms

  function esc(s) {
    return String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  }
  function colorClass(c) { return "col-" + (COLORS.includes(c) ? c : "white"); }
  function cssColor(c) { return `var(--c-${COLORS.includes(c) ? c : "white"})`; }

  // "$x^2$ metin" → KaTeX'li HTML
  function renderInline(text) {
    const parts = String(text || "").split(/(\$[^$]+\$)/g);
    return parts.map((p) => {
      if (p.length > 2 && p.startsWith("$") && p.endsWith("$") && window.katex) {
        try { return katex.renderToString(p.slice(1, -1), { throwOnError: false }); } catch { return esc(p); }
      }
      return esc(p);
    }).join("");
  }
  function renderDisplay(tex) {
    if (!window.katex) return esc(tex);
    try { return katex.renderToString(tex, { throwOnError: false, displayMode: true }); } catch { return esc(tex); }
  }

  function weightOf(op) {
    switch (op.op) {
      case "title": return Math.max(8, (op.text || "").length * 0.9);
      case "write": return Math.max(8, (op.text || "").replace(/\$[^$]*\$/g, (m) => "x".repeat(Math.ceil(m.length * 0.5))).length);
      case "math": return Math.max(12, (op.tex || "").length * 0.55);
      case "arrow_note": return Math.max(6, (op.text || "").length * 0.8);
      case "plot": return 30 + (op.functions || []).length * 35 + (op.points || []).length * 6;
      case "diagram": return 8 + (op.shapes || []).length * 10;
      case "underline": return 6;
      case "box": return 9;
      case "show_page": return 14;
      default: return 0;
    }
  }

  // Elle çizilmiş görünüm için hafif titreşimli çizgi
  function roughLine(x1, y1, x2, y2, j = 1.2) {
    const mx = (x1 + x2) / 2 + (Math.random() - 0.5) * j * 2;
    const my = (y1 + y2) / 2 + (Math.random() - 0.5) * j * 2;
    return `M${x1.toFixed(1)} ${y1.toFixed(1)} Q${mx.toFixed(1)} ${my.toFixed(1)} ${x2.toFixed(1)} ${y2.toFixed(1)}`;
  }
  function svgEl(tag, attrs) {
    const e = document.createElementNS(NS, tag);
    for (const k in attrs) e.setAttribute(k, attrs[k]);
    return e;
  }
  function niceStep(span) {
    const raw = span / 8, p = Math.pow(10, Math.floor(Math.log10(raw))), f = raw / p;
    return (f < 1.5 ? 1 : f < 3.5 ? 2 : f < 7.5 ? 5 : 10) * p;
  }

  class Board {
    constructor(root) {
      this.root = root;
      this.pages = [];
      this.view = -1;
      this.courseId = "";
      this.active = new Set(); // çalışan animasyonlar
      this.rate = 1;
      this.onPageChange = () => {};
      this.clear();
    }

    // ---------------- sayfalar
    clear() {
      this.root.innerHTML = "";
      this.pages = [];
      this.newPage(true);
    }
    newPage(empty) {
      const p = document.createElement("div");
      p.className = "board-page";
      if (empty) {
        const e = document.createElement("div");
        e.className = "board-empty";
        e.textContent = "Tahta hazır. Bir soru sor ya da notlarından bir sayfa seç.";
        p.appendChild(e);
      }
      const pen = document.createElement("div");
      pen.className = "pen";
      pen.textContent = "✏️";
      pen.style.opacity = 0;
      p.appendChild(pen);
      p._pen = pen;
      this.root.appendChild(p);
      this.pages.push(p);
      this.show(this.pages.length - 1);
      return p;
    }
    get page() { return this.pages[this.pages.length - 1]; }
    show(i) {
      this.view = Math.max(0, Math.min(i, this.pages.length - 1));
      this.pages.forEach((p, k) => p.classList.toggle("off", k !== this.view));
      this.onPageChange(this.view, this.pages.length);
    }
    lastItem() {
      const items = this.page.querySelectorAll(":scope > .b-item");
      return items[items.length - 1] || null;
    }
    append(el) {
      const p = this.page;
      p.querySelector(".board-empty")?.remove();
      if (this.view !== this.pages.length - 1) this.show(this.pages.length - 1);
      p.insertBefore(el, p._pen);
      const bottom = el.offsetTop + el.offsetHeight + 30;
      if (bottom > p.scrollTop + p.clientHeight) p.scrollTop = bottom - p.clientHeight;
      return el;
    }

    // ---------------- animasyon kontrolü
    _anim(el, frames, opts) {
      const a = el.animate(frames, { fill: "both", easing: "linear", ...opts });
      a.playbackRate = this.rate;
      if (this.paused) a.pause();
      if (this.fast) a.finish();
      this.active.add(a);
      const done = a.finished.catch(() => {}).finally(() => this.active.delete(a));
      return done;
    }
    pause() { this.paused = true; this.active.forEach((a) => a.pause()); }
    resume() { this.paused = false; this.active.forEach((a) => a.play()); }
    setRate(r) { this.rate = r; this.active.forEach((a) => a.updatePlaybackRate(r)); }
    finishAll() { this.fast = true; this.active.forEach((a) => a.finish()); }

    // Bir adımın tüm işlemlerini sırayla, toplam ~totalMs içinde canlandırır.
    async render(ops, totalMs) {
      this.fast = false;
      ops = (ops || []).filter((o) => o && o.op);
      const weights = ops.map(weightOf);
      const W = weights.reduce((a, b) => a + b, 0) || 1;
      for (let i = 0; i < ops.length; i++) {
        let d = Math.min((totalMs * weights[i]) / W, weights[i] * MS_PER_WEIGHT);
        d = Math.max(weights[i] ? 180 : 0, d);
        try { await this.renderOp(ops[i], this.fast ? 0 : d); }
        catch (e) { console.warn("tahta işlemi atlandı", ops[i], e); }
      }
      this.page._pen.style.opacity = 0;
    }
    // Animasyonsuz anında çizim (kayıtları hızlı gösterme, PDF)
    async renderInstant(ops) { this.fast = true; for (const op of ops || []) { try { await this.renderOp(op, 0); } catch {} } }

    async renderOp(op, d) {
      switch (op.op) {
        case "title": return this._text("b-title", renderInline(op.text), op.color, d);
        case "write": return this._text("b-write", renderInline(op.text), op.color, d);
        case "math": return this._text("b-math", renderDisplay(op.tex || ""), op.color, d);
        case "arrow_note": return this._text("b-arrow-note", "↳ " + renderInline(op.text), op.color || "yellow", d);
        case "underline": return this._decor("underline", op.color || "yellow", d);
        case "box": return this._decor("box", op.color || "yellow", d);
        case "plot": return this._plot(op, d);
        case "diagram": return this._diagram(op, d);
        case "show_page": return this._showPage(op, d);
        case "newpage": this.newPage(false); return;
      }
    }

    async _text(cls, html, color, d) {
      const el = document.createElement("div");
      el.className = `b-item ${cls} ${colorClass(color)}`;
      el.innerHTML = html;
      this.append(el);
      const pen = this.page._pen;
      if (d > 0) {
        pen.style.opacity = 1;
        const x0 = el.offsetLeft, y = el.offsetTop + el.offsetHeight * 0.75;
        this._anim(pen, [{ left: x0 + "px", top: y + "px" }, { left: x0 + el.offsetWidth + "px", top: y + "px" }], { duration: d });
      }
      await this._anim(el, [{ clipPath: "inset(-12px 100% -12px -12px)" }, { clipPath: "inset(-12px -12px -12px -12px)" }], { duration: d });
    }

    // Yolları sırayla çizer: her yol uzunluğuna göre süre alır.
    async _drawPaths(paths, d, extraFades = []) {
      const lens = paths.map((p) => { try { return Math.max(1, p.getTotalLength()); } catch { return 1; } });
      const L = lens.reduce((a, b) => a + b, 0) || 1;
      let delay = 0;
      const all = paths.map((p, i) => {
        const dur = (d * 0.9 * lens[i]) / L;
        const pr = this._anim(p, [{ strokeDasharray: `${lens[i]} ${lens[i]}`, strokeDashoffset: lens[i] },
                                  { strokeDasharray: `${lens[i]} ${lens[i]}`, strokeDashoffset: 0 }], { duration: dur, delay });
        delay += dur;
        return pr;
      });
      for (const [el, at] of extraFades) all.push(this._anim(el, [{ opacity: 0 }, { opacity: 1 }], { duration: Math.max(1, d * 0.1), delay: at * d }));
      await Promise.all(all);
    }

    async _decor(kind, color, d) {
      const target = this.lastItem();
      if (!target) return;
      const w = target.offsetWidth + 16, h = target.offsetHeight + 8;
      const svg = svgEl("svg", { class: "decor", width: w, height: h, viewBox: `0 0 ${w} ${h}` });
      svg.style.color = cssColor(color);
      const path = svgEl("path", { fill: "none", stroke: "currentColor", "stroke-width": 2.6, "stroke-linecap": "round" });
      if (kind === "underline") {
        path.setAttribute("d", roughLine(6, h - 3, w - 6, h - 5, 2));
      } else {
        const r = () => (Math.random() - 0.5) * 4;
        path.setAttribute("d", `M${4 + r()} ${4 + r()} L${w - 4 + r()} ${3 + r()} L${w - 3 + r()} ${h - 4 + r()} L${3 + r()} ${h - 3 + r()} Z`);
      }
      svg.appendChild(path);
      target.appendChild(svg);
      await this._drawPaths([path], d);
    }

    async _plot(op, d) {
      const W = 540, H = 330, m = { l: 44, r: 20, t: 18, b: 34 };
      let [x0, x1] = Array.isArray(op.xrange) ? op.xrange.map(Number) : [-5, 5];
      let [y0, y1] = Array.isArray(op.yrange) ? op.yrange.map(Number) : [-5, 5];
      if (!(x1 > x0)) [x0, x1] = [-5, 5];
      if (!(y1 > y0)) [y0, y1] = [-5, 5];
      const X = (x) => m.l + ((x - x0) / (x1 - x0)) * (W - m.l - m.r);
      const Y = (y) => H - m.b - ((y - y0) / (y1 - y0)) * (H - m.t - m.b);
      const svg = svgEl("svg", { class: "b-svg", viewBox: `0 0 ${W} ${H}`, width: W, height: H });
      svg.style.maxWidth = "100%"; svg.style.height = "auto";
      const wrap = document.createElement("div");
      wrap.className = "b-item";
      wrap.appendChild(svg);
      this.append(wrap);

      const axes = [], fades = [];
      const clipId = "clip" + Math.random().toString(36).slice(2);
      const defs = svgEl("defs", {}), clip = svgEl("clipPath", { id: clipId });
      clip.appendChild(svgEl("rect", { x: m.l - 6, y: m.t - 6, width: W - m.l - m.r + 12, height: H - m.t - m.b + 12 }));
      defs.appendChild(clip); svg.appendChild(defs);
      const ax = X(Math.min(Math.max(0, x0), x1)), ay = Y(Math.min(Math.max(0, y0), y1));
      const stroke = { fill: "none", stroke: "var(--c-white)", "stroke-width": 1.8, "stroke-linecap": "round" };
      const addPath = (dstr, attrs, list) => { const p = svgEl("path", { ...stroke, ...attrs, d: dstr }); svg.appendChild(p); list.push(p); return p; };
      addPath(roughLine(m.l - 6, ay, W - m.r + 4, ay, 0.8) + ` M${W - m.r - 4} ${ay - 5} L${W - m.r + 4} ${ay} L${W - m.r - 4} ${ay + 5}`, {}, axes);
      addPath(roughLine(ax, H - m.b + 6, ax, m.t - 4, 0.8) + ` M${ax - 5} ${m.t + 4} L${ax} ${m.t - 4} L${ax + 5} ${m.t + 4}`, {}, axes);
      const addText = (x, y, t, attrs = {}) => { const e = svgEl("text", { x, y, "font-size": 18, ...attrs }); e.textContent = t; svg.appendChild(e); return e; };
      fades.push([addText(W - m.r - 4, ay - 8, op.xlabel || "x", { "text-anchor": "end" }), 0.25]);
      fades.push([addText(ax + 8, m.t + 10, op.ylabel || "y"), 0.25]);
      const fmt = (v) => (Math.abs(v) < 1e-9 ? "0" : +v.toFixed(2) + "");
      const sx = niceStep(x1 - x0), sy = niceStep(y1 - y0);
      for (let v = Math.ceil(x0 / sx) * sx; v <= x1 + 1e-9; v += sx) {
        if (Math.abs(v) < 1e-9) continue;
        addPath(`M${X(v)} ${ay - 4} L${X(v)} ${ay + 4}`, { "stroke-width": 1.2 }, axes);
        fades.push([addText(X(v), ay + 20, fmt(v), { "text-anchor": "middle", "font-size": 15, opacity: 0.8 }), 0.3]);
      }
      for (let v = Math.ceil(y0 / sy) * sy; v <= y1 + 1e-9; v += sy) {
        if (Math.abs(v) < 1e-9) continue;
        addPath(`M${ax - 4} ${Y(v)} L${ax + 4} ${Y(v)}`, { "stroke-width": 1.2 }, axes);
        fades.push([addText(ax - 8, Y(v) + 5, fmt(v), { "text-anchor": "end", "font-size": 15, opacity: 0.8 }), 0.3]);
      }

      const curves = [];
      (op.functions || []).forEach((f, fi) => {
        let fn;
        try {
          const expr = String(f.expr || "").replace(/\*\*/g, "^").replace(/\bln\(/g, "log(");
          fn = math.compile(expr);
        } catch { return; }
        const N = 400, span = y1 - y0;
        let dstr = "", pen = false, prevY = null, lastPt = null;
        for (let i = 0; i <= N; i++) {
          const x = x0 + ((x1 - x0) * i) / N;
          let y;
          try { y = Number(fn.evaluate({ x, e: Math.E, pi: Math.PI })); } catch { y = NaN; }
          const ok = Number.isFinite(y) && y > y0 - span * 2 && y < y1 + span * 2;
          const jump = prevY !== null && Math.abs(y - prevY) > span * 1.5;
          if (!ok || jump) { pen = false; prevY = ok ? y : null; if (!ok) continue; }
          const cy = Math.max(-50, Math.min(H + 50, Y(y)));
          dstr += (pen ? " L" : " M") + X(x).toFixed(1) + " " + cy.toFixed(1);
          pen = true; prevY = y;
          if (y >= y0 && y <= y1 && X(x) < W - m.r - 30) lastPt = [X(x), cy];
        }
        if (!dstr) return;
        const cp = addPath(dstr, { stroke: cssColor(f.color || ["yellow", "blue", "red", "green"][fi % 4]), "stroke-width": 2.6 }, curves);
        cp.setAttribute("clip-path", `url(#${clipId})`);
        if (f.label && lastPt) fades.push([addText(Math.min(lastPt[0] + 4, W - 60), Math.max(lastPt[1] - 8, 16), f.label, { fill: cssColor(f.color || "yellow") }), 0.6 + 0.3 * ((fi + 1) / (op.functions.length || 1))]);
      });
      svg.querySelectorAll("text").forEach((t) => (t.style.opacity = 0));
      const pts = [];
      (op.points || []).forEach((p, i) => {
        const c = svgEl("path", { d: `M${X(p.x) - 4} ${Y(p.y)} a4 4 0 1 0 8 0 a4 4 0 1 0 -8 0`, fill: "none", stroke: cssColor(p.color || "red"), "stroke-width": 3 });
        svg.appendChild(c);
        pts.push(c);
        if (p.label) fades.push([addText(X(p.x) + 8, Y(p.y) - 8, p.label, { fill: cssColor(p.color || "red"), "font-size": 17 }), 0.85 + 0.15 * (i / (op.points.length || 1))]);
      });
      svg.querySelectorAll("text").forEach((t) => (t.style.opacity = 0));
      // Önce eksenler (%30), sonra eğriler (%55), sonra noktalar
      const tAxes = d * 0.3, tCurves = d * 0.55, tPts = d * 0.15;
      await this._drawPaths(axes, tAxes, fades.filter((f) => f[1] <= 0.3).map(([e]) => [e, 0.6]));
      await this._drawPaths(curves, tCurves, fades.filter((f) => f[1] > 0.3 && f[1] <= 0.9).map(([e]) => [e, 0.9]));
      await this._drawPaths(pts, tPts, fades.filter((f) => f[1] > 0.84).map(([e]) => [e, 0.5]));
      svg.querySelectorAll("text").forEach((t) => { if (t.style.opacity === "0" && !t.getAnimations().length) t.style.opacity = 1; });
    }

    async _diagram(op, d) {
      const w = Math.max(1, Number(op.w) || 10), h = Math.max(1, Number(op.h) || 6), U = 52;
      const svg = svgEl("svg", { class: "b-svg", viewBox: `-10 -10 ${w * U + 20} ${h * U + 20}`, width: w * U + 20, height: h * U + 20 });
      svg.style.maxWidth = "100%"; svg.style.height = "auto";
      const wrap = document.createElement("div");
      wrap.className = "b-item";
      wrap.appendChild(svg);
      this.append(wrap);
      const X = (x) => Number(x) * U, Y = (y) => (h - Number(y)) * U;
      const paths = [], fades = [];
      const n = (op.shapes || []).length || 1;
      (op.shapes || []).forEach((s, i) => {
        const col = cssColor(s.color || "white");
        const at = i / n;
        const add = (dstr) => { const p = svgEl("path", { d: dstr, fill: "none", stroke: col, "stroke-width": 2.4, "stroke-linecap": "round", "stroke-linejoin": "round" }); svg.appendChild(p); paths.push(p); };
        switch (s.type) {
          case "line": add(roughLine(X(s.x1), Y(s.y1), X(s.x2), Y(s.y2))); break;
          case "arrow": {
            const x1 = X(s.x1), y1 = Y(s.y1), x2 = X(s.x2), y2 = Y(s.y2);
            const a = Math.atan2(y2 - y1, x2 - x1), k = 12;
            add(roughLine(x1, y1, x2, y2) + ` M${x2 - k * Math.cos(a - 0.45)} ${y2 - k * Math.sin(a - 0.45)} L${x2} ${y2} L${x2 - k * Math.cos(a + 0.45)} ${y2 - k * Math.sin(a + 0.45)}`);
            break;
          }
          case "circle": { const r = Number(s.r) * U, cx = X(s.cx), cy = Y(s.cy); add(`M${cx - r} ${cy} a${r} ${r} 0 1 0 ${2 * r} 0 a${r} ${r} 0 1 0 ${-2 * r} 0`); break; }
          case "rect": { const x = X(s.x), y = Y(Number(s.y) + Number(s.h)), ww = Number(s.w) * U, hh = Number(s.h) * U; add(`M${x} ${y} h${ww} v${hh} h${-ww} Z`); break; }
          case "polyline": if (Array.isArray(s.points) && s.points.length > 1) add("M" + s.points.map(([x, y]) => `${X(x)} ${Y(y)}`).join(" L")); break;
          case "text": {
            const t = svgEl("text", { x: X(s.x), y: Y(s.y), "font-size": s.size || 22, fill: col, "text-anchor": s.anchor || "middle" });
            t.textContent = s.text || ""; t.style.opacity = 0; svg.appendChild(t); fades.push([t, at]); break;
          }
        }
      });
      await this._drawPaths(paths, d, fades);
    }

    async _showPage(op, d) {
      if (!this.courseId || !op.doc || !op.page) return;
      const img = document.createElement("img");
      img.className = "b-item b-page-img";
      img.alt = `Not sayfası ${op.page}`;
      img.src = `/api/courses/${this.courseId}/docs/${op.doc}/pages/${op.page}.png`;
      const ok = await new Promise((res) => { img.onload = () => res(true); img.onerror = () => res(false); setTimeout(() => res(false), 4000); });
      if (!ok) return; // görseli olmayan belge (ör. ders kaydından çıkan not)
      this.append(img);
      await this._anim(img, [{ clipPath: "inset(0 0 100% 0)", opacity: 0.3 }, { clipPath: "inset(0 0 0 0)", opacity: 1 }], { duration: d });
    }

    // ---------------- PDF
    exportPDF() {
      let area = document.getElementById("printArea");
      if (!area) { area = document.createElement("div"); area.id = "printArea"; document.body.appendChild(area); }
      area.innerHTML = "";
      this.pages.forEach((p) => {
        if (!p.querySelector(".b-item")) return;
        const c = document.createElement("div");
        c.className = "print-page";
        p.querySelectorAll(":scope > .b-item").forEach((it) => c.appendChild(it.cloneNode(true)));
        // Kopyalarda animasyon olmadığından, animasyonla görünür olan öğelerin gizli başlangıç stilini kaldır.
        c.querySelectorAll("[style]").forEach((e) => { e.style.opacity = ""; e.style.clipPath = ""; });
        area.appendChild(c);
      });
      if (!area.children.length) return false;
      window.print();
      return true;
    }
  }

  window.Board = Board;
  window.BoardUtil = { renderInline, weightOf };
})();
