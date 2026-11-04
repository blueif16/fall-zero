// The flow's rules (web/flow.js) on small hand-built rooms: run with `node --test tests/web/`.
import { test } from "node:test";
import assert from "node:assert/strict";
import { stepOf, nextLine, costText, timeText, shoppingList, planOutcome, rowHow, fixGroups, handoffText, stuckOptions, statusWith, weightsFor, keysFor, statusOf } from "../../web/flow.js";

const ALL = (s) => ({ child: s, adult: s, quake: s });
const risks = (r) => Object.fromEntries(Object.entries(r).map(([k, status]) => [k, { status, says: "" }]));
const strap = (after, done = false) => ({
  key: "anchor", kind: "strap", title: "Strap it to the wall", answer: { anchored: "yes" }, done, after,
  how: { cost: "$10–25", time: "15 min" },
});
const move = { key: "moved", kind: "moved", title: "Move heavy things lower", answer: { moved: [0] }, done: false, after: null,
  how: { cost: "Free", time: "5 min" } };
const floorQ = { key: "floor", title: "Which floor is this room on?", options: [{ label: "Ground", value: "ground" }] };
const card = ({ now = ALL("tips"), fixes = [], questions = [], name = "Tall dresser" } = {}) => ({
  name, status: ["tips", "maybe", "holds"].find((s) => Object.values(now).includes(s)), headline: "",
  risks: risks(now), fixes, questions, answers: {}, items: [],
});
const room = (...cards) => ({ ev: { report: {} }, pieces: cards.map((c, i) => ({ card: c, index: i, n: i + 1 })) });

test("a room with an open question is at 'be sure'", () => {
  assert.equal(stepOf(room(card({ fixes: [strap(ALL("holds"))], questions: [floorQ] }))), "sure");
});

test("skipping the questions moves a room with a fix to do on to the plan", () => {
  const r = room(card({ fixes: [strap(ALL("holds"))], questions: [floorQ] }));
  r.skipAsks = true;
  assert.equal(stepOf(r), "plan");
});

test("a room that can tip, with a fix not done, is at the plan", () => {
  assert.equal(stepOf(room(card({ fixes: [strap(ALL("holds"))] }))), "plan");
});

test("a room whose fixes are done and that holds everywhere is safe", () => {
  assert.equal(stepOf(room(card({ now: ALL("holds"), fixes: [strap(ALL("holds"), true)] }))), "safe");
});

test("a room that holds with only optional fixes left is safe", () => {
  assert.equal(stepOf(room(card({ now: ALL("holds"), fixes: [strap(ALL("holds"), true), move] }))), "safe");
});

test("a fix being done is the fix step, and one waiting for its check is the check step", () => {
  const r = room(card({ fixes: [strap(ALL("holds"))] }));
  r.fixing = "kind:strap";
  assert.equal(stepOf(r), "fix");
  r.checking = "kind:strap";
  assert.equal(stepOf(r), "check");
});

test("at the plan, next names the fix that settles most, and the pieces it covers", () => {
  const r = room(card({ fixes: [move, strap(ALL("holds"))] }), card({ name: "Bookcase", fixes: [strap(ALL("holds"))] }));
  const next = nextLine(r);
  assert.match(next.text, /Strap it to the wall/);
  assert.deepEqual(next.pieces, [1, 2]);
  assert.equal(next.step, "plan");
});

test("at the plan, next counts the needed fixes done so far", () => {
  const half = room(
    card({ now: ALL("holds"), fixes: [strap(ALL("holds"), true)] }),
    card({ name: "Bookcase", fixes: [{ ...strap(ALL("holds")), kind: "tv_strap", title: "Strap the TV" }] }),
  );
  assert.match(nextLine(half).text, /1 of 2 done/);
});

test("at 'be sure', next counts the questions left without repeating one (the card shows them)", () => {
  const anchoredQ = { key: "anchored", title: "Is it already strapped to the wall?", options: [{ label: "Yes", value: "yes" }] };
  const next = nextLine(room(card({ fixes: [strap(ALL("holds"))], questions: [floorQ, anchoredQ] })));
  assert.equal(next.step, "sure");
  assert.match(next.text, /2 quick answers/);
  assert.doesNotMatch(next.text, /Which floor|strapped/);
});

test("a safe room's next says it holds and points at another room", () => {
  const next = nextLine(room(card({ now: ALL("holds"), fixes: [strap(ALL("holds"), true)] })));
  assert.equal(next.step, "safe");
  assert.match(next.text, /holds/i);
  assert.match(next.text, /another room/i);
});

test("a room that holds but still has a question is at 'be sure' (assess.py asks only what can change a verdict)", () => {
  const drawersQ = { key: "drawers", title: "What's in the drawers?", options: [{ label: "Full", value: "full" }] };
  assert.equal(stepOf(room(card({ now: ALL("holds"), questions: [drawersQ] }))), "sure");
});

test("a room nothing more can fix, still at risk, says so instead of claiming it holds", () => {
  const next = nextLine(room(card({ now: ALL("maybe"), fixes: [move] })));
  assert.equal(next.step, "safe");
  assert.doesNotMatch(next.text, /holds/i);
});

test("with two helpful fixes, next names the one that makes the room safest", () => {
  const locks = { key: "locks", kind: "locks", title: "Drawer locks", answer: { locks: true }, done: false,
    after: { child: "holds", adult: "tips", quake: "tips" }, how: { cost: "$10–20", time: "20 min" } };
  const next = nextLine(room(card({ fixes: [locks, strap(ALL("holds"))] })));
  assert.match(next.text, /Strap it to the wall/);
  assert.doesNotMatch(next.text, /Drawer locks/);
});

test("at the plan, next says what the room becomes after that fix, not its cost (the row shows that)", () => {
  const next = nextLine(room(card({ fixes: [strap(ALL("holds"))] }), card({ name: "Bookcase", fixes: [strap(ALL("holds"))] })));
  assert.match(next.text, /then everything here holds/);
  assert.doesNotMatch(next.text, /\$|min/);
});

test("when one fix leaves part of the room at risk, next says how many pieces it makes hold", () => {
  const partly = { ...strap(ALL("holds")), kind: "tv_strap", title: "Strap the TV" };
  const next = nextLine(room(card({ fixes: [partly] }), card({ name: "Bookcase", fixes: [] })));
  assert.match(next.text, /then 1 of 2 hold/);
  assert.doesNotMatch(next.text, /everything/);
});

test("a fix that settles only one scenario claims neither the room nor a piece holds", () => {
  const locks = { key: "locks", kind: "locks", title: "Drawer locks", answer: { locks: true }, done: false,
    after: { child: "holds", adult: "tips", quake: "tips" }, how: {} };
  const next = nextLine(room(card({ fixes: [locks] })));
  assert.match(next.text, /Drawer locks/);
  assert.doesNotMatch(next.text, /hold/);
});

test("cost and time read from the catalog's numbers", () => {
  assert.equal(costText({ cost_usd: [10, 25] }), "$10–25");
  assert.equal(costText({ cost_usd: [0, 0] }), "Free");
  assert.equal(costText({ cost_usd: [15, 15] }), "$15");
  assert.equal(timeText({ minutes: 15 }), "15 min");
});

test("a chat saved before the numbers keeps its cost and time words", () => {
  assert.equal(costText({ cost: "$10–20 a set" }), "$10–20 a set");
  assert.equal(timeText({ time: "20 min" }), "20 min");
  assert.equal(costText(undefined), "");
});

// fixes as they come from the catalog now: numbers for the shopping list
const strapN = (after, done = false) => ({ ...strap(after, done),
  how: { item: "Anti-tip straps, metal or nylon", count: 2, cost_usd: [10, 25], minutes: 15 } });
const tvN = (after) => ({ key: "tv", kind: "tv_strap", title: "Strap the TV", answer: { tv: true }, done: false, after,
  how: { item: "TV anti-tip strap kit", count: 1, cost_usd: [10, 20], minutes: 15 } });
const moveN = { ...move, how: { item: "", count: 0, cost_usd: [0, 0], minutes: 5 } };

test("the shopping list merges one item across pieces: its count per piece times the pieces", () => {
  const list = shoppingList(room(card({ fixes: [strapN(ALL("holds"))] }), card({ name: "Bookcase", fixes: [strapN(ALL("holds"))] })));
  assert.deepEqual(list.items, [{ item: "Anti-tip straps, metal or nylon", qty: 4, pieces: [1, 2] }]);
});

test("the shopping list totals the cost and time of every fix still to do, free ones included", () => {
  const list = shoppingList(room(card({ fixes: [strapN(ALL("holds")), moveN, tvN(ALL("holds"))] })));
  assert.deepEqual(list.cost_usd, [20, 45]);
  assert.equal(list.minutes, 35);
  assert.equal(list.items.length, 2);
});

test("the shopping list leaves out what's done", () => {
  const list = shoppingList(room(card({ now: ALL("holds"), fixes: [strapN(ALL("holds"), true)] }), card({ name: "TV", fixes: [tvN(ALL("holds"))] })));
  assert.deepEqual(list.items.map((x) => x.item), ["TV anti-tip strap kit"]);
  assert.deepEqual(list.cost_usd, [10, 20]);
});

test("with every fix done, the room holds if each piece's best fix holds it", () => {
  assert.equal(planOutcome(room(card({ fixes: [strapN(ALL("holds")), moveN] }), card({ name: "TV", fixes: [tvN(ALL("holds"))] }))),
    "everything here holds");
});

test("two fixes on one piece count as at least the better of the two, per scenario", () => {
  const childOnly = { ...tvN({ child: "holds", adult: "tips", quake: "tips" }), kind: "locks", key: "locks" };
  const quakeOnly = { ...tvN({ child: "tips", adult: "holds", quake: "holds" }), kind: "latches", key: "latches" };
  assert.equal(planOutcome(room(card({ fixes: [childOnly, quakeOnly] }))), "everything here holds");
  assert.equal(planOutcome(room(card({ fixes: [childOnly] }))), "");
});

test("when the plan can't make every piece hold, it says how many it does", () => {
  assert.equal(planOutcome(room(card({ fixes: [strapN(ALL("holds"))] }), card({ name: "Lamp", now: ALL("maybe"), fixes: [moveN] }))),
    "1 of 2 hold");
});

test("a to-do row's cost and time cover every piece it's for, so the rows add up to the shopping line", () => {
  const r = room(card({ fixes: [strapN(ALL("holds")), moveN] }), card({ name: "Bookcase", fixes: [strapN(ALL("holds"))] }));
  const rows = fixGroups(r).map(rowHow);
  assert.deepEqual(rows.map((h) => h.cost_usd), [[20, 50], [0, 0]]);
  assert.deepEqual(rows.map((h) => h.minutes), [30, 5]);
  const list = shoppingList(r);
  assert.equal(rows.reduce((n, h) => n + h.minutes, 0), list.minutes);
});

test("a row from a chat saved before the numbers shows its words as they were", () => {
  const old = { ...strap(ALL("holds")), how: { cost: "$10–25", time: "15 min" } };
  const h = rowHow(fixGroups(room(card({ fixes: [old] }), card({ name: "B", fixes: [old] })))[0]);
  assert.equal(costText(h), "$10–25");
  assert.equal(timeText(h), "15 min");
});

test("a room isn't left fixing or checking a fix that's already done, or no longer there", () => {
  const r = room(card({ now: ALL("holds"), fixes: [strapN(ALL("holds"), true)] }));
  r.fixing = "kind:strap";
  assert.equal(stepOf(r), "safe");
  r.fixing = null;
  r.checking = "kind:gone";
  assert.equal(stepOf(r), "safe");
});

test("a hand-off message is filled with the room, the pieces and the fix, and nothing left to fill", () => {
  const r = room(card({ name: "tall white bookcase", fixes: [strapN(ALL("holds"))] }), card({ name: "TV stand", fixes: [strapN(ALL("holds"))] }));
  r.ev.report.room = "living room";
  const g = fixGroups(r)[0];
  const text = handoffText("Hi, in the {room}: {pieces}. The fix: {fixes}.", r, g);
  assert.equal(text, "Hi, in the living room: Tall white bookcase and TV stand. The fix: Strap it to the wall.");
});

test("a row's stuck options are its fix kind's, once each, even when several pieces share it", () => {
  const stuck = [{ key: "metal_studs", label: "Metal studs", say: "Use toggles", then: "" }, { key: "renting", label: "I rent", say: "Ask", then: "landlord" }];
  const f = { ...strapN(ALL("holds")), how: { ...strapN(ALL("holds")).how, stuck } };
  const g = fixGroups(room(card({ fixes: [f] }), card({ name: "B", fixes: [f] })))[0];
  assert.deepEqual(stuckOptions(g).map((o) => o.key), ["metal_studs", "renting"]);
  assert.deepEqual(stuckOptions(fixGroups(room(card({ fixes: [moveN] })))[0]), []);
});

test("a fix handed to someone else isn't next; what's left to do yourself is", () => {
  const locks = { key: "locks", kind: "locks", title: "Drawer locks", answer: { locks: true }, done: false,
    after: { child: "holds", adult: "tips", quake: "tips" }, how: {} };
  const r = room(card({ fixes: [strapN(ALL("holds")), locks] }));
  r.handed = { "kind:strap": "landlord" };
  assert.match(nextLine(r).text, /Drawer locks/);
});

test("with only handed-off fixes left, the room is waiting on them, and says who", () => {
  const r = room(card({ fixes: [strapN(ALL("holds"))] }));
  r.handed = { "kind:strap": "landlord" };
  const next = nextLine(r);
  assert.equal(next.step, "plan");
  assert.match(next.text, /landlord/);
  assert.match(next.text, /Strap it to the wall/);
});

test("'before' shows each piece as it was saved just before the fix was checked", () => {
  const r = room(card({ now: ALL("holds"), fixes: [strapN(ALL("holds"), true)] }));
  const g = fixGroups(r)[0];
  const was = { key: `was:${g.key}`, was: true, before: { 0: { child: "tips", adult: "maybe", quake: "tips" } } };
  assert.equal(statusWith(r.pieces[0], "adult", was), "maybe");
  assert.equal(statusWith(r.pieces[0], "adult", null), "holds");
});

test("after a failed check, the stuck options about it moving come first", () => {
  const stuck = [{ key: "renting", label: "I rent", say: "", then: "" }, { key: "wont_stay", label: "It still moves", say: "", then: "", moved: true }];
  const g = fixGroups(room(card({ fixes: [{ ...strapN(ALL("holds")), how: { stuck } }] })))[0];
  assert.deepEqual(stuckOptions(g).map((o) => o.key), ["renting", "wont_stay"]);
  assert.deepEqual(stuckOptions(g, true).map((o) => o.key), ["wont_stay", "renting"]);
});

// --- who's home -----------------------------------------------------------------------------------
const HOUSEHOLD = {
  child: { options: [{ key: "crawling", scenarios: { child: "later" } }, { key: "climbing", scenarios: { child: "primary" } }, { key: "none", scenarios: { child: "none" } }] },
  older: { options: [{ key: "lives_here", scenarios: { adult: "primary" } }, { key: "no", scenarios: { adult: "none" } }] },
  quake: { options: [{ key: "yes", scenarios: { quake: "primary" } }, { key: "no", scenarios: { quake: "none" } }] },
  rent: { options: [{ key: "rent", renter: true }] },
};

test("who's home decides what each scenario counts for; what isn't answered counts in full", () => {
  assert.deepEqual(weightsFor({ child: "crawling", older: "no" }, HOUSEHOLD), { child: "later", adult: "none", quake: "primary" });
  assert.deepEqual(weightsFor({}, HOUSEHOLD), { child: "primary", adult: "primary", quake: "primary" });
});

test("a scenario that isn't for this home leaves the verdicts; 'later' still counts", () => {
  const r = room(card({ now: { child: "holds", adult: "holds", quake: "tips" } }));
  r.weights = { child: "later", adult: "primary", quake: "none" };
  assert.deepEqual(keysFor(r), ["child", "adult"]);
  assert.equal(statusOf(r.pieces[0], r), "holds");
  r.weights = { child: "later", adult: "primary", quake: "primary" };
  assert.equal(statusOf(r.pieces[0], r), "tips");
});

test("if nothing is marked as mattering, every scenario still counts (visitors, the next owner)", () => {
  const r = room(card({ now: { child: "tips", adult: "holds", quake: "holds" } }));
  r.weights = { child: "none", adult: "none", quake: "none" };
  assert.deepEqual(keysFor(r), ["child", "adult", "quake"]);
});

test("a fix that only helps a scenario this home doesn't have isn't on the plan, and the room is safe", () => {
  const latch = { key: "latches", kind: "latches", title: "Latches", answer: { latches: true }, done: false,
    after: { child: "holds", adult: "holds", quake: "holds" }, how: {} };
  const r = room(card({ now: { child: "holds", adult: "holds", quake: "tips" }, fixes: [latch] }));
  r.weights = { child: "primary", adult: "primary", quake: "none" };
  assert.equal(stepOf(r), "safe");
  assert.match(nextLine(r).text, /Everything here holds/);
});

test("who's home not confirmed yet is one more thing to be sure of", () => {
  const r = room(card({ fixes: [strapN(ALL("holds"))] }));
  r.askHome = true;
  assert.equal(stepOf(r), "sure");
  assert.match(nextLine(r).text, /one quick answer/);
  r.askHome = false;
  assert.equal(stepOf(r), "plan");
});
