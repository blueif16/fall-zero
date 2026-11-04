// The room's logic, with no page in it: the statuses of a room's pieces under each scenario, its fixes and
// questions merged across pieces, and the to-do order. app.js draws what this returns; tests/web/ runs it
// under node.

export const RISKS = [["child", "Child climbs"], ["adult", "Adult leans"], ["quake", "Earthquake"]];
export const ITEM_WORD = { tv: "TV", screen: "TV" }; // only when the model gave no usable short name
export const WORD = { tips: "Tips", maybe: "Maybe", holds: "Holds" };

// Model-written labels can come back garbled (a 2,500-character "short name" of run-together words):
// a garbled one falls back to a plainer field, and every label shown is clipped to one tidy line
export const garbled = (s) => !s || String(s).length > 120 || /_|\S{24,}/.test(s);
export const clip = (s, n = 48) => {
  const t = String(s ?? "").replace(/\s+/g, " ").trim();
  if (t.length <= n) return t;
  const cut = t.slice(0, n - 1), sp = cut.lastIndexOf(" ");
  return `${(sp > n * 0.6 ? cut.slice(0, sp) : cut).trimEnd()}…`;
};
export const tidy = (n, ...tries) => clip(tries.find((s) => !garbled(s)) ?? "", n);
export const itemName = (it) => cap1(tidy(28, it.short, it.name) || ITEM_WORD[it.kind] || "Item");
export const pieceName = (c) => cap1(tidy(60, c.name) || "This piece");
export const fixTitle = (f) => tidy(60, f.title, f.how?.label) || "Fix";

export const RANK = { holds: 0, maybe: 1, tips: 2 };
export const KEYS = RISKS.map(([k]) => k);
export const worstOf = (statuses) => ["tips", "maybe", "holds"].find((s) => statuses.includes(s)) || "holds";
export const cap1 = (s) => (s ? s[0].toUpperCase() + s.slice(1) : "");

// --- who's home: which scenarios count for this home -------------------------------------------------

// What each scenario counts for, from the household's answers (catalog/household.toml): "primary",
// "later" (it counts, and is tagged "soon") or "none". A scenario no answer names counts in full.
export function weightsFor(household, catalog) {
  const w = Object.fromEntries(KEYS.map((k) => [k, "primary"]));
  for (const [question, answer] of Object.entries(household || {})) {
    Object.assign(w, catalog?.[question]?.options?.find((o) => o.key === answer)?.scenarios);
  }
  return w;
}

// The scenarios the verdicts count for this room's home (room.weights); all of them if none is marked as
// mattering, since visitors and whoever lives here next still climb and lean
export const keysFor = (room) => {
  const ks = KEYS.filter((k) => room.weights?.[k] !== "none");
  return ks.length ? ks : KEYS;
};

// A piece's verdict for this home: its worst status in the scenarios that count
export const statusOf = (p, room) => worstOf(keysFor(room).map((k) => p.card.risks[k].status));

// A fix's cost and time, from the catalog's numbers; chats saved before them kept the words
export const costText = (how) => {
  if (!how?.cost_usd) return how?.cost || "";
  const [lo, hi] = how.cost_usd;
  return hi === 0 ? "Free" : lo === hi ? `$${lo}` : `$${lo}–${hi}`;
};
export const timeText = (how) => (how?.minutes ? `${how.minutes} min` : how?.time || "");

// --- the fixes and the questions of a photo, merged across its pieces ----------------------------

// The same fix on several pieces ("Strap it to the wall") is one: by its kind when the skill names it
export const groupKey = (f) => (f.kind ? `kind:${f.kind}` : f.key.startsWith("fix_") ? f.title : `${f.key}|${f.title}`);

export function fixGroups(room) {
  const groups = new Map();
  for (const p of room.pieces) {
    for (const f of p.card.fixes) {
      const key = groupKey(f);
      if (!groups.has(key)) groups.set(key, { key, f, members: [] });
      groups.get(key).members.push({ p, f });
    }
  }
  return [...groups.values()].map((g) => {
    const acts = g.members.filter((m) => m.f.answer);
    return {
      ...g, act: acts.length > 0, done: acts.length > 0 && acts.every((m) => m.f.done),
      sim: acts.some((m) => !m.p.card.judged), // the viewer can play it
      title: groupTitle(g),
    };
  });
}

// The pieces' own short title when most of them share it ("Strap it to the wall"), else the skill's label
export function groupTitle(g) {
  const count = new Map();
  g.members.forEach((m) => count.set(fixTitle(m.f), (count.get(fixTitle(m.f)) || 0) + 1));
  const [title, n] = [...count].sort((a, b) => b[1] - a[1])[0];
  return n * 2 > g.members.length ? title : g.f.how?.label || title;
}

// What a piece's status for `k` becomes with a variant shown (a fix, or "all together"), or as it is
export function statusWith(p, k, v) {
  if (v?.was) return v.before?.[p.index]?.[k] ?? p.card.risks[k].status; // as it was before a fix was checked
  if (v?.plan) return v.plans[k].members.find((m) => m.p === p)?.f.after[k] ?? p.card.risks[k].status;
  const m = v?.members.find((x) => x.p === p && x.f.after && !x.f.done);
  return m ? m.f.after[k] : p.card.risks[k].status;
}
export const roomWith = (room, k, v) => worstOf(room.pieces.map((p) => statusWith(p, k, v)));
export const roomNow = (room) => Object.fromEntries(KEYS.map((k) => [k, roomWith(room, k, null)]));

// The to-do list: what settles the most first (for the room, then piece by piece); done ones last
export function todo(room) {
  const now = roomNow(room);
  return fixGroups(room).map((g) => {
    const ks = keysFor(room);
    const gain = ks.reduce((n, k) => n + (RANK[roomWith(room, k, g)] < RANK[now[k]]), 0);
    const lift = g.members.reduce((n, { p }) => n + ks.reduce((s, k) => s + RANK[p.card.risks[k].status] - RANK[statusWith(p, k, g)], 0), 0);
    return { ...g, gain, lift };
  }).sort((a, b) => a.done - b.done || b.act - a.act || b.gain - a.gain || b.lift - a.lift || b.members.length - a.members.length);
}

// The same question on several pieces (same words, same answers) is asked once
export function askGroups(room) {
  const groups = new Map();
  const ks = keysFor(room);
  for (const p of room.pieces) {
    for (const q of p.card.questions) {
      if (q.about && !q.about.some((k) => ks.includes(k))) continue; // about nothing this home has
      const key = q.kind === "measure" ? `${p.n}:${q.key}` : JSON.stringify([q.key, q.title, q.options]);
      if (!groups.has(key)) groups.set(key, { key, q, members: [] });
      groups.get(key).members.push(p);
    }
  }
  return [...groups.values()].sort((a, b) => b.members.length - a.members.length);
}

// Each threatened piece's fix that helps `k` most, and what the room becomes ("All together")
export function plan(room, k) {
  const members = [];
  for (const p of room.pieces) {
    if (p.card.risks[k].status === "holds" || p.card.judged) continue;
    const best = p.card.fixes.filter((f) => f.answer && !f.done && f.after).sort((a, b) => RANK[a.after[k]] - RANK[b.after[k]])[0];
    if (best && RANK[best.after[k]] < RANK[p.card.risks[k].status]) members.push({ p, f: best });
  }
  return { members, after: worstOf(room.pieces.map((p) => members.find((m) => m.p === p)?.f.after[k] ?? p.card.risks[k].status)) };
}

// The scenario a fix helps most: where its pieces' statuses drop the most (null when it changes none)
export function bestScenario(g) {
  const gain = (k) => g.members.reduce((n, { p }) => n + RANK[p.card.risks[k].status] - RANK[statusWith(p, k, g)], 0);
  const best = KEYS.reduce((a, b) => (gain(b) > gain(a) ? b : a));
  return gain(best) > 0 ? best : null;
}

// One to-do row's cost and time: its fix on every piece it's for (all of them once it's done, else the ones
// still to do). A row from a chat saved before the numbers keeps its words.
export function rowHow(g) {
  const ms = g.members.filter((m) => m.f.answer && (g.done || !m.f.done) && m.f.how?.cost_usd);
  if (!ms.length) return g.f.how;
  return {
    cost_usd: ms.reduce(([lo, hi], m) => [lo + m.f.how.cost_usd[0], hi + m.f.how.cost_usd[1]], [0, 0]),
    minutes: ms.reduce((n, m) => n + (m.f.how.minutes || 0), 0),
  };
}

// --- the plan: what to buy for the fixes still to do, and what the room becomes with them all done ------

// Every item to buy (its count per piece, times the pieces it's for), with the total cost and time of all
// the fixes not done yet, free ones included
export function shoppingList(room) {
  const items = new Map();
  let lo = 0, hi = 0, minutes = 0;
  for (const p of room.pieces) {
    for (const f of p.card.fixes) {
      if (!f.answer || f.done) continue;
      const how = f.how || {};
      if (how.cost_usd) [lo, hi] = [lo + how.cost_usd[0], hi + how.cost_usd[1]];
      minutes += how.minutes || 0;
      if (!(how.count > 0 && how.item)) continue;
      if (!items.has(how.item)) items.set(how.item, { item: how.item, qty: 0, pieces: [] });
      const it = items.get(how.item);
      it.qty += how.count;
      if (!it.pieces.includes(p.n)) it.pieces.push(p.n);
    }
  }
  return { items: [...items.values()], cost_usd: [lo, hi], minutes };
}

// With every fix done: each piece is at least as safe as its best fix makes it, scenario by scenario (two
// fixes together were never simulated, and doing both can only help)
export function planOutcome(room) {
  const best = (p, k) => p.card.fixes.filter((f) => f.answer && !f.done && f.after)
    .reduce((s, f) => (RANK[f.after[k]] < RANK[s] ? f.after[k] : s), p.card.risks[k].status);
  const hold = room.pieces.filter((p) => keysFor(room).every((k) => best(p, k) === "holds")).length;
  if (hold === room.pieces.length) return "everything here holds";
  return hold ? `${hold} of ${room.pieces.length} hold` : "";
}

// --- fixing: the stuck options of a row, and the message for whoever else has to say yes or do it -----

// "I'm stuck" offers its fix kind's options (fixes.toml `stuck`, most common first), once each however many
// pieces share it; after a failed check, the ones about it moving lead
export function stuckOptions(g, afterCheck = false) {
  const seen = new Map();
  for (const m of g.members) for (const o of m.f.how?.stuck || []) if (!seen.has(o.key)) seen.set(o.key, o);
  const all = [...seen.values()];
  return afterCheck ? [...all.filter((o) => o.moved), ...all.filter((o) => !o.moved)] : all;
}

const listed = (names) => (names.length < 2 ? names.join("") : `${names.slice(0, -1).join(", ")} and ${names.at(-1)}`);

// A hand-off's message (handoffs.toml `template`) for this fix: the room, the pieces it's for, the fix
export function handoffText(template, room, g) {
  const ms = g.members.some((m) => m.f.answer) ? g.members.filter((m) => m.f.answer) : g.members;
  return template
    .replaceAll("{room}", clip(room.ev.report.room || "room", 40))
    .replaceAll("{pieces}", listed([...new Set(ms.map((m) => pieceName(m.p.card)))]))
    .replaceAll("{fixes}", g.title);
}

// --- where the room is in the flow, and the one thing to do next ---------------------------------

// The steps of a check, in order. "find" is done once the verdicts are in; the rest follow from the cards.
export const STEPS = ["find", "sure", "plan", "fix", "check", "safe"];

// The fixes still to do that would make a piece safer, in the to-do order: yours, and the ones handed to a
// landlord or a handyman (room.handed: group key -> who)
const toDo = (room) => todo(room).filter((g) => g.act && !g.done && g.lift > 0 && !room.handed?.[g.key]);
const handedOff = (room) => todo(room).filter((g) => g.act && !g.done && g.lift > 0 && room.handed?.[g.key]);

// The fixes that count toward "n of m done": done ones that changed the physics, and the ones still to do
const counted = (room) => todo(room).filter((g) => g.act && (g.done ? g.members.some((m) => m.f.after) : g.lift > 0));

const atRisk = (room) => keysFor(room).some((k) => roomWith(room, k, null) !== "holds");

// Being sure while a question is open (assess.py asks only what could change a verdict), then the plan
// while a fix would make a piece safer, else safe. Fixing and checking are where the person has taken it.
export function stepOf(room) {
  if (!room.pieces.length) return null;
  const open = (key) => key && fixGroups(room).some((g) => g.key === key && !g.done); // not done since
  if (open(room.checking)) return "check";
  if (open(room.fixing)) return "fix";
  if (!room.skipAsks && (askGroups(room).length || room.askHome)) return "sure"; // askHome: who's home, unconfirmed
  return toDo(room).length || handedOff(room).length ? "plan" : "safe";
}

// What the room becomes with a fix done: everything holds, or how many of its pieces do
function outcome(room, g) {
  const ks = keysFor(room);
  if (ks.every((k) => roomWith(room, k, g) === "holds")) return "then everything here holds";
  const hold = room.pieces.filter((p) => ks.every((k) => statusWith(p, k, g) === "holds")).length;
  return hold ? `then ${hold} of ${room.pieces.length} hold` : "";
}
const numbers = (members) => [...new Set(members.map((m) => (m.p ?? m).n))];

// The one line the room card leads with: what to do next, never at odds with the card below it
export function nextLine(room) {
  const step = stepOf(room);
  if (step === "sure") { // the questions are right below: say how many, not which
    const asks = askGroups(room);
    const n = asks.length + (room.askHome ? 1 : 0);
    return { step, text: `Next: ${n === 1 ? "one quick answer makes" : `${n} quick answers make`} this sure`,
      pieces: numbers(asks.flatMap((a) => a.members)), key: asks[0]?.key ?? "home" };
  }
  if (step === "plan" || step === "fix" || step === "check") {
    const groups = counted(room);
    const g = (step === "plan" ? null : groups.find((x) => x.key === (room.checking || room.fixing))) || toDo(room)[0];
    if (!g) { // all that's left is with someone else
      const h = handedOff(room)[0];
      return { step, text: `Next: waiting on your ${room.handed[h.key]} · ${h.title}`, pieces: numbers(h.members), key: h.key };
    }
    const done = groups.filter((x) => x.done).length;
    const so_far = done ? `${done} of ${groups.length} done. ` : "";
    const what = step === "check" ? `check that ${fixTitle(g.f).toLowerCase()} holds` : g.title;
    const then = step === "plan" ? outcome(room, g) : "";
    const extra = then ? `, ${then}` : "";
    return { step, text: `${so_far}Next: ${what}${extra}`, pieces: numbers(g.members), key: g.key };
  }
  if (step === "safe") {
    const next = room.suggest ? `the ${room.suggest.name} (${room.suggest.why})` : "check another room";
    const text = atRisk(room)
      ? `Nothing I can test would make this safer. Ask me about it, or next: ${next}.`
      : `Everything here holds. Next: ${next}.`;
    return { step, text, pieces: [] };
  }
  return { step: null, text: "", pieces: [] };
}

// --- keeping it safe: reminders, the next room, the plan on paper ----------------------------------

// A date (YYYY-MM-DD) n months on; the 31st of a shorter month is its last day
export function addMonths(date, n) {
  const [y, m, d] = date.split("-").map(Number);
  const first = new Date(Date.UTC(y, m - 1 + n, 1));
  const last = new Date(Date.UTC(first.getUTCFullYear(), first.getUTCMonth() + 1, 0)).getUTCDate();
  return new Date(Date.UTC(first.getUTCFullYear(), first.getUTCMonth(), Math.min(d, last))).toISOString().slice(0, 10);
}

// When to look again (household.toml): the next milestone of each confirmed answer, then the strap check
// everyone gets, soonest first
export function reminders(home, catalog, today) {
  const out = [];
  if (home?.confirmed) {
    for (const [q, c] of Object.entries(catalog || {})) {
      const next = c?.options?.find((o) => o.key === home[q])?.next;
      if (next) out.push({ title: c.label ? `${c.label}: look again` : "Look again", date: addMonths(today, next.months), say: next.say });
    }
  }
  const r = catalog?.recheck;
  if (r) out.push({ title: r.title, date: addMonths(today, r.months), say: r.say });
  return out.sort((a, b) => a.date.localeCompare(b.date));
}

// RFC 5545: text escaped (\ ; , and newlines), lines folded at 75 octets, CRLF between them
const icsEscape = (t) => String(t).replace(/[\\;,]/g, (c) => `\\${c}`).replace(/\r?\n/g, "\\n");
function fold(line) {
  const bytes = new TextEncoder().encode(line);
  if (bytes.length <= 75) return line;
  const out = [];
  let cur = "", size = 0;
  for (const ch of line) {
    const n = new TextEncoder().encode(ch).length;
    if (size + n > (out.length ? 74 : 75)) { // a continuation line starts with a space
      out.push(cur);
      cur = "";
      size = 0;
    }
    cur += ch;
    size += n;
  }
  out.push(cur);
  return out.join("\r\n ");
}

// A calendar file with one all-day event per reminder, each with a reminder the morning before
export function icsText(list, stamp) {
  const lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Fall 0//Keep it safe//EN", "CALSCALE:GREGORIAN"];
  list.forEach((r, i) => {
    const day = r.date.replaceAll("-", "");
    lines.push("BEGIN:VEVENT", `UID:${day}-${i}-${stamp}@fall-zero`, `DTSTAMP:${stamp}`, `DTSTART;VALUE=DATE:${day}`,
      `SUMMARY:${icsEscape(`Fall 0: ${r.title}`)}`, `DESCRIPTION:${icsEscape(r.say)}`,
      "BEGIN:VALARM", "ACTION:DISPLAY", "TRIGGER:-PT15H", `DESCRIPTION:${icsEscape(r.title)}`, "END:VALARM", "END:VEVENT");
  });
  lines.push("END:VCALENDAR");
  return lines.map(fold).join("\r\n") + "\r\n";
}

// The room to check next (household.toml `rooms`): the first that fits this home and hasn't been checked
export function nextRoom(home, catalog, checked) {
  const names = checked.map((n) => String(n).toLowerCase());
  const fits = (r) => !r.for || Object.entries(r.for).some(([q, keys]) => home?.confirmed && keys.includes(home[q]));
  const seen = (r) => names.some((n) => r.match.some((w) => n.includes(w)));
  return (catalog?.rooms || []).find((r) => fits(r) && !seen(r)) || null;
}

const html = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

// The home's plan on paper, the written record: who's home, then each room with what it found, what's
// done and what's left (what to buy, cost, time), and one shopping list for the home
export function planHTML(recs, home, catalog, today) {
  const ks = keysFor({ weights: home?.confirmed ? weightsFor(home, catalog) : null });
  const shop = new Map();
  let lo = 0, hi = 0, minutes = 0;
  const rooms = recs.map((r) => {
    const pieces = r.breakdown.pieces.map((p) => {
      const s = worstOf(ks.map((k) => p.status[k]));
      for (const t of p.todo || []) {
        if (t.cost_usd) [lo, hi] = [lo + t.cost_usd[0], hi + t.cost_usd[1]];
        minutes += t.minutes || 0;
        if (t.count > 0 && t.item) shop.set(t.item, (shop.get(t.item) || 0) + t.count);
      }
      const todo = (p.todo || []).map((t) => `<li>${html(t.title)}${t.count > 0 ? ` — ${t.count} × ${html(t.item)}` : ""}${t.cost_usd ? `, ${costText(t)}` : ""}${t.minutes ? `, ${t.minutes} min` : ""}</li>`).join("");
      const done = (p.done || []).map((t) => `<li class="done">✓ ${html(t)}</li>`).join("");
      return `<div class="piece"><h3>${html(cap1(p.name))} <span class="${s}">${WORD[s]}</span></h3><ul>${done}${todo}</ul></div>`;
    }).join("");
    return `<section><h2>${html(cap1(r.name))}</h2><p class="when">Checked ${html(r.updated.slice(0, 10))}</p>${pieces}</section>`;
  }).join("");
  const items = [...shop].map(([item, qty]) => `<li>${qty} × ${html(item)}</li>`).join("");
  const total = { cost_usd: [lo, hi], minutes };
  return `<h1>Our home's tip-over plan</h1><p class="when">Made ${html(today)} with Fall 0 · a screening, not a certification</p>
    ${items ? `<section><h2>To buy</h2><ul>${items}</ul><p>${costText(total)} · about ${timeText(total)}</p></section>` : ""}${rooms}`;
}
