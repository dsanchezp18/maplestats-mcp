"""A hyphen at the end of a PDF line: dropped for a split word, kept for a compound."""

from __future__ import annotations

from maplestats_mcp.modules.statcan.reference import pdf
from maplestats_mcp.modules.statcan.reference.__tests__.test_publications import PGDP_PDF, _pdf


def test_a_compound_cut_at_its_hyphen_keeps_the_hyphen() -> None:
    lines = [
        "Estimates of the number of self-",
        "employed workers and of non-",
        "farm payrolls are published monthly in the survey tables",
    ]
    (paragraph,) = pdf._paragraphs(lines)
    assert "self-employed workers" in paragraph
    assert "non-farm payrolls" in paragraph


def test_a_word_split_by_the_typesetter_is_still_joined() -> None:
    lines = [
        "The publication presents statis-",
        "tics for each indus-",
        "try in the province.",
    ]
    (paragraph,) = pdf._paragraphs(lines)
    assert "statistics for each industry" in paragraph
    assert "-" not in paragraph


def test_french_compounds_keep_the_hyphen() -> None:
    lines = [
        "Une sous-",
        "estimation de la demi-",
        "heure travaillée n'a pas été corrigée dans cette série.",
    ]
    (paragraph,) = pdf._paragraphs(lines)
    assert "sous-estimation" in paragraph
    assert "demi-heure" in paragraph


def test_a_prefix_that_splits_ordinary_words_needs_the_document_to_hyphenate_it() -> None:
    # "high-" / "est" is the typesetter's split of "highest", so it joins. "well-" /
    # "known" is a compound only because the document writes "well-known" elsewhere.
    lines = ["The high-", "est rate is a well-", "known figure."]
    assert pdf._paragraphs(lines) == ["The highest rate is a wellknown figure."]
    elsewhere = pdf._hyphenated_pairs([["It is a well-known figure"]])
    assert pdf._paragraphs(lines, elsewhere) == ["The highest rate is a well-known figure."]


def test_the_pairs_a_document_hyphenates_include_each_step_of_a_long_compound() -> None:
    pairs = pdf._hyphenated_pairs([["the Year-over-year change", "a part-time job"], ["x-"]])
    assert pairs == {"year-over", "over-year", "part-time"}


def test_extract_keeps_compounds_so_a_search_for_them_finds_the_page() -> None:
    page = [
        "Self-employment",
        "In 1999 the number of self-",
        "employed workers outside agriculture, and of non-",
        "farm payrolls, was published for the first time in the monthly tables.",
        "",
        "A part-time job is counted in the survey.",
    ]
    second = [
        "The share of part-",
        "time jobs was estimated from the same tables for the whole of the year.",
    ]
    document = pdf.extract(
        _pdf([page, second]), PGDP_PDF, max_pages=5, max_chars=10**6, seconds=60.0
    )
    text = " ".join(b.text for b in document.page.blocks if b.kind == "text")
    assert "self-employed workers" in text
    assert "non-farm payrolls" in text
    # "part-time" is written whole on the first page, so the split on the second is a compound.
    assert "share of part-time jobs" in text
