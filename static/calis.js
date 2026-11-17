/* Çalış modülü: window.Calis = { kartlar, hatalar, simulasyon, ozetKarti, calismaAlani, indirmeDugmeleri, ozet, ozetVerisi }
   ctx = { courseId, course, api, postJSON, toast, ask }  (sessionId varsa özet kartı onu kullanır)
   Sunucu tarafı: app/calis.py (/api/calis/...). Stiller bu dosyada enjekte edilir. */
(function () {
  "use strict";

  // ---------------------------------------------------------------- stiller
  const CSS = `
.cl{--cl-gap:12px;color:var(--text);max-width:100%;box-sizing:border-box}
.cl *{box-sizing:border-box}
.cl h3,.cl h4{margin:0 0 6px}
.cl .cl-muted{color:var(--muted);font-size:.9em}
.cl .cl-row{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
.cl .cl-sp{flex:1}
.cl .cl-panel{background:var(--panel-solid);border:1px solid var(--line);border-radius:var(--radius);box-shadow:var(--shadow);padding:16px;margin:0 0 var(--cl-gap);min-width:0;overflow-wrap:anywhere}
.cl button{font:inherit;cursor:pointer;padding:8px 14px;border:1px solid var(--line);background:var(--panel-solid);color:var(--text);border-radius:999px}
.cl button:disabled{opacity:.5;cursor:default}
.cl button.cl-pri{background:var(--grad);color:var(--accent-text);border:0;font-weight:600}
.cl button.cl-ghost{background:transparent}
.cl button.cl-sm{padding:5px 11px;font-size:.88em}
.cl input[type=text],.cl input[type=number],.cl select,.cl textarea{font:inherit;width:100%;padding:8px 10px;border:1px solid var(--line);border-radius:var(--radius-sm);background:var(--panel-solid);color:var(--text)}
.cl textarea{resize:vertical;min-height:70px}
.cl label.cl-f{display:block;margin:0 0 10px;font-size:.92em}
.cl label.cl-f>span{display:block;margin-bottom:3px;font-weight:600}
.cl .cl-badge{display:inline-block;padding:2px 9px;border-radius:999px;font-size:.78em;font-weight:600;background:var(--accent-2);color:var(--accent)}
.cl .cl-badge.t-kavram_yanilgisi{background:#fde7e7;color:#b3261e}
.cl .cl-badge.t-islem_hatasi{background:#fff1d6;color:#9a5b00}
.cl .cl-badge.t-dikkat{background:#e4eefc;color:#1d4fa3}
.cl .cl-badge.t-bilgi_eksikligi{background:#ece6f7;color:#5b3a99}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]) .cl .cl-badge.t-kavram_yanilgisi{background:#3b1c1c;color:#ff9c94}
:root:not([data-theme=light]) .cl .cl-badge.t-islem_hatasi{background:#3a2c10;color:#ffcc7a}
:root:not([data-theme=light]) .cl .cl-badge.t-dikkat{background:#142640;color:#9cc2ff}
:root:not([data-theme=light]) .cl .cl-badge.t-bilgi_eksikligi{background:#271c3d;color:#cdb6ff}}
:root[data-theme=dark] .cl .cl-badge.t-kavram_yanilgisi{background:#3b1c1c;color:#ff9c94}
:root[data-theme=dark] .cl .cl-badge.t-islem_hatasi{background:#3a2c10;color:#ffcc7a}
:root[data-theme=dark] .cl .cl-badge.t-dikkat{background:#142640;color:#9cc2ff}
:root[data-theme=dark] .cl .cl-badge.t-bilgi_eksikligi{background:#271c3d;color:#cdb6ff}
/* hatalar */
.cl .cl-hata{border-top:1px solid var(--line);padding:12px 0}
.cl .cl-hata:first-of-type{border-top:0}
.cl .cl-hata .cl-q{font-weight:600;margin-bottom:6px}
.cl .cl-ans{margin:4px 0;padding:6px 10px;border-radius:var(--radius-sm);font-size:.92em}
.cl .cl-ans.bad{background:color-mix(in srgb,#d93025 12%,transparent)}
.cl .cl-ans.good{background:color-mix(in srgb,#1e9e5a 14%,transparent)}
/* kartlar */
.cl .cl-prog{height:8px;background:var(--panel-2);border-radius:999px;overflow:hidden;margin:6px 0 14px}
.cl .cl-prog>i{display:block;height:100%;background:var(--grad);width:0;transition:width .3s}
.cl .cl-flip{perspective:1200px;touch-action:pan-y;user-select:none}
.cl .cl-flipin{position:relative;min-height:min(52vh,340px);transition:transform .45s;transform-style:preserve-3d}
.cl .cl-flip.on .cl-flipin{transform:rotateY(180deg)}
.cl .cl-face{position:absolute;inset:0;backface-visibility:hidden;-webkit-backface-visibility:hidden;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;padding:22px;border-radius:var(--radius);border:1px solid var(--line);background:var(--panel-solid);box-shadow:var(--shadow-lg);overflow:auto;font-size:1.18em;line-height:1.5;overflow-wrap:anywhere}
.cl .cl-face.back{transform:rotateY(180deg);background:var(--accent-2)}
.cl .cl-face .cl-src{position:absolute;top:10px;left:14px;font-size:.62em}
.cl .cl-rate{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-top:14px}
.cl .cl-rate button{padding:12px 6px;border-radius:var(--radius-sm)}
.cl .cl-hint{text-align:center;margin-top:8px}
/* simülasyon */
.cl .cl-bar{position:sticky;top:0;z-index:5;display:flex;gap:10px;align-items:center;flex-wrap:wrap;background:var(--panel-solid);border:1px solid var(--line);border-radius:var(--radius);padding:10px 14px;margin-bottom:12px;box-shadow:var(--shadow)}
.cl .cl-time{font:700 1.4em ui-monospace,Menlo,Consolas,monospace}
.cl .cl-time.low{color:#d93025}
.cl .cl-sq{padding:14px 0;border-top:1px solid var(--line)}
.cl .cl-sq:first-of-type{border-top:0}
.cl .cl-opt{display:flex;gap:8px;align-items:flex-start;padding:7px 10px;margin:4px 0;border:1px solid var(--line);border-radius:var(--radius-sm);cursor:pointer}
.cl .cl-opt input{margin-top:4px}
.cl .cl-opt:has(input:checked){border-color:var(--accent);background:var(--accent-2)}
.cl .cl-score{font:800 3.2em/1 system-ui;background:var(--grad);-webkit-background-clip:text;background-clip:text;color:transparent}
.cl .cl-loss{display:grid;grid-template-columns:minmax(80px,200px) 1fr 52px;gap:8px;align-items:center;margin:6px 0;font-size:.92em}
.cl .cl-loss i{display:block;height:10px;border-radius:999px;background:#d93025;opacity:.75}
.cl .cl-loss span{overflow-wrap:anywhere}
/* çalışma alanı */
.cl .cl-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:0 14px}
.cl table.cl-t{border-collapse:collapse;width:100%;font-size:.92em}
.cl table.cl-t td{border-top:1px solid var(--line);padding:5px 8px;vertical-align:top;overflow-wrap:anywhere}
.cl table.cl-t td:first-child{font-weight:600;white-space:nowrap;width:1%}
.cl .cl-steps{margin:0;padding-left:20px}
.cl .cl-steps li{margin:3px 0;overflow-wrap:anywhere;white-space:pre-wrap}
/* özet kartı */
.cl .cl-ozet h3{font-size:1.25em}
.cl .cl-chips{display:flex;flex-wrap:wrap;gap:6px;margin:8px 0}
.cl .cl-formul{overflow-x:auto;max-width:100%;padding:2px 0}
.cl .cl-ozet ul{margin:6px 0;padding-left:20px}
@media (max-width:560px){.cl .cl-panel{padding:12px;border-radius:var(--radius-sm)}.cl .cl-loss{grid-template-columns:90px 1fr 48px}.cl .cl-face{font-size:1.05em;padding:16px}}
@media print{html.cl-printing body *{visibility:hidden!important}
html.cl-printing .cl-print-target,html.cl-printing .cl-print-target *{visibility:visible!important}
html.cl-printing .cl-print-target{position:absolute!important;left:0;top:0;width:100%;box-shadow:none!important;border:0!important}
html.cl-printing .cl-print-target button{display:none!important}}
`;
  function stilVer() {
    if (document.getElementById("calis-style")) return;
    const s = document.createElement("style");
    s.id = "calis-style";
    s.textContent = CSS;
    document.head.appendChild(s);
  }

  // ---------------------------------------------------------------- yardımcılar
  const esc = (t) => String(t == null ? "" : t).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const MESAJ = (e) => (e && e.message) || String(e);

  // "$x$" satır içi, "$$x$$" ayrı satır formül; satır sonları korunur
  function tex(metin) {
    const parca = String(metin == null ? "" : metin).split(/(\$\$[^$]+\$\$)/g);
    return parca.map((p) => {
      if (p.length > 4 && p.startsWith("$$") && p.endsWith("$$")) {
        const t = p.slice(2, -2);
        if (window.katex) { try { return `<div class="cl-formul">${katex.renderToString(t, { throwOnError: false, displayMode: true })}</div>`; } catch {} }
        return `<div class="cl-formul">${esc(t)}</div>`;
      }
      const h = window.BoardUtil && BoardUtil.renderInline ? BoardUtil.renderInline(p) : esc(p);
      return h.replace(/\n/g, "<br>");
    }).join("");
  }

  async function json(ctx, yol, govde, secenek) {
    const baslik = { "Content-Type": "application/json" };
    const opts = govde === undefined ? { ...(secenek || {}) } : { method: "POST", headers: baslik, body: JSON.stringify(govde), ...(secenek || {}) };
    let r;
    try { r = await fetch(yol, opts); } catch (e) { throw new Error("Sunucuya ulaşılamadı."); }
    if (!r.ok) {
      let m = r.statusText;
      try { m = (await r.json()).detail || m; } catch {}
      throw new Error(typeof m === "string" ? m : "İstek başarısız");
    }
    return r.json();
  }
  const toast = (ctx, m) => { try { (ctx && ctx.toast ? ctx.toast : console.log)(m); } catch {} };
  const cid = (ctx) => (ctx && (ctx.courseId || (ctx.course && ctx.course.id))) || "";

  function kok(el, ad) {
    stilVer();
    el.innerHTML = "";
    const d = document.createElement("div");
    d.className = "cl " + ad;
    el.appendChild(d);
    return d;
  }
  const bos = (ad, m) => `<div class="cl-panel"><h3>${esc(ad)}</h3><p class="cl-muted">${m}</p></div>`;

  function dosyaIndir(blob, ad) {
    const u = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = u; a.download = ad; document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(u), 4000);
  }

  // ---------------------------------------------------------------- yanlışları otomatik yakala (fetch sarmalayıcı)
  // /api/quiz/grade cevabı correct=false ise soruyu Hatalarım defterine yazar. Hiçbir koşulda asıl isteği bozmaz.
  (function fetchSar() {
    if (window.__calisFetchSarildi || typeof window.fetch !== "function") return;
    window.__calisFetchSarildi = true;
    const orijinal = window.fetch.bind(window);
    window.fetch = function (girdi, secenek) {
      const p = orijinal(girdi, secenek);
      try {
        const url = typeof girdi === "string" ? girdi : (girdi && girdi.url) || "";
        const yontem = String((secenek && secenek.method) || (girdi && girdi.method) || "GET").toUpperCase();
        const fd = secenek && secenek.body;
        if (yontem === "POST" && /\/api\/quiz\/grade(\?|$)/.test(url) && typeof FormData !== "undefined" && fd instanceof FormData) {
          const soruMetni = fd.get("question"), ogr = fd.get("answer"), kurs = fd.get("course_id");
          p.then((r) => (r.ok ? r.clone().json() : null)).then((g) => {
            if (!g || g.correct !== false) return;
            let q = {};
            try { q = JSON.parse(soruMetni); } catch { return; }
            if (!q.question) return;
            orijinal("/api/calis/hata", {
              method: "POST", headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ course_id: String(kurs || ""), soru: q.question, dogru_cevap: String(q.answer || ""), ogrenci_cevabi: String(ogr || ""),
                konu: String(g.mistake_topic || q.topic || ""), kaynak: String(q.page || "") }),
            }).then(() => window.dispatchEvent(new CustomEvent("calis:hata"))).catch(() => {});
          }).catch(() => {});
        }
      } catch {}
      return p;
    };
  })();

  // ================================================================ 1) HATALARIM
  const TUR = { kavram_yanilgisi: "Kavram yanılgısı", islem_hatasi: "İşlem hatası", dikkat: "Dikkat", bilgi_eksikligi: "Bilgi eksikliği" };

  async function hatalar(el, ctx) {
    const R = kok(el, "cl-hatalar");
    let arsiv = false, yuk = 0;
    async function ciz() {
      const b = ++yuk;
      R.innerHTML = '<div class="cl-panel cl-muted">Yükleniyor…</div>';
      let v;
      try { v = await json(ctx, `/api/calis/hatalar?course_id=${encodeURIComponent(cid(ctx))}&arsiv=${arsiv ? 1 : 0}`); }
      catch (e) { if (b === yuk) R.innerHTML = bos("Hatalarım", esc(MESAJ(e))); return; }
      if (b !== yuk) return;
      const turSay = {};
      v.hatalar.forEach((h) => { if (h.tur) turSay[h.tur] = (turSay[h.tur] || 0) + 1; });
      let h = `<div class="cl-panel"><div class="cl-row"><h3 style="margin:0">${arsiv ? "Öğrendiklerim (arşiv)" : "Hatalarım defteri"}</h3><span class="cl-badge">${v.hatalar.length} soru</span>` +
        Object.entries(turSay).map(([t, n]) => `<span class="cl-badge t-${t}">${TUR[t] || t}: ${n}</span>`).join("") +
        `<span class="cl-sp"></span><button class="cl-ghost cl-sm" data-k="arsiv">${arsiv ? "← Hatalarım" : "Öğrendiklerim"}</button></div>` +
        (v.hatalar.length ? "" : `<p class="cl-muted">${arsiv ? "Arşivde soru yok." : "Henüz hata kaydı yok. Sınavda ya da soru bankasında yanlış yaptığın sorular burada toplanır."}</p>`) + "</div>";
      v.gruplar.forEach((g) => {
        h += `<div class="cl-panel"><h4>${esc(g.konu)} <span class="cl-muted">(${g.hatalar.length})</span></h4>`;
        g.hatalar.forEach((x) => {
          h += `<div class="cl-hata" data-id="${x.id}"><div class="cl-q">${tex(x.soru)}</div>` +
            (x.ogrenci_cevabi ? `<div class="cl-ans bad"><b>Cevabın:</b> ${tex(x.ogrenci_cevabi)}</div>` : "") +
            (x.dogru_cevap ? `<div class="cl-ans good"><b>Doğru cevap:</b> ${tex(x.dogru_cevap)}</div>` : "") +
            `<div class="cl-row" style="margin:6px 0">${x.tur ? `<span class="cl-badge t-${x.tur}">${TUR[x.tur] || esc(x.tur)}</span>` : ""}` +
            (x.sayac > 1 ? `<span class="cl-badge">${x.sayac}× yanlış</span>` : "") + (x.kaynak ? `<span class="cl-muted">${esc(x.kaynak)}</span>` : "") + `</div>` +
            (x.aciklama ? `<div class="cl-muted">${esc(x.aciklama)}${x.oneri ? " <b>Öneri:</b> " + esc(x.oneri) : ""}</div>` : "") +
            `<div class="cl-row" style="margin-top:8px"><button class="cl-sm" data-k="anlat">📖 Bu konuyu tekrar anlat</button><button class="cl-sm" data-k="benzer">✏️ Benzer soru sor</button>` +
            `<button class="cl-sm cl-ghost" data-k="ogrendim">${arsiv ? "↩ Geri al" : "✔ Öğrendim"}</button></div></div>`;
        });
        h += "</div>";
      });
      R.innerHTML = h;
      R.querySelector('[data-k="arsiv"]').onclick = () => { arsiv = !arsiv; ciz(); };
      const kayit = Object.fromEntries(v.hatalar.map((x) => [x.id, x]));
      R.querySelectorAll(".cl-hata").forEach((d) => {
        const x = kayit[d.dataset.id], konu = x.konu || "bu konu";
        d.querySelector('[data-k="anlat"]').onclick = () => ctx.ask && ctx.ask({ text: `“${konu}” konusunda şu soruyu yanlış yaptım:\n${x.soru}\nBana bu konuyu baştan, hatamın nedenine odaklanarak anlat ve bir örnek çöz.`, label: `Tekrar anlat: ${konu}` });
        d.querySelector('[data-k="benzer"]').onclick = () => ctx.ask && ctx.ask({ text: `Şu soruya benzer, aynı konuda yeni bir soru sor, cevabımı bekle ve sonra değerlendir:\n${x.soru}`, label: `Benzer soru: ${konu}` });
        d.querySelector('[data-k="ogrendim"]').onclick = async (e) => {
          e.target.disabled = true;
          try { await json(ctx, `/api/calis/hata/${x.id}/arsiv`, { geri: arsiv }); ciz(); } catch (err) { toast(ctx, MESAJ(err)); e.target.disabled = false; }
        };
      });
    }
    const dinle = () => { if (!R.isConnected) window.removeEventListener("calis:hata", dinle); else if (!arsiv) ciz(); };
    window.addEventListener("calis:hata", dinle);
    return ciz();
  }

  // ================================================================ 2) KARTLAR
  async function kartlar(el, ctx) {
    const R = kok(el, "cl-kartlar");
    R.innerHTML = '<div class="cl-panel cl-muted">Kartlar yükleniyor…</div>';
    const yenile = () => { if (!R.isConnected) window.removeEventListener("calis:hata", yenile); else kartlar(el, ctx); };
    window.addEventListener("calis:hata", yenile);
    let v;
    try { v = await json(ctx, `/api/calis/kartlar?course_id=${encodeURIComponent(cid(ctx))}&n=30`); }
    catch (e) { R.innerHTML = bos("Kartlar", esc(MESAJ(e))); return; }
    const kuyruk = v.kartlar.map((k) => ({ ...k, _tekrar: 0 }));
    const toplam = kuyruk.length;
    let bitti = 0, cevir = false;
    const sayac = { bilemedim: 0, zor: 0, kolay: 0 };
    if (!toplam) {
      R.innerHTML = bos("Kartlar", `Bugün tekrar edilecek kart yok. 🎉 Toplam kart destesi: ${v.toplam}.<br>Kartlar; hazır paket kavramlarından, formül kâğıdından, soru bankasından ve hatalarından otomatik oluşur.`);
      return;
    }
    function ciz() {
      if (!R.isConnected) return;
      if (!kuyruk.length) {
        R.innerHTML = `<div class="cl-panel"><h3>Bugünkü kartlar bitti 🎉</h3><p>${toplam} kartı tekrar ettin.</p>` +
          `<div class="cl-row"><span class="cl-badge">Kolay: ${sayac.kolay}</span><span class="cl-badge">Zor: ${sayac.zor}</span><span class="cl-badge">Bilemedim: ${sayac.bilemedim}</span></div>` +
          `<p class="cl-muted">Her kart, cevabına göre 1/3/7/14/30 gün sonra yeniden karşına çıkar.</p><button class="cl-pri" data-k="yeni">Yeniden yükle</button></div>`;
        R.querySelector('[data-k="yeni"]').onclick = () => kartlar(el, ctx);
        return;
      }
      const k = kuyruk[0];
      R.innerHTML = `<div class="cl-row cl-muted"><span>${bitti}/${toplam} tamamlandı</span><span class="cl-sp"></span><span>${k.kaynak === "hata" ? "Hatalarımdan" : esc(k.konu || "")}</span></div>` +
        `<div class="cl-prog"><i style="width:${Math.round((100 * bitti) / toplam)}%"></i></div>` +
        `<div class="cl-flip${cevir ? " on" : ""}" tabindex="0"><div class="cl-flipin"><div class="cl-face front"><span class="cl-src cl-badge">${esc(KAYNAK[k.kaynak] || k.kaynak)}</span>${tex(k.on)}</div>` +
        `<div class="cl-face back">${tex(k.arka)}</div></div></div>` +
        `<div class="cl-hint cl-muted">${cevir ? "Ne kadar hatırladın?" : "Çevirmek için karta dokun · Boşluk · Enter"}</div>` +
        `<div class="cl-rate" style="${cevir ? "" : "visibility:hidden"}"><button data-p="bilemedim">😕 Bilemedim<br><small>1 · yarın</small></button><button data-p="zor">😐 Zor<br><small>2</small></button><button data-p="kolay">😀 Kolay<br><small>3 · uzun aralık</small></button></div>`;
      const fl = R.querySelector(".cl-flip");
      let x0 = null;
      fl.onclick = () => { if (!cevir) { cevir = true; ciz(); } else { cevir = false; ciz(); } };
      fl.addEventListener("touchstart", (e) => { x0 = e.touches[0].clientX; }, { passive: true });
      fl.addEventListener("touchend", (e) => {
        if (x0 == null) return;
        const dx = e.changedTouches[0].clientX - x0; x0 = null;
        if (Math.abs(dx) < 60) return;
        e.preventDefault();
        if (!cevir) { cevir = true; ciz(); } else cevapla(dx > 0 ? "kolay" : "bilemedim");  // sağa = kolay, sola = bilemedim
      });
      R.querySelectorAll("[data-p]").forEach((b) => (b.onclick = () => cevapla(b.dataset.p)));
    }
    async function cevapla(p) {
      if (!cevir || !kuyruk.length) return;
      const k = kuyruk.shift();
      cevir = false;
      sayac[p]++;
      if (p === "bilemedim" && k._tekrar < 2) { k._tekrar++; kuyruk.splice(Math.min(3, kuyruk.length), 0, k); }  // oturum içinde birkaç kart sonra yine sor
      else bitti++;
      ciz();
      try { await json(ctx, `/api/calis/kart/${k.id}/cevap`, { puan: p, course_id: cid(ctx) }); } catch (e) { toast(ctx, MESAJ(e)); }
    }
    const tus = (e) => {
      if (!R.isConnected) { document.removeEventListener("keydown", tus); return; }
      if (/^(INPUT|TEXTAREA|SELECT)$/.test((e.target.tagName || ""))) return;
      if (!R.offsetParent) return;  // sekme görünmüyorsa
      if (e.key === " " || e.key === "Enter") { e.preventDefault(); if (kuyruk.length) { cevir = !cevir; ciz(); } }
      else if (e.key === "1") cevapla("bilemedim");
      else if (e.key === "2") cevapla("zor");
      else if (e.key === "3") cevapla("kolay");
    };
    document.addEventListener("keydown", tus);
    ciz();
  }
  const KAYNAK = { kavram: "Kavram", formul: "Formül", banka: "Soru", hata: "Hata", ozet: "Özet" };

  // ================================================================ 3) SINAV SİMÜLASYONU
  async function simulasyon(el, ctx) {
    const R = kok(el, "cl-sim");
    let zamanlayici = null;
    const temizle = () => { clearInterval(zamanlayici); zamanlayici = null; };
    async function baslangic() {
      temizle();
      R.innerHTML = '<div class="cl-panel cl-muted">Hazırlanıyor…</div>';
      let k;
      try { k = await json(ctx, `/api/calis/simulasyon/kaynaklar?course_id=${encodeURIComponent(cid(ctx))}`); }
      catch (e) { R.innerHTML = bos("Sınav simülasyonu", esc(MESAJ(e))); return; }
      const sec = k.denemeler.map((d) => `<option value="d${d.index}">${esc(d.baslik)} (${d.soru_sayisi} soru)</option>`).join("") +
        (k.banka_soru ? `<option value="banka">Soru bankasından karışık (bankada ${k.banka_soru} soru var)</option>` : "");
      if (!sec) { R.innerHTML = bos("Sınav simülasyonu", "Bu derste henüz deneme sınavı ya da soru bankası yok. Ders paketi hazırlanınca burada görünür."); return; }
      const nSecenek = (m) => {
        const l = [10, 20, 30].filter((x) => x <= m);
        if (!l.length || (m < 30 && !l.includes(m))) l.push(m);
        const sec = l.includes(20) ? 20 : l[l.length - 1];
        return l.map((x) => `<option${x === sec ? " selected" : ""}>${x}</option>`).join("");
      };
      R.innerHTML = `<div class="cl-panel"><h3>⏱ Sınav simülasyonu</h3><p class="cl-muted">Gerçek sınav koşulu: süre işler, ipucu yok. Bitince puanın, konu bazında kaybın ve yanlışların Hatalarım defterine eklenir.</p>` +
        `<div class="cl-grid"><label class="cl-f"><span>Sınav</span><select data-k="kaynak">${sec}</select></label>` +
        `<label class="cl-f"><span>Süre</span><select data-k="sure"><option value="30">30 dk</option><option value="60">60 dk</option><option value="90" selected>90 dk</option><option value="120">120 dk</option><option value="0">Süre yok</option></select></label>` +
        `<label class="cl-f" data-k="nbox" style="display:none"><span>Soru sayısı</span><select data-k="n">${nSecenek(k.banka_soru)}</select></label></div>` +
        `<button class="cl-pri" data-k="basla">Sınavı başlat</button></div>`;
      const ks = R.querySelector('[data-k="kaynak"]');
      const nb = () => { R.querySelector('[data-k="nbox"]').style.display = ks.value === "banka" ? "" : "none"; };
      ks.onchange = nb; nb();
      R.querySelector('[data-k="basla"]').onclick = async (e) => {
        e.target.disabled = true;
        const q = ks.value === "banka" ? `kaynak=banka&n=${R.querySelector('[data-k="n"]').value}` : `kaynak=deneme&index=${ks.value.slice(1)}`;
        try {
          const s = await json(ctx, `/api/calis/simulasyon/sorular?course_id=${encodeURIComponent(cid(ctx))}&${q}`);
          sinav(s, +R.querySelector('[data-k="sure"]').value);
        } catch (err) { toast(ctx, MESAJ(err)); e.target.disabled = false; }
      };
    }

    function sinav(s, dk) {
      const bas = Date.now(), bitis = dk ? bas + dk * 60000 : 0;
      const Q = s.sorular;
      let metinSon = null, h = `<div class="cl-bar"><b>${esc(s.baslik)}</b><span class="cl-sp"></span><span class="cl-muted" data-k="say"></span><span class="cl-time" data-k="sure">${dk ? "" : "Süre yok"}</span><button class="cl-pri cl-sm" data-k="bitir">Sınavı bitir</button></div><div class="cl-panel">`;
      Q.forEach((q, i) => {
        if (q.metin && q.metin !== metinSon) { h += `<blockquote class="cl-muted" style="margin:10px 0;padding:8px 12px;border-left:3px solid var(--accent)">${tex(q.metin)}</blockquote>`; metinSon = q.metin; }
        h += `<div class="cl-sq" data-i="${i}"><div class="cl-row"><b>${i + 1}.</b><span class="cl-badge">${esc(q.bolum || (q.tur === "dy" ? "D/Y" : q.tur === "coktan" ? "Test" : "Klasik"))}</span></div><div style="margin:6px 0">${tex(q.soru)}</div>`;
        if (q.tur === "dy") h += ["D", "Y"].map((c) => `<label class="cl-opt"><input type="radio" name="q${i}" value="${c}"><span>${c === "D" ? "Doğru" : "Yanlış"}</span></label>`).join("");
        else if (q.tur === "coktan") h += q.siklar.map((c, j) => `<label class="cl-opt"><input type="radio" name="q${i}" value="${"ABCDE"[j]}"><span><b>${"ABCDE"[j]})</b> ${tex(c)}</span></label>`).join("");
        else h += `<textarea rows="4" placeholder="Cevabını yaz…" data-a="${i}"></textarea>`;
        h += "</div>";
      });
      R.innerHTML = h + "</div>";
      const sureEl = R.querySelector('[data-k="sure"]'), sayEl = R.querySelector('[data-k="say"]');
      const cevapli = () => Q.filter((q, i) => (q.tur === "acik" ? (R.querySelector(`[data-a="${i}"]`).value || "").trim() : R.querySelector(`input[name="q${i}"]:checked`))).length;
      const guncelle = () => {
        sayEl.textContent = `${cevapli()}/${Q.length} cevaplandı`;
        if (!bitis) return;
        const kalan = Math.max(0, Math.round((bitis - Date.now()) / 1000));
        sureEl.textContent = `${String(Math.floor(kalan / 60)).padStart(2, "0")}:${String(kalan % 60).padStart(2, "0")}`;
        sureEl.classList.toggle("low", kalan <= 300);
        if (kalan <= 0) { toast(ctx, "Süre doldu."); bitir(); }
      };
      R.addEventListener("input", guncelle);
      temizle(); zamanlayici = setInterval(() => { if (!R.isConnected) temizle(); else guncelle(); }, 1000);
      guncelle();
      let bittiMi = false;
      function bitir() {
        if (bittiMi) return; bittiMi = true; temizle();
        const cev = Q.map((q, i) => ({
          soru: q.soru, tur: q.tur, dogru: q.dogru || "", cevap_metni: q.cevap_metni || "", konu: q.konu || "", kaynak: q.kaynak || "",
          ogrenci: q.tur === "acik" ? (R.querySelector(`[data-a="${i}"]`).value || "").trim() : (R.querySelector(`input[name="q${i}"]:checked`) || {}).value || "",
        }));
        const sure_sn = Math.round((Date.now() - bas) / 1000);
        const acik = cev.map((c, i) => [c, i]).filter(([c]) => c.tur === "acik" && c.ogrenci);
        if (!acik.length) return gonder(cev, sure_sn, s.baslik);
        // açık uçlular: örnek cevapla karşılaştır, kendini puanla
        let h2 = `<div class="cl-panel"><h3>Açık uçlu cevaplarını puanla</h3><p class="cl-muted">Örnek cevapla karşılaştır; ne kadar doğru buldun?</p>`;
        acik.forEach(([c, i]) => {
          h2 += `<div class="cl-sq" data-i="${i}"><div>${tex(c.soru)}</div><div class="cl-ans bad"><b>Cevabın:</b> ${tex(c.ogrenci)}</div><div class="cl-ans good"><b>Örnek cevap:</b> ${tex(c.cevap_metni)}</div>` +
            `<div class="cl-row"><label class="cl-opt"><input type="radio" name="p${i}" value="1">Doğru</label><label class="cl-opt"><input type="radio" name="p${i}" value="0.5">Kısmen</label><label class="cl-opt"><input type="radio" name="p${i}" value="0" checked>Yanlış</label></div></div>`;
        });
        R.innerHTML = h2 + `<button class="cl-pri" data-k="tamam">Sonucu göster</button></div>`;
        R.querySelector('[data-k="tamam"]').onclick = () => {
          acik.forEach(([c, i]) => { c.puan = +R.querySelector(`input[name="p${i}"]:checked`).value; });
          gonder(cev, sure_sn, s.baslik);
        };
      }
      R.querySelector('[data-k="bitir"]').onclick = () => { if (cevapli() < Q.length && !confirm(`${Q.length - cevapli()} soru boş. Yine de bitirilsin mi?`)) return; bitir(); };
    }

    async function gonder(cev, sure_sn, baslik) {
      R.innerHTML = '<div class="cl-panel cl-muted">Puanlanıyor…</div>';
      let r;
      try { r = await json(ctx, "/api/calis/simulasyon/puanla", { course_id: cid(ctx), cevaplar: cev, sure_sn, baslik }); }
      catch (e) { R.innerHTML = bos("Sınav simülasyonu", esc(MESAJ(e))); return; }
      const mx = Math.max(1, ...r.konular.map((k) => k.kayip));
      R.innerHTML = `<div class="cl-panel" style="text-align:center"><div class="cl-score">${r.puan}</div><div class="cl-muted">/ 100 · ${Math.floor(sure_sn / 60)} dk ${sure_sn % 60} sn</div>` +
        `<div class="cl-row" style="justify-content:center;margin-top:10px"><span class="cl-badge">✔ ${r.dogru} doğru</span><span class="cl-badge t-kavram_yanilgisi">✘ ${r.yanlis} yanlış</span><span class="cl-badge">○ ${r.bos} boş</span></div></div>` +
        `<div class="cl-panel"><h4>Konu bazında kaybettiğin puan</h4>` +
        r.konular.map((k) => `<div class="cl-loss"><span>${esc(k.konu)}</span><div><i style="width:${Math.max(2, Math.round((100 * k.kayip) / mx))}%"></i></div><b>${k.kayip ? "−" + k.kayip : "0"}</b></div>`).join("") + `</div>` +
        `<div class="cl-panel"><p>${r.hata_eklendi ? `📒 ${r.hata_eklendi} soru Hatalarım defterine eklendi.` : "Hiç hata yok, harika!"}</p><div class="cl-row">` +
        (r.hata_eklendi ? `<button data-k="hatalar">Hatalarıma bak</button>` : "") + `<button class="cl-pri" data-k="yeni">Yeni sınav</button></div></div>`;
      if (r.hata_eklendi) window.dispatchEvent(new CustomEvent("calis:hata"));  // açık Kartlar/Hatalarım yeniden çizilsin
      R.querySelector('[data-k="yeni"]').onclick = baslangic;
      const hb = R.querySelector('[data-k="hatalar"]');
      if (hb) hb.onclick = () => hatalar(el, ctx);
    }
    return baslangic();
  }

  // ================================================================ 4) EXCEL / PYTHON ÇALIŞMA ALANI
  async function dosyaIste(arac, girdi, bicim, ctx) {
    const r = await fetch(`/api/calis/indir/${bicim}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ arac, girdi }) });
    if (!r.ok) { let m = r.statusText; try { m = (await r.json()).detail || m; } catch {} throw new Error(m); }
    dosyaIndir(await r.blob(), `${arac}.${bicim}`);
  }
  // Sohbette hesap aracı kullanıldığında arayüz bunu çağırabilir: indirme düğmeleri (DOM öğesi) döndürür
  function indirmeDugmeleri(arac, girdi, ctx) {
    if (!girdi || typeof girdi !== "object" || Array.isArray(girdi)) return null;  // sunucu girdi göndermediyse düğme gösterme
    stilVer();
    const d = document.createElement("div");
    d.className = "cl cl-row";
    d.innerHTML = `<button class="cl-sm" data-b="xlsx">📊 Excel olarak indir</button><button class="cl-sm" data-b="py">🐍 Python olarak indir</button>`;
    d.querySelectorAll("button").forEach((b) => (b.onclick = async () => {
      b.disabled = true;
      try { await dosyaIste(arac, girdi, b.dataset.b, ctx); } catch (e) { toast(ctx, MESAJ(e)); }
      b.disabled = false;
    }));
    return d;
  }

  const bosDeger = (v) => v === "" || v == null;
  function tipBul(s, defs) {
    if (!s) return { tip: "json" };
    if (s.$ref) return tipBul(defs[s.$ref.split("/").pop()], defs);
    if (s.anyOf) { const n = s.anyOf.filter((x) => x.type !== "null"); return { ...tipBul(n[0], defs), bos: true }; }
    if (s.enum) return { tip: "enum", enum: s.enum };
    if (s.type === "number" || s.type === "integer") return { tip: "sayi", tam: s.type === "integer" };
    if (s.type === "boolean") return { tip: "bool" };
    if (s.type === "string") return { tip: "metin" };
    if (s.type === "array") {
      const i = s.items && (s.items.$ref ? null : s.items);
      if (i && (i.type === "number" || i.type === "integer")) return { tip: "liste" };
      if (i && i.type === "array" && i.items && (i.items.type === "number" || i.items.type === "integer")) return { tip: "matris" };
      if (i && i.type === "string") return { tip: "metinListe" };
    }
    return { tip: "json" };
  }
  function degerYaz(inp, t, v) {
    if (v === undefined || v === null) { if (t.tip === "bool") inp.checked = false; else inp.value = ""; return; }
    if (t.tip === "bool") inp.checked = !!v;
    else if (t.tip === "liste" || t.tip === "metinListe") inp.value = v.join(", ");
    else if (t.tip === "matris") inp.value = v.map((r) => r.join(", ")).join("\n");
    else if (t.tip === "json") inp.value = JSON.stringify(v, null, 1);
    else inp.value = v;
  }
  // Türkçe ondalık virgül: ';' ya da satır sonu varsa onlarla (ve boşlukla) böl, virgül ondalıktır;
  // yoksa rakamlar arasındaki boşluksuz virgül ondalıktır ("12,5"), ", " ya da boşluk ayırıcıdır.
  function sayiParcala(v) {
    const m = String(v);
    if (/[;\n]/.test(m)) return m.split(/[;\n\s]+/).filter(Boolean);
    return m.replace(/(\d),(\d)/g, "$1.$2").split(/[\s,]+/).filter(Boolean);
  }
  function degerOku(inp, t, ad) {
    if (t.tip === "bool") return inp.checked;
    const v = inp.value.trim();
    if (v === "") return undefined;
    const sayi = (x) => { const n = Number(String(x).replace(",", ".")); if (!isFinite(n)) throw new Error(`“${ad}” alanında geçersiz sayı: ${x}`); return n; };
    if (t.tip === "sayi") return sayi(v);
    if (t.tip === "liste") return sayiParcala(v).map(sayi);
    if (t.tip === "metinListe") return v.split(/\s*,\s*/).filter(Boolean);
    if (t.tip === "matris") return v.split(/\n/).map((r) => r.trim()).filter(Boolean).map((r) => sayiParcala(r).map(sayi));
    if (t.tip === "json") { try { return JSON.parse(v); } catch { throw new Error(`“${ad}” alanı geçerli JSON olmalı`); } }
    return v;
  }
  const bicimSayi = (v) => (typeof v === "number" ? String(Math.round(v * 1e6) / 1e6) : Array.isArray(v) || (v && typeof v === "object") ? JSON.stringify(v) : String(v));

  async function calismaAlani(el, ctx) {
    const R = kok(el, "cl-alan");
    R.innerHTML = '<div class="cl-panel cl-muted">Araçlar yükleniyor…</div>';
    let araclar;
    try { araclar = (await json(ctx, "/api/calis/hesap/araclar")).araclar; } catch (e) { R.innerHTML = bos("Hesap alanı", esc(MESAJ(e))); return; }
    R.innerHTML = `<div class="cl-panel"><h3>🧮 Excel / Python çalışma alanı</h3><label class="cl-f"><span>Araç</span><select data-k="arac">${araclar.map((a) => `<option value="${a.ad}">${esc(a.aciklama)}</option>`).join("")}</select></label>` +
      `<div data-k="form"></div><div class="cl-row"><button class="cl-pri" data-k="coz">Çöz</button><button class="cl-ghost" data-k="ornek">Örnek yükle</button></div></div><div data-k="sonuc"></div>`;
    const sel = R.querySelector('[data-k="arac"]'), form = R.querySelector('[data-k="form"]'), sonuc = R.querySelector('[data-k="sonuc"]');
    let alanlar = [], arac;
    function formKur() {
      arac = araclar.find((a) => a.ad === sel.value);
      const defs = arac.sema.$defs || {};
      alanlar = Object.entries(arac.sema.properties || {}).map(([ad, s]) => {
        const t = tipBul(s, defs);
        const wrap = document.createElement("label");
        wrap.className = "cl-f";
        const ipucu = { liste: "3; 5; 2,5", matris: "her satır bir satır: 1; 2; 3,5", metinListe: "virgülle ayır", json: "JSON", sayi: "" }[t.tip] || "";
        wrap.innerHTML = `<span>${esc(s.title && s.title !== ad ? s.title : ad)}</span>`;
        let inp;
        if (t.tip === "enum") { inp = document.createElement("select"); inp.innerHTML = t.enum.map((x) => `<option>${esc(x)}</option>`).join(""); }
        else if (t.tip === "bool") { inp = document.createElement("input"); inp.type = "checkbox"; inp.style.width = "auto"; }
        else if (t.tip === "matris" || t.tip === "json") { inp = document.createElement("textarea"); inp.rows = t.tip === "json" ? 6 : 4; inp.spellcheck = false; }
        else { inp = document.createElement("input"); inp.type = t.tip === "sayi" ? "number" : "text"; if (t.tip === "sayi") inp.step = "any"; }
        if (ipucu && inp.placeholder !== undefined) inp.placeholder = ipucu;
        wrap.appendChild(inp);
        if (t.tip === "liste" || t.tip === "matris") { const d = document.createElement("small"); d.className = "cl-muted"; d.textContent = "Ondalık için virgül, ayırıcı olarak boşluk ya da ; kullan"; wrap.appendChild(d); }
        if (s.description) { const d = document.createElement("small"); d.className = "cl-muted"; d.textContent = s.description; wrap.appendChild(d); }
        form.appendChild(wrap);
        return { ad, t, inp, s };
      });
      form.innerHTML = "";
      alanlar.forEach((a) => form.appendChild(a.inp.parentElement));
      form.className = "cl-grid";
      doldur(arac.ornek || {});
      sonuc.innerHTML = "";
    }
    function doldur(o) {
      alanlar.forEach((a) => degerYaz(a.inp, a.t, o[a.ad] !== undefined ? o[a.ad] : a.s.default));
    }
    function girdiOku() {
      const g = {};
      alanlar.forEach((a) => { const v = degerOku(a.inp, a.t, a.ad); if (v !== undefined) g[a.ad] = v; });
      return g;
    }
    sel.onchange = formKur;
    R.querySelector('[data-k="ornek"]').onclick = () => doldur(arac.ornek || {});
    R.querySelector('[data-k="coz"]').onclick = async (e) => {
      let g;
      try { g = girdiOku(); } catch (err) { return toast(ctx, MESAJ(err)); }
      e.target.disabled = true;
      sonuc.innerHTML = '<div class="cl-panel cl-muted">Çözülüyor…</div>';
      try {
        const r = await json(ctx, "/api/calis/hesap", { arac: arac.ad, girdi: g });
        sonuc.innerHTML = `<div class="cl-panel"><h4>${esc(r.baslik)}</h4><table class="cl-t">${Object.entries(r.sayilar).map(([k, v]) => `<tr><td>${esc(k)}</td><td>${esc(bicimSayi(v))}</td></tr>`).join("")}</table></div>` +
          `<div class="cl-panel"><h4>Adımlar</h4><ol class="cl-steps">${r.adimlar.map((a) => `<li>${esc(a)}</li>`).join("")}</ol></div><div class="cl-panel" data-k="dl"><h4>Dosya olarak al</h4></div>`;
        const dl = indirmeDugmeleri(arac.ad, g, ctx);
        dl.classList.remove("cl");
        sonuc.querySelector('[data-k="dl"]').appendChild(dl);
        const not = document.createElement("p");
        not.className = "cl-muted";
        not.textContent = (arac.excel ? "Excel: girdiler + formüllü model sayfası" + (/programlama|ulastirma|atama/.test(arac.ad) ? " (Solver'a hazır, kısa yönergeyle)" : "") : "Excel: girdiler ve sonuç sayfaları")
          + ". " + (arac.python ? "Python: yorumlu, çalıştırılabilir çözüm (numpy/scipy)." : "Python: girdiler + beklenen sonuç içeren şablon.");
        sonuc.querySelector('[data-k="dl"]').appendChild(not);
      } catch (err) { sonuc.innerHTML = `<div class="cl-panel"><b>Çözülemedi:</b> ${esc(MESAJ(err))}</div>`; }
      e.target.disabled = false;
    };
    formKur();
  }

  // ================================================================ 5) DERS SONRASI ÖZET KARTI
  async function ozetKarti(el, ctx) {
    const R = kok(el, "cl-ozetkart");
    R.innerHTML = '<div class="cl-panel cl-muted">Özet kartı hazırlanıyor…</div>';
    let sid = ctx && (ctx.sessionId || ctx.session_id || ctx.sid);
    const sig = ctx && ctx.signal ? { signal: ctx.signal } : undefined;
    const iptal = () => !!(sig && sig.signal.aborted);
    try {
      if (!sid) {  // oturum verilmediyse bu dersin en son kaydı
        const l = await json(ctx, "/api/sessions", undefined, sig);
        const m = l.find((s) => !cid(ctx) || s.course_id === cid(ctx)) || l[0];
        sid = m && m.id;
      }
      if (!sid) throw new Error("Henüz kayıtlı bir anlatım yok.");
    } catch (e) { if (iptal()) return; R.innerHTML = bos("Özet kartı", esc(MESAJ(e))); return; }
    let k;
    try { k = await json(ctx, "/api/calis/ozet-karti", { session_id: sid }, sig); } catch (e) { if (iptal()) return; R.innerHTML = bos("Özet kartı", esc(MESAJ(e))); return; }
    if (iptal()) return;
    R.innerHTML = `<div class="cl-panel cl-ozet cl-print-target"><div class="cl-row"><span class="cl-badge">📝 Ders özeti</span><span class="cl-muted">${k.kaynak === "yapay_zeka" ? "" : "(otomatik, tahtadan)"}</span></div><h3>${esc(k.baslik)}</h3>` +
      (k.anahtar_kavramlar.length ? `<div class="cl-chips">${k.anahtar_kavramlar.map((c) => `<span class="cl-badge">${esc(c)}</span>`).join("")}</div>` : "") +
      (k.formuller.length ? `<h4>Formüller</h4>${k.formuller.map((f) => tex("$$" + f + "$$")).join("")}` : "") +
      (k.ozet_maddeleri.length ? `<h4>Özet</h4><ul>${k.ozet_maddeleri.map((m) => `<li>${tex(m)}</li>`).join("")}</ul>` : "") +
      (k.kontrol_sorusu ? `<h4>Kendini kontrol et</h4><div>${tex(k.kontrol_sorusu)}</div><details style="margin-top:6px"><summary class="cl-muted">Cevabı göster</summary><div class="cl-ans good">${tex(k.cevap)}</div></details>` : "") +
      `<div class="cl-row" style="margin-top:12px"><button class="cl-sm" data-k="pdf">🖨 PDF indir</button><button class="cl-sm" data-k="deste">🃏 Kart destesine ekle</button></div></div>`;
    const kart = R.querySelector(".cl-print-target");
    R.querySelector('[data-k="pdf"]').onclick = () => {  // tarayıcının yazdırma penceresi: "PDF olarak kaydet"
      const kapat = () => { document.documentElement.classList.remove("cl-printing"); window.removeEventListener("afterprint", kapat); };
      document.documentElement.classList.add("cl-printing");
      window.addEventListener("afterprint", kapat);
      window.print();
      setTimeout(kapat, 1500);
    };
    R.querySelector('[data-k="deste"]').onclick = async (e) => {
      const kartlar = [];
      if (k.kontrol_sorusu && k.cevap) kartlar.push({ on: k.kontrol_sorusu, arka: k.cevap, konu: k.baslik });
      k.formuller.forEach((f) => kartlar.push({ on: `Formül (${k.baslik})`, arka: "$$" + f + "$$", konu: k.baslik }));
      k.ozet_maddeleri.slice(0, 3).forEach((m) => kartlar.push({ on: `${k.baslik}: bir önemli nokta söyle`, arka: m, konu: k.baslik }));
      e.target.disabled = true;
      try {
        const r = await json(ctx, "/api/calis/kartlar/ekle", { course_id: k.course_id || cid(ctx), kartlar });
        toast(ctx, r.eklenen ? `${r.eklenen} kart desteye eklendi.` : "Bu kartlar zaten destede.");
      } catch (err) { toast(ctx, MESAJ(err)); e.target.disabled = false; }
    };
  }

  // ================================================================ ana sayfa özeti
  async function ozetVerisi(ctx) { return json(ctx, `/api/calis/ozet?course_id=${encodeURIComponent(cid(ctx))}`); }
  async function ozet(el, ctx) {
    const R = kok(el, "cl-ozet-mini");
    let v;
    try { v = await ozetVerisi(ctx); } catch { R.innerHTML = ""; return; }
    const sim = v.son_simulasyon;
    R.innerHTML = `<div class="cl-panel"><h4>Çalış</h4><div class="cl-row">` +
      `<button class="cl-sm" data-g="kartlar">🃏 Bugün ${v.bugun_tekrar_kart} kart</button><button class="cl-sm" data-g="hatalar">📒 ${v.hata_sayisi} hata</button>` +
      (sim ? `<span class="cl-muted">Son simülasyon: ${sim.puan}</span>` : "") + `</div>` +
      (v.en_cok_hata_konu ? `<p class="cl-muted" style="margin:6px 0 0">En çok hata: ${esc(v.en_cok_hata_konu)}</p>` : "") + `</div>`;
    R.querySelectorAll("[data-g]").forEach((b) => (b.onclick = () => window.dispatchEvent(new CustomEvent("calis:git", { detail: { hedef: b.dataset.g } }))));
  }

  window.Calis = { kartlar, hatalar, simulasyon, ozetKarti, calismaAlani, indirmeDugmeleri, ozet, ozetVerisi };
})();
