# Handoff: where Fall 0 stands (2026-10-27, second session)

Meta Global AI Developer Hackathon. Building period Oct 27 – Nov 4, 2026. **Submission due Wed Nov 4,
9:00 PM ET**, with a 3-minute demo video. The repo must be public, and the demo may show only work built
during the event. The product spec is [PRD.md](PRD.md); [../README.md](../README.md) covers setup, commands and the model map.

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
- **Cards:** same as before (verdict, three risk tiles, items on top, questions, fixes with
  after-states, the 3D viewer). Judged pieces have "judged" tags and no viewer, and their fixes and
  answers still update the verdict. The viewer has a "Drawer locks" variant.
- **Tests:** `uv run pytest` runs 35 tests in about 35 s: physics vs MuJoCo (now including a bookcase, a
  wardrobe and a range), cards, judged cards, every example, legacy reports, the skill loader, and the
  earthquake with sliding drawers.

The user's UX rule still holds: **nobody reads text.** The user's architecture rule, from this session:
**no hard-coded objects or prompts.** Furniture knowledge lives in `src/fall_zero/skill/`, and the code is
generic.

## This session's changes (uncommitted on master until the user asks)

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
| `src/fall_zero/sim.py` | MuJoCo model: drawers on slides, doors on hinges (degrees in MJCF), loose items, `shake`, `Trace` |
| `src/fall_zero/server.py` | FastAPI: `/api/turn`, `/api/assess`, `/api/simulate`, `/api/threads`, static web (no-cache) |
| `web/` | chat, cards (judged tags), three.js viewer |

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
- **Pyright:** flags the dynamic `Literal[...]` schemas and the OpenAI calls; ruff is clean.
- **Keys:** only in `.env`. Rotate the Meta and Baseten keys (they were pasted in an early transcript).

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

1. **Commit** this session's work once the user okays it.
2. **Real product data** (the user's idea, scoped down): grow `catalog/examples.toml` from public
   spec sheets with real dimensions and weights (IKEA, Wayfair, office and garage brands, ranges), with
   sources. Recommended over importing 3D model files for the physics; the user hadn't decided at the end
   of the session.
3. **Demo video (3 min):** kitchen, living room and nursery; the earthquake tab with drawers sliding
   out; the drawer-lock and strap variants; one judged mirror.
4. **Survey speed:** 8–11 s on busy rooms. Trim `rooms.md`, or let the survey stream pieces.
5. **Earthquake:** doors swinging open (magnetic catches); recorded accelerograms.
6. **Validation:** pull tests against `pull_test_prediction_N`; source the assumptions above.
7. **Hackathon:** make the repo public, polish the README, build the Muse connector from the PRD, and
   use more than one video frame.
