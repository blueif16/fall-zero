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
| **Then: keep it safe** | "Am I done?" | Next room, especially the living room. A reminder for the next milestone (from the age band), a strap check in 6 months, and "check before a new piece goes against the wall". The plan can be shared with a partner, a landlord or a handyman. | Past checks (`openHistory`) | The room library (Fall 0's memory: a known room is recognized and updated); "My home"; `.ics` reminders; a shareable plan |

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
- **Accounts or logins.** The home is kept per browser, like saved chats today.
- **A native app or AR.**
- **Checking the fix from a photo by vision.** It's unreliable, and the physical check is the stronger
  signal. Maybe later.

## Decided (2026-11-04)

- **Build the whole design**, not a slice for the deadline. The goal is set first, then every step
  below is built and checked in order.
- **Who's home is asked after the first photo**, prefilled from the survey's guess.
- **The home is a room library, and it is Fall 0's memory.**
  - Every analyzed room is kept: its photo, its pieces and their outlines, the answers, and what was
    done and checked, with dates. The person can remove a room.
  - A new photo, even in a new chat, is matched against the library. A known room is updated rather
    than started over: "Your living room again: the bookcase you strapped on Nov 2 still holds". This is
    how Fall 0 shows it understands the home's layout.
- **Check it is a physical check prompt.** No re-photo by vision.

## Goal

For any home, Fall 0 runs the whole tip-over job as one flow: who's home → what can fall → your plan →
fix it → check it → keep it safe. It remembers every room it has seen, so a new photo of a known room
updates that room instead of starting over.

## Build plan

Each step is merged only when its "done when" holds and has been checked: tests, or a screenshot of the
running app. Steps 4a and 6a–6c can run in parallel with the front-end steps.

### S1. The flow's logic, pure and tested (`web/flow.js`)
- **1a.** Move the room logic out of `app.js` into `web/flow.js`, a module with no DOM. `app.js`
  imports it, and nothing changes on screen. The functions: `worstOf`, `statusWith`, `roomWith`,
  `roomNow`, `fixGroups`, `todo`, `askGroups`, `plan`, `bestScenario`.
- **1b.** `stepOf(room)`: the room's current step (what can fall / be sure / plan / fix / check /
  safe).
- **1c.** `nextLine(room)`: the one "Next:" sentence and what it points at.
- **1d.** `node --test tests/web/`, with fixtures taken from a real saved report.
- **Done when:** the tests pass, and each fails if the rule it covers is broken.

### S2. The step rail and the "Next:" line on the room card
- **2a.** A rail: What can fall · Be sure · Plan · Fix · Check. The current step is marked and done
  steps are ticked. Tapping a step that's done or open goes to it.
- **2b.** The "Next:" line is recomputed on every render. Muse Spark's sentence stays above as the
  opener.
- **2c.** The current step's content leads, and the rest folds away.
- **Done when:** in the replayed living-room chat, nothing on the card contradicts the rail or the
  "Next:" line, checked with a screenshot of each step.

### S3. Your plan
- **3a.** `fixes.toml` gets numbers instead of display strings: `cost_usd = [lo, hi]`, `minutes`, and
  `buy` with a count per piece. The page formats them. `assess.how` and the chips are updated.
- **3b.** `planGroups(room)`: Now, free → This weekend → Needs someone. Each group says what the room
  becomes once it and the groups before it are done.
- **3c.** `shoppingList(room)`: items merged with counts, plus the total cost range and total time.
- **Done when:** on the living-room sample, the "This weekend" line adds up to its rows, and the tests
  cover the merging.

### S4. Fix it and Check it
- **4a. Content, in `fixes.toml`**, sourced from JOURNEY.md and RESEARCH.md:
  - for every fix kind with steps, a `check` (the question, plus what "holds" and "it moved" mean);
  - a `stuck` list: metal studs, plaster/brick/concrete, no holes in the back, not against a wall,
    can't drill or renting, someone said no;
  - each stuck option gives an answer and a `then`: another fix kind, `landlord`, or `handyman`.
- **4b. Tests:** every anchoring kind has a check and at least four stuck options, and every `then`
  points at something that exists.
- **4c. Fix it, in the card:**
  - one step at a time, with Back and Next;
  - "I'm stuck" opens the list from 4a;
  - the panel plays that fix;
  - the last step leads to Check it.
- **4d. Check it:**
  - **Holds:** done → physics re-run → the panel plays before, then after. The fix records "checked
    on <date>", in the chat and in the library.
  - **It moved:** back to "I'm stuck".
- **4e. Hand-offs:**
  - a landlord message to copy, filled with the pieces and the fix;
  - a printable handyman work order: the photo with outlines, and what goes where.
- **Done when:**
  - on the nursery sample, plan → fix → check → holds works, with before and after in the panel;
  - "I'm stuck → I rent" leads to the landlord message.

### S5. Who's home
- **5a.** The survey also returns a structured guess at the household: the child's age band and an
  older adult. The earthquake area and renting can't be seen, so they start as unknown. The Survey
  section of `SKILL.md` asks for it.
- **5b.** `catalog/household.toml`: what each answer changes.
  - Each scenario is marked primary, later ("soon" for a crawler) or not for this home.
  - The next milestone and when it comes.
  - Renting puts renter options first.
- **5c.** A row of chips on the first room card, prefilled, one tap to confirm. Saved for the whole
  home.
- **5d.** The effects:
  - The headline, the glance row and the panel tabs follow what matters for this home.
  - A scenario that doesn't apply is dimmed, never hidden.
  - Renters see the renter option first, and landlord hand-offs.
- **Done when:** changing a chip re-ranks the card without running the physics again, and `flow.js` tests
  cover it.

### S6. The room library: Fall 0's memory of the home
- **6a. Storage:**
  - `homes/<owner>/home.json` holds the household;
  - `homes/<owner>/rooms/<id>.json` holds each room: its name, still, size, pieces (with stable ids,
    names, families and outlines), the answers per piece, done and checked dates, and every check of
    it;
  - the API gets the home, saves the household, and removes a room;
  - tests in `test_store.py` / `test_server`.
- **6b. Saving, with a breakdown:**
  - Every analyzed photo goes into the library, as a new room or an update.
  - After every simulation (a new photo, an answer, a fix done or checked), the room's **breakdown** is
    rewritten. It is a short record of what was found, per piece:
    - the verdict per scenario and why;
    - what would fall from it;
    - where it stands;
    - the fixes done and checked, with dates;
    - the questions still open.
  - Each check also keeps a dated snapshot of the breakdown, so the room has a history.
- **6c. Recognizing:**
  - When the library has rooms, Muse Spark gets the new still and the rooms' thumbnails and returns
    the matching room (or none) and which piece is which. The prompt goes in a "Match" section of
    `SKILL.md`. It runs alongside SAM and the describe step.
  - The matched pieces' answers are carried over before the cards are built.
  - The report says which room it is, since when, and what was carried over.
  - **Bring it up:** a known room opens with what Fall 0 found last time ("Nov 2: the bookcase could
    tip on a climbing child; you strapped it").
  - **What changed:** the new findings are compared with the breakdown:
    - pieces that are new, gone or moved, and things added to or taken off them;
    - verdicts that got better or worse;
    - fixes still in place.
  - The advice leads with the changes ("The TV stand moved next to the bookcase: in a quake the
    bookcase now knocks into it"). Muse Spark's opener gets the breakdown and the changes as context.
- **6d. "My home" (past checks becomes this):**
  - each room with its thumbnail, status, progress and when it was last checked, and Remove;
  - a known room's card says "Your living room again · checked Nov 2 · 1 strapped".
- **6e. One plan for the home:** S3 across every room, with one shopping list.
- **Done when:**
  - the living-room sample sent again in a new chat is recognized, and its strapped bookcase arrives as
    "holds";
  - a copy of that photo with one piece cropped out is recognized as the same room, and the piece is
    reported as gone;
  - after the room is removed, the next send is new again.

### S7. Keep it safe
- **7a. Reminders:** `.ics` files made in the browser for the next milestone (from the household), a
  strap check in 6 months, and "after you move furniture". The wording comes from `household.toml`.
- **7b. The plan, printed or shared:** a print layout for the home plan, as the written record.
- **7c. The next room:** when a room is done, Fall 0 suggests the next one to check, from who's home
  (bedrooms and the living room for a child).

### S8. Wrap-up
- **8a.** The front page's steps match the flow, and the clips are re-recorded with `tools/tutorial.py`.
- **8b.** README, HANDOFF and PRD updated. `pytest`, `node --test` and `ruff` pass. Deploy to Vercel
  and check the live site end to end.
