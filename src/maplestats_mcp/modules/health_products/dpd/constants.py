"""Constants for the Drug Product Database API (checked live 2026-10-03).

Whole tables, English, as served that day: drugproduct 58,310 rows (15 MB),
status 58,310 (one current status per product, 10.8 MB), activeingredient
120,845 (16 MB), schedule 59,283 (3.3 MB), therapeuticclass 48,097
(3.8 MB), company 5,249 (1.4 MB). Each loads in under 7 s.
"""

PATH_PRODUCT = "drug/drugproduct"
PATH_INGREDIENT = "drug/activeingredient"
PATH_STATUS = "drug/status"
PATH_SCHEDULE = "drug/schedule"
PATH_ATC = "drug/therapeuticclass"
PATH_FORM = "drug/form"
PATH_ROUTE = "drug/route"
PATH_PACKAGING = "drug/packaging"
PATH_STANDARD = "drug/pharmaceuticalstd"
PATH_SPECIES = "drug/veterinaryspecies"
PATH_COMPANY = "drug/company"

SEARCH_PAGE = "https://health-products.canada.ca/dpd-bdpp/"
FRESHNESS = "DPD online data, refreshed by Health Canada on business days"

# Whole tables change slowly; six hours keeps a busy server off the API.
TABLE_TTL_SECONDS = 6 * 60 * 60
LOOKUP_TTL_SECONDS = 60 * 60

LIMIT_DEFAULT = 50
LIMIT_MAX = 500

# external_status_code -> (English, French), as the status table spells
# them in each language. The API filter `status=` takes these codes. No
# product had code 11 on 2026-10-03; its English label is the API guide's
# and its French label follows the pattern of codes 12 and 14.
STATUSES: dict[int, tuple[str, str]] = {
    1: ("Approved", "Approuvé"),
    2: ("Marketed", "Commercialisé"),
    3: ("Cancelled Pre Market", "Annulé avant commercialisation"),
    4: ("Cancelled Post Market", "Annulé après commercialisation"),
    6: ("Dormant", "Dormant"),
    9: ("Cancelled (Unreturned Annual)", "Annulé (notification annuelle omise)"),
    10: ("Cancelled (Safety Issue)", "Annulé (problème d'innocuité)"),
    11: ("Authorized By Interim Order", "Autorisé par arrêté d'urgence"),
    12: ("Authorization By Interim Order Revoked", "Autorisation par arrêté d'urgence révoquée"),
    13: ("Restricted Access", "Accès restreint"),
    14: ("Authorization By Interim Order Expired", "Autorisation par arrêté d'urgence expirée"),
    15: ("Cancelled (Transitioned To Biocides)", "Annulé (transféré aux biocides)"),
}
STATUS_KEYS: dict[str, int] = {
    "approved": 1,
    "marketed": 2,
    "cancelled_pre_market": 3,
    "cancelled_post_market": 4,
    "dormant": 6,
    "cancelled_unreturned_annual": 9,
    "cancelled_safety_issue": 10,
    "authorized_interim_order": 11,
    "interim_order_revoked": 12,
    "restricted_access": 13,
    "interim_order_expired": 14,
    "cancelled_biocides": 15,
}

CLASSES_FR = {
    "Human": "Humain",
    "Veterinary": "Vétérinaire",
    "Disinfectant": "Désinfectant",
    "Radiopharmaceutical": "Radiopharmaceutique",
}

# Schedule names in the English table (upper case there) and in French.
SCHEDULES_FR = {
    "NON-PRESCRIPTION DRUGS": "Médicaments sans ordonnance",
    "PRESCRIPTION": "Médicaments sur ordonnance",
    "HOMEOPATHIC": "Homéopathique",
    "ETHICAL": "Spécialité médicale",
    "SCHEDULE D": "Annexe D",
    "NARCOTICS (CDSA I)": "Stupéfiants (LRCDAS I)",
    "TARGETED SUBSTANCES (CDSA IV)": "Substances ciblées (LRCDAS IV)",
    "CONTROLLED DRUGS (CDSA IV)": "Drogues contrôlées (LRCDAS IV)",
    "SCHEDULE C": "Annexe C",
    "CONTROLLED DRUGS (CDSA I)": "Drogues contrôlées (LRCDAS I)",
    "CONTROLLED DRUGS (CDSA III)": "Drogues contrôlées (LRCDAS III)",
    "NARCOTICS (CDSA II)": "Stupéfiants (LRCDAS II)",
    "PRESCRIPTION RECOMMENDED": "Médicaments sur ordonnance recommandés",
    "COVID-19 - IO - AUTHORIZATION": "COVID-19 - AU - Autorisation",
}
