# Fall-Zero

> View in Room tells you if it fits. Fall-Zero tells you if it falls.

Phone video of a room → per-piece furniture tip-over verdict for a climbing child, an elderly person grabbing
for support, and earthquake shaking. Built for the Meta Global AI Developer Hackathon (Oct 27 – Nov 4, 2026).
Product spec: [docs/PRD.md](docs/PRD.md).

## Where each model fits

| Pipeline step | Model / service | Code |
| --- | --- | --- |
| Outline each piece and everything standing on it, all at once | SAM 3.1 (Meta Model API) | `analyze.segment_all` |
| Fallback 3D reconstruction for pieces with no preset | SAM 3D Objects (open weights; Modal app ready, not hosted) | `modal_apps/sam3d.py`, `reconstruct.py` |
| Identify the product, look up spec weight and recalls | Muse Spark 1.3 + web search + structured output | `meta.respond_json` |
| Chat: one-line summary above the cards, follow-ups | Muse Spark 1.3 (vision, streamed, chained by response id) | `agent.reply` |
| Match each piece to a tunable preset, then run the scenarios | presets + statics + MuJoCo (local) | `presets.toml`, `furniture.py`, `physics.py`, `sim.py` |
| Staged earthquake: shaking rises through four intensity levels; items on top slide and fall | MuJoCo (local) | `sim.shake` |
| Voice entry ("is this dresser safe?") | Muse Voice Transcribe | `voice.py` |
| Illustrations / UI assets | Muse Image | `meta.generate_image` |
| Long agentic jobs, alternative backends | Muse Wonder; Muse Spark Open on Baseten / Fireworks / Modal; Muse Glimmer on Modal | `clients.py`, `modal_apps/glimmer.py` |

Every provider speaks the OpenAI protocol, so `clients.chat(prompt, provider="baseten")` and friends switch
backends with one argument.

## Setup

```bash
uv sync
cp .env.example .env          # then fill in the keys you have
uv run fall-zero smoke        # calls each configured service once; unconfigured ones are skipped
```

Modal (for SAM 3D Objects and, optionally, Glimmer):

```bash
uv run modal token new                                        # log the CLI in
uv run modal secret create huggingface HF_TOKEN=hf_...        # token with access to facebook/sam-3d-objects
uv run modal run modal_apps/sam3d.py::download_weights        # once
uv run modal deploy modal_apps/sam3d.py
uv run fall-zero smoke meta-image meta-sam sam3d               # image -> mask -> out/smoke.glb
```

`modal_apps/glimmer.py` holds an H100 while it's warm and scales to zero after 10 idle minutes. Run
`uv run modal app stop fall-zero-glimmer` when you're done with it.

## Commands

| Command | What it does |
| --- | --- |
| `uv run fall-zero serve [--port 8011]` | Chat web app at http://localhost:8011: send a photo or video, get the verdicts, ask follow-ups |
| `uv run fall-zero analyze PHOTO_OR_VIDEO [--no-video]` | Per-piece verdicts, ranked fixes, and before/after videos in `out/<name>/` |
| `uv run pytest` | Physics tests (MuJoCo agrees with the statics, pull test within ±10%) and card tests |
| `uv run fall-zero smoke [checks...]` | Health check. Checks: `meta-spark meta-wonder meta-image meta-vision meta-search-json meta-sam meta-voice-file meta-voice-realtime baseten fireworks modal glimmer sam3d mujoco` |
| `uv run ruff check . && uv run ruff format .` | Lint and format |

## Layout

```
src/fall_zero/
  config.py       settings from .env
  clients.py      OpenAI-compatible client per provider (meta, baseten, fireworks, modal, glimmer)
  meta.py         Muse Spark/Wonder text + vision, structured output, Muse Image, SAM 3.1
  voice.py        Muse Voice Transcribe: file upload and realtime WebSocket
  analyze.py      photo/video -> pieces -> SAM boxes -> preset + estimate -> verdicts, fixes, videos
  assess.py       report -> cards: tips/maybe/holds per risk, re-checked fixes, questions when unsure
  agent.py        chat agent: one or two sentences above the cards, follow-up questions
  presets.toml    furniture library the agent matches pieces to (depth, material, drawer grid...)
  furniture.py    parametric template: panels, drawers, items on top (TV, boxes), mass, ASTM F2057 constants
  physics.py      tip-over statics, F2057 child tests, elderly grab, rocking threshold
  sim.py          MuJoCo model + video of a template under a scenario; the staged earthquake
  reconstruct.py  fallback for pieces with no preset: SAM mask -> SAM 3D Objects (not hosted)
  server.py       serves web/ and the API; /api/turn streams one chat turn as NDJSON
  smoke.py        end-to-end check of every service
web/              chat page (plain HTML/CSS/JS, no build step)
modal_apps/
  sam3d.py        SAM 3D Objects on an L40S
  glimmer.py      Muse Glimmer 30B on vLLM, H100
samples/          generated test rooms (Muse Image)
tests/            physics, card and earthquake tests
docs/PRD.md
```

## Web app

`uv run fall-zero serve`, then open http://localhost:8011. Send a photo or a short video (attach, drop, or
paste; the empty screen has two sample rooms).

Nobody reads paragraphs, so the answer is cards. Each piece gets a verdict (can tip / might tip / stable),
a tile per risk (climbing child, adult leaning, earthquake), question cards when the answer depends on
something a photo can't show (is it strapped? which floor? how deep? what material? measured size?), and fix
cards that show what each risk becomes once the fix is done. Tapping an answer or "I did this" re-runs the
physics in place (`/api/assess`). Muse Spark adds one or two sentences above the cards.

Things on top are judged one by one: Muse Spark says what each is and whether it's hard or breakable, the
physics gives how hard it would hit (weight x fall height), and the simulated earthquakes show whether it
falls. Only things that would hurt someone go into the "move it" fix; a plush toy is marked harmless.

"See it happen" plays the simulation inside the card in 3D (three.js): the child test, the adult grab, or the
staged earthquake, as it is, strapped, or with the hard things moved. The server sends only the motion
(`/api/simulate`, about a second), the browser draws it, and you can turn the view.

Chats are saved as they happen (`out/threads/`); the clock button in the top-left control reopens them.
Numbers, timings and the raw report are under "Details".

API: `POST /api/turn` (multipart `text`, `previous_response_id`, `context`, optional `media`) streams NDJSON
events `step`, `report` (with `run` and `cards`), `delta`, `done` (with the `response_id` for the next turn),
or `error`. `POST /api/assess` (`run`, `piece`, `answers`) returns one updated card; `POST /api/simulate`
(plus `scenario`, `variant`, `seed`) returns a simulation's motion for the viewer; `/api/threads` lists, saves
and deletes chats. Each upload and its
`report.json` land in `out/web/<id>/`. The other routes are listed at `/docs`.

## Earthquake

`sim.shake(template, anchored=False, video=..., building_hz=None)` shakes the piece against a wall with its
drawers shut and full, in four 5-second stages at the USGS intensity levels: strong (0.15 g), very strong
(0.3 g), severe (0.5 g), violent (0.8 g). The floor motion is filtered noise (Kanai-Tajimi with the
Clough-Penzien high-pass, the textbook model of strong ground motion). `building_hz` adds the sway of the
building, i.e. an upper floor instead of the ground. The simulation runs in the floor's frame, where shaking
equals a sideways gravity; the video camera moves against the floor so the room is seen to shake. Things on
top are loose bodies and fall on their own.

Each card shakes the piece as it is, strapped, and with the hard things moved, in 3 simulated earthquakes
each, all in parallel (a few seconds, cached). An upper floor is assumed until the user answers the floor
question.

What it shows so far: short acceleration peaks alone don't topple furniture, even at 0.8 g on the ground
floor. On an upper floor the swaying building rocks a tall chest until it goes over. The nursery chest with
its TV and boxes fell in 2 of 3 simulated quakes, 1 of 3 with the top cleared, and never when strapped.
Drawers stay shut during the shaking for now; in reality they slide open and make it worse.

## Notes

- Baseten: the hackathon build of Muse Spark Open is `meta-models/muse-spark-open-1026`, not the docs' default.
- Muse Spark Open reasons at `xhigh` by default on every host; pass `reasoning_effort="low"` for cheap calls.
- SAM video: upload the clip with `client("meta").files.create(purpose="user_data", ...)` and send it as
  `{"type": "input_video", "file_id": ...}`; parse with `meta_sam_parser.video_segmentation_format()`.
- Fireworks dropped serverless Glimmer on Sept 25, 2026, so Glimmer runs on our own Modal GPU.
- Hackathon rules: the repo must be public, and the demo must show only work built during the event.
- Rendering under WSL waits ~65 ms per frame on the GPU copy, so videos take ~15 s each (4 render in
  parallel). Native Linux GPUs are much faster. Verdicts and fixes print first, in ~30 s.
