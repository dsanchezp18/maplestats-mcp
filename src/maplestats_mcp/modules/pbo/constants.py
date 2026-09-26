"""Constants for the PBO distribution API (checked 2026-09-26)."""

API = "https://99bank.pbo-dpb.ca/distribution/1/"
WEBSITE = "https://www.pbo-dpb.ca"

RATE_LIMIT_SOURCE = "pbo"
RATE_LIMIT_PER_SECOND = 1.0
RATE_LIMIT_CAPACITY = 2.0

LIST_TTL_SECONDS = 60 * 60
PUBLICATION_TTL_SECONDS = 6 * 60 * 60
PAGE_SIZE = 15  # fixed by the API; per_page and limit are ignored
TEXT_MAX_CHARS = 20_000

# Publication type codes seen in the API, with their meaning.
TYPES = {
    "RP": ("Report", "Rapport"),
    "NT": ("Note", "Note"),
    "LEG": ("Legislative costing note", "Note d'évaluation du coût d'une mesure législative"),
    "ES": ("Cost estimate", "Estimation des coûts"),
    "OA": ("Additional analysis", "Analyse complémentaire"),
    "LIBARC": ("Archived publication", "Publication archivée"),
}
