# Handoff: where Fall 0 stands (2026-11-04, fifth session)

Meta Global AI Developer Hackathon. Building period Oct 27 – Nov 4, 2026. **Submission due Wed Nov 4,
9:00 PM ET**, with a 3-minute demo video. The repo must be public, and the demo may show only work built
during the event. The product spec is [PRD.md](PRD.md); [../README.md](../README.md) covers setup, commands and the model map.

## Session 5 in short (2026-11-04, read this first)

The user's ask: the app felt scattered. Make it one flow that runs the whole job for a home, step by step,
from finding the problem to solving it. [JOURNEY.md](JOURNEY.md) is the research: the step where people
stall is between deciding and doing, and between doing and knowing it worked. [FLOW.md](FLOW.md) is the
design and its build plan, S1–S8. Each step has a "done when", and each was merged into `skill-and-zones`
once it was met.

What the user decided:
- Build the whole design, not a slice cut for the deadline.
- Who's home is asked after the photo, prefilled from it.
- The home is a **room library that is Fall 0's memory**: every check is kept with a breakdown of what it
  found, and a new photo of a known room is recognized and compared with that breakdown.
- Check it is a physical check prompt.

What's built:
- **`web/flow.js`:** the room's logic with no page in it. It covers the step, "Next:", the plan's shopping
  line and outcome, stuck options, hand-off messages, who's-home weights, reminders, the next room and the
  printed plan. Tests: `node --test "tests/web/*.test.mjs"` (45); each rule was checked by breaking it.
- **The card:**
  - a track (What can fall · Be sure · Plan · Fix · Check) and one "Next:" line;
  - "Who's home?" at the top of Be sure;
  - Fix it, with "I'm stuck", landlord and handyman messages, and "Needs someone";
  - Check it, which re-runs the physics, then the panel plays the room before and after;
  - Keep it safe: Remind me (`.ics`) and Print the plan.
- **The catalogs:**
  - `fixes.toml` gives each kind `item/count/cost_usd/minutes`, a `check`, and `stuck` options, listed by
    how often each stops people (Consumer Reports surveys);
  - `handoffs.toml` holds the landlord and handyman messages;
  - `household.toml` holds the chips, what each answer does to a scenario, the reminders and the rooms to
    check next.
- **`library.py`:**
  - each room is a record: stable piece ids, answers, the breakdown, and a snapshot per check;
  - `match_pieces` pairs pieces by kind and place, `carry` brings over what's still true, `changes` says
    what changed;
  - the turn runs Muse Spark's room match (SKILL.md "Match") alongside the pipeline. Live eval: 5/5.
- **Checked end to end in Chrome:**
  1. A strapped living room was sent again in a new chat and came back strapped.
  2. The card said "Still in place" for both straps, and with the mirror cropped out, "Gone: the mirror".
  3. The opener started from what changed.

Gotchas from this session:
- The dev server reloads on `.py` changes, not on `skill/catalog/*.toml`. Restart it after a catalog edit.
- Port 8012 is taken by another session's server. This session's test server ran on 8023.
- Another session owns the front page step cards and `tools/tutorial.py` (see CLAUDE.md). The "fix" clip
  presses "I did this", which a fix with steps no longer has. They've been told the new path.
- On macOS, run pytest as `MUJOCO_GL=cgl uv run pytest`.

Next:
1. **Deployed** 2026-11-04, 7 PM ET (d827a54), and checked live end to end: a check, Fix it → Check it, then
   the same room recognized in a new chat from the Blob-stored library.
2. Re-record the how-to clips (the step-cards session).
3. Watch the first real re-checks: things on a piece are matched by name, by place, or by a shared word.
4. FLOW.md's "Not doing" still stands.

## Session 4 in short

The user's feedback this session drove the work:
- "Simulate everything segmentation finds."
- "We need 3D characters, not red boxes."
- "Contents change the mass."
- "Never show the same content on the left and the right."
- "Research what people fear and what actually helps."

[RESEARCH.md](RESEARCH.md) has the findings and sources. The advice lives in
`skill/catalog/fixes.toml`. The work was split across parallel agents by file, then checked
together. Details are under "Session 4's changes" below. The session-3 description that follows is
still accurate except where session 4 says otherwise.

## Deployed on Vercel (2026-10-28)

https://fall-zero.vercel.app runs the current working tree (sessions 3–4 plus the deploy changes, all
uncommitted). It was checked end to end on the live site:
- The living-room sample was analyzed in 80 s.
- The panel's three simulations loaded.
- "Strap it" turned the piece to "holds".
- The saved chat reopened.
- No console errors.

README "Deploying" covers the commands, the one key (`MODEL_API_KEY`, a Vercel Secret) and what differs
there. The code changes were:
- `store.py`: uploads and chats in Blob storage when deployed.
- Earthquakes run serially there.
- `MUJOCO_GL=disable` there.
- The page shrinks photos, picks a video's frame and records WAV.
- Saved chats are listed per browser.
- The dev playgrounds are off.

## What works now

You send a photo or video of **any room** in the chat at http://localhost:8011 (`uv run fall-zero serve`).
Cards arrive in about 14–17 s for a one-piece room, and about 30 s for a kitchen with three pieces.

- **The pipeline:**
  1. **Survey** (Muse Spark, reading `skill/SKILL.md` "Survey" plus `references/rooms.md`). It lists
     everything that could tip, with each piece's family, whether the engine can build it (`case`) or
     must judge it, which references it needs, what stands on it, the room type and who lives there.
  2. **SAM 3.1** outlines every piece and item while Muse Spark reads each piece in parallel:
     - **Describe:** case pieces get the "Describe" section, the piece's references and the catalogs.
       Muse Spark returns zones from the floor up (drawers, side- or bottom-hinged doors, open shelves),
       contents and fill, material, a known weight if any, the runners, the items on top, and the
       anchoring fix to offer.
     - **Judge:** everything else gets the "Judge" section. Muse Spark returns statuses, fixes with
       their after-statuses, and a question with per-option outcomes.
  3. **Engine:** the closest worked example is changed to what the photo shows, the panels are scaled
     to a known weight, and statics and the child tests run over 300 plausible sizes.
  4. **MuJoCo** shakes each variant in 3 simulated earthquakes: as is, strapped, with drawer
     interlocks, and with the hard things moved.
- **Covered so far:** dressers, chests, wardrobes, bookcases, cube shelves, TV and media units,
  hutches, display cabinets, filing cabinets, tool chests, steel shelving and ranges, as 20 worked
  examples. Mirrors, lamps, safes, coat racks and stacked washers are judged.
- **Room first (the user's rule):** people judge the setup as a whole, not object by object. A photo
  with two or more pieces gets one room card in the chat:
  - the worst status for each risk across the pieces, with the numbers of the pieces behind it;
  - "Do these first": fixes merged across pieces, each with the whole room's state afterwards, and
    "I did this" applies it to every piece it covers;
  - the floor question, asked once;
  - piece chips.

  A one-piece photo gets its piece card in the chat (no viewer there any more). The agent's reply
  speaks about the room (`agent._room` gives it the worst status per risk and the shared fixes).
- **The panel (session 3, the user's rule: details never scroll the chat):** a large panel slides in
  from the right, like the claude.ai artifact panel, and the chat narrows to the left. It opens:
  - by itself on a new photo (wide screens only), on the room's worst scenario;
  - from a risk tile (that scenario), a numbered outline or a chip (that piece), or a fix's "Show me"
    (that fix previewed).

  It has three scenario tabs, one big 3D viewer and a body below:
  - **Room view:** "Stop it first" ranks the fixes for the chosen scenario across the room. Each card
    shows its pieces turning green or not. "All together" plays the room with each threatened piece's
    best fix done.
  - **Piece view:** the camera flies to the piece and the rest fade. The body holds its items on top,
    fixes (sorted for the scenario) and questions. "Room" goes back.
  - Over the viewer: numbered 3D tags (tap one to open that piece), event pills ("1 fell over",
    "1 knocked into 2"), and pills for the fixes to preview.
  - Esc or × closes it. Phone width: full screen, pills in one scrolling row.
  - All of this lives in the page (`openPanel`, `renderPanel`, `prevent`, `plan` in `web/app.js`).
- **Whole-room simulation (session 3, the user's rule: "the full simulation with everything"):**
  `room.scene` places every piece as the photo shows it and runs one MuJoCo model:
  - Order and spacing come from the outlines, at the pieces' own m/px. Backs sit against one shared
    wall. Judged pieces are translucent ghosts sized from their outline.
  - **Earthquake:** one shake for all pieces, on the seed where most pieces do what they do in most of
    their cached runs.
  - **Child and adult:** in the room view every piece is loaded at once; in a piece view only that
    piece.
  - Contacts between pieces become "knocked into" events. In the living-room sample, the bookcase
    falls onto the TV console in the earthquake.
  - A new photo's three scenes are computed in the background while the reply is written
    (`server._prepare_scenes`). One room quake takes about 2–4 s, child or adult about 0.5–1.5 s.
- **Outlines:** the photo shows SAM's real masks, not boxes (`analyze.outline`):
  - Douglas-Peucker cuts a path from 76 kB to under 1 kB, and holes are dropped. For example, the
    hutch outline cuts around the high chair in front of it.
  - Two pieces never share an outline (`analyze.assign_outlines`).
  - Reports saved before session 3 have no outlines and still draw boxes.
- **Piece cards:** verdict, three risk tiles (now buttons), items on top, questions, fixes with
  after-states and "Show me". Judged pieces have "judged" tags, no "Show me", and their fixes and
  answers still update the verdict.
- **Tests:** `uv run pytest` runs 43 tests in about 50 s:
  - physics vs MuJoCo, including a bookcase, a wardrobe and a range;
  - cards, judged cards, every example, legacy reports, the skill loader;
  - the earthquake with sliding drawers;
  - room layout, a shared quake where each piece keeps its own strap, a child test that loads only its
    piece, and outline simplification.

The user's UX rule still holds: **nobody reads text.** The user's architecture rule, from this session:
**no hard-coded objects or prompts.** Furniture knowledge lives in `src/fall_zero/skill/`, and the code is
generic.

## Session 4's changes (on branch `skill-and-zones`, not yet committed)

1. **Everything on a piece is simulated.**
   - The survey lists every separate thing standing on a piece, on top or on its open shelves
     (`Thing.where`, `Spotted.on_it`). Old reports still load.
   - SAM matches inside the piece's outline count for shelf things.
   - `measure_items` places them on a shelf with `TopItem.shelf`, an index into
     `Case.shelf_levels(("open",))`; `Case.base_of` gives the surface height.
   - Open-shelf contents (books, dishes, toys) are always there, as loose bodies `stuff_<zone>_<shelf>_<chunk>`
     split around dividers and around things on the shelf (`furniture.runs`). They spill in quakes:
     "books fell off the shelves".
   - Item hazards use the real drop height. Cards' items carry `where`, `drop_m`, `kg` and `tempting`.
2. **Contents count in the mass.** `Case.mass()` is the empty weight. The "What's in the drawers?"
   question (Full / About half / Nearly empty) sets the drawer fill and `Case.contents_known`, so every
   test counts it. It is asked only when full versus empty changes a child or adult verdict. Details
   carry `mass_full_kg` and `holds`.
3. **Practical advice.** Every fix carries `kind` (a key of `catalog/fixes.toml`) and `how`: buy,
   cost, time, tools, steps, avoid, renter, source.
   - The describe step picks the anchor: `strap`, `bracket` for ranges, or `tv_strap`.
   - Habit fixes are added when they apply: `tempting` (moves the items, physics re-run), `heavy_low`,
     `within_reach`, `latches`, `recall`, `distance`.
   - Icons are a fixed set: strap, lock, top, distance, tv, toy, weight, hand, latch, search.
4. **Speed and the solver.** 2 ms steps without noslip, with ground motion still generated at 1 ms.
   - Load tests: median 0.2 s. One-piece quakes: median 0.55 s.
   - The quake outcomes match the old solver across 384 runs: 200 vs 202 pieces fell, 62 vs 63 shelves
     spilled.
   - Statics agree with the load-test simulation in 459 of 486 tests.
5. **People instead of test weights** (`web/people.js`, `web/viewer.js`).
   - Traces carry `actors`: who stands for the load (child or adult) and the action (stand on the
     drawer or shelf, hang on a door, pull, or watch), plus the load point's body and local point.
   - `loads` is now the ramp fraction, `pieces` carry x, y, width and depth, and `phases` gives settle
     and ramp, or quiet before a quake.
   - The viewer builds a procedural child (about 1.10 m) and an older adult (about 1.66 m) with
     two-bone IK. They walk in, climb or grab, and fall back when the piece tips.
   - The red weights are gone. Shelf contents are drawn as spines, the floor shows where a piece
     lands, and `onTip(index, seconds)` reports how long it took to fall.
6. **Left = choices, right = simulation, never duplicated** (`web/app.js`, `web/style.css`).
   - **Left:** the photo, the reply, and one card with "Help me be sure" questions, "Do these first"
     fixes (cost and time chips, "Show me", "I did this") and "Good habits" chips. A glance row with
     the three scenario statuses shows only while the panel is closed.
   - **Right:** the tabs, the viewer with fix pills, what happens to each piece, what would fall, the
     previewed fix's how-to, and the piece's fact tiles (size, empty → full weight, what it holds).
   - Every model-written label is clipped to one line.
7. **Robustness.**
   - `knowledge.label` and `knowledge.tidy` clean garbled model text where reports and cards are
     built. Once the model returned a 2,524-character item name.
   - One failed SAM call retries once, then leaves that thing without an outline.
   - A judged piece's question disappears once a fix settles it.
   - Loose things (items, shelf contents) have their frame at their own center, and their speed is capped
     at 8 m/s (`sim._Loose`). A vase squeezed between a falling bookcase and the floor was shot out at
     37 m/s and slid 212 m. The viewer also hides and never frames anything outside the room.
8. Tests: 55, covering shelf placement, the drawers question, fixes from the catalog, labels, SAM
   failure, the kitchen hutch quake, judged questions and the squeezed-item runaway.

## Session 3's changes (on branch `skill-and-zones`, uncommitted along with session 4)

1. `sim.py` builds any number of pieces into one model (`Placed`, `Ghost`, `scene_mjcf`,
   `simulate_scene`, `shake_scene`, `quake_scenario`). Each piece's names carry a prefix.
   - A lone piece gets byte-identical MJCF to before, checked over 1,228 piece/scenario pairs.
   - `simulate` and `shake` are now one-piece wrappers.
   - Traces carry every strap, each piece's carcass body and height (for the tags), ghosts, and events
     tagged with piece numbers.
2. `room.py`: `layout` (photo order to metres) and `scene` (cached per answers, scenario and focus;
   concurrent requests wait for the first). Endpoint: `POST /api/scene`.
3. `analyze.py`: `assign_outlines` (was `assign_boxes`), `outline`, and `on_top` with `union_box`.
   Reports now hold `outline` for pieces and items, and cards pass it on.
4. **Mirroring fixed:** facing a piece's front (+y) you look along -y, so the photo's left is +x.
   `room.layout` and the x of items on top (`measure_items`) follow this now. Older reports keep their
   mirrored items, which is harmless for the physics.
5. Web: the panel (`index.html` skeleton, `style.css` panel section, `app.js`). `viewer.js` handles
   several straps, transparent ghosts, the 3D tags, focus with fading, camera flights, and framing
   from the bounding sphere. The old inline "See it happen" block is gone.
6. `agent.py`: the reply speaks about the room when there are two or more pieces.

## Session 2's changes (on branch `skill-and-zones`)

1. Speed: sizing at low effort, run in parallel with SAM; earthquake workers start with the server.
   Cards went from 31.7 s to about 14–17 s.
2. Static files: `Cache-Control: no-cache` for `web/`.
3. Earthquakes: drawers ride free on their runners (friction 0.05 for metal slides, 0.25 for wood
   runners), and the drawer-lock fix is checked against earthquakes too.
4. Zones: the template is a stack of zones (`furniture.Case`, with `Dresser` kept as an alias). Old saved
   reports load through `Case.from_dict`.
5. The skill: `skill/SKILL.md`, six references, catalogs (`examples.toml` replaces `presets.toml`,
   plus `materials.toml` and `contents.toml`), and `knowledge.py`. Survey, describe and judge replace the
   hard-coded identify and estimate steps.
6. Judged cards for anything the engine can't build.
7. Depth questions are relative to the piece's own depth, and the material question only appears for wood.
8. Two new generated test rooms: `samples/kitchen_range_hutch.png` and `samples/living_room_mirror_bookcase.png`.

## Map of the code

| File | Role |
| --- | --- |
| `src/fall_zero/skill/` | what Muse Spark reads: `SKILL.md` (Survey, Describe, Judge, References), `references/*.md`, `catalog/*.toml` |
| `src/fall_zero/knowledge.py` | loads the skill: per-step instructions, answer schemas whose allowed values come from the catalogs, and `survey`, `describe`, `judge` |
| `src/fall_zero/analyze.py` | photo/video → still → survey → SAM ‖ describe/judge → item measuring → physics; CLI report; MP4 rendering |
| `src/fall_zero/assess.py` | entry → card (`card`: `assess` for built pieces, `judged_card` for judged ones); risks, item hazards, fixes, questions, earthquakes, viewer motion |
| `src/fall_zero/furniture.py` | `Case` (zones → panels, drawers, doors, shelves, contents), `TopItem`, catalog loaders, `with_mass` |
| `src/fall_zero/physics.py` | statics, the three child tests generalized to drawers, doors and shelves, adult grab, rocking threshold |
| `src/fall_zero/sim.py` | MuJoCo model of one piece or a room (`Placed`, `scene_mjcf`): drawers on slides, doors on hinges (degrees in MJCF), loose items, `simulate_scene`, `shake_scene`, `Trace` |
| `src/fall_zero/room.py` | the whole room as one scene: `layout` from the outlines, `scene` for the panel |
| `src/fall_zero/server.py` | FastAPI: `/api/turn`, `/api/assess`, `/api/scene`, `/api/simulate`, `/api/threads`, `/files`, static web (no-cache) |
| `src/fall_zero/store.py` | runs and saved chats: `out/` locally, the private Vercel Blob store when deployed |
| `app.py`, `vercel.json`, `.vercelignore` | the Vercel entrypoint, the function's 300 s, and what never gets uploaded |
| `web/` | chat (`app.js`: left = choices, right = panel), the three.js viewer (`viewer.js`), the procedural people (`people.js`) |
| `src/fall_zero/skill/catalog/fixes.toml` | practical advice per fix kind: buy, cost, time, tools, steps, avoid, renter, source |
| `docs/RESEARCH.md` | who gets hurt and how, what people believe and fear, what works; sources |

To teach it a new kind of piece, add a worked example to `catalog/examples.toml`, plus a reference
paragraph if it needs knowledge. To add a material or contents, edit the catalog. No code changes.

## Gotchas

- **Port:** 8011 (Docker holds 8000).
- **MJCF hinge ranges are in degrees**, while qpos and ctrl are in radians. A radian range once
  silently shut every door.
- **Process pool:** `assess.quakes` uses a spawn pool. Run scripts that call it from a file with a
  `__main__` guard. When comparing variants by monkeypatching in workers, use `max_tasks_per_child=1`,
  or the patch leaks into later jobs; this produced a wrong comparison once.
- **Killing the test server:** `pkill -f "...port 8012"` matches the calling shell and kills it. Kill
  by the PIDs from `ss -ltnp` instead.
- **Muse Spark function tools work** (2–10 s per round trip), but the skill passes references by code
  instead, to save the round trip.
- **Handedness:** MuJoCo +y is a piece's front. Seen from the front, +x is on the viewer's left, so
  anything placed from the photo uses x = (center - photo x) * scale.
- **Viewer bounding boxes:** call `scene.updateMatrixWorld(true)` before measuring freshly posed
  bodies. Exclude a lone piece's own `p0_wall`, or the camera frames a 4 m wall.
- **Pyright:** flags the dynamic `Literal[...]` schemas and the OpenAI calls; ruff is clean.
- **SAM can return an undecodable mask** ("Mask payload could not be decoded"). Each phrase now fails
  soft; if a whole photo fails, retry first.
- **Muse Spark can ramble** in a short field (a 2,524-character name). Everything shown goes through
  `knowledge.label`.
- **Saved chats store their cards.** Chats from before session 4 show the older fix cards (no `how`)
  until a re-check.
- **Keys:** only in `.env`, plus `MODEL_API_KEY` as a Vercel Secret (README, "Deploying"). Rotate the Meta
  and Baseten keys (they were pasted in an early transcript), then update the Vercel one.
- **Vercel:**
  - **What it uploads:** the CLI reads `.vercelignore`, not `.gitignore`; that is what keeps `.env` off it.
  - **`.env.local`:** written by `vercel link` and holds the Blob token. The app never reads it, so local
    runs keep using `out/`.
  - **Startup:** importing MuJoCo there needs `MUJOCO_GL=disable`; otherwise it looks for libEGL and every
    request fails.
  - **A tapped answer or fix** takes about 10 s there, against 1–2 s locally, because its earthquakes run
    on one CPU.
  - **Anyone with the URL can run the pipeline on our Meta key.** A Vercel Firewall rate limit on
    `/api/turn` would cap that.

## Assumptions to replace with sources

- Adult grab: 100–300 N at 0.95 m.
- Item hazard: 8 J for a hard item, 4 J for glass, 20 J for serious; a TV always counts.
- Earthquakes: synthetic ground motion; 1.5 Hz upper-floor sway; doors stay shut during the shaking.
- Drawer runner friction: 0.05 for metal slides, 0.25 for wood runners. Detents and soft-close slides
  aren't modeled.
- Contents densities marked "assumption" in `catalog/contents.toml`: books, files, dishes, pantry,
  tools, linens, toys, media, and 30 kg/m for a hanging rail.
- Example weights for steel pieces (filing cabinet 38 kg, tool chest 55 kg, shelving 20 kg, range 70 kg).
- Bookcases, TV stands and ranges borrow the F2057 child tests (marked in each scenario's `standard`).

## Next steps, in the order I'd take them

0. **Ask the user** what they think of the people, the shelf items and the left/right split, and
   whether to commit sessions 3 and 4 (both uncommitted on `skill-and-zones`). Open questions:
   - **An open drawer or door props the piece.** In 20 unstrapped cases (the filing cabinet, a HEMNES
     shoe cabinet, the GE, Whirlpool and Summit ranges, the Ashley server) it hits the floor and props
     the piece after 2–10°. Statics calls that "tips", so the animation shows the piece caught while
     the card says "Tips". This is likely in the kitchen demo. Decide whether a propped piece counts
     as tipping (the CPSC rule counts it) and show it that way, or change the verdict.
   - **Strapped cases:** in 7 of them, statics caps the strap at its 50 lbf rating, but the simulated
     strap never gives.
   - **Hutch ledge:** things on its mid-height ledge (a jar, a cloth) get no outline and are put on
     top. The template needs a set-back upper or ledge.
   - The room verdict tiles still come from the per-piece cards; pieces stand in one row against
     one wall (both carried over from session 3).
1. **Merge** branch `skill-and-zones` into master when the user okays it.
2. **Demo video (3 min):**
   - the living room: the child climbing the TV stand, the bookcase spilling books in the quake;
   - the kitchen: the range bracket fix;
   - the nursery: a child climbing the dresser drawers, "Fell in 1.2 s", strapped vs not;
   - one judged mirror.
3. **Recall check:** match a recognized brand and model against CPSC recalls (sourced), rather than
   only the generic "check cpsc.gov/Recalls" habit.
4. **Survey speed:** 8–15 s on busy rooms. Trim `rooms.md`, or let the survey stream pieces.
5. **Earthquake:** doors swinging open (magnetic catches); recorded accelerograms; people in the quake
   scene (a child playing in the fall zone) if it reads well.
6. **Validation:** pull tests against `pull_test_prediction_N`; source the assumptions above.
7. **Hackathon:** make the repo public, polish the README, build the Muse connector from the PRD, and
   use more than one video frame.
