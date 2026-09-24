"""Constants for the 2006-2016 census data tables (www12.statcan.gc.ca).

Confirmed live 2026-09-24. Each release has an index page whose
Lp-eng.cfm links carry THEME ids; a theme's list page with GRP=0
("Ungroup related products") lists every table as one row (catalogue
number, full title, formats), 20 rows per page, paged with StartRow.
Each table has three direct downloads, all ZIPs behind a 302 redirect:
CompDataDownload.cfm?PID=..&OFT=CSV (CSV), OpenDataDownload.cfm?PID=..
(SDMX) and Download.cfm?PID=.. (Beyond 20/20 IVT). The 2021 census data
tables are ordinary NDM tables (98-10-xxxx) and are served by wds_.
"""

from __future__ import annotations

from dataclasses import dataclass

HOST = "https://www12.statcan.gc.ca"


@dataclass(frozen=True)
class Release:
    label: str
    # Directory holding index-eng.cfm; theme URLs are taken from that
    # page's own links, since their other parameters differ by release.
    path: str


RELEASES: dict[str, Release] = {
    "2016": Release("2016 Census", "/census-recensement/2016/dp-pd/dt-td/"),
    "2011": Release("2011 Census", "/census-recensement/2011/dp-pd/tbt-tt/"),
    "2011_nhs": Release("2011 National Household Survey", "/nhs-enm/2011/dp-pd/dt-td/"),
    "2006": Release("2006 Census", "/census-recensement/2006/dp-pd/tbt/"),
}

RATE_LIMIT_SOURCE = "statcan-census-tables"
RATE_LIMIT_PER_SECOND = 3.0
RATE_LIMIT_CAPACITY = 6.0

CATALOGUE_TTL_SECONDS = 7 * 24 * 60 * 60
MAX_PAGES_PER_THEME = 60
SEARCH_LIMIT_DEFAULT = 25
SEARCH_LIMIT_MAX = 200
