"""Meta Model API: Muse Spark / Wonder (text + vision), Muse Image, SAM 3.1.

Speech-to-text lives in `voice.py` because it uses its own endpoints instead of the OpenAI protocol.
"""

import base64
import mimetypes
from dataclasses import dataclass
from pathlib import Path

from meta_sam_parser import (
    SegmentationBoxRecord,
    SegmentationMaskRecord,
    decode_mask_to_svg_path,
    image_segmentation_format,
    parse_responses_stream,
)
from pydantic import BaseModel

from fall_zero.clients import aclient, client
from fall_zero.config import get_settings


def image_part(image: str | Path) -> dict:
    """An `input_image` content part from a URL, data URL, or local file path."""
    s = str(image)
    if s.startswith(("http://", "https://", "data:")):
        return {"type": "input_image", "image_url": s}
    path = Path(image)
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    data = base64.b64encode(path.read_bytes()).decode()
    return {"type": "input_image", "image_url": f"data:{mime};base64,{data}"}


# --- Muse Spark / Muse Wonder ------------------------------------------------


def respond(
    prompt: str,
    images: list[str | Path] | None = None,
    model: str | None = None,
    effort: str | None = None,
    previous_response_id: str | None = None,
    **kwargs,
):
    """Responses API call. Returns the full response; read `.output_text` for the answer
    and pass `.id` back as `previous_response_id` to continue the conversation."""
    if images:
        content = [{"type": "input_text", "text": prompt}, *(image_part(i) for i in images)]
        input_ = [{"role": "user", "content": content}]
    else:
        input_ = prompt
    if effort:
        kwargs["reasoning"] = {"effort": effort}  # minimal | low | medium | high | max
    if previous_response_id:
        kwargs["previous_response_id"] = previous_response_id
    return client("meta").responses.create(model=model or get_settings().meta_text_model, input=input_, **kwargs)


def respond_json[T: BaseModel](
    prompt: str,
    schema: type[T],
    images: list[str | Path] | None = None,
    web_search: bool = False,
    model: str | None = None,
    effort: str | None = None,
) -> T:
    """Structured output, optionally grounded in live web search. Returns a validated `schema` instance."""
    kwargs: dict = {
        "text": {"format": {"type": "json_schema", "name": schema.__name__, "schema": schema.model_json_schema()}}
    }
    if web_search:
        kwargs["tools"] = [{"type": "web_search"}]
    resp = respond(prompt, images=images, model=model, effort=effort, **kwargs)
    return schema.model_validate_json(final_text(resp))


def final_text(resp) -> str:
    """Text of the last assistant message. With tools, the model also writes progress notes
    between searches, and `resp.output_text` concatenates all of them."""
    last = next(o for o in reversed(resp.output) if o.type == "message")
    return "".join(c.text for c in last.content if c.type == "output_text")


# --- Muse Image --------------------------------------------------------------


def generate_image(prompt: str, size: str | None = None, output_format: str = "png") -> bytes:
    """One-shot text-to-image; returns the encoded image. `size` ("1792x1024") sets the aspect ratio only."""
    kwargs = {"size": size} if size else {}
    resp = client("meta").images.generate(
        model=get_settings().meta_image_model,
        prompt=prompt,
        n=1,
        extra_body={"output_format": output_format},
        **kwargs,
    )
    return base64.b64decode(resp.data[0].b64_json)


def edit_image(images: list[str | Path], prompt: str, output_format: str = "png") -> bytes:
    """One-shot edit / compose of local image files."""
    files = [open(p, "rb") for p in images]
    try:
        resp = client("meta").images.edit(
            model=get_settings().meta_image_model,
            image=files if len(files) > 1 else files[0],
            prompt=prompt,
            extra_body={"output_format": output_format},
        )
    finally:
        for f in files:
            f.close()
    return base64.b64decode(resp.data[0].b64_json)


# For multi-turn image refinement, use `respond(..., model="muse-image-1.0",
# previous_response_id=...)`: the image comes back as an `image_generation_call`
# output item. See https://dev.meta.ai/docs/image-generation


# --- SAM 3.1 -----------------------------------------------------------------


@dataclass
class Segment:
    object_id: str
    box: tuple[float, float, float, float]  # left, top, right, bottom in source pixels
    svg_path: str  # mask outline, in box-local mask pixels
    mask: SegmentationMaskRecord
    confidence: float | None = None


async def segment_image(image: str | Path, concept: str, include_confidence: bool = False) -> list[Segment]:
    """Find every `concept` (a short noun phrase like "yellow school bus") in an image."""
    kwargs = {"metadata": {"include_confidence": "true"}} if include_confidence else {}
    stream = await aclient("meta").responses.create(
        model=get_settings().meta_sam_model,
        input=[
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": concept}, image_part(image)],
            }
        ],
        stream=True,
        **kwargs,
    )
    result = await parse_responses_stream(stream, image_segmentation_format()).final_result()

    boxes = {r.object_id: r for r in result.records if isinstance(r, SegmentationBoxRecord)}
    segments = []
    for m in (r for r in result.records if isinstance(r, SegmentationMaskRecord)):
        b = boxes.get(m.object_id)
        src = b or m.bounds
        box = (src.left, src.top, src.right, src.bottom)
        segments.append(Segment(m.object_id, box, decode_mask_to_svg_path(m.mask), m, m.confidence))
    return segments
