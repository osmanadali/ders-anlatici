/* Arayüz katmanı: sekme yapısı (Ana sayfa / Ders / Çalış / Kaynaklar / Plan), ana sayfa, alttan açılan panel (telefon),
   odak modu + pomodoro, yürürken ders (ekransız), tahta menüsü ve "Tahtaya yaz" çizim katmanı.
   app.js içindeki mantığa window.DersCore üzerinden bağlanır; app.js da window.DersUI'yı çağırır. */
(function () {
  const C = window.DersCore;
  if (!C) { console.warn("DersCore yok: arayuz.js devre dışı"); return; }
  const { S, $, api, toast, ask, ctx, player, board } = C;
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const lget = C.localGet, lset = C.localSet;
  const mobilMQ = matchMedia("(max-width: 900px), (max-height: 500px) and (orientation: landscape)");
  const landscape = () => innerWidth > innerHeight;

  // ================================================================ sekmeler
  const TOP = {
    home: { subs: [] },
    ders: { subs: [["chat", "Sohbet"], ["lecture", "Ders anlat"], ["proje", "Proje & Hayat"]] },
    calis: { subs: [["quiz", "Sınav"], ["kartlar", "Kartlar"], ["hatalar", "Hatalarım"], ["sim", "Simülasyon"], ["erp", "Alıştırma"]] },
    kaynak: { subs: [["notes", "Notlar"], ["library", "Kütüphane"], ["records", "Kayıtlar"]] },
    plan: { subs: [] },
  };
  const ALIAS = { alistirma: "erp", "calisma-alani": "erp", takvim: "plan", ana: "home" };
  const lastSub = { ders: "chat", calis: "quiz", kaynak: "notes" };
  const state = { top: "home", sub: "home" };

  function resolve(name) {
    name = ALIAS[name] || name;
    if (name === "home" || name === "plan") return { top: name, sub: name };
    if (TOP[name]) return { top: name, sub: lastSub[name] };
    for (const [t, d] of Object.entries(TOP)) if (d.subs.some(([k]) => k === name)) return { top: t, sub: name };
    return { top: "ders", sub: "chat" };
  }

  // Modüllerin (Calis / Guncel) çizeceği kapsayıcılar
  const MOD = {
    kartlar: [["calisKartlar", "Calis", "kartlar"]],
    hatalar: [["calisHatalar", "Calis", "hatalar"]],
    sim: [["calisSimulasyon", "Calis", "simulasyon"]],
    erp: [["calisAlani", "Calis", "calismaAlani"]],
    proje: [["guncelBitirme", "Guncel", "bitirme"], ["guncelGunluk", "Guncel", "gunlukHayat"]],
  };
  let filled = {};
  function moduleFill(sub) {
    (MOD[sub] || []).forEach(([elId, mod, fn]) => {
      const el = document.getElementById(elId), f = window[mod]?.[fn];
      if (!el) return;
      if (typeof f !== "function") {
        if (!el.childNodes.length || el.dataset.yok) { el.dataset.yok = "1"; el.innerHTML = '<p class="muted mod-yok">Bu bölüm henüz hazır değil.</p>'; }
        return;
      }
      if (filled[elId] === (S.courseId || "-")) return;
      filled[elId] = S.courseId || "-";
      el.innerHTML = ""; delete el.dataset.yok;
      try { Promise.resolve(f.call(window[mod], el, ctx)).catch((e) => console.warn(mod + "." + fn, e)); }
      catch (e) { console.warn(mod + "." + fn, e); }
    });
  }

  function renderSubs() {
    const nav = $("#subTabs"), subs = TOP[state.top].subs;
    nav.classList.toggle("hidden", !subs.length);
    nav.innerHTML = "";
    subs.forEach(([k, label]) => {
      const b = document.createElement("button");
      b.type = "button"; b.dataset.tab = k; b.textContent = label;
      b.onclick = () => { C.switchTab(k); sheet.aç(); };
      nav.appendChild(b);
    });
  }
  function show(name) {
    const r = resolve(name);
    if (r.top !== state.top) { state.top = r.top; renderSubs(); }
    state.sub = r.sub;
    if (lastSub[r.top]) lastSub[r.top] = r.sub;
    $$("#topTabs button").forEach((b) => b.classList.toggle("active", b.dataset.top === r.top));
    $$("#subTabs button").forEach((b) => b.classList.toggle("active", b.dataset.tab === r.sub));
    $$(".tab-panel").forEach((p) => p.classList.toggle("active", p.id === "tab-" + r.sub));
    $("#subTabs button.active")?.scrollIntoView({ block: "nearest", inline: "center" });
    if (r.sub === "home") homeYenile();
    moduleFill(r.sub);
    return r.sub;
  }
  $$("#topTabs button").forEach((b) => (b.onclick = () => { C.switchTab(b.dataset.top); sheet.aç(); }));

  // ================================================================ ana sayfa
  function selam() {
    const h = new Date().getHours();
    return h < 5 ? "İyi geceler" : h < 12 ? "Günaydın" : h < 18 ? "İyi günler" : "İyi akşamlar";
  }
  function zamanGoreli(ts) { return C.goreli ? C.goreli(ts) : new Date(ts * 1000).toLocaleString("tr-TR"); }
  async function homeYenile() {
    $("#homeHi").textContent = selam() + (S.course ? ` — ${S.course.name}` : "");
    $("#homeDate").textContent = new Date().toLocaleDateString("tr-TR", { weekday: "long", day: "numeric", month: "long", year: "numeric" });
    // kaldığın yerden devam: en son kayıt
    const dv = $("#homeDevam");
    api("/api/sessions").then((rows) => {
      const r = rows && rows[0];
      if (!r) {
        dv.innerHTML = '<span class="h-ic">✨</span><span class="h-t"><b>Hadi başlayalım</b><small class="muted">Henüz kayıt yok: bir soru sor ya da notunu ekle.</small></span>';
        dv.onclick = () => C.switchTab("chat");
        return;
      }
      const course = (S.courses || []).find((c) => c.id === r.course_id);
      dv.innerHTML = `<span class="h-ic">▶</span><span class="h-t"><b>Kaldığın yerden devam</b><span class="h-baslik"></span><small class="muted"></small></span>`;
      dv.querySelector(".h-baslik").textContent = r.title || "Adsız anlatım";
      dv.querySelector("small").textContent = `${new Date(r.updated * 1000).toLocaleString("tr-TR", { dateStyle: "medium", timeStyle: "short" })} · ${r.steps} adım${course ? " · " + course.name : ""}`;
      dv.onclick = () => C.openRecord(r.id, true);
    }).catch(() => { dv.onclick = null; });
    // bugünkü görevler + yaklaşan sınavlar
    try {
      const td = await api(`/api/today?day=${C.localDate()}`);
      const box = $("#homeBugun");
      box.innerHTML = "";
      if (!td.tasks.length) box.innerHTML = '<p class="muted small">Bugün için görev yok. Plan sekmesinden bir sınav takvimi oluştur.</p>';
      td.tasks.slice(0, 6).forEach((t) => box.appendChild(C.taskEl(t, t.course_id, t.course, t.done)));
      if (td.tasks.length > 6) box.insertAdjacentHTML("beforeend", `<button type="button" class="ghost small" data-git="plan">+${td.tasks.length - 6} görev daha…</button>`);
      const sx = $("#homeSinav");
      if (!td.exams.length) sx.textContent = "Kayıtlı sınav yok.";
      else sx.innerHTML = td.exams.slice(0, 5).map((e) => {
        const left = Math.round((new Date(e.exam_date) - new Date(C.localDate())) / 864e5);
        return `<div class="sinav-satir ${left <= 7 ? "yakin" : ""}"><span>${esc(e.course)} <i>${esc(e.exam_type)}</i></span><b>${left === 0 ? "BUGÜN" : left + " gün"}</b></div>`;
      }).join("");
    } catch (e) { $("#homeBugun").innerHTML = `<p class="muted small">${esc(e.message)}</p>`; }
    homeModuller();
  }
  let homeGen = "";
  function homeModuller() {
    const key = (S.courseId || "-") + "|" + (window.Guncel ? 1 : 0) + (window.Calis ? 1 : 0);
    if (homeGen === key) return;
    homeGen = key;
    const kart = (karId, elId, mod, fn) => {
      const k = document.getElementById(karId), el = document.getElementById(elId);
      const f = window[mod]?.[fn];
      k.classList.toggle("hidden", typeof f !== "function");
      if (typeof f !== "function") return;
      el.innerHTML = "";
      const bos = () => { if (!el.childNodes.length) k.classList.add("hidden"); };
      try { Promise.resolve(f.call(window[mod], el, ctx)).then(bos, bos); } catch (e) { k.classList.add("hidden"); }
    };
    kart("homeKavramKart", "homeKavram", "Guncel", "gununKavrami");
    kart("homeBultenKart", "homeBulten", "Guncel", "bulten");
    const ck = $("#homeCalisKart");
    ck.classList.toggle("hidden", !window.Calis);
    if (window.Calis) {
      const el = $("#homeCalis");
      el.innerHTML = "";
      if (typeof window.Calis.ozet === "function") { try { window.Calis.ozet(el, ctx); } catch {} }
      else el.innerHTML = '<p class="muted small">Tekrar kartların ve hata defterin burada seni bekliyor.</p>';
    }
  }
  document.addEventListener("click", (e) => {
    const g = e.target.closest("[data-git]");
    if (g) { C.switchTab(g.dataset.git); sheet.aç(); }
  });
  $("#homeQuick").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-q]");
    if (!b) return;
    ({ not: () => $("#autoInput").click(), konus: () => $("#convBtn").click(), yuru: () => walk.baslat(), odak: () => odak.ac() })[b.dataset.q]?.();
  });

  // ================================================================ ⋯ menüsü
  const more = { btn: $("#moreBtn"), menu: $("#moreMenu") };
  function moreKapat() { more.menu.classList.add("hidden"); more.btn.setAttribute("aria-expanded", "false"); }
  more.btn.onclick = (e) => {
    e.stopPropagation();
    const ac = more.menu.classList.toggle("hidden") === false;
    more.btn.setAttribute("aria-expanded", String(ac));
  };
  more.menu.addEventListener("click", (e) => {
    const t = e.target.closest("[data-tikla]");
    if (t) document.getElementById(t.dataset.tikla)?.click();
    setTimeout(moreKapat, 60);
  });
  document.addEventListener("click", (e) => { if (!e.target.closest(".more-wrap")) moreKapat(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") moreKapat(); });

  // ================================================================ alttan açılan panel (telefon)
  const side = $(".side");
  const sheet = {
    durum: "yarim", surukleme: null,
    peek() { return 78; },
    yarim() { return Math.round(innerHeight * (landscape() ? 0.62 : 0.5)); },
    tam() { return Math.max(200, innerHeight - (($(".topbar")?.offsetHeight) || 56) - 6); },
    yukseklik(d) { return d === "kapali" ? this.peek() : d === "yarim" ? this.yarim() : this.tam(); },
    uygula(h, anim = true) {
      side.style.transition = anim ? "" : "none";
      side.style.height = h + "px";
      // dikey telefonda tahta panelin üstünde kalır; yatayda panel tahtanın üstüne biner
      const rez = landscape() ? 0 : Math.min(h, Math.max(this.peek(), this.yarim()));
      document.documentElement.style.setProperty("--rezerv", rez + "px");
      document.documentElement.style.setProperty("--sheet-h", h + "px");
    },
    ayarla(d, anim = true) {
      this.durum = d; side.dataset.sheet = d;
      this.uygula(this.yukseklik(d), anim);
    },
    aç() { if (mobilMQ.matches && this.durum === "kapali") this.ayarla("yarim"); },
    ilk() {
      if (mobilMQ.matches) { side.classList.add("sheet"); this.ayarla(landscape() ? "kapali" : "yarim", false); }
      else { side.classList.remove("sheet"); side.style.height = ""; side.style.transition = ""; delete side.dataset.sheet;
        document.documentElement.style.removeProperty("--rezerv"); document.documentElement.style.removeProperty("--sheet-h"); }
    },
  };
  (function bindSheet() {
    const h = $("#sheetHandle");
    let sy = 0, sh = 0, moved = false, vy = 0, ly = 0, lt = 0;
    h.addEventListener("pointerdown", (e) => {
      if (!mobilMQ.matches) return;
      h.setPointerCapture(e.pointerId);
      sy = ly = e.clientY; sh = side.offsetHeight; moved = false; vy = 0; lt = e.timeStamp; sheet.surukleme = true;
    });
    h.addEventListener("pointermove", (e) => {
      if (!sheet.surukleme) return;
      const dy = e.clientY - sy;
      if (Math.abs(dy) > 5) moved = true;
      const dt = Math.max(1, e.timeStamp - lt); vy = (e.clientY - ly) / dt; ly = e.clientY; lt = e.timeStamp;
      if (moved) sheet.uygula(Math.max(sheet.peek(), Math.min(sheet.tam(), sh - dy)), false);
    });
    const bitir = (e) => {
      if (!sheet.surukleme) return;
      sheet.surukleme = null;
      if (!moved) { sheet.ayarla(sheet.durum === "kapali" ? "yarim" : sheet.durum === "tam" ? "yarim" : "kapali"); return; }
      let hh = side.offsetHeight - vy * 120;  // hızlı sürüklemede yöne doğru fırlat
      const adaylar = ["kapali", "yarim", "tam"].map((d) => [d, Math.abs(sheet.yukseklik(d) - hh)]);
      adaylar.sort((a, b) => a[1] - b[1]);
      sheet.ayarla(adaylar[0][0]);
    };
    h.addEventListener("pointerup", bitir);
    h.addEventListener("pointercancel", bitir);
    h.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); h.click?.(); } });
    mobilMQ.addEventListener("change", () => { sheet.ilk(); window.dispatchEvent(new Event("resize")); });
    let ro = 0;
    addEventListener("resize", () => { clearTimeout(ro); ro = setTimeout(() => { if (mobilMQ.matches && !sheet.surukleme) sheet.ayarla(sheet.durum, false); }, 80); });
    addEventListener("orientationchange", () => setTimeout(() => { sheet.ilk(); window.dispatchEvent(new Event("resize")); }, 200));
  })();

  // ================================================================ odak modu + pomodoro
  const ODAK_SN = 25 * 60, MOLA_SN = 5 * 60;
  const odak = {
    acik: false, faz: "odak", bitis: 0, kalan: ODAK_SN, durdu: false, zaman: null,
    kaydet() { lset("odakZ", JSON.stringify({ faz: this.faz, bitis: this.bitis, kalan: this.kalan, durdu: this.durdu })); },
    ac(devam) {
      this.acik = true; lset("odak", "1");
      document.body.classList.add("odak");
      $("#odakHalka").classList.remove("hidden"); $("#odakCik").classList.remove("hidden");
      $("#focusBtn").classList.add("on");
      if (!devam) this.baslatFaz("odak");
      else {
        try { const z = JSON.parse(lget("odakZ") || "null"); if (z) { Object.assign(this, { faz: z.faz, bitis: z.bitis, kalan: z.kalan, durdu: z.durdu }); } else this.baslatFaz("odak"); }
        catch { this.baslatFaz("odak"); }
      }
      clearInterval(this.zaman); this.zaman = setInterval(() => this.tik(), 500); this.tik();
      setTimeout(() => window.dispatchEvent(new Event("resize")), 120);
      if (!devam) toast("Odak modu: 25 dakikalık tur başladı. Çıkmak için Esc.", 3500);
    },
    kapat() {
      if (!this.acik) return;
      this.acik = false; lset("odak", "0"); lset("odakZ", "");
      clearInterval(this.zaman);
      document.body.classList.remove("odak");
      $("#odakHalka").classList.add("hidden"); $("#odakCik").classList.add("hidden"); $("#odakMola").classList.add("hidden");
      $("#focusBtn").classList.remove("on");
      setTimeout(() => window.dispatchEvent(new Event("resize")), 120);
    },
    baslatFaz(f) {
      this.faz = f; this.durdu = false;
      this.kalan = f === "odak" ? ODAK_SN : MOLA_SN;
      this.bitis = Date.now() + this.kalan * 1000;
      $("#odakMola").classList.add("hidden");
      this.kaydet();
    },
    kalanSn() { return this.durdu ? this.kalan : Math.max(0, Math.round((this.bitis - Date.now()) / 1000)); },
    tik() {
      const k = this.kalanSn(), top = this.faz === "odak" ? ODAK_SN : MOLA_SN;
      $("#odakSure").textContent = `${String(Math.floor(k / 60)).padStart(2, "0")}:${String(k % 60).padStart(2, "0")}`;
      $("#odakFaz").textContent = this.durdu ? "duraklatıldı" : this.faz === "odak" ? "odak" : "mola";
      $("#odakHalka").dataset.faz = this.faz;
      $("#odakHalka").querySelector(".r1").style.strokeDashoffset = String(100 - (k / top) * 100);
      if (!this.durdu && k <= 0 && !this.bildirildi) { this.bildirildi = true; this.bitti(); }
      if (k > 0) this.bildirildi = false;
    },
    bitti() {
      window.Sesler?.zil();
      const m = $("#odakMola");
      m.classList.remove("hidden");
      if (this.faz === "odak") {
        m.innerHTML = '<b>🎉 25 dakika odak tamam!</b><span>Kısa bir mola iyi gelir: kalk, su iç, gözlerini dinlendir.</span><div class="row"><button type="button" class="primary small" data-o="mola">☕ 5 dk mola</button><button type="button" class="ghost small" data-o="devam">Devam et</button><button type="button" class="ghost small" data-o="bitir">Bitir</button></div>';
        toast("Pomodoro bitti: 5 dakika mola öneriyorum.", 6000);
      } else {
        m.innerHTML = '<b>⏰ Mola bitti</b><span>Hazırsan yeni bir odak turu başlatalım.</span><div class="row"><button type="button" class="primary small" data-o="devam">🎯 Yeni tur</button><button type="button" class="ghost small" data-o="bitir">Bitir</button></div>';
        toast("Mola bitti.", 4000);
      }
    },
    durdurDevam() {
      if (this.durdu) { this.durdu = false; this.bitis = Date.now() + this.kalan * 1000; }
      else { this.kalan = this.kalanSn(); this.durdu = true; }
      this.kaydet(); this.tik();
    },
  };
  $("#odakMola").addEventListener("click", (e) => {
    const o = e.target.closest("[data-o]")?.dataset.o;
    if (o === "mola") odak.baslatFaz("mola"); else if (o === "devam") odak.baslatFaz("odak"); else if (o === "bitir") odak.kapat();
    odak.tik();
  });
  $("#odakHalka").onclick = () => odak.durdurDevam();
  $("#odakCik").onclick = () => odak.kapat();
  $("#focusBtn").onclick = () => (odak.acik ? odak.kapat() : odak.ac());

  // ================================================================ yürürken ders (ekransız)
  const walk = {
    acik: false, konusmayiBiz: false, zaman: null,
    async baslat() {
      if (this.acik) return;
      if (odak.acik) odak.kapat();
      if (drawing.acik) drawing.kapat();
      this.acik = true; S.walk = true;
      document.body.classList.add("yuru");
      $("#yuruyus").classList.remove("hidden");
      window.Sesler?.sustur(true);
      C.teacher?.unlock?.();
      this.medya(true);
      this.yenile();
      this.zaman = setInterval(() => this.yenile(), 400);
      if (!S.conv) {
        this.konusmayiBiz = true;
        try { await C.toggleConversation(); } catch {}
        if (!S.conv) { this.konusmayiBiz = false; toast("Mikrofon açılamadı: soruları yazarak soramazsın ama anlatımı dinleyebilirsin.", 6000); }
      }
      if (!player.busy && !S.streamOpen) {
        const hi = `Yürüyüşe çıkıyoruz. ${S.course ? S.course.name + " dersinden" : "Bir konudan"} başlayalım mı? Ne anlatmamı istersin?`;
        player.enqueue({ say: hi, board: [], audio: S.settings?.tts_enabled === false ? null : "/api/tts?text=" + encodeURIComponent(hi) });
      }
    },
    bitir() {
      if (!this.acik) return;
      this.acik = false; S.walk = false;
      clearInterval(this.zaman);
      document.body.classList.remove("yuru");
      $("#yuruyus").classList.add("hidden");
      window.Sesler?.sustur(false);
      this.medya(false);
      if (this.konusmayiBiz && S.conv) C.toggleConversation();
      this.konusmayiBiz = false;
      S.stream?.abort(); player.stop();
    },
    yenile() {
      const d = $("#yuruDurum"), alt = $("#yuruAlt"), ply = $("#yuruOynat");
      let t, a = "İstediğin an konuşarak sözümü kesebilirsin.";
      if (player.state === "paused") { t = "Duraklatıldı"; a = "Devam etmek için dokun."; }
      else if (player.state === "playing") t = "Anlatıyorum…";
      else if (S.streamOpen) t = "Düşünüyorum…";
      else if (S.conv) t = "Seni dinliyorum…";
      else { t = "Hazır"; a = "Mikrofon kapalı: “Soru sor” ile yazarak sorabilirsin."; }
      if (d.textContent !== t) d.textContent = t;
      alt.textContent = a;
      const dur = player.state === "paused";
      ply.innerHTML = dur ? "▶<span>Devam</span>" : "⏸<span>Durdur</span>";
      ply.disabled = !player.busy;
      d.dataset.durum = player.state;
    },
    medya(on) {
      const ms = navigator.mediaSession;
      if (!ms) return;
      try {
        if (on) {
          ms.metadata = new MediaMetadata({ title: "Yürürken ders", artist: S.course?.name || "Ders Anlatıcı", album: "Ders Anlatıcı" });
          ms.setActionHandler("play", () => player.resume());
          ms.setActionHandler("pause", () => player.pause());
          ms.setActionHandler("stop", () => player.pause());
        } else {
          ["play", "pause", "stop"].forEach((k) => ms.setActionHandler(k, null));
          ms.metadata = null; ms.playbackState = "none";
        }
      } catch {}
    },
  };
  $("#walkBtn").onclick = () => walk.baslat();
  $("#yuruBitir").onclick = () => walk.bitir();
  $("#yuruOynat").onclick = () => { if (player.busy) player.toggle(); };
  $("#yuruSor").onclick = () => {
    if (player.state === "playing") player.pause();
    if (S.conv) { toast("Dinliyorum: sorunu söyle.", 2500); C.teacher?.setState?.("listening"); }
    else {
      const q = prompt("Sorunu yaz");
      if (q && q.trim()) ask({ text: q.trim() });
    }
  };

  // ================================================================ tahta: tıklayınca menü
  const menu = $("#tahtaMenu");
  function bolumMetni(item) {
    if (item.classList.contains("b-page-img")) return "[not sayfası görseli] " + (item.alt || "");
    if (item.querySelector(".b-svg")) {
      const t = $$("text", item).map((x) => x.textContent).join(" ").trim();
      return "[grafik/şekil]" + (t ? " " + t : "");
    }
    const c = item.cloneNode(true);
    c.querySelectorAll(".decor,.pen").forEach((x) => x.remove());
    let saf = null;
    c.querySelectorAll(".katex").forEach((k) => {
      const a = k.querySelector("annotation");
      const tex = a ? a.textContent : k.textContent;
      if (item.classList.contains("b-math") && c.querySelectorAll(".katex").length === 1) saf = tex;
      k.replaceWith(document.createTextNode("$" + tex + "$"));
    });
    const out = saf ?? c.textContent;
    return out.replace(/\s+/g, " ").trim().slice(0, 500);
  }
  function menuKapat() { menu.classList.add("hidden"); }
  $("#board").addEventListener("click", (e) => {
    if (drawing.acik) return;
    const it = e.target.closest(".b-item");
    if (!it) { menuKapat(); return; }
    const sel = String(getSelection() || "").trim();
    const metin = sel.length > 1 ? sel.slice(0, 500) : bolumMetni(it);
    if (!metin) return;
    const kisa = metin.length > 60 ? metin.slice(0, 57) + "…" : metin;
    menu.innerHTML = `<div class="tm-baslik"></div>
      <button type="button" data-k="acikla">💡 Bunu açıkla</button>
      <button type="button" data-k="ornek">🧪 Örnek ver</button>
      <button type="button" data-k="neden">❓ Neden?</button>`;
    menu.querySelector(".tm-baslik").textContent = kisa;
    menu.dataset.metin = metin; menu.dataset.kisa = kisa;
    menu.classList.remove("hidden");
    const w = menu.offsetWidth, h = menu.offsetHeight;
    menu.style.left = Math.max(8, Math.min(innerWidth - w - 8, e.clientX - w / 2)) + "px";
    menu.style.top = Math.max(8, Math.min(innerHeight - h - 8, e.clientY + 12)) + "px";
    e.stopPropagation();
  });
  menu.addEventListener("click", (e) => {
    const k = e.target.closest("button")?.dataset.k;
    if (!k) return;
    const m = menu.dataset.metin, kisa = menu.dataset.kisa;
    const fiil = { acikla: "açıkla", ornek: "için bir örnek ver", neden: "neden böyle olduğunu açıkla" }[k];
    const ik = { acikla: "💡 Açıkla", ornek: "🧪 Örnek", neden: "❓ Neden" }[k];
    menuKapat();
    ask({ text: `Tahtadaki şu kısmı ${fiil}: "${m}"`, label: `${ik}: ${kisa}` });
  });
  document.addEventListener("click", (e) => { if (!e.target.closest("#tahtaMenu") && !e.target.closest("#board .b-item")) menuKapat(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") menuKapat(); });

  // ================================================================ tahta: "Tahtaya yaz" çizim katmanı
  const RENKLER = [["#f4f2e8", "Beyaz"], ["#f2d675", "Sarı"], ["#f29a90", "Kırmızı"], ["#9cc8f2", "Mavi"], ["#a9dca5", "Yeşil"]];
  const drawing = {
    acik: false, arac: "kalem", renk: RENKLER[0][0], kalinlik: 3, cizgiler: [], cur: null, kok: null, canvas: null, g: null, ro: null,
    ac() {
      if (this.acik) return;
      if (walk.acik) return;
      const cls = document.querySelector(".classroom");
      const page = board.pages[board.view];
      const kok = document.createElement("div");
      kok.className = "cizim-sahne";
      kok.innerHTML = `<div class="cizim-zemin"><div class="cizim-arka"></div></div>
        <canvas class="cizim-kat"></canvas>
        <div class="cizim-bar" role="toolbar" aria-label="Çizim araçları">
          <button type="button" data-a="kalem" class="on" title="Kalem">✏️</button>
          <button type="button" data-a="silgi" title="Silgi">🧽</button>
          <span class="cz-renkler">${RENKLER.map(([c, n], i) => `<button type="button" data-r="${c}" class="cz-renk${i ? "" : " on"}" style="--rc:${c}" title="${n}" aria-label="${n}"></button>`).join("")}</span>
          <input type="range" min="2" max="12" value="3" class="cz-kalin" title="Kalınlık" aria-label="Kalınlık">
          <button type="button" data-a="geri" title="Geri al">↶</button>
          <button type="button" data-a="temizle" title="Hepsini sil">🗑</button>
          <button type="button" data-a="goster" class="primary small" title="Çözümü hocaya gönder">👩‍🏫 Hocaya göster</button>
          <button type="button" data-a="kapat" title="Çizimi kapat (Esc)">✕</button>
        </div>`;
      cls.appendChild(kok);
      this.kok = kok; this.canvas = $(".cizim-kat", kok); this.g = this.canvas.getContext("2d");
      if (page) {  // bağlam: tahtadaki yazıların düz bir kopyası (3B sınıfta bile hizalı kalır)
        const c = page.cloneNode(true);
        c.classList.remove("off"); c.querySelector(".pen")?.remove();
        c.querySelectorAll("[style]").forEach((x) => { x.style.clipPath = ""; });
        $(".cizim-arka", kok).appendChild(c);
      }
      kok.addEventListener("click", (e) => {
        const b = e.target.closest("button");
        if (!b) return;
        if (b.dataset.r) { this.renk = b.dataset.r; this.arac = "kalem"; }
        else if (b.dataset.a === "kalem" || b.dataset.a === "silgi") this.arac = b.dataset.a;
        else if (b.dataset.a === "geri") { this.cizgiler.pop(); this.ciz(); }
        else if (b.dataset.a === "temizle") { this.cizgiler = []; this.ciz(); }
        else if (b.dataset.a === "goster") return this.gonder();
        else if (b.dataset.a === "kapat") return this.kapat();
        $$("[data-a=kalem],[data-a=silgi]", kok).forEach((x) => x.classList.toggle("on", x.dataset.a === this.arac));
        $$(".cz-renk", kok).forEach((x) => x.classList.toggle("on", x.dataset.r === this.renk && this.arac === "kalem"));
      });
      $(".cz-kalin", kok).oninput = (e) => { this.kalinlik = Number(e.target.value); };
      const cv = this.canvas;
      const nokta = (e) => { const r = cv.getBoundingClientRect(); return [(e.clientX - r.left) / r.width, (e.clientY - r.top) / r.height, e.pressure || 0.5, e.pointerType]; };
      cv.addEventListener("pointerdown", (e) => {
        if (e.button > 0) return;
        e.preventDefault(); cv.setPointerCapture(e.pointerId);
        const [x, y, p] = nokta(e);
        this.cur = { arac: this.arac, renk: this.renk, kalinlik: this.kalinlik, pts: [[x, y, p]] };
        this.cizgiler.push(this.cur); this.ciz();
      });
      cv.addEventListener("pointermove", (e) => {
        if (!this.cur) return;
        e.preventDefault();
        const list = e.getCoalescedEvents ? e.getCoalescedEvents() : [e];
        (list.length ? list : [e]).forEach((ev) => { const [x, y, p] = nokta(ev); this.cur.pts.push([x, y, p]); });
        this.ciz();
      });
      const bit = () => { this.cur = null; };
      cv.addEventListener("pointerup", bit); cv.addEventListener("pointercancel", bit);
      this.ro = new ResizeObserver(() => this.boyutla()); this.ro.observe(kok);
      this.acik = true;
      $("#drawBtn").classList.add("on");
      document.body.classList.add("cizim-acik");
      this.boyutla();
    },
    boyutla() {
      const r = this.canvas.getBoundingClientRect(), dpr = Math.min(2, devicePixelRatio || 1);
      this.canvas.width = Math.max(1, Math.round(r.width * dpr)); this.canvas.height = Math.max(1, Math.round(r.height * dpr));
      this.ciz();
    },
    ciz(g = this.g, w = this.canvas.width, h = this.canvas.height) {
      g.clearRect(0, 0, w, h);
      g.lineCap = "round"; g.lineJoin = "round";
      const olcek = w / 900;
      for (const c of this.cizgiler) {
        g.globalCompositeOperation = c.arac === "silgi" ? "destination-out" : "source-over";
        g.strokeStyle = g.fillStyle = c.renk;
        const kal = c.kalinlik * olcek * (c.arac === "silgi" ? 5 : 1);
        if (c.pts.length === 1) { g.beginPath(); g.arc(c.pts[0][0] * w, c.pts[0][1] * h, kal / 2, 0, 7); g.fill(); continue; }
        for (let i = 1; i < c.pts.length; i++) {
          const a = c.pts[i - 1], b = c.pts[i];
          g.lineWidth = kal * (c.arac === "kalem" ? 0.6 + 0.8 * (b[2] || 0.5) : 1);
          g.beginPath(); g.moveTo(a[0] * w, a[1] * h); g.lineTo(b[0] * w, b[1] * h); g.stroke();
        }
      }
      g.globalCompositeOperation = "source-over";
    },
    async gonder() {
      if (!this.cizgiler.length) { toast("Önce tahtaya çözümünü yaz."); return; }
      const r = this.canvas.getBoundingClientRect();
      const w = Math.min(1400, Math.round(r.width * 2)), h = Math.round(w * r.height / r.width);
      const cv = document.createElement("canvas"); cv.width = w; cv.height = h;
      const g = cv.getContext("2d");
      g.fillStyle = "#24372f"; g.fillRect(0, 0, w, h);   // tahta rengi: beyaz tebeşir yazısı okunur kalsın
      const kat = document.createElement("canvas"); kat.width = w; kat.height = h;
      this.ciz(kat.getContext("2d"), w, h);
      g.drawImage(kat, 0, 0);
      const blob = await new Promise((res) => cv.toBlob(res, "image/png"));
      if (!blob) { toast("Çizim görüntüye çevrilemedi."); return; }
      const file = new File([blob], "tahta.png", { type: "image/png" });
      this.kapat();
      ask({ text: "Tahtaya yazdığım çözümü kontrol et", files: [file], label: "✏️ Tahtadaki çözümümü kontrol et" });
    },
    kapat() {
      if (!this.acik) return;
      this.acik = false; this.ro?.disconnect();
      this.kok?.remove(); this.kok = null; this.cur = null;
      $("#drawBtn").classList.remove("on");
      document.body.classList.remove("cizim-acik");
    },
  };
  $("#drawBtn").onclick = () => (drawing.acik ? drawing.kapat() : drawing.ac());
  // yeni anlatım / ders değişince eski çizimler silinsin
  $("#newSessionBtn").addEventListener("click", () => { drawing.cizgiler = []; drawing.kapat(); });

  // ================================================================ ortak klavye
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape" || e.defaultPrevented) return;
    if (document.querySelector("dialog[open]")) return;
    if (drawing.acik) { drawing.kapat(); return; }
    if (walk.acik) { walk.bitir(); return; }
    if (odak.acik) odak.kapat();
  });

  // ================================================================ dışa açılan API
  window.DersUI = {
    show, dersDegisti() {
      filled = {}; homeGen = "";
      if (state.sub === "home") homeYenile(); else moduleFill(state.sub);
    },
    oynatici(st) {
      try { if (walk.acik && navigator.mediaSession) navigator.mediaSession.playbackState = st === "playing" ? "playing" : st === "paused" ? "paused" : "none"; } catch {}
    },
    altyazi() {},
    odak, walk, sheet, drawing,
  };

  // ================================================================ başlangıç
  sheet.ilk();
  renderSubs();
  show("home");
  if (lget("odak") === "1") odak.ac(true);
  document.addEventListener("visibilitychange", () => { if (!document.hidden && odak.acik) odak.tik(); });
})();
