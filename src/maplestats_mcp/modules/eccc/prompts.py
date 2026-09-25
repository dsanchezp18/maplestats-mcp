"""Guided-workflow MCP prompts for the eccc module."""

from __future__ import annotations

from typing import Annotated, Literal

from fastmcp.prompts import prompt

Lang = Annotated[Literal["en", "fr"], "Language: 'en' or 'fr'"]


@prompt
def find_and_query_eccc_collection(topic: str, lang: Lang = "en") -> str:
    """Guided workflow: find an MSC GeoMet collection on a topic and query its data."""
    return (
        f"To find and fetch MSC GeoMet (Environment and Climate Change Canada) data about "
        f"'{topic}':\n"
        "1. Check docs://eccc/well-known-collections first - it already lists the "
        "collection ids that matter most (weather-alerts, swob-realtime, "
        "aqhi-observations-realtime, climate-normals, hydrometric-realtime, "
        "marineweather-realtime, and more) with example property filters for each.\n"
        "2. If not covered there, call eccc_search_collections(query=<topic>) to find a "
        "candidate collection id among the ~100 this server publishes.\n"
        "3. Call eccc_get_collection(collection_id=...) to confirm what it covers and see "
        "its full list of queryable property names - an unrecognized property name is "
        "silently ignored upstream and returns zero rows rather than an error, so check "
        "here before filtering.\n"
        "4. Call eccc_query_items(collection_id=..., filters={...}, bbox=[...], limit=...) "
        "for the actual rows. Prefer filtering by a station id/province/other property or a "
        "narrow bbox over paging through an entire large collection. Try datetime_filter "
        "only after the above - support for it genuinely varies by collection (see "
        "docs://eccc/gotchas)."
    )


@prompt
def eccc_severe_weather_check(location: str, lang: Lang = "en") -> str:
    """Guided workflow: check for active weather alerts affecting a Canadian location."""
    return (
        f"To check for active weather alerts affecting '{location}':\n"
        '1. Call eccc_query_items(collection_id="weather-alerts", '
        f'filters={{"province": <2-letter code for {location}>}}) - or pass a bbox around '
        f"{location} instead if you have its coordinates.\n"
        '2. Read each returned feature\'s `properties.status_en` ("alert" means still '
        'active; "ended" means it has expired), `alert_type`, `risk_colour_en`, '
        "`feature_name_en` (the specific affected area), and `alert_text_en` (the full "
        "alert text).\n"
        "3. weather-alerts does not support datetime_filter (see docs://eccc/gotchas) - "
        "filter by province/bbox only."
    )
