"""Constants for StatCan's LODE open databases (facilities, buildings, addresses).

Confirmed live 2026-10-02: statcan.gc.ca/en/lode/databases lists the open
databases; each links a www150.statcan.gc.ca /n1/pub/ product page whose
.zip links are free, unauthenticated downloads answering `Accept-Ranges:
bytes`. Every file here is read through its .zip and no .csv/.xlsx path is
requested.
The product pages state the data are released under the Open Government
Licence - Canada, with the publication governed by the Statistics Canada
Open Licence Agreement.

Data formats seen in the zips: GeoJSON (ODHF; coordinates are in EPSG:3347
metres although GeoJSON normally means degrees), GeoPackage (a SQLite file,
read here with the standard library), CSV (ODEF, ODCAF, ODBus, ODA, Index
of Remoteness, Proximity Measures) and GeoParquet (ODHF, ODSRF; not read,
since the same data ship as GeoPackage and Parquet needs a new dependency).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from maplestats_mcp import config

ALLOWED_HOST = "www150.statcan.gc.ca"
LANDING_URL = {
    "en": "https://www.statcan.gc.ca/en/lode/databases",
    "fr": "https://www.statcan.gc.ca/fr/ecdo/bases-donnees",
}
PUB_URL = "https://www150.statcan.gc.ca/n1/pub/{path}-{suffix}.htm"

RATE_LIMIT_SOURCE = "statcan-lode"
# Pages and HEAD probes go at most one every two seconds (a burst of two
# for the first request of a call).
RATE_LIMIT_PER_SECOND = 0.5
RATE_LIMIT_CAPACITY = 2.0

CACHE_TTL_SECONDS = 24 * 60 * 60
RECORDS_DEFAULT = 25
RECORDS_MAX = 500
FIELD_EXAMPLES = 1

# Per-call download cap. ODSRF (269 MB zip, 466 MB GeoPackage) is the
# largest queryable archive; the National Address Register (1.67 GB) and
# the 443 MB transit archive stay range-read only.
DEFAULT_MAX_DOWNLOAD_MB = 300
MAX_MEMBER_BYTES = 800_000_000
# Describe may download a GeoPackage only to read its table schema, so it
# uses a much smaller cap.
DESCRIBE_DOWNLOAD_BYTES = 60_000_000
PREVIEW_ROWS_MAX = 200
PREVIEW_SCAN_DEFAULT_MB = 8
PREVIEW_SCAN_MAX_MB = 40
RANGE_CHUNK_BYTES = 1 << 20
SCAN_ROWS_MAX = 2_000_000


def max_download_bytes() -> int:
    """Largest archive one call may download (MAPLE_LODE_MAX_DOWNLOAD_MB; 0 turns downloads off)."""
    return config.get_lode_max_download_bytes(DEFAULT_MAX_DOWNLOAD_MB)


def cache_dir() -> Path:
    """Where downloaded archives are unpacked (MAPLE_LODE_CACHE_DIR; a hosted instance should use a persistent volume)."""
    return config.get_lode_cache_dir()


def cache_max_bytes() -> int:
    """Cap on the unpacked cache (MAPLE_LODE_CACHE_MAX_GB, default 3); least recently used files go first."""
    return config.get_lode_cache_max_bytes()


PROVINCES: dict[str, tuple[str, str, str]] = {
    # code: (PRUID, English name, French name)
    "NL": ("10", "Newfoundland and Labrador", "Terre-Neuve-et-Labrador"),
    "PE": ("11", "Prince Edward Island", "Île-du-Prince-Édouard"),
    "NS": ("12", "Nova Scotia", "Nouvelle-Écosse"),
    "NB": ("13", "New Brunswick", "Nouveau-Brunswick"),
    "QC": ("24", "Quebec", "Québec"),
    "ON": ("35", "Ontario", "Ontario"),
    "MB": ("46", "Manitoba", "Manitoba"),
    "SK": ("47", "Saskatchewan", "Saskatchewan"),
    "AB": ("48", "Alberta", "Alberta"),
    "BC": ("59", "British Columbia", "Colombie-Britannique"),
    "YT": ("60", "Yukon", "Yukon"),
    "NT": ("61", "Northwest Territories", "Territoires du Nord-Ouest"),
    "NU": ("62", "Nunavut", "Nunavut"),
}
# ODB spells two names differently from StatCan's usual list.
PROVINCE_ALIASES: dict[str, str] = {
    "newfoundland": "NL",
    "yukon territory": "YT",
    "northwest territory": "NT",
    "pei": "PE",
}

OGL = "Open Government Licence - Canada"
OGL_URL = "https://open.canada.ca/en/open-government-licence-canada"
STATCAN_LICENCE = "Statistics Canada Open Licence"
STATCAN_LICENCE_URL = "https://www.statcan.gc.ca/en/terms-conditions/open-licence"
OGL_FR = "Licence du gouvernement ouvert – Canada"
OGL_URL_FR = "https://ouvert.canada.ca/fr/licence-du-gouvernement-ouvert-canada"
STATCAN_LICENCE_FR = "Licence ouverte de Statistique Canada"
STATCAN_LICENCE_URL_FR = "https://www.statcan.gc.ca/fr/reference/licence"


@dataclass(frozen=True)
class Database:
    key: str
    catalogue_number: str
    title_en: str
    title_fr: str
    group: str  # open_database | accessibility | address_register
    page_en: str
    page_fr: str
    description_en: str
    description_fr: str
    formats: tuple[str, ...]
    on_landing_page: bool = True
    # How a file is picked when the caller gives neither `file` nor `province`:
    # a substring of the download's file name. None means the caller must choose.
    default_file: str | None = None
    queryable: bool = True


def _pub(path: str) -> tuple[str, str]:
    return (
        PUB_URL.format(path=path, suffix="eng"),
        PUB_URL.format(path=path, suffix="fra"),
    )


DATABASES: tuple[Database, ...] = (
    Database(
        "odhf",
        "13-26-0001",
        "Open Database of Healthcare Facilities (ODHF)",
        "Base de données ouvertes sur les établissements de soins de santé (BDOESS)",
        "open_database",
        *_pub("13-26-0001/132600012020001"),
        "Names, types, addresses and locations of about 22,000 healthcare facilities "
        "(hospitals, clinics, pharmacies, nursing homes) in nine types.",
        "Noms, types, adresses et emplacements d'environ 22 000 établissements de soins "
        "de santé (hôpitaux, cliniques, pharmacies, foyers de soins) en neuf types.",
        ("GeoJSON", "GeoPackage", "GeoParquet"),
        default_file="geojson",
    ),
    Database(
        "odsrf",
        "21-26-0002",
        "Open Database of Sports and Recreational Facilities (ODSRF)",
        "Base de données ouvertes sur les installations récréatives et sportives (BDIORS)",
        "open_database",
        *_pub("21-26-0002/212600022021001"),
        "Name, type and location of about 249,000 sports and recreation facilities "
        "(arenas, pools, parks, trails, ski resorts) in 54 types.",
        "Nom, type et emplacement d'environ 249 000 installations sportives et récréatives "
        "(arénas, piscines, parcs, sentiers, stations de ski) en 54 types.",
        ("GeoPackage", "GeoParquet"),
        default_file="gpkg",
    ),
    Database(
        "odb",
        "34-26-0001",
        "Open Database of Buildings (ODB)",
        "Base de données ouvertes sur les immeubles (BDOI)",
        "open_database",
        *_pub("34-26-0001/342600012018001"),
        "About 14.4 million building footprints compiled from hundreds of sources, "
        "one GeoPackage zip per province (Quebec and Ontario in parts).",
        "Environ 14,4 millions d'empreintes d'immeubles compilées de centaines de sources, "
        "un fichier zip GeoPackage par province (Québec et Ontario en parties).",
        ("GeoPackage",),
    ),
    Database(
        "odef",
        "37-26-0001",
        "Open Database of Educational Facilities (ODEF)",
        "Base de données ouvertes sur les établissements d'enseignement (BDOEE)",
        "open_database",
        *_pub("37-26-0001/372600012022001"),
        "About 19,000 schools and other educational facilities with grades, ISCED "
        "levels and French immersion flags.",
        "Environ 19 000 écoles et autres établissements d'enseignement avec niveaux, "
        "CITE et immersion française.",
        ("CSV",),
        default_file="odef",
    ),
    Database(
        "odcaf",
        "21-26-0001",
        "Open Database of Cultural and Art Facilities (ODCAF)",
        "Base de données ouvertes sur les installations culturelles et artistiques (BDOICA)",
        "open_database",
        "https://www.statcan.gc.ca/en/lode/databases/odcaf",
        "https://www.statcan.gc.ca/fr/ecdo/bases-donnees/bdoica",
        "About 8,000 museums, galleries, libraries, theatres and heritage sites with "
        "address and coordinates.",
        "Environ 8 000 musées, galeries, bibliothèques, théâtres et sites patrimoniaux "
        "avec adresse et coordonnées.",
        ("CSV",),
        default_file="odcaf",
    ),
    Database(
        "odi",
        "34-26-0003",
        "Open Database of Infrastructure (ODI)",
        "Base de données ouvertes sur les infrastructures",
        "open_database",
        *_pub("34-26-0003/342600032023001"),
        "Infrastructure locations in 11 downloadable types: electric grid, oil and gas, "
        "airports, bridges and tunnels, ports, railways, water, waste, telecom.",
        "Emplacements d'infrastructures en 11 types téléchargeables : réseau électrique, "
        "pétrole et gaz, aéroports, ponts et tunnels, ports, chemins de fer, eau, déchets, "
        "télécommunications.",
        ("GeoPackage",),
    ),
    Database(
        "odbiz",
        "21-26-0003",
        "Open Database of Businesses (ODBus)",
        "Base de données ouvertes sur les entreprises",
        "open_database",
        *_pub("21-26-0003/212600032023001"),
        "Business names, addresses, locations and industry codes from municipal and "
        "provincial licence registers.",
        "Noms, adresses, emplacements et codes d'industrie d'entreprises tirés de "
        "registres de permis municipaux et provinciaux.",
        ("CSV",),
        default_file="odbus",
    ),
    Database(
        "oda",
        "46-26-0001",
        "Open Database of Addresses (ODA)",
        "Base de données ouvertes d'adresses (BDOA)",
        "open_database",
        "https://www.statcan.gc.ca/en/lode/databases/oda",
        "https://www.statcan.gc.ca/fr/ecdo/bases-donnees/bdoa",
        "Over 10 million civic addresses with coordinates, one CSV zip per province "
        "(Newfoundland and Labrador, Yukon and Nunavut are not offered).",
        "Plus de 10 millions d'adresses civiques avec coordonnées, un fichier zip CSV par "
        "province (Terre-Neuve-et-Labrador, le Yukon et le Nunavut ne sont pas offerts).",
        ("CSV",),
    ),
    Database(
        "odg",
        "32-26-0005",
        "Open Database of Greenhouses (ODG)",
        "Base de données ouverte sur les serres",
        "open_database",
        *_pub("32-26-0005/322600052023001"),
        "About 3,900 digitized greenhouse footprints (version 2.0 adds 1,006 detected by "
        "machine learning).",
        "Environ 3 900 empreintes de serres numérisées (la version 2.0 en ajoute 1 006 "
        "détectées par apprentissage automatique).",
        ("Shapefile", "GeoPackage"),
        default_file="v2",
    ),
    Database(
        "pedestrian",
        "34-26-0004",
        "Canadian Pedestrian Network Database",
        "Base de données sur les réseaux piétonniers du Canada",
        "open_database",
        *_pub("34-26-0004/342600042025001"),
        "Sidewalks, paths, crosswalks and stairways from 55 municipalities (136 MB zip).",
        "Trottoirs, sentiers, passages piétonniers et escaliers de 55 municipalités "
        "(zip de 136 Mo).",
        ("GeoPackage",),
        default_file="pedestrian",
    ),
    Database(
        "cycling",
        "23-26-0004",
        "Canadian Cycling Network Database",
        "Base de données sur les réseaux cyclables du Canada",
        "open_database",
        *_pub("23-26-0004/232600042024001"),
        "Cycling infrastructure from 75 municipalities, classified with Can-BICS.",
        "Infrastructures cyclables de 75 municipalités, classées selon Can-BICS.",
        ("GeoPackage",),
        default_file="cycling",
    ),
    Database(
        "transit",
        "23-26-0003",
        "Canadian Public Transit Network Database",
        "Base de données sur les réseaux de transport en commun du Canada",
        "open_database",
        *_pub("23-26-0003/232600032025001"),
        "GTFS feeds and geospatial files for over 100 transit services (443 MB zip; "
        "listed and range-read only).",
        "Flux GTFS et fichiers géospatiaux de plus de 100 services de transport en commun "
        "(zip de 443 Mo; liste et lecture par plages seulement).",
        ("GTFS", "GeoPackage"),
        queryable=False,
    ),
    Database(
        "remoteness",
        "17-26-0001",
        "Index of Remoteness",
        "Indice d'éloignement",
        "accessibility",
        *_pub("17-26-0001/172600012020001"),
        "Remoteness index of every census subdivision (2021 boundaries), from 0 to 1.",
        "Indice d'éloignement de chaque subdivision de recensement (limites de 2021), de 0 à 1.",
        ("CSV",),
        on_landing_page=False,
        default_file="remoteness",
    ),
    Database(
        "pmd",
        "17-26-0002",
        "Proximity Measures Database",
        "Base de données sur les mesures de proximité",
        "accessibility",
        *_pub("17-26-0002/172600022023001"),
        "Ten proximity measures and a composite index for every dissemination block (164 MB CSV).",
        "Dix mesures de proximité et un indice composite pour chaque îlot de diffusion "
        "(CSV de 164 Mo).",
        ("CSV",),
        on_landing_page=False,
        default_file="pmd",
    ),
    Database(
        "sam",
        "27-26-0001",
        "Spatial Access Measures",
        "Mesures d'accès spatial",
        "accessibility",
        *_pub("27-26-0001/272600012023001"),
        "Spatial access to services by dissemination area, 2022 and 2024 editions.",
        "Accès spatial aux services par aire de diffusion, éditions de 2022 et de 2024.",
        ("CSV",),
        on_landing_page=False,
        default_file="msa2024",
    ),
    Database(
        "nar",
        "46-26-0002",
        "National Address Register (NAR)",
        "Registre national des adresses (RNA)",
        "address_register",
        *_pub("46-26-0002/462600022022001"),
        "Residential and non-residential addresses of Canada, one 1.67 GB zip per "
        "release (updated twice a year). Never downloaded here: list it and preview "
        "members by HTTP range.",
        "Adresses résidentielles et non résidentielles du Canada, un zip de 1,67 Go par "
        "diffusion (mis à jour deux fois par an). Jamais téléchargé ici : liste et "
        "aperçu des fichiers par plages HTTP.",
        ("CSV",),
        on_landing_page=False,
        queryable=False,
    ),
)

BY_KEY = {db.key: db for db in DATABASES}
