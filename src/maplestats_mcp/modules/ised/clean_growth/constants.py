"""Constants for the Clean Growth Hub's federal cleantech investment page."""

PAGE_URLS = {
    "en": "https://ised-isde.canada.ca/site/clean-growth-hub/en/federal-investment-clean-technology-2016-2024",
    "fr": (
        "https://ised-isde.canada.ca/site/carrefour-croissance-propre/fr/"
        "investissements-federaux-dans-technologies-propres-2016-2024"
    ),
}
PDF_URLS = {
    "en": "https://ised-isde.canada.ca/site/clean-growth-hub/sites/default/files/documents/federal-investment-from-2016-2024-en.pdf",
    "fr": "https://ised-isde.canada.ca/site/clean-growth-hub/sites/default/files/documents/federal-investment-from-2016-2024-fr.pdf",
}
# The page's projects come from this dataset (its note 1); its DataStore
# table answers record-level questions through ckan_datastore_search.
GRANTS_DATASET_ID = "432527ab-7aac-45b5-81d6-7597107a7013"
GRANTS_RESOURCE_ID = "1d15a62f-5656-49ad-8c88-f40ce689d831"

RATE_LIMIT_SOURCE = "ised-clean-growth"
RATE_LIMIT_PER_SECOND = 1.0
RATE_LIMIT_CAPACITY = 2.0
CACHE_TTL_SECONDS = 24 * 60 * 60
MAX_PAGE_BYTES = 2 * 1024 * 1024
