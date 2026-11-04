// The flow's rules (web/flow.js) on small hand-built rooms: run with `node --test tests/web/`.
import { test } from "node:test";
import assert from "node:assert/strict";
import { stepOf, nextLine } from "../../web/flow.js";

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
