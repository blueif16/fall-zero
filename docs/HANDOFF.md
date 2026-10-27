# Handoff: where Fall 0 stands (2026-10-27)

Meta Global AI Developer Hackathon. Building period Oct 27 – Nov 4, 2026. **Submission due Wed Nov 4,
9:00 PM ET**, with a 3-minute demo video. The repo must be public, and the demo may show only work built
during the event. The product spec is [PRD.md](PRD.md); [../README.md](../README.md) covers setup, commands and the model map.

## What works now

You send a photo or video of a room in the chat at http://localhost:8011 (`uv run fall-zero serve`). In
about 30 s, each dresser, chest or nightstand comes back as a card:

- **The pipeline:**
  1. Muse Spark lists the pieces and what stands on each one.
  2. SAM 3.1 outlines all of them in one parallel pass.
  3. Muse Spark matches each piece to a preset in `presets.toml`, estimates its size, and judges every item
     on top: short name, material, hard or soft, breakable, kg.
  4. Statics and the ASTM F2057 child tests run over 300 plausible sizes.
  5. MuJoCo shakes the piece in 3 simulated earthquakes for each version: as is, strapped, and with the
     hard things moved.
- **The card:**
  - a verdict;
  - three risk tiles (child climbs, adult leans, earthquake), each tips, maybe or holds;
  - "On top" chips rated danger, caution or fine (a plush toy is fine, a ceramic pot or a TV is not);
  - question cards (strapped? which floor? depth? material? tape measure?);
  - fix cards that show each risk after the fix.

  Tapping an answer or "I did this" re-checks through `/api/assess`.
- **"See it happen":** a three.js viewer inside the card plays the real simulation: the child test, the adult
  grab, or the staged earthquake, each as is, strapped, or with the hard things moved. The server sends only
  the motion (`/api/simulate`, about 1 s); the browser draws it, and you can turn the view.
- **Chat:**
  - Muse Spark writes 1–2 sentences above the cards, and follow-ups chain through `previous_response_id`.
  - The mic button uses Muse Voice Transcribe.
  - Chats are saved to `out/threads/` and reopened with the clock button at the top left.
- **UI:** light theme with a dotted background. The "Fall 0" wordmark is Instrument Serif with an italic blue
  numeral 0. There's no top bar, only a floating control at the top left (wordmark, new chat, history, live status).
- **Tests:** `uv run pytest` runs 21 tests: physics vs MuJoCo, the cards, item hazards, the earthquake, and
  the viewer trace.

The user's UX rule: **nobody reads text.** Answer with visual cards: is it dangerous, how to fix it, what
we still need to know. Keep asking when unsure. Prose stays at one or two sentences, and numbers stay
under "Details".

## Map of the code

| File | Role |
| --- | --- |
| `src/fall_zero/analyze.py` | photo/video → still → identify → SAM → estimate → item measuring (`measure_items`, `separate`) → physics; also the CLI report and MP4 rendering |
| `src/fall_zero/assess.py` | report entry → card: risks, item hazards (`item_hazard`), fixes, questions, simulated quakes (`quakes`, process pool + cache), viewer motion (`trajectory`) |
| `src/fall_zero/sim.py` | MuJoCo model (items on top are loose bodies), load tests, `shake` (staged earthquake, Kanai–Tajimi ground motion, optional building sway), `Trace` (motion for the viewer), MP4 recorder |
| `src/fall_zero/physics.py` | statics, F2057 tests, adult grab, rocking threshold, pull-test force |
| `src/fall_zero/furniture.py` | `Dresser` template, `TopItem`, presets loader |
| `src/fall_zero/agent.py` | Muse Spark chat voice (instructions, brief of the cards) |
| `src/fall_zero/server.py` | FastAPI: `/api/turn` (NDJSON stream), `/api/assess`, `/api/simulate`, `/api/threads`, static web |
| `web/` | `index.html`, `style.css`, `app.js` (chat, cards, history), `viewer.js` (three.js playback) |

## Gotchas

- **Port:** the server runs on **8011**, because a Docker container on the user's machine holds 8000.
- **Browser cache:** the user once saw the old page without the simulation. Their browser hadn't loaded the
  new script, and a refresh fixed it. `StaticFiles` sends no `Cache-Control`; adding `no-cache` for `web/`
  would prevent this.
- **Process pool:** `assess.quakes` uses a spawn-context process pool. Run scripts that call it from a file
  with a `__main__` guard, not from stdin.
- **Video rendering:** MP4 rendering under WSL is slow, about 65 ms per frame of GPU readback. The browser
  viewer avoids it.
- **Pyright:** it flags the OpenAI Responses calls (TypedDict noise). Ruff is clean.
- **Keys:** they live only in `.env` (gitignored, chmod 600), and the pre-commit hook blocks key patterns.
  The Meta and Baseten keys were pasted into an early session transcript, so **rotate them**. Fireworks and
  Modal aren't configured; the Glimmer and SAM 3D Modal apps are untested and not hosted.
- **Old chats:** chats saved before the item ratings and the simulation still open, with the older cards.

## Assumptions to replace with sources

- **Adult grab force:** 100–300 N at 0.95 m (`physics.GRAB_FORCE_RANGE_N`).
- **Item hazard:** a hard item counts from 8 J, roughly 1 kg from 0.8 m; glass or ceramic from 4 J; serious
  from 20 J; a TV always (`assess.HURT_J`, `SERIOUS_J`).
- **Earthquakes:**
  - The ground motion is synthetic, Kanai–Tajimi with the Clough–Penzien high-pass.
  - The stages are 0.15, 0.30, 0.50 and 0.80 g, 5 s each.
  - An upper floor is modeled as a 1.5 Hz building sway, and the card assumes an upper floor until the user answers.
  - Drawers stay shut during the shaking; in reality they slide open, which makes it worse.
- **Items:** depth is guessed by kind; a TV's weight comes from its measured width (0.0045 kg per square inch
  of diagonal); items are centered front to back unless they overlap.
- **Muse Spark sizing:** it varies run to run. The preset pick and the size change, and the verdicts mostly don't.

## Next steps, in the order I'd take them

1. **Demo video (3 min).** Script: the nursery photo, then the cards, then the "Earthquake" tab (the TV
   falls, then the chest falls), then "Strapped" (it holds), then a tap on "Yes, strapped". Also export the
   MP4s via `sim.shake(video=...)`.
2. **Speed.** The Muse Spark sizing call takes 15–20 s of the ~30 s. Options: merge identify and estimate,
   lower the effort, or stream each card as soon as it's ready.
3. **Earthquake realism.** Let drawers slide open; optionally use a recorded accelerogram; show the floor
   answer in the viewer.
4. **More furniture.** Add bookcase, TV stand and wardrobe presets; today those come back as "can't check yet".
5. **Static files:** add `Cache-Control: no-cache` for `web/`.
6. **Validation.** Pull tests with a luggage scale against `pull_test_prediction_N` (PRD); source the assumptions above.
7. **Hackathon requirements.** Make the GitHub repo public (no remote yet), polish the README, build the Muse
   connector from the PRD, and use several video frames instead of only the sharpest one.
