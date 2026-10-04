"""Agency configuration and limits for the static GTFS module.

Adding an agency is adding an `Agency` here (and its key to
`AgencyKey` in schemas.py; a unit test keeps the two in sync). Every
entry below was checked live on 2026-10-01 (VIA Rail, GO/UP Express and
BC Transit on 2026-10-02): the URL answers without a
key, supports HTTP range requests, and the licence page was read. See
docs/ROADMAP.md for what was checked and what was left out.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime

SOURCE = "transit"

RATE_LIMIT_PER_SECOND = 5.0
RATE_LIMIT_CAPACITY = 10.0

# The feeds change a few times a year at most, so a day-old directory is fine; the central directory is cached
# only briefly because a replaced zip invalidates every stored offset.
CACHE_TTL_DIRECTORY_SECONDS = 10 * 60
CACHE_TTL_TABLE_SECONDS = 3 * 60 * 60
CACHE_TTL_SCAN_SECONDS = 60 * 60

# stop_times.txt is streamed in ranges of this size (compressed bytes).
SCAN_CHUNK_BYTES = 4 * 1024 * 1024
# Bounds for one streamed file, with room above the largest feed served live.
SCAN_MAX_COMPRESSED_BYTES = 150 * 1024 * 1024
SCAN_MAX_UNCOMPRESSED_BYTES = 1024 * 1024 * 1024
# A feed from a host without range support (BC Transit) is downloaded whole
# and kept in memory; the largest one seen (Victoria) is 17 MB.
WHOLE_MAX_BYTES = 60 * 1024 * 1024
# Small tables (stops, routes, trips, calendars) are read whole.
TABLE_MAX_BYTES = 60 * 1024 * 1024
MAX_CONCURRENT_SCANS = 2

LIMIT_DEFAULT = 20
LIMIT_MAX = 500
# The national list has some 140 feeds at about 1.5 KB each; a page keeps
# the default response small.
NATIONAL_LIMIT_DEFAULT = 25
NATIONAL_LIMIT_MAX = 200
STOP_FAMILY_MAX = 50


@dataclass(frozen=True)
class Agency:
    key: str
    name_en: str
    name_fr: str
    city: str
    province: str
    timezone: str
    feed_url: str
    source_page: str
    licence: str
    licence_url: str
    attribution: str
    update_cadence: str
    notes_en: str = ""
    notes_fr: str = ""
    # GTFS route_type codes this module will not report schedules for
    # (STM's terms bar building an application on its métro timetables).
    excluded_route_types: tuple[int, ...] = ()
    # False when the host answers neither HEAD nor Range (BC Transit builds each
    # zip on request), so the whole zip is downloaded and held in memory.
    range_requests: bool = True
    # Set only for agencies of the StatCan national database (national.py).
    database: str = "live"
    # "available", "overlaps_live" (served by a live agency instead) or "excluded".
    status: str = "available"
    status_reason: str = ""
    live_agency_key: str | None = None
    window_start: date | None = None
    window_end: date | None = None
    validator_errors: int | None = None
    validator_warnings: int | None = None


# -- StatCan Canadian Public Transit Network Database (23-26-0003) ----------
# Confirmed live 2026-10-02: one 443,590,902-byte zip (HTTP 206, Last-Modified
# 2025-05-07) holding gtfs/<custom_id>/gtfs.zip for 138 feeds, data_sources.csv
# (per-feed licence_url and attribution), validation_summary.csv and a
# 485 MB GeoPackage this module does not read. Each inner zip is a plain GTFS
# feed. www150.statcan.gc.ca/robots.txt sets Crawl-delay 2 for all agents.
NATIONAL_PREFIX = "national:"
NATIONAL_URL = (
    "https://www150.statcan.gc.ca/n1/pub/23-26-0003/2025001/zip/"
    "canadian_public_transit_network_database.zip"
)
NATIONAL_PAGE = "https://www150.statcan.gc.ca/n1/pub/23-26-0003/232600032025001-eng.htm"
NATIONAL_ROOT = "canadian_public_transit_network_database/"
NATIONAL_LICENCE = (
    "Statistics Canada Open Licence / Open Government Licence - Canada for the compilation; "
    "each feed also carries its transit agency's own licence (see licence_url)"
)
NATIONAL_LICENCE_URL = "https://www.statcan.gc.ca/en/reference/licence"
NATIONAL_NOTICE = (
    "Adapted from Statistics Canada, Canadian Public Transit Network Database, 2025. "
    "This does not constitute an endorsement by Statistics Canada of this product."
)
# Last-Modified of the zip, read 2026-10-02 (the release of 2025-01-31 was
# corrected on 2025-05-07). A new release gets a new URL (2025001 in the path).
NATIONAL_AS_OF = datetime(2025, 5, 7, 20, 45, 12, tzinfo=UTC)
NATIONAL_FRESHNESS = (
    "Snapshot compiled by Statistics Canada's Urban Data Lab, version 1.0 released "
    "2025-01-31 (corrected 2025-05-07); not updated since. Each feed's own service "
    "window (coverage) is mostly in 2025, so recent dates fall outside it."
)
# Crawl-delay 2 in robots.txt: one request every two seconds to www150.
NATIONAL_RATE_PER_SECOND = 0.5
NATIONAL_CHUNK_BYTES = 16 * 1024 * 1024
# One nested feed is inflated into memory; the largest feed this module
# serves is 34 MB inflated (OC Transpo, 99 MB, is served live instead).
NATIONAL_MAX_COMPRESSED_BYTES = 60 * 1024 * 1024
NATIONAL_MAX_INFLATED_BYTES = 60 * 1024 * 1024
NATIONAL_CATALOG_TTL_SECONDS = 24 * 60 * 60

# Database id -> live agency key, for the feeds this module already reads
# from the agency's own site. They are listed but not served from the zip.
NATIONAL_OVERLAPS: dict[str, str] = {
    "societe_transport_montreal": "stm",
    "oc_transpo": "oc_transpo",
    "calgary_transit": "calgary",
    "via_rail": "via_rail",
    "go_transit": "go_transit",
    "union_pearson_express": "up_express",
    "bc_transit_victoria": "bct_victoria",
    "bc_transit_kelowna": "bct_kelowna",
    "bc_transit_kamloops": "bct_kamloops",
    "bc_transit_nanaimo": "bct_nanaimo",
    "bc_transit_prince_george": "bct_prince_george",
    "bc_transit_fraser_valley_region": "bct_fraser_valley",
    "bc_transit_north_okanagan": "bct_north_okanagan",
    "bc_transit_comox_valley": "bct_comox_valley",
    "bc_transit_cowichan_valley": "bct_cowichan_valley",
    "bc_transit_campbell_river": "bct_campbell_river",
    "bc_transit_squamish": "bct_squamish",
    "bc_transit_whistler": "bct_whistler",
}
# Feeds left out for their own terms.
NATIONAL_EXCLUDED: dict[str, str] = {
    "translink_vancouver": (
        "TransLink's terms require users to identify themselves to TransLink and let it "
        "impose conditions, which a public server cannot do (the same reason its own feed "
        "is not offered)."
    ),
}
# Province or territory code -> IANA zone, used until the feed's agency.txt is read.
PROVINCE_TIMEZONES: dict[str, str] = {
    "bc": "America/Vancouver",
    "ab": "America/Edmonton",
    "sk": "America/Regina",
    "mb": "America/Winnipeg",
    "on": "America/Toronto",
    "qc": "America/Toronto",
    "nb": "America/Halifax",
    "ns": "America/Halifax",
    "pe": "America/Halifax",
    "nl": "America/St_Johns",
    "yt": "America/Whitehorse",
    "nt": "America/Yellowknife",
    "nu": "America/Iqaluit",
}


def _bc_transit(key: str, system: str, operator_id: int, also: str = "") -> Agency:
    """One BC Transit system. Operator ids are from bctransit.com/open-data."""
    return Agency(
        key=key,
        name_en=f"BC Transit - {system}",
        name_fr=f"BC Transit - {system}",
        city=system,
        province="BC",
        timezone="America/Vancouver",
        feed_url=f"https://bct.tmix.se/Tmix.Cap.TdExport.WebApi/gtfs/?operatorIds={operator_id}",
        source_page="https://www.bctransit.com/open-data",
        licence="BC Transit Open Data Terms of Use (limited, revocable, non-exclusive licence)",
        licence_url="https://www.bctransit.com/open-data/terms-of-use/",
        attribution="Source: BC Transit.",
        update_cadence="Rebuilt by BC Transit on request from its scheduling system.",
        notes_en=(
            f"Operator id {operator_id}. {also} BC Transit's host builds each zip on request "
            "(5 to 25 s) and serves neither HEAD nor byte ranges, so this module downloads the "
            "whole zip and keeps it in memory for ten minutes. The terms require saying BC "
            "Transit is the source and bar use of its domain name and trade-marks. Real-time "
            "feeds exist but are not built (docs/findings/municipal-sources.md)."
        ).replace("  ", " "),
        notes_fr=(
            f"Identifiant d'exploitant {operator_id}. {also} L'hôte de BC Transit construit "
            "chaque zip à la demande (5 à 25 s) et ne prend en charge ni HEAD ni les plages "
            "d'octets; ce module télécharge donc le zip complet et le garde en mémoire dix "
            "minutes. Les conditions exigent d'indiquer BC Transit comme source et interdisent "
            "l'usage de son nom de domaine et de ses marques de commerce."
        ).replace("  ", " "),
        range_requests=False,
    )


AGENCIES: dict[str, Agency] = {
    "stm": Agency(
        key="stm",
        name_en="Societe de transport de Montreal (STM)",
        name_fr="Société de transport de Montréal (STM)",
        city="Montreal",
        province="QC",
        timezone="America/Toronto",
        feed_url="https://www.stm.info/sites/default/files/gtfs/gtfs_stm.zip",
        source_page="https://www.stm.info/en/about/developers",
        licence="Creative Commons Attribution 4.0 (CC BY 4.0)",
        licence_url="https://www.stm.info/en/about/developers/terms-use",
        attribution="Source: Société de transport de Montréal (STM), CC BY 4.0.",
        update_cadence="At each service change (several times a year).",
        notes_en=(
            "STM's terms say métro schedules are for information only and cannot be used "
            "to develop an application, so métro lines (route_type 1) are left out of "
            "route and departure results; bus lines are included. STM forbids use of its "
            "logo without permission. Stop and route names are French."
        ),
        notes_fr=(
            "Les conditions de la STM précisent que les horaires du métro sont donnés à titre "
            "informatif et ne peuvent servir à développer une application; les lignes de métro "
            "(route_type 1) sont donc exclues des résultats de lignes et de passages, mais "
            "les lignes d'autobus sont incluses. La STM interdit l'utilisation de son logo "
            "sans permission. Les noms d'arrêts et de lignes sont en français."
        ),
        excluded_route_types=(1,),
    ),
    "oc_transpo": Agency(
        key="oc_transpo",
        name_en="OC Transpo (Ottawa)",
        name_fr="OC Transpo (Ottawa)",
        city="Ottawa",
        province="ON",
        timezone="America/Toronto",
        feed_url="https://oct-gtfs-emasagcnfmcgeham.z01.azurefd.net/public-access/GTFSExport.zip",
        source_page="https://www.octranspo.com/en/plan-your-trip/travel-tools/developers/",
        licence="City of Ottawa Open Data Licence Version 2.0",
        licence_url=(
            "https://ottawa.ca/en/city-hall/get-know-your-city/open-data"
            "#open-data-licence-version-2-0"
        ),
        attribution="Contains information licensed under the City of Ottawa Open Data Licence v2.0.",
        update_cadence="At each service change; release notes published per update.",
        notes_en=(
            "The City's catalogue still lists www.octranspo.com/files/google_transit.zip, "
            "which returns 404; this module reads the file served from OC Transpo's own "
            "Azure Front Door host, which is open without a key. Only the real-time "
            "feed needs a registered developer account."
        ),
        notes_fr=(
            "Le catalogue de la Ville indique encore www.octranspo.com/files/google_transit.zip, "
            "qui renvoie une erreur 404; ce module lit le fichier servi par l'hôte Azure Front "
            "Door d'OC Transpo, ouvert sans clé. Seul le flux temps réel exige un compte."
        ),
    ),
    "calgary": Agency(
        key="calgary",
        name_en="Calgary Transit",
        name_fr="Calgary Transit",
        city="Calgary",
        province="AB",
        timezone="America/Edmonton",
        feed_url="https://data.calgary.ca/download/npk7-z3bj/application%2Fzip",
        source_page="https://data.calgary.ca/d/Calgary-Transit-Scheduling-Data/npk7-z3bj",
        licence="Open Government Licence - City of Calgary (Open Calgary Terms of Use), v2.1",
        licence_url="https://data.calgary.ca/stories/s/u45n-7awa/",
        attribution="Contains information licensed under the Open Government Licence - City of Calgary.",
        update_cadence="Irregular (per the Open Calgary record); follows Calgary Transit service changes.",
    ),
    "via_rail": Agency(
        key="via_rail",
        name_en="VIA Rail Canada",
        name_fr="VIA Rail Canada",
        city="Canada-wide (intercity)",
        province="CA",
        timezone="America/Toronto",
        feed_url="https://www.viarail.ca/sites/all/files/gtfs/viarail.zip",
        source_page="https://www.viarail.ca/en/developer-resources",
        licence="Open Government Licence - Canada, version 2.0",
        licence_url="https://open.canada.ca/en/open-government-licence-canada",
        attribution="Contains information licensed under the Open Government Licence - Canada.",
        update_cadence="At each timetable change (last updated 2026-08-17 when checked).",
        notes_en=(
            "Intercity trains across Canada. Times are local to each stop (stop_timezone "
            "in stops.txt), not to the agency's America/Toronto zone. The feed is encoded "
            "in Windows-1252, which this module decodes."
        ),
        notes_fr=(
            "Trains interurbains partout au Canada. Les heures sont locales à chaque arrêt "
            "(stop_timezone dans stops.txt), et non à la zone America/Toronto de l'organisme. "
            "Le flux est encodé en Windows-1252, que ce module décode."
        ),
    ),
    "go_transit": Agency(
        key="go_transit",
        name_en="GO Transit (Metrolinx)",
        name_fr="GO Transit (Metrolinx)",
        city="Greater Toronto and Hamilton Area",
        province="ON",
        timezone="America/Toronto",
        feed_url="https://assets.metrolinx.com/raw/upload/Documents/Metrolinx/Open%20Data/GO-GTFS.zip",
        source_page="https://www.gotransit.com/en/information-resources/software-developers",
        licence="Open Government Licence - Ontario - Metrolinx",
        licence_url=(
            "https://assets.metrolinx.com/image/upload/v1663237565/Documents/Metrolinx/"
            "Open-Government-Licence-Ontario-Metrolinx.pdf"
        ),
        attribution="Contains information licensed under the Open Government Licence - Ontario - Metrolinx.",
        update_cadence="At each service change; the feed checked 2026-10-02 was published 2026-10-01.",
        notes_en="GO train and GO bus services. UP Express has its own feed (up_express).",
        notes_fr="Services de train et d'autobus GO. L'UP Express a son propre flux (up_express).",
    ),
    "up_express": Agency(
        key="up_express",
        name_en="UP Express (Metrolinx)",
        name_fr="UP Express (Metrolinx)",
        city="Toronto",
        province="ON",
        timezone="America/Toronto",
        feed_url="https://assets.metrolinx.com/raw/upload/Documents/Metrolinx/Open%20Data/UP-GTFS.zip",
        source_page="https://www.gotransit.com/en/information-resources/software-developers",
        licence="Open Government Licence - Ontario - Metrolinx",
        licence_url=(
            "https://assets.metrolinx.com/image/upload/v1663237565/Documents/Metrolinx/"
            "Open-Government-Licence-Ontario-Metrolinx.pdf"
        ),
        attribution="Contains information licensed under the Open Government Licence - Ontario - Metrolinx.",
        update_cadence="At each service change.",
        notes_en="Union Station to Pearson Airport train.",
        notes_fr="Train entre la gare Union et l'aéroport Pearson.",
    ),
    "bct_victoria": _bc_transit("bct_victoria", "Victoria", 48),
    "bct_kelowna": _bc_transit("bct_kelowna", "Kelowna", 47),
    "bct_kamloops": _bc_transit("bct_kamloops", "Kamloops", 46),
    "bct_nanaimo": _bc_transit("bct_nanaimo", "Nanaimo", 41),
    "bct_prince_george": _bc_transit(
        "bct_prince_george", "Prince George", 22, "Also covers Bulkley-Nechako."
    ),
    "bct_fraser_valley": _bc_transit(
        "bct_fraser_valley",
        "Fraser Valley (Chilliwack)",
        13,
        "Also covers Agassiz-Harrison, Central Fraser Valley and Hope.",
    ),
    "bct_north_okanagan": _bc_transit(
        "bct_north_okanagan", "North Okanagan (Vernon)", 14, "Also covers Shuswap."
    ),
    "bct_comox_valley": _bc_transit("bct_comox_valley", "Comox Valley", 45),
    "bct_cowichan_valley": _bc_transit("bct_cowichan_valley", "Cowichan Valley", 10),
    "bct_campbell_river": _bc_transit("bct_campbell_river", "Campbell River", 12),
    "bct_squamish": _bc_transit("bct_squamish", "Squamish", 43),
    "bct_whistler": _bc_transit("bct_whistler", "Whistler", 44),
}

# GTFS route_type values (basic and the common extended codes).
ROUTE_TYPES: dict[int, str] = {
    0: "tram / streetcar / light rail",
    1: "subway / metro",
    2: "rail",
    3: "bus",
    4: "ferry",
    5: "cable tram",
    6: "aerial lift",
    7: "funicular",
    11: "trolleybus",
    12: "monorail",
}
