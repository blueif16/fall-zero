"""The room library: Fall 0's memory of a home (docs/FLOW.md S6).

Every checked room is kept as a record: its photo, its pieces (with ids that stay the same from one
check to the next), what was answered and done, and a breakdown of what was found, piece by piece, with
a dated snapshot of the breakdown for each check. A new photo of a known room matches its pieces to the
record's, carries over what is still true (it's strapped, what's in the drawers, the floor), and says
what changed since: pieces new, gone or moved, things put on or taken off, verdicts better or worse,
fixes still in place.

Records live in the store under homes/<owner>/ (homes/local/ when running locally).
"""

import base64
import io
import json
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path

from PIL import Image

from fall_zero import store
from fall_zero.assess import CARD_STATUSES, JUDGED_KINDS, RISK_KEYS, judged_icon

RANK = {"holds": 0, "maybe": 1, "tips": 2}
CARRY = ("anchored", "locks", "drawers", "depth", "material", "measured")  # what stays true of a piece
ROOM_WIDE = ("floor",)  # what is true of the whole room
HURTS = ("danger", "caution")  # what would hurt someone if it fell
TODO = ("item", "count", "cost_usd", "minutes")  # a fix still to do, for the home's shopping list
NEAR = 0.15  # two things this close along a piece (a share of its width) are the same thing
STOP = {"the", "a", "an", "by", "on", "of", "with", "in", "and", "to", "under", "next", "near"}


def folder(owner: str) -> str:
    """Locally the home is yours; deployed, each browser's (X-Owner) is its own."""
    if not store.REMOTE:
        return "homes/local/"
    if not re.fullmatch(r"[0-9a-f]{32}", owner):
        raise ValueError("no owner")
    return f"homes/{owner}/"


def entries(report: dict) -> list[dict]:
    """The report's pieces that have a card, in the cards' order."""
    return [e for e in report["pieces"] if e["status"] in CARD_STATUSES]


def _x(entry: dict, width: float) -> float | None:
    box = entry.get("box")
    return round((box[0] + box[2]) / 2 / width, 3) if box else None


def _words(*texts: str) -> set[str]:
    return {w for t in texts for w in re.findall(r"[a-z0-9]+", (t or "").lower()) if w not in STOP}


def _worst(statuses) -> str:
    return max(statuses, key=RANK.__getitem__, default="holds")


# --- a check of a room, as a record ------------------------------------------------------------------


def _across(box, piece) -> float | None:
    """Where a thing stands along its piece, from its left edge (0) to its right (1)."""
    if not box or not piece or piece[2] <= piece[0]:
        return None
    return round(((box[0] + box[2]) / 2 - piece[0]) / (piece[2] - piece[0]), 3)


def _same_things(before: dict, after: dict) -> tuple[list[str], list[str]]:
    """What was put on a piece and what was taken off. A thing goes by its name, or else by its place (on
    top or on a shelf, at about the same spot along the piece), since one photo's "vase" is another's
    "potted plant". Breakdowns saved before places were kept go by name alone."""
    old = list(before.get("spots") or [{"name": n} for n in before["items"]])
    put = []
    for t in after.get("spots") or [{"name": n} for n in after["items"]]:
        near = [o for o in old if o.get("x") is not None and t.get("x") is not None and o.get("where") == t.get("where")
                and abs(o["x"] - t["x"]) < NEAR]  # fmt: skip
        same = next((o for o in old if o["name"] == t["name"]), None) or (
            min(near, key=lambda o: abs(o["x"] - t["x"])) if near else None
        )
        if same:
            old.remove(same)
        else:
            put.append(t["name"])
    return put, [o["name"] for o in old]


def _todo(fix: dict) -> dict:
    how = fix.get("how") or {}
    return {"kind": fix.get("kind", ""), "title": fix["title"]} | {k: how[k] for k in TODO if k in how}


def breakdown(report: dict, cards: list[dict], pieces: list[dict], now: str) -> dict:
    """What this check found, piece by piece: the verdict per scenario and why, what would fall from it,
    what stands on it, where it stands, the fixes done and the questions still open."""
    out = []
    for p, c in zip(pieces, cards, strict=True):
        items = [it.get("short") or it.get("name") or "" for it in c.get("items", [])]
        out.append({
            "id": p["id"], "name": c["name"], "family": p["family"], "x": p["x"],
            "status": {k: c["risks"][k]["status"] for k in RISK_KEYS},
            "why": {k: c["risks"][k].get("says", "") for k in RISK_KEYS},
            "falls": [n for n, it in zip(items, c.get("items", []), strict=True) if it.get("level") in HURTS],
            "items": items,
            "spots": [{"name": n, "where": it.get("where", "top"), "x": _across(it.get("box"), p["box"])}
                      for n, it in zip(items, c.get("items", []), strict=True)],  # fmt: skip
            "done": [f["title"] for f in c["fixes"] if f.get("done")],
            "todo": [_todo(f) for f in c["fixes"] if f.get("answer") and not f.get("done")],
            "open": [q["title"] for q in c["questions"]],
        })  # fmt: skip
    status = {k: _worst(p["status"][k] for p in out) for k in RISK_KEYS}
    return {"date": now, "room": report.get("room") or "room", "status": status, "pieces": out}


def record(report: dict, cards: list[dict], run: str, previous: dict | None = None, ids: dict | None = None,
           extras: dict | None = None, thread: str | None = None, now: str | None = None) -> dict:  # fmt: skip
    """The room as this check leaves it. `previous` is the room's record when it was recognized, `ids`
    which of its pieces each card is (card index -> piece id), `extras` what only the page knows (when
    each fix was checked)."""
    now = now or datetime.now(UTC).isoformat()
    ids = dict(ids or {})
    width = report["size"][0]
    checked = (extras or {}).get("checked", {})
    was = {p["id"]: p for p in (previous or {}).get("pieces", [])}
    pieces = []
    for i, (e, c) in enumerate(zip(entries(report), cards, strict=True)):
        pid = ids.get(i) or f"p{uuid.uuid4().hex[:8]}"
        pieces.append({
            "id": pid, "name": c["name"], "family": e["piece"].get("family", ""), "x": _x(e, width),
            "box": e.get("box"), "answers": c.get("answers", {}),
            "done": [f["kind"] for f in c["fixes"] if f.get("done") and f.get("kind")],
            "checked": checked.get(str(i)) or checked.get(i) or was.get(pid, {}).get("checked", {}),
        })  # fmt: skip
    bd = breakdown(report, cards, pieces, now)
    before = (previous or {}).get("history", [])
    return {
        "id": (previous or {}).get("id") or uuid.uuid4().hex[:12],
        "name": report.get("room") or "room",
        "created": (previous or {}).get("created", now),
        "updated": now,
        "run": run,
        "thread": thread or (previous or {}).get("thread"),
        "still": f"/files/{run}/{Path(report['image']).name}" if report.get("image") else report.get("still"),
        "size": report["size"],
        "pieces": pieces,
        "breakdown": bd,
        "history": [h for h in before if h["run"] != run] + [{"run": run, "date": now, "breakdown": bd}],
    }


# --- a new photo of a known room ---------------------------------------------------------------------


def match_pieces(previous: dict, report: dict) -> dict[int, str]:
    """Which of the record's pieces each card of a new photo is: the same kind of thing (its family, or
    most of its name) in about the same place. Card index -> piece id; a piece with no match is new."""
    width = report["size"][0]
    pairs = []
    for i, e in enumerate(entries(report)):
        fam, name, x = _words(e["piece"].get("family", "")), _words(e["piece"]["name"]), _x(e, width)
        for old in previous["pieces"]:
            same_family = bool(fam & _words(old["family"]))
            ow = _words(old["name"])
            alike = len(name & ow) / len(name | ow) if name | ow else 0
            if not (same_family or alike >= 0.34):
                continue
            near = 1 - abs(x - old["x"]) if x is not None and old["x"] is not None else 0.5
            pairs.append((2 * same_family + alike + 0.5 * near, i, old["id"]))
    out: dict[int, str] = {}
    for _, i, pid in sorted(pairs, reverse=True):
        if i not in out and pid not in out.values():
            out[i] = pid
    return dict(sorted(out.items()))


def carry(previous: dict, ids: dict[int, str], report: dict) -> dict[int, dict]:
    """The answers to start each card of the new photo with: what's still true of its piece (strapped,
    what's in the drawers, its measured size) and of the room (the floor). A judged piece keeps its done
    fixes by kind, since the judge numbers them afresh each time. What named one photo's things (which
    items were moved) doesn't carry."""
    by_id = {p["id"]: p for p in previous["pieces"]}
    room = {k: v for p in previous["pieces"] for k, v in p["answers"].items() if k in ROOM_WIDE}
    out = {}
    for i, e in enumerate(entries(report)):
        answers = dict(room)
        old = by_id.get(ids.get(i))
        if old:
            answers |= {k: v for k, v in old["answers"].items() if k in CARRY}
            if e["status"] == "judged":
                for j, f in enumerate(e["judgment"]["fixes"]):
                    if JUDGED_KINDS.get(judged_icon(f)) in old["done"]:
                        answers[f"fix_{j}"] = True
        if answers:
            out[i] = answers
    return out


def changes(before: dict, after: dict) -> list[dict]:
    """What changed between two breakdowns of a room: pieces new, gone or moved (their order along the
    wall changed), things put on or taken off a piece, verdicts worse or better (with the scenarios, so
    the page shows only those that count for the home), and fixes still in place."""
    old, new = {p["id"]: p for p in before["pieces"]}, {p["id"]: p for p in after["pieces"]}
    out = []

    def say(kind, p, text, **more):
        out.append({"kind": kind, "id": p["id"], "name": p["name"], "text": text} | more)

    for p in after["pieces"]:
        if p["id"] not in old:
            say("new", p, f"New: {p['name']}")
    for p in before["pieces"]:
        if p["id"] not in new:
            say("gone", p, f"Gone: {p['name']}")
    common = [pid for pid in new if pid in old]

    def order(side):
        placed = sorted((side[pid]["x"], pid) for pid in common if side[pid]["x"] is not None)
        return {pid: rank for rank, (_, pid) in enumerate(placed)}

    was, now = order(old), order(new)
    for pid in common:
        o, n = old[pid], new[pid]
        if pid in was and pid in now and was[pid] != now[pid]:
            say("moved", n, f"Moved: {n['name']}")
        worse = [k for k in RISK_KEYS if RANK[n["status"][k]] > RANK[o["status"][k]]]
        better = [k for k in RISK_KEYS if RANK[n["status"][k]] < RANK[o["status"][k]]]
        if worse:
            say("worse", n, f"{n['name']} can fall now", scenarios=worse)
        if better:
            say("better", n, f"{n['name']} holds better", scenarios=better)
        put, taken = _same_things(o, n)
        for item in put:
            say("added", n, f"New on {n['name']}: {item}", item=item, hurts=item in n["falls"])
        for item in taken:
            say("removed", n, f"Off {n['name']}: {item}", item=item)
        for fix in [f for f in o["done"] if f in n["done"]]:
            say("kept", n, f"Still in place: {fix.lower()} ({n['name']})", fix=fix)
    return out


# --- the library in the store ------------------------------------------------------------------------


def _room_name(owner: str, rid: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{12}", rid):
        raise ValueError("unknown room")
    return f"{folder(owner)}rooms/{rid}.json"


def save(owner: str, rec: dict) -> dict:
    store.write(_room_name(owner, rec["id"]), json.dumps(rec).encode())
    return rec


def get(owner: str, rid: str) -> dict | None:
    body = store.read(_room_name(owner, rid))
    return json.loads(body) if body else None


def remove(owner: str, rid: str) -> None:
    store.delete(_room_name(owner, rid))


def household(owner: str) -> dict:
    """Who's home, as the person confirmed it (catalog/household.toml's answers)."""
    body = store.read(f"{folder(owner)}home.json")
    return json.loads(body) if body else {}


def save_household(owner: str, answers: dict) -> None:
    store.write(f"{folder(owner)}home.json", json.dumps(answers).encode())


def photo(rec: dict, side: int = 640) -> str | None:
    """A room's latest photo, small, as a data URL: what the match step looks at."""
    name = rec.get("still", "").removeprefix("/files/")
    path = store.local(f"web/{name}") if name.count("/") == 1 else None
    if not path:
        return None
    img = Image.open(path).convert("RGB")
    img.thumbnail((side, side))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=80)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def rooms(owner: str) -> list[dict]:
    """Every room in the home, newest check first, as the full records."""
    names = [n for n in store.names(f"{folder(owner)}rooms/") if n.endswith(".json")]
    found = [json.loads(body) for n in names if (body := store.read(n))]
    return sorted(found, key=lambda r: r["updated"], reverse=True)
