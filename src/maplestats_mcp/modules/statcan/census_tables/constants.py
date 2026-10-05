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

# Checked 2026-10-02 and again 2026-10-05: every www12.statcan.gc.ca path, the
# table lists and the download links alike, answers scripts with a Cloudflare
# managed challenge (HTTP 403). No StatCan notice about it as of 2026-10-05.
# MapleStats does not try to pass it; it reports the block.
BLOCKED_NOTE = (
    "Statistics Canada's www12 host, which serves these census tables, is currently behind "
    "a Cloudflare bot challenge that scripts cannot pass (a browser can still open the "
    "pages). Other routes to census data: 2021 tables are WDS tables (wds_search_cubes, "
    "98-10-xxxx); the 2021 Census Profile, down to dissemination areas, is on a separate "
    "host that still works (statcan_census_profile_*); an indicator subset of the 2016 "
    "profile (down to health regions) is in WDS tables 17100122 and 17100123; copies of "
    "older tables are on Borealis (borealis_search_ivt)."
)
# Passed through lang.say(), which adds the French no-break spaces.
BLOCKED_NOTE_FR = (
    "Le serveur www12 de Statistique Canada, qui sert ces tableaux du recensement, est "
    "actuellement derrière une vérification de sécurité Cloudflare que les scripts ne peuvent "
    "pas franchir (un navigateur peut encore ouvrir les pages). Autres sources de données du "
    "recensement : les tableaux de 2021 sont des tableaux du WDS (wds_search_cubes, "
    "98-10-xxxx) ; le Profil du recensement de 2021, jusqu'aux aires de diffusion, est sur "
    "un autre serveur qui fonctionne toujours (statcan_census_profile_*) ; un "
    "sous-ensemble d'indicateurs du profil de 2016 (jusqu'aux régions "
    "sociosanitaires) se trouve dans les tableaux 17100122 et 17100123 du WDS ; des copies "
    "des tableaux plus anciens sont dans Borealis (borealis_search_ivt)."
)
