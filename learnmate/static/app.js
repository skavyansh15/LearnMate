"use strict";
// LearnMate AI front end - plain JavaScript. All text is added with textContent (never innerHTML), so it is XSS-safe.
const $ = id => document.getElementById(id);
const state = { video: null };

function el(tag, props = {}, ...kids) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === "class") n.className = v;
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else if (v !== undefined && v !== null && v !== false) n.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat()) if (kid !== null && kid !== undefined && kid !== false) n.append(kid);
  return n;
}
const put = (node, ...kids) => node.replaceChildren(...kids.flat().filter(k => k !== null && k !== undefined && k !== false));
const fmt = s => { s = Math.floor(s || 0); return Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0"); };
let toastTimer;
function toast(msg) {
  const t = $("toast"); t.textContent = msg; t.style.display = "block";
  clearTimeout(toastTimer); toastTimer = setTimeout(() => { t.style.display = "none"; }, 6000);
}

async function api(path, { method = "GET", json, form } = {}) {
  const opt = { method, headers: { "X-Requested-With": "fetch" } };
  if (json) { opt.headers["Content-Type"] = "application/json"; opt.body = JSON.stringify(json); }
  if (form) opt.body = form;
  let res;
  try { res = await fetch(path, opt); } catch { throw new Error("Cannot reach the server. Is it running?"); }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) { const e = data.error || {}; throw new Error((e.message || "Request failed.") + (e.hint ? " " + e.hint : "")); }
  return data;
}
const guard = fn => async (...a) => { try { await fn(...a); } catch (e) { toast(e.message); } };

// ---------- answers with clickable citations --------------------------------
function jump(src) {
  if (src.time !== null && src.time !== undefined && state.video) { state.video.currentTime = src.time; state.video.play(); }
}
function answerBlock(d) {
  const by = Object.fromEntries(d.sources.map(s => [s.n, s]));
  const parts = d.answer.split(/((?<![\w)])\[\d+\])/).map(p => {
    const m = p.match(/^\[(\d+)\]$/);
    if (!m) return p;
    const s = by[m[1]];
    return s ? el("button", { class: "cite", type: "button", title: s.label, onclick: () => jump(s) }, String(s.n)) : "";
  });
  const srcs = d.sources.map(s => el("button", { class: "src", type: "button", onclick: () => jump(s) },
    el("b", {}, `[${s.n}] ${s.label}`), el("span", {}, s.snippet)));
  return [el("span", {}, parts), ...srcs, d.warning ? el("small", { class: "warn" }, d.warning) : null,
    d.mode === "demo" && d.status === "ok" ? el("small", {}, "Demo mode: text taken directly from the course.") : null].filter(Boolean);
}

// ---------- course tutor chatbot -----------------------------------------------------------------
function chat(scope, getTime) {
  const msgs = el("div", { class: "msgs" });
  const history = [];
  
  const botIntro = el("div", { class: "msg bot" },
    el("b", { style: "display:block;margin-bottom:4px;color:var(--primary)" }, "🤖 LearnMate Course Chatbot"),
    el("span", {}, "Hello! I am your AI course tutor. I am strictly grounded in what you have watched up to the current timestamp and course documents. Ask me anything!")
  );
  msgs.append(botIntro);

  const input = el("input", { placeholder: "Ask chatbot a question about the video...", maxlength: 500, required: true, "aria-label": "Your question" });
  
  const suggestions = el("div", { class: "chat-suggestions", style: "display:flex;gap:6px;flex-wrap:wrap;margin-bottom:10px" },
    el("button", { class: "action-pill", type: "button", onclick: () => { input.value = "What did the instructor just explain?"; form.requestSubmit(); } }, "💡 What was just explained?"),
    el("button", { class: "action-pill", type: "button", onclick: () => { input.value = "Summarize the key points covered so far"; form.requestSubmit(); } }, "📝 Summarize so far"),
    el("button", { class: "action-pill", type: "button", onclick: () => { input.value = "Explain the last concept in simple terms"; form.requestSubmit(); } }, "🔍 Simplify last concept")
  );

  const form = el("form", { class: "row", onsubmit: guard(async e => {
    e.preventDefault();
    const q = input.value.trim(); if (!q) return;
    input.value = "";
    if (state.video) state.video.pause();
    const t = getTime();
    msgs.append(el("div", { class: "msg user" }, q, t !== null ? el("small", {}, "watched at " + fmt(t)) : null));
    const wait = el("div", { class: "msg bot" }, "Thinking based on covered content...");
    msgs.append(wait); msgs.scrollTop = msgs.scrollHeight;
    try {
      const d = await api("/api/ask", { method: "POST", json: { course_id: state.course.id, question: q, scope, current_time: t, history: history.slice(-6) } });
      wait.replaceChildren(...answerBlock(d));
      if (d.status === "not_found") wait.classList.add("nf");
      else history.push({ role: "user", content: q }, { role: "assistant", content: d.answer });
    } catch (err) { wait.textContent = err.message; wait.classList.add("err"); }
    msgs.scrollTop = msgs.scrollHeight;
  }) }, input, el("button", { class: "btn" }, "Send"));

  const lockNote = scope === "video" 
    ? "🔒 Chatbot is strictly locked to what you've watched up to the current video timestamp." 
    : "📄 Chatbot answers using your uploaded course documents.";
    
  return el("div", { class: "chatbot-container" },
    el("div", { class: "chatbot-header-bar", style: "display:flex;align-items:center;justify-content:space-between;margin-bottom:8px" },
      el("small", { class: "hint", style: "font-weight:600" }, lockNote),
      el("button", { class: "btn alt small", type: "button", style: "padding:2px 8px;font-size:11px", onclick: () => { msgs.replaceChildren(botIntro); history.length = 0; } }, "Clear Chat")
    ),
    suggestions,
    msgs,
    form
  );
}

// ---------- study tools & smart quiz -------------------------------------------------------------
function quizUI(d) {
  const answers = d.questions.map(() => null);
  const boxes = d.questions.map((q, i) => el("div", { class: "q" }, el("b", {}, `${i + 1}. ${q.q}`),
    q.options.map((o, j) => el("label", {}, el("input", { type: "radio", name: `q${i}`, onchange: () => { answers[i] = j; } }), o))));
  const result = el("div");
  const submit = el("button", { class: "btn", onclick: guard(async () => {
    const r = await api(`/api/quiz/${d.quiz_id}/grade`, { method: "POST", json: { answers } });
    submit.disabled = true;
    boxes.forEach((b, i) => {
      const x = r.results[i];
      b.classList.add(x.correct ? "right" : "wrong");
      b.querySelectorAll("input").forEach(inp => { inp.disabled = true; });
      b.append(el("small", {}, (x.correct ? "Correct. " : `Answer: ${d.questions[i].options[x.answer]}. `) + x.explanation),
        el("button", { class: "src", type: "button", onclick: () => jump(x.source) }, el("b", {}, x.source.label), el("span", {}, x.source.snippet)));
    });
    result.textContent = `Score: ${r.score} / ${r.total}`;
  }) }, "Check answers");
  return el("div", {}, d.warning ? el("small", { class: "warn" }, d.warning) : null, boxes, submit, el("h3", {}, result));
}

function studyTab() {
  const out = el("div"); const course = state.course;
  const hasVideoCues = course.has_video && course.duration > 0;
  const scopeSel = el("select", { "aria-label": "Study material" }, el("option", { value: hasVideoCues ? "video" : "docs" }, hasVideoCues ? "Video watched so far" : "My documents"));
  if (hasVideoCues && course.documents.length && !course.demo) scopeSel.append(el("option", { value: "docs" }, "My documents"));
  const base = () => ({ course_id: course.id, scope: scopeSel.value, current_time: (scopeSel.value === "video" && state.video) ? state.video.currentTime : 0 });
  const run = (btn, label, fn) => guard(async () => {
    btn.disabled = true; out.replaceChildren(el("p", { class: "hint" }, "Working on " + label + "..."));
    try { await fn(); } catch (e) { out.replaceChildren(); throw e; } finally { btn.disabled = false; }
  });
  const show = d => out.replaceChildren(d.status === "ok" ? el("div", { class: "msg bot" }, ...answerBlock(d)) : el("div", { class: "msg bot nf" }, d.answer));
  const mk = (label, kind) => { const b = el("button", { class: "btn small" }, label); b.onclick = run(b, label.toLowerCase(), async () => show(await api("/api/study", { method: "POST", json: { ...base(), kind } }))); return b; };
  const quizBtn = el("button", { class: "btn small" }, "🎯 AI Smart Quiz");
  quizBtn.onclick = run(quizBtn, "an AI-selected quiz based on covered concepts", async () => {
    const d = await api("/api/quiz", { method: "POST", json: { ...base(), count: 5 } });
    out.replaceChildren(d.status === "ok" ? quizUI(d) : el("div", { class: "msg bot nf" }, d.answer));
  });
  const a = el("input", { placeholder: "Concept A", maxlength: 60, "aria-label": "Concept A" });
  const b = el("input", { placeholder: "Concept B", maxlength: 60, "aria-label": "Concept B" });
  const cmp = el("button", { class: "btn small alt" }, "Compare");
  cmp.onclick = run(cmp, "the comparison", async () => show(await api("/api/study", { method: "POST", json: { ...base(), kind: "compare", a: a.value, b: b.value } })));
  return el("div", {}, el("label", {}, "Study Scope"), scopeSel, el("div", { class: "tools", style: "margin-top:12px" }, mk("Summary", "summary"), mk("Revision notes", "notes"), quizBtn),
    el("div", { class: "row" }, a, b, cmp), el("div", { style: "margin-top:14px" }, out));
}

// ---------- documents ------------------------------------------------------------------
function docsTab() {
  const c = state.course;
  if (c.demo) return el("p", { class: "hint" }, "The demo course's PDF and slides (lecture_notes.pdf, lecture_slides.pptx) are unlocked by the video: they appear as sources in the Ask tab once you have watched that part. Create your own course to upload files.");
  const file = el("input", { type: "file", accept: ".pdf,.pptx,.txt,.md,.csv,.docx", "aria-label": "Document file" });
  const up = el("button", { class: "btn small" }, "Upload");
  up.onclick = guard(async () => {
    if (!file.files[0]) throw new Error("Choose a file (.pdf, .pptx, .txt, .docx, .md, .csv) first.");
    const fd = new FormData(); fd.append("file", file.files[0]);
    up.disabled = true;
    try { await api(`/api/courses/${c.id}/documents`, { method: "POST", form: fd }); toast("Uploaded."); await showCourse(c.id, "Documents"); } finally { up.disabled = false; }
  });
  const list = c.documents.map(d => el("div", { class: "card" }, `${d.name} `, el("span", { class: "hint" }, `${d.pages} ${d.kind === "slide" ? "slides" : d.kind === "pdf" ? "pages" : "parts"}`),
    el("button", { class: "btn small alt", style: "float:right", onclick: guard(async () => { await api(`/api/courses/${c.id}/documents/${d.id}`, { method: "DELETE" }); await showCourse(c.id, "Documents"); }) }, "Delete")));
  return el("div", {}, el("p", { class: "hint" }, "Upload any document (PDF, Word docx, TXT, PPTX slides, Markdown). Gemini reads it directly and answers questions."),
    el("div", { class: "row" }, file, up), list, c.documents.length ? el("h3", { style: "margin-top:16px" }, "Ask your documents") : null,
    c.documents.length ? chat("docs", () => null) : null);
}

// ---------- mock interview ----------------------------------------------------------------
function chips(list, cls) { return list.length ? list.map(x => el("span", { class: "chip " + cls }, x)) : el("span", { class: "hint" }, "none"); }

function scorecardUI(s) {
  return el("div", {}, el("div", { class: "big" }, s.overall_percent + "%"), el("h3", {}, s.level), el("p", {}, s.feedback),
    s.questions.map(q => el("div", { class: "card" }, el("b", {}, `${q.question} - ${q.score_percent}%`), el("div", {}, "Covered: ", chips(q.covered, "ok")),
      el("div", {}, "Missed: ", chips(q.missed, "no")), q.follow_up_on ? el("small", {}, `Follow-up asked about: ${q.follow_up_on}`) : null)),
    el("div", { class: "card" }, el("div", {}, "Strengths: ", chips(s.strengths, "ok")), el("div", {}, "To revise: ", chips(s.gaps, "no")), el("small", {}, s.follow_up_recovery)),
    el("details", {}, el("summary", {}, "How was this scored?"), el("p", { class: "hint" }, s.how_scored)));
}

function interviewTab() {
  const box = el("div");
  const intro = () => box.replaceChildren(el("p", { class: "hint" }, "A short text interview that adapts: weak answers get a follow-up, strong answers lead to harder questions. Questions cover the whole course, so it works best after watching."),
    el("button", { class: "btn", onclick: guard(async () => question(await api("/api/interview/start", { method: "POST", json: { course_id: state.course.id, count: 4 } }))) }, "Start interview"));
  function question(d, feedback) {
    const ta = el("textarea", { maxlength: 2000, "aria-label": "Your answer", placeholder: "Type your answer..." });
    const send = el("button", { class: "btn" }, "Submit answer");
    send.onclick = guard(async () => {
      send.disabled = true;
      try {
        const r = await api(`/api/interview/${d.interview_id}/answer`, { method: "POST", json: { answer: ta.value } });
        if (r.finished) {
          const card = await api(`/api/interview/${d.interview_id}/scorecard`);
          box.replaceChildren(scorecardUI(card), el("button", { class: "btn alt", onclick: intro }, "New interview"));
          return;
        }
        question(r, r.feedback);
      } finally { send.disabled = false; }
    });
    put(box, feedback ? el("p", { class: "hint" }, feedback) : null, el("small", { class: "hint" }, `${d.note || ""} - ${d.level} question`),
      el("h3", {}, d.question), ta, el("div", { style: "margin-top:10px" }, send));
  }
  intro();
  return box;
}

function renderYTFallback(container, c) {
  put(container, el("div", { class: "yt-fallback-box" },
    el("h3", {}, "YouTube Embedding Restricted"),
    el("p", {}, "The owner of this video has restricted external embedding on third-party websites."),
    el("a", { class: "btn", href: c.video_url, target: "_blank", rel: "noreferrer" }, "Watch on YouTube ↗"),
    el("p", { class: "hint", style: "color:#aaa;margin-top:6px" }, "AI learning tools, transcript Q&A, and document features remain fully active.")
  ));
}

function openKeyModal() {
  const modal = $("key-modal");
  const keyInput = el("input", { type: "password", placeholder: "nvapi-...", "aria-label": "API Key" });
  const modelInput = el("input", { value: "openai/gpt-oss-20b", placeholder: "openai/gpt-oss-20b", "aria-label": "Model Name" });
  const urlInput = el("input", { value: "https://integrate.api.nvidia.com/v1", placeholder: "https://integrate.api.nvidia.com/v1", "aria-label": "Base URL" });

  const saveBtn = el("button", { class: "btn" }, "Save Settings");
  const clearBtn = el("button", { class: "btn alt" }, "Clear Settings");
  const closeBtn = el("button", { class: "btn alt small", style: "float:right" }, "Close");

  closeBtn.onclick = () => { modal.style.display = "none"; };
  saveBtn.onclick = guard(async () => {
    const k = keyInput.value.trim();
    if (!k) throw new Error("Please enter your API Key.");
    const model = modelInput.value.trim() || "openai/gpt-oss-20b";
    const base_url = urlInput.value.trim() || "https://integrate.api.nvidia.com/v1";
    await api("/api/config/key", { method: "POST", json: { api_key: k, model, base_url } });
    toast("NVIDIA NIM AI settings and key saved successfully!");
    modal.style.display = "none";
    await updateConfigUI();
  });
  clearBtn.onclick = guard(async () => {
    await api("/api/config/key", { method: "DELETE" });
    toast("API Key and custom settings cleared.");
    modal.style.display = "none";
    await updateConfigUI();
  });

  const box = el("div", { class: "modal-box" },
    closeBtn,
    el("h2", {}, "AI Model & Key Settings"),
    el("p", { class: "hint", style: "margin:6px 0 14px" }, "Configure your API key and endpoint for ChatGPT OSS 20B or any OpenAI-compatible provider."),
    el("label", {}, "API Key *"), keyInput,
    el("label", {}, "Model Name"), modelInput,
    el("label", {}, "Base URL / Endpoint"), urlInput,
    el("div", { class: "row", style: "margin-top:18px" }, saveBtn, clearBtn)
  );

  put(modal, box);
  modal.style.display = "flex";
}

// ---------- pages ---------------------------------------------------------------------------
async function showCourse(id, openTab = "Ask") {
  const c = await api("/api/courses/" + id);
  state.course = c; const view = $("view"); view.replaceChildren();
  let video = null, lastSent = 0, ytPlayer = null, ytPoll = null;
  // Wall-clock fallback: track elapsed playback time even before YT SDK responds
  let ytWallStart = null, ytWallAccum = 0, ytPlaying = false;
  // Seed currentTime from server-stored max progress so AI isn't stuck at t=0
  state.currentTime = (c.progress && c.progress.max_position) ? c.progress.max_position : 0;
  
  const leftFrame = el("div");
  const ph = el("b", {}, "0:00");

  // now() returns the best current playback position estimate
  const now = () => {
    // 1. Real YT.Player SDK (most accurate)
    if (ytPlayer && typeof ytPlayer.getCurrentTime === "function") {
      try { const t = ytPlayer.getCurrentTime(); if (t > 0) return t; } catch (e) {}
    }
    // 2. Native HTML5 video
    if (video) return video.currentTime;
    // 3. Wall-clock estimate (YouTube is playing but SDK not ready yet)
    if (ytPlaying && ytWallStart !== null) return ytWallAccum + (Date.now() - ytWallStart) / 1000;
    // 4. Accumulated wall-clock (paused)
    if (ytWallAccum > 0) return ytWallAccum;
    // 5. Server max position (fallback so AI gets meaningful context)
    return state.currentTime || 0;
  };

  let setupYT = null;

  if (c.has_video) {
    if (c.video_type === "youtube" && c.video_embed) {
      const vidContainer = el("div", { id: "yt-player-box", class: "video-frame" });
      leftFrame.append(vidContainer);

      const m = c.video_embed.match(/\/embed\/([a-zA-Z0-9_-]+)/);
      const ytId = m ? m[1] : null;

      setupYT = function trySetupYT() {
        if (!document.getElementById("yt-player-box")) { setTimeout(trySetupYT, 100); return; }
        if (window.YT && window.YT.Player && ytId) {
          try {
            ytPlayer = new YT.Player("yt-player-box", {
              videoId: ytId,
              playerVars: {
                enablejsapi: 1,
                origin: window.location.origin,
                rel: 0,
                modestbranding: 1,
                playsinline: 1
              },
              events: {
                onStateChange: (e) => {
                  if (e.data === 1) { // PLAYING
                    ytWallStart = Date.now(); ytPlaying = true;
                  } else { // PAUSED / ENDED / BUFFERING
                    if (ytPlaying && ytWallStart !== null) ytWallAccum += (Date.now() - ytWallStart) / 1000;
                    ytWallStart = null; ytPlaying = false;
                  }
                },
                onError: (e) => {
                  console.warn("YouTube player error code:", e.data);
                  if ([2, 100, 101, 150].includes(e.data)) {
                    renderYTFallback(vidContainer, c);
                  }
                },
                onReady: () => {}
              }
            });
            clearInterval(ytPoll);
            ytPoll = setInterval(() => {
              const curr = now();
              if (curr > 0) {
                state.currentTime = curr;
                ph.textContent = fmt(curr);
                if (curr - lastSent >= 10 || curr < lastSent) {
                  lastSent = curr;
                  api("/api/progress/watch", { method: "POST", json: { course_id: c.id, position: curr } }).catch(() => {});
                }
              }
            }, 1000);
          } catch (e) {
            console.warn("YT.Player init error:", e);
            renderYTFallback(vidContainer, c);
          }
        } else {
          setTimeout(trySetupYT, 200);
        }
      };
    } else {
      video = el("video", { controls: true, preload: "metadata", src: c.video_url,
        onerror: () => toast("The video could not be loaded. Check that the file format is supported (.mp4, .webm).") });
      video.addEventListener("timeupdate", () => {
        ph.textContent = fmt(video.currentTime);
        state.currentTime = video.currentTime;
        if (video.currentTime - lastSent >= 10 || video.currentTime < lastSent) {
          lastSent = video.currentTime;
          api("/api/progress/watch", { method: "POST", json: { course_id: c.id, position: video.currentTime } }).catch(() => {});
        }
      });
      leftFrame.append(video);
    }
  } else {
    leftFrame.append(el("div", { class: "yt-fallback-box", style: "background:var(--surface-subtle);color:var(--text-main);border:1px solid var(--border)" },
      el("h3", {}, "📄 Documents Course"),
      el("p", { class: "hint" }, "This course has no video. Upload PDF or Word files to ask questions.")
    ));
  }

  state.video = video;

  const quickActions = el("div", { class: "video-action-pills" },
    video ? el("button", { class: "action-pill", type: "button", onclick: () => { video.currentTime = Math.max(0, video.currentTime - 10); } }, "⏮ -10s") : null,
    video ? el("button", { class: "action-pill", type: "button", onclick: () => { video.currentTime = video.currentTime + 10; } }, "⏭ +10s") : null,
    c.video_url ? el("a", { class: "action-pill", href: c.video_url, target: "_blank", rel: "noreferrer" }, "🌐 Source Link ↗") : null
  );

  const videoHeroCard = el("div", { class: "video-hero-card" },
    el("div", { class: "video-frame-container" }, leftFrame),
    el("div", { class: "video-control-bar" },
      el("div", { class: "video-title-header" },
        el("h1", { class: "course-main-title" }, c.title),
        el("div", { class: "video-badges" },
          el("span", { class: "badge live" }, c.has_video ? (c.video_type === "youtube" ? "📺 YouTube" : c.video_type === "local" ? "💻 PC Video" : "🌐 Web Stream") : "📄 Docs"),
          c.duration > 0 ? el("span", { class: "badge" }, `⏱ ${fmt(c.duration)} total`) : null
        )
      ),
      el("div", { class: "video-toolbar" },
        el("div", { class: "playback-status" }, "Playback time: ", ph),
        quickActions
      ),
      (c.has_video && c.duration > 0) ? el("div", { class: "bar", title: c.progress.percent_watched + "% watched" }, el("i", { style: `width:${c.progress.percent_watched}%` })) : null
    )
  );

  const hasVideoCues = c.has_video && c.duration > 0;
  const tabs = hasVideoCues ? [
    { id: "Ask", label: "💬 AI Chatbot" },
    { id: "Study", label: "📚 Study Tools" },
    { id: "Documents", label: "📄 Documents" },
    { id: "Interview", label: "🎙️ Interview" }
  ] : [
    { id: "Documents", label: "📄 Documents" },
    { id: "Ask", label: "💬 AI Chatbot" },
    { id: "Study", label: "📚 Study Tools" },
    { id: "Interview", label: "🎙️ Interview" }
  ];

  const body = el("div", { class: "tab" }), bar = el("div", { class: "tabs", role: "tablist" });
  const open = tabObj => {
    bar.querySelectorAll("button").forEach(b => b.setAttribute("aria-selected", String(b.dataset.id === tabObj.id)));
    const chatScope = (tabObj.id === "Ask" && hasVideoCues) ? "video" : "docs";
    body.replaceChildren(tabObj.id === "Ask" ? chat(chatScope, now) : tabObj.id === "Study" ? studyTab() : tabObj.id === "Documents" ? docsTab() : interviewTab());
    // Update URL hash without breaking history
    const targetHash = `#/course/${c.id}/${tabObj.id.toLowerCase()}`;
    if (location.hash !== targetHash) {
      history.replaceState(null, "", targetHash);
    }
  };

  tabs.forEach(t => {
    const b = el("button", { role: "tab", type: "button", "data-id": t.id, onclick: () => open(t) }, t.label);
    bar.append(b);
  });

  const panelHeader = el("div", { class: "panel-header" },
    el("h3", {}, "🤖 Gemini AI Assistant")
  );

  view.append(
    el("div", { class: "workspace-nav" },
      el("a", { href: "#/", class: "back-link" }, "← Back to Workspace"),
      el("span", { class: "badge" }, c.documents.length + " documents loaded")
    ),
    el("div", { class: "course-view" },
      videoHeroCard,
      el("div", { class: "panel" }, panelHeader, bar, body)
    )
  );

  const initialTab = tabs.find(t => t.id.toLowerCase() === openTab.toLowerCase()) || tabs[0];
  open(initialTab);

  if (setupYT) requestAnimationFrame(setupYT);
}

async function showDashboard() {
  state.video = null;
  const { courses } = await api("/api/courses"); const view = $("view"); view.replaceChildren();
  const vids = courses.filter(c => c.has_video);
  const avg = vids.length ? Math.round(vids.reduce((a, c) => a + c.progress.percent_watched, 0) / vids.length) : 0;
  const qz = courses.flatMap(c => c.progress.quizzes), qs = qz.reduce((a, q) => a + q.score, 0), qt = qz.reduce((a, q) => a + q.total, 0);

  const statCard = (icon, val, label) => el("div", { class: "stat-card" },
    el("div", { class: "stat-icon" }, icon),
    el("div", {}, el("b", {}, String(val)), el("span", {}, label))
  );

  const courseCards = courses.map(c => {
    const typeLabel = c.has_video ? (c.video_type === "youtube" ? "YouTube video" : c.video_type === "local" ? "Local PC video" : "Web video") : "Documents only";
    return el("div", { class: "course-card" },
      el("div", { class: "course-card-body" },
        el("div", { class: "meta", style: "margin-bottom:8px" }, el("span", { class: "meta-pill" }, typeLabel)),
        el("h3", {}, c.title),
        el("div", { class: "meta", style: "margin-top:8px" },
          el("span", {}, `📄 ${c.documents.length} docs`),
          el("span", {}, "•"),
          el("span", {}, `💬 ${c.progress.questions} questions`)
        ),
        (c.has_video && c.duration > 0) ? el("div", { class: "bar", title: c.progress.percent_watched + "% watched" }, el("i", { style: `width:${c.progress.percent_watched}%` })) : null
      ),
      el("div", { class: "acts" },
        el("a", { class: "btn", href: "#/course/" + c.id }, "Watch & Learn →"),
        c.demo ? null : el("button", { class: "btn alt small", onclick: guard(async () => { if (confirm("Delete this course and its files?")) { await api("/api/courses/" + c.id, { method: "DELETE" }); showDashboard(); } }) }, "Delete")
      )
    );
  });

  const title = el("input", { name: "title", placeholder: "e.g., Introduction to Computer Science", maxlength: 80, required: true });
  const url = el("input", { name: "video_url", placeholder: "https://www.youtube.com/watch?v=... or direct MP4 URL" });
  const vidFile = el("input", { type: "file", name: "video_file", accept: ".mp4,.webm,.mkv,.mov,.avi" });
  const tr = el("input", { type: "file", name: "transcript", accept: ".srt,.vtt" });
  const form = el("form", { onsubmit: guard(async e => {
    e.preventDefault();
    const fd = new FormData();
    fd.append("title", title.value);
    if (url.value.trim()) fd.append("video_url", url.value.trim());
    if (vidFile.files[0]) fd.append("video_file", vidFile.files[0]);
    if (tr.files[0]) fd.append("transcript", tr.files[0]);
    const c = await api("/api/courses", { method: "POST", form: fd });
    location.hash = "#/course/" + c.id;
  }) },
    el("label", {}, "Course Title *"), title,
    el("label", {}, "Option A: Video Link (YouTube watch link, Shorts, Vimeo, or Web URL)"), url,
    el("label", {}, "Option B: Local Video File from PC (.mp4, .webm, .mkv, .mov)"), vidFile,
    el("label", {}, "Transcript File (.srt or .vtt - Optional: YouTube transcripts are fetched automatically!)"), tr,
    el("p", { class: "hint", style: "font-size:12px;margin:2px 0 10px" }, "Tip: For YouTube links, transcripts are extracted automatically from the video captions if available."),
    el("p", { style: "margin-top:18px" }, el("button", { class: "btn" }, "✨ Create Course")));

  view.append(
    el("div", { class: "dashboard-header" },
      el("h1", {}, "Learning Workspace"),
      el("p", { class: "hint", style: "font-size:14px;margin-top:4px" }, "Watch interactive lectures, ask Gemini AI questions, generate revision notes, and take adaptive quizzes.")
    ),
    el("div", { class: "stats" },
      statCard("📚", courses.length, "Total Courses"),
      statCard("🎬", avg + "%", "Average Watched"),
      statCard("🎯", qt ? Math.round(100 * qs / qt) + "%" : "-", "Quiz Average"),
      statCard("🎙️", courses.reduce((a, c) => a + c.progress.interviews.length, 0), "Interviews Completed")
    ),
    el("h2", { style: "margin-bottom:16px" }, "Your Courses"),
    el("div", { class: "courses-grid" }, ...courseCards),
    el("details", { class: "add" }, el("summary", {}, "➕ Add New Course"), form)
  );
}

async function updateConfigUI() {
  try {
    const cfg = await api("/api/config"), m = $("mode"), kBtn = $("key-btn");
    const modelName = cfg.model || "openai/gpt-oss-20b";
    const modeText = cfg.mode === "live" ? `✨ AI Live (${modelName})` : "💡 Demo Mode";
    if (m) {
      m.textContent = modeText;
      if (cfg.mode === "live") m.classList.add("live"); else m.classList.remove("live");
    }
    if (kBtn) {
      const kText = cfg.has_user_key ? "🔑 API Settings (Active)" : "🔑 Set API Key & Model";
      const keySpan = kBtn.querySelector(".key-text");
      if (keySpan) keySpan.textContent = kText; else kBtn.textContent = kText;
      if (cfg.has_user_key) kBtn.classList.add("live"); else kBtn.classList.remove("live");
    }
  } catch (e) { toast(e.message); }
}

async function init() {
  const kBtn = $("key-btn");
  if (kBtn) kBtn.onclick = openKeyModal;
  await updateConfigUI();
  const route = guard(async () => {
    const m = location.hash.match(/^#\/course\/([\w-]+)(?:\/([\w-]+))?/);
    if (m) {
      const courseId = m[1];
      const tabSlug = (m[2] || "").toLowerCase();
      const tabMap = { ask: "Ask", study: "Study", docs: "Documents", documents: "Documents", interview: "Interview" };
      await showCourse(courseId, tabMap[tabSlug] || "Ask");
    } else {
      await showDashboard();
    }
  });
  window.addEventListener("hashchange", route); route();
}
init();
