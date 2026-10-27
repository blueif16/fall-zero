// Fall-Zero chat. Nobody reads paragraphs, so the answer is cards: per piece a verdict, three risk
// tiles (child, adult, earthquake), question cards when we're unsure, and fix cards that show what
// each fix changes. Tapping an answer or "I did this" re-runs the physics (/api/assess) in place.
//
// Each turn POSTs to /api/turn and reads NDJSON: step... -> report -> delta... -> done (or error).
// Muse Spark chains the chat through the last response id. The page saves the whole chat (messages,
// cards, answers) to /api/threads after every turn and tap, so past checks can be reopened.

const $ = (id) => document.getElementById(id);
const els = {
  empty: $("empty"), messages: $("messages"), thread: $("thread"), composer: $("composer"), text: $("text"),
  file: $("file"), attachment: $("attachment"), send: $("send"), mic: $("mic"), drop: $("drop"), toast: $("toast"),
  status: $("status"), statusLabel: document.querySelector("#status .label"),
  historyBtn: $("history-btn"), history: $("history"), historyList: $("history-list"),
};

const svg = (body) => `<svg viewBox="0 0 24 24" aria-hidden="true">${body}</svg>`;
const ICON = {
  child: svg('<circle cx="12" cy="4.8" r="2.4"/><path d="M12 7.8v7M7 10.5l5 1.6 5-1.6M9.5 21l2.5-6.2 2.5 6.2"/>'),
  adult: svg('<circle cx="10" cy="4.5" r="2.3"/><path d="M10 7.5v7.5M10 15l-2.5 6M10 15l2 6M10 9.5l5 2.5M15 12v9"/>'),
  quake: svg('<path d="M2 12h3l2-4 3 9 3-13 3 11 2-5 1 2h3"/>'),
  strap: svg('<path d="M3 3v18"/><rect x="8" y="7" width="12" height="14" rx="1.5"/><path d="M3 9h7M12 12h4M12 16h4"/>'),
  lock: svg('<rect x="5" y="11" width="14" height="9" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/>'),
  top: svg('<rect x="3" y="12" width="12" height="9" rx="1"/><path d="M7 9l4-4h7M15 2l3 3-3 3"/>'),
  distance: svg('<path d="M3 12h18M6 8l-3 4 3 4M18 8l3 4-3 4"/>'),
  tips: svg('<path d="M12 3.5l9.5 17h-19z"/><path d="M12 10v4.5M12 17.6v.2"/>'),
  maybe: svg('<circle cx="12" cy="12" r="9.5"/><path d="M9.6 9.4a2.5 2.5 0 1 1 3.4 2.4c-.7.3-1 .8-1 1.6M12 17v.3"/>'),
  holds: svg('<path d="M5 12.5l4.5 4.5L19 7.5"/>'),
  close: svg('<path d="M6 6l12 12M18 6L6 18"/>'),
  ask: svg('<path d="M4 5h16v11H9l-5 4z"/>'),
  wrench: svg('<path d="M14.5 6.5a4 4 0 0 0 5 5l-8 8a2.1 2.1 0 0 1-3-3l8-8a4 4 0 0 0-2-2z"/>'),
  play: svg('<path d="M7 4.5v15l12-7.5z"/>'),
  replay: svg('<path d="M4 12a8 8 0 1 0 2.4-5.7"/><path d="M4 4v4.5h4.5"/>'),
};
const RISKS = [["child", "Child climbs"], ["adult", "Adult leans"], ["quake", "Earthquake"]];
const ITEM_WORD = { tv: "TV", box: "Boxes", basket: "Basket", lamp: "Lamp", plant: "Plant", books: "Books", decor: "Decor", other: "Item" };
const WORD = { tips: "Tips", maybe: "Maybe", holds: "Holds" };
const PLACEHOLDER = matchMedia("(max-width: 560px)").matches
  ? "Photo, video or a question"
  : "Add a photo or video of the room, or ask a question";

let previousId = null;
let pending = null; // File waiting to be sent
let busy = false;
let pieces = []; // every piece card in this chat: {run, index, n, card, el, still, size, marker, record}
let thread = null; // the chat being saved: {id, created, title, previous_response_id, messages}

els.text.placeholder = PLACEHOLDER;

// --- status in the floating control -------------------------------------------------

function setStatus(text, tone) {
  if (els.statusLabel.textContent !== text) {
    els.statusLabel.textContent = text;
    els.statusLabel.classList.remove("swap");
    void els.statusLabel.offsetWidth; // restart the animation
    els.statusLabel.classList.add("swap");
  }
  els.status.dataset.tone = tone;
}

function summarizeStatus() {
  if (!pieces.length) return setStatus(previousId ? "Ready" : "Send a photo to start", "idle");
  const questions = pieces.reduce((n, p) => n + p.card.questions.length, 0);
  const tips = pieces.filter((p) => p.card.status === "tips").length;
  const maybe = pieces.filter((p) => p.card.status === "maybe").length;
  const parts = [];
  if (tips) parts.push(tips > 1 ? `${tips} can tip` : "Can tip");
  else if (maybe) parts.push(maybe > 1 ? `${maybe} might tip` : "Might tip");
  if (questions) parts.push(`${questions} question${questions > 1 ? "s" : ""}`);
  if (!parts.length) return setStatus("All stable", "holds");
  setStatus(parts.join(" · "), tips ? "tips" : "ask");
}

// --- attaching a photo or video ---------------------------------------------------------

function attach(file) {
  if (!file) return;
  if (!/^(image|video)\//.test(file.type)) return toast("Send a photo or a video");
  pending = file;
  const url = URL.createObjectURL(file);
  const isVideo = file.type.startsWith("video/");
  const preview = isVideo ? `<video src="${url}" muted></video>` : `<img src="${url}" alt="">`;
  els.attachment.innerHTML = `${preview}<div class="name">${esc(file.name)}
    <small>${isVideo ? "Video" : "Photo"} · ${(file.size / 1e6).toFixed(1)} MB</small></div>
    <button type="button" title="Remove">${ICON.close}</button>`;
  els.attachment.querySelector("button").onclick = clearAttachment;
  els.attachment.hidden = false;
  els.composer.classList.add("has-media");
  els.text.placeholder = "Anything to add? (optional)";
  updateSend();
  els.text.focus();
}

function clearAttachment() {
  pending = null;
  els.attachment.hidden = true;
  els.attachment.innerHTML = "";
  els.composer.classList.remove("has-media");
  els.text.placeholder = PLACEHOLDER;
  updateSend();
}

async function attachSample(src) {
  const blob = await (await fetch(src)).blob();
  attach(new File([blob], src.split("/").pop(), { type: blob.type }));
}

$("pick").onclick = $("pick-big").onclick = () => els.file.click();
els.file.onchange = () => { attach(els.file.files[0]); els.file.value = ""; };
document.querySelectorAll(".sample").forEach((b) => (b.onclick = () => attachSample(b.dataset.src)));

let dragDepth = 0;
window.addEventListener("dragenter", (e) => { e.preventDefault(); dragDepth++; els.drop.hidden = false; });
window.addEventListener("dragleave", () => { if (--dragDepth <= 0) { dragDepth = 0; els.drop.hidden = true; } });
window.addEventListener("dragover", (e) => e.preventDefault());
window.addEventListener("drop", (e) => {
  e.preventDefault();
  dragDepth = 0;
  els.drop.hidden = true;
  attach(e.dataTransfer.files[0]);
});
window.addEventListener("paste", (e) => {
  const file = [...(e.clipboardData?.files || [])].find((f) => /^(image|video)\//.test(f.type));
  if (file) { e.preventDefault(); attach(file); }
});

// --- composer ---------------------------------------------------------------------------

function updateSend() {
  els.send.disabled = busy || (!pending && !els.text.value.trim());
}

els.text.addEventListener("input", () => {
  els.text.style.height = "auto";
  els.text.style.height = `${els.text.scrollHeight}px`;
  updateSend();
});
els.text.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); els.composer.requestSubmit(); }
});
els.composer.addEventListener("submit", (e) => { e.preventDefault(); send(); });

function resetChat() {
  previousId = null;
  pieces = [];
  thread = null;
  els.messages.innerHTML = "";
  clearAttachment();
  els.text.value = "";
}

function newChat() {
  if (busy) return;
  resetChat();
  els.empty.hidden = false;
  els.empty.style.animation = "none";
  void els.empty.offsetWidth;
  els.empty.style.animation = "";
  closeHistory();
  summarizeStatus();
}
$("new-chat").onclick = $("home").onclick = newChat;

// --- voice: record, then Muse Voice Transcribe fills the text box -----------------------

let recorder = null;
els.mic.onclick = async () => {
  if (recorder) return recorder.stop();
  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch {
    return toast("Microphone not available");
  }
  const chunks = [];
  recorder = new MediaRecorder(stream);
  recorder.ondataavailable = (e) => chunks.push(e.data);
  recorder.onstop = async () => {
    stream.getTracks().forEach((t) => t.stop());
    recorder = null;
    els.mic.classList.remove("recording");
    const form = new FormData();
    form.append("audio", new Blob(chunks, { type: chunks[0]?.type || "audio/webm" }), "voice.webm");
    setStatus("Listening back…", "busy");
    try {
      const res = await fetch("/api/transcribe", { method: "POST", body: form });
      if (!res.ok) throw new Error(await res.text());
      const { transcript } = await res.json();
      els.text.value = [els.text.value.trim(), (transcript || "").trim()].filter(Boolean).join(" ");
      els.text.dispatchEvent(new Event("input"));
    } catch (err) {
      toast(`Couldn't hear that: ${err.message.slice(0, 100)}`);
    } finally {
      summarizeStatus();
    }
  };
  recorder.start();
  els.mic.classList.add("recording");
  setStatus("Listening — tap the mic to stop", "busy");
};

// --- sending a turn ---------------------------------------------------------------------

async function send() {
  const text = els.text.value.trim();
  if (busy || (!text && !pending)) return;
  busy = true;
  els.empty.hidden = true;
  closeHistory();
  const file = pending;
  const isVideo = !!file && file.type.startsWith("video/");
  thread ??= { id: crypto.randomUUID().replace(/-/g, "").slice(0, 12), created: new Date().toISOString(), messages: [] };
  const userRecord = { role: "user", text, media: null };
  const botRecord = { role: "bot", say: "", report: null };
  thread.messages.push(userRecord, botRecord);
  addUserMessage(text, file && { url: URL.createObjectURL(file), video: isVideo });

  const form = new FormData();
  form.append("text", text);
  if (previousId) form.append("previous_response_id", previousId);
  if (file) form.append("media", file, file.name);
  else if (pieces.length) form.append("context", JSON.stringify(pieces.map(contextOf)));
  els.text.value = "";
  els.text.style.height = "auto";
  clearAttachment();
  setStatus(file ? "Uploading…" : "Thinking…", "busy");

  const bot = new BotMessage(file, botRecord);
  bot.onReport = (ev) => (userRecord.media = { url: ev.upload, video: isVideo });
  try {
    const res = await fetch("/api/turn", { method: "POST", body: form });
    if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
    const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
    let buf = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += value;
      let i;
      while ((i = buf.indexOf("\n")) >= 0) {
        const line = buf.slice(0, i).trim();
        buf = buf.slice(i + 1);
        if (line) bot.handle(JSON.parse(line));
      }
    }
  } catch (err) {
    bot.handle({ type: "error", text: err.message });
  } finally {
    bot.finish();
    busy = false;
    updateSend();
    summarizeStatus();
    thread.previous_response_id = previousId;
    saveThread();
  }
}

const contextOf = (p) => ({
  piece: `${p.n}. ${p.card.name}`, verdict: p.card.headline,
  risks: Object.fromEntries(Object.entries(p.card.risks).map(([k, r]) => [k, r.status])), answers: p.card.answers,
});

function addUserMessage(text, media) {
  const el = document.createElement("div");
  el.className = "msg user";
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  if (media?.url) {
    const node = document.createElement(media.video ? "video" : "img");
    node.src = media.url;
    if (media.video) { node.controls = true; node.muted = true; }
    bubble.append(node);
  }
  if (text) bubble.append(document.createTextNode(text));
  el.append(bubble);
  els.messages.append(el);
  scrollDown();
}

class BotMessage {
  // `record` is this reply as saved in the thread; a reopened chat replays it with `restore()`
  constructor(file, record, restoring = false) {
    this.record = record;
    this.el = document.createElement("div");
    this.el.className = "msg bot";
    let top = restoring ? "" : `<div class="typing"><i></i><i></i><i></i></div>`;
    if (file) {
      const url = URL.createObjectURL(file);
      const media = file.type.startsWith("video/") ? `<video src="${url}#t=0.5" muted preload="auto"></video>` : `<img src="${url}" alt="">`;
      top = `<div class="scan">${media}<div class="beam"></div>
        <div class="step"><span class="spin"></span><span class="txt">Uploading</span><span class="model" hidden></span></div></div>`;
    }
    this.el.innerHTML = `<div class="top">${top}</div><div class="say"></div><div class="cards"></div>`;
    this.say = this.el.querySelector(".say");
    this.raw = "";
    els.messages.append(this.el);
    scrollDown();
  }

  handle(ev) {
    if (ev.type === "step") this.step(ev.text);
    else if (ev.type === "report") {
      this.record.report = ev;
      this.onReport?.(ev);
      this.report(ev);
    } else if (ev.type === "delta") {
      this.record.say += ev.text;
      this.delta(ev.text);
    } else if (ev.type === "done") previousId = ev.response_id;
    else if (ev.type === "error") {
      this.record.error = ev.text;
      this.error(ev.text);
    }
  }

  restore() {
    if (this.record.report) this.report(this.record.report);
    if (this.record.say) this.say.innerHTML = DOMPurify.sanitize(marked.parse(this.record.say));
    if (this.record.error) this.error(this.record.error);
  }

  step(text) {
    const [label, model] = text.split(" · ");
    setStatus(label, "busy");
    const step = this.el.querySelector(".scan .step");
    if (!step) return;
    const txt = document.createElement("span");
    txt.className = "txt";
    txt.textContent = label;
    step.querySelector(".txt").replaceWith(txt);
    const tag = step.querySelector(".model");
    tag.hidden = !model;
    tag.textContent = model || "";
  }

  report(ev) {
    const top = this.el.querySelector(".top");
    if (!ev.cards.length) {
      top.innerHTML = `<figure class="still"><img src="${ev.still}" alt=""></figure>`;
    } else {
      top.innerHTML = stillFigure(ev);
    }
    const cards = this.el.querySelector(".cards");
    ev.cards.forEach((card, index) => {
      const p = { run: ev.run, index, n: pieces.length + 1, card, still: ev.still, size: ev.size, record: ev };
      p.el = document.createElement("article");
      p.el.style.setProperty("--i", index);
      p.marker = top.querySelector(`[data-piece="${index}"]`);
      p.marker?.setAttribute("data-n", p.n);
      top.querySelectorAll(`[data-piece="${index}"] text`).forEach((t) => (t.textContent = p.n));
      pieces.push(p);
      render(p);
      cards.append(p.el);
    });
    let tail = "";
    if (ev.others.length) {
      tail += `<p class="also">Also saw ${ev.others.map(esc).join(", ")}. I can't check ${ev.others.length > 1 ? "those" : "that"} yet.</p>`;
    }
    if (!ev.cards.length && !ev.others.length) tail += `<p class="also">I couldn't find furniture that could tip over in this one.</p>`;
    tail += detailsHTML(ev);
    cards.insertAdjacentHTML("beforeend", tail);
    summarizeStatus();
    scrollDown();
  }

  delta(text) {
    this.el.querySelector(".typing")?.remove();
    this.raw += text;
    this.say.classList.add("streaming");
    this.say.innerHTML = DOMPurify.sanitize(marked.parse(this.raw));
    scrollDown();
  }

  error(text) {
    this.el.querySelector(".typing")?.remove();
    this.el.querySelector(".scan .beam")?.remove();
    this.el.querySelector(".scan .step")?.remove();
    this.say.insertAdjacentHTML("beforeend", `<p class="error">Something went wrong: ${esc(text)}</p>`);
  }

  finish() {
    this.el.querySelector(".typing")?.remove();
    this.say.classList.remove("streaming");
  }
}

// --- the analyzed frame, with each piece boxed --------------------------------------------

function stillFigure(ev) {
  const [w, h] = ev.size;
  const r = Math.max(w, h) * 0.03;
  // what stands on each piece: dashed outlines with a small tag, drawn first so the pieces sit on top
  const things = ev.cards.flatMap((c) => c.items.filter((it) => it.box)).map((it, j) => {
    const [x1, y1, x2, y2] = it.box;
    const word = ITEM_WORD[it.kind] || "Item";
    const tw = word.length * r * 0.62 + r * 0.8;
    return `<g class="thing" style="--i:${j}">
      <rect x="${x1}" y="${y1}" width="${x2 - x1}" height="${y2 - y1}" pathLength="1" stroke="#fff" stroke-dasharray="1"/>
      <rect x="${x1}" y="${y1}" width="${x2 - x1}" height="${y2 - y1}" pathLength="1" class="dash"/>
      <rect x="${x1}" y="${y1 - r * 1.3}" width="${tw}" height="${r * 1.2}" rx="${r * 0.3}" class="tag"/>
      <text x="${x1 + r * 0.4}" y="${y1 - r * 0.42}" font-size="${r * 0.9}" font-weight="700" fill="#fff">${word}</text></g>`;
  }).join("");
  const boxes = things + ev.cards.map((c, i) => {
    if (!c.box) return "";
    const [x1, y1, x2, y2] = c.box;
    const col = `var(--${c.status})`;
    return `<g data-piece="${i}" style="color:${col}">
      <rect x="${x1}" y="${y1}" width="${x2 - x1}" height="${y2 - y1}" pathLength="1" stroke="currentColor"/>
      <circle cx="${x1 + r}" cy="${y1 + r}" r="${r}" fill="currentColor"/>
      <text x="${x1 + r}" y="${y1 + r * 1.38}" fill="#fff" font-size="${r * 1.1}" font-weight="700" text-anchor="middle">${i + 1}</text></g>`;
  }).join("");
  const at = ev.frame_at_s != null ? `<figcaption class="also">Frame at ${ev.frame_at_s.toFixed(1)} s</figcaption>` : "";
  return `<figure class="still"><img src="${ev.still}" alt="The checked photo">
    <svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">${boxes}</svg>${at}</figure>`;
}

// --- a piece card ---------------------------------------------------------------------------

function render(p, prev = null) {
  const c = p.card;
  p.el.className = `card ${c.status}`;
  // only cards that weren't there before animate in, so an update doesn't replay the whole card
  let i = 0;
  const enter = (list, key) =>
    !prev || !prev[list].some((x) => x.key === key) ? { cls: " enter", style: ` style="--i:${i++}"` } : { cls: "", style: "" };

  const risks = RISKS.map(([k, label]) => {
    const r = c.risks[k];
    const changed = prev && prev.risks[k].status !== r.status;
    return `<div class="risk ${r.status}${changed ? " pop" : ""}" title="${esc(r.says)}">
      <div class="rtop"><span class="ricon">${ICON[k]}</span><span class="rstate">${ICON[r.status]}${WORD[r.status]}</span></div>
      <div class="rlabel">${label}${r.simulated ? `<span class="simtag">simulated</span>` : ""}</div><div class="rsays">${esc(r.says)}</div></div>`;
  }).join("");

  const questions = c.questions.map((q) => {
    const e = enter("questions", q.key);
    if (q.kind === "measure") {
      const g = q.guess;
      return `<div class="q${e.cls}"${e.style} data-q="${q.key}"><div class="qt">${esc(q.title)}</div><div class="qh">${esc(q.hint || "")}</div>
        <div class="dims">${[["width_cm", "Width"], ["depth_cm", "Depth"], ["height_cm", "Height"]].map(([k, l]) =>
          `<label>${l} cm<input type="number" inputmode="numeric" min="10" max="400" name="${k}" placeholder="${g[k]}"></label>`).join("")}</div>
        <button class="go" type="button">Check with these</button></div>`;
    }
    return `<div class="q${e.cls}"${e.style} data-q="${q.key}"><div class="qt">${esc(q.title)}</div>${q.hint ? `<div class="qh">${esc(q.hint)}</div>` : ""}
      <div class="opts">${q.options.map((o) =>
        `<button type="button" data-v="${esc(JSON.stringify(o.value))}">${esc(o.label)}${o.sub ? `<small>${esc(o.sub)}</small>` : ""}</button>`).join("")}</div></div>`;
  }).join("");

  const fixes = c.fixes.map((f) => {
    const e = enter("fixes", f.key);
    if (!f.answer) {
      return `<div class="fix info${e.cls}"${e.style}><div class="ficon">${ICON[f.icon]}</div>
        <div class="ft">${esc(f.title)}</div><div class="fw">${esc(f.why)}</div></div>`;
    }
    const after = f.after
      ? `<div class="after">After${RISKS.map(([k, label]) => `<i class="${f.after[k]}" title="${label}: ${WORD[f.after[k]]}">${ICON[k]}</i>`).join("")}</div>`
      : "";
    return `<div class="fix${f.done ? " done" : ""}${e.cls}"${e.style} data-fix="${f.key}"><div class="ficon">${ICON[f.icon]}</div>
      <div class="ft">${esc(f.title)}</div><div class="fw">${esc(f.why)}</div>${after}
      <button class="done-btn" type="button">${f.done ? `${ICON.holds}Done` : "I did this"}</button></div>`;
  }).join("");

  const verdictChanged = prev && prev.status !== c.status;
  p.el.innerHTML = `
    <header class="card-head">
      <div class="thumb" style="${thumbStyle(p)}"><span class="num">${p.n}</span></div>
      <div><div class="name">${esc(c.name)}</div>
        <div class="verdict${verdictChanged ? " pop" : ""}">${ICON[c.status]}<span>${esc(c.headline)}</span></div></div>
    </header>
    ${c.items.length ? `<div class="ontop"><span>On top</span>${[...c.items].sort(byHazard).map((it) =>
      `<span class="item ${it.level}${it.moved ? " moved" : ""}" title="${esc(it.why)}"><i style="${thumbStyle(p, it.box, 28)}"></i>${esc(it.short)}${
        it.level === "fine" ? "" : ICON[it.level === "danger" ? "tips" : "maybe"]}</span>`).join("")}</div>` : ""}
    <div class="risks">${risks}</div>
    <div class="sim-slot"></div>
    ${questions ? `<section class="block"><h4>${ICON.ask}Help me be sure</h4><div class="cards-row">${questions}</div></section>` : ""}
    ${fixes ? `<section class="block"><h4>${ICON.wrench}${c.status === "holds" ? "Keep it that way" : "How to fix it"}</h4><div class="cards-row">${fixes}</div></section>` : ""}
    ${c.note ? `<p class="note">${esc(c.note)}</p>` : ""}`;

  if (p.marker) p.marker.style.color = `var(--${c.status})`;
  mountSim(p);

  p.el.querySelectorAll("[data-q]").forEach((qEl) => {
    const key = qEl.dataset.q;
    qEl.querySelectorAll(".opts button").forEach((b) => (b.onclick = () => {
      b.classList.add("picked");
      answer(p, { [key]: JSON.parse(b.dataset.v) });
    }));
    qEl.querySelector(".go")?.addEventListener("click", () => {
      const vals = Object.fromEntries([...qEl.querySelectorAll("input")].map((x) => [x.name, parseFloat(x.value)]));
      if (Object.values(vals).some((v) => !(v >= 10 && v <= 400))) return toast("Fill in all three, in cm");
      answer(p, { measured: vals });
    });
  });
  p.el.querySelectorAll("[data-fix]").forEach((fEl) => {
    const f = c.fixes.find((x) => x.key === fEl.dataset.fix);
    fEl.querySelector(".done-btn").onclick = () => {
      if (!f.done) return answer(p, f.answer);
      const next = { ...c.answers };
      Object.keys(f.answer).forEach((k) => delete next[k]);
      recheck(p, next);
    };
  });
}

const HAZARD_ORDER = { danger: 0, caution: 1, fine: 2 };
const byHazard = (a, b) => HAZARD_ORDER[a.level] - HAZARD_ORDER[b.level];

// --- the simulation in each card ------------------------------------------------------------

let viewerModule = null;
const SCENARIOS = [["child", "Child climbs"], ["adult", "Adult leans"], ["quake", "Earthquake"]];

function mountSim(p) {
  if (!p.sim) {
    const el = document.createElement("section");
    el.className = "block sim";
    el.innerHTML = `<h4>${ICON.play}See it happen</h4><div class="sim-tabs"></div>
      <div class="viewer"><div class="cap"></div><ul class="events"></ul>
        <button class="replay" type="button" hidden>${ICON.replay}Replay</button>
        <div class="loading"><span class="spin"></span>Simulating…</div><div class="bar"><i></i></div></div>
      <div class="sim-variants"></div>`;
    const worst = SCENARIOS.find(([k]) => p.card.risks[k].status === "tips");
    p.sim = { el, scenario: worst ? worst[0] : "quake", variant: "as_is", key: null, viewer: null };
    el.querySelector(".replay").onclick = () => {
      el.querySelector(".replay").hidden = true;
      p.sim.viewer?.play();
    };
  }
  p.el.querySelector(".sim-slot")?.replaceWith(p.sim.el); // after a re-render; tab clicks leave it in place
  const c = p.card;
  const fixes = Object.fromEntries(c.fixes.map((f) => [f.key, f]));
  const variants = [["as_is", c.answers.anchored === "yes" ? "As it is now (strapped)" : "As it is now"]];
  if (fixes.anchor && !fixes.anchor.done) variants.push(["anchor", "Strapped"]);
  if (fixes.moved && !fixes.moved.done) variants.push(["moved", "Hard things moved"]);
  if (!variants.some(([k]) => k === p.sim.variant)) p.sim.variant = "as_is";
  const tabs = p.sim.el.querySelector(".sim-tabs");
  tabs.innerHTML = SCENARIOS.map(([k, label]) =>
    `<button type="button" data-k="${k}" class="${k === p.sim.scenario ? "on" : ""}"><i class="${c.risks[k].status}"></i>${label}</button>`).join("");
  tabs.querySelectorAll("button").forEach((b) => (b.onclick = () => { p.sim.scenario = b.dataset.k; mountSim(p); }));
  const vs = p.sim.el.querySelector(".sim-variants");
  vs.innerHTML = variants.length > 1 ? variants.map(([k, label]) =>
    `<button type="button" data-k="${k}" class="${k === p.sim.variant ? "on" : ""}">${label}</button>`).join("") : "";
  vs.querySelectorAll("button").forEach((b) => (b.onclick = () => { p.sim.variant = b.dataset.k; mountSim(p); }));
  loadSim(p);
}

async function loadSim(p) {
  const s = p.sim, c = p.card;
  const key = JSON.stringify([c.answers, s.scenario, s.variant, c.quake_seed]);
  if (key === s.key) return;
  s.key = key;
  const host = s.el.querySelector(".viewer");
  host.classList.add("busy");
  s.el.querySelector(".replay").hidden = true;
  try {
    const res = await fetch("/api/simulate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ run: p.run, piece: p.index, answers: c.answers, scenario: s.scenario, variant: s.variant, seed: c.quake_seed }),
    });
    if (!res.ok) throw new Error(`${res.status}`);
    const trace = await res.json();
    if (s.key !== key) return; // the user switched while this was running
    viewerModule ??= await import("./viewer.js");
    if (!s.viewer) {
      s.viewer = new viewerModule.SimViewer(host);
      s.viewer.onEnd = () => (s.el.querySelector(".replay").hidden = false);
    }
    const cap = host.querySelector(".cap"), events = host.querySelector(".events"), bar = host.querySelector(".bar i");
    let shown = -1;
    s.viewer.onFrame = (t, progress) => {
      const caption = trace.captions.filter(([at]) => at <= t).pop();
      cap.textContent = caption ? caption[1] : "";
      const happened = trace.events.filter(([at]) => at <= t);
      if (happened.length !== shown) {
        shown = happened.length;
        events.innerHTML = happened.map(([, text]) => `<li>${esc(text)}</li>`).join("");
      }
      bar.style.width = `${progress * 100}%`;
    };
    s.viewer.load(trace);
  } catch (err) {
    host.querySelector(".cap").textContent = `Couldn't simulate: ${err.message}`;
  } finally {
    if (s.key === key) host.classList.remove("busy");
  }
}

function answer(p, change) {
  recheck(p, { ...p.card.answers, ...change });
}

async function recheck(p, answers) {
  p.el.classList.add("busy");
  setStatus("Re-checking with your answer…", "busy");
  try {
    const res = await fetch("/api/assess", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ run: p.run, piece: p.index, answers }),
    });
    if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
    const prev = p.card;
    p.card = await res.json();
    p.record.cards[p.index] = p.card;
    render(p, prev);
    saveThread();
  } catch (err) {
    toast(`Couldn't re-check: ${err.message.slice(0, 100)}`);
    render(p);
  } finally {
    p.el.classList.remove("busy");
    summarizeStatus();
  }
}

function thumbStyle(p, box = p.card.box, S = 56) {
  if (!box || !p.still) return "";
  const [W, H] = p.size;
  const [x1, y1, x2, y2] = box;
  const bw = x2 - x1, bh = y2 - y1;
  const k = S / Math.max(bw, bh);
  const ox = x1 * k - (S - bw * k) / 2, oy = y1 * k - (S - bh * k) / 2;
  return `background-image:url('${p.still}');background-size:${W * k}px ${H * k}px;background-position:${-ox}px ${-oy}px`;
}

function detailsHTML(ev) {
  const rows = ev.cards.map((c, i) => {
    const d = c.details;
    return `<tr><td>${i + 1}. ${esc(c.name)}</td><td>${d.size_cm.join(" × ")} cm${d.depth_guessed ? " (depth guessed)" : ""},
      ~${d.mass_kg} kg empty, ${d.mass_with_clothes_kg} kg with clothes, ${d.top_load_kg} kg on top, ${esc(d.material)},
      preset ${esc(d.preset)}, starts rocking at ${d.rocking_starts_g} g. Size from: ${esc(d.size_basis)}</td></tr>`;
  }).join("");
  const timing = Object.entries(ev.report.seconds || {}).map(([k, v]) => `${k} ${v.toFixed(1)} s`).join(", ");
  return `<details class="nerd"><summary>Details</summary><table>${rows}</table><div>${timing}</div>
    <pre>${esc(JSON.stringify(ev.report, null, 2))}</pre></details>`;
}

// --- saved chats ------------------------------------------------------------------------------

let saveTimer;
function saveThread() {
  if (!thread) return;
  const reports = thread.messages.filter((m) => m.report).map((m) => m.report);
  const cards = reports.flatMap((r) => r.cards);
  const firstText = thread.messages.find((m) => m.role === "user" && m.text)?.text;
  thread.title = cards.length ? cards.map((c) => c.name).join(" · ") : firstText?.slice(0, 60) || "Room check";
  thread.thumb = reports[0]?.still || null;
  thread.status = cards.length ? worst(cards.map((c) => c.status)) : null;
  clearTimeout(saveTimer);
  const body = JSON.stringify(thread);
  saveTimer = setTimeout(() => {
    fetch(`/api/threads/${thread.id}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body })
      .catch(() => toast("Couldn't save this chat"));
  }, 250);
}

const worst = (statuses) => ["tips", "maybe", "holds"].find((s) => statuses.includes(s)) || null;
const VERDICT = { tips: "Can tip", maybe: "Might tip", holds: "Stable" };

async function openHistory() {
  els.history.hidden = false;
  els.historyBtn.setAttribute("aria-expanded", "true");
  els.historyList.innerHTML = `<div class="history-empty">Loading…</div>`;
  let list = [];
  try {
    list = await (await fetch("/api/threads")).json();
  } catch {
    els.historyList.innerHTML = `<div class="history-empty">Couldn't load past checks.</div>`;
    return;
  }
  if (!list.length) {
    els.historyList.innerHTML = `<div class="history-empty">Nothing yet. Your checks will show up here.</div>`;
    return;
  }
  els.historyList.innerHTML = list.map((t, i) => `
    <div class="hitem${thread?.id === t.id ? " current" : ""}" role="button" tabindex="0" data-id="${t.id}" style="--i:${i}">
      <span class="hthumb"${t.thumb ? ` style="background-image:url('${t.thumb}')"` : ""}></span>
      <span class="htext"><span class="htitle">${esc(t.title || "Room check")}</span>
        <span class="hmeta"><i class="${t.status || ""}"></i>${t.status ? VERDICT[t.status] + " · " : ""}${ago(t.updated)}</span></span>
      <span class="hdel" role="button" title="Delete">${ICON.close}</span>
    </div>`).join("");
  els.historyList.querySelectorAll(".hitem").forEach((item) => {
    item.onclick = (e) => (e.target.closest(".hdel") ? deleteThread(item.dataset.id) : openThread(item.dataset.id));
    item.onkeydown = (e) => e.key === "Enter" && openThread(item.dataset.id);
  });
}

function closeHistory() {
  els.history.hidden = true;
  els.historyBtn.setAttribute("aria-expanded", "false");
}

els.historyBtn.onclick = () => (els.history.hidden ? openHistory() : closeHistory());
document.addEventListener("click", (e) => {
  if (!els.history.hidden && !e.target.closest("#history, #history-btn")) closeHistory();
});
document.addEventListener("keydown", (e) => e.key === "Escape" && closeHistory());

async function openThread(id) {
  if (busy) return;
  let saved;
  try {
    const res = await fetch(`/api/threads/${id}`);
    if (!res.ok) throw new Error(res.status);
    saved = await res.json();
  } catch {
    return toast("Couldn't open that chat");
  }
  resetChat();
  thread = saved;
  previousId = saved.previous_response_id || null;
  els.empty.hidden = true;
  for (const m of saved.messages) {
    if (m.role === "user") addUserMessage(m.text, m.media);
    else new BotMessage(null, m, true).restore();
  }
  closeHistory();
  summarizeStatus();
}

async function deleteThread(id) {
  await fetch(`/api/threads/${id}`, { method: "DELETE" });
  if (thread?.id === id) newChat();
  openHistory();
}

function ago(iso) {
  const s = (Date.now() - new Date(iso)) / 1000;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  if (s < 172800) return "yesterday";
  return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

// --- helpers ------------------------------------------------------------------------------

function esc(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

function scrollDown() {
  requestAnimationFrame(() => (els.thread.scrollTop = els.thread.scrollHeight));
}

let toastTimer;
function toast(msg) {
  els.toast.textContent = msg;
  els.toast.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (els.toast.hidden = true), 3000);
}
