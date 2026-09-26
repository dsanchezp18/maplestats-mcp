"""Constants for the Competition Bureau's merger-review reports."""

BASE = "https://competition-bureau.canada.ca/en/mergers-and-acquisitions/"
CURRENT_URL = BASE + "report-concluded-merger-reviews"
ARCHIVE_URL = BASE + "archived-report-merger-reviews"
FR_URLS = {
    "current": "https://bureau-concurrence.canada.ca/fr/fusions-acquisitions/rapport-examens-fusions-termines",
    "archive": "https://bureau-concurrence.canada.ca/fr/fusions-acquisitions/archive-rapport-examens-fusions",
}

RATE_LIMIT_SOURCE = "competition-bureau"
RATE_LIMIT_PER_SECOND = 1.0
RATE_LIMIT_CAPACITY = 2.0
# The report is updated on or after each Tuesday.
CACHE_TTL_SECONDS = 6 * 60 * 60
MAX_PAGE_BYTES = 5 * 1024 * 1024

LIMIT_DEFAULT = 25
LIMIT_MAX = 500

# Codes and meanings from the pages' own legends (checked 2026-09-25).
OUTCOMES = {
    "ARC": ("Advance ruling certificate (s. 102)", "Certificat de décision préalable (art. 102)"),
    "NAL": ("No action letter", "Lettre de non-intervention"),
    "CA": ("Consent agreement registered", "Consentement enregistré"),
    "JD": ("Judicial decision", "Décision judiciaire"),
    "TA": ("Transaction abandoned by the parties", "Transaction abandonnée par les parties"),
    "Other": ("Other", "Autre"),
    "Ongoing": ("Review ongoing", "Examen en cours"),
}
