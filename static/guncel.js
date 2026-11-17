/* Güncel kal: haftalık bülten, günün kavramı, bitirme projesi danışmanı, günlük hayattan endüstri mühendisliği,
   Vikipedi bekçisi. window.Guncel = { bulten, gununKavrami, bitirme, gunlukHayat }; ctx = { courseId, course, api, postJSON, toast, ask } */
(function () {
  "use strict";

  var CSS = [
    ".gn{--gn-r:var(--radius,18px);font:inherit;color:var(--text,#15201f);max-width:100%;box-sizing:border-box}",
    ".gn *{box-sizing:border-box;min-width:0}",
    ".gn-card{background:var(--panel-solid,#fbfcfc);border:1px solid var(--line,#dde5e4);border-radius:var(--gn-r);box-shadow:var(--shadow,none);padding:16px;margin:0 0 12px;overflow-wrap:anywhere}",
    ".gn-head{display:flex;align-items:flex-start;justify-content:space-between;gap:10px;flex-wrap:wrap;margin-bottom:10px}",
    ".gn-title{font-size:1.05rem;font-weight:700;margin:0;line-height:1.3}",
    ".gn-sub{color:var(--muted,#5f6e6b);font-size:.82rem;margin-top:2px}",
    ".gn-badge{display:inline-block;background:var(--accent-2,#dff4ef);color:var(--accent,#0f9b84);border-radius:999px;padding:2px 10px;font-size:.75rem;font-weight:600;margin:0 6px 4px 0}",
    ".gn-badge.alt{background:var(--panel-2,#f1f5f5);color:var(--muted,#5f6e6b)}",
    ".gn-btn{appearance:none;border:1px solid var(--line,#dde5e4);background:var(--panel-2,#f1f5f5);color:var(--text,#15201f);border-radius:var(--radius-sm,12px);padding:8px 12px;font:inherit;font-size:.85rem;cursor:pointer;min-height:38px}",
    ".gn-btn:hover{border-color:var(--accent,#0f9b84)}",
    ".gn-btn:disabled{opacity:.55;cursor:default}",
    ".gn-btn.pri{background:var(--grad,var(--accent,#0f9b84));color:var(--accent-text,#fff);border-color:transparent;font-weight:600}",
    ".gn-row{display:flex;gap:8px;flex-wrap:wrap;align-items:center}",
    ".gn-item{border-top:1px solid var(--line,#dde5e4);padding:12px 0}",
    ".gn-item:first-of-type{border-top:0;padding-top:0}",
    ".gn-item h4{margin:0 0 4px;font-size:.95rem;line-height:1.35}",
    ".gn-item p{margin:0 0 8px;font-size:.88rem;line-height:1.5}",
    ".gn-item a{color:var(--accent,#0f9b84);font-size:.8rem;text-decoration:none}",
    ".gn-muted{color:var(--muted,#5f6e6b);font-size:.85rem;line-height:1.5}",
    ".gn-in,.gn-ta{width:100%;border:1px solid var(--line,#dde5e4);border-radius:var(--radius-sm,12px);background:var(--panel-2,#f1f5f5);color:var(--text,#15201f);font:inherit;padding:10px 12px;font-size:.9rem}",
    ".gn-ta{min-height:84px;resize:vertical}",
    ".gn-in:focus,.gn-ta:focus{outline:2px solid var(--focus,#2cc3a5);outline-offset:0}",
    ".gn-q{background:var(--accent-2,#dff4ef);border-radius:var(--radius-sm,12px);padding:10px 12px;margin:10px 0;font-size:.92rem;line-height:1.5}",
    ".gn-ans{margin-top:8px;padding:10px 12px;border-left:3px solid var(--accent,#0f9b84);background:var(--panel-2,#f1f5f5);border-radius:8px;font-size:.88rem;line-height:1.5}",
    ".gn-trend{display:flex;gap:6px;flex-wrap:wrap}",
    ".gn-step{display:flex;gap:10px;align-items:flex-start}",
    ".gn-num{flex:0 0 28px;height:28px;border-radius:50%;background:var(--grad,var(--accent,#0f9b84));color:var(--accent-text,#fff);display:flex;align-items:center;justify-content:center;font-weight:700;font-size:.85rem}",
    ".gn-step .gn-body{flex:1 1 0}",
    ".gn-list{margin:8px 0;padding:0;list-style:none}",
    ".gn-list li{padding:6px 0;border-top:1px dashed var(--line,#dde5e4);font-size:.88rem;line-height:1.45}",
    ".gn-list li:first-child{border-top:0}",
    ".gn-list b{display:block}",
    ".gn-prev{max-width:100%;max-height:200px;border-radius:var(--radius-sm,12px);margin-top:8px;display:block}",
    ".gn-err{color:#c0392b;font-size:.85rem}",
    ".gn-spin{display:inline-block;width:14px;height:14px;border:2px solid var(--line,#dde5e4);border-top-color:var(--accent,#0f9b84);border-radius:50%;animation:gnspin .8s linear infinite;vertical-align:-2px;margin-right:6px}",
    "@keyframes gnspin{to{transform:rotate(360deg)}}",
    "@media (max-width:480px){.gn-card{padding:12px}.gn-btn{flex:1 1 auto}}"
  ].join("\n");

  function stil() {
    if (document.getElementById("gn-stil")) return;
    var s = document.createElement("style");
    s.id = "gn-stil";
    s.textContent = CSS;
    document.head.appendChild(s);
  }

  function h(tag, attrs) {
    var e = document.createElement(tag);
    if (attrs) for (var k in attrs) {
      if (k === "class") e.className = attrs[k];
      else if (k === "on") for (var ev in attrs.on) e.addEventListener(ev, attrs.on[ev]);
      else if (attrs[k] !== undefined && attrs[k] !== null) e.setAttribute(k, attrs[k]);
    }
    for (var i = 2; i < arguments.length; i++) add(e, arguments[i]);
    return e;
  }
  function add(e, c) {
    if (c === null || c === undefined || c === false) return;
    if (Array.isArray(c)) c.forEach(function (x) { add(e, x); });
    else e.appendChild(typeof c === "object" ? c : document.createTextNode(String(c)));
  }

  var sonCtx = null;
  function J(url, govde) {
    var opt = govde === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(govde) };
    return fetch(url, opt).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (j) {
        if (!r.ok) throw new Error(j.detail || ("Hata " + r.status));
        return j;
      });
    });
  }
  function toast(ctx, m) { try { (ctx && ctx.toast) ? ctx.toast(m) : null; } catch (e) { /* sessiz */ } }
  function sor(ctx, text, label, files) {
    if (ctx && typeof ctx.ask === "function") return ctx.ask({ text: text, files: files || [], label: label });
    toast(ctx, "Sohbet henüz hazır değil");
  }
  function hazirla(el, ctx) {
    stil();
    sonCtx = ctx || sonCtx;
    el.textContent = "";
    var kok = h("div", { class: "gn" });
    el.appendChild(kok);
    return kok;
  }
  function yukleniyor(m) { return h("div", { class: "gn-muted" }, h("span", { class: "gn-spin" }), m || "Yükleniyor…"); }
  function tarihYaz(iso) {
    try { return new Date(iso).toLocaleDateString("tr-TR", { day: "numeric", month: "long", year: "numeric" }); } catch (e) { return iso || ""; }
  }

  /* ------------------------------------------------------------ haftalık bülten */
  function bulten(el, ctx) {
    var kok = hazirla(el, ctx);
    var kart = h("div", { class: "gn-card" });
    kok.appendChild(kart);

    function ciz(b, trend) {
      kart.textContent = "";
      var uret = h("button", { class: "gn-btn", type: "button" }, b ? "Yenile" : "Bülteni hazırla");
      uret.addEventListener("click", function () { yenile(uret); });
      kart.appendChild(h("div", { class: "gn-head" },
        h("div", null, h("h3", { class: "gn-title" }, (b && b.baslik) || "Bu hafta endüstri mühendisliğinde neler oldu?"),
          h("div", { class: "gn-sub" }, b ? tarihYaz(b.tarih) + (b.yapay_zeka ? " · yapay zeka özeti" : " · başlık listesi") : "Haftalık sektör bülteni")),
        uret));
      if (!b || !b.maddeler || !b.maddeler.length) {
        kart.appendChild(h("p", { class: "gn-muted" }, b ? "Bu hafta için yeni haber ya da makale bulunamadı. İnternet bağlantını kontrol edip yenile." :
          "Henüz bülten yok. Hazırlandığında son bir haftanın haber ve makaleleri derslerine bağlanarak özetlenir."));
      } else {
        b.maddeler.forEach(function (m) {
          var chips = [];
          if (m.ders) chips.push(h("span", { class: "gn-badge" }, "Ders: " + m.ders));
          if (m.kariyer) chips.push(h("span", { class: "gn-badge alt" }, "Kariyer: " + m.kariyer));
          var an = h("button", { class: "gn-btn pri", type: "button" }, "Hocaya anlattır");
          an.addEventListener("click", function () {
            sor(ctx, "Bu haftanın bülteninden şu maddeyi 10 dakikalık bir mini derse çevir: önce ne olduğunu sade anlat, sonra hangi ders konusuna bağlandığını göster, " +
              "gerçek hayattan bir örnek ver, sonunda iki kısa soru sor.\n\nMadde: " + m.baslik + "\n" + (m.ozet || "") +
              (m.ders ? "\nBağlı ders/konu: " + m.ders : "") + (m.kariyer ? "\nKariyer bağlantısı: " + m.kariyer : "") + (m.url ? "\nKaynak: " + m.url : ""),
              "Bülten: " + m.baslik);
          });
          kart.appendChild(h("div", { class: "gn-item" },
            h("h4", null, m.baslik), h("p", null, m.ozet), h("div", null, chips),
            h("div", { class: "gn-row" }, an, m.url ? h("a", { href: m.url, target: "_blank", rel: "noopener noreferrer" }, "Kaynağı aç" + (m.kaynak ? " (" + m.kaynak + ")" : "")) : null)));
        });
      }
      if (trend && trend.yukselenler && trend.yukselenler.length) {
        kart.appendChild(h("div", { class: "gn-item" }, h("h4", null, "Yükselen konular"),
          h("div", { class: "gn-sub", style: "margin-bottom:6px" }, "Son 6 ay, önceki 6 aya göre sektör haberlerinde"),
          h("div", { class: "gn-trend" }, trend.yukselenler.slice(0, 6).map(function (t) {
            return h("span", { class: "gn-badge", title: t.eski + " → " + t.yeni + " haber" }, t.ad + " ↑" + t.degisim);
          }))));
      }
    }

    function yenile(btn) {
      btn.disabled = true;
      btn.textContent = "Hazırlanıyor…";
      var ilk = J("/api/guncel/haberler/cek", {}).catch(function () { return null; });
      ilk.then(function () { return J("/api/guncel/bulten/uret", {}); }).then(function (r) {
        return J("/api/guncel/trend").catch(function () { return null; }).then(function (t) { ciz(r.bulten, t); });
      }).catch(function (e) {
        btn.disabled = false; btn.textContent = "Tekrar dene";
        kart.appendChild(h("div", { class: "gn-err" }, e.message));
      });
    }

    kart.appendChild(yukleniyor());
    Promise.all([J("/api/guncel/bulten"), J("/api/guncel/trend").catch(function () { return null; })])
      .then(function (r) { ciz(r[0].bulten, r[1]); })
      .catch(function (e) { kart.textContent = ""; kart.appendChild(h("div", { class: "gn-err" }, "Bülten yüklenemedi: " + e.message)); });
  }

  /* ------------------------------------------------------------ günün kavramı */
  function gununKavrami(el, ctx) {
    var kok = hazirla(el, ctx);
    var kart = h("div", { class: "gn-card" });
    kok.appendChild(kart);
    var deneme = 0, sayac = null;

    function ciz(k) {
      kart.textContent = "";
      var cevap = h("div", { class: "gn-ans", hidden: "" }, k.cevap || "");
      var goster = h("button", { class: "gn-btn", type: "button" }, "Cevabı göster");
      goster.addEventListener("click", function () {
        var acik = cevap.hasAttribute("hidden");
        if (acik) cevap.removeAttribute("hidden"); else cevap.setAttribute("hidden", "");
        goster.textContent = acik ? "Cevabı gizle" : "Cevabı göster";
      });
      var konus = h("button", { class: "gn-btn pri", type: "button" }, "Hocayla konuş");
      konus.addEventListener("click", function () {
        sor(ctx, "Günün kavramı: " + k.kavram + (k.ders ? " (" + k.ders + ")" : "") + ".\nBunu bana kısaca anlat, gerçek hayattan örnek ver ve şu soruyla beni yokla: " + k.soru,
          "Günün kavramı: " + k.kavram);
      });
      kart.appendChild(h("div", { class: "gn-head" },
        h("div", null, h("div", { class: "gn-sub" }, "Günün kavramı · " + tarihYaz(k.tarih)), h("h3", { class: "gn-title" }, k.kavram)),
        k.ders ? h("span", { class: "gn-badge" }, k.ders) : null));
      kart.appendChild(h("p", { class: "gn-muted", style: "color:var(--text)" }, k.aciklama));
      kart.appendChild(h("div", { class: "gn-item" }, h("h4", null, "Gerçek hayattan örnek"), h("p", null, k.ornek)));
      kart.appendChild(h("div", { class: "gn-q" }, h("b", null, "Soru: "), k.soru));
      kart.appendChild(cevap);
      kart.appendChild(h("div", { class: "gn-row", style: "margin-top:10px" }, goster, konus,
        k.bekliyor ? h("span", { class: "gn-muted" }, h("span", { class: "gn-spin" }), "Hoca açıklamayı zenginleştiriyor…") : null));
      if (k.bekliyor && deneme < 12) {
        clearTimeout(sayac);
        sayac = setTimeout(function () {
          if (!kart.isConnected) return;
          deneme++;
          J("/api/guncel/gunun-kavrami").then(function (y) {
            // cevap açıkken yeniden çizip öğrenciyi bozma: yalnızca içerik değiştiyse çiz
            if (y.yapay_zeka || !y.bekliyor) ciz(y); else { deneme++; ciz(y); }
          }).catch(function () { /* sessiz */ });
        }, 6000);
      }
    }

    kart.appendChild(yukleniyor());
    J("/api/guncel/gunun-kavrami").then(ciz)
      .catch(function (e) { kart.textContent = ""; kart.appendChild(h("div", { class: "gn-err" }, "Günün kavramı yüklenemedi: " + e.message)); });
  }

  /* ------------------------------------------------------------ bitirme projesi danışmanı */
  var ASAMALAR = [
    { id: "daraltma", ad: "Konu daraltma", ipucu: "Konuyu ölçülebilir, 3-4 ayda bitirilebilir bir probleme indir." },
    { id: "literatur", ad: "Literatür taraması", ipucu: "Konuya özel makaleleri bul; kütüphaneye eklenir, hoca sorularında kaynak olarak kullanır." },
    { id: "yontem", ad: "Yöntem seçimi", ipucu: "Bilgi haritasından yöntemler ve denemen için hesap araçları." },
    { id: "veri", ad: "Veri planı", ipucu: "Hangi veri, nereden, nasıl toplanacak." },
    { id: "zaman", ad: "Zaman çizelgesi", ipucu: "Haftalık kilometre taşları." },
    { id: "rapor", ad: "Rapor iskeleti", ipucu: "Bölüm başlıkları ve her bölümde yazılacaklar." }
  ];

  function bitirme(el, ctx) {
    var kok = hazirla(el, ctx);
    var durum = null;
    var kapsayici = h("div");
    kok.appendChild(kapsayici);

    function baglam(a) {
      var s = "Bitirme projesi konum: " + durum.konu + ".\n";
      if (durum.aciklama) s += durum.aciklama + "\n";
      var ad = durum.adimlar || {};
      Object.keys(ad).forEach(function (k) {
        if (ad[k].maddeler) s += "- " + k + ": " + ad[k].maddeler.map(function (m) { return m.baslik; }).slice(0, 6).join("; ") + "\n";
      });
      return s;
    }

    function ciz() {
      kapsayici.textContent = "";
      var konu = h("textarea", { class: "gn-ta", placeholder: "Proje fikrini ya da konunu yaz (ör. Üniversite yemekhanesinde kuyruk ve hizmet süresi iyileştirme)", maxlength: "300" });
      konu.value = durum.konu || "";
      var kaydet = h("button", { class: "gn-btn pri", type: "button" }, durum.konu ? "Konuyu güncelle" : "Başla");
      kaydet.addEventListener("click", function () {
        if (!konu.value.trim()) { toast(ctx, "Önce konuyu yaz"); return; }
        kaydet.disabled = true;
        J("/api/guncel/bitirme", { konu: konu.value }).then(function (d) { durum = d; ciz(); })
          .catch(function (e) { kaydet.disabled = false; toast(ctx, e.message); });
      });
      var sifirla = durum.konu ? h("button", { class: "gn-btn", type: "button" }, "Yeni proje") : null;
      if (sifirla) sifirla.addEventListener("click", function () {
        if (confirm("Mevcut proje planı silinsin mi?")) J("/api/guncel/bitirme", { sifirla: true }).then(function (d) { durum = d; ciz(); });
      });
      kapsayici.appendChild(h("div", { class: "gn-card" },
        h("h3", { class: "gn-title" }, "Bitirme projesi danışmanı"),
        h("p", { class: "gn-muted" }, "Konunu yaz; birlikte daraltalım, literatürü tarayalım, yöntem, veri, zaman çizelgesi ve rapor iskeletini çıkaralım."),
        konu, h("div", { class: "gn-row", style: "margin-top:8px" }, kaydet, sifirla)));
      if (!durum.konu) return;
      ASAMALAR.forEach(function (a, i) { kapsayici.appendChild(asama(a, i + 1)); });
    }

    function maddeler(liste) {
      return h("ul", { class: "gn-list" }, (liste || []).map(function (m) {
        return h("li", null, h("b", null, m.baslik), m.aciklama || null);
      }));
    }

    function asama(a, no) {
      var gov = h("div", { class: "gn-body" });
      var s = (durum.adimlar || {})[a.id];
      var hata = h("div", { class: "gn-err" });
      var btn = h("button", { class: "gn-btn" + (s || (a.id === "literatur" && durum.literatur.length) ? "" : " pri"), type: "button" },
        (s || (a.id === "literatur" && durum.literatur.length)) ? "Yeniden üret" : (a.id === "literatur" ? "Literatürü tara" : "Üret"));
      var sorgu = null;
      if (a.id === "literatur") {
        var onerilen = ((durum.adimlar.daraltma || {}).sorgular || [])[0] || "";
        sorgu = h("input", { class: "gn-in", placeholder: "İngilizce arama sorgusu (boşsa daraltmadan alınır)", value: durum.literatur_sorgu || onerilen, style: "margin-bottom:8px" });
        btn.addEventListener("click", function () {
          btn.disabled = true; hata.textContent = "";
          btn.textContent = "Taranıyor…";
          J("/api/guncel/bitirme/literatur", { sorgu: sorgu.value }).then(function (r) {
            if (r.hata) { hata.textContent = r.hata; btn.disabled = false; btn.textContent = "Tekrar dene"; return; }
            return J("/api/guncel/bitirme").then(function (d) { durum = d; ciz(); toast(ctx, r.sonuclar.length + " makale bulundu"); });
          }).catch(function (e) { btn.disabled = false; btn.textContent = "Tekrar dene"; hata.textContent = e.message; });
        });
      } else {
        btn.addEventListener("click", function () {
          btn.disabled = true; hata.textContent = ""; btn.textContent = "Hazırlanıyor…";
          J("/api/guncel/bitirme", { adim: a.id }).then(function (d) { durum = d; ciz(); })
            .catch(function (e) { btn.disabled = false; btn.textContent = "Tekrar dene"; hata.textContent = e.message; });
        });
      }
      var konus = h("button", { class: "gn-btn", type: "button" }, "Hocayla konuş");
      konus.addEventListener("click", function () {
        var ic = "";
        if (a.id === "literatur") ic = (durum.literatur || []).slice(0, 8).map(function (x) { return "- " + x.baslik + (x.yil ? " (" + x.yil + ")" : ""); }).join("\n");
        else if (s) ic = s.maddeler.map(function (m) { return "- " + m.baslik + (m.aciklama ? ": " + m.aciklama : ""); }).join("\n");
        sor(ctx, baglam(a) + "\nŞu an \"" + a.ad + "\" aşamasındayım." + (ic ? "\nMevcut taslak:\n" + ic : "") +
          "\nBu aşamada bana danışmanlık yap: taslağı değerlendir, eksikleri söyle ve bir sonraki adımı öner.", "Bitirme: " + a.ad);
      });
      if (a.id === "literatur") {
        if (durum.literatur && durum.literatur.length) {
          gov.appendChild(h("ul", { class: "gn-list" }, durum.literatur.map(function (x) {
            return h("li", null, h("b", null, x.baslik),
              [x.yazar, x.yil, x.dergi].filter(Boolean).join(" · "), " ",
              x.yeni ? h("span", { class: "gn-badge" }, "kütüphaneye eklendi") : h("span", { class: "gn-badge alt" }, "kütüphanede"),
              x.url ? h("a", { href: x.url, target: "_blank", rel: "noopener noreferrer", style: "margin-left:4px;color:var(--accent);font-size:.8rem" }, "aç") : null);
          })));
        }
      } else if (s) {
        gov.appendChild(maddeler(s.maddeler));
        if (s.not) gov.appendChild(h("div", { class: "gn-muted" }, s.not));
        if (a.id === "yontem" && s.araclar && s.araclar.length) {
          gov.appendChild(h("div", null, h("span", { class: "gn-sub" }, "Hesap araçlarında dene: "),
            s.araclar.map(function (x) { return h("span", { class: "gn-badge" }, x); })));
        }
        if (s.yapay_zeka === false) gov.appendChild(h("div", { class: "gn-sub" }, "Yapay zeka kapalıyken genel şablon gösterilir."));
      }
      var ust = h("div", { class: "gn-head", style: "margin-bottom:6px" }, h("h3", { class: "gn-title" }, a.ad));
      return h("div", { class: "gn-card" }, h("div", { class: "gn-step" }, h("div", { class: "gn-num" }, String(no)),
        h("div", { class: "gn-body" }, ust, h("div", { class: "gn-muted" }, a.ipucu), sorgu ? h("div", { style: "margin-top:8px" }, sorgu) : null,
          gov, hata, h("div", { class: "gn-row", style: "margin-top:8px" }, btn, konus))));
    }

    kapsayici.appendChild(yukleniyor());
    J("/api/guncel/bitirme").then(function (d) { durum = d; ciz(); })
      .catch(function (e) { kapsayici.textContent = ""; kapsayici.appendChild(h("div", { class: "gn-err" }, "Yüklenemedi: " + e.message)); });
  }

  /* ------------------------------------------------------------ günlük hayattan endüstri mühendisliği */
  var TALIMAT_YEDEK = "GÜNLÜK HAYATTAN ENDÜSTRİ MÜHENDİSLİĞİ: Öğrencinin anlattığı/gösterdiği sistemi tanımla (girdi, süreç, çıktı, darboğaz); hangi EM modeliyle (kuyruk, yerleşim, çizelgeleme, envanter) modelleneceğini, gereken verileri, hesap araçlarıyla basit bir sayısal örneği ve iyileştirme önerilerini anlat.";
  var ORNEKLER = [
    ["Market kasası kuyruğu", "Marketteki kasa kuyruğu: "],
    ["Yemekhane", "Yemekhanedeki yemek alma ve ödeme akışı: "],
    ["Kargo", "Kargo şubesinde paket kabul ve teslimat: "],
    ["Otopark", "Otopark giriş-çıkış ve doluluk: "]
  ];

  function gunlukHayat(el, ctx) {
    var kok = hazirla(el, ctx);
    var gorevKarti = h("div", { class: "gn-card" }, yukleniyor());
    var talimat = TALIMAT_YEDEK;
    kok.appendChild(gorevKarti);
    J("/api/guncel/gunluk-hayat/gorev").then(function (g) {
      talimat = g.talimat || talimat;
      gorevKarti.textContent = "";
      gorevKarti.appendChild(h("div", { class: "gn-sub" }, "Günün “çevrene bak” görevi"));
      gorevKarti.appendChild(h("p", { style: "margin:4px 0 0;line-height:1.5" }, g.gorev));
    }).catch(function () { gorevKarti.remove(); });

    var acik = h("textarea", { class: "gn-ta", placeholder: "Çevrendeki sistemi anlat: kaç kişi/araç/paket, ne kadar bekliyor, kaç görevli var, nerede tıkanıyor…" });
    var dosya = h("input", { type: "file", accept: "image/*", style: "display:none" });
    var onizle = h("div");
    var secili = null;
    dosya.addEventListener("change", function () {
      secili = dosya.files && dosya.files[0] || null;
      onizle.textContent = "";
      if (secili) {
        var img = h("img", { class: "gn-prev", alt: "Seçilen fotoğraf" });
        img.src = URL.createObjectURL(secili);
        onizle.appendChild(img);
      }
    });
    var foto = h("button", { class: "gn-btn", type: "button" }, "Fotoğraf çek / seç");
    foto.addEventListener("click", function () { dosya.click(); });
    var gonder = h("button", { class: "gn-btn pri", type: "button" }, "Hocaya gönder");
    gonder.addEventListener("click", function () {
      var t = acik.value.trim();
      if (!t && !secili) { toast(ctx, "Bir fotoğraf ekle ya da sistemi anlat"); return; }
      sor(ctx, talimat + "\n\nÖğrencinin anlattığı sistem: " + (t || "(yalnızca fotoğraf; görünenleri tanımla)"),
        "Günlük hayattan EM", secili ? [secili] : []);
    });
    var cipler = h("div", { class: "gn-row", style: "margin-bottom:8px" }, ORNEKLER.map(function (o) {
      var b = h("button", { class: "gn-btn", type: "button" }, o[0]);
      b.addEventListener("click", function () { acik.value = o[1]; acik.focus(); });
      return b;
    }));
    kok.appendChild(h("div", { class: "gn-card" },
      h("h3", { class: "gn-title" }, "Günlük hayattan endüstri mühendisliği"),
      h("p", { class: "gn-muted" }, "Çevrendeki bir sistemin fotoğrafını çek ya da anlat; hoca onu bir mühendis gibi modellesin."),
      cipler, acik, onizle, dosya,
      h("div", { class: "gn-row", style: "margin-top:8px" }, foto, gonder)));
  }

  /* ------------------------------------------------------------ Vikipedi bekçisi */
  var DURAK = /\b(bana|lütfen|lutfen|biraz|kısaca|kisaca|detaylı|detayli|anlat|anlatır mısın|anlatir misin|açıkla|acikla|hocam|merhaba|şunu|bunu|hakkında|hakkinda|nedir|nedir\?|ne demek|ne anlama gelir|nasıl çalışır|nasil calisir|nasıl|nasil|neden|ne|mi|mı|mu|mü|bir|bu|şu|su|ve|ile|için|icin)\b/gi;
  var denenen = {};

  function terimCikar(metin) {
    var t = String(metin || "").replace(/\s+/g, " ").trim();
    if (!t || t.length > 160) return "";
    var m = t.match(/^(.{3,70}?)\s+(nedir|ne demek|ne anlama gelir|nasıl çalışır|nasil calisir|hakkında)\b/i);
    var aday = m ? m[1] : (t.split(" ").length <= 5 ? t : "");
    aday = aday.replace(/[?!.,;:"“”()]/g, " ").replace(DURAK, " ").replace(/\s+/g, " ").trim();
    var kelime = aday.split(" ").filter(Boolean).slice(0, 4);
    aday = kelime.join(" ");
    if (aday.length < 4 || aday.length > 60 || /\d{2,}|[=+*\/^]/.test(aday)) return "";
    return aday;
  }

  function bekciKontrol(metin) {
    var terim = terimCikar(metin);
    if (!terim) return;
    var anahtar = terim.toLowerCase();
    if (denenen[anahtar]) return;
    denenen[anahtar] = 1;
    fetch("/api/kutuphane/ara?q=" + encodeURIComponent(terim)).then(function (r) { return r.json(); }).then(function (j) {
      if (j && j.sonuclar && j.sonuclar.length) return null;  // kütüphanede zaten var
      return J("/api/guncel/ogren", { terim: terim });
    }).then(function (r) {
      if (r && r.durum === "eklendi") toast(sonCtx, "Vikipedi'den öğrenildi: " + r.baslik);
    }).catch(function () { /* arka plan işi: sessiz */ });
  }

  function bekciKur() {
    if (window.__guncelBekci || typeof window.fetch !== "function") return;
    window.__guncelBekci = true;
    var orijinal = window.fetch;
    window.fetch = function (girdi, secenek) {
      var p = orijinal.apply(this, arguments);
      try {
        var url = typeof girdi === "string" ? girdi : (girdi && girdi.url) || "";
        var f = secenek && secenek.body;
        if (/\/api\/ask(\?|$)/.test(url) && f && typeof FormData !== "undefined" && f instanceof FormData) {
          var metin = f.get("text"), mod = f.get("mode");
          if (metin && (!mod || mod === "chat")) {
            p.then(function (r) {
              var k = r.clone();
              if (!k.body || !k.body.getReader) return;
              var o = k.body.getReader();
              (function oku() { return o.read().then(function (x) { return x.done ? bekciKontrol(metin) : oku(); }); })().catch(function () { /* akış kesildi */ });
            }).catch(function () { /* istek hatası: bekçi karışmaz */ });
          }
        }
      } catch (e) { /* bekçi asla isteği bozmaz */ }
      return p;
    };
  }
  bekciKur();

  window.Guncel = { bulten: bulten, gununKavrami: gununKavrami, bitirme: bitirme, gunlukHayat: gunlukHayat, _terimCikar: terimCikar };
})();
