"""Guided-workflow MCP prompts for the boc module."""

from __future__ import annotations

from typing import Annotated, Literal

from fastmcp.prompts import prompt

Lang = Annotated[Literal["en", "fr"], "Language: 'en' or 'fr'"]


@prompt
def find_and_fetch_boc_series(topic: str, lang: Lang = "en") -> str:
    """Guided workflow: find a Bank of Canada Valet series on a topic and
    fetch its recent observations."""
    return (
        f"To find and fetch Bank of Canada data about '{topic}':\n"
        "1. Check docs://boc/well-known-series first - it already lists "
        "the common exchange rate, policy/prime rate, CPI, and commodity "
        "price series names.\n"
        "2. If not covered there, call boc_search_series(query=<topic>) "
        "(or boc_search_groups for a themed family of related series) to "
        "find a candidate series/group name.\n"
        "3. Call boc_get_series(name=...) or boc_get_group(name=...) to "
        "confirm what it measures.\n"
        "4. Call boc_get_observations(series_names=[...], recent=<n>) or "
        "boc_get_group_observations(group_name=..., recent=<n>) for the "
        "latest data, or pass start_date/end_date instead of recent for a "
        "specific historical window."
    )


@prompt
def compare_boc_series(series_names: str, lang: Lang = "en") -> str:
    """Guided workflow: fetch several Bank of Canada series together for
    comparison over the same date range."""
    return (
        f"To compare {series_names} over the same period:\n"
        "1. Call boc_get_observations(series_names=[...], "
        "start_date=..., end_date=...) with all series names in one "
        "call rather than one call per series.\n"
        "2. Check each returned row's `values` keys before assuming every "
        "series appears in every row - series of different publication "
        "frequencies (e.g. daily vs monthly) are not merged into shared "
        "rows. See docs://boc/gotchas for the confirmed details."
    )
