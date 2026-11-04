"""Turning SAM's matches into one outline per piece."""

import asyncio
from collections import Counter
from pathlib import Path
from types import SimpleNamespace as Match

from meta_sam_parser import InvalidSegmentationMaskError

from fall_zero.analyze import assign_outlines, outline, segment_all

RANGE, HUTCH, CABINET = (68, 274, 561, 899), (858, 0, 1526, 912), (520, 480, 850, 890)


def test_two_pieces_never_share_an_outline():
    """ "small wooden cabinet" also matched the big hutch next to it; the cabinet takes its own match."""
    found = [[Match(box=RANGE, confidence=0.9)],
             [Match(box=(857, 0, 1529, 914), confidence=0.6), Match(box=CABINET, confidence=0.5)],
             [Match(box=HUTCH, confidence=0.95)]]  # fmt: skip
    assert [m and m.box for m in assign_outlines(found)] == [RANGE, CABINET, HUTCH]


def test_the_surer_piece_keeps_a_contested_outline():
    found = [[Match(box=(857, 0, 1529, 914), confidence=0.5)], [Match(box=HUTCH, confidence=0.95)], []]
    assert [m and m.box for m in assign_outlines(found)] == [None, HUTCH, None]


def test_an_outline_is_one_light_solid_shape_in_photo_pixels():
    """SAM's path steps along every pixel; holes (books inside a bookcase's frame) are dropped."""
    edge = "L".join(f"{i} 0" for i in range(1, 100))
    square, hole = f"M0 0L{edge}L100 0L100 100L0 100Z", "M40 40L50 40L60 40L60 50L60 60L50 60L40 60L40 50Z"
    box = Match(left=10, top=20, right=210, bottom=220)
    path = outline([Match(svg_path=square + hole, mask=Match(bounds=box, mask=Match(width=100, height=100)))])
    assert path.count("M") == 1 and path.count("L") == 3
    assert path.startswith("M10 20L210 20")  # scaled by 2 and moved to where the mask sits


def test_a_failed_sam_call_is_tried_again_then_left_without_an_outline():
    """The session's first photo failed whole on one undecodable mask; now that phrase alone comes back empty."""
    calls = Counter()

    async def sam(image, concept, include_confidence=False):
        calls[concept] += 1
        if concept == "vase" or (concept == "range" and calls[concept] == 1):
            raise InvalidSegmentationMaskError("Mask payload could not be decoded.")
        return [Match(box=HUTCH, confidence=0.9)]

    found = asyncio.run(segment_all(Path("room.jpg"), ["hutch", "range", "vase"], segment=sam))
    assert [[m.box for m in f] for f in found] == [[HUTCH], [HUTCH], []]
    assert calls == {"hutch": 1, "range": 2, "vase": 2}
