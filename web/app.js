// Fall-Zero chat. Nobody reads paragraphs, and nothing shows twice. Each photo gets one card of choices
// in the chat: "Help me be sure" questions and the to-do list of fixes (for the room, or the piece when
// the photo has one). Tapping an answer or "I did this" re-runs the physics (/api/assess) in place. A
// glance row (verdict and the three scenarios) shows only while that room's panel is closed.
//
// The panel on the right is the simulation (/api/scene). It follows the chat: the scenario, the piece
// tapped on the photo, the fix being previewed. Below the viewer it shows what the chat doesn't: what
// happens to each piece and what falls, a piece's facts, or how to do the previewed fix.
//
// Each turn POSTs to /api/turn and reads NDJSON: step... -> report -> delta... -> done (or error).
// Muse Spark chains the chat through the last response id. The page saves the whole chat (messages,
// cards, answers) to /api/threads after every turn and tap, so past checks can be reopened.

import {
  RISKS, WORD, garbled, clip, tidy, itemName, pieceName, fixTitle, RANK, KEYS, worstOf, cap1,
  fixGroups, statusWith, roomWith, roomNow, todo, askGroups, plan, bestScenario, STEPS, stepOf, nextLine, costText, timeText,
} from "./flow.js";

const $ = (id) => document.getElementById(id);
const els = {
  empty: $("empty"), tryone: $("tryone"), messages: $("messages"), thread: $("thread"), composer: $("composer"), text: $("text"),
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
  room: svg('<path d="M3 11l9-7 9 7"/><path d="M5 9.5V20h14V9.5"/><path d="M10 20v-6h4v6"/>'),
  // fix icons the skill names (fix.icon), next to strap, lock, top and distance above
  tv: svg('<rect x="3" y="4.5" width="18" height="12" rx="1.5"/><path d="M8.5 20.5h7M12 16.5v4"/>'),
  toy: svg('<circle cx="12" cy="13.5" r="6.5"/><circle cx="6.5" cy="6.5" r="2.3"/><circle cx="17.5" cy="6.5" r="2.3"/><path d="M9.8 12.5v.1M14.2 12.5v.1M10.3 16c1.1.8 2.3.8 3.4 0"/>'),
  weight: svg('<path d="M9.2 8.5a2.8 2.8 0 1 1 5.6 0"/><path d="M6.5 8.5h11l2.5 12H4z"/>'),
  hand: svg('<path d="M8 13V6a1.5 1.5 0 0 1 3 0v5M11 10.5V4.5a1.5 1.5 0 0 1 3 0v6M14 10.5V6a1.5 1.5 0 0 1 3 0v7.5a7 7 0 0 1-7 7h-.5a6 6 0 0 1-4.7-2.3l-2.7-3.5a1.6 1.6 0 0 1 2.5-2L8 14.5"/>'),
  latch: svg('<rect x="3" y="4" width="18" height="16" rx="1.5"/><path d="M12 4v16"/><rect x="8" y="10" width="8" height="4" rx="1.5"/>'),
  search: svg('<circle cx="10.5" cy="10.5" r="6.5"/><path d="M15.5 15.5L21 21"/>'),
  // the how-to and the facts
  clock: svg('<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3.2 2"/>'),
  bag: svg('<path d="M5 8h14l-1.2 12.5H6.2z"/><path d="M9 8V6.5a3 3 0 0 1 6 0V8"/>'),
  ruler: svg('<path d="M3 15.5L15.5 3 21 8.5 8.5 21z"/><path d="M7 11.5l2 2M10 8.5l2 2M13 5.5l2 2"/>'),
  box: svg('<path d="M3 7.5L12 3l9 4.5v9L12 21l-9-4.5z"/><path d="M3 7.5l9 4.5 9-4.5M12 12v9"/>'),
};
const PLACEHOLDER = matchMedia("(max-width: 560px)").matches
  ? "Photo, video or a question"
  : "Add a photo or video of the room, or ask a question";

let previousId = null;
let pending = null; // File waiting to be sent
let busy = false;
let pieces = []; // every piece in this chat: {run, index, n, card, el, still, size, marker, record, room}
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

function attach(file, sample = null) {
  if (!file) return;
  if (!/^(image|video)\//.test(file.type)) return toast("Send a photo or a video");
  pending = file;
  markSample(sample);
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

// What goes up is what the models read anyway: a JPEG at most 1600 px a side (analyze.MAX_SIDE), or a
// video's sharpest frame. Uploads stay far under Vercel's 4.5 MB request limit, and the server needs no ffmpeg.
const MAX_SIDE = 1600;

async function prepared(file) {
  if (file.type.startsWith("video/")) {
    const { canvas, at } = await sharpestFrame(file);
    return { file: await jpeg(canvas, "frame.jpg"), at };
  }
  let bitmap;
  try {
    bitmap = await createImageBitmap(file, { imageOrientation: "from-image" });
  } catch {
    return { file, at: null }; // a format this browser can't draw (HEIC outside Safari): sent as it is
  }
  return { file: await jpeg(fit(bitmap, bitmap.width, bitmap.height), "photo.jpg"), at: null };
}

function fit(source, w, h, side = MAX_SIDE) {
  const k = Math.min(1, side / Math.max(w, h));
  const canvas = Object.assign(document.createElement("canvas"), { width: Math.round(w * k), height: Math.round(h * k) });
  const ctx = canvas.getContext("2d", { willReadFrequently: side < MAX_SIDE });
  ctx.imageSmoothingQuality = "high";
  ctx.drawImage(source, 0, 0, canvas.width, canvas.height);
  return canvas;
}

const jpeg = (canvas, name) => new Promise((ok) =>
  canvas.toBlob((b) => ok(new File([b], name, { type: "image/jpeg" })), "image/jpeg", 0.9));

// The sharpest of n evenly spaced frames, so a phone pan doesn't hand the models a blurred one
async function sharpestFrame(file, n = 8) {
  const video = Object.assign(document.createElement("video"), { muted: true, playsInline: true, preload: "auto" });
  const once = (event) => new Promise((ok, fail) => {
    video.addEventListener(event, ok, { once: true });
    video.addEventListener("error", () => fail(new Error("This video can't be read in this browser")), { once: true });
  });
  video.src = URL.createObjectURL(file);
  try {
    await once("loadeddata");
    const duration = Number.isFinite(video.duration) ? video.duration : 0;
    let best = null;
    for (let i = 0; i < (duration ? n : 1); i++) {
      if (duration) {
        video.currentTime = (duration * (i + 0.5)) / n;
        await once("seeked");
      }
      const canvas = fit(video, video.videoWidth, video.videoHeight);
      const score = sharpness(canvas);
      if (!best || score > best.score) best = { score, canvas, at: duration ? video.currentTime : null };
    }
    return best;
  } finally {
    URL.revokeObjectURL(video.src);
  }
}

// Spread of a Laplacian over a small gray copy: edges smeared by motion score low
function sharpness(canvas) {
  const small = fit(canvas, canvas.width, canvas.height, 400);
  const { data, width: w, height: h } = small.getContext("2d").getImageData(0, 0, small.width, small.height);
  const g = new Float32Array(w * h);
  for (let i = 0; i < w * h; i++) g[i] = 0.299 * data[4 * i] + 0.587 * data[4 * i + 1] + 0.114 * data[4 * i + 2];
  let sum = 0, sq = 0, k = 0;
  for (let y = 1; y < h - 1; y++) {
    for (let x = 1; x < w - 1; x++) {
      const i = y * w + x, l = 4 * g[i] - g[i - 1] - g[i + 1] - g[i - w] - g[i + w];
      sum += l; sq += l * l; k++;
    }
  }
  return k ? sq / k - (sum / k) ** 2 : 0;
}

function clearAttachment() {
  pending = null;
  markSample(null);
  els.attachment.hidden = true;
  els.attachment.innerHTML = "";
  els.composer.classList.remove("has-media");
  els.text.placeholder = PLACEHOLDER;
  updateSend();
}

async function attachSample(button) {
  const src = button.dataset.src;
  const blob = await (await fetch(src)).blob();
  attach(new File([blob], src.split("/").pop(), { type: blob.type }), button);
}

// the sample room that's attached gets a ring, so it's clear which one goes
function markSample(button) {
  document.querySelectorAll(".sample").forEach((b) => b.classList.toggle("on", b === button));
}

$("pick").onclick = () => els.file.click();
els.file.onchange = () => { attach(els.file.files[0]); els.file.value = ""; };
document.querySelectorAll(".sample").forEach((b) => (b.onclick = () => attachSample(b)));

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
  closePanel();
  previousId = null;
  pieces = [];
  thread = null;
  els.messages.innerHTML = "";
  clearAttachment();
  els.text.value = "";
}

// The welcome screen and the sample rooms above the chat bar show together, only while the chat is empty
function showEmpty(on) {
  els.empty.hidden = !on;
  els.tryone.hidden = !on;
  if (!on) openStep(null);
}

// How to use it: one step card is open at a time (the mouse over it, keyboard focus, or a tap; a second tap
// closes it). The open card widens and plays its recording from the start; with reduced motion it only shows
// the still, with controls to play it.
const flow = document.querySelector(".flow");
const calm = matchMedia("(prefers-reduced-motion: reduce)");
function openStep(li) {
  const was = flow.querySelector("li.open");
  if (was === li) return;
  if (was) {
    was.classList.remove("open");
    was.querySelector("video").pause();
  }
  if (!li) return delete flow.dataset.open;
  li.classList.add("open");
  flow.dataset.open = [...flow.children].indexOf(li);
  const video = li.querySelector("video");
  video.controls = calm.matches;
  if (calm.matches) return;
  video.currentTime = 0;
  video.play().catch(() => {}); // a still is fine if the clip can't play
}
for (const li of flow.children) {
  let tappedOpen = false;
  li.addEventListener("pointerenter", (e) => e.pointerType === "mouse" && openStep(li));
  li.addEventListener("pointerdown", (e) => (tappedOpen = e.pointerType !== "mouse" && li.classList.contains("open")));
  li.addEventListener("focus", () => openStep(li));
  li.addEventListener("click", () => openStep(tappedOpen ? null : li));
}
flow.addEventListener("pointerleave", (e) => e.pointerType === "mouse" && openStep(null));
flow.addEventListener("focusout", (e) => !flow.contains(e.relatedTarget) && !flow.matches(":hover") && openStep(null));

function newChat() {
  if (busy) return;
  resetChat();
  showEmpty(true);
  els.empty.style.animation = "none";
  void els.empty.offsetWidth;
  els.empty.style.animation = "";
  closeHistory();
  summarizeStatus();
}
$("new-chat").onclick = $("home").onclick = newChat;

// --- voice: record, then Muse Voice Transcribe fills the text box -----------------------

let recorder = null;
// The recording as the 24 kHz mono 16-bit WAV the transcriber takes (voice.RATE), made here so the server
// needs no ffmpeg
async function toWav(recording, rate = 24000) {
  const ctx = new AudioContext();
  const audio = await ctx.decodeAudioData(await recording.arrayBuffer()).finally(() => ctx.close());
  const offline = new OfflineAudioContext(1, Math.ceil(audio.duration * rate), rate);
  const src = Object.assign(offline.createBufferSource(), { buffer: audio });
  src.connect(offline.destination);
  src.start();
  const pcm = (await offline.startRendering()).getChannelData(0);
  const view = new DataView(new ArrayBuffer(44 + pcm.length * 2));
  const text = (at, s) => [...s].forEach((c, i) => view.setUint8(at + i, c.charCodeAt(0)));
  text(0, "RIFF"); view.setUint32(4, 36 + pcm.length * 2, true); text(8, "WAVEfmt ");
  view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true);
  view.setUint32(24, rate, true); view.setUint32(28, rate * 2, true); view.setUint16(32, 2, true); view.setUint16(34, 16, true);
  text(36, "data"); view.setUint32(40, pcm.length * 2, true);
  pcm.forEach((x, i) => view.setInt16(44 + i * 2, Math.max(-1, Math.min(1, x)) * 0x7fff, true));
  return new Blob([view], { type: "audio/wav" });
}

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
    setStatus("Listening back…", "busy");
    try {
      form.append("audio", await toWav(new Blob(chunks, { type: chunks[0]?.type || "audio/webm" })), "voice.wav");
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
  showEmpty(false);
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
  if (!file && pieces.length) form.append("context", JSON.stringify(pieces.map(contextOf)));
  els.text.value = "";
  els.text.style.height = "auto";
  clearAttachment();
  setStatus(file ? "Uploading…" : "Thinking…", "busy");

  const bot = new BotMessage(file, botRecord);
  bot.onReport = (ev) => (userRecord.media = { url: ev.upload, video: false }); // a video is kept as its frame
  try {
    if (file) {
      const up = await prepared(file);
      form.append("media", up.file, up.file.name);
      if (up.at != null) form.append("frame_at_s", up.at.toFixed(2));
    }
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
  piece: `${p.n}. ${pieceName(p.card)}`, verdict: p.card.headline,
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
    this.restoring = restoring;
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
    if (this.record.say) this.say.innerHTML = md(this.record.say);
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
    top.innerHTML = ev.cards.length ? stillFigure(ev) : `<figure class="still"><img src="${ev.still}" alt=""></figure>`;
    const cards = this.el.querySelector(".cards");
    // One card of choices for the photo (questions and fixes, for the room or its one piece). The
    // simulation and the details open in the panel, from a scenario, an outline or a fix's "Show me".
    const room = { ev, pieces: [], el: document.createElement("article"), figure: top.querySelector(".still") };
    ev.cards.forEach((card, index) => {
      const p = { run: ev.run, index, n: pieces.length + 1, card, still: ev.still, size: ev.size, record: ev, room, el: room.el };
      p.marker = top.querySelector(`[data-piece="${index}"]`);
      p.marker?.setAttribute("data-n", p.n);
      top.querySelectorAll(`[data-piece="${index}"] text`).forEach((t) => (t.textContent = p.n));
      if (p.marker) p.marker.onclick = () => openPanel(room, { focus: p, ...(pnl.room === room && { scenario: pnl.scenario, variant: pnl.variant }) });
      pieces.push(p);
      room.pieces.push(p);
    });
    if (room.pieces.length) {
      cards.append(room.el);
      // a new check opens straight onto the room's worst scenario, where there's room for the panel
      if (!this.restoring && matchMedia("(min-width: 901px)").matches) openPanel(room);
      renderCard(room);
    }
    let tail = "";
    if (ev.others.length) {
      tail += `<p class="also">Also saw ${ev.others.map((o) => esc(clip(o, 40))).join(", ")}. I can't check ${ev.others.length > 1 ? "those" : "that"} yet.</p>`;
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
    this.say.innerHTML = md(this.raw);
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

// --- the analyzed frame, with each piece outlined ------------------------------------------------

// SAM's real outline when the report has one (older reports only have a box)
function shape(item, attrs) {
  if (item.outline) return `<path d="${item.outline}" pathLength="1" ${attrs}/>`;
  const [x1, y1, x2, y2] = item.box;
  return `<rect x="${x1}" y="${y1}" width="${x2 - x1}" height="${y2 - y1}" pathLength="1" ${attrs}/>`;
}

function stillFigure(ev) {
  const [w, h] = ev.size;
  const r = Math.max(w, h) * 0.03;
  // what stands on each piece: dashed outlines with a small tag, drawn first so the pieces sit on top
  const things = ev.cards.flatMap((c) => c.items.filter((it) => it.box)).map((it, j) => {
    const [x1, y1] = it.box;
    const word = itemName(it);
    const tw = word.length * r * 0.62 + r * 0.8;
    return `<g class="thing" style="--i:${j}">
      ${shape(it, 'stroke="#fff" stroke-dasharray="1"')}${shape(it, 'class="dash"')}
      <rect x="${x1}" y="${y1 - r * 1.3}" width="${tw}" height="${r * 1.2}" rx="${r * 0.3}" class="tag"/>
      <text x="${x1 + r * 0.4}" y="${y1 - r * 0.42}" font-size="${r * 0.9}" font-weight="700" fill="#fff">${esc(word)}</text></g>`;
  }).join("");
  const outlines = ev.cards.map((c, i) => {
    if (!c.box) return "";
    const [x1, y1] = c.box;
    return `<g data-piece="${i}" style="color:var(--${c.status})">${shape(c, 'class="shape"')}
      <circle cx="${x1 + r}" cy="${y1 + r}" r="${r}" fill="currentColor"/>
      <text x="${x1 + r}" y="${y1 + r * 1.38}" fill="#fff" font-size="${r * 1.1}" font-weight="700" text-anchor="middle">${i + 1}</text></g>`;
  }).join("");
  const at = ev.frame_at_s != null ? `<figcaption class="also">Frame at ${ev.frame_at_s.toFixed(1)} s</figcaption>` : "";
  return `<figure class="still"><img src="${ev.still}" alt="The checked photo">
    <svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">${outlines.length ? things + outlines : ""}</svg>${at}</figure>`;
}

// --- shared pieces of the cards ------------------------------------------------------------------

const pn = (p, s = p.card.status) => `<span class="pn ${s}">${p.n}</span>`;
const badges = (ps) => [...new Set(ps)].map((p) => pn(p)).join("");
const HAZARD_ORDER = { danger: 0, caution: 1, fine: 2 };
const byHazard = (a, b) => (HAZARD_ORDER[a.level] ?? 2) - (HAZARD_ORDER[b.level] ?? 2);
const afterIcons = (after) =>
  `<div class="after">${RISKS.map(([k, label]) => `<i class="${after[k]}" title="${label}: ${WORD[after[k]]}">${ICON[k]}</i>`).join("")}</div>`;
const fixIcon = (f) => ICON[f.icon] || ICON.wrench;

// keys drawn on this card last time; only new questions and fixes animate in
function enterer(room) {
  const seen = room.seen, next = new Set();
  let i = 0;
  const enter = (key) => {
    next.add(key);
    return seen?.has(key) ? { cls: "", style: "" } : { cls: " enter", style: ` style="--i:${i++}"` };
  };
  enter.done = () => (room.seen = next);
  return enter;
}

function roomHeadline(room) {
  const ps = room.pieces;
  if (ps.length === 1) return { status: ps[0].card.status, headline: ps[0].card.headline, name: esc(pieceName(ps[0].card)) };
  const status = worstOf(ps.map((p) => p.card.status));
  const count = (s) => ps.filter((p) => p.card.status === s).length;
  const headline = status === "holds" ? "Everything here is stable"
    : [[count("tips"), "can tip"], [count("maybe"), "might tip"]].filter(([n]) => n).map(([n, w]) => `${n} ${w}`).join(", ");
  const where = room.ev.report.room ? `This ${esc(clip(room.ev.report.room, 24))}` : "This room";
  return { status, headline: cap1(headline), name: `${where} · ${ps.length} pieces` };
}

// --- the card in the chat: a couple of choices, never what the panel shows -------------------------

const TODO_SHOWN = 4, ASKS_SHOWN = 2; // longer lists fold the rest behind "N more"

function glanceHTML(room, head) {
  const now = roomNow(room);
  return `<div class="glance"><div class="gin">
    <button class="gv" type="button" title="See it happen">${ICON[head.status]}<span><small>${head.name}</small><b>${esc(head.headline)}</b></span></button>
    <div class="gk">${RISKS.map(([k, label]) => `<button class="gs ${now[k]}" type="button" data-k="${k}" title="${label}: ${WORD[now[k]]}">
      ${ICON[k]}<i>${ICON[now[k]]}</i></button>`).join("")}</div></div></div>`;
}

function askHTML(room, asks, enter) {
  const multi = room.pieces.length > 1;
  return asks.map((a, i) => {
    const q = a.q, e = enter(`q:${a.key}`);
    const who = multi ? `<span class="who">${badges(a.members)}</span>` : "";
    const head = `<div class="qt">${who}<span>${esc(clip(q.title, 90))}</span></div>${q.hint ? `<div class="qh">${esc(clip(q.hint, 140))}</div>` : ""}`;
    if (q.kind === "measure") {
      return `<div class="q${e.cls}"${e.style} data-a="${i}">${head}
        <div class="dims">${[["width_cm", "Width"], ["depth_cm", "Depth"], ["height_cm", "Height"]].map(([k, l]) =>
          `<label>${l} cm<input type="number" inputmode="numeric" min="10" max="400" name="${k}" placeholder="${q.guess[k]}"></label>`).join("")}</div>
        <button class="go" type="button">Check with these</button></div>`;
    }
    return `<div class="q${e.cls}"${e.style} data-a="${i}">${head}
      <div class="opts">${q.options.map((o) =>
        `<button type="button" data-v="${esc(JSON.stringify(o.value))}">${esc(clip(o.label, 40))}${o.sub ? `<small>${esc(clip(o.sub, 48))}</small>` : ""}</button>`).join("")}</div></div>`;
  }).join("");
}

// A small fact chip (cost, time, what to buy); its text stays on one line inside its row
const chip = (text, icon = "", cls = "") =>
  text ? `<span class="tchip${cls ? ` ${cls}` : ""}" title="${esc(text)}">${icon}<span>${esc(text)}</span></span>` : "";

// One row of the to-do list: what, which pieces, what it costs; "Show me" previews it in the panel
function todoRow(room, g, i, enter) {
  const e = enter(`f:${g.key}`);
  const how = g.f.how || {};
  const meta = [
    room.pieces.length > 1 ? `<span class="who">${badges(g.members.map((m) => m.p))}</span>` : "",
    chip(costText(how)), chip(timeText(how), ICON.clock, "time"),
  ].join("");
  const show = g.done ? "" : `<button class="show-btn" type="button" title="Show it in the simulation">${ICON.play}<span>Show me</span></button>`;
  const did = `<button class="done-btn" type="button">${g.done ? `${ICON.holds}Done` : "I did this"}</button>`;
  return `<div class="trow${g.done ? " done" : ""}${e.cls}"${e.style} data-g="${i}">
    <span class="ficon">${g.done ? ICON.holds : fixIcon(g.f)}</span>
    <div class="tt"><div class="ft">${esc(g.title)}</div>${meta ? `<div class="tm">${meta}</div>` : ""}</div>
    <div class="acts">${show}${did}</div></div>`;
}

// A good habit (advice with nothing to tick off or simulate): a chip; the panel says how
function habitChip(room, g, i, enter) {
  const e = enter(`h:${g.key}`);
  const who = room.pieces.length > 1 ? `<span class="who">${badges(g.members.map((m) => m.p))}</span>` : "";
  return `<button type="button" class="habit${e.cls}"${e.style} data-g="${i}" title="How">${fixIcon(g.f)}<span>${esc(g.title)}</span>${who}</button>`;
}

// --- where the room is: the steps of a check, and the one thing to do next ------------------------

const TRACK = [["find", "What can fall"], ["sure", "Be sure"], ["plan", "Plan"], ["fix", "Fix"], ["check", "Check"]];

// The steps, ticked up to the room's own (all of them once it's safe), and the "Next:" line under them.
// "Be sure" and "Plan" can be tapped to go back to the questions or past them.
function trackHTML(room, step, asks) {
  const at = STEPS.indexOf(step);
  const steps = TRACK.map(([key, label], i) => {
    const state = i < at ? "done" : i === at ? "now" : "";
    const tap = (key === "sure" && asks.length && step !== "sure") || (key === "plan" && step === "sure");
    const inner = `<i>${state === "done" ? ICON.holds : i + 1}</i><b>${label}</b>`;
    return `<li class="${state}">${tap ? `<button type="button" data-step="${key}">${inner}</button>` : `<span>${inner}</span>`}</li>`;
  }).join("");
  const next = nextLine(room);
  const g = next.key && room.groups.find((x) => x.key === next.key);
  const icon = step === "sure" ? ICON.ask : step === "safe" ? (next.text.startsWith("Everything") ? ICON.holds : ICON.ask) : g ? fixIcon(g.f) : ICON.wrench;
  const who = room.pieces.length > 1 && next.pieces.length ? `<span class="who">${badges(next.pieces.map((n) => room.pieces.find((p) => p.n === n)))}</span>` : "";
  return `<div class="flowbar"><ol class="track" aria-label="Steps">${steps}</ol>
    ${next.text ? `<button class="next ${step}" type="button"><span class="ni">${icon}</span><span class="nt">${esc(next.text)}</span>${who}</button>` : ""}</div>`;
}

// The "Next:" line does what it says: shows the question, previews the fix, or opens a new photo
function goNext(room) {
  const next = nextLine(room);
  if (next.step === "sure") {
    const q = room.el.querySelector(".q");
    q?.scrollIntoView({ block: "center", behavior: calm.matches ? "auto" : "smooth" });
    q?.classList.remove("flash");
    void q?.offsetWidth; // restart the animation
    q?.classList.add("flash");
  } else if (next.step === "plan") {
    const g = room.groups.find((x) => x.key === next.key);
    if (g) showFix(room, g);
  } else if (next.step === "safe") {
    if (next.text.startsWith("Everything")) els.file.click();
    else els.text.focus();
  }
}

function renderCard(room) {
  const ps = room.pieces;
  const head = roomHeadline(room);
  const enter = enterer(room);
  const asks = askGroups(room);
  const groups = todo(room);
  const fold = (list, n, open) => (!open && list.length > n + 1 ? n : list.length);
  const acts = groups.filter((g) => g.act), habits = groups.filter((g) => !g.act);
  const nAsks = fold(asks, ASKS_SHOWN, room.moreAsks), nRows = fold(acts, TODO_SHOWN, room.more);
  const moreBtn = (n, what) => (n ? `<button class="more" type="button" data-more="${what}">${n} more</button>` : "");
  const at = (g) => groups.indexOf(g); // rows and chips point into room.groups
  const rows = acts.slice(0, nRows).map((g) => todoRow(room, g, at(g), enter)).join("") + moreBtn(acts.length - nRows, "todo");
  const chips = habits.length ? `<div class="habits">${habits.map((g) => habitChip(room, g, at(g), enter)).join("")}</div>` : "";
  const notes = ps.filter((p) => p.card.note).map((p) => `<p class="note">${ps.length > 1 ? pn(p) : ""}${esc(clip(p.card.note, 140))}</p>`).join("");
  const popped = room.status && room.status !== head.status;
  room.status = head.status;
  room.asks = asks;
  room.groups = groups;

  const step = stepOf(room);
  const asking = asks.length && step === "sure";
  const folded = asks.length && !asking
    ? `<button class="asked" type="button" data-step="sure">${ICON.ask}<span>Help me be sure</span><i>${asks.length}</i></button>` : "";

  room.el.className = `card choices ${head.status}${pnl.room === room ? " open" : ""}${room.pending ? " busy" : ""}`;
  room.el.innerHTML = `${glanceHTML(room, head)}${trackHTML(room, step, asks)}
    ${asking ? `<section class="block"><h4>${ICON.ask}Help me be sure</h4><div class="asks">${askHTML(room, asks.slice(0, nAsks), enter)}</div>${moreBtn(asks.length - nAsks, "asks")}</section>` : ""}
    ${acts.length ? `<section class="block"><h4>${ICON.wrench}${head.status === "holds" ? "Keep it that way" : "Do these first"}</h4>
      <div class="todo">${rows}</div></section>` : ""}
    ${habits.length ? `<section class="block"><h4>${ICON.hand}Good habits</h4>${chips}</section>` : ""}
    ${!asks.length && !groups.length ? `<div class="calm">${ICON.holds}Nothing to do here</div>` : ""}${folded}${notes}`;
  enter.done();
  if (popped) room.el.querySelector(".gv")?.classList.add("pop");
  ps.forEach((p) => p.marker && (p.marker.style.color = `var(--${p.card.status})`));
  bindCard(room);
  markOpen();
}

function bindCard(room) {
  const el = room.el;
  el.querySelectorAll("[data-step]").forEach((b) => (b.onclick = () => {
    room.skipAsks = b.dataset.step === "plan";
    renderCard(room);
    if (!room.skipAsks) goNext(room);
  }));
  el.querySelector(".next")?.addEventListener("click", () => goNext(room));
  el.querySelector(".gv").onclick = () => openPanel(room);
  el.querySelectorAll(".gs").forEach((b) => (b.onclick = () => openPanel(room, { scenario: b.dataset.k })));
  el.querySelectorAll("[data-a]").forEach((qEl) => {
    const a = room.asks[+qEl.dataset.a];
    qEl.querySelectorAll(".opts button").forEach((b) => (b.onclick = () => {
      b.classList.add("picked");
      a.members.forEach((p) => answer(p, { [a.q.key]: JSON.parse(b.dataset.v) }));
    }));
    qEl.querySelector(".go")?.addEventListener("click", () => {
      const vals = Object.fromEntries([...qEl.querySelectorAll("input")].map((x) => [x.name, parseFloat(x.value)]));
      if (Object.values(vals).some((v) => !(v >= 10 && v <= 400))) return toast("Fill in all three, in cm");
      answer(a.members[0], { measured: vals });
    });
  });
  el.querySelectorAll(".trow[data-g]").forEach((row) => {
    const g = room.groups[+row.dataset.g];
    row.querySelector(".done-btn")?.addEventListener("click", (e) => {
      e.currentTarget.classList.add("working");
      toggleDone(g.members, !g.done);
    });
    row.querySelector(".show-btn")?.addEventListener("click", () => showFix(room, g));
  });
  el.querySelectorAll(".habit[data-g]").forEach((b) => (b.onclick = () => showFix(room, room.groups[+b.dataset.g])));
  el.querySelectorAll("[data-more]").forEach((b) => (b.onclick = () => {
    if (b.dataset.more === "asks") room.moreAsks = true;
    else room.more = true;
    renderCard(room);
  }));
}

// "Show me": the panel plays the room with this fix done and says how to do it; tapped again, as it is
function showFix(room, g) {
  if (pnl.room === room && pnl.variant === g.key) return openPanel(room, { focus: pnl.focus, scenario: pnl.scenario });
  const focus = pnl.room === room && g.members.some((m) => m.p === pnl.focus) ? pnl.focus : null;
  const here = pnl.room === room ? pnl.scenario : null;
  const keep = here && g.members.some(({ p }) => RANK[statusWith(p, here, g)] < RANK[p.card.risks[here].status]);
  openPanel(room, { focus, scenario: keep ? here : bestScenario(g) || here, variant: g.key });
}

function toggleDone(members, done) {
  for (const { p, f } of members) {
    if (!f.answer) continue;
    if (done && !f.done) answer(p, f.answer);
    else if (!done && f.done) {
      const next = { ...p.card.answers };
      Object.keys(f.answer).forEach((k) => delete next[k]);
      recheck(p, next);
    }
  }
}

// --- the panel: the whole room's simulation, and what the chat doesn't show -----------------------

let viewerModule = null;
const panelEl = $("panel");
const pnl = {
  room: null, focus: null, scenario: "quake", variant: null, // what it shows; `variant` is a fix group's key or "plan"
  key: null, viewer: null, shownRoom: null, shownFocus: null, shownScenario: null, tips: [], // what the viewer last loaded
  who: panelEl.querySelector(".p-who"), back: panelEl.querySelector(".p-back"), tabs: panelEl.querySelector(".p-tabs"),
  host: panelEl.querySelector(".viewer"), variants: panelEl.querySelector(".p-variants"), body: panelEl.querySelector(".p-body"),
};
pnl.back.onclick = () => openPanel(pnl.room, { scenario: pnl.scenario, variant: pnl.variant });
// the fix pills are one row: an edge fades out while more pills hide past it, and a mouse wheel slides it
const pillFade = () => {
  const el = pnl.variants;
  el.classList.toggle("fade", el.scrollLeft + el.clientWidth < el.scrollWidth - 16); // past the row's own padding
  el.classList.toggle("fade-l", el.scrollLeft > 16);
};
pnl.variants.addEventListener("scroll", pillFade, { passive: true });
pnl.variants.addEventListener("wheel", (e) => {
  const el = pnl.variants;
  if (el.scrollWidth <= el.clientWidth || Math.abs(e.deltaX) > Math.abs(e.deltaY)) return;
  el.scrollLeft += e.deltaY;
  e.preventDefault();
}, { passive: false });
addEventListener("resize", () => pnl.room && pillFade());
panelEl.querySelector(".p-close").onclick = closePanel;
pnl.host.querySelector(".replay").onclick = () => {
  pnl.host.querySelector(".replay").hidden = true;
  pnl.tips = [];
  pnl.viewer?.play();
};

// the scenario to open with: the first that tips, then the first that might
function worstScenario(statuses) {
  return KEYS.find((k) => statuses[k] === "tips") || KEYS.find((k) => statuses[k] === "maybe") || "quake";
}

function openPanel(room, { focus = null, scenario = null, variant = null } = {}) {
  if (room.pieces.length === 1) focus = room.pieces[0];
  const moved = pnl.room !== room || pnl.focus !== focus;
  pnl.room = room;
  pnl.focus = focus;
  pnl.scenario = scenario || (moved ? worstScenario(focus ? Object.fromEntries(KEYS.map((k) => [k, focus.card.risks[k].status])) : roomNow(room)) : pnl.scenario);
  pnl.variant = variant;
  document.body.classList.add("panel-open");
  panelEl.inert = false;
  renderPanel(moved);
}

function closePanel() {
  if (!pnl.room) return;
  document.body.classList.remove("panel-open");
  panelEl.inert = true;
  pnl.room = pnl.focus = pnl.variant = null;
  markOpen(); // the glance row comes back
}

// The variant the panel shows: a fix group, "all together" (each scenario's own plan), or none
function findVariant(room, key) {
  if (!key) return null;
  if (key === "plan") {
    const plans = Object.fromEntries(KEYS.map((k) => [k, plan(room, k)]));
    return { key, plan: true, plans, sim: true };
  }
  const g = fixGroups(room).find((x) => x.key === key);
  return g && !g.done ? g : null; // a fix that's done is simply how the room is now
}

// The fixes to play over the viewer: in the room, "all together" and what helps this scenario; for a piece, its own
function pillsFor(room, p, k, v) {
  const helps = (g) => g.members.filter(({ p: q }) => RANK[statusWith(q, k, g)] < RANK[q.card.risks[k].status]).length;
  // a piece plays only its own fixes, and a judged piece has nothing to play
  const own = (g) => !p.card.judged && g.members.some((m) => m.p === p && m.f.answer && !m.f.done);
  const groups = fixGroups(room).filter((g) => g.sim && !g.done && (p ? own(g) : helps(g)));
  if (!p) groups.sort((a, b) => RANK[roomWith(room, k, a)] - RANK[roomWith(room, k, b)] || helps(b) - helps(a));
  const multi = room.pieces.length > 1;
  const pills = groups.slice(0, p ? 4 : 3).map((g) => ({ key: g.key, label: `${fixIcon(g.f)}<span>${esc(g.title)}</span>${multi && !p ? badges(g.members.map((m) => m.p)) : ""}` }));
  const all = plan(room, k);
  if (!p && all.members.length > 1) pills.unshift({ key: "plan", label: `${ICON.holds}<span>All together</span>${badges(all.members.map((m) => m.p))}` });
  if (v?.sim && !v.plan && (!p || own(v)) && !pills.some((o) => o.key === v.key)) {
    pills.push({ key: v.key, label: `${fixIcon(v.f)}<span>${esc(v.title)}</span>` });
  }
  return pills;
}

function renderPanel(moved = false) {
  const { room, focus: p } = pnl;
  if (!room) return;
  const k = pnl.scenario;
  const multi = room.pieces.length > 1;
  const v = findVariant(room, pnl.variant);
  if (!v) pnl.variant = null;
  pnl.back.hidden = !(multi && p);

  // who: the piece, or the room, as it is now
  const head = p ? { status: p.card.status, headline: p.card.headline, name: esc(pieceName(p.card)) } : roomHeadline(room);
  pnl.who.className = `p-who ${head.status}${moved ? " swap" : ""}`;
  pnl.who.innerHTML = `${p ? `<div class="thumb" style="${thumbStyle(p, p.card.box, 44)}">${multi ? `<span class="num">${p.n}</span>` : ""}</div>`
    : `<div class="thumb room-icon">${ICON.room}</div>`}
    <div style="min-width:0"><div class="name">${head.name}</div><div class="verdict">${ICON[head.status]}<span>${esc(head.headline)}</span></div></div>`;

  // the three scenarios, each with what's shown: as it is, or with the previewed fix
  pnl.tabs.innerHTML = RISKS.map(([key, label]) => {
    const s = p ? statusWith(p, key, v) : roomWith(room, key, v);
    const was = p ? p.card.risks[key].status : roomWith(room, key, null);
    const behind = p || s === "holds" ? "" : room.pieces.filter((q) => statusWith(q, key, v) === s).map((q) => pn(q, s)).join("");
    return `<button type="button" class="p-tab ${s}${key === k ? " on" : ""}${s !== was ? " better" : ""}" data-k="${key}">
      <span class="ricon">${ICON[key]}</span><span class="tl">${label}</span><span class="ts">${ICON[s]}${WORD[s]}${behind}</span></button>`;
  }).join("");
  pnl.tabs.querySelectorAll(".p-tab").forEach((b) => (b.onclick = () => {
    pnl.scenario = b.dataset.k;
    renderPanel();
  }));

  // the fixes the viewer can play, over the viewer
  const pills = pillsFor(room, p, k, v);
  const asIs = room.pieces.some((q) => q.card.answers.anchored === "yes") ? "As it is now (strapped)" : "As it is now";
  const on = v?.sim ? v.key : null;
  pnl.variants.innerHTML = pills.length ? [{ key: null, label: `<span>${asIs}</span>` }, ...pills].map((o) =>
    `<button type="button" class="${o.key === on ? "on" : ""}" data-v="${esc(o.key ?? "")}">${o.label}</button>`).join("") : "";
  pnl.variants.querySelectorAll("button").forEach((b) => (b.onclick = () => {
    pnl.variant = b.dataset.v || null;
    renderPanel();
  }));
  const shownPill = pnl.variants.querySelector(".on");
  pnl.variants.scrollLeft = 0;
  if (shownPill && shownPill.offsetLeft + shownPill.offsetWidth > pnl.variants.scrollLeft + pnl.variants.clientWidth) {
    pnl.variants.scrollLeft = shownPill.offsetLeft + shownPill.offsetWidth - pnl.variants.clientWidth + 40;
  }
  pillFade();

  // below: how to do the previewed fix, or what happens (to each piece, or this piece's facts)
  pnl.body.classList.toggle("swap", moved);
  pnl.body.innerHTML = v && !v.plan ? howHTML(room, v, p, k) : p ? factsHTML(p, k, v) : happensHTML(room, k, v);
  pnl.body.querySelectorAll("[data-n]").forEach((b) => (b.onclick = () => openPanel(room, { focus: room.pieces.find((q) => q.n === +b.dataset.n), scenario: k, variant: pnl.variant })));
  if (moved) pnl.body.scrollTop = 0;

  markOpen();
  loadScene();
}

const WHEN = { child: "a child climbs", adult: "someone leans on it", quake: "the floor shakes" };
const WHERE = { top: "on top", shelf: "on a shelf" };

// An item that would come down: thumb, name, how heavy and from how high, colored by how much it hurts
function thingHTML(p, it, multi) {
  const facts = [it.kg != null ? `${+(+it.kg).toFixed(1)} kg` : "", it.drop_m != null ? `${(+it.drop_m).toFixed(1)} m` : ""].filter(Boolean).join(" · ");
  const where = it.where && WHERE[it.where] ? `<em>${WHERE[it.where]}</em>` : "";
  return `<span class="obj ${it.level || "fine"}" title="${esc(clip(it.why || "", 160))}"><i style="${thumbStyle(p, it.box, 30)}"></i>
    <span><b><span class="on">${esc(itemName(it))}</span>${it.tempting ? `<span class="tempt" title="A child would climb for it">${ICON.toy}</span>` : ""}</b>
    ${facts || where ? `<small>${facts}${facts && where ? " · " : ""}${where}</small>` : ""}</span>${multi ? pn(p) : ""}</span>`;
}

// The items a variant takes off (a "move it lower" fix being previewed) don't fall
function stays(p, idx, v) {
  const m = v?.plan ? null : v?.members.find((x) => x.p === p);
  return (m?.f.answer?.moved || []).includes(idx);
}

// Room, scenario k: what each piece does, and what comes down with it
function happensHTML(room, k, v) {
  const multi = room.pieces.length > 1;
  const tiles = room.pieces.map((p) => {
    const s = statusWith(p, k, v);
    const used = v?.plan ? v.plans[k].members.find((m) => m.p === p)?.f : null;
    const says = used ? `${fixIcon(used)}${esc(fixTitle(used))}` : esc(clip(p.card.risks[k].says, 140));
    return `<button type="button" class="ptile ${s}" data-n="${p.n}">
      <span class="thumb" style="${thumbStyle(p, p.card.box, 46)}"><span class="num">${p.n}</span></span>
      <span class="pt"><span class="pname">${esc(pieceName(p.card))}</span><b>${ICON[s]}${WORD[s]}</b><small>${says}</small></span></button>`;
  }).join("");
  const falling = room.pieces.flatMap((p) => p.card.items.map((it, i) => ({ p, it, i })))
    .filter(({ p, it, i }) => !it.moved && !stays(p, i, v) && it.level && it.level !== "fine" && (statusWith(p, k, v) !== "holds" || (k === "quake" && it.falls)))
    .sort((a, b) => byHazard(a.it, b.it)).slice(0, 6);
  const things = falling.length ? `<div class="falls"><span class="lbl">${ICON.tips}Would fall</span>${falling.map(({ p, it }) => thingHTML(p, it, multi)).join("")}</div>` : "";
  const calm = roomWith(room, k, v) === "holds" ? `<div class="calm small">${ICON.holds}Nothing here tips when ${WHEN[k]}</div>` : "";
  return `<div class="ptiles" style="--n:${room.pieces.length}">${tiles}</div>${things || calm}`;
}

// One piece: what scenario k does to it, then its facts (size, weight, what it holds, what's on it)
function factsHTML(p, k, v) {
  const c = p.card, d = c.details || {};
  const s = statusWith(p, k, v);
  const outcome = `<div class="outcome ${s}"><span class="oi">${ICON[k]}</span><span><b>${ICON[s]}${WORD[s]}</b>
    <small>${esc(clip(c.risks[k].says, 140))}</small></span></div>`;
  const fact = (icon, label, value, sub) => `<div class="fact"><small>${icon}${label}</small>${value}${sub ? `<span>${sub}</span>` : ""}</div>`;
  const tiles = [];
  if (c.judged) {
    tiles.push(fact(ICON.search, "Judged", "<b>From safety guidance</b>", "Not built to simulate"));
  } else {
    if (d.size_cm) {
      const [w, dp, h] = d.size_cm.map(Math.round);
      tiles.push(fact(ICON.ruler, "Size", `<b>${w} × ${d.depth_guessed ? "~" : ""}${dp} × ${h}</b>`, "cm · w × d × h"));
    }
    const kg = d.mass_kg != null ? Math.round(d.mass_kg) : null;
    const full = d.mass_full_kg ?? d.mass_with_clothes_kg;
    const loaded = full != null && Math.round(full) !== kg ? Math.round(full) : null;
    if (kg != null) {
      tiles.push(fact(ICON.weight, "Weight", `<b>${kg} kg${loaded != null ? `<span class="to">→</span>${loaded} kg` : ""}</b>`,
        loaded != null ? "empty → full" : "empty"));
    }
    if (d.holds?.length) {
      const rows = d.holds.slice(0, 3).map((h) =>
        `<span class="hrow"><b>${esc(cap1(tidy(24, h.what) || "Things"))}</b>${h.kg != null ? `<em>${Math.round(h.kg)} kg</em>` : ""}</span>`);
      tiles.push(fact(ICON.box, "Holds", `<span class="holds">${rows.join("")}</span>`));
    }
  }
  const items = c.items.filter((it, i) => !it.moved && !stays(p, i, v)).sort(byHazard).slice(0, 6);
  const things = items.length ? `<div class="falls"><span class="lbl">${ICON.top}On it</span>${items.map((it) => thingHTML(p, it, false)).join("")}</div>` : "";
  return `<div class="facts" style="--nf:${tiles.length}">${outcome}${tiles.join("")}</div>${things}`;
}

// The previewed fix: what it changes, then how to do it (what to buy, cost, time, tools, steps). The
// chat's row already shows the cost and time beside the panel, so here they show only on a phone
function howHTML(room, g, p, k) {
  const multi = room.pieces.length > 1;
  const how = g.f.how;
  const members = p ? g.members.filter((m) => m.p === p) : g.members;
  const after = p ? statusWith(p, k, g) : roomWith(room, k, g);
  const result = g.members.some((m) => m.f.after)
    ? `<div class="result ${after}" title="${RISKS.find(([x]) => x === k)[1]}">${ICON[k]}<span class="to">→</span>${multi ? members.map(({ p: q }) => pn(q, statusWith(q, k, g))).join("") : ""}${ICON[after]}${WORD[after]}</div>` : "";
  const who = multi && !result ? `<span class="who">${badges(g.members.map((m) => m.p))}</span>` : "";
  const title = `<div class="how-head"><span class="ficon">${fixIcon(g.f)}</span><div class="hh"><b>${esc(clip(how?.label || g.title, 60))}</b>
    ${who}</div>${result}</div>`;
  if (!how) {
    return `<div class="how">${title}<p class="hl">${esc(clip(g.f.why || "", 160))}</p>
      ${g.f.after ? afterIcons(Object.fromEntries(KEYS.map((x) => [x, p ? statusWith(p, x, g) : roomWith(room, x, g)]))) : ""}</div>`;
  }
  const beside = g.act ? "on-phone" : ""; // a good habit's chip in the chat has no cost or time
  const tools = (how.tools || []).join(" · ");
  const chips = [chip(how.buy, ICON.bag, "buy"), chip(costText(how), "", beside), chip(timeText(how), ICON.clock, beside), chip(tools, ICON.wrench, "tool")].join("");
  const steps = (how.steps || []).slice(0, 4).map((s, i) => `<li><span class="sn">${i + 1}</span><span>${esc(clip(s, 140))}</span></li>`).join("");
  const line = (cls, icon, text) => (text ? `<p class="hl ${cls}" title="${esc(text)}">${icon}<span>${esc(clip(text, 240))}</span></p>` : "");
  return `<div class="how">${title}${chips ? `<div class="hchips">${chips}</div>` : ""}
    ${steps ? `<ol class="steps">${steps}</ol>` : ""}
    ${line("renter", ICON.room, how.renter)}${line("avoid", ICON.tips, how.avoid)}
    ${how.source ? `<small class="src">${esc(clip(how.source, 160))}</small>` : ""}</div>`;
}

// The chat shows what the panel shows: its room's glance row folds away, its piece's outline stands
// out, and the fix being previewed is marked
function markOpen() {
  document.querySelectorAll(".still.focusing").forEach((f) => f.classList.remove("focusing"));
  document.querySelectorAll(".still g.focus").forEach((g) => g.classList.remove("focus"));
  document.querySelectorAll(".card.open").forEach((c) => c.classList.remove("open"));
  document.querySelectorAll(":is(.trow, .habit):is(.showing, .other)").forEach((r) => {
    r.classList.remove("showing", "other");
    const label = r.querySelector(".show-btn span");
    if (label) label.textContent = "Show me";
  });
  const { room, focus: p } = pnl;
  if (!room) return;
  room.el.classList.add("open");
  const multi = room.pieces.length > 1;
  if (p && multi) {
    room.figure?.classList.add("focusing");
    p.marker?.classList.add("focus");
  }
  room.el.querySelectorAll("[data-g]").forEach((row) => {
    const g = room.groups[+row.dataset.g];
    if (g.key === pnl.variant && !g.done) {
      row.classList.add("showing");
      const label = row.querySelector(".show-btn span");
      if (label) label.textContent = "Showing";
    } else if (p && multi && !g.members.some((m) => m.p === p)) row.classList.add("other");
  });
}

// The room scene the panel shows: every piece's answers, plus the previewed fix
function sceneRequest() {
  const { room, focus: p, scenario: k } = pnl;
  const v = findVariant(room, pnl.variant);
  const members = v?.plan ? v.plans[k].members : v?.members || [];
  const answers = room.pieces.map((q) => {
    const m = members.find((x) => x.p === q && x.f.answer);
    return m && !m.f.done ? { ...q.card.answers, ...m.f.answer } : q.card.answers;
  });
  const focus = room.pieces.length > 1 && p && k !== "quake" ? p.index : null; // a quake shakes everything
  return { run: room.ev.run, answers, scenario: k, focus };
}

const OVER = /\b(tipped|fell) over\b/i;
const EVENT_S = 5; // how long an event pill stays over the viewer, in simulated seconds

// The scene's event words name items by their short names; a garbled one is said by its tidy name
function eventText(room) {
  return (text, i) => {
    let out = String(text);
    for (const it of room.pieces[i]?.card.items || []) {
      for (const said of [it.short, it.name]) {
        if (said && garbled(said) && out.includes(said)) out = out.replace(said, itemName(it).toLowerCase());
      }
    }
    return cap1(clip(out, 44));
  };
}

let sceneTimer;
function loadScene() {
  clearTimeout(sceneTimer);
  sceneTimer = setTimeout(fetchScene, 80); // a burst of taps (one fix on three pieces) runs once
}

async function fetchScene() {
  const room = pnl.room;
  if (!room) return;
  const req = sceneRequest();
  const key = JSON.stringify(req);
  const focus = room.pieces.length > 1 && pnl.focus ? pnl.focus.index : null;
  const host = pnl.host;
  const nosim = host.querySelector(".nosim");
  const judged = () => {
    const p = pnl.focus;
    const pic = p?.card.box ? `<i class="nthumb" style="${thumbStyle(p, p.card.box, 132)}"></i>` : ICON.search;
    nosim.innerHTML = `<span>${pic}<b>Judged, not simulated</b><small>From safety guidance</small></span>`;
    nosim.hidden = false;
  };
  // a judged piece isn't built, so it has nothing of its own to play; the room's scene waits underneath
  if (pnl.focus?.card.judged) {
    host.classList.remove("busy");
    return judged();
  }
  nosim.hidden = true;
  if (key === pnl.key) { // the same simulation: just look at another piece
    if (pnl.viewer && (pnl.shownFocus !== focus || pnl.shownRoom !== room)) pnl.viewer.focus(focus);
    pnl.shownFocus = focus;
    return;
  }
  pnl.key = key;
  host.classList.add("busy");
  host.querySelector(".replay").hidden = true;
  host.querySelector(".events").innerHTML = ""; // the last run's events don't linger behind the veil
  try {
    const res = await fetch("/api/scene", { method: "POST", headers: { "Content-Type": "application/json" }, body: key });
    if (!res.ok) throw new Error(`${res.status}`);
    const trace = await res.json();
    if (pnl.key !== key) return; // the user moved on while this ran
    if (!trace.frames) return judged();
    viewerModule ??= await import("./viewer.js");
    if (!pnl.viewer) {
      pnl.viewer = new viewerModule.SimViewer(host);
      pnl.viewer.onEnd = () => (host.querySelector(".replay").hidden = false);
      pnl.viewer.onTag = (i) => pnl.room && openPanel(pnl.room, { focus: pnl.room.pieces[i], scenario: pnl.scenario, variant: pnl.variant });
      // how fast a piece went over, when the viewer reports it: faster than anyone watching can step in
      pnl.viewer.onTip = (i, seconds) => {
        if (Number.isFinite(+seconds) && !pnl.tips.some((x) => x.i === i)) pnl.tips.push({ i, s: +seconds });
      };
    }
    const cap = host.querySelector(".cap"), events = host.querySelector(".events"), bar = host.querySelector(".bar i");
    const multi = room.pieces.length > 1;
    const tag = (i) => (multi && i != null && room.pieces[i] ? pn(room.pieces[i]) : "");
    const v = findVariant(room, pnl.variant);
    const timed = req.scenario !== "quake"; // a climb or a grab: how fast it went over answers "I'm watching"
    const said = eventText(room);
    let shown = "";
    pnl.tips = [];
    pnl.viewer.onFrame = (t, progress) => {
      const caption = trace.captions.filter(([at]) => at <= t).pop();
      cap.textContent = caption ? clip(caption[1], 60) : "";
      const fast = timed ? pnl.tips : [];
      // a piece's "tipped over" becomes its "Fell in 1.2 s", which stays; other events show for a few
      // seconds, so they never sit over the room; at most three pills
      const happened = trace.events.filter(([at, text, i]) => at <= t && t - at < EVENT_S && !(OVER.test(text) && fast.some((x) => x.i === i)));
      const now = `${happened.map(([at]) => at).join()}/${fast.length}`;
      if (now !== shown) {
        shown = now;
        const room_ = Math.max(0, 3 - fast.length);
        events.innerHTML = [
          ...fast.slice(0, 3).map(({ i, s }) => `<li class="fast" title="Faster than anyone watching can step in">${ICON.clock}${tag(i)}<span>Fell in ${s.toFixed(1)} s<small> · too fast to catch</small></span></li>`),
          ...happened.slice(Math.max(0, happened.length - room_)).map(([, text, i, j]) => `<li>${tag(i)}<span>${esc(said(text, i))}</span>${tag(j)}</li>`),
        ].join("");
      }
      bar.style.width = `${progress * 100}%`;
    };
    const labels = Object.fromEntries(room.pieces.map((q) => [q.index, { n: q.n, status: statusWith(q, req.scenario, v) }]));
    host.querySelector(".replay").hidden = true; // the last trace may have ended while this one loaded
    // a new room, piece or scenario is framed afresh (each scenario's people stand and climb differently)
    const reframe = pnl.shownRoom !== room || pnl.shownFocus !== focus || pnl.shownScenario !== req.scenario;
    pnl.viewer.load(trace, { labels, focus, reframe });
    pnl.shownRoom = room;
    pnl.shownFocus = focus;
    pnl.shownScenario = req.scenario;
  } catch (err) {
    host.querySelector(".cap").textContent = `Couldn't simulate: ${err.message}`;
  } finally {
    if (pnl.key === key) host.classList.remove("busy");
  }
}

function answer(p, change) {
  recheck(p, { ...p.card.answers, ...change });
}

// Rechecks run side by side (one answer for three pieces): the busy marks stay until the last is back
let rechecking = 0;
async function recheck(p, answers) {
  const room = p.room;
  room.pending = (room.pending || 0) + 1;
  rechecking++;
  room.el.classList.add("busy");
  if (pnl.room === room) panelEl.classList.add("busy");
  setStatus("Re-checking with your answer…", "busy");
  try {
    const res = await fetch("/api/assess", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ run: p.run, piece: p.index, answers }),
    });
    if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
    p.card = await res.json();
    p.record.cards[p.index] = p.card;
    renderCard(room);
    if (pnl.room === room) renderPanel();
    saveThread();
  } catch (err) {
    toast(`Couldn't re-check: ${err.message.slice(0, 100)}`);
    renderCard(room);
  } finally {
    if (--room.pending === 0) room.el.classList.remove("busy");
    if (--rechecking === 0) panelEl.classList.remove("busy");
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
    if (c.judged) return `<tr><td>${i + 1}. ${esc(c.name)}</td><td>Judged, not simulated (${esc(d.family)}): ${esc(d.judged)}</td></tr>`;
    return `<tr><td>${i + 1}. ${esc(c.name)}</td><td>${d.size_cm.join(" × ")} cm${d.depth_guessed ? " (depth guessed)" : ""},
      ~${d.mass_kg} kg empty, ${d.mass_with_clothes_kg} kg loaded, ${d.top_load_kg} kg on top, ${esc(d.material)},
      preset ${esc(d.preset)}, starts rocking at ${d.rocking_starts_g} g. Size from: ${esc(d.size_basis)}</td></tr>`;
  }).join("");
  const timing = Object.entries(ev.report.seconds || {}).map(([k, v]) => `${k} ${v.toFixed(1)} s`).join(", ");
  return `<details class="nerd"><summary>Details</summary><table>${rows}</table><div>${timing}</div>
    <pre>${esc(JSON.stringify(ev.report, null, 2))}</pre></details>`;
}

// --- saved chats ------------------------------------------------------------------------------

// Deployed, each browser sees only the chats it saved: the server keeps them under this id
const OWNER = (() => {
  try {
    return (localStorage.owner ??= crypto.randomUUID().replace(/-/g, ""));
  } catch {
    return crypto.randomUUID().replace(/-/g, ""); // storage blocked: this visit's chats only
  }
})();
const threadApi = (path = "", init = {}) =>
  fetch(`/api/threads${path}`, { ...init, headers: { ...init.headers, "X-Owner": OWNER } });

let saveTimer;
function saveThread() {
  if (!thread) return;
  const reports = thread.messages.filter((m) => m.report).map((m) => m.report);
  const cards = reports.flatMap((r) => r.cards);
  const firstText = thread.messages.find((m) => m.role === "user" && m.text)?.text;
  thread.title = cards.length ? cards.map(pieceName).join(" · ") : clip(firstText, 60) || "Room check";
  thread.thumb = reports[0]?.still || null;
  thread.status = cards.length ? worst(cards.map((c) => c.status)) : null;
  clearTimeout(saveTimer);
  const body = JSON.stringify(thread);
  saveTimer = setTimeout(() => {
    threadApi(`/${thread.id}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body })
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
    list = await (await threadApi()).json();
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
      <span class="htext"><span class="htitle">${esc(clip(t.title, 120) || "Room check")}</span>
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
document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape") return;
  if (!els.history.hidden) closeHistory();
  else closePanel();
});

async function openThread(id) {
  if (busy) return;
  let saved;
  try {
    const res = await threadApi(`/${id}`);
    if (!res.ok) throw new Error(res.status);
    saved = await res.json();
  } catch {
    return toast("Couldn't open that chat");
  }
  resetChat();
  thread = saved;
  previousId = saved.previous_response_id || null;
  showEmpty(false);
  for (const m of saved.messages) {
    if (m.role === "user") addUserMessage(m.text, m.media);
    else new BotMessage(null, m, true).restore();
  }
  closeHistory();
  summarizeStatus();
}

async function deleteThread(id) {
  await threadApi(`/${id}`, { method: "DELETE" });
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

// The reply's markdown; plain text if the CDN's marked or DOMPurify didn't load
const md = (text) => (window.marked && window.DOMPurify ? DOMPurify.sanitize(marked.parse(text)) : `<p>${esc(text)}</p>`);

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
