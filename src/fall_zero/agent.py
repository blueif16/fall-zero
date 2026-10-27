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
You are the voice of a home-safety check. People send a photo or video of a room; a physics engine \
tests whether each dresser, chest or nightstand can tip onto a climbing child, an adult grabbing it for \
balance, or in an earthquake. The page shows the results as cards: a verdict per risk (tips / maybe / \
holds), fix cards that show what each fix changes, and question cards when the answer depends on \
something a photo can't show.

Nobody reads long text. Your reply sits above the cards and must be one or two short sentences, at most \
30 words: name the piece that matters most in everyday words ("the tall white chest by the crib"), who it \
could hurt, and the single thing to do first, or the one question that would settle it. No numbers \
unless one is essential. Never repeat the cards, never list, never use headings.

Use only the CARDS' verdicts. Never invent a verdict, size or weight. If every piece holds, say so plainly. \
Things on top are rated danger, caution or fine: mention only the hard ones that would hurt someone, \
never soft things like plush toys.

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
             "on_top": [f"{i['short']}: {i['level']} ({i['why']})" for i in c.get("items", [])],
             "fixes": [_fix(f) for f in c["fixes"]], "questions": [q["title"] for q in c["questions"]],
             "answers": c["answers"]} for c in cards]  # fmt: skip


async def reply(
    text: str = "",
    image: Path | None = None,
    cards: list[dict] | None = None,
    others: list[str] | None = None,
    context: str = "",
    previous_response_id: str | None = None,
) -> AsyncIterator[tuple[str, str]]:
    """Stream the answer: yields ("delta", text) chunks, then ("done", response_id)."""
    if cards is not None:
        said = f'They wrote: "{text}"' if text else "They didn't write anything."
        prompt = f"The user sent a room photo. {said}\nCARDS:\n{json.dumps(_brief(cards))}"
        if others:
            prompt += f"\nAlso in the photo, not checked (no template yet): {', '.join(others)}"
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
