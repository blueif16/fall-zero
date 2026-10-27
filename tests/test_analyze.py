"""Turning SAM's matches into one outline per piece."""

from types import SimpleNamespace as Match

from fall_zero.analyze import assign_boxes

RANGE, HUTCH, CABINET = (68, 274, 561, 899), (858, 0, 1526, 912), (520, 480, 850, 890)


def test_two_pieces_never_share_an_outline():
    """ "small wooden cabinet" also matched the big hutch next to it; the cabinet takes its own match."""
    found = [[Match(box=RANGE, confidence=0.9)],
             [Match(box=(857, 0, 1529, 914), confidence=0.6), Match(box=CABINET, confidence=0.5)],
             [Match(box=HUTCH, confidence=0.95)]]  # fmt: skip
    assert assign_boxes(found) == [RANGE, CABINET, HUTCH]


def test_the_surer_piece_keeps_a_contested_outline():
    found = [[Match(box=(857, 0, 1529, 914), confidence=0.5)], [Match(box=HUTCH, confidence=0.95)], []]
    assert assign_boxes(found) == [None, HUTCH, None]
