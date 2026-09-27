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

# Information requests (checked live 2026-09-27): 1,121 requests since
# December 2008, 40 per page; the list ignores every filter parameter.
REGISTER_TTL_SECONDS = 6 * 60 * 60
IR_PAGE_SIZE = 25
IR_FETCH_CONCURRENCY = 4

REQUEST_STATUSES = {
    "completed": ("Completed", "Terminée"),
    "pending": ("Pending", "En attente"),
    "pending_correspondence": ("Pending correspondence", "Correspondance en attente"),
    "pending_data": ("Pending data", "Données en attente"),
    "canceled": ("Canceled", "Annulée"),
}
DISPOSITIONS = {
    "all_disclosed": ("All disclosed", "Communication totale"),
    "disclosed_in_part": ("Disclosed in part", "Communication partielle"),
    "nothing_disclosed": ("Nothing disclosed", "Aucune communication"),
    "does_not_exist": ("Information does not exist", "L'information n'existe pas"),
}
DOCUMENT_TYPES = {
    "request_letter": ("Request letter", "Lettre de demande"),
    "reply_letter": ("Reply letter", "Lettre de réponse"),
    "other_outgoing_letter": ("Other letter from PBO", "Autre lettre du DPB"),
    "other_incoming_letter": ("Other letter to PBO", "Autre lettre au DPB"),
}
