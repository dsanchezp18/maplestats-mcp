"""The shared any-case bytes pattern both health_products readers use."""

from __future__ import annotations

import pytest

from maplestats_mcp.shared.any_case_bytes import any_case_pattern


@pytest.mark.parametrize(
    ("query", "line"),
    [
        ("échinacée", "Échinacée Plus"),
        ("ÉCHINACÉE", "échinacée plus"),
        ("éruption", "Éruption cutanée"),
        ("RASH", "skin rash"),
        ("œdème", "Œdème"),
        ("ça", "ÇA"),
    ],
)
def test_the_pattern_matches_whatever_the_case_of_any_letter(query, line):
    assert any_case_pattern(query).search(line.encode("utf-8")) is not None


def test_the_pattern_is_the_text_not_a_regular_expression():
    assert any_case_pattern("a.b").search(b"axb") is None
    assert any_case_pattern("a.b").search(b"A.B") is not None


def test_an_ascii_spelling_does_not_match_an_accented_letter():
    assert any_case_pattern("echinacee").search("Échinacée".encode()) is None
