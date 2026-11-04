# Fall-Zero

> View in Room tells you if it fits. Fall-Zero tells you if it falls.

Phone video of any room → a tip-over verdict for every piece of furniture or appliance in it, for a climbing
child, an elderly person grabbing for support, and earthquake shaking. Built for the Meta Global AI Developer Hackathon (Oct 27 – Nov 4, 2026).
Product spec: [docs/PRD.md](docs/PRD.md).

## Where each model fits

| Pipeline step | Model / service | Code |
| --- | --- | --- |
| Outline each piece and everything standing on it, all at once | SAM 3.1 (Meta Model API) | `analyze.segment_all` |
| Fallback 3D reconstruction for pieces with no preset | SAM 3D Objects (open weights; Modal app ready, not hosted) | `modal_apps/sam3d.py`, `reconstruct.py` |
| Survey the room, then describe each piece for the engine (or judge it), guided by the tip-over skill | Muse Spark 1.3 + structured output | `knowledge.py`, `skill/` |
| Chat: one-line summary above the cards, follow-ups | Muse Spark 1.3 (vision, streamed, chained by response id) | `agent.reply` |
| Build each piece from its zones (drawers, doors, open shelves), then run the scenarios | statics + MuJoCo (local) | `furniture.py`, `physics.py`, `sim.py` |
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

## Deploying

Live at https://fall-zero.vercel.app (Vercel project `fall-zero`, Hobby plan). From the repo root:

```bash
npx vercel deploy --prod     # uploads the working tree, minus .vercelignore (.env, out/, tests, docs)
```

- **Entry:** the root `app.py` loads `src/fall_zero/server.py`. `vercel.json` gives the function 300 s,
  the Hobby maximum; a photo takes about 80 s.
- **Keys:** the app needs one there, `MODEL_API_KEY` (Meta: Muse Spark, SAM 3.1, voice). It is stored as a
  Secret for Production and Preview. To change it, for example after rotating, pipe it from `.env` so it
  never shows on screen, then redeploy (a new key reaches new deployments only):
  ```bash
  uv run python -c "from dotenv import dotenv_values; print(dotenv_values('.env')['MODEL_API_KEY'], end='')" \
    | npx vercel env add MODEL_API_KEY -e production,preview --sensitive --force --yes
  ```
  The other `.env` keys (Baseten, Fireworks, Modal, Hugging Face) serve the CLI and the smoke tests. The web
  app doesn't use them, so they aren't uploaded.
- **Storage:** uploads, reports and saved chats go to the private Blob store `fall-zero-files`; Vercel set
  `BLOB_READ_WRITE_TOKEN` when it was connected. Locally they stay in `out/`. Deployed, each browser lists
  only its own chats.
- **What differs on Vercel** (where `VERCEL` is set):
  - One CPU, so the earthquakes run one after another (about 15 s a room).
  - No OpenGL (`MUJOCO_GL=disable`).
  - No ffmpeg and a 4.5 MB request limit, so the page sends a photo at 1600 px, a video as its sharpest
    frame, and voice as WAV.
  - The `/api/chat`, `/api/image` and `/api/segment` playgrounds are off.

## Layout

```
src/fall_zero/
  config.py       settings from .env
  clients.py      OpenAI-compatible client per provider (meta, baseten, fireworks, modal, glimmer)
  meta.py         Muse Spark/Wonder text + vision, structured output, Muse Image, SAM 3.1
  voice.py        Muse Voice Transcribe: file upload and realtime WebSocket
  analyze.py      photo/video -> pieces -> SAM outlines -> preset + estimate -> verdicts, fixes, videos
  assess.py       report -> cards: tips/maybe/holds per risk, re-checked fixes, questions when unsure
  agent.py        chat agent: one or two sentences above the cards, follow-up questions
  knowledge.py    loads the skill: the prompt for each step, and answer schemas held to the catalogs
  skill/          the tip-over skill Muse Spark reads (no furniture knowledge lives in the code):
    SKILL.md        how to survey a room, describe a piece as zones, and judge what can't be built
    references/     rooms, case furniture, appliances and screens, other hazards, weights, standards
    catalog/        examples.toml (worked examples), materials.toml, contents.toml, fixes.toml (practical advice)
  furniture.py    one parametric template for every case piece: a box whose front is a stack of zones
                  (drawers, side- or bottom-hinged doors, open shelves), contents, things on it, mass
  physics.py      tip-over statics, F2057 child tests, elderly grab, rocking threshold
  sim.py          MuJoCo model + video of one piece or a whole room under a scenario; the staged earthquake
  room.py         the whole room as one scene: pieces placed as the photo shows them, simulated together
  reconstruct.py  fallback for pieces with no preset: SAM mask -> SAM 3D Objects (not hosted)
  server.py       serves web/ and the API; /api/turn streams one chat turn as NDJSON
  smoke.py        end-to-end check of every service
web/              chat page (plain HTML/CSS/JS, no build step); viewer.js plays the simulation, people.js draws
                  the child and adult who climb or grab
modal_apps/
  sam3d.py        SAM 3D Objects on an L40S
  glimmer.py      Muse Glimmer 30B on vLLM, H100
samples/          generated test rooms (Muse Image)
tests/            physics, card and earthquake tests
docs/PRD.md, docs/RESEARCH.md (who gets hurt, what people fear, what works, with sources)
```

## Web app

`uv run fall-zero serve`, then open http://localhost:8011. The empty screen explains the four steps (snap
the room, find what can tip, simulate it, fix it). Send a photo or a short video (the chat bar's button, drop,
or paste), or tap one of the four sample rooms above the chat bar.

Any room works: a nursery, a kitchen (a range, a hutch), a living room (a TV on a console, a bookcase, a
leaning mirror), a garage or an office. Most pieces are boxes with drawers, doors or shelves, which the engine
builds and tests. Anything else (a leaning mirror, a floor lamp, a safe) is judged by Muse Spark from the
skill's references and its tiles are tagged "judged" instead of "simulated".

Nobody reads paragraphs, so the answer is cards, split in two and never repeated. The chat on the left holds
the choices: questions when the answer depends on something a photo can't show (is it strapped? which floor?
what's in the drawers? how deep? measured size?), and "Do these first", the fixes that help the whole room most
("Strap it to the wall" on pieces 1 and 2 is one row), each with its cost and time, "Show me" and "I did this",
plus good habits (nothing tempting on top, heavy things low, everyday things within reach). Tapping an answer or
"I did this" re-runs the physics (`/api/assess`). Muse Spark adds one or two sentences above, about the room.
The advice is practical and sourced (`skill/catalog/fixes.toml`, `docs/RESEARCH.md`): what to buy, what to
avoid (plastic straps, peel-and-stick, bare drywall), three steps, and what renters can do.

SAM 3.1 outlines every piece and every thing on it, on top or on its open shelves, and the photo shows those
real shapes (around a high chair standing in front of a hutch, say), numbered. The outlines also size and place
those things (on the right shelf) against their piece, and place the pieces side by side in the room's 3D scene.
What the shelves hold (books, dishes, toys) counts in the weight and is simulated loose, so it spills.

Things on it are judged one by one: Muse Spark says what each is and whether it's hard or breakable, the
physics gives how hard it would hit (weight x fall height), and the simulated earthquakes show whether it
falls. Only things that would hurt someone go into the "move it" fix; a plush toy is marked harmless.

The panel on the right (opened by the glance row, a numbered outline or a fix's "Show me") plays the whole room
in 3D (three.js): every piece placed as the photo shows it, against one wall, with everything on it, under the
chosen scenario. A child walks up and climbs the open drawer or shelf, or tugs it; an older adult grabs it for
balance; or one staged earthquake shakes them all, so books spill and one piece knocking into another shows up
too. The floor shows where a piece would land, and a tipped piece says how fast it fell. Pieces the engine
can't build stand in place as ghosts. Below the viewer: what happens to each piece, what would fall, and the
previewed fix's how-to; "All together" plays the room with every needed fix done. A piece opens on its own
view: the camera flies to it, the rest fade, and its facts (size, weight empty and full, what it holds) sit below. The server sends only the motion (`/api/scene`,
precomputed for a new photo while the reply is written), the browser draws it, and you can turn the view.

Chats are saved as they happen (`out/threads/`); the clock button in the top-left control reopens them.
Numbers, timings and the raw report are under "Details".

API: `POST /api/turn` (multipart `text`, `previous_response_id`, `context`, optional `media`) streams NDJSON
events `step`, `report` (with `run` and `cards`), `delta`, `done` (with the `response_id` for the next turn),
or `error`. `POST /api/assess` (`run`, `piece`, `answers`) returns one updated card; `POST /api/scene`
(`run`, each piece's `answers`, `scenario`, optional `focus`) returns the whole room's simulation for the
panel's viewer; `POST /api/simulate` (`run`, `piece`, `scenario`, `variant`, `seed`) returns one piece's;
`/api/threads` lists, saves and deletes chats. Each upload and its
`report.json` land in `out/web/<id>/`. The other routes are listed at `/docs`.

## Earthquake

`sim.shake(template, anchored=False, video=..., building_hz=None, locks=False)` shakes the piece against a
wall with its drawers shut and full (only their runners' friction holds them, so they can slide out; with
`locks`, an interlock lets only one), in four 5-second stages at the USGS intensity levels: strong (0.15 g), very strong
(0.3 g), severe (0.5 g), violent (0.8 g). The floor motion is filtered noise (Kanai-Tajimi with the
Clough-Penzien high-pass, the textbook model of strong ground motion). `building_hz` adds the sway of the
building, i.e. an upper floor instead of the ground. The simulation runs in the floor's frame, where shaking
equals a sideways gravity; the video camera moves against the floor so the room is seen to shake. Things on
top are loose bodies and fall on their own.

Each card shakes the piece as it is, strapped, with drawer interlocks, and with the hard things moved, in 3
simulated earthquakes each, all in parallel (about 3 s with the workers warm, cached). An upper floor is assumed until the user answers the floor
question.

What it shows so far: drawers on metal slides open by the second stage (0.3 g), the weight moves forward, and
tall chests fall even on the ground floor (the nursery chest in 2 of 3 quakes). With drawer interlocks it
stays up on the ground floor; strapped, it never falls. Doors stay shut during the shaking for now.

## Notes

- Baseten: the hackathon build of Muse Spark Open is `meta-models/muse-spark-open-1026`, not the docs' default.
- Muse Spark Open reasons at `xhigh` by default on every host; pass `reasoning_effort="low"` for cheap calls.
- SAM video: upload the clip with `client("meta").files.create(purpose="user_data", ...)` and send it as
  `{"type": "input_video", "file_id": ...}`; parse with `meta_sam_parser.video_segmentation_format()`.
- Fireworks dropped serverless Glimmer on Sept 25, 2026, so Glimmer runs on our own Modal GPU.
- Hackathon rules: the repo must be public, and the demo must show only work built during the event.
- Rendering under WSL waits ~65 ms per frame on the GPU copy, so videos take ~15 s each (4 render in
  parallel). Native Linux GPUs are much faster. In the web app, cards arrive in about 14-17 s for one piece.
