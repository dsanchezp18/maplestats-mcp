"""Constants for every Canadian Socrata (SODA) portal this server covers.

Every portal below was verified live 2026-09-18 to run the identical
cross-domain discovery API, per-domain Views API, and SODA row-query
API, so one client serves all of them. Each keeps its own rate-limit
bucket (`socrata-<key>`).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Portal:
    domain: str
    name_en: str
    name_fr: str
    bilingual_content: bool = False


PORTALS: dict[str, Portal] = {
    "ns": Portal(
        "data.novascotia.ca", "Open Data Nova Scotia", "Données ouvertes de la Nouvelle-Écosse"
    ),
    "nb": Portal(
        "gnb.socrata.com",
        "Government of New Brunswick Open Data",
        "Données ouvertes du gouvernement du Nouveau-Brunswick",
        bilingual_content=True,
    ),
    "calgary": Portal(
        "data.calgary.ca", "City of Calgary Open Data", "Données ouvertes de la Ville de Calgary"
    ),
    "edmonton": Portal(
        "data.edmonton.ca", "City of Edmonton Open Data", "Données ouvertes de la Ville d'Edmonton"
    ),
    "winnipeg": Portal(
        "data.winnipeg.ca", "City of Winnipeg Open Data", "Données ouvertes de la Ville de Winnipeg"
    ),
}

RATE_LIMIT_PER_SECOND = 2.0
RATE_LIMIT_CAPACITY = 5.0

CACHE_TTL_SEARCH_SECONDS = 10 * 60
CACHE_TTL_DATASET_SECONDS = 60 * 60
CACHE_TTL_ROWS_SECONDS = 5 * 60
CACHE_TTL_FACET_SECONDS = 24 * 60 * 60

SEARCH_LIMIT_DEFAULT = 10
SEARCH_LIMIT_MAX = 100
ROWS_LIMIT_DEFAULT = 10
ROWS_LIMIT_MAX = 1000
DESCRIPTION_EXCERPT_LENGTH = 300
