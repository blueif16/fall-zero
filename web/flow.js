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
