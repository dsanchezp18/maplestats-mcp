"""Constants for StatCan's extra .Stat Suite SDMX spaces (CCEI and stcshared).

Verified live 2026-10-02 (the Data Explorer CONFIG of de-ccei.statcan.gc.ca
and de-rural.statcan.gc.ca names these bases):

- https://api.statcan.gc.ca/ccei-ccie/sdmx/rest: the Canadian Centre for Energy
  Information space, 245 dataflows (119 Statistics Canada table mirrors under
  agency STC, 114 under CA1.CCEI, 8 ECCC/NRCan flows under CCEI, 4 others).
- https://api.statcan.gc.ca/stcshared-partagestc/sdmx/rest: the shared space,
  238 dataflows (CITH 98, QOL 60, PCEIP 44, MEA 18, RURAL 13, QOL.ECCC 3,
  QOL.ISC 1, CA1 1).

Both speak SDMX REST 1.x: structures as SDMX-JSON 1.0 (the v2 structure
media types answer 406), data as SDMX-CSV 2.0 (SDMX-JSON 2.0 also works, CSV
is simpler to parse). Every dataflow carries a NonProductionDataflow
annotation. Full-text and facet search is a separate service,
sdmx-sfs.statcan.gc.ca, one tenant per explorer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

SpaceKey = Literal["ccei", "stcshared"]
TenantKey = Literal["ccei", "rural", "cith", "pceip"]


@dataclass(frozen=True)
class Space:
    key: str
    name_en: str
    name_fr: str
    base_url: str
    # Short names of the search tenants (see SEARCH_TENANTS) covering this space.
    tenants: tuple[str, ...]


SPACES: dict[str, Space] = {
    "ccei": Space(
        key="ccei",
        name_en="Canadian Centre for Energy Information (CCEI)",
        name_fr="Centre canadien d'information sur l'énergie (CCIE)",
        base_url="https://api.statcan.gc.ca/ccei-ccie/sdmx/rest",
        tenants=("ccei",),
    ),
    "stcshared": Space(
        key="stcshared",
        name_en="Statistics Canada shared space (rural, CITH, QOL, PCEIP, MEA)",
        name_fr="Espace partagé de Statistique Canada (rural, CITH, QOL, PCEIP, MEA)",
        base_url="https://api.statcan.gc.ca/stcshared-partagestc/sdmx/rest",
        tenants=("rural", "cith", "pceip"),
    ),
}

# Search tenants confirmed live 2026-10-02 (flows indexed: ccei 122, rural 10,
# cith 98, pceip 43). The QOL and MEA flows of stcshared are in no search
# tenant: only sdmx_space_list_flows finds them.
SEARCH_TENANTS: dict[str, str] = {
    "ccei": "statcan-ccei-public",
    "rural": "statcan-stcshared-rural-public",
    "cith": "statcan-stcshared-cith-public",
    "pceip": "statcan-stcshared-pceip-public",
}
SEARCH_URL = "https://sdmx-sfs.statcan.gc.ca/api/search"

# api.statcan.gc.ca and the search host each get their own bucket.
RATE_LIMIT_SOURCE = "statcan-sdmx-spaces"
RATE_LIMIT_SEARCH_SOURCE = "statcan-sdmx-search"
RATE_LIMIT_PER_SECOND = 10.0
RATE_LIMIT_CAPACITY = 10.0

# Media types (the server lists them in its 406 body).
ACCEPT_STRUCTURE = "application/vnd.sdmx.structure+json; charset=utf-8; version=1.0"
ACCEPT_DATA = "application/vnd.sdmx.data+csv; charset=utf-8; version=2.0.0"

# A data request that selects a whole large flow times out (HTTP 504, or no
# answer within 100 s with lastNObservations=1 on a 451,360-observation flow).
READ_TIMEOUT_SECONDS = 45.0
# Keys that select nothing (all, or only wildcards) are refused above this many
# observations; the flow's size comes from its availability constraint.
MAX_UNFILTERED_OBSERVATIONS = 20_000

# Data limits.
DEFAULT_LAST_N = 12
MAX_ROWS = 500  # newest observations kept per series
MAX_SERIES = 200
MAX_LAST_N = 5_000

# Listing and structure browsing.
DEFAULT_LIST_LIMIT = 50
MAX_LIST_LIMIT = 250
DEFAULT_CODE_LIMIT = 100
MAX_CODE_LIMIT = 1_000
DESCRIPTION_CHARS = 400

# Search: the service returns 0.7 to 1.6 MB whatever `rows` is (facets and
# highlighting cannot be switched off), so rows is kept small.
DEFAULT_SEARCH_LIMIT = 10
MAX_SEARCH_ROWS = 50
MAX_FACETS = 6
MAX_FACET_VALUES = 8

CACHE_TTL_SECONDS = 24 * 60 * 60

PERIOD_PATTERN = r"^\d{4}(-(\d{2}(-\d{2})?|[QSWAMB]\d{1,2}))?$"
ID_PATTERN = r"^[A-Za-z0-9_.\-]+$"
KEY_PATTERN = r"^[A-Za-z0-9_+.\-]*$"
