from __future__ import annotations

from maple_data_mcp.shared.json_utils import get_or, list_or_empty


def test_list_or_empty_coalesces_absent_and_null_keys():
    assert list_or_empty({}, "items") == []
    assert list_or_empty({"items": None}, "items") == []
    assert list_or_empty({"items": ["a"]}, "items") == ["a"]


def test_get_or_coalesces_absent_and_null_keys():
    assert get_or({}, "count", 0) == 0
    assert get_or({"count": None}, "count", 0) == 0
    assert get_or({"count": 5}, "count", 0) == 5


def test_get_or_preserves_falsy_but_present_values():
    """0 is a real, present value - not a missing one - so it must not
    be coalesced to the default the way an explicit null is."""
    assert get_or({"count": 0}, "count", 99) == 0
