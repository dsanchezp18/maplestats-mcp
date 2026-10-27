"""Constants for the CBSA Customs Tariff module (checked live 2026-10-26)."""

from __future__ import annotations

SITE = "https://www.cbsa-asfc.gc.ca"
MENU_URL = SITE + "/trade-commerce/tariff-tarif/{year}/menu-{suffix}.html"
SUFFIX = {"en": "eng", "fr": "fra"}
# Year pages exist from 2018 (2017 answers 404); earlier editions are not online.
FIRST_YEAR = 2018
# The Access table holding the schedule, in every edition from 2018 to 2026-2.
TABLE = "TPHS"

# Also the provenance source, whose terms are in shared/licences.py.
RATE_LIMIT_SOURCE = "cbsa-tariff"
RATE_LIMIT_PER_SECOND = 1.0
RATE_LIMIT_CAPACITY = 2.0

# A year page changes when CBSA posts an amendment (three in 2026 by October).
MENU_TTL_SECONDS = 6 * 3600
# The 2026-2 zip was 1.2 MB and held a 25 MB .accdb (26 MB in French);
# 2018's held a 10 MB .mdb.
MAX_ZIP_BYTES = 30 * 1024 * 1024
MAX_DATABASE_BYTES = 200 * 1024 * 1024
# Parquet copies kept on disk, least recently used removed first.
MAX_CACHED_EDITIONS = 12

SEARCH_LIMIT_MAX = 100
CHILDREN_LIMIT = 200
SNIPPET_CHARS = 600

# Rate columns, as (code, accepted column names, English name, French name).
# The English file names columns with English codes and the French file with
# French codes (TÉU, NPF ...); 2018's files used GT, MT and MUST, and both
# 2018 files had English names. Names are compared on their ASCII letters and
# digits only, because access-parser decodes the French ones with replacement
# characters (U+FFFD for the É of TÉU): both spellings then read 'TU'.
TREATMENTS: tuple[tuple[str, tuple[str, ...], str, str], ...] = (
    ("MFN", ("MFN", "NPF"), "Most-Favoured-Nation Tariff", "Tarif de la nation la plus favorisée"),
    ("GT", ("General Tariff", "GT", "Tarif général", "TG"), "General Tariff", "Tarif général"),
    ("AUT", ("AUT", "TAU"), "Australia Tariff", "Tarif de l'Australie"),
    ("NZT", ("NZT", "TNZ"), "New Zealand Tariff", "Tarif de la Nouvelle-Zélande"),
    (
        "CCCT",
        ("CCCT", "TPAC"),
        "Commonwealth Caribbean Countries Tariff",
        "Tarif des pays antillais du Commonwealth",
    ),
    (
        "LDCT",
        ("LDCT", "TPMD", "TPDM"),
        "Least Developed Country Tariff",
        "Tarif des pays les moins développés",
    ),
    ("GPT", ("GPT", "TPG"), "General Preferential Tariff", "Tarif de préférence général"),
    ("UST", ("UST", "TÉU"), "United States Tariff (CUSMA)", "Tarif des États-Unis (ACEUM)"),
    ("MXT", ("MXT", "MT", "TMX", "TM"), "Mexico Tariff (CUSMA)", "Tarif du Mexique (ACEUM)"),
    (
        "MUST",
        ("MUST", "TMEU"),
        "Mexico-United States Tariff (NAFTA, to 2020)",
        "Tarif Mexique-États-Unis (ALENA, jusqu'en 2020)",
    ),
    (
        "CIAT",
        ("CIAT", "TACI"),
        "Canada-Israel Agreement Tariff",
        "Tarif de l'Accord Canada-Israël",
    ),
    ("CT", ("CT", "TC"), "Chile Tariff", "Tarif du Chili"),
    ("CRT", ("CRT", "TCR"), "Costa Rica Tariff", "Tarif du Costa Rica"),
    ("IT", ("IT", "TI"), "Iceland Tariff", "Tarif de l'Islande"),
    ("NT", ("NT", "TN"), "Norway Tariff", "Tarif de la Norvège"),
    (
        "SLT",
        ("SLT", "TSL"),
        "Switzerland-Liechtenstein Tariff",
        "Tarif de la Suisse-Liechtenstein",
    ),
    ("PT", ("PT", "TP"), "Peru Tariff", "Tarif du Pérou"),
    ("COLT", ("COLT", "TCOL"), "Colombia Tariff", "Tarif de la Colombie"),
    ("JT", ("JT", "TJ"), "Jordan Tariff", "Tarif de la Jordanie"),
    ("PAT", ("PAT", "TPA"), "Panama Tariff", "Tarif du Panama"),
    ("HNT", ("HNT", "THN"), "Honduras Tariff", "Tarif du Honduras"),
    ("KRT", ("KRT", "TKR"), "Korea Tariff", "Tarif de la Corée"),
    (
        "CEUT",
        ("CEUT", "TCUE"),
        "Canada-European Union Tariff (CETA)",
        "Tarif Canada-Union européenne (AECG)",
    ),
    ("UAT", ("UAT", "TUA"), "Ukraine Tariff", "Tarif de l'Ukraine"),
    ("CPTPT", ("CPTPT", "TPTGP"), "CPTPP Tariff", "Tarif du PTPGP"),
    (
        "UKT",
        ("UKT", "TUK"),
        "United Kingdom Tariff (CUKTCA)",
        "Tarif du Royaume-Uni (ACCRU)",
    ),
    (
        "CPUKT",
        ("CPUKT", "TUKGP"),
        "Comprehensive and Progressive United Kingdom Tariff (CPTPP)",
        "Tarif du Royaume-Uni au titre du PTPGP",
    ),
)

# The other columns, English and French names.
FIELDS: dict[str, tuple[str, ...]] = {
    "tariff": ("TARIFF", "TARIF"),
    "effective_date": ("EFF_DATE", "DATE_EFF"),
    "change": ("CHANGE", "CHANGEMENT"),
    "sub_chapter": ("SUB_CHAP", "SOUS_CHAP"),
    "desc1": ("DESC1",),
    "desc2": ("DESC2",),
    "desc3": ("DESC3",),
    "footnote": ("FOOTNOTE", "NOTE DE BAS DE PAGE"),
    "uom": ("UOM", "UDM"),
}


FRESHNESS = (
    "a new edition (T2026, T2026-1 ...) each time the tariff is amended, with its effective "
    "date; several a year"
)
FRESHNESS_FR = (
    "une nouvelle édition (T2026, T2026-1 ...) à chaque modification du tarif, avec sa date "
    "d'entrée en vigueur ; plusieurs par année"
)
COVERAGE = (
    "the Schedule's chapters 1-99: headings, subheadings, tariff items and 10-digit "
    "classification numbers, with MFN, General and preferential rates; surtaxes, "
    "safeguards, anti-dumping and countervailing duties, excise and GST are not included"
)
COVERAGE_FR = (
    "les chapitres 1 à 99 de l'annexe : positions, sous-positions, numéros tarifaires et "
    "numéros de classement à 10 chiffres, avec les taux NPF, général et préférentiels ; "
    "les surtaxes, mesures de sauvegarde, droits antidumping et compensateurs, la taxe "
    "d'accise et la TPS n'y sont pas"
)
