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
    const gain = KEYS.reduce((n, k) => n + (RANK[roomWith(room, k, g)] < RANK[now[k]]), 0);
    const lift = g.members.reduce((n, { p }) => n + KEYS.reduce((s, k) => s + RANK[p.card.risks[k].status] - RANK[statusWith(p, k, g)], 0), 0);
    return { ...g, gain, lift };
  }).sort((a, b) => a.done - b.done || b.act - a.act || b.gain - a.gain || b.lift - a.lift || b.members.length - a.members.length);
}

// The same question on several pieces (same words, same answers) is asked once
export function askGroups(room) {
  const groups = new Map();
  for (const p of room.pieces) {
    for (const q of p.card.questions) {
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
  const hold = room.pieces.filter((p) => KEYS.every((k) => best(p, k) === "holds")).length;
  if (hold === room.pieces.length) return "everything here holds";
  return hold ? `${hold} of ${room.pieces.length} hold` : "";
}

// --- where the room is in the flow, and the one thing to do next ---------------------------------

// The steps of a check, in order. "find" is done once the verdicts are in; the rest follow from the cards.
export const STEPS = ["find", "sure", "plan", "fix", "check", "safe"];

// The fixes still to do that would make a piece safer, in the to-do order
const toDo = (room) => todo(room).filter((g) => g.act && !g.done && g.lift > 0);

// The fixes that count toward "n of m done": done ones that changed the physics, and the ones still to do
const counted = (room) => todo(room).filter((g) => g.act && (g.done ? g.members.some((m) => m.f.after) : g.lift > 0));

const atRisk = (room) => Object.values(roomNow(room)).some((s) => s !== "holds");

// Being sure while a question is open (assess.py asks only what could change a verdict), then the plan
// while a fix would make a piece safer, else safe. Fixing and checking are where the person has taken it.
export function stepOf(room) {
  if (!room.pieces.length) return null;
  if (room.checking) return "check";
  if (room.fixing) return "fix";
  if (!room.skipAsks && askGroups(room).length) return "sure";
  return toDo(room).length ? "plan" : "safe";
}

// What the room becomes with a fix done: everything holds, or how many of its pieces do
function outcome(room, g) {
  if (KEYS.every((k) => roomWith(room, k, g) === "holds")) return "then everything here holds";
  const hold = room.pieces.filter((p) => KEYS.every((k) => statusWith(p, k, g) === "holds")).length;
  return hold ? `then ${hold} of ${room.pieces.length} hold` : "";
}
const numbers = (members) => [...new Set(members.map((m) => (m.p ?? m).n))];

// The one line the room card leads with: what to do next, never at odds with the card below it
export function nextLine(room) {
  const step = stepOf(room);
  if (step === "sure") { // the questions are right below: say how many, not which
    const asks = askGroups(room);
    const n = asks.length;
    return { step, text: `Next: ${n === 1 ? "one quick answer" : `${n} quick answers`} make this sure`,
      pieces: numbers(asks.flatMap((a) => a.members)), key: asks[0].key };
  }
  if (step === "plan" || step === "fix" || step === "check") {
    const groups = counted(room);
    const g = (step === "plan" ? null : groups.find((x) => x.key === (room.checking || room.fixing))) || toDo(room)[0];
    const done = groups.filter((x) => x.done).length;
    const so_far = done ? `${done} of ${groups.length} done. ` : "";
    const what = step === "check" ? `check that ${fixTitle(g.f).toLowerCase()} holds` : g.title;
    const then = step === "plan" ? outcome(room, g) : "";
    const extra = then ? `, ${then}` : "";
    return { step, text: `${so_far}Next: ${what}${extra}`, pieces: numbers(g.members), key: g.key };
  }
  if (step === "safe") {
    const text = atRisk(room)
      ? "Nothing I can test would make this safer. Ask me about it, or check another room."
      : "Everything here holds. Next: check another room.";
    return { step, text, pieces: [] };
  }
  return { step: null, text: "", pieces: [] };
}
