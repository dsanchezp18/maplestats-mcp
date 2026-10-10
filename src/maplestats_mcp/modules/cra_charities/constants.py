"""Constants for the CRA registered charities module (verified live 2026-10-10)."""

BASE_URL = "https://open.canada.ca/data/api/3/action/"
RATE_LIMIT_SOURCE = "cra-charities"
RATE_LIMIT_PER_SECOND = 2.0
RATE_LIMIT_CAPACITY = 4.0

CACHE_TTL_SECONDS = 60 * 60
CACHE_TTL_DISCOVERY_SECONDS = 24 * 60 * 60

ORGANIZATION = "cra-arc"
DATASET_TITLE_PATTERN = r"^(\d{4}) List of charities$"
DATASET_PAGE = "https://open.canada.ca/data/en/dataset/{id}"

# Resource names inside each year's package (English names, read live).
RESOURCE_IDENTIFICATION = "Identification"
RESOURCE_GENERAL = "General information"
RESOURCE_DIRECTORS = "Charities Businesses Directors/Officers"
RESOURCE_CODES_PREFIX = "Codes Lists"

# Fallback when discovery finds no matching package: the 2024 list, read live.
FALLBACK_YEAR = 2024
FALLBACK_PACKAGE_ID = "80c00cdb-1358-415c-bb8b-0de7f12675b8"
FALLBACK_RESOURCES = {
    RESOURCE_IDENTIFICATION: "694fdc72-eae4-4ee0-83eb-832ab7b230e3",
    RESOURCE_GENERAL: "fd7c8679-8032-4613-b2b7-44fb8bc9c7c9",
    RESOURCE_DIRECTORS: "3eb35dcd-9b0c-4ae9-a45c-e5e481567c23",
}

LIMIT_DEFAULT = 20
LIMIT_MAX = 100
DIRECTORS_MAX = 500

# CRA designation codes: A public foundation, B private foundation, C charitable organization.
DESIGNATIONS = {
    "A": ("Public foundation", "Fondation publique"),
    "B": ("Private foundation", "Fondation privée"),
    "C": ("Charitable organization", "Organisme de bienfaisance"),
}
