"""Guided-workflow MCP prompts for the cmhc module."""

from __future__ import annotations

from typing import Annotated, Literal

from fastmcp.prompts import prompt

Lang = Annotated[Literal["en", "fr"], "Language: 'en' or 'fr'"]


@prompt
def find_and_query_cmhc_table(topic: str, lang: Lang = "en") -> str:
    """Guided workflow: find a CMHC HMIP category on a topic and fetch its data."""
    return (
        f"To find and fetch CMHC housing data about '{topic}':\n"
        "1. Check docs://cmhc/well-known-categories first - it already lists the "
        "common categories (Primary Rental Market, New Housing Construction, "
        "Secondary Rental Market, Seniors' Rental Housing, Population/Households, "
        "Core Housing Need) with their exact spelling.\n"
        "2. If not covered there, call cmhc_list_categories(lang=...) to see every "
        "category currently available - category names are language-dependent "
        "strings, so use the same lang for every following call.\n"
        "3. Call cmhc_get_table_options(category_level_1=..., category_level_2=...) "
        "to see the valid column_field/row_field breakdowns for that category - "
        "e.g. 'Bedroom Type' as the column with 'Historical Time Periods' as the "
        "row for a national time series, or 'Provinces' as the row for a current "
        "cross-tabulation by province.\n"
        "4. Call cmhc_get_table_data(category_level_1=..., category_level_2=..., "
        "column_field=..., row_field=...) for the actual data. Default geography "
        "is Canada-wide; call cmhc_list_provinces first and pass "
        "geography_type='Province', geography_id=<id> for one province instead.\n"
        "5. Check each cell's `value` for null before using it - it means the "
        "figure was suppressed or not applicable; the reason is in `flag`. See "
        "docs://cmhc/gotchas for the full reliability-flag legend."
    )
