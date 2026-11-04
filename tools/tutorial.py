# /// script
# requires-python = ">=3.12"
# dependencies = ["playwright>=1.58", "pillow>=11", "imageio-ffmpeg>=0.6"]
# ///
"""Re-record the front page's how-to clips (web/tutorial/) from one live run of the app.

    uv run fall-zero serve                # first, in another terminal
    uv run tools/tutorial.py              # drive a real check in Chrome, record it, cut the four clips
    uv run tools/tutorial.py --cut-only   # re-cut the last take after editing CLIPS

What gets pressed is session(); what each clip keeps is CLIPS. A clip frames named page elements (REGIONS)
wherever they are on screen at that moment, and fits long waits into a set number of seconds, so the same
spec still cuts right after the layout or the models' speed change. The take (frames, marks, element boxes)
stays in out/tutorial-take/. A closed card shows only part of its still: the middle, unless web/index.html sets
the video's object-position. Uses Google Chrome; without it: `uv run --with playwright playwright install chromium`.
"""

import argparse
import asyncio
import base64
import bisect
import json
import re
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TAKE = ROOT / "out" / "tutorial-take"
OUT = ROOT / "web" / "tutorial"
VIEW = (1280, 800)  # CSS px, recorded at 2x
SIZE = (960, 600)  # each clip; the open card shows it at about 480 x 300 CSS px
FPS = 30
PAD = 24  # CSS px of breathing room around what a clip frames
MIN_W = 520  # never zoom in closer than this many CSS px across

# Page elements a clip can frame: name -> (CSS selector, which match). Their boxes are sampled 10x a second.
REGIONS = {
    "composer": ("#composer", "first"),
    "scan": (".msg.bot .top", "last"),  # the sent photo: scanning, then outlined
    "tabs": ("#panel .p-tabs", "first"),
    "viewer": ("#panel .viewer", "first"),
    "glance": (".card.choices .glance", "last"),
    "todo": (".card.choices .trow", "first"),
}


@dataclass
class Seg:
    start: str  # a mark from session(), optionally shifted: "sent+0.6"
    end: str
    frame: tuple[str, ...]  # REGIONS kept in view (their union)
    secs: float | None = None  # squeeze this stretch into this many seconds; None = real time
    pan: float = 0.7  # seconds to glide over from the previous segment's framing


@dataclass
class Clip:
    name: str  # web/tutorial/<name>.mp4 and .jpg (the still shown before it plays)
    segs: list[Seg]
    poster: float = 0.5  # where in the clip the still is taken, 0-1
    hold: float = 1.0  # seconds the last frame stays before the loop restarts


CLIPS = [
    Clip("room", [Seg("home+0.3", "sent+0.6", ("composer",)), Seg("sent+0.6", "scan+2", ("scan",), secs=2.2)], 0.55),
    Clip(
        "find",
        [
            Seg("scan", "report", ("scan",), secs=3.5),
            Seg("report", "replied", ("scan",), secs=2.5),
            Seg("replied+0.3", "looked+1.6", ("scan",)),
        ],
        0.97,
    ),
    Clip(
        "watch",
        [
            Seg("sim", "sim-end", ("tabs", "viewer"), secs=3.5),
            Seg("other-1.2", "other+0.2", ("tabs", "viewer")),  # the cursor heads for the other scenario
            Seg("other+0.2", "other-end", ("tabs", "viewer"), secs=5),
        ],
        0.25,
    ),
    Clip(
        "fix",
        [Seg("scrolled", "fixed", ("glance", "todo")), Seg("fixed", "rechecked+2", ("glance", "todo"), secs=3)],
        0.92,
    ),
]


# --- recording -----------------------------------------------------------------------------------

# Runs in the page before the app: a visible cursor (so a viewer sees what gets pressed), the element-box
# sampler, and the front page's own how-to cards hidden, so no clip shows the clips.
PAGE_SETUP = """
window.__fzBoxes = [];
addEventListener("DOMContentLoaded", () => {
  const s = document.createElement("style");
  s.textContent = "#empty{display:none!important}";
  document.head.appendChild(s);
  const c = document.createElement("div");
  c.style.cssText = "position:fixed;left:0;top:0;width:26px;height:26px;margin:-13px 0 0 -13px;border-radius:50%;" +
    "background:rgba(22,22,26,.22);border:2px solid #fff;box-shadow:0 1px 6px rgba(0,0,0,.35);pointer-events:none;" +
    "z-index:2147483647;transform:translate(-99px,-99px);transition:scale .12s,background .12s";
  document.documentElement.appendChild(c);
  addEventListener("mousemove", (e) => (c.style.transform = `translate(${e.clientX}px,${e.clientY}px)`), true);
  addEventListener("mousedown", () => { c.style.scale = ".72"; c.style.background = "rgba(37,99,235,.55)"; }, true);
  addEventListener("mouseup", () => { c.style.scale = "1"; c.style.background = "rgba(22,22,26,.22)"; }, true);
  setInterval(() => {
    const boxes = {};
    for (const [name, [sel, which]] of Object.entries(window.__fzRegions)) {
      const all = [...document.querySelectorAll(sel)].map((e) => e.getBoundingClientRect())
        .filter((r) => r.width && r.height);
      const r = which === "last" ? all.at(-1) : all[0];
      if (r) boxes[name] = [r.x, r.y, r.width, r.height];
    }
    window.__fzBoxes.push([Date.now() / 1000, boxes]);
  }, 100);
});
"""


class Recorder:
    def __init__(self, page, cdp, take: Path):
        self.page, self.cdp, self.take = page, cdp, take
        self.frames: list[dict] = []
        self.marks: dict[str, float] = {}
        cdp.on("Page.screencastFrame", self._frame)

    def _frame(self, ev: dict) -> None:
        name = f"{len(self.frames):06d}.jpg"
        (self.take / "frames" / name).write_bytes(base64.b64decode(ev["data"]))
        self.frames.append({"f": name, "ts": ev["metadata"].get("timestamp") or time.time()})
        asyncio.ensure_future(self._ack(ev["sessionId"]))

    async def _ack(self, sid: int) -> None:
        try:
            await self.cdp.send("Page.screencastFrameAck", {"sessionId": sid})
        except Exception:
            pass  # the page closed

    async def start(self) -> None:
        size = {"maxWidth": VIEW[0] * 2, "maxHeight": VIEW[1] * 2}
        await self.cdp.send("Page.startScreencast", {"format": "jpeg", "quality": 90, **size})

    async def mark(self, name: str, wait: float = 0) -> None:
        self.marks[name] = time.time()
        print(f"  {name}")
        await self.page.wait_for_timeout(wait * 1000)

    async def press(self, selector: str) -> None:
        """Glide the cursor to the element's middle and click it there, as a person would."""
        el = self.page.locator(selector).first
        await el.wait_for(state="visible")
        box = await el.bounding_box()
        await self.page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, steps=28)
        await self.page.wait_for_timeout(260)
        await self.page.mouse.down()
        await self.page.wait_for_timeout(110)
        await self.page.mouse.up()

    async def gone(self, selector: str, timeout: float = 120) -> None:
        await self.page.wait_for_timeout(400)  # whatever the last press started has begun
        await self.page.wait_for_function("(s) => !document.querySelector(s)", arg=selector, timeout=timeout * 1000)

    async def played(self) -> None:
        """The panel's simulation finished playing (its Replay button shows)."""
        try:
            await self.page.locator("#panel .replay:not([hidden])").wait_for(timeout=60_000)
        except Exception:
            print("  (no Replay button within 60 s; going on)")


# Smooth-scrolls the chat so the last element matching a selector sits `top` CSS px from the window's top
SCROLL_TO = """((sel, top) => {
  const all = document.querySelectorAll(sel), y = all[all.length - 1].getBoundingClientRect().top;
  document.querySelector("main").scrollBy({ top: y - top, behavior: "smooth" }); })"""


async def session(r: Recorder, photo: Path, question: str) -> None:
    """One real check, the way a person would use it. Every mark is a point CLIPS can cut at."""
    p = r.page
    await r.mark("home", wait=1.2)
    async with p.expect_file_chooser() as chooser:
        await r.press("#pick")
    await (await chooser.value).set_files(photo)
    await r.mark("attached", wait=0.9)
    await r.press("#text")
    await p.keyboard.type(question, delay=45)
    await r.mark("typed", wait=0.5)
    await r.press("#send")
    await r.mark("sent")
    await p.locator(".msg.bot .scan").wait_for()
    await r.mark("scan")
    await p.locator(".card.choices").wait_for(timeout=300_000)
    await r.mark("report")

    async def chat():  # the reply streams in, scrolling the photo up under the controls; look back at it
        await r.gone("#status[data-tone=busy]")
        await r.mark("replied", wait=0.4)
        await p.evaluate(f"() => {{ {SCROLL_TO}('.msg.bot .still', 96); }}")
        await r.mark("looked", wait=1.6)

    async def panel():  # meanwhile the panel opens by itself and plays the worst scenario
        await r.gone("#panel .viewer.busy")
        await r.mark("sim")
        await r.played()
        await r.mark("sim-end", wait=0.6)

    await asyncio.gather(chat(), panel())
    other = "child" if await p.locator("#panel .p-tab.on[data-k=quake]").count() else "quake"
    await r.press(f"#panel .p-tab[data-k={other}]")
    await r.mark("other")
    await r.gone("#panel .viewer.busy")
    await r.played()
    await r.mark("other-end", wait=0.6)
    await r.press("#panel .p-close")
    await r.mark("closed", wait=0.8)
    await p.evaluate(f"() => {{ {SCROLL_TO}('.card.choices', 90); }}")
    await r.mark("scrolled", wait=0.9)
    await r.press(".card.choices .trow .done-btn")  # "I did this" on the first fix: the physics runs again
    await r.mark("fixed")
    await r.gone(".card.choices.busy")
    await r.mark("rechecked", wait=2.5)
    await r.mark("end")


async def record(url: str, photo: Path, question: str, take: Path) -> None:
    from playwright.async_api import async_playwright

    if take.exists():
        for f in (take / "frames").glob("*.jpg"):
            f.unlink()
    (take / "frames").mkdir(parents=True, exist_ok=True)
    async with async_playwright() as pw:
        try:
            browser = await pw.chromium.launch(channel="chrome")
        except Exception:
            browser = await pw.chromium.launch()  # Playwright's own Chromium, if installed
        ctx = await browser.new_context(viewport={"width": VIEW[0], "height": VIEW[1]}, device_scale_factor=2)
        await ctx.add_init_script(f"window.__fzRegions = {json.dumps(REGIONS)};" + PAGE_SETUP)
        page = await ctx.new_page()
        r = Recorder(page, await ctx.new_cdp_session(page), take)
        await page.goto(url, wait_until="networkidle")
        await page.mouse.move(VIEW[0] / 2, VIEW[1] - 40)
        await r.start()
        failed = None
        try:
            await session(r, photo, question)
        except Exception as e:
            failed = e
            await page.screenshot(path=take / "error.png")
        await r.cdp.send("Page.stopScreencast")
        boxes = await page.evaluate("window.__fzBoxes")
        await browser.close()
    (take / "frames.json").write_text(json.dumps(r.frames))
    (take / "marks.json").write_text(json.dumps(r.marks, indent=1))
    (take / "boxes.json").write_text(json.dumps(boxes))
    about = {"url": url, "photo": str(photo), "question": question, "view": VIEW, "at": time.ctime()}
    (take / "take.json").write_text(json.dumps(about))
    if failed:
        sys.exit(f"The session stopped: {failed}\nSee {take / 'error.png'}; marks so far are in marks.json.")
    print(f"recorded {len(r.frames)} frames")


# --- cutting -------------------------------------------------------------------------------------


class Take:
    def __init__(self, take: Path):
        self.dir = take
        self.frames = json.loads((take / "frames.json").read_text())
        self.ts = [f["ts"] for f in self.frames]
        self.marks = json.loads((take / "marks.json").read_text())
        self.boxes = json.loads((take / "boxes.json").read_text())
        self.box_ts = [t for t, _ in self.boxes]

    def at(self, ref: str) -> float:
        """A mark's time, shifted by an optional "+s" / "-s" ("sim-end+0.5")."""
        name, shift = re.fullmatch(r"(.+?)([+-][\d.]+)?", ref).groups()
        if name not in self.marks:
            sys.exit(f"CLIPS cuts at {name!r}, which session() never marked (marks: {', '.join(self.marks)})")
        return self.marks[name] + float(shift or 0)

    def region(self, name: str, t: float, half: float = 0.25) -> list[float] | None:
        """The element's box around time t, averaged over half a second so the framing glides; else the
        nearest sample within a second; else None (not on screen)."""
        for span in (half, 1.0):
            lo, hi = bisect.bisect_left(self.box_ts, t - span), bisect.bisect_right(self.box_ts, t + span)
            seen = [(abs(bt - t), b[name]) for bt, b in self.boxes[lo:hi] if name in b]
            if seen and span == half:
                return [sum(v) / len(seen) for v in zip(*(b for _, b in seen), strict=True)]
            if seen:
                return min(seen)[1]
        return None

    def framing(self, names: tuple[str, ...], t: float) -> list[float] | None:
        boxes = [b for b in (self.region(n, t) for n in names) if b]
        if not boxes:
            return None
        x1, y1 = min(b[0] for b in boxes) - PAD, min(b[1] for b in boxes) - PAD
        x2, y2 = max(b[0] + b[2] for b in boxes) + PAD, max(b[1] + b[3] for b in boxes) + PAD
        return fit([x1, y1, x2 - x1, y2 - y1])

    def frame_at(self, t: float) -> str:
        return self.frames[max(0, bisect.bisect_right(self.ts, t) - 1)]["f"]


def fit(box: list[float]) -> list[float]:
    """The smallest SIZE-shaped crop of the viewport around box."""
    aspect = SIZE[0] / SIZE[1]
    x, y, w, h = box
    cx, cy = x + w / 2, y + h / 2
    w = max(w, h * aspect, MIN_W)
    w = min(w, VIEW[0], VIEW[1] * aspect)
    h = w / aspect
    x = min(max(cx - w / 2, 0), VIEW[0] - w)
    y = min(max(cy - h / 2, 0), VIEW[1] - h)
    return [x, y, w, h]


def ease(u: float) -> float:
    u = min(max(u, 0.0), 1.0)
    return u * u * (3 - 2 * u)


def plan(take: Take, clip: Clip) -> list[tuple[float, list[float]]]:
    """(source time, crop) for every output frame of the clip."""
    out: list[tuple[float, list[float]]] = []
    crop = [0.0, 0.0, *fit([0, 0, *VIEW])[2:]]
    for i, s in enumerate(clip.segs):
        a, b = take.at(s.start), take.at(s.end)
        n = max(1, round((s.secs if s.secs else b - a) * FPS))
        was = crop
        for k in range(n):
            t = a + (b - a) * k / n
            aim = take.framing(s.frame, t) or crop
            u = ease(k / FPS / s.pan) if i and s.pan else 1.0
            crop = [p + (q - p) * u for p, q in zip(was, aim, strict=True)]
            out.append((t, crop))
    out += [out[-1]] * round(clip.hold * FPS)
    return out


def cut(take_dir: Path, out_dir: Path, only: list[str] | None = None) -> None:
    import imageio_ffmpeg
    from PIL import Image

    take = Take(take_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    first = Image.open(take_dir / "frames" / take.frames[0]["f"])
    scale = first.width / VIEW[0]
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    for clip in CLIPS:
        if only and clip.name not in only:
            continue
        frames = plan(take, clip)
        mp4, jpg = out_dir / f"{clip.name}.mp4", out_dir / f"{clip.name}.jpg"
        raw = f"-loglevel error -y -f rawvideo -pix_fmt rgb24 -s {SIZE[0]}x{SIZE[1]} -r {FPS} -i -"
        h264 = "-c:v libx264 -preset slow -crf 26 -pix_fmt yuv420p -movflags +faststart -an"
        enc = subprocess.Popen([ffmpeg, *raw.split(), *h264.split(), str(mp4)], stdin=subprocess.PIPE)
        poster = min(len(frames) - 1, int(clip.poster * len(frames)))
        name, img = None, None
        for k, (t, (x, y, w, h)) in enumerate(frames):
            f = take.frame_at(t)
            if f != name:
                name, img = f, Image.open(take_dir / "frames" / f).convert("RGB")
            box = (x * scale, y * scale, (x + w) * scale, (y + h) * scale)
            shot = img.resize(SIZE, Image.Resampling.LANCZOS, box=box)
            enc.stdin.write(shot.tobytes())
            if k == poster:
                shot.save(jpg, quality=82, optimize=True)
        enc.stdin.close()
        if enc.wait():
            sys.exit(f"ffmpeg failed on {clip.name}")
        print(f"  {mp4.relative_to(ROOT)}  {len(frames) / FPS:.1f} s  {mp4.stat().st_size // 1024} KB")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--url", default="http://localhost:8011")
    ap.add_argument("--photo", type=Path, default=ROOT / "samples" / "living_room_mirror_bookcase.png")
    ap.add_argument("--question", default="My toddler climbs everything. Is this room safe?")
    ap.add_argument("--cut-only", action="store_true", help="re-cut the last take instead of recording a new one")
    ap.add_argument("--clip", action="append", help="cut only this clip (repeatable)")
    args = ap.parse_args()
    if not args.cut_only:
        try:
            health = json.load(urllib.request.urlopen(f"{args.url}/api/health", timeout=5))
        except OSError:
            sys.exit(f"The app isn't answering at {args.url}. Start it first: uv run fall-zero serve")
        if not health.get("meta"):
            sys.exit("The app has no Meta key (MODEL_API_KEY in .env), so a check can't run.")
        print("recording…")
        asyncio.run(record(args.url, args.photo.resolve(), args.question, TAKE))
    print("cutting…")
    cut(TAKE, OUT, args.clip)


if __name__ == "__main__":
    main()
