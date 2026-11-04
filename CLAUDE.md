# Fall-Zero — agent notes

- The front page's how-to clips (`web/tutorial/*.mp4|.jpg`) are generated: re-record them with `tools/tutorial.py`, never edit them by hand. See "How-to clips" below.

## How-to clips (`tools/tutorial.py`)

The four cards in `web/index.html` (`ol.flow`) each play one clip: `room`, `find`, `watch`, `fix`. A single run of `tools/tutorial.py` records a real check in Chrome and cuts all four, so after a UI or model change the clips are refreshed by one recapture plus small edits.

**Before running:** the app is up at `http://localhost:8011` and `MODEL_API_KEY` is set. On macOS that means `MUJOCO_GL=cgl uv run fall-zero serve`; Linux/WSL needs no variable. Google Chrome must be installed; without it, run `uv run --with playwright playwright install chromium`.

**Run:** `uv run tools/tutorial.py`. It takes about 2 min and makes real Meta API calls. Its dependencies come from `tools/tutorial.py.lock` in an isolated environment, not the app's.
- To re-cut the last take without recording: `--cut-only`.
- To cut just one clip: `--clip watch`.

**How it works:**
1. **Record:** `session()` presses and types like a person, with a visible cursor dot. It saves 2x screencast frames, `marks.json` (named moments) and `boxes.json` (each `REGIONS` element's on-screen box, sampled 10×/s) to `out/tutorial-take/`, which is gitignored.
2. **Cut:** each `Clip` is a list of `Seg(start_mark, end_mark, frame=REGIONS…, secs=None)`.
   - The crop follows the named elements as they move.
   - `secs` squeezes a long wait, such as the model, to a fixed length.
   - The crop glides between segments.
3. **Output:** 960×600 H.264 MP4s plus a still at `poster`.

**Where to edit:**
- What gets done: `session()`.
- What each clip keeps: `CLIPS`.
- What can be framed: `REGIONS`, given as (selector, first|last).

Use generic selectors such as the first question or the first fix, because the model's output changes from run to run. If `CLIPS` cuts at a mark that `session()` never made, the tool exits and names it. Only the open card shows media: its clip at the full 16:10, with the `poster` still showing until the clip plays. Closed cards show only their colour, numeral and text.

**A good re-record shows** (check every clip with `ffmpeg -i web/tutorial/X.mp4 -vf "fps=12/DURATION,scale=480:-1,tile=4x3" -frames:v 1 sheet.jpg`, then look at the sheet):
- **room:** "Photo / video" is clicked, the photo attaches, the question is typed and sent, and the view glides up to the scan.
- **find:** the scan steps play, then it ends on the fully outlined photo, not hidden under the top-left bar.
- **watch:** one scenario plays, the other scenario's tab is clicked, and that scenario plays.
- **fix:** "I did this" is clicked and the verdict turns green.
- Each clip is ≤ ~13 s and ≤ ~500 KB.
- On the page, card 1 is open and playing on load. Hovering a card, the round ‹ › buttons and ←/→ open another card, which widens and plays while the rest pause and show no media. With reduced motion nothing autoplays.

**Never:**
- trim or edit the MP4s by hand (re-cut instead);
- hard-code pixel crops or wall-clock seconds;
- add page fakery beyond the two recording-only tweaks in `PAGE_SETUP`: hiding `#empty`, so clips don't show the cards themselves, and the cursor dot;
- commit `out/tutorial-take/`.

Commit regenerated clips together with the change that made them necessary.
