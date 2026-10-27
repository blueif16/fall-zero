"""The tip-over skill (`skill/`): the instructions and references Muse Spark reads, and the catalogs the
engine builds from. The code keeps no furniture knowledge of its own. A new reference, material, kind
of contents or worked example is a file edit under `skill/`, not a code change.

Each step reads SKILL.md's opening, its own section, and only the references it needs:
- `survey`: "Survey" + `rooms` -> every piece that could tip, its family, the references it needs,
  and what stands on it;
- `describe`: "Describe" + the piece's references + the catalogs -> the case the engine builds;
- `judge`: "Judge" + the piece's references -> a verdict for anything the engine can't build.

The code picks the references from the survey's answer, so the extra knowledge costs no extra
round trip (a function-tool lookup would add 2-10 s per call).
"""

import re
from functools import cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from fall_zero import meta
from fall_zero.furniture import SKILL_DIR, contents, examples, materials

EFFORT = "low"  # sizes pieces as well as medium does, in about half the time


@cache
def sections() -> dict[str, str]:
    """SKILL.md split at its `## ` headings; "" is the text before the first one, frontmatter dropped."""
    text = re.sub(r"\A---\n.*?\n---\n", "", (SKILL_DIR / "SKILL.md").read_text(), flags=re.S)
    parts = re.split(r"^## (.+)$", text, flags=re.M)
    out = {"": parts[0].strip()}
    for title, body in zip(parts[1::2], parts[2::2], strict=True):
        out[title.strip()] = f"## {title.strip()}\n{body.strip()}"
    return out


@cache
def references() -> dict[str, str]:
    return {p.stem: p.read_text().strip() for p in sorted((SKILL_DIR / "references").glob("*.md"))}


def _reading(names) -> str:
    refs = references()
    return "\n\n".join(f'<reference name="{n}">\n{refs[n]}\n</reference>' for n in dict.fromkeys(names) if n in refs)


def instructions(step: str, refs=()) -> str:
    s = sections()
    return "\n\n".join(filter(None, [s[""], s[step], s["References"] if step == "Survey" else "", _reading(refs)]))


# The catalog keys become the answer's allowed values, so the model can only name what the engine has
RefName = Literal[tuple(references())]  # type: ignore[valid-type]
MaterialName = Literal[tuple(materials())]  # type: ignore[valid-type]
ContentsName = Literal[(*contents(), "none")]  # type: ignore[valid-type]
ExampleName = Literal[(*examples(), "none")]  # type: ignore[valid-type]
Status = Literal["tips", "maybe", "holds"]


# --- survey ----------------------------------------------------------------------------------------


class Thing(BaseModel):
    name: str
    sam_concept: str


class Spotted(BaseModel):
    name: str
    sam_concept: str
    family: str
    engine: Literal["case", "judge"]
    references: list[RefName]
    on_top: list[Thing]


class Survey(BaseModel):
    room: str
    people: str
    pieces: list[Spotted]


def survey(image: Path) -> Survey:
    """Everything in the photo that could tip or fall onto someone."""
    found = meta.respond_json("Survey this room.", Survey, images=[image], effort=EFFORT,
                              instructions=instructions("Survey", ["rooms"]))  # fmt: skip
    names = {t.name.lower() for p in found.pieces for t in p.on_top}
    # something listed both on a piece and as a piece of its own stays on its piece
    found.pieces = [p for p in found.pieces if p.name.lower() not in names]
    return found


# --- describe --------------------------------------------------------------------------------------


class ZoneSpec(BaseModel):
    kind: Literal["drawers", "doors", "open"]
    share: float
    rows: int
    cols: int
    shelves: int
    hinge: Literal["side", "bottom"]
    contents: ContentsName
    fill: float


class ItemSpec(BaseModel):
    short_name: str
    shape: Literal["block", "screen"]
    material: str
    hard: bool
    breakable: bool
    kg: float
    depth_cm: float


class CaseSpec(BaseModel):
    example: ExampleName
    width_cm: float
    height_cm: float
    depth_cm: float
    depth_is_guess: bool
    base: Literal["plinth", "legs"]
    base_height_cm: float
    material: MaterialName
    known_mass_kg: float | None
    drawer_runners: Literal["metal_slides", "wood_runners", "unknown"]
    zones: list[ZoneSpec]
    brand_model: str | None
    size_basis: str
    items_on_top: list[ItemSpec]
    nearby: str | None
    anchor_fix: str
    anchor_how: str


def zones_text(zones) -> str:
    """Zones from the floor up in a few words each: "drawers 3x2 clothes; doors 2 side, 1 shelf, books 0.5"."""
    parts = []
    for z in zones:
        what = {"drawers": f"drawers {z.rows}x{z.cols}", "doors": f"doors {z.cols} {z.hinge}",
                "open": f"open {z.cols}"}[z.kind]  # fmt: skip
        if z.kind != "drawers" and z.shelves:
            what += f", {z.shelves} {'shelf' if z.shelves == 1 else 'shelves'}"
        kept = z.contents or ("clothes" if z.kind == "drawers" else "")
        if kept and kept != "none":
            what += f", {kept}" + (f" {z.fill:g}" if z.fill < 1 else "")
        parts.append(what + (f" ({z.share:g})" if len(zones) > 1 else ""))
    return "; ".join(parts)


SHORTLIST = 16  # worked examples per describe prompt: the whole catalog slows the call by ~5 s
STOPWORDS = {"a", "an", "and", "by", "cm", "for", "in", "of", "on", "or", "the", "to", "with", "size", "white"}


def _words(text: str) -> set[str]:
    words = {w.rstrip("s") for w in re.findall(r"[a-z]+", text.lower().replace("_", " "))}
    return {w for w in words if len(w) > 2 and w not in STOPWORDS}


def shortlist(about: str = "", n: int = SHORTLIST) -> list[str]:
    """The worked examples whose names share the most words with the piece ("white tall bookcase by TV",
    "bookcase"), catalog order breaking ties; with nothing in common, the first ones."""
    want = _words(about)
    keys = list(examples())
    score = {k: len(want & _words(f"{k} {examples()[k][0]}")) for k in keys}
    return sorted(keys, key=lambda k: (-score[k], keys.index(k)))[:n]


def catalogs_text(keys: list[str] | None = None) -> str:
    """The catalogs in one line per entry, for the describe step: the worked examples in `keys` (all of
    them by default), the materials and the contents."""
    library = examples()
    ex = "\n".join(
        f"- {k}: {label} | {d.width * 100:.0f}x{d.depth * 100:.0f}x{d.height * 100:.0f} cm | {d.material}, {d.base} | "
        f"{d.mass():.0f} kg | {zones_text(d.zones)}"
        for k in keys or library
        for label, d in [library[k]]
    )
    mats = "\n".join(f"- {k}: {m.label}" for k, m in materials().items())
    kept = "\n".join(f"- {k}: {c.label}" for k, c in contents().items())
    return (
        f"## Worked examples (key: name | W x D x H | material, base | empty weight | zones from the floor up, "
        f"with each zone's share of the height)\n{ex}\n\n## Materials\n{mats}\n\n## Contents\n{kept}"
    )


def describe(image: Path, piece: Spotted, room: str = "") -> CaseSpec:
    """The piece as a case for the engine."""
    on_top = "; ".join(f"{i + 1}. {t.name}" for i, t in enumerate(piece.on_top))
    task = f"In this photo of a {room or 'room'}, describe the {piece.name} ({piece.family}) for the engine. " + (
        f"Items on top, in this order: {on_top}." if on_top else "Nothing stands on top: items_on_top is empty."
    )
    refs = [*piece.references, *(["weights"] if piece.on_top else [])]
    examples_for = catalogs_text(shortlist(f"{piece.name} {piece.family}"))
    return meta.respond_json(task, CaseSpec, images=[image], effort=EFFORT,
                             instructions=instructions("Describe", refs) + "\n\n" + examples_for)  # fmt: skip


# --- judge -----------------------------------------------------------------------------------------


class Statuses(BaseModel):
    child: Status
    adult: Status
    quake: Status


class Risk(BaseModel):
    status: Status
    says: str


class JudgedFix(BaseModel):
    title: str
    why: str
    icon: Literal["strap", "lock", "top", "distance", "move"]
    after: Statuses


class Option(BaseModel):
    label: str
    after: Statuses


class Question(BaseModel):
    title: str
    options: list[Option]


class Judgment(BaseModel):
    child: Risk
    adult: Risk
    quake: Risk
    fixes: list[JudgedFix]
    question: Question | None
    basis: str


def judge(image: Path, piece: Spotted, room: str = "", people: str = "") -> Judgment:
    """A verdict from the references, for what the engine can't build."""
    where = f"{room or 'room'} ({people or 'household unknown'})"
    task = f"In this photo of a {where}, judge the {piece.name} ({piece.family})."
    return meta.respond_json(task, Judgment, images=[image], effort=EFFORT,
                             instructions=instructions("Judge", piece.references))  # fmt: skip
