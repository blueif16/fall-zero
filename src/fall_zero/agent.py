"""The chat agent: Muse Spark says in a sentence or two what the cards show, and answers follow-ups.

The cards (assess.py) carry the verdicts, fixes and questions; people look at those, not at prose.
Each turn chains to the last with `previous_response_id`, so the photo and earlier cards stay in
context without the server storing the conversation.
"""

import json
from collections.abc import AsyncIterator
from pathlib import Path

from fall_zero.clients import aclient
from fall_zero.config import get_settings
from fall_zero.meta import image_part

INSTRUCTIONS = """\
You are the voice of a home-safety check. People send a photo or video of any room; a physics engine \
tests whether each piece of furniture or appliance there can tip onto a climbing child, an adult grabbing \
it for balance, or in an earthquake. Things the engine can't build (a leaning mirror, a floor lamp) are \
judged from safety guidance instead, and their cards say "judged". The page shows the results as cards: \
a verdict per risk (tips / maybe / holds), fix cards that show what each fix changes, and question cards \
when the answer depends on something a photo can't show.

Nobody reads long text. Your reply sits above the cards and must be one or two short sentences, at most \
30 words. With one piece: name it in everyday words ("the tall white chest by the crib"), who it could \
hurt, and the single thing to do first, or the one question that would settle it. With two or more \
pieces the page shows one card for the whole room, and people judge the setup as a whole, so speak about \
the room: what in it can fall and on whom, and the one step that makes the whole room safest (ROOM lists \
the fixes shared across pieces, most helpful first). No numbers unless one is essential. Never repeat \
the cards, never list, never use headings.

Use only the CARDS' verdicts. Never invent a verdict, size or weight. If every piece holds, say so plainly. \
Things standing on a piece (on top or on its shelves) are rated danger, caution or fine: mention only the \
hard ones that would hurt someone, never soft things like plush toys.

When KNOWN is present, this room was checked before: start from what changed since (CHANGED: a fix \
still in place, something new, moved or put on top), in the same one or two sentences, and don't \
repeat what still holds.

For follow-up questions answer in at most three short sentences, from the cards and general \
furniture-safety knowledge. CONTEXT, when present, is the cards as they stand after the user's taps. If \
asked about a change the cards don't cover, say it hasn't been checked yet rather than guessing. If no \
photo has been sent yet, ask for a photo or short video of the room.\
"""


def _fix(f: dict) -> str:
    after = f" -> {f['after']}" if f["after"] else ""
    return f"{f['title']}{after}{' (done)' if f.get('done') else ''}"


def _brief(cards: list[dict]) -> list[dict]:
    """What the agent needs from each card; the numbers stay out."""
    return [{"piece": c["name"], "verdict": c["headline"],
             "risks": {k: f"{r['status']}: {r['says']}" for k, r in c["risks"].items()},
             "on_it": [f"{i['short']} on {'the top' if i.get('where', 'top') == 'top' else 'a shelf'}: {i['level']} "
                       f"({i['why']})" for i in c.get("items", [])],
             "fixes": [_fix(f) for f in c["fixes"]], "questions": [q["title"] for q in c["questions"]],
             "answers": c["answers"]} for c in cards]  # fmt: skip


RANK = {"holds": 0, "maybe": 1, "tips": 2}


def _room(cards: list[dict]) -> dict:
    """The room as the page's room card shows it: the worst status per risk and the pieces behind it,
    and each fix with every piece it covers, ranked by how many risks it settles across the room."""
    worst = {k: max((c["risks"][k]["status"] for c in cards), key=RANK.__getitem__) for k in cards[0]["risks"]}
    fixes: dict[str, dict] = {}
    for c in cards:
        for f in c["fixes"]:
            if f.get("answer") and not f.get("done"):
                entry = fixes.setdefault(f["title"], {"pieces": [], "settles": 0})
                entry["pieces"].append(c["name"])
                entry["settles"] += sum(RANK[f["after"][k]] < RANK[c["risks"][k]["status"]] for k in f["after"] or {})
    return {"worst": {k: f"{s}: " + ", ".join(c["name"] for c in cards if c["risks"][k]["status"] == s)
                      if s != "holds" else s for k, s in worst.items()},
            "fixes_first": [{"fix": t, "pieces": v["pieces"]}
                            for t, v in sorted(fixes.items(), key=lambda kv: -kv[1]["settles"])][:3]}  # fmt: skip


def turn_prompt(text: str, cards: list[dict], others: list[str], known: dict | None) -> str:
    """What the agent reads about a new photo: the cards, the room, and for a room checked before
    (`known`, library.py), what it found then and what changed since."""
    said = f'They wrote: "{text}"' if text else "They didn't write anything."
    prompt = f"The user sent a room photo. {said}\nCARDS:\n{json.dumps(_brief(cards))}"
    if len(cards) > 1:
        prompt += f"\nROOM:\n{json.dumps(_room(cards))}"
    if others:
        prompt += f"\nAlso in the photo, not checked (no template yet): {', '.join(others)}"
    if known:
        last = [{"piece": p["name"], "worst": max(p["status"].values(), key=RANK.__getitem__), "done": p["done"]}
                for p in known["last"]["pieces"]]  # fmt: skip
        prompt += (f"\nKNOWN: their {known['name']}, last checked {known['since'][:10]}: {json.dumps(last)}"
                   f"\nCHANGED: {json.dumps([c['text'] for c in known['changes']]) or 'nothing'}")  # fmt: skip
    return prompt


async def reply(
    text: str = "",
    image: Path | None = None,
    cards: list[dict] | None = None,
    others: list[str] | None = None,
    context: str = "",
    previous_response_id: str | None = None,
    known: dict | None = None,
) -> AsyncIterator[tuple[str, str]]:
    """Stream the answer: yields ("delta", text) chunks, then ("done", response_id)."""
    if cards is not None:
        prompt = turn_prompt(text, cards, others or [], known)
    else:
        prompt = f"CONTEXT:\n{context}\n\n{text}" if context else text
    content: list[dict] = [{"type": "input_text", "text": prompt}]
    if image:
        content.append(image_part(image))
    kwargs = {"previous_response_id": previous_response_id} if previous_response_id else {}
    stream = await aclient("meta").responses.create(
        model=get_settings().meta_text_model,
        instructions=INSTRUCTIONS,
        input=[{"role": "user", "content": content}],
        reasoning={"effort": "low"},
        stream=True,
        **kwargs,
    )
    async for event in stream:
        if event.type == "response.output_text.delta":
            yield "delta", event.delta
        elif event.type == "response.completed":
            yield "done", event.response.id
