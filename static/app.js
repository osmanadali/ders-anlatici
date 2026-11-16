/* Arayüz mantığı: sohbet, sesli soru, notlar, ders anlatımı, sınav ve kayıtlar. */
(function () {
  const $ = (s) => document.querySelector(s);
  const board = new Board($("#board"));
  const teacher2d = new Teacher($("#teacher"));
  let teacher = teacher2d;
  let teacher3d = null;
  function webglOk() { try { return !!document.createElement("canvas").getContext("webgl2"); } catch { return false; } }
  async function enable3D(on) {
    if (on && !teacher3d && webglOk()) {
      try {
        const m = await import("/static/teacher3d.js");
        teacher3d = m.mount({ root: $(".classroom"), board, teacher2d,
          onError: (err) => toast("Hoca modeli yüklenemedi: " + (err?.message || err) + " (varsayılan hoca kullanılıyor)", 9000) });
        teacher = teacher3d;
      } catch (e) { console.warn("3B sınıf açılamadı, 2B devam", e); toast("3B sınıf açılamadı, 2B hocayla devam ediliyor."); }
    } else if (!on && teacher3d) {
      teacher3d.destroy(); teacher3d = null; teacher = teacher2d;
    }
  }
  document.addEventListener("pointerdown", () => teacher.unlock(), { capture: true });
  document.addEventListener("keydown", () => teacher.unlock(), { capture: true });
  function teacherStatus(t) { $("#teacherStatus").textContent = t || ""; }
  const S = {
    courses: [], courseId: "", course: null, sessionId: "",
    attachments: [], pageCtx: null, viewer: { doc: null, page: 1 },
    stream: null, streamOpen: false, tutorBubble: null,
    plan: null, lectureIdx: -1, lectureActive: false,
    settings: {}, quiz: null, micPausedPlayer: false,
    conv: null, convPaused: false, recentSays: [],
  };

  const player = new Player(board, {
    onStep(step) {
      $("#caption").textContent = step.say || "";
      if (step.say) { S.recentSays.push({ say: step.say, t: Date.now() }); S.recentSays = S.recentSays.slice(-4); }
      if (S.tutorBubble && step.say) {
        S.tutorBubble.textContent += (S.tutorBubble.textContent ? " " : "") + step.say;
        scrollChat();
      }
    },
    onState(st) {
      $("#playBtn").textContent = st === "paused" ? "▶" : "⏸";
      if (st === "idle") teacher.setState(S.streamOpen ? "thinking" : S.conv ? "listening" : "idle");
      if (st === "paused" && !S.convPaused && !S.micPausedPlayer) teacher.setState("idle");
    },
    onAudioError(url) {
      // Ses üretilemedi → tarayıcının robotik sesine düşüldü. Gerçek sebebi göster (bir kez).
      if (S.audioErrShown) return;
      S.audioErrShown = true;
      fetch(url).then((r) => (r.ok ? null : r.json())).then((d) => {
        if (d?.detail) toast(d.detail + " (şimdilik tarayıcı sesi kullanılıyor)", 9000);
      }).catch(() => {});
    },
    onAudio(audio) { teacher.fakeTalk = !audio || !teacher.attachAudio(audio); },
    onSpeak(on, drawing) {
      if (on) { teacher.setState(drawing ? "writing" : "talking"); teacherStatus(""); }
      else S.lastSpeechEnd = Date.now();
    },
    onIdle() {
      if (!S.streamOpen) {
        $("#caption").textContent = "";
        teacher.setState(S.conv ? "listening" : "idle");
        teacherStatus(S.conv ? "Seni dinliyorum…" : "");
        if (S.lectureActive && $("#autoNext").checked) setTimeout(nextSection, 1200);
      }
    },
  });
  board.onPageChange = (i, n) => { $("#pageInfo").textContent = n > 1 ? `Tahta ${i + 1}/${n}` : ""; };

  // ================================================================ yardımcılar
  function toast(msg, ms = 3500) {
    const t = $("#toast");
    t.textContent = msg;
    t.classList.remove("hidden");
    clearTimeout(toast._t);
    toast._t = setTimeout(() => t.classList.add("hidden"), ms);
  }
  async function api(path, opts = {}) {
    const r = await fetch(path, opts);
    if (!r.ok) {
      let msg = r.statusText;
      try { msg = (await r.json()).detail || msg; } catch {}
      throw new Error(msg);
    }
    return r.headers.get("content-type")?.includes("json") ? r.json() : r;
  }
  const postJSON = (path, body) => api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  function dropEmptyBubble() {
    if (S.tutorBubble && !S.tutorBubble.textContent.trim()) S.tutorBubble.remove();
    S.tutorBubble = null;
  }
  function scrollChat() { const l = $("#chatLog"); l.scrollTop = l.scrollHeight; }
  function addMsg(kind, text, att) {
    $("#chatLog .hint")?.remove();
    const d = document.createElement("div");
    d.className = "msg " + kind;
    d.textContent = text || "";
    if (att && att.length) {
      const a = document.createElement("span");
      a.className = "att";
      a.textContent = "📎 " + att.join(", ");
      d.appendChild(a);
    }
    $("#chatLog").appendChild(d);
    scrollChat();
    return d;
  }
  function switchTab(name) {
    document.querySelectorAll(".tabs button").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
    document.querySelectorAll(".tab-panel").forEach((p) => p.classList.toggle("active", p.id === "tab-" + name));
    if (name === "records") loadRecords();
    if (name === "quiz") loadWeak();
    if (name === "plan") loadPlanTab();
  }
  document.querySelectorAll(".tabs button").forEach((b) => b.addEventListener("click", () => switchTab(b.dataset.tab)));

  // ================================================================ anlatım isteği (SSE akışı)
  async function ask({ text = "", mode = "chat", doc_id = "", page = 0, section = null, files = [], label = "" }) {
    teacher.unlock();
    let interrupted = "";
    if (S.streamOpen || player.busy) {
      interrupted = player.currentSay;
      S.stream?.abort();
      player.stop();
    }
    if (mode !== "lecture") S.lectureActive = false;
    const ctx = S.pageCtx;
    if (mode === "chat" && ctx && !doc_id) { doc_id = ctx.doc; page = ctx.page; }

    const fd = new FormData();
    fd.append("text", text);
    fd.append("mode", mode);
    fd.append("session_id", S.sessionId || "");
    fd.append("course_id", S.courseId || "");
    fd.append("doc_id", doc_id || "");
    fd.append("page", String(page || 0));
    if (section) fd.append("section", JSON.stringify(section));
    if (interrupted) fd.append("interrupted", interrupted);
    if (S.conv) fd.append("style", "konusma");
    files.forEach((f) => fd.append("files", f, f.name));

    const shown = label || text || (doc_id ? `Sayfa ${page}` : "");
    addMsg("user", shown + (ctx && mode === "chat" ? `  (📄 ${ctx.label})` : ""), files.map((f) => f.name));
    dropEmptyBubble();
    S.tutorBubble = addMsg("tutor", "");
    $("#caption").textContent = "Düşünüyor…";
    teacher.setState("thinking");
    teacherStatus("");

    const ctrl = new AbortController();
    S.stream = ctrl;
    S.streamOpen = true;
    try {
      const r = await fetch("/api/ask", { method: "POST", body: fd, signal: ctrl.signal });
      if (!r.ok) {
        let m = r.statusText; try { m = (await r.json()).detail; } catch {}
        throw new Error(m);
      }
      const reader = r.body.getReader();
      const dec = new TextDecoder();
      let buf = "";
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        let i;
        while ((i = buf.indexOf("\n\n")) >= 0) {
          const chunk = buf.slice(0, i); buf = buf.slice(i + 2);
          if (!chunk.startsWith("data: ")) continue;
          handleEvent(JSON.parse(chunk.slice(6)));
        }
      }
    } catch (e) {
      if (e.name !== "AbortError") {
        dropEmptyBubble();
        const offline = e instanceof TypeError;  // "Failed to fetch": sunucu kapalı / ulaşılamıyor
        addMsg("err", offline
          ? "Sunucuya ulaşılamadı. Siyah komut penceresi kapanmış olabilir: Ders Anlatici.bat ile yeniden aç. Sorun sürerse ders-anlatici/veri/sunucu.log dosyasını gönder."
          : "Hata: " + e.message);
        $("#caption").textContent = "";
      }
    } finally {
      if (S.stream === ctrl) {
        S.streamOpen = false;
        S.stream = null;
        if (!player.busy) player.hooks.onIdle();
      }
    }
  }

  function handleEvent(ev) {
    switch (ev.type) {
      case "session": S.sessionId = ev.id; break;
      case "step": player.enqueue(ev); break;
      case "memory": toast(`Not aldım: “${ev.topic}” konusunu tekrar edeceğiz.`); break;
      case "notice": toast(ev.message); break;
      case "stage": $("#caption").textContent = ev.message; teacherStatus(ev.message); break;
      case "status": {
        $("#caption").textContent = ev.message;
        // Düşünme süresini doğal bir ana çevir: hoca "bir bakayım" der ve düşünme pozuna geçer.
        const fillers = ["Hmm, güzel soru. Bir dakika, önce kendim bir çözeyim, sonra sana adım adım anlatacağım.",
          "Bir bakayım… Önce soruyu kafamda çözeyim, sonra tahtada beraber yapalım.",
          "Tamam, düşünüyorum. Her adımın nereden geldiğini göstereceğim, bir saniye."];
        const say = fillers[Math.floor(Math.random() * fillers.length)];
        if (!player.busy) {
          player.enqueue({ say, board: [], audio: S.settings.tts_enabled === false ? null : "/api/tts?text=" + encodeURIComponent(say), filler: true });
        }
        break;
      }
      case "error": dropEmptyBubble(); addMsg("err", ev.message); $("#caption").textContent = ""; S.lectureActive = false; break;
    }
  }

  // ================================================================ sohbet formu ve ekler
  function renderAttachments() {
    const row = $("#attachRow");
    row.innerHTML = "";
    S.attachments.forEach((f, i) => {
      const c = document.createElement("span");
      c.className = "chip";
      if (f.type.startsWith("image/")) {
        const img = document.createElement("img");
        img.src = URL.createObjectURL(f);
        c.appendChild(img);
      }
      c.appendChild(document.createTextNode(f.name.length > 22 ? f.name.slice(0, 20) + "…" : f.name));
      const x = document.createElement("button");
      x.type = "button"; x.textContent = "×";
      x.onclick = () => { S.attachments.splice(i, 1); renderAttachments(); };
      c.appendChild(x);
      row.appendChild(c);
    });
    if (S.pageCtx) {
      const c = document.createElement("span");
      c.className = "chip";
      c.textContent = "📄 " + S.pageCtx.label;
      const x = document.createElement("button");
      x.type = "button"; x.textContent = "×";
      x.onclick = () => { S.pageCtx = null; renderAttachments(); };
      c.appendChild(x);
      row.appendChild(c);
    }
  }
  function addFiles(list) {
    for (const f of list) {
      if (f.type.startsWith("image/") || f.type === "application/pdf") S.attachments.push(f);
    }
    renderAttachments();
  }
  $("#fileInput").addEventListener("change", (e) => { addFiles(e.target.files); e.target.value = ""; });
  $("#askInput").addEventListener("paste", (e) => {
    const files = [...(e.clipboardData?.items || [])].filter((i) => i.kind === "file").map((i) => i.getAsFile()).filter(Boolean)
      .map((f, k) => new File([f], f.name && f.name !== "image.png" ? f.name : `ekran_${Date.now()}_${k}.png`, { type: f.type }));
    if (files.length) { e.preventDefault(); addFiles(files); }
  });
  const side = $(".side");
  side.addEventListener("dragover", (e) => e.preventDefault());
  side.addEventListener("drop", (e) => { e.preventDefault(); switchTab("chat"); addFiles(e.dataTransfer.files); });

  $("#askForm").addEventListener("submit", (e) => {
    e.preventDefault();
    const text = $("#askInput").value.trim();
    if (!text && !S.attachments.length && !S.pageCtx) return;
    const files = S.attachments;
    S.attachments = [];
    $("#askInput").value = "";
    ask({ text, files });
    S.pageCtx = null;
    renderAttachments();
  });
  $("#askInput").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("#askForm").requestSubmit(); }
  });

  // ================================================================ oynatma kontrolleri
  $("#playBtn").onclick = () => player.toggle();
  $("#stopBtn").onclick = () => { S.stream?.abort(); S.lectureActive = false; player.stop(); $("#caption").textContent = ""; };
  $("#speedSelect").onchange = (e) => player.setRate(Number(e.target.value));
  $("#prevPageBtn").onclick = () => board.show(board.view - 1);
  $("#nextPageBtn").onclick = () => board.show(board.view + 1);
  $("#exportBtn").onclick = () => { if (!board.exportPDF()) toast("Tahta boş."); };
  $("#newSessionBtn").onclick = () => {
    S.stream?.abort(); player.stop(); S.sessionId = ""; S.lectureActive = false;
    board.clear(); $("#chatLog").innerHTML = ""; $("#caption").textContent = "";
    toast("Yeni anlatım başladı.");
  };
  document.addEventListener("keydown", (e) => {
    if (e.target.closest("textarea, input, select")) return;
    if (e.key === "p" || e.key === "P") player.toggle();
  });

  // ================================================================ sesli soru (söz kesme dahil)
  let rec = null, chunks = [];
  async function startRec() {
    if (rec) return;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      if (player.state === "playing") { player.pause(); S.micPausedPlayer = true; }
      chunks = [];
      rec = new MediaRecorder(stream);
      rec.ondataavailable = (e) => e.data.size && chunks.push(e.data);
      rec.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        $("#micBtn").classList.remove("rec");
        const blob = new Blob(chunks, { type: rec.mimeType || "audio/webm" });
        rec = null;
        if (blob.size < 2000) { resumeIfMicPaused(); return; }
        $("#caption").textContent = "Sesini yazıya çeviriyorum…";
        try {
          const fd = new FormData();
          fd.append("file", blob, "soru.webm");
          const { text } = await api("/api/stt", { method: "POST", body: fd });
          if (!text) { toast("Ses anlaşılamadı."); resumeIfMicPaused(); return; }
          S.micPausedPlayer = false;
          const files = S.attachments; S.attachments = []; renderAttachments();
          ask({ text, files });
        } catch (e) {
          toast("Sesli soru hatası: " + e.message);
          resumeIfMicPaused();
        }
      };
      rec.start();
      $("#micBtn").classList.add("rec");
      $("#caption").textContent = "Dinliyorum… (bitirince tekrar bas)";
    } catch (e) {
      toast("Mikrofona erişilemedi: " + e.message);
    }
  }
  function stopRec() { if (rec && rec.state === "recording") rec.stop(); }
  // ---------------- konuşmalı ders (eller serbest)
  async function toggleConversation() {
    if (S.conv) {
      S.conv.stop(); S.conv = null;
      $("#convBtn").classList.remove("on"); $("#micMeter").classList.add("hidden");
      teacherStatus("");
      if (!player.busy) teacher.setState("idle");
      if (S.convPaused) { S.convPaused = false; player.resume(); }
      return;
    }
    teacher.unlock();
    const hooks = {
      isTutorSpeaking: () => player.state === "playing",
      // Yankı olabilecek metin: yalnızca hoca konuşurken ve sustuktan sonraki 3 sn (cevaplar "tamam" vb. filtrelenmesin)
      tutorText: () => (player.state === "playing" || Date.now() - (S.lastSpeechEnd || 0) < 3000)
        ? [player.currentSay, ...S.recentSays.slice(-2).map((x) => x.say)].join(" ") : "",
      onSpeechStart() {
        if (player.state === "playing") { player.pause(); S.convPaused = true; }
        teacher.setState("listening");
        teacherStatus("Dinliyorum…");
      },
      onFalseStart() {
        if (S.convPaused) { S.convPaused = false; player.resume(); teacher.setState("talking"); teacherStatus(""); }
        else if (!player.busy) teacher.setState(S.streamOpen ? "thinking" : "listening");
      },
      onText(text) {
        S.convPaused = false;
        const files = S.attachments; S.attachments = []; renderAttachments();
        ask({ text, files });
      },
      async onUtterance(wav) {
        const st = await api("/api/status").catch(() => ({}));
        teacherStatus(st.whisper === "hazırlanıyor"
          ? "Konuşma tanıma modeli ilk kez hazırlanıyor (~1.6 GB, bir kez)…" : "Anlamaya çalışıyorum…");
        try {
          const fd = new FormData();
          fd.append("file", wav, "soru.wav");
          const { text } = await api("/api/stt", { method: "POST", body: fd });
          if (!text || text.replace(/[^\p{L}\p{N}]/gu, "").length < 2) { hooks.onFalseStart(); teacherStatus("Seni dinliyorum…"); return; }
          hooks.onText(text);
        } catch (e) {
          toast("Ses anlaşılamadı: " + e.message);
          hooks.onFalseStart();
        }
      },
      onLevel(level, state) {
        const m = $("#micMeter");
        m.firstElementChild.style.width = Math.round(level * 100) + "%";
        m.classList.toggle("speaking", state === "speaking");
      },
      onFail(reason, info = {}) {
        if (S.convPaused) { S.convPaused = false; player.resume(); }
        if (S.conv) { S.conv.stop(); S.conv = null; }
        $("#convBtn").classList.remove("on"); $("#micMeter").classList.add("hidden");
        if (info.permission) {  // izin sorunu Whisper ile de çözülmez
          toast(reason + " Adres çubuğundaki/pencere başlığındaki kilit simgesinden mikrofona izin ver.", 9000);
          teacher.setState("idle"); teacherStatus("");
          return;
        }
        // Bu oturum için Whisper'a geç (kalıcı değil: sonraki açılışta tarayıcı tanıması yeniden denenir)
        toast(reason + " Bilgisayardaki Whisper'a geçiyorum.", 7000);
        S.convSttFallback = true;
        toggleConversation();
      },
    };
    const useBrowser = window.BrowserConversation?.available() && localGet("convStt") !== "whisper" && !S.convSttFallback;
    const conv = useBrowser ? new BrowserConversation(hooks) : new Conversation(hooks);
    try { await conv.start(); }
    catch (e) { toast("Mikrofon açılamadı: " + e.message); return; }
    conv.sensitivity = Number(localGet("sens") || 1);
    S.conv = conv;
    $("#convBtn").classList.add("on"); $("#micMeter").classList.remove("hidden");
    toast("Konuşmalı ders açık. Kulaklık kullanırsan hoca kendi sesini duyup durmaz.", 5000);
    if (!player.busy && !S.streamOpen && S.greetedCourse !== (S.courseId || "-")) {
      S.greetedCourse = S.courseId || "-";
      const hi = S.course ? `Merhaba! ${S.course.name} dersine hazırım. Hangi konudan başlayalım? İstediğin an sözümü kesebilirsin.`
                          : "Merhaba! Hazırım. Takıldığın yeri anlat, istediğin an sözümü kesebilirsin.";
      S.tutorBubble = addMsg("tutor", "");
      player.enqueue({ say: hi, board: [], audio: S.settings.tts_enabled === false ? null : "/api/tts?text=" + encodeURIComponent(hi) });
    }
  }
  $("#convBtn").onclick = toggleConversation;

  function resumeIfMicPaused() { if (S.micPausedPlayer) { S.micPausedPlayer = false; player.resume(); } $("#caption").textContent = ""; }
  $("#micBtn").onclick = () => (rec ? stopRec() : startRec());
  // Boşluk tuşunu basılı tut = bas-konuş
  let spaceDown = false;
  document.addEventListener("keydown", (e) => {
    if (e.code !== "Space" || e.repeat || e.target.closest("textarea, input, select, button")) return;
    e.preventDefault(); spaceDown = true; startRec();
  });
  document.addEventListener("keyup", (e) => {
    if (e.code === "Space" && spaceDown) { spaceDown = false; setTimeout(stopRec, 250); }
  });

  // ================================================================ dersler ve notlar
  async function loadCourses(selectId) {
    S.courses = await api("/api/courses");
    const sel = $("#courseSelect");
    sel.innerHTML = '<option value="">— Ders seç (notsuz da sorabilirsin) —</option>' +
      S.courses.map((c) => `<option value="${c.id}">${c.name.replace(/</g, "&lt;")}</option>`).join("");
    const want = selectId ?? localGet("course") ?? "";
    sel.value = S.courses.some((c) => c.id === want) ? want : "";
    await selectCourse(sel.value);
  }
  async function selectCourse(id) {
    S.courseId = id;
    board.courseId = id;
    localSet("course", id);
    S.course = id ? await api(`/api/courses/${id}`) : null;
    S.plan = null; S.lectureActive = false;
    $("#planList").innerHTML = ""; $("#planStatus").textContent = "";
    if (S.course?.lecture_plan) {  // hazır ders paketinden ya da önceden çıkarılmış plan
      S.plan = S.course.lecture_plan;
      $("#planStatus").textContent = (S.plan.hazir ? "📦 Hazır ders planı (notların tamamından): " : "") + S.plan.title + " — başlamak için bir bölüme tıkla.";
      renderPlan();
    }
    const rb = $("#rehberBox");
    if (S.course?.sinav_rehberi) {
      rb.classList.remove("hidden");
      rb.querySelector("div").innerHTML = BoardUtil.renderInline(S.course.sinav_rehberi).replace(/\n/g, "<br>");
    } else rb.classList.add("hidden");
    renderDenemeler();
    renderDocs();
    loadWeak();
    if ($("#tab-plan").classList.contains("active")) loadPlanTab();
  }
  $("#courseSelect").onchange = (e) => { S.sessionId = ""; selectCourse(e.target.value); };
  $("#newCourseBtn").onclick = async () => {
    const name = prompt("Ders adı (ör. Diferansiyel Denklemler):");
    if (!name) return;
    const c = await postJSON("/api/courses", { name });
    await loadCourses(c.id);
    switchTab("notes");
  };

  function renderProfile() {
    const box = $("#profileBox"), p = S.course?.profile;
    if (!p) { box.classList.add("hidden"); return; }
    box.classList.remove("hidden");
    const esc = (t) => String(t || "").replace(/</g, "&lt;");
    box.innerHTML = `<details><summary>📚 Ders profili: ${esc(p.kod)} ${esc(p.ad)}${p.dil ? " · " + esc(p.dil) : ""}${p.akts ? " · " + p.akts + " AKTS" : ""}</summary>
      ${p.ad_en ? `<div class="muted">${esc(p.ad_en)}</div>` : ""}<p>${esc(p.icerik)}</p>
      ${(p.haftalik_konular || []).length ? "<ol>" + p.haftalik_konular.map((t) => `<li>${esc(t)}</li>`).join("") + "</ol>" : ""}
      ${(p.kaynak_kitaplar || []).length ? `<div class="muted">Kaynaklar: ${esc(p.kaynak_kitaplar.join("; "))}</div>` : ""}</details>`;
  }

  function renderDocs() {
    renderProfile();
    const ul = $("#docList");
    ul.innerHTML = "";
    $("#pageViewer").classList.add("hidden");
    if (!S.course) { ul.innerHTML = '<li class="muted">Önce üstten bir ders seç ya da “+ Ders” ile oluştur.</li>'; return; }
    if (!S.course.docs.length) ul.innerHTML = `<li class="muted">Bu derste henüz not yok. PDF ya da defter fotoğrafı yükle.${S.course.profile ? " (Not olmasa da hoca müfredattaki konuları anlatabilir.)" : ""}</li>`;
    let pendingOcr = 0;
    S.course.docs.forEach((d) => {
      const ocr = d.pages.filter((p) => p.needs_ocr).length;
      const busy = d.status && !d.status.startsWith("Hata");
      pendingOcr += ocr + (busy ? 1 : 0);
      const info = d.status ? d.status : `${d.pages.length} ${d.kind === "audio" ? "bölüm" : "sf"}${ocr ? ` · ${ocr} okunuyor…` : ""}`;
      const li = document.createElement("li");
      li.innerHTML = `<span>${{ pdf: "📕", image: "🖼️", audio: "🎙" }[d.kind] || "📄"}</span><span class="name"></span><span class="muted small"></span><button class="ghost small mv" title="Başka derse taşı">↪</button><button class="ghost small del" title="Sil">🗑</button>`;
      li.querySelector(".small").textContent = info;
      li.querySelector(".name").textContent = d.name;
      li.onclick = (e) => { if (e.target.tagName === "BUTTON" || !d.pages.length) return; openViewer(d, 1); };
      li.querySelector(".mv").onclick = () => openMove(d);
      li.querySelector(".del").onclick = async () => {
        if (!confirm(`“${d.name}” silinsin mi?`)) return;
        await api(`/api/courses/${S.courseId}/docs/${d.id}`, { method: "DELETE" });
        S.course = await api(`/api/courses/${S.courseId}`);
        renderDocs();
      };
      if (S.viewer.doc?.id === d.id) li.classList.add("active");
      ul.appendChild(li);
    });
    if (S.viewer.doc && S.course.docs.some((d) => d.id === S.viewer.doc.id)) openViewer(S.viewer.doc, S.viewer.page);
    clearTimeout(renderDocs._poll);
    if (pendingOcr) renderDocs._poll = setTimeout(async () => { if (S.courseId) { S.course = await api(`/api/courses/${S.courseId}`); renderDocs(); } }, 5000);
  }
  function openViewer(doc, page) {
    S.viewer = { doc, page: Math.max(1, Math.min(page, doc.pages.length)) };
    $("#pageViewer").classList.remove("hidden");
    $("#pvLabel").textContent = `${doc.name} — sayfa ${S.viewer.page}/${doc.pages.length}`;
    const isText = doc.kind === "audio";
    $("#pvImg").classList.toggle("hidden", isText);
    $("#pvText").classList.toggle("hidden", !isText);
    if (isText) $("#pvText").innerHTML = BoardUtil.renderInline(doc.pages[S.viewer.page - 1]?.text || "")
      + `<p><a href="/api/courses/${S.courseId}/docs/${doc.id}/transcript" target="_blank">Ham transkripti aç</a></p>`;
    else $("#pvImg").src = `/api/courses/${S.courseId}/docs/${doc.id}/pages/${S.viewer.page}.png`;
    if (isText) $("#pvLabel").textContent = `${doc.name} — bölüm ${S.viewer.page}/${doc.pages.length}`;
    document.querySelectorAll("#docList li").forEach((li, i) => li.classList.toggle("active", S.course.docs[i]?.id === doc.id));
  }
  $("#pvPrev").onclick = () => openViewer(S.viewer.doc, S.viewer.page - 1);
  $("#pvNext").onclick = () => openViewer(S.viewer.doc, S.viewer.page + 1);
  $("#pvExplain").onclick = () => {
    const { doc, page } = S.viewer;
    switchTab("chat");
    ask({ mode: "page", doc_id: doc.id, page, label: `“${doc.name}” ${page}. sayfayı anlat` });
  };
  $("#pvAsk").onclick = () => {
    const { doc, page } = S.viewer;
    S.pageCtx = { doc: doc.id, page, label: `${doc.name} s.${page}` };
    renderAttachments();
    switchTab("chat");
    $("#askInput").focus();
  };
  $("#docInput").addEventListener("change", async (e) => {
    if (!S.courseId) { const f = [...e.target.files]; e.target.value = ""; return autoAdd(f); }  // ders seçilmemiş: kendisi bulsun
    const files = [...e.target.files];
    e.target.value = "";
    for (const [i, f] of files.entries()) {
      $("#uploadStatus").textContent = `Yükleniyor ${i + 1}/${files.length}: ${f.name}…`;
      const fd = new FormData();
      fd.append("file", f, f.name);
      try { await api(`/api/courses/${S.courseId}/docs`, { method: "POST", body: fd }); }
      catch (err) { toast(`${f.name}: ${err.message}`); }
    }
    $("#uploadStatus").textContent = "";
    S.course = await api(`/api/courses/${S.courseId}`);
    renderDocs();
  });

  $("#packInput").addEventListener("change", async (e) => {
    const f = e.target.files[0];
    e.target.value = "";
    if (!f) return;
    $("#uploadStatus").textContent = `Ders paketi yükleniyor: ${f.name}…`;
    const fd = new FormData();
    fd.append("file", f, f.name);
    try {
      const r = await api("/api/hazir", { method: "POST", body: fd });
      toast(`📦 ${r.ders || r.id}: ${r.belge} belgelik paket kuruldu` +
        (r.uygulanan ? `, ${r.uygulanan} yüklü nota uygulandı.` : ". Aynı PDF'leri yüklediğinde kendiliğinden eşleşecek."));
      if (S.courseId) await selectCourse(S.courseId);
    } catch (err) { toast("Paket yüklenemedi: " + err.message); }
    $("#uploadStatus").textContent = "";
  });

  // ================================================================ deneme sınavları + konu anlatımı (ders paketinden)
  function mdLite(md) {  // başlık, madde, kalın, paragraf: konu anlatımı için yeterli
    const inl = (t) => BoardUtil.renderInline(t).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>");
    let html = "", list = "";
    const close = () => { if (list) { html += `</${list}>`; list = ""; } };
    for (const raw of String(md || "").split("\n")) {
      const line = raw.trimEnd();
      let m;
      if (/^\s*\|.*\|\s*$/.test(line)) {  // tablo satırı
        const cells = line.trim().slice(1, -1).split("|").map((c) => c.trim());
        if (cells.every((c) => /^:?-{2,}:?$/.test(c))) continue;  // ayraç satırı
        if (list !== "table") { close(); html += '<table class="md-table">'; list = "table"; html += "<tr>" + cells.map((c) => `<th>${inl(c)}</th>`).join("") + "</tr>"; }
        else html += "<tr>" + cells.map((c) => `<td>${inl(c)}</td>`).join("") + "</tr>";
      }
      else if ((m = line.match(/^(#{1,4})\s+(.*)/))) { close(); const n = Math.min(6, m[1].length + 2); html += `<h${n}>${inl(m[2])}</h${n}>`; }
      else if ((m = line.match(/^\s*[-*•]\s+(.*)/))) { if (list !== "ul") { close(); html += "<ul>"; list = "ul"; } html += `<li>${inl(m[1])}</li>`; }
      else if ((m = line.match(/^\s*\d+[.)]\s+(.*)/))) { if (list !== "ol") { close(); html += "<ol>"; list = "ol"; } html += `<li>${inl(m[1])}</li>`; }
      else if (!line.trim()) close();
      else { close(); html += `<p>${inl(line)}</p>`; }
    }
    close();
    return html;
  }
  function renderDenemeler() {
    const kb = $("#konuBox"), db = $("#denemeBox"), ob = $("#ozetBox"), ex = S.course?.denemeler || [];
    ob.classList.toggle("hidden", !S.course?.kisa_ozet);
    if (S.course?.kisa_ozet) ob.querySelector("div").innerHTML = mdLite(S.course.kisa_ozet);
    if (S.course?.konu_anlatimi) {
      kb.classList.remove("hidden");
      kb.querySelector("div").innerHTML = mdLite(S.course.konu_anlatimi);
    } else kb.classList.add("hidden");
    db.classList.toggle("hidden", !ex.length);
    $("#denemeBtns").innerHTML = ex.map((x, i) => `<button class="ghost small" data-i="${i}">${(x.baslik || "Deneme " + (i + 1)).replace(/</g, "&lt;")}</button>`).join(" ");
    $("#denemeBtns").querySelectorAll("button").forEach((b) => (b.onclick = () => openDeneme(ex[+b.dataset.i])));
  }
  function openDeneme(x) {
    const esc = (t) => BoardUtil.renderInline(t || "");
    const src = (t) => (t ? `<span class="muted small"> (${String(t).replace(/</g, "&lt;")})</span>` : "");
    const open = [];  // açık uçlu sorular (değerlendirme için)
    const openQ = (soru, ornek, puan, kaynak, label) => {
      const k = open.push({ question: soru, kind: "acik_uclu", choices: [], answer: ornek + (puan ? "\nPuanlama: " + puan : ""), topic: label, page: kaynak || "" }) - 1;
      return `<div class="dq"><div class="q">${esc(soru)}</div><textarea rows="5" data-open="${k}" placeholder="Cevabını yaz…"></textarea>
        <div class="row"><button class="ghost small" data-grade="${k}">Hocaya değerlendirt</button></div><div class="fb hidden" data-fb="${k}"></div>
        <details class="key hidden"><summary>Örnek cevap</summary><p>${esc(ornek).replace(/\n/g, "<br>")}</p>${puan ? `<p class="muted small"><b>Puanlama:</b> ${esc(puan)}</p>` : ""}${src(kaynak)}</details></div>`;
    };
    const area = $("#quizArea");
    area.innerHTML = `<div class="deneme">
      <div class="row"><h3 style="margin:0">${esc(x.baslik)}</h3><div class="spacer"></div><button class="ghost small" data-k="close">✕ Kapat</button></div>
      <p class="muted small">Süre sınırı yok. Cevaplarını işaretle/yaz, sonra en alttan “Kontrol et”.</p>
      <h4>1. Bölüm — Doğru / Yanlış</h4>
      ${(x.bolum1_dy || []).map((q, i) => `<div class="dq dy" data-i="${i}"><div class="q">${i + 1}. ${esc(q.ifade)}</div>
        <label class="check"><input type="radio" name="dy${i}" value="D"> D</label> <label class="check"><input type="radio" name="dy${i}" value="Y"> Y</label>
        <div class="key hidden">Cevap: <b>${q.cevap}</b> — ${esc(q.aciklama)}${src(q.kaynak)}</div></div>`).join("")}
      <h4>2. Bölüm — Çoktan seçmeli</h4>
      ${(x.bolum2_coktan || []).map((q, i) => `<div class="dq mc" data-i="${i}"><div class="q">${i + 1}. ${esc(q.soru)}</div>
        ${(q.siklar || []).map((c, k) => `<label class="check opt"><input type="radio" name="mc${i}" value="${"ABCDE"[k]}"> <b>${"ABCDE"[k]})</b> ${esc(String(c).replace(/^[A-E][).]\s*/, ""))}</label>`).join("")}
        <div class="key hidden">Cevap: <b>${String(q.cevap).trim().charAt(0)}</b> — ${esc(q.aciklama)}${src(q.kaynak)}</div></div>`).join("")}
      <h4>3. Bölüm — Metin soruları</h4>
      <blockquote class="metin">${esc(x.bolum3_metin?.metin).replace(/\n/g, "<br>")}</blockquote>
      ${(x.bolum3_metin?.sorular || []).map((q, i) => openQ(`${i + 1}. ${q.soru}`, q.ornek_cevap, "", x.bolum3_metin?.kaynak, "Metin sorusu")).join("")}
      <h4>4. Bölüm — Klasik</h4>
      ${(x.bolum4_klasik || []).map((q) => openQ(q.soru, q.ornek_cevap, q.puanlama, q.kaynak, "Klasik soru")).join("")}
      <h4>5. Bölüm — Bonus</h4>
      ${(x.bolum5_bonus || []).map((q) => openQ(q.soru, q.cozum, "", "", "Bonus soru")).join("")}
      <div class="row"><button class="primary" data-k="check">Kontrol et</button><span class="dscore"></span></div>
    </div>`;
    area.querySelector('[data-k="close"]').onclick = () => { area.innerHTML = ""; };
    area.querySelectorAll("[data-grade]").forEach((b) => (b.onclick = async () => {
      const k = +b.dataset.grade, ans = area.querySelector(`[data-open="${k}"]`).value.trim(), fb = area.querySelector(`[data-fb="${k}"]`);
      if (!ans) return toast("Önce cevabını yaz.");
      b.disabled = true; fb.classList.remove("hidden"); fb.className = "fb"; fb.textContent = "Değerlendiriliyor…";
      const fd = new FormData();
      fd.append("question", JSON.stringify(open[k])); fd.append("answer", ans); fd.append("course_id", S.courseId || "");
      try { showFeedback(fb, await api("/api/quiz/grade", { method: "POST", body: fd })); } catch (e) { fb.textContent = "Hata: " + e.message; }
      b.disabled = false;
    }));
    area.querySelector('[data-k="check"]').onclick = () => {
      let ok = 0, n = 0;
      const mark = (el, picked, right) => {
        n++; const good = picked === right; if (good) ok++;
        el.classList.toggle("ok", good); el.classList.toggle("bad", !good);
      };
      area.querySelectorAll(".dy").forEach((el) => mark(el, el.querySelector("input:checked")?.value, x.bolum1_dy[+el.dataset.i].cevap));
      area.querySelectorAll(".mc").forEach((el) => mark(el, el.querySelector("input:checked")?.value, String(x.bolum2_coktan[+el.dataset.i].cevap).trim().charAt(0).toUpperCase()));
      area.querySelectorAll(".key").forEach((el) => el.classList.remove("hidden"));
      area.querySelector(".dscore").textContent = ` D/Y + test: ${ok}/${n} doğru. Açık uçlu cevapları örnek cevapla karşılaştır ya da “Hocaya değerlendirt”.`;
    };
    area.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  // ================================================================ yerel yapay zeka durumu
  let yerelTimer = null;
  const GB = { "gemma4:26b": 18.7, "gemma4:12b": 8, "gemma4:e4b": 6.6, "gemma4:e2b": 4.6 };
  async function refreshYerel(fillSelect = false) {
    let y;
    try { y = await api("/api/yerel"); } catch { return null; }
    const chip = $("#yerelChip"), pct = y.progress != null ? ` %${Math.round(y.progress * 100)}` : "";
    const txt = { hazir: "✔ " + y.detail, kuruluyor: "⏳ " + y.detail + pct, hata: "⚠ " + y.detail,
      bilinmiyor: "Henüz başlatılmadı" }[y.state] || y.detail;
    $("#yerelDurum").textContent = txt;
    $("#yerelBar").classList.toggle("hidden", y.state !== "kuruluyor" || y.progress == null);
    if (y.progress != null) $("#yerelBar").value = y.progress;
    chip.classList.toggle("hidden", y.state === "hazir" || y.state === "bilinmiyor");
    chip.textContent = y.state === "hata" ? "⚠ Yapay zeka" : `🧠 Kuruluyor${pct}`;
    chip.title = txt;
    if (y.hw) $("#yerelHw").textContent = `Bilgisayar: ${y.hw.ram_gb} GB bellek` + (y.hw.vram_gb ? `, ${y.hw.vram_gb} GB ekran kartı` : ", ekran kartı yok") + `, ${y.hw.disk_gb} GB boş disk`;
    if (fillSelect) {
      const cur = S.settings.yerel_model || "";
      $("#setYerelModel").innerHTML = `<option value="">Otomatik (bu bilgisayara göre${y.model && !cur ? ": " + y.model : ""})</option>` +
        y.secenekler.map((m) => `<option value="${m}">${m} (${GB[m] || "?"} GB)</option>`).join("");
      $("#setYerelModel").value = cur;
    }
    clearTimeout(yerelTimer);
    if (y.state === "kuruluyor") yerelTimer = setTimeout(() => refreshYerel(), 3000);
    return y;
  }
  $("#yerelChip").onclick = () => $("#settingsBtn").click();
  $("#yerelHazirla").onclick = async () => {
    try { await postJSON("/api/yerel/hazirla", { model: $("#setYerelModel").value }); } catch (e) { return toast(e.message); }
    refreshYerel();
  };

  // ================================================================ dersini kendisi bulan not ekleme
  async function autoAdd(files) {
    files = [...files].filter((f) => /\.(pdf|png|jpe?g|webp|json)$/i.test(f.name) || f.type.startsWith("image/"));
    if (!files.length) return;
    let hint = "", last = null;
    for (const [i, f] of files.entries()) {
      $("#uploadStatus").textContent = `Ekleniyor ${i + 1}/${files.length}: ${f.name} (dersi bulunuyor)…`;
      toast(`📥 ${f.name}: hangi derse ait olduğuna bakılıyor…`, 2500);
      const fd = new FormData();
      fd.append("file", f, f.name);
      fd.append("ipucu", hint);
      try {
        const r = await api("/api/notes/auto", { method: "POST", body: fd });
        if (r.paket) { toast(`📦 Ders paketi kuruldu: ${r.paket.ders_adi || r.paket.id} (${r.paket.belge} belge)`, 6000); last = r.paket.ders_id; continue; }
        hint = r.ders_id; last = r.ders_id;
        toast(`📥 ${f.name} → ${r.ders_adi}${r.yeni_ders ? " (yeni ders oluşturuldu)" : ""} · ${r.neden}. Yanlışsa notun yanındaki ↪ ile taşı.`, 7000);
      } catch (err) { toast(`${f.name}: ${err.message}`); }
    }
    $("#uploadStatus").textContent = "";
    if (last) { await loadCourses(last); switchTab("notes"); }
  }
  $("#autoInput").addEventListener("change", (e) => { const f = [...e.target.files]; e.target.value = ""; autoAdd(f); });
  // Dosyayı pencerenin herhangi bir yerine sürükleyip bırakma
  window.addEventListener("dragover", (e) => { if (e.dataTransfer?.types?.includes("Files")) { e.preventDefault(); document.body.classList.add("drop"); } });
  window.addEventListener("dragleave", (e) => { if (!e.relatedTarget) document.body.classList.remove("drop"); });
  window.addEventListener("drop", (e) => {
    if (!e.dataTransfer?.files?.length) return;
    e.preventDefault(); document.body.classList.remove("drop");
    autoAdd(e.dataTransfer.files);
  });

  let moving = null;
  function openMove(d) {
    moving = d;
    $("#moveName").textContent = d.name;
    $("#moveTarget").innerHTML = S.courses.filter((c) => c.id !== S.courseId)
      .map((c) => `<option value="${c.id}">${c.name.replace(/</g, "&lt;")}</option>`).join("");
    if (!$("#moveTarget").options.length) return toast("Taşınacak başka ders yok; önce “+ Ders” ile oluştur.");
    $("#moveDlg").showModal();
  }
  $("#moveOk").onclick = async () => {
    if (!moving) return;
    const to = $("#moveTarget").value;
    try {
      await postJSON(`/api/courses/${S.courseId}/docs/${moving.id}/move`, { hedef: to });
      toast(`“${moving.name}” taşındı.`);
      S.course = await api(`/api/courses/${S.courseId}`);
      renderDocs();
    } catch (e) { toast("Taşınamadı: " + e.message); }
    moving = null;
  };

  // Not Kutusu (Masaüstü) ve İndirilenler'den kendiliğinden eklenenleri bildir
  let kutuSon = 0;
  async function kutuKontrol() {
    try {
      const k = await api(`/api/kutu?son=${kutuSon}`);
      $("#kutuInfo").textContent = `📂 Notları ${k.yol} klasörüne de bırakabilirsin: hangi derse ait olduğunu bulup kendiliğinden ekler.`;
      if (k.olaylar.length) {
        kutuSon = k.olaylar[k.olaylar.length - 1].id;
        k.olaylar.forEach((o) => toast(o.mesaj, 7000));
        const cur = S.courseId;
        await loadCourses(cur || k.olaylar.find((o) => o.ders_id)?.ders_id);
      }
    } catch {}
  }
  api("/api/kutu").then((k) => { kutuSon = k.olaylar.length ? k.olaylar[k.olaylar.length - 1].id : 0; kutuKontrol(); }).catch(() => {});
  setInterval(kutuKontrol, 8000);

  // ================================================================ müfredattan ders ekle
  let programs = [];
  function renderCurriculum() {
    const p = programs.find((x) => x.id === $("#curProgram").value);
    if (!p) return;
    $("#curNote").innerHTML = (p.not || "").replace(/</g, "&lt;") + (p.kaynaklar.length ? `<br>Kaynak: ${p.kaynaklar.slice(0, 2).map((u) => `<a href="${u}" target="_blank" rel="noopener">${new URL(u).hostname}</a>`).join(", ")}` : "");
    const have = new Set(S.courses.map((c) => c.profile?.kod).filter(Boolean));
    const bySem = {};
    p.dersler.forEach((d) => (bySem[d.yariyil || 0] ||= []).push(d));
    $("#curList").innerHTML = Object.keys(bySem).sort((a, b) => a - b).map((sem) =>
      `<h4>${sem > 0 ? sem + ". yarıyıl" : "Seçmeli / diğer"}</h4>` + bySem[sem].map((d) =>
        `<label><input type="checkbox" value="${d.kod}" ${have.has(d.kod) ? "checked disabled" : ""}> <span><b>${d.kod}</b> ${d.ad}${d.dil === "İngilizce" ? " 🇬🇧" : ""} <span class="en">${d.ad_en || ""}${have.has(d.kod) ? " · eklendi" : ""}</span></span></label>`
      ).join("")).join("");
  }
  $("#curriculumBtn").onclick = async () => {
    try { programs = await api("/api/curriculum"); } catch (e) { return toast(e.message); }
    if (!programs.length) return toast("Kayıtlı müfredat yok.");
    $("#curProgram").innerHTML = programs.map((p) => `<option value="${p.id}">${p.program}</option>`).join("");
    renderCurriculum();
    $("#curDlg").showModal();
  };
  $("#curProgram").onchange = renderCurriculum;
  $("#curImport").onclick = async () => {
    const codes = [...document.querySelectorAll("#curList input:checked:not(:disabled)")].map((i) => i.value);
    if (!codes.length) return;
    const made = await postJSON("/api/curriculum/import", { program: $("#curProgram").value, codes });
    toast(`${made.length} ders eklendi. Her birinin hocası müfredattaki konuları biliyor.`);
    await loadCourses(made[0]?.id);
  };

  // ================================================================ ders ses kaydı
  $("#recInput").addEventListener("change", async (e) => {
    const f = e.target.files[0];
    e.target.value = "";
    if (!f) return;
    if (!S.courseId) return toast("Önce bir ders seç.");
    $("#uploadStatus").textContent = `Kayıt yükleniyor (${(f.size / 1e6).toFixed(0)} MB)…`;
    const fd = new FormData();
    fd.append("file", f, f.name);
    try {
      await api(`/api/courses/${S.courseId}/recordings`, { method: "POST", body: fd });
      toast("Kayıt yüklendi. Yazıya dökülüp ders notuna çevriliyor; bitince listede görünecek.", 6000);
    } catch (err) { toast("Kayıt yüklenemedi: " + err.message); }
    $("#uploadStatus").textContent = "";
    S.course = await api(`/api/courses/${S.courseId}`);
    renderDocs();
  });
  $("#formulaBtn").onclick = () => {
    if (!S.courseId) return toast("Önce bir ders seç.");
    window.open(`/static/formul.html?c=${S.courseId}`, "_blank");
  };

  // ================================================================ sınav takvimi
  const localDate = (d = new Date()) => d.toLocaleDateString("sv-SE");
  const KIND = { anlat: "Öğren", tekrar: "Tekrar", sinav: "Sına", formul: "Formül" };
  function taskEl(t, courseId, courseName, done) {
    const el = document.createElement("div");
    el.className = "task" + (done ? " done" : "");
    el.innerHTML = `<input type="checkbox" ${done ? "checked" : ""} title="Yaptım">
      <div class="t-main"><div><span class="badge ${t.kind}">${KIND[t.kind] || t.kind}</span> <span class="t-topic"></span> <span class="muted small">${t.minutes} dk${courseName ? " · " + courseName : ""}</span></div><div class="t-detail"></div></div>
      <button class="ghost small">Başla</button>`;
    el.querySelector(".t-topic").textContent = t.topic;
    el.querySelector(".t-detail").textContent = t.detail;
    el.querySelector("input").onchange = async (e) => {
      await postJSON(`/api/courses/${courseId}/schedule/done`, { task_id: t.id, done: e.target.checked });
      el.classList.toggle("done", e.target.checked);
    };
    el.querySelector("button").onclick = () => startTask(t, courseId);
    return el;
  }
  async function startTask(t, courseId) {
    if (courseId !== S.courseId) { $("#courseSelect").value = courseId; await selectCourse(courseId); S.sessionId = ""; }
    if (t.kind === "sinav") {
      switchTab("quiz");
      $("#qTopic").value = t.topic === "Genel deneme" ? "" : t.topic;
      $("#quizBtn").click();
    } else if (t.kind === "formul") {
      window.open(`/static/formul.html?c=${courseId}`, "_blank");
    } else {
      switchTab("chat");
      const what = t.kind === "tekrar" ? "Kısa bir tekrar yapalım, en önemli noktaları ve sık yapılan hataları hatırlat, sonunda bana bir soru sor" : "Bu konuyu bana baştan anlat ve bir örnek çöz";
      ask({ text: `Çalışma takvimimdeki bugünkü görev: ${t.topic}. (${t.detail}) ${what}.`, label: `📅 ${KIND[t.kind]}: ${t.topic}` });
    }
  }
  async function loadPlanTab() {
    const box = $("#todayBox");
    try {
      const td = await api(`/api/today?day=${localDate()}`);
      box.innerHTML = "";
      if (td.exams.length) {
        const ex = document.createElement("div");
        ex.innerHTML = td.exams.map((e) => {
          const left = Math.round((new Date(e.exam_date) - new Date(localDate())) / 864e5);
          return `<span class="exam-chip">${e.course.replace(/</g, "&lt;")} ${e.exam_type}: <b>${left === 0 ? "BUGÜN" : left + " gün"}</b></span>`;
        }).join("");
        box.appendChild(ex);
      }
      if (!td.tasks.length) box.insertAdjacentHTML("beforeend", '<p class="muted">Bugün için görev yok. Aşağıdan bir sınav takvimi oluştur.</p>');
      td.tasks.forEach((t) => box.appendChild(taskEl(t, t.course_id, t.course, t.done)));
    } catch (e) { box.innerHTML = `<p class="muted">${e.message}</p>`; }
    renderSchedule();
  }
  function renderSchedule() {
    const area = $("#schedArea");
    area.innerHTML = "";
    const sc = S.course?.schedule;
    if (!S.course) { area.innerHTML = '<p class="muted">Ders seçilmedi.</p>'; return; }
    if (!sc) { area.innerHTML = '<p class="muted">Bu ders için takvim yok.</p>'; return; }
    $("#exDate").value = sc.exam_date; $("#exType").value = sc.exam_type; $("#exMin").value = sc.minutes; $("#exScope").value = sc.scope || "";
    const today = localDate();
    const total = sc.days.reduce((a, d) => a + d.tasks.length, 0), done = Object.keys(sc.done).length;
    area.insertAdjacentHTML("beforeend", `<p class="muted">İlerleme: ${done}/${total} görev</p>`);
    sc.days.forEach((d) => {
      const h = document.createElement("div");
      h.className = "sched-day" + (d.date === today ? " today" : "");
      const dt = new Date(d.date + "T12:00");
      h.textContent = dt.toLocaleDateString("tr-TR", { weekday: "long", day: "numeric", month: "long" }) + (d.date === today ? " · bugün" : "") + (d.date === sc.exam_date ? " · SINAV" : "");
      area.appendChild(h);
      d.tasks.forEach((t) => area.appendChild(taskEl(t, S.courseId, "", !!sc.done[t.id])));
    });
  }
  $("#schedBtn").onclick = async () => {
    if (!S.courseId) return toast("Önce bir ders seç.");
    if (!$("#exDate").value) return toast("Sınav tarihini seç.");
    $("#schedBtn").disabled = true;
    $("#schedArea").innerHTML = '<p class="muted">Takvim hazırlanıyor… (konuları ve zayıf noktalarını hesaba katıyorum)</p>';
    try {
      await postJSON(`/api/courses/${S.courseId}/schedule`, {
        exam_date: $("#exDate").value, exam_type: $("#exType").value, minutes: Number($("#exMin").value) || 90,
        scope: $("#exScope").value.trim(), today: localDate(),
      });
      S.course = await api(`/api/courses/${S.courseId}`);
      loadPlanTab();
    } catch (e) { $("#schedArea").innerHTML = ""; toast("Hata: " + e.message); }
    $("#schedBtn").disabled = false;
  };

  // ================================================================ dersi baştan anlat
  $("#planBtn").onclick = async () => {
    if (!S.courseId) return toast("Önce bir ders seç.");
    $("#planBtn").disabled = true;
    $("#planStatus").textContent = "Notları okuyup ders planı çıkarıyorum… (bir dakika sürebilir)";
    try {
      S.plan = await postJSON("/api/lecture/plan", { course_id: S.courseId, focus: $("#planFocus").value.trim() });
      $("#planStatus").textContent = S.plan.title + " — başlamak için bir bölüme tıkla.";
      renderPlan();
    } catch (e) { $("#planStatus").textContent = "Hata: " + e.message; }
    $("#planBtn").disabled = false;
  };
  function renderPlan() {
    const ol = $("#planList");
    ol.innerHTML = "";
    S.plan.sections.forEach((s, i) => {
      const li = document.createElement("li");
      li.innerHTML = `<span></span><small></small>`;
      li.querySelector("span").textContent = s.title;
      li.querySelector("small").textContent = s.summary + (s.pages.length ? ` · ${s.pages.join(", ")}` : "");
      li.style.cursor = "pointer";
      li.onclick = () => runSection(i);
      if (i === S.lectureIdx) li.classList.add("current");
      ol.appendChild(li);
    });
  }
  function runSection(i) {
    if (!S.plan || i >= S.plan.sections.length) { S.lectureActive = false; toast("Ders bitti! İstersen Sınav sekmesinden kendini test et."); return; }
    S.lectureIdx = i;
    renderPlan();
    const s = S.plan.sections[i], prev = S.plan.sections[i - 1];
    S.lectureActive = true;
    ask({
      mode: "lecture",
      label: `Bölüm ${i + 1}: ${s.title}`,
      section: { i: i + 1, n: S.plan.sections.length, title: s.title, summary: s.summary, pages: s.pages, prev: prev ? `${prev.title} (${prev.summary})` : "" },
    });
    switchTab("chat");
  }
  function nextSection() { if (S.lectureActive && !player.busy && !S.streamOpen) runSection(S.lectureIdx + 1); }

  // ================================================================ sınav modu
  $("#quizBtn").onclick = async () => {
    if (!S.courseId) return toast("Önce bir ders seç.");
    $("#quizBtn").disabled = true;
    $("#quizArea").innerHTML = '<p class="muted">Sorular hazırlanıyor…</p>';
    try {
      const q = await postJSON("/api/quiz/generate", {
        course_id: S.courseId, count: Number($("#qCount").value) || 5,
        difficulty: $("#qDiff").value, topic: $("#qTopic").value.trim(),
      });
      S.quiz = { questions: q.questions, i: 0, results: [] };
      renderQuestion();
    } catch (e) { $("#quizArea").innerHTML = ""; toast("Hata: " + e.message); }
    $("#quizBtn").disabled = false;
  };
  function speak(text) {
    if (S.settings.tts_enabled === false) {
      const u = new SpeechSynthesisUtterance(text); u.lang = "tr-TR"; speechSynthesis.speak(u); return;
    }
    fetch("/api/tts", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text }) })
      .then((r) => (r.ok ? r.blob() : null)).then((b) => b && new Audio(URL.createObjectURL(b)).play()).catch(() => {});
  }
  function renderQuestion() {
    const Q = S.quiz, q = Q.questions[Q.i], area = $("#quizArea");
    const res = Q.results[Q.i];
    area.innerHTML = "";
    const card = document.createElement("div");
    card.className = "qcard";
    card.innerHTML = `<div class="qnav"><b>Soru ${Q.i + 1}/${Q.questions.length}</b><span class="muted small">${q.topic}${q.page ? " · " + q.page : ""}</span><div class="spacer"></div>
      <button class="ghost small" data-k="prev">◀</button><button class="ghost small" data-k="next">▶</button></div>
      <div class="q"></div>`;
    card.querySelector(".q").innerHTML = BoardUtil.renderInline(q.question);
    let chosen = res?.answer || "";
    let photo = null;
    if (q.kind === "coktan_secmeli" && q.choices.length) {
      const ch = document.createElement("div");
      ch.className = "choices";
      q.choices.forEach((c, k) => {
        const b = document.createElement("button");
        b.innerHTML = `<b>${"ABCDE"[k]})</b> ` + BoardUtil.renderInline(c);
        if (chosen === c) b.classList.add("sel");
        b.onclick = () => { chosen = c; ch.querySelectorAll("button").forEach((x) => x.classList.remove("sel")); b.classList.add("sel"); };
        ch.appendChild(b);
      });
      card.appendChild(ch);
    } else {
      const ta = document.createElement("textarea");
      ta.placeholder = "Cevabını / çözümünü yaz… ya da kâğıda çözüp fotoğrafını ekle.";
      ta.value = chosen;
      ta.oninput = () => (chosen = ta.value);
      card.appendChild(ta);
      const lab = document.createElement("label");
      lab.className = "ghost small file-label";
      lab.innerHTML = '📷 Çözümün fotoğrafı <input type="file" accept="image/*" hidden>';
      lab.querySelector("input").onchange = (e) => { photo = e.target.files[0] || null; lab.firstChild.textContent = photo ? "📷 " + photo.name + " " : "📷 Çözümün fotoğrafı "; };
      card.appendChild(lab);
    }
    const row = document.createElement("div");
    row.className = "row";
    row.innerHTML = '<button class="primary small" data-k="check">Kontrol et</button><button class="ghost small" data-k="explain">Tahtada çöz ve anlat</button>';
    card.appendChild(row);
    const fb = document.createElement("div");
    if (res) showFeedback(fb, res);
    card.appendChild(fb);
    area.appendChild(card);
    const score = Q.results.filter(Boolean);
    if (score.length) {
      const p = document.createElement("p");
      p.className = "muted";
      p.textContent = `Puan: ${score.reduce((a, r) => a + r.score, 0).toFixed(1)} / ${score.length} cevaplanan`;
      area.appendChild(p);
    }

    card.querySelector('[data-k="prev"]').onclick = () => { if (Q.i > 0) { Q.i--; renderQuestion(); } };
    card.querySelector('[data-k="next"]').onclick = () => { if (Q.i < Q.questions.length - 1) { Q.i++; renderQuestion(); } };
    card.querySelector('[data-k="check"]').onclick = async (e) => {
      if (!chosen && !photo) return toast("Önce cevap ver.");
      e.target.disabled = true;
      fb.className = "fb"; fb.textContent = "Değerlendiriyorum…";
      const fd = new FormData();
      fd.append("question", JSON.stringify(q));
      fd.append("answer", chosen);
      fd.append("course_id", S.courseId);
      if (photo) fd.append("image", photo, photo.name);
      try {
        const g = await api("/api/quiz/grade", { method: "POST", body: fd });
        Q.results[Q.i] = { ...g, answer: chosen };
        showFeedback(fb, g);
        speak(g.feedback);
        loadWeak();
      } catch (err) { fb.textContent = "Hata: " + err.message; }
      e.target.disabled = false;
    };
    card.querySelector('[data-k="explain"]').onclick = () => {
      const choices = q.choices.length ? "\nŞıklar: " + q.choices.map((c, k) => `${"ABCDE"[k]}) ${c}`).join("  ") : "";
      const mine = chosen ? `\nBenim cevabım: ${chosen}` : "";
      const files = photo ? [photo] : [];
      switchTab("chat");
      ask({ text: `Bu sınav sorusunu bana tahtada adım adım çöz ve anlat:\n${q.question}${choices}${mine}`, files, label: `Sınav sorusu ${Q.i + 1}: tahtada çöz` });
    };
  }
  function showFeedback(fb, g) {
    fb.className = "fb " + (g.correct ? "ok" : "bad");
    fb.innerHTML = `<b>${g.correct ? "✔ Doğru" : "✘ Tam değil"}</b> (${Math.round(g.score * 100)}%) — ` + BoardUtil.renderInline(g.feedback);
  }
  async function loadWeak() {
    const ul = $("#weakList");
    if (!S.courseId) { ul.innerHTML = '<li class="muted">Ders seçilmedi.</li>'; return; }
    try {
      const rows = await api(`/api/memory/${S.courseId}`);
      ul.innerHTML = rows.length ? "" : '<li class="muted">Henüz kayıt yok.</li>';
      rows.forEach((r) => {
        const li = document.createElement("li");
        li.innerHTML = `<span></span><button class="ghost small">Tekrar anlat</button>`;
        li.querySelector("span").textContent = `${r.konu} — ` + [r.yanlis && `${r.yanlis} yanlış`, r.dogru && `${r.dogru} doğru`, r.zorlandi && `${r.zorlandi} kez zorlandın`].filter(Boolean).join(", ");
        li.querySelector("button").onclick = () => { switchTab("chat"); ask({ text: `“${r.konu}” konusunda zorlanıyorum. Bana bu konuyu baştan, en çok hata yapılan noktalara odaklanarak anlat ve bir örnek çöz.` }); };
        ul.appendChild(li);
      });
    } catch { ul.innerHTML = ""; }
  }

  // ================================================================ kayıtlar
  async function loadRecords() {
    const ul = $("#recordList");
    const rows = await api("/api/sessions");
    ul.innerHTML = rows.length ? "" : '<li class="muted">Henüz kayıt yok.</li>';
    rows.forEach((r) => {
      const li = document.createElement("li");
      const course = S.courses.find((c) => c.id === r.course_id);
      li.innerHTML = `<span class="name"></span><span class="muted small"></span><button class="ghost small" data-k="show" title="Tahtayı anında göster">⚡</button><button class="ghost small" data-k="del" title="Sil">🗑</button>`;
      li.querySelector(".name").textContent = r.title;
      li.querySelector(".small").textContent = `${new Date(r.updated * 1000).toLocaleString("tr-TR", { dateStyle: "short", timeStyle: "short" })} · ${r.steps} adım${course ? " · " + course.name : ""}`;
      li.onclick = (e) => { if (e.target.tagName !== "BUTTON") openRecord(r.id, false); };
      li.querySelector('[data-k="show"]').onclick = () => openRecord(r.id, true);
      li.querySelector('[data-k="del"]').onclick = async () => {
        if (!confirm("Bu kayıt silinsin mi?")) return;
        await api(`/api/sessions/${r.id}`, { method: "DELETE" });
        loadRecords();
      };
      ul.appendChild(li);
    });
  }
  async function openRecord(sid, instant) {
    S.stream?.abort(); player.stop(); S.lectureActive = false;
    const s = await api(`/api/sessions/${sid}`);
    if (s.course_id && s.course_id !== S.courseId) { $("#courseSelect").value = s.course_id; await selectCourse(s.course_id); }
    S.sessionId = sid;
    board.clear();
    $("#chatLog").innerHTML = "";
    switchTab("chat");
    for (const t of s.timeline) {
      if (t.type === "user") { addMsg("user", t.text, t.attachments); S.tutorBubble = addMsg("tutor", ""); }
      else if (t.type === "step") {
        if (instant) { await board.renderInstant(t.board); if (S.tutorBubble && t.say) S.tutorBubble.textContent += " " + t.say; }
        else player.enqueue({ ...t });
      }
    }
    toast(instant ? "Kayıt yüklendi. Sorunu yazarak kaldığın yerden devam edebilirsin." : "Kayıt oynatılıyor…");
  }

  // ================================================================ ayarlar
  async function loadSettings() {
    S.settings = await api("/api/settings");
  }
  $("#settingsBtn").onclick = async () => {
    await loadSettings();
    const st = S.settings, sel = $("#setVoice");
    sel.innerHTML = `<option value="${st.voice_id}">${st.voice_name || st.voice_id}</option>`;
    $("#setTtsModel").value = st.tts_model;
    $("#setLevel").value = st.level;
    $("#setProvider").value = st.tts_provider || "edge";
    $("#setDeep").value = st.deep_solve || "auto";
    api("/api/llm-options").then((o) => {
      $("#setLlm").value = st.llm_provider || "";
      $("#setGeminiModel").innerHTML = `<option value="">Otomatik (önerilen)${o.gemini_auto ? ": " + o.gemini_auto : ""}</option>` +
        o.gemini_models.map((m) => `<option>${m}</option>`).join("");
      $("#setGeminiModel").value = o.gemini_models.includes(st.gemini_model) ? st.gemini_model : "";
      $("#llmInfo").textContent = `Şu an anlatan: ${o.brain}.` + (o.gemini_error ? " Gemini: " + o.gemini_error : "");
    }).catch(() => {});
    $("#setStt").value = st.stt_provider || "whisper";
    $(".settings").dataset.prov = $("#setProvider").value;
    api("/api/voice-options").then((o) => {
      $("#setEdgeVoice").innerHTML = Object.entries(o.edge).map(([k, v]) => `<option value="${k}">${v}</option>`).join("");
      $("#setEdgeVoice").value = st.edge_voice;
      $("#sampleStatus").textContent = o.sample ? "✔ Ses örneği kayıtlı" : "Henüz ses örneği yok";
    }).catch(() => {});
    $("#setWeb").checked = !!st.web_search;
    $("#set3d").checked = localGet("hoca3d") !== "0";
    $("#setConvStt").value = localGet("convStt") === "whisper" || !window.BrowserConversation?.available() ? "whisper" : "browser";
    ["keyGemini", "keyEleven"].forEach((id) => ($("#" + id).value = ""));
    refreshYerel(true);
    api("/api/keys").then((k) => {
      $("#keyGemini").placeholder = k.gemini ? `kayıtlı: ${k.gemini}` : "boş bırakabilirsin";
      $("#keyEleven").placeholder = k.elevenlabs ? `kayıtlı: ${k.elevenlabs}` : "boş bırakabilirsin";
    }).catch(() => {});
    $("#setSens").value = localGet("sens") || "1";
    $("#settingsDlg").showModal();
    if (st.tts_provider !== "elevenlabs") return;
    try {
      const voices = await api("/api/voices");
      sel.innerHTML = voices.map((v) => {
        const tag = v.category === "cloned" ? "🎙 klon" : v.language === "tr" ? "TR" : v.language;
        return `<option value="${v.voice_id}" data-name="${v.name.replace(/"/g, "")}" data-preview="${v.preview_url || ""}">${v.name} (${tag}${v.gender ? ", " + v.gender : ""})</option>`;
      }).join("");
      sel.value = st.voice_id;
    } catch (e) { toast("Ses listesi alınamadı: " + e.message); }
  };
  $("#setProvider").onchange = async (e) => {
    $(".settings").dataset.prov = e.target.value;
    if (e.target.value === "elevenlabs" && $("#setVoice").options.length < 2) {
      try {
        const voices = await api("/api/voices");
        $("#setVoice").innerHTML = voices.map((v) => `<option value="${v.voice_id}" data-name="${v.name.replace(/"/g, "")}" data-preview="${v.preview_url || ""}">${v.name} (${v.category === "cloned" ? "🎙 klon" : v.language})</option>`).join("");
        $("#setVoice").value = S.settings.voice_id;
      } catch (err) { toast("Ses listesi alınamadı: " + err.message); }
    }
  };
  $("#previewVoice").onclick = async () => {
    const prov = $("#setProvider").value;
    const o = $("#setVoice").selectedOptions[0];
    if (prov === "elevenlabs" && o?.dataset.preview) return new Audio(o.dataset.preview).play();
    await $("#saveSettings").onclick();  // seçimi kaydedip o sesle örnek cümle söylet
    toast(prov === "xtts" ? "Yerel klon ilk seferde modeli yüklüyor, biraz sürebilir…" : "Örnek cümle hazırlanıyor…");
    speak("Merhaba, bugün birlikte çalışalım. Takıldığın yeri bana sorabilirsin.");
  };
  async function uploadSample(blob, name) {
    $("#sampleStatus").textContent = "Yükleniyor…";
    const fd = new FormData();
    fd.append("file", blob, name);
    try {
      const r = await api("/api/voice-sample", { method: "POST", body: fd });
      $("#sampleStatus").textContent = `✔ ${r.seconds} sn ses örneği kaydedildi, hoca artık senin sesinle konuşacak`;
      $("#setProvider").value = "xtts"; $(".settings").dataset.prov = "xtts";
      S.settings = await api("/api/settings");
    } catch (e) { $("#sampleStatus").textContent = "Hata: " + e.message; }
  }
  $("#sampleFile").onchange = (e) => { const f = e.target.files[0]; if (f) uploadSample(f, f.name); e.target.value = ""; };
  let sampleRec = null;
  $("#recSample").onclick = async () => {
    if (sampleRec) { sampleRec.stop(); return; }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: false, noiseSuppression: true } });
      const parts = [];
      sampleRec = new MediaRecorder(stream);
      sampleRec.ondataavailable = (e) => e.data.size && parts.push(e.data);
      sampleRec.onstop = () => {
        stream.getTracks().forEach((t) => t.stop());
        $("#recSample").classList.remove("rec"); $("#recSample").textContent = "🎙 Okuyarak kaydet";
        uploadSample(new Blob(parts, { type: sampleRec.mimeType }), "ornek.webm");
        sampleRec = null;
      };
      sampleRec.start();
      $("#recSample").classList.add("rec"); $("#recSample").textContent = "⏹ Bitir";
      $("#sampleStatus").textContent = "Kaydediliyor… metni okuyunca Bitir'e bas";
    } catch (e) { toast("Mikrofon açılamadı: " + e.message); }
  };
  $("#saveSettings").onclick = async () => {
    const keys = {};
    if ($("#keyGemini").value.trim()) keys.gemini = $("#keyGemini").value.trim();
    if ($("#keyEleven").value.trim()) keys.elevenlabs = $("#keyEleven").value.trim();
    if (Object.keys(keys).length) {
      try { await postJSON("/api/keys", keys); toast("Anahtarlar kaydedildi."); }
      catch (e) { toast("Anahtar kaydedilemedi: " + e.message); }
    }
    const yModel = $("#setYerelModel").value;
    if (yModel !== (S.settings.yerel_model || "")) {
      postJSON("/api/yerel/hazirla", { model: yModel }).then(() => refreshYerel()).catch((e) => toast(e.message));
    }
    const o = $("#setVoice").selectedOptions[0];
    S.settings = await postJSON("/api/settings", {
      voice_id: $("#setVoice").value || S.settings.voice_id,
      voice_name: o?.dataset.name || o?.textContent || S.settings.voice_name,
      tts_model: $("#setTtsModel").value,
      level: $("#setLevel").value,
      tts_provider: $("#setProvider").value,
      llm_provider: $("#setLlm").value,
      gemini_model: $("#setGeminiModel").value,
      deep_solve: $("#setDeep").value,
      edge_voice: $("#setEdgeVoice").value || S.settings.edge_voice,
      stt_provider: $("#setStt").value,
      web_search: $("#setWeb").checked,
    });
    localSet("sens", $("#setSens").value);
    localSet("hoca3d", $("#set3d").checked ? "1" : "0");
    localSet("convStt", $("#setConvStt").value);
    enable3D($("#set3d").checked);
    if (S.conv) S.conv.sensitivity = Number($("#setSens").value);
    toast("Ayarlar kaydedildi.");
  };

  // ---------------- 3B hoca modeli (GLB)
  async function reload3D() { if (teacher3d) { await enable3D(false); await enable3D(true); } }
  $("#glbInput").onchange = async (e) => {
    const f = e.target.files[0]; e.target.value = "";
    if (!f) return;
    $("#glbStatus").textContent = "Yükleniyor…";
    const fd = new FormData(); fd.append("file", f, f.name);
    try {
      const r = await api("/api/teacher-model", { method: "POST", body: fd });
      $("#glbStatus").textContent = `✔ Model yüklendi (${r.mb} MB)`;
      await reload3D();
    } catch (err) { $("#glbStatus").textContent = "Hata: " + err.message; }
  };
  $("#glbFlip").onclick = async () => { localSet("hocaCevir", localGet("hocaCevir") === "1" ? "0" : "1"); await reload3D(); };
  $("#glbReset").onclick = async () => { await api("/api/teacher-model", { method: "DELETE" }); $("#glbStatus").textContent = "Varsayılan hocaya dönüldü."; await reload3D(); };

  // ---------------- tema: otomatik → açık → koyu
  const THEMES = [["", "🌓", "Tema: otomatik (sistem)"], ["light", "☀️", "Tema: açık (kâğıt)"], ["dark", "🌙", "Tema: koyu (gece)"]];
  function applyTheme(t) {
    if (t) document.documentElement.dataset.theme = t; else delete document.documentElement.dataset.theme;
    const [, icon, title] = THEMES.find((x) => x[0] === t) || THEMES[0];
    $("#themeBtn").textContent = icon; $("#themeBtn").title = title;
  }
  applyTheme(localGet("tema") || "");
  $("#themeBtn").onclick = () => {
    const cur = localGet("tema") || "";
    const next = THEMES[(THEMES.findIndex((x) => x[0] === cur) + 1) % THEMES.length][0];
    localSet("tema", next); applyTheme(next); toast(THEMES.find((x) => x[0] === next)[2], 2000);
  };

  function localGet(k) { try { return localStorage.getItem("ders." + k); } catch { return null; } }
  function localSet(k, v) { try { localStorage.setItem("ders." + k, v); } catch {} }

  // ================================================================ telefon
  $("#phoneBtn").onclick = async () => {
    const info = await api("/api/connect-info").catch(() => ({}));
    const body = $("#phoneBody");
    if (info.url) {
      let qr = "";
      if (window.qrcode) { const q = qrcode(0, "M"); q.addData(info.url); q.make(); qr = q.createSvgTag({ cellSize: 5, margin: 2 }); }
      body.innerHTML = `<div style="text-align:center;background:#fff;border-radius:8px;padding:8px">${qr}</div>
        <p>Telefonun kamerasıyla QR kodu okut ya da adresi aç:<br><a href="${info.url}" target="_blank">${info.url}</a></p>
        ${typeof info.password === "string" ? `<p>Şifre: <b>${info.password.replace(/</g, "&lt;")}</b></p>` : ""}
        <p class="muted small">Açılınca tarayıcı menüsünden “Ana ekrana ekle” dersen uygulama gibi çalışır. Bilgisayar açık ve uygulama çalışıyor olmalı.</p>`;
    } else {
      body.innerHTML = `<p>Telefondan kullanmak için uygulamayı bilgisayarda <b>telefon modunda</b> başlat:</p>
        <ol><li>Bir kez <b>cloudflared</b> kur (ücretsiz):<br><code>winget install Cloudflare.cloudflared</code> (Windows) ya da <code>brew install cloudflared</code> (Mac)</li>
        <li><b>Telefondan Kullan.bat</b> dosyasına çift tıkla (ya da <code>python baslat.py --telefon</code>).</li>
        <li>Bu pencereyi tekrar aç: QR kod ve şifre burada görünecek.</li></ol>
        <p class="muted small">Neden gerekli? Telefon tarayıcıları mikrofonu yalnızca güvenli (https) adreslerde açar. Tünel bu adresi ücretsiz verir; şifre de başkalarının girmesini engeller.</p>`;
    }
    $("#phoneDlg").showModal();
  };

  // ================================================================ başlat
  loadSettings().catch(() => {});
  // Masaüstü uygulaması: pencere açık olduğu sürece sunucuya "buradayım" de (kapanınca sunucu kendini kapatır)
  const ping = () => fetch("/api/ping", { method: "POST" }).catch(() => {});
  ping(); setInterval(ping, 20000);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) ping(); });
  // Güncellemeden sonraki ilk açılışta neyin yenilendiğini söyle
  api("/api/version").then((v) => {
    if (v.sha && localGet("seenVersion") !== v.sha) {
      if (localGet("seenVersion")) toast("Uygulama güncellendi: " + v.message, 8000);
      localSet("seenVersion", v.sha);
    }
  }).catch(() => {});
  // Yerel yapay zeka: ilk açılışta kendiliğinden kurulur; durum üst çubukta görünür
  refreshYerel().then((y) => {
    if (y && y.state === "kuruluyor") toast("Yapay zeka bu bilgisayara ilk kez kuruluyor (bir kerelik indirme). Bitince hoca kendiliğinden çalışır.", 9000);
  });
  if (localGet("hoca3d") !== "0" && !matchMedia("(prefers-reduced-motion: reduce)").matches) enable3D(true);
  loadCourses().catch((e) => toast("Sunucuya bağlanılamadı: " + e.message));
})();
