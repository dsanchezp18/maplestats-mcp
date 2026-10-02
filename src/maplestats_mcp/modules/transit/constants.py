"""Agency configuration and limits for the static GTFS module.

Adding an agency is adding an `Agency` here (and its key to
`AgencyKey` in schemas.py; a unit test keeps the two in sync). Every
entry below was checked live on 2026-10-01: the URL answers without a
key, supports HTTP range requests, and the licence page was read. See
docs/ROADMAP.md for what was checked and what was left out.
"""

from __future__ import annotations

from dataclasses import dataclass

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
# Bounds for one streamed file: the largest feed here is TTC at 84 MB
# compressed.
SCAN_MAX_COMPRESSED_BYTES = 150 * 1024 * 1024
SCAN_MAX_UNCOMPRESSED_BYTES = 1024 * 1024 * 1024
# Small tables (stops, routes, trips, calendars) are read whole.
TABLE_MAX_BYTES = 60 * 1024 * 1024
MAX_CONCURRENT_SCANS = 2

LIMIT_DEFAULT = 20
LIMIT_MAX = 500
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


AGENCIES: dict[str, Agency] = {
    "ttc": Agency(
        key="ttc",
        name_en="Toronto Transit Commission (TTC)",
        name_fr="Commission de transport de Toronto (TTC)",
        city="Toronto",
        province="ON",
        timezone="America/Toronto",
        feed_url=(
            "https://ckan0.cf.opendata.inter.prod-toronto.ca/dataset/"
            "b811ead4-6eaf-4adb-8408-d389fb5a069c/resource/"
            "c920e221-7a1c-488b-8c5b-6d8cd4e85eaf/download/completegtfs.zip"
        ),
        source_page=("https://open.toronto.ca/dataset/merged-gtfs-ttc-routes-and-schedules/"),
        licence="Open Government Licence - Toronto",
        licence_url=(
            "https://www.toronto.ca/city-government/data-research-maps/open-data/open-data-licence/"
        ),
        attribution="Contains information licensed under the Open Government Licence - Toronto.",
        update_cadence="Quarterly per the City of Toronto catalogue; refreshed more often in practice.",
        notes_en=(
            "The CKAN record says 'License not specified'; City of Toronto open data "
            "is published under the Open Government Licence - Toronto."
        ),
        notes_fr=(
            "La fiche CKAN indique « licence non précisée »; les données ouvertes de la "
            "Ville de Toronto sont publiées sous la Licence du gouvernement ouvert - Toronto."
        ),
    ),
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
