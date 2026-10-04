"""Constants for the Medical Devices Active Licence Listing API (checked live 2026-10-03).

Whole tables that day: licence 74,115 rows (21 MB, 4.6 s; 35,844 active),
company 7,670 (1.8 MB), device 302,429 (45 MB; 156,233 active), device
identifier 1.65 million active rows (217 MB, never loaded). `last_refresh_dt`
on every licence read 2026-10-02: the listing is refreshed daily.
"""

PATH_LICENCE = "medical-devices/licence"
PATH_COMPANY = "medical-devices/company"
PATH_DEVICE = "medical-devices/device"
PATH_IDENTIFIER = "medical-devices/deviceidentifier"

SEARCH_PAGE = "https://health-products.canada.ca/mdall-limh/"
FRESHNESS = "MDALL, refreshed daily by Health Canada"
FRESHNESS_FR = "LIMH, mise à jour chaque jour par Santé Canada"

TABLE_TTL_SECONDS = 6 * 60 * 60
LOOKUP_TTL_SECONDS = 6 * 60 * 60

LIMIT_DEFAULT = 50
LIMIT_MAX = 500
COMPANIES_MAX = 200

# French licence type labels, as `licencetype?lang=fr` names them.
LICENCE_TYPES_FR = {
    "D": "Instrument à article unique",
    "S": "Système",
    "K": "Trousse d'essai",
    "F": "Famille d'instruments",
    "G": "Groupe d'instruments",
    "Y": "Famille de groupe d'instruments",
}

# licence_status codes: English labels from the API guide; the API gives
# no French labels for them, so the French ones are this module's.
LICENCE_STATUSES: dict[str, tuple[str, str]] = {
    "C": ("Cancelled", "Annulée"),
    "D": ("Issued (conditional)", "Délivrée (conditionnelle)"),
    "I": ("Issued (active)", "Délivrée (active)"),
    "M": ("Merged", "Fusionnée"),
    "O": ("Discontinued at renewal", "Abandonnée au renouvellement"),
    "P": ("Pending signature", "En attente de signature"),
    "R": ("Cancelled, no renewal response", "Annulée, sans réponse au renouvellement"),
    "S": ("Suspended", "Suspendue"),
    "W": ("Withdrawn", "Retirée"),
    "Q": ("Suspended, invalid QS certificate", "Suspendue, certificat SQ invalide"),
    "X": ("Cancelled, QS 2003", "Annulée, SQ 2003"),
}
