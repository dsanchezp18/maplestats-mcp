"""Constants for the PMPRB module (checked live 2026-09-27)."""

SITE = "https://www.canada.ca"
# The annual reports index lists every report and patented medicines list;
# reports from 2017 back link to the retired pmprb-cepmb.gc.ca site.
INDEX_PAGE = {
    "en": SITE + "/en/patented-medicine-prices-review/services/annual-reports.html",
    "fr": SITE + "/fr/examen-prix-medicaments-brevetes/services/rapports-annuels.html",
}
REPORT_LINK = r"^(?:Annual Report|Rapport annuel)\s+(\d{4})$"
LIST_LINK = r"^(?:List of Patented Medicines|Liste des médicaments brevetés)\s+(\d{4})$"

RATE_LIMIT_SOURCE = "pmprb"
RATE_LIMIT_PER_SECOND = 1.0
RATE_LIMIT_CAPACITY = 2.0

# Reports come out once a year (the 2024 report in late 2025).
INDEX_TTL_SECONDS = 24 * 60 * 60
PAGE_TTL_SECONDS = 24 * 60 * 60
# The largest page, the 2020 medicines list, was 593 KB.
MAX_PAGE_BYTES = 4 * 1024 * 1024

# 100 medicines came to about 275 KB.
MEDICINES_DEFAULT_LIMIT = 25
MEDICINES_MAX_LIMIT = 1000

# Price review status in the medicines lists, as spelled in English and
# French (2020 and 2021 pages), folded.
STATUSES: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "within_guidelines": (
        "Within Guidelines",
        "Conforme aux lignes directrices",
        ("within guidelines", "conformes aux lignes directrices"),
    ),
    "does_not_trigger": (
        "Does not trigger an investigation",
        "Ne justifie pas une enquête",
        ("does not trigger", "ne justifie pas une enquete"),
    ),
    "under_investigation": (
        "Subject to investigation",
        "Sous enquête",
        ("subj. investigation", "sous enquete"),
    ),
    "under_review": ("Under review", "Sous examen", ("under review", "sous examen")),
    "voluntary_compliance_undertaking": (
        "Voluntary Compliance Undertaking",
        "Engagement de conformité volontaire",
        ("vcu", "ecv"),
    ),
    "notice_of_hearing": ("Notice of Hearing", "Avis d'audience", ("notice of hearing", "noh")),
    "stay_order": (
        "Subject to Stay Order",
        "Assujettie à une ordonnance de sursis",
        ("subject to stay order", "assujettie a une ordonnance de sursis"),
    ),
}
