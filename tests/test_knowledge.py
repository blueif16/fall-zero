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
