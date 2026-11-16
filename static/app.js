/* Arayüz mantığı: sohbet, sesli soru, notlar, ders anlatımı, sınav ve kayıtlar. */
(function () {
  const $ = (s) => document.querySelector(s);
  const board = new Board($("#board"));
  const S = {
    courses: [], courseId: "", course: null, sessionId: "",
    attachments: [], pageCtx: null, viewer: { doc: null, page: 1 },
    stream: null, streamOpen: false, tutorBubble: null,
    plan: null, lectureIdx: -1, lectureActive: false,
    settings: {}, quiz: null, micPausedPlayer: false,
  };

  const player = new Player(board, {
    onStep(step) {
      $("#caption").textContent = step.say || "";
      if (S.tutorBubble && step.say) {
        S.tutorBubble.textContent += (S.tutorBubble.textContent ? " " : "") + step.say;
        scrollChat();
      }
    },
    onState(st) {
      $("#playBtn").textContent = st === "paused" ? "▶" : "⏸";
    },
    onIdle() {
      if (!S.streamOpen) {
        $("#caption").textContent = "";
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
  }
  document.querySelectorAll(".tabs button").forEach((b) => b.addEventListener("click", () => switchTab(b.dataset.tab)));

  // ================================================================ anlatım isteği (SSE akışı)
  async function ask({ text = "", mode = "chat", doc_id = "", page = 0, section = null, files = [], label = "" }) {
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
    files.forEach((f) => fd.append("files", f, f.name));

    const shown = label || text || (doc_id ? `Sayfa ${page}` : "");
    addMsg("user", shown + (ctx && mode === "chat" ? `  (📄 ${ctx.label})` : ""), files.map((f) => f.name));
    S.tutorBubble = addMsg("tutor", "");
    $("#caption").textContent = "Düşünüyor…";

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
        addMsg("err", "Hata: " + e.message);
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
      case "error": addMsg("err", ev.message); $("#caption").textContent = ""; S.lectureActive = false; break;
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
    renderDocs();
    loadWeak();
  }
  $("#courseSelect").onchange = (e) => { S.sessionId = ""; selectCourse(e.target.value); };
  $("#newCourseBtn").onclick = async () => {
    const name = prompt("Ders adı (ör. Diferansiyel Denklemler):");
    if (!name) return;
    const c = await postJSON("/api/courses", { name });
    await loadCourses(c.id);
    switchTab("notes");
  };

  function renderDocs() {
    const ul = $("#docList");
    ul.innerHTML = "";
    $("#pageViewer").classList.add("hidden");
    if (!S.course) { ul.innerHTML = '<li class="muted">Önce üstten bir ders seç ya da “+ Ders” ile oluştur.</li>'; return; }
    if (!S.course.docs.length) { ul.innerHTML = '<li class="muted">Bu derste henüz not yok. PDF ya da defter fotoğrafı yükle.</li>'; }
    let pendingOcr = 0;
    S.course.docs.forEach((d) => {
      const ocr = d.pages.filter((p) => p.needs_ocr).length;
      pendingOcr += ocr;
      const li = document.createElement("li");
      li.innerHTML = `<span>${d.kind === "pdf" ? "📕" : "🖼️"}</span><span class="name"></span><span class="muted small">${d.pages.length} sf${ocr ? ` · ${ocr} okunuyor…` : ""}</span><button class="ghost small" title="Sil">🗑</button>`;
      li.querySelector(".name").textContent = d.name;
      li.onclick = (e) => { if (e.target.tagName === "BUTTON") return; openViewer(d, 1); };
      li.querySelector("button").onclick = async () => {
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
    $("#pvImg").src = `/api/courses/${S.courseId}/docs/${doc.id}/pages/${S.viewer.page}.png`;
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
    if (!S.courseId) { toast("Önce bir ders seç ya da oluştur."); e.target.value = ""; return; }
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

  // ================================================================ dersi baştan anlat
  $("#planBtn").onclick = async () => {
    if (!S.courseId) return toast("Önce bir ders seç.");
    $("#planBtn").disabled = true;
    $("#planStatus").textContent = "Notları okuyup ders planı çıkarıyorum… (bir dakika sürebilir)";
    try {
      S.plan = await postJSON("/api/lecture/plan", { course_id: S.courseId });
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
    $("#setEffort").value = st.effort;
    $("#setTts").checked = st.tts_enabled !== false;
    $("#settingsDlg").showModal();
    try {
      const voices = await api("/api/voices");
      sel.innerHTML = voices.map((v) => {
        const tag = v.category === "cloned" ? "🎙 klon" : v.language === "tr" ? "TR" : v.language;
        return `<option value="${v.voice_id}" data-name="${v.name.replace(/"/g, "")}" data-preview="${v.preview_url || ""}">${v.name} (${tag}${v.gender ? ", " + v.gender : ""})</option>`;
      }).join("");
      sel.value = st.voice_id;
    } catch (e) { toast("Ses listesi alınamadı: " + e.message); }
  };
  $("#previewVoice").onclick = () => {
    const o = $("#setVoice").selectedOptions[0];
    if (o?.dataset.preview) new Audio(o.dataset.preview).play();
    else speak("Merhaba, bugün birlikte çalışalım. Takıldığın yeri bana sorabilirsin.");
  };
  $("#saveSettings").onclick = async () => {
    const o = $("#setVoice").selectedOptions[0];
    S.settings = await postJSON("/api/settings", {
      voice_id: $("#setVoice").value,
      voice_name: o?.dataset.name || o?.textContent || "",
      tts_model: $("#setTtsModel").value,
      level: $("#setLevel").value,
      effort: $("#setEffort").value,
      tts_enabled: $("#setTts").checked,
    });
    toast("Ayarlar kaydedildi.");
  };

  function localGet(k) { try { return localStorage.getItem("ders." + k); } catch { return null; } }
  function localSet(k, v) { try { localStorage.setItem("ders." + k, v); } catch {} }

  // ================================================================ başlat
  loadSettings().catch(() => {});
  loadCourses().catch((e) => toast("Sunucuya bağlanılamadı: " + e.message));
})();
