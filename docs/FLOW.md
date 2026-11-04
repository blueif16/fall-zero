# Fall 0 as one flow: proposal

*Draft 2026-11-04. The research behind it is [JOURNEY.md](JOURNEY.md); the product spec is [PRD.md](PRD.md).*

## Why

Today Fall 0 is a set of good parts that all show at once:
- the photo with its outlines;
- a reply;
- one card holding questions, fixes and habits;
- three scenarios;
- piece chips and fix pills;
- the panel, with the how-to inside it;
- chat, and past checks.

Nothing says what to do next, and the reply never moves forward. In a saved chat, the reply still says
"No — they can fall… Anchor them all", while the card below it says "Everything here is stable".

The research says the parts people need are the ones we're thinnest on:
- **People stop after the checklist.** In a randomized trial of a room-by-room app, fewer than half
  of the parents who opened it finished one room.
- **Professionals keep going.** They go on to a written, costed plan, an install, a check, and a
  record kept for later.
- **The stuck points are specific.** Metal studs, a back with no holes, renting, a partner who says
  no. Nobody answers those.

Fall 0 can't hold the drill, but it can run that whole sequence for each home. One flow, from the first
photo to "checked, and here's when to look again".

## The flow

One home, one plan, five steps. Every room card shows where it is, and only that step's content leads.

| Step | The person's question | What Fall 0 does | Built today | New |
| --- | --- | --- | --- | --- |
| **1 Who's home** | — | A row of chips: child's age (crawling / climbing 1–3 / 3–6 / none), an older adult who grabs furniture, earthquake area, rent or own. Filled in from the survey's guess, so it's one tap to confirm. | The survey guesses `people` (`analyze.py:451`); the floor question | The chips; scenarios ranked and dimmed by who's home; renter options first for renters |
| **2 What can fall** | "Is everything a risk?" | Pieces worst first, and the fall played at once. Shows which pieces **hold as they are**: lower priority, nothing to buy. Asks only the questions that change a verdict ("Help me be sure"). | Outlines, verdicts, the panel opening on the worst scenario, the questions (`app.js` `stillFigure`, `askGroups`, `openPanel`) | The "holds as it is" list |
| **3 Your plan** | "Which first, and what do I buy?" | The fixes grouped the way people act: **Now, free** (move the TV and heavy things) → **This weekend** (one shopping list with total cost and time) → **Needs someone** (landlord, handyman). Each group says what the room becomes after it. | `todo()`, `fixGroups()`, `statusWith()`/`roomWith()`, and `how` from `fixes.toml` (buy, cost, time) | The grouping, the combined shopping list, "after this group" |
| **4 Fix it** | "How, on *my* wall?" | One fix at a time, step by step, with the simulation of that fix beside it. **"I'm stuck"** lists the real stuck points: metal studs, plaster or brick, no holes in the back, not against a wall, can't drill, someone said no. Each leads to an alternative or to someone who can do it. | `howHTML` (steps, avoid, renter; currently in the panel), "Show me" | The step-through; a `stuck` table per fix kind in `fixes.toml` |
| **5 Check it** | "Did it work?" | After "I did this", a ten-second physical check ("pull the top gently: it shouldn't move"). If it holds, the physics re-runs and the before and after play, with the date. If it moved, Fall 0 goes back to "I'm stuck". | `toggleDone` → `recheck` → `/api/assess`, the variant replay | A `check` per fix kind in `fixes.toml` (the range bracket already has one); "checked on" |
| **Then: keep it safe** | "Am I done?" | Next room, especially the living room. A reminder for the next milestone (from the age band), a strap check in 6 months, and "check before a new piece goes against the wall". The plan can be shared with a partner, a landlord or a handyman. | Past checks (`openHistory`) | One chat = one home; past checks becomes "My home"; `.ics` reminders; a shareable plan |

**The voice follows the step.** A "Next:" line on the room card is recomputed after every tap, for
example "2 of 3 done. Next: strap the bookcase, 15 min". It never contradicts the card. Muse Spark's
sentence stays as the opener, and follow-ups get the current step as context (`contextOf`).

### The room card, step by step

```
┌──────────────────────────────────────────────────────────────┐
│ This living room · 3 pieces          [child ✕] [adult ✓] [quake ✕] │
│ ● What can fall ─ ● Be sure ─ ◉ Your plan ─ ○ Fix ─ ○ Check  │
│ Next: strap the bookcase and the TV stand · $10–25 · 15 min  │
├──────────────────────────────────────────────────────────────┤
│ NOW, FREE                        → child still tips on 1     │
│   Move the TV remote off the stand          1 min  [Done]    │
│ THIS WEEKEND · 2 strap kits, 1 TV strap · $17–40 · 30 min    │
│   Strap it to the wall   1 2      [Show me] [Fix it]         │
│   Strap the TV           2        [Show me] [Fix it]         │
│                                  → everything holds          │
│ HOLDS AS IT IS: 3 Leaning mirror (keep play away from it)    │
└──────────────────────────────────────────────────────────────┘
```

## What stays the same (rules from earlier sessions)

- **Nobody reads text.** Each step is chips, rows and one "Next" line, never paragraphs.
- **Left = choices, right = simulation, never duplicated.**
  - The plan, the steps and the checks are choices, so they go on the left.
  - The panel keeps playing whatever is being looked at.
  - The how-to moves out of the panel body into "Fix it".
- **The room comes first.** The plan merges fixes across pieces, as `todo()` already does.
- **No hard-coded objects or prompts.**
  - Stuck points, checks and who-is-home weights are data in `skill/catalog/` (`fixes.toml`, plus one
    small table for who's home).
  - The page only draws them.
- **Screening, not certification.** "Holds as it is" says what the physics found. It isn't a promise.

## Not doing

- **Product buy links and affiliate links.** In the trial, 68,797 check-offs led to only 255 trips to
  Amazon. A clear "what to buy" line is enough.
- **Accounts or logins.** A home is a saved chat, as today.
- **A native app or AR.**
- **Checking the fix from a photo by vision.** It's unreliable, and the physical check is the stronger
  signal. Maybe later.

## Phases

### Phase 0: tonight, only if it fits before the 9 PM ET submission
Front end only, with no new model calls or pipeline changes. Timeboxed to about an hour so the demo can
still be recorded.

1. **The "Next:" line** on the room card, recomputed from the card state after every tap. This fixes the
   stale reply.
2. **One shopping line** under "Do these first": the undone fixes' `buy`, the cost range and the total
   time.
3. **A demo script that follows the flow:** what can fall → watch it fall → plan → I did this → check →
   holds. This needs no code.

### Phase 1: the five steps (about 2–3 days)
1. The step rail on the room card, with the current step derived from state:
   - questions still open → Be sure;
   - fixes not done → Your plan or Fix it;
   - everything done → Checked.
2. Who's home: the chips, prefilled from `people`, saved with the chat. Scenario order and dimming,
   renter-first `how`.
3. Plan groups (now, free / this weekend / needs someone), the shopping list, and "after this group".
4. The "Fix it" step-through, plus `stuck` and `check` for every fix kind in `fixes.toml`. Tests: every
   kind has both, and every stuck option points to a fix kind or a hand-off that exists.
5. Check it: the physical check → recheck → before and after → "checked on <date>".
6. The front page's four steps rewritten to match these five, and the clips re-recorded with
   `tools/tutorial.py`.

### Phase 2: home and coming back
1. **One chat = one home.**
   - The rail's status becomes the home's progress ("2 rooms · 4 of 5 safe").
   - Past checks becomes "My home": rooms, status, the combined plan and shopping list.
2. **Hand-offs:**
   - a shareable, printable plan (the written record);
   - a landlord request drafted from the plan (ask, explain, offer to repair, in writing);
   - a handyman work order (the photo with outlines, and what goes where).
3. **Reminders as `.ics` files:**
   - the next milestone from the age band;
   - a strap check in 6 months;
   - "after you move furniture".
4. **"Before you buy" as a second way in** (PRD P1): a listing photo and its dimensions → one piece's
   verdict and what you'll need. The recall check (PRD P1) fits in step 2.

## Decisions needed

1. **Tonight:** Phase 0, or leave the code alone and only record the demo?
2. **Who's home:** after the first photo, prefilled (recommended), or before it, the way professionals
   ask first?
3. **One chat = one home** (recommended), or a separate home object?
4. **Check it:** the physical check prompt only (recommended), or a re-photo checked by vision too?
