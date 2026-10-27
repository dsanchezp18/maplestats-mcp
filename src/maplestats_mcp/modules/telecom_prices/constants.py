"""Constants for the CRTC Communications Market Reports module (checked live 2026-10-27)."""

from __future__ import annotations

from dataclasses import dataclass

# The workbooks are found through the federal CKAN catalogue (their URLs hold
# spaces, an en dash and a stale year range, and could move on a new edition),
# then fetched from the CRTC's file host, which, unlike crtc.gc.ca, serves
# them without a Cloudflare challenge.
CKAN_PACKAGE_SHOW = "https://open.canada.ca/data/api/3/action/package_show"
DATASET_PAGE = "https://open.canada.ca/data/{lang}/dataset/{dataset_id}"
FILE_HOST = "applications.crtc.gc.ca"
REPORT_PAGE = {
    "en": "https://crtc.gc.ca/eng/publications/reports/policymonitoring/",
    "fr": "https://crtc.gc.ca/fra/publications/reports/policymonitoring/",
}

SOURCE = "crtc-cmr"

RATE_LIMIT_SOURCE = "crtc-cmr"
RATE_LIMIT_PER_SECOND = 2.0
RATE_LIMIT_CAPACITY = 4.0

# The CRTC updates the quarterly workbook three or four times a year and the
# others once a year.
PACKAGE_TTL_SECONDS = 6 * 60 * 60
FILE_TTL_SECONDS = 12 * 60 * 60
# The price workbook was 1.8 MB; the others 90-190 KB.
MAX_FILE_BYTES = 20 * 1024 * 1024

ROWS_DEFAULT_LIMIT = 500
ROWS_MAX_LIMIT = 5000


@dataclass(frozen=True)
class Workbook:
    dataset_id: str
    # The resource ids of the English and French XLSX files. The price and
    # quarterly workbooks are bilingual, so both languages read one file.
    resource_en: str
    resource_fr: str
    title_en: str
    title_fr: str


PRICES = Workbook(
    dataset_id="8bde476f-49e1-455d-9705-77e6ffab72ca",
    resource_en="42de6a1e-9b28-44ff-9f57-7a0c9d89be64",
    resource_fr="42de6a1e-9b28-44ff-9f57-7a0c9d89be64",
    title_en="Year-End Monthly Reported Prices for Internet and Mobile services - CMR",
    title_fr=(
        "Prix mensuels déclarés à la fin de l'année pour les services d'Internet et de "
        "téléphone mobile - RMC"
    ),
)
TRENDS = Workbook(
    dataset_id="cb02d3b1-dacb-4401-beec-9f9fe178fc1c",
    resource_en="78a789cc-0e47-4820-857c-828a95a7b91c",
    resource_fr="78a789cc-0e47-4820-857c-828a95a7b91c",
    title_en="Current Trends in Communications Industry, Quarterly Results - CMR",
    title_fr="Tendances actuelles pour l'industrie des communications - RMC",
)
SECTORS: dict[str, Workbook] = {
    "mobile": Workbook(
        dataset_id="09a45d61-4cd5-4fce-bc06-affb722b7f10",
        resource_en="b7495b3a-90bb-45f8-bd4d-b575f29a66e2",
        resource_fr="8651f13d-9891-4235-b226-b829d5aa7a9a",
        title_en="Retail Mobile Sector - CMR",
        title_fr="Secteur des services mobiles de détail - RMC",
    ),
    "internet": Workbook(
        dataset_id="8a80c08b-ba7e-4a72-869e-f7fcdc6eb6e3",
        resource_en="2f5a5a87-599a-4c25-b7bb-5c4527b8e32a",
        resource_fr="90ab450e-85f8-49f8-aced-4f1bad20bda6",
        title_en="Retail Fixed Internet Sector and Broadband Availability - CMR",
        title_fr="Secteur des services Internet fixes de détail et disponibilité - RMC",
    ),
}

# Sheet names in the price workbook.
PRICE_SHEETS = {"mobile": "Moyennes-Averages Mobile", "internet": "Moyennes-Averages Internet"}

# Sheet names in the quarterly workbook.
TREND_SHEETS = {
    "mobile": "Mobile",
    "internet": "Internet",
    "wireline": "TeleFilaires-WirelineVoice",
    "tv_distribution": "EDR-BDU",
}

PROVINCES: dict[str, tuple[str, str]] = {
    "NL": ("Newfoundland and Labrador", "Terre-Neuve-et-Labrador"),
    "PE": ("Prince Edward Island", "Île-du-Prince-Édouard"),
    "NS": ("Nova Scotia", "Nouvelle-Écosse"),
    "NB": ("New Brunswick", "Nouveau-Brunswick"),
    "QC": ("Quebec", "Québec"),
    "ON": ("Ontario", "Ontario"),
    "MB": ("Manitoba", "Manitoba"),
    "SK": ("Saskatchewan", "Saskatchewan"),
    "AB": ("Alberta", "Alberta"),
    "BC": ("British Columbia", "Colombie-Britannique"),
    "YT": ("Yukon", "Yukon"),
    "NT": ("Northwest Territories", "Territoires du Nord-Ouest"),
    "NU": ("Nunavut", "Nunavut"),
}
