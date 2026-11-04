"""The skill: its sections, references and catalogs load, and the answers are held to what the engine has."""

import pytest
from pydantic import ValidationError

from fall_zero import knowledge
from fall_zero.furniture import contents, examples, materials


def test_skill_sections_and_references_load():
    s = knowledge.sections()
    assert {"Survey", "Describe", "Judge", "References"} <= set(s)
    refs = knowledge.references()
    assert {"rooms", "case-furniture", "weights", "standards"} <= set(refs)
    for name in refs:  # every reference file is listed in SKILL.md, so the survey can ask for it
        assert f"`{name}`" in s["References"], name


def test_each_step_reads_only_what_it_needs():
    survey = knowledge.instructions("Survey", ["rooms"])
    assert "## Survey" in survey and "## Describe" not in survey and '<reference name="rooms">' in survey
    describe = knowledge.instructions("Describe", ["case-furniture"])
    assert "## Describe" in describe and '<reference name="rooms">' not in describe


def test_catalogs_cover_what_examples_use():
    for key, (_, d) in examples().items():
        assert d.material in materials(), key
        assert all(z.contents in ("", "none", *contents()) for z in d.zones), key
    assert "range_30in" in knowledge.catalogs_text()


def test_answers_are_limited_to_the_catalogs():
    zone = {"kind": "drawers", "share": 1, "rows": 3, "cols": 1, "shelves": 0, "hinge": "side", "fill": 1}
    knowledge.ZoneSpec(**zone, contents="clothes")
    with pytest.raises(ValidationError):
        knowledge.ZoneSpec(**zone, contents="gold bars")


def test_each_piece_reads_only_the_examples_like_it():
    assert {"ikea_billy_80", "bookcase_tall"} <= set(knowledge.shortlist("tall white bookcase by the TV bookcase"))
    ranges = knowledge.shortlist("white freestanding range kitchen range")
    assert sum(k.endswith("range") or k == "range_30in" for k in ranges) >= 4
    assert len(knowledge.shortlist("anything at all")) == knowledge.SHORTLIST


def test_real_products_carry_their_weight():
    """Products in the catalog are calibrated to their published weight (KALLAX is honeycomb board)."""
    _, kallax = examples()["ikea_kallax_2x4"]
    assert abs(kallax.mass() - 19.31) < 0.1 and kallax.density_scale < 0.7


def test_labels_are_short_words_or_the_fallback():
    label, NAME = knowledge.label, knowledge.NAME
    assert label("plant pot") == "plant pot"
    assert label("", "small vase with eucalyptus on shelf") == "small vase with eucalyptus"  # clipped, no dangling "on"
    assert label("vaseria_leafy_short_name vaseeucalyptus" * 60, "vase") == "vase"
    assert label("vase vase vase vase", "") == "" and label(None) == ""
    assert label("low wooden media console under TV", "", NAME) == "low wooden media console under TV"
    assert label("IKEA BESTÅ TV bench") == "IKEA BESTÅ TV bench"
