"""Constants for CIPO's IP Horizons researcher datasets on open.canada.ca."""

CKAN_BASE_URL = "https://open.canada.ca/data/api/3/action/package_show"
DATASET_PAGE_URL = "https://open.canada.ca/data/en/dataset/{id}"
RATE_LIMIT_SOURCE = "ised-ip-horizons"
RATE_LIMIT_PER_SECOND = 1.0
RATE_LIMIT_CAPACITY = 3.0

# The catalogue changes a few times a year; the dictionaries even less.
CATALOGUE_TTL_SECONDS = 6 * 60 * 60
DICTIONARY_TTL_SECONDS = 24 * 60 * 60

# The three IP Horizons packages published by CIPO on open.canada.ca,
# confirmed live 2026-09-25 by searching for "IP Horizons".
PACKAGE_IDS = {
    "patent": "fe1dfbb9-0fc3-42ca-b2a9-6ca4c05dbac9",
    "industrial_design": "d92aacca-769f-4e8e-9d79-0bcf3078ff21",
    "trademark": "4bf74760-7ae7-4c83-ace8-b84a3b9aea8d",
}

# Only patents and industrial designs have a dictionary: the trademark
# URL following the same pattern answers an HTML 404 page (checked live
# 2026-09-25), and the trademark package lists none.
DICTIONARY_URLS = {
    "patent": "https://opic-cipo.ca/cipo/client_downloads/IP_Horizon_Resources/PT_Data_Dictionary.zip",
    "industrial_design": "https://opic-cipo.ca/cipo/client_downloads/IP_Horizon_Resources/ID_Data_Dictionary.zip",
}
MAX_DICTIONARY_BYTES = 5 * 1024 * 1024

# Releases on CIPO's server that open.canada.ca does not list. Checked
# 2026-09-25: every trademark link the package lists (TM_CSV_2024_08_20 and
# older) answers 404, while all 19 tables of the 2024-11-20 release answer;
# probing the 20th of each month through 2026-09 found no later one.
UNLISTED_RELEASES = {
    "trademark": [
        (
            "https://opic-cipo.ca/cipo/client_downloads/TM_CSV_2024_11_20/TM_{table}_2024-11-20.zip",
            (
                "applicant_classification",
                "application_disclaimer",
                "application_main",
                "application_text",
                "cancellation_case",
                "cancellation_case_action",
                "cipo_classification",
                "claim",
                "event",
                "footnote",
                "footnote_formatted",
                "heading",
                "interested_party",
                "mark_description",
                "opposition_case",
                "opposition_case_action",
                "priority_claim",
                "representation",
                "transliteration",
            ),
        )
    ]
}
UNLISTED_NOTE = (
    "Trademark files come from the 2024-11-20 release on CIPO's server; "
    "open.canada.ca still lists only older, now-removed files."
)
