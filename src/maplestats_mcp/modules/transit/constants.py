"""Agency configuration and limits for the static GTFS module.

Adding an agency is adding an `Agency` here (and its key to
`AgencyKey` in schemas.py; a unit test keeps the two in sync). Every
entry below was checked live on 2026-10-01 (VIA Rail, GO/UP Express and
BC Transit on 2026-10-02, the Quebec regional feeds on 2026-10-03): the URL answers without a
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
    # French text for the fields above; empty means the English text stands
    # (a credit line a licence fixes in English, a proper name).
    city_fr: str = ""
    licence_fr: str = ""
    attribution_fr: str = ""
    update_cadence_fr: str = ""
    status_reason_fr: str = ""
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
# feed.
NATIONAL_PREFIX = "national:"
NATIONAL_URL = (
    "https://www150.statcan.gc.ca/n1/pub/23-26-0003/2025001/zip/"
    "canadian_public_transit_network_database.zip"
)
NATIONAL_PAGE = "https://www150.statcan.gc.ca/n1/pub/23-26-0003/232600032025001-eng.htm"
NATIONAL_PAGE_FR = "https://www150.statcan.gc.ca/n1/pub/23-26-0003/232600032025001-fra.htm"
NATIONAL_ROOT = "canadian_public_transit_network_database/"
NATIONAL_LICENCE = (
    "Statistics Canada Open Licence / Open Government Licence - Canada for the compilation; "
    "each feed also carries its transit agency's own licence (see licence_url)"
)
NATIONAL_NAME_FR = "Base de données ouvertes sur les réseaux de transport en commun canadiens"
NATIONAL_LICENCE_FR = (
    "Licence ouverte de Statistique Canada / Licence du gouvernement ouvert – Canada pour la "
    "compilation; chaque flux porte aussi la licence de son organisme de transport (voir "
    "licence_url)"
)
NATIONAL_LICENCE_URL = "https://www.statcan.gc.ca/en/reference/licence"
NATIONAL_NOTICE = (
    "Adapted from Statistics Canada, Canadian Public Transit Network Database, 2025. "
    "This does not constitute an endorsement by Statistics Canada of this product."
)
NATIONAL_NOTICE_FR = (
    f"Adapté de Statistique Canada, {NATIONAL_NAME_FR}, 2025. Ceci ne constitue pas une "
    "approbation de ce produit par Statistique Canada."
)
# Last-Modified of the zip, read 2026-10-02 (the release of 2025-01-31 was
# corrected on 2025-05-07). A new release gets a new URL (2025001 in the path).
NATIONAL_AS_OF = datetime(2025, 5, 7, 20, 45, 12, tzinfo=UTC)
NATIONAL_FRESHNESS = (
    "Snapshot compiled by Statistics Canada's Urban Data Lab, version 1.0 released "
    "2025-01-31 (corrected 2025-05-07); not updated since. Each feed's own service "
    "window (coverage) is mostly in 2025, so recent dates fall outside it."
)
NATIONAL_FRESHNESS_FR = (
    "Instantané compilé par Statistique Canada, version 1.0 publiée le 2025-01-31 (corrigée "
    "le 2025-05-07) ; aucune mise à jour depuis. La période de service (couverture) de chaque "
    "flux se situe surtout en 2025 : les dates récentes en sont donc exclues."
)
# One request every two seconds to www150.
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
    # Quebec feeds read live since 2026-10-03: the agencies' current files are
    # newer than the 2025 snapshot (exo's sectors run to 2027-01-03).
    "exo": "exo_trains",
    "exo_chambly_richelieu_carignan": "exo_chambly_richelieu_carignan",
    "exo_laurentides": "exo_laurentides",
    "exo_la_presqu'ile": "exo_la_presquile",
    "exo_sorel_varennes": "exo_sorel_varennes",
    "exo_sud_ouest": "exo_sud_ouest",
    "exo_richelieu": "exo_vallee_du_richelieu",
    "exo_l'assomption": "exo_lassomption",
    "exo_terrebonne_mascouche": "exo_terrebonne_mascouche",
    "exo_sainte_julie": "exo_sainte_julie",
    "exo_le_richelain_roussillon": "exo_le_richelain_roussillon",
    "reseau_transport_capitale": "rtc_quebec",
    "societe_transport_laval": "stl_laval",
    "societe_de_transport_de_trois_rivieres": "sttr_trois_rivieres",
    "societe_transport_rimouski": "rimouski",
    "ville_de_rouyn_noranda": "rouyn_noranda",
}
# Feeds left out for their own terms.
NATIONAL_EXCLUDED: dict[str, str] = {
    "translink_vancouver": (
        "TransLink's terms require users to identify themselves to TransLink and let it "
        "impose conditions, which a public server cannot do (the same reason its own feed "
        "is not offered)."
    ),
}
NATIONAL_EXCLUDED_FR: dict[str, str] = {
    "translink_vancouver": (
        "Les conditions de TransLink exigent que les utilisateurs s'identifient auprès de "
        "TransLink et lui permettent d'imposer des conditions, ce qu'un serveur public ne peut "
        "pas faire (la même raison pour laquelle son propre flux n'est pas offert)."
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
        licence_fr=(
            "Conditions d'utilisation des données ouvertes de BC Transit (licence limitée, "
            "révocable et non exclusive)"
        ),
        attribution_fr="Source : BC Transit.",
        update_cadence_fr=(
            "Reconstruit par BC Transit à chaque demande, à partir de son système de "
            "planification des horaires."
        ),
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
            "d'octets ; ce module télécharge donc le zip complet et le garde en mémoire dix "
            "minutes. Les conditions exigent d'indiquer BC Transit comme source et interdisent "
            "l'usage de son nom de domaine et de ses marques de commerce."
        ).replace("  ", " "),
        range_requests=False,
    )


QC_CC_BY = "Creative Commons Attribution 4.0 (CC BY 4.0), per the Données Québec record"
QC_CC_BY_FR = "Creative Commons Attribution 4.0 (CC BY 4.0), selon la fiche de Données Québec"
QC_LICENCE_URL = "https://www.donneesquebec.ca/licence/#cc-by"
_DQ = "https://www.donneesquebec.ca/recherche/dataset/"


def _exo(
    key: str, code: str, sector_en: str, sector_fr: str, city: str, dataset: str | None
) -> Agency:
    """One exo GTFS feed (exo.quebec/fr/a-propos/donnees-ouvertes, CC BY).

    `dataset` is the Données Québec record; Le Richelain/Roussillon has none,
    so exo's own open data page stands in.
    """
    return Agency(
        key=key,
        name_en=f"exo - {sector_en}",
        name_fr=f"exo - {sector_fr}",
        city=city,
        province="QC",
        timezone="America/Toronto",
        feed_url=(
            "https://exo.quebec/uploads/ressources-telechargeables/a-propos/donnees-ouvertes/"
            f"{code}/google_transit.zip"
        ),
        source_page=f"{_DQ}{dataset}"
        if dataset
        else "https://exo.quebec/fr/a-propos/donnees-ouvertes",
        licence=QC_CC_BY,
        licence_url=QC_LICENCE_URL,
        attribution="Source: exo (Réseau de transport métropolitain), CC BY 4.0.",
        update_cadence="At each service change; exo's sector feeds checked 2026-10-03 run to 2027-01-03.",
        city_fr="Grand Montréal" if city == "Greater Montreal" else "",
        licence_fr=QC_CC_BY_FR,
        attribution_fr="Source : exo (Réseau de transport métropolitain), CC BY 4.0.",
        update_cadence_fr=(
            "À chaque changement de service ; les flux des secteurs d'exo vérifiés le 2026-10-03 "
            "vont jusqu'au 2027-01-03."
        ),
        notes_en=(
            f"exo publishes one feed per bus sector and one for its trains (code {code}). Names "
            "are French. Some routes use GTFS extended route_type 1501 (on-demand taxi)."
        ),
        notes_fr=(
            f"exo publie un flux par secteur d'autobus et un pour ses trains (code {code}). "
            "Certaines lignes utilisent le route_type étendu 1501 (taxi collectif)."
        ),
    )


def _quebec(
    key: str,
    name: str,
    city: str,
    feed_url: str,
    dataset: str,
    attribution: str,
    update_cadence: str,
    notes_en: str = "",
    notes_fr: str = "",
    *,
    licence: str = QC_CC_BY,
    licence_url: str = QC_LICENCE_URL,
    range_requests: bool = True,
    city_fr: str = "",
    licence_fr: str = QC_CC_BY_FR,
    attribution_fr: str = "",
    update_cadence_fr: str = "",
) -> Agency:
    """A Quebec feed listed on Données Québec.

    An English credit line written "Source: ..." reads "Source : ..." in French
    unless `attribution_fr` says otherwise.
    """
    if not attribution_fr and attribution.startswith("Source: "):
        attribution_fr = "Source : " + attribution.removeprefix("Source: ")
    return Agency(
        key=key,
        name_en=name,
        name_fr=name,
        city=city,
        province="QC",
        timezone="America/Toronto",
        feed_url=feed_url,
        source_page=f"{_DQ}{dataset}",
        licence=licence,
        licence_url=licence_url,
        attribution=attribution,
        update_cadence=update_cadence,
        notes_en=notes_en,
        notes_fr=notes_fr,
        range_requests=range_requests,
        city_fr=city_fr,
        licence_fr=licence_fr,
        attribution_fr=attribution_fr,
        update_cadence_fr=update_cadence_fr,
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
        city_fr="Montréal",
        licence_fr="Licence Creative Commons Attribution 4.0 (CC BY 4.0)",
        attribution_fr="Source : Société de transport de Montréal (STM), CC BY 4.0.",
        update_cadence_fr="À chaque changement de service (plusieurs fois par année).",
        notes_en=(
            "STM's terms say métro schedules are for information only and cannot be used "
            "to develop an application, so métro lines (route_type 1) are left out of "
            "route and departure results; bus lines are included. STM forbids use of its "
            "logo without permission. Stop and route names are French."
        ),
        notes_fr=(
            "Les conditions de la STM précisent que les horaires du métro sont donnés à titre "
            "informatif et ne peuvent servir à développer une application ; les lignes de métro "
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
        licence_fr="Licence de données ouvertes de la Ville d'Ottawa, version 2.0",
        update_cadence_fr=(
            "À chaque changement de service ; des notes de version accompagnent chaque mise à jour."
        ),
        notes_en=(
            "The City's catalogue still lists www.octranspo.com/files/google_transit.zip, "
            "which returns 404; this module reads the file served from OC Transpo's own "
            "Azure Front Door host, which is open without a key. Only the real-time "
            "feed needs a registered developer account."
        ),
        notes_fr=(
            "Le catalogue de la Ville indique encore www.octranspo.com/files/google_transit.zip, "
            "qui renvoie une erreur 404 ; ce module lit le fichier servi par l'hôte Azure Front "
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
        # The City of Calgary publishes its licence and credit line in English only.
        licence_fr=(
            "Licence du gouvernement ouvert de la Ville de Calgary (Open Government Licence - "
            "City of Calgary, conditions d'utilisation d'Open Calgary), version 2.1"
        ),
        update_cadence_fr=(
            "Irrégulière (selon la fiche d'Open Calgary) ; suit les changements de service de "
            "Calgary Transit."
        ),
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
        city_fr="Partout au Canada (trains interurbains)",
        licence_fr="Licence du gouvernement ouvert – Canada, version 2.0",
        attribution_fr=(
            "Contient des informations visées par la Licence du gouvernement ouvert – Canada."
        ),
        update_cadence_fr=(
            "À chaque changement d'horaire (dernière mise à jour le 2026-08-17 lors de la "
            "vérification)."
        ),
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
        city_fr="Région du grand Toronto et de Hamilton",
        licence_fr="Licence du gouvernement ouvert – Ontario – Metrolinx",
        update_cadence_fr=(
            "À chaque changement de service ; le flux vérifié le 2026-10-02 avait été publié le "
            "2026-10-01."
        ),
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
        licence_fr="Licence du gouvernement ouvert – Ontario – Metrolinx",
        update_cadence_fr="À chaque changement de service.",
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
    # -- Quebec regional and ferry feeds (Données Québec, checked 2026-10-03) --
    "exo_trains": _exo(
        "exo_trains",
        "trains",
        "commuter trains (exo1 to exo6)",
        "trains de banlieue (exo1 à exo6)",
        "Greater Montreal",
        "exo-trains-gtfs",
    ),
    "exo_chambly_richelieu_carignan": _exo(
        "exo_chambly_richelieu_carignan",
        "citcrc",
        "Chambly-Richelieu-Carignan buses",
        "autobus Chambly-Richelieu-Carignan",
        "Chambly",
        "chambly-richelieu-carignan-gtfs",
    ),
    "exo_laurentides": _exo(
        "exo_laurentides",
        "citla",
        "Laurentides buses",
        "autobus Laurentides",
        "Saint-Jérôme",
        "laurentides-gtfs",
    ),
    "exo_la_presquile": _exo(
        "exo_la_presquile",
        "citpi",
        "La Presqu'île buses",
        "autobus La Presqu'île",
        "Vaudreuil-Dorion",
        "presquile-gtfs",
    ),
    "exo_sorel_varennes": _exo(
        "exo_sorel_varennes",
        "citsv",
        "Sorel-Varennes buses",
        "autobus Sorel-Varennes",
        "Varennes",
        "sorel-varennes-gtfs",
    ),
    "exo_sud_ouest": _exo(
        "exo_sud_ouest",
        "citso",
        "Sud-Ouest buses",
        "autobus Sud-Ouest",
        "Châteauguay",
        "sud-ouest-gtfs",
    ),
    "exo_vallee_du_richelieu": _exo(
        "exo_vallee_du_richelieu",
        "citvr",
        "Vallée du Richelieu buses",
        "autobus Vallée du Richelieu",
        "Beloeil",
        "vallee-du-richelieu-gtfs",
    ),
    "exo_lassomption": _exo(
        "exo_lassomption",
        "mrclasso",
        "L'Assomption buses",
        "autobus L'Assomption",
        "Repentigny",
        "lassomption-gtfs",
    ),
    "exo_terrebonne_mascouche": _exo(
        "exo_terrebonne_mascouche",
        "mrclm",
        "Terrebonne-Mascouche buses",
        "autobus Terrebonne-Mascouche",
        "Terrebonne",
        "terrebonne-mascouche-gtfs",
    ),
    "exo_sainte_julie": _exo(
        "exo_sainte_julie",
        "omitsju",
        "Sainte-Julie buses",
        "autobus Sainte-Julie",
        "Sainte-Julie",
        "sainte-julie-gtfs",
    ),
    "exo_le_richelain_roussillon": _exo(
        "exo_le_richelain_roussillon",
        "lrrs",
        "Le Richelain and Roussillon buses",
        "autobus Le Richelain et Roussillon",
        "La Prairie",
        None,
    ),
    "rtc_quebec": _quebec(
        "rtc_quebec",
        "Réseau de transport de la Capitale (RTC)",
        "Québec City",
        "https://cdn.rtcquebec.ca/Site_Internet/DonneesOuvertes/googletransit.zip",
        "rtc-gtfs-arrets-et-les-parcours",
        (
            "Application, produit ou service, intégrant les Informations publiques du Réseau de "
            "transport de la Capitale, mises à jour le [date of the feed]."
        ),
        "At each service change; the zip checked 2026-10-03 was dated 2026-10-02.",
        (
            "The RTC's own terms (rtcquebec.ca/donnees-ouvertes) allow personal and commercial "
            "use, require the credit line above with the feed's update date, and bar altering "
            "the data in a way that misleads. The zip is 32 MB."
        ),
        (
            "Les conditions du RTC (rtcquebec.ca/donnees-ouvertes) permettent l'usage personnel "
            "et commercial, exigent la mention ci-dessus avec la date de mise à jour et "
            "interdisent d'altérer les données de façon trompeuse. Le zip fait 32 Mo."
        ),
        licence=(
            "RTC open data terms of use (Creative Commons Attribution 4.0 on its Données Québec "
            "record)"
        ),
        licence_url="https://www.rtcquebec.ca/donnees-ouvertes",
        city_fr="Québec",
        licence_fr=(
            "Conditions d'utilisation des données ouvertes du RTC (Creative Commons Attribution "
            "4.0 sur sa fiche de Données Québec)"
        ),
        update_cadence_fr=(
            "À chaque changement de service ; le zip vérifié le 2026-10-03 était daté du 2026-10-02."
        ),
    ),
    "stl_laval": _quebec(
        "stl_laval",
        "Société de transport de Laval (STL)",
        "Laval",
        "https://stlaval.ca/datas/opendata/GTF_STL.zip",
        "https-www-stlaval-ca-datas-opendata-gtf_stl-zip",
        "Source: Société de transport de Laval (STL).",
        "Quarterly per the Données Québec record; the feed checked 2026-10-03 runs to 2026-10-30.",
        (
            "The Données Québec record says CC BY 4.0, but the STL's own GTFS terms grant a "
            "non-exclusive, limited and revocable licence, bar any commercial or "
            "quasi-commercial use without the STL's prior written permission, and bar use of its "
            "marks. Treat the data as non-commercial."
        ),
        (
            "La fiche de Données Québec indique CC BY 4.0, mais les conditions GTFS de la STL "
            "accordent un droit non exclusif, limité et révocable, interdisent toute utilisation "
            "commerciale ou quasi commerciale sans l'autorisation écrite préalable de la STL et "
            "interdisent l'usage de ses marques. Usage non commercial seulement."
        ),
        licence=(
            "STL GTFS terms of use: limited, revocable licence; no commercial use without the "
            "STL's written permission (CC BY 4.0 on its Données Québec record)"
        ),
        licence_url="https://stlaval.ca/affaires/donnees-ouvertes",
        licence_fr=(
            "Conditions d'utilisation GTFS de la STL : licence limitée et révocable ; aucun usage "
            "commercial sans l'autorisation écrite de la STL (CC BY 4.0 sur sa fiche de Données "
            "Québec)"
        ),
        update_cadence_fr=(
            "Trimestrielle selon la fiche de Données Québec ; le flux vérifié le 2026-10-03 va "
            "jusqu'au 2026-10-30."
        ),
    ),
    "sts_sherbrooke": _quebec(
        "sts_sherbrooke",
        "Société de transport de Sherbrooke (STS)",
        "Sherbrooke",
        "https://gtfs.sts.qc.ca:8443/gtfs/client/GTFS_clients.zip",
        "transport-sts",
        "Source: Société de transport de Sherbrooke (STS), Données Québec, CC BY 4.0.",
        "At each service change; the feed checked 2026-10-03 runs to 2026-12-20.",
        (
            "The Données Québec record points to a directory listing; this module reads the zip "
            "in it (GTFS_clients.zip). The feed has no feed_info.txt."
        ),
        (
            "La fiche de Données Québec renvoie à un répertoire ; ce module lit le zip qu'il "
            "contient (GTFS_clients.zip). Le flux n'a pas de feed_info.txt."
        ),
        update_cadence_fr=(
            "À chaque changement de service ; le flux vérifié le 2026-10-03 va jusqu'au 2026-12-20."
        ),
    ),
    "stq_ferries": _quebec(
        "stq_ferries",
        "Société des traversiers du Québec (STQ)",
        "Quebec-wide (ferries)",
        "https://gtfs.traversiers.com/api/gtfs.zip",
        "stq-gtfs-pour-les-traverses",
        "Source: Société des traversiers du Québec, Données Québec, CC BY 4.0.",
        "Daily per the Données Québec record.",
        (
            "Ferry crossings (route_type 4), for example Québec-Lévis and Sorel-Tracy-"
            "Saint-Ignace-de-Loyola. The host serves no byte ranges, so the 71 KB zip is "
            "downloaded whole."
        ),
        (
            "Traverses (route_type 4), par exemple Québec-Lévis et Sorel-Tracy-Saint-Ignace-de-"
            "Loyola. L'hôte ne sert pas de plages d'octets ; le zip de 71 Ko est téléchargé en "
            "entier."
        ),
        range_requests=False,
        city_fr="Partout au Québec (traversiers)",
        update_cadence_fr="Quotidienne selon la fiche de Données Québec.",
    ),
    "sttr_trois_rivieres": _quebec(
        "sttr_trois_rivieres",
        "Société de transport de Trois-Rivières (STTR)",
        "Trois-Rivières",
        f"{_DQ}a2d3c9de-4045-41e3-b2ea-5bb64bd8c50f/resource/"
        "71d94f75-5a36-4789-b581-a21d49dcd5f5/download/gtfs.zip",
        "gtsf",
        "Source: Société de transport de Trois-Rivières (STTR), Données Québec, CC BY 4.0.",
        "Each season; the feed checked 2026-10-03 (autumn 2026) runs to 2026-12-26.",
        (
            "The STTR renames the file each season; Données Québec serves the resource by its id "
            "whatever the file name, so this URL keeps working."
        ),
        (
            "La STTR renomme le fichier à chaque saison ; Données Québec sert la ressource par son "
            "identifiant quel que soit le nom du fichier."
        ),
        update_cadence_fr=(
            "À chaque saison ; le flux vérifié le 2026-10-03 (automne 2026) va jusqu'au 2026-12-26."
        ),
    ),
    "rimouski": _quebec(
        "rimouski",
        "Société des transports de Rimouski (Citébus)",
        "Rimouski",
        f"{_DQ}d2d92b84-4361-42f0-81eb-3c395bc54597/resource/"
        "bd4021ba-d3ae-4d3b-b8fd-016405166761/download/gtfsrimouskibus.zip",
        "transport-collectif",
        "Source: Ville de Rimouski, Données Québec, CC BY 4.0.",
        "As needed; the feed checked 2026-10-03 runs to 2027-02-14.",
        "Published by the Ville de Rimouski. The feed has no feed_info.txt.",
        "Publié par la Ville de Rimouski. Le flux n'a pas de feed_info.txt.",
        update_cadence_fr=("Au besoin ; le flux vérifié le 2026-10-03 va jusqu'au 2027-02-14."),
    ),
    "rouyn_noranda": _quebec(
        "rouyn_noranda",
        "Ville de Rouyn-Noranda (transport en commun)",
        "Rouyn-Noranda",
        f"{_DQ}41ae2192-51ec-4e20-9a1a-6dd1ffd43777/resource/"
        "c08636e0-5ce0-4bcf-9fb3-e3be76665c84/download/gtfs.zip",
        "transport-en-commun-gtfs",
        "Source: Ville de Rouyn-Noranda, Données Québec, CC BY 4.0.",
        "As needed; the feed checked 2026-10-03 was published 2026-02-05.",
        update_cadence_fr=(
            "Au besoin ; le flux vérifié le 2026-10-03 avait été publié le 2026-02-05."
        ),
    ),
    "stsv_valleyfield": _quebec(
        "stsv_valleyfield",
        "Société de transport de Salaberry-de-Valleyfield (STSV)",
        "Salaberry-de-Valleyfield",
        f"{_DQ}2c84537c-0a2f-4e6f-aae8-1664bd92d90b/resource/"
        "0e4c9cb4-7ab3-40d2-a3d8-a0ecf5d3165c/download/gtfs.zip",
        "gtfs-stsv",
        "Source: Société de transport de Salaberry-de-Valleyfield, Données Québec, CC BY 4.0.",
        "Twice a year per the Données Québec record; the feed checked 2026-10-03 runs to 2026-12-31.",
        (
            "The Communobus routes (route ids Com_1 to Com_6, on-demand service) are described "
            "by frequencies.txt; this module does not expand frequencies, so their trips are left "
            "out of departures and route summaries. The regular lines are complete."
        ),
        (
            "Les lignes Communobus (Com_1 à Com_6, transport sur demande) sont décrites par "
            "frequencies.txt ; ce module ne développe pas les fréquences, leurs voyages sont donc "
            "exclus des passages et des résumés de ligne. Les lignes régulières sont complètes."
        ),
        update_cadence_fr=(
            "Deux fois par année selon la fiche de Données Québec ; le flux vérifié le 2026-10-03 "
            "va jusqu'au 2026-12-31."
        ),
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
ROUTE_TYPES_FR: dict[int, str] = {
    0: "tramway / train léger",
    1: "métro",
    2: "train",
    3: "autobus",
    4: "traversier",
    5: "tramway à câble",
    6: "remontée aérienne",
    7: "funiculaire",
    11: "trolleybus",
    12: "monorail",
}
