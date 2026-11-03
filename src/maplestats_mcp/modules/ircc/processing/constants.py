"""Constants for IRCC's processing-times JSON files on canada.ca.

IRCC publishes no API for its "Check processing times" tool; the page reads
these static files (found in its source on 2026-11-03, each fetched in both
languages that day: HTTP 200, application/json, UTF-8, some with a BOM).

- data-ptime-<lang>.json: times by country of residence for 8 application
  types (visitor visa, super visa, study and work permits from outside
  Canada, dependent and adopted children, government-assisted and privately
  sponsored refugees). Each type is an object of ISO 3166 alpha-2 code ->
  text ("26 days", "No processing time available", "Not enough data") plus
  a "lastupdated" date; privately sponsored refugees have an object
  {"sponsor": ..., "refugee": ...} per country.
- data-ptime-non-country-<lang>.json: types with one time for everyone
  (applications from inside Canada, ETA, IEC, citizenship certificates and
  searches, PR cards, document amendments), grouped, with
  "default-update": {"lastupdated": "October 29, 2026"}.
- flpt-<lang>.json: forward-looking times for permanent residence and
  citizenship programs ("current-flpt": "About 6 months"), people waiting
  ("total-people"), and "default-update": {"flpt_lastupdated",
  "flpt_interval": "monthly"}. Its "people-ahead"/"wait-times" keys (per
  application month, about 3,600 each) are not read.
- flpt-by-week-<lang>.json: the same for study and work permit extensions
  ("SP-EXT", "WP-EXT"), with "tr-last-updated".
- data-country-name-<lang>.json: {"country-name": {code: name}}; it lacks
  two codes the times use (CA and GL on 2026-11-03).

French files escape accents as HTML entities ("Pas assez de donn&eacute;es"),
so every string is unescaped. The canada.ca host refused curl's TLS
fingerprint that day (HTTP/2 stream reset) but answers shared/http.py's
client, which is what this module uses.
"""

from __future__ import annotations

JSON_BASE = "https://www.canada.ca/content/dam/ircc/documents/json/"
FILE_PTIME = "data-ptime"
FILE_NON_COUNTRY = "data-ptime-non-country"
FILE_FLPT = "flpt"
FILE_FLPT_WEEK = "flpt-by-week"
FILE_COUNTRIES = "data-country-name"
TIME_FILES = (FILE_PTIME, FILE_NON_COUNTRY, FILE_FLPT, FILE_FLPT_WEEK)

PAGE_URL_EN = (
    "https://www.canada.ca/en/immigration-refugees-citizenship/services/application/"
    "check-processing-times.html"
)
PAGE_URL_FR = (
    "https://www.canada.ca/fr/immigration-refugies-citoyennete/services/demande/"
    "verifier-delais-traitement.html"
)

RATE_LIMIT_SOURCE = "ircc-processing-times"
RATE_LIMIT_PER_SECOND = 1.0
RATE_LIMIT_CAPACITY = 4.0

# IRCC replaces the files weekly (temporary residence) or monthly (permanent
# residence); an hour keeps a session's repeated calls off canada.ca.
CACHE_TTL_SECONDS = 60 * 60

# Codes the time files use that data-country-name lacks (ISO 3166 names).
EXTRA_COUNTRIES: dict[str, tuple[str, str]] = {
    "CA": ("Canada", "Canada"),
    "GL": ("Greenland", "Groenland"),
}

# Category ids and their labels.
CATEGORIES: dict[str, tuple[str, str]] = {
    "visit": ("Visitors and travel", "Visiteurs et voyages"),
    "study": ("Study", "Études"),
    "work": ("Work", "Travail"),
    "family": ("Family sponsorship", "Parrainage familial"),
    "economic": ("Economic immigration", "Immigration économique"),
    "refugees": ("Refugees and humanitarian", "Réfugiés et motifs d'ordre humanitaire"),
    "citizenship": ("Citizenship", "Citoyenneté"),
    "documents": ("PR cards and documents", "Cartes de RP et documents"),
    "other": ("Other", "Autres"),
}

# Application type id (IRCC's own JSON key) -> (file, category, label en, label fr).
# Keys read from the files on 2026-11-03; labels follow the program names on
# IRCC's pages. "roc" in IRCC's keys is "rest of Canada" (outside Quebec).
# A key found in a file but not listed here is still returned, labelled with
# the key itself, so a new type IRCC adds is not lost.
TYPES: dict[str, tuple[str, str, str, str]] = {
    # data-ptime: by country of residence
    "visitor-outside-canada": (
        FILE_PTIME,
        "visit",
        "Visitor visa, applying from outside Canada",
        "Visa de visiteur, demande présentée à l'extérieur du Canada",
    ),
    "supervisa": (
        FILE_PTIME,
        "visit",
        "Parent and grandparent super visa",
        "Super visa pour parents et grands-parents",
    ),
    "study": (
        FILE_PTIME,
        "study",
        "Study permit, applying from outside Canada",
        "Permis d'études, demande présentée à l'extérieur du Canada",
    ),
    "work": (
        FILE_PTIME,
        "work",
        "Work permit, applying from outside Canada",
        "Permis de travail, demande présentée à l'extérieur du Canada",
    ),
    "child_dependent": (
        FILE_PTIME,
        "family",
        "Dependent child sponsorship (permanent residence)",
        "Parrainage d'un enfant à charge (résidence permanente)",
    ),
    "child_adopted": (
        FILE_PTIME,
        "family",
        "Adopted child sponsorship (permanent residence)",
        "Parrainage d'un enfant adopté (résidence permanente)",
    ),
    "refugees_gov": (
        FILE_PTIME,
        "refugees",
        "Government-assisted refugees",
        "Réfugiés pris en charge par le gouvernement",
    ),
    "refugees_private": (
        FILE_PTIME,
        "refugees",
        "Privately sponsored refugees (sponsor application and refugee application)",
        "Réfugiés parrainés par le secteur privé (demande du répondant et demande du réfugié)",
    ),
    # data-ptime-non-country
    "visitor_inside_canada": (
        FILE_NON_COUNTRY,
        "visit",
        "Visitor visa, applying from inside Canada",
        "Visa de visiteur, demande présentée au Canada",
    ),
    "visitor_extension": (
        FILE_NON_COUNTRY,
        "visit",
        "Visitor record (extend a stay as a visitor)",
        "Fiche du visiteur (prolonger un séjour comme visiteur)",
    ),
    "study_extension": (
        FILE_NON_COUNTRY,
        "study",
        "Study permit, applying from inside Canada",
        "Permis d'études, demande présentée au Canada",
    ),
    "work_extension": (
        FILE_NON_COUNTRY,
        "work",
        "Work permit, applying from inside Canada",
        "Permis de travail, demande présentée au Canada",
    ),
    "iec": (
        FILE_NON_COUNTRY,
        "work",
        "International Experience Canada work permit",
        "Permis de travail d'Expérience internationale Canada",
    ),
    "iec_past": (
        FILE_NON_COUNTRY,
        "work",
        "International Experience Canada work permit, previous season",
        "Permis de travail d'Expérience internationale Canada, saison précédente",
    ),
    "eta": (
        FILE_NON_COUNTRY,
        "visit",
        "Electronic Travel Authorization (eTA)",
        "Autorisation de voyage électronique (AVE)",
    ),
    "skilled_trades_ee": (
        FILE_NON_COUNTRY,
        "economic",
        "Federal Skilled Trades Program (Express Entry)",
        "Programme des travailleurs de métiers spécialisés (fédéral) (Entrée express)",
    ),
    "cit_resumption": (
        FILE_NON_COUNTRY,
        "citizenship",
        "Citizenship resumption",
        "Réintégration dans la citoyenneté",
    ),
    "cit_renunciation": (
        FILE_NON_COUNTRY,
        "citizenship",
        "Citizenship renunciation",
        "Répudiation de la citoyenneté",
    ),
    "cit_search": (
        FILE_NON_COUNTRY,
        "citizenship",
        "Search of citizenship records",
        "Recherche dans les registres de citoyenneté",
    ),
    "cit_adoption_part1": (
        FILE_NON_COUNTRY,
        "citizenship",
        "Citizenship for a person adopted by a Canadian, part 1",
        "Citoyenneté pour une personne adoptée par un Canadien, partie 1",
    ),
    "new_pr": (
        FILE_NON_COUNTRY,
        "documents",
        "Permanent resident card, new permanent residents",
        "Carte de résident permanent, nouveaux résidents permanents",
    ),
    "existing_pr": (
        FILE_NON_COUNTRY,
        "documents",
        "Permanent resident card, renewal or replacement",
        "Carte de résident permanent, renouvellement ou remplacement",
    ),
    "vos": (
        FILE_NON_COUNTRY,
        "documents",
        "Verification of status",
        "Vérification du statut",
    ),
    "replacement": (
        FILE_NON_COUNTRY,
        "documents",
        "Replacement of a valid immigration document",
        "Remplacement d'un document d'immigration valide",
    ),
    "amend_imm": (
        FILE_NON_COUNTRY,
        "documents",
        "Amendment of an immigration document (permanent residence)",
        "Modification d'un document d'immigration (résidence permanente)",
    ),
    "amend_tr": (
        FILE_NON_COUNTRY,
        "documents",
        "Amendment of a temporary resident document",
        "Modification d'un document de résident temporaire",
    ),
    "sawp_current": (
        FILE_NON_COUNTRY,
        "work",
        "Seasonal Agricultural Worker Program work permit",
        "Permis de travail du Programme des travailleurs agricoles saisonniers",
    ),
    # flpt: permanent residence and citizenship, forward-looking
    "aip": (
        FILE_FLPT,
        "economic",
        "Atlantic Immigration Program",
        "Programme d'immigration au Canada atlantique",
    ),
    "caregiver": (
        FILE_FLPT,
        "economic",
        "Caregivers (permanent residence)",
        "Aides familiaux (résidence permanente)",
    ),
    "cec": (
        FILE_FLPT,
        "economic",
        "Canadian Experience Class (Express Entry)",
        "Catégorie de l'expérience canadienne (Entrée express)",
    ),
    "fsw": (
        FILE_FLPT,
        "economic",
        "Federal Skilled Worker Program (Express Entry)",
        "Programme des travailleurs qualifiés (fédéral) (Entrée express)",
    ),
    "pnp-ee": (
        FILE_FLPT,
        "economic",
        "Provincial Nominee Program, through Express Entry",
        "Programme des candidats des provinces, par Entrée express",
    ),
    "pnp-base": (
        FILE_FLPT,
        "economic",
        "Provincial Nominee Program, outside Express Entry (paper or base)",
        "Programme des candidats des provinces, hors Entrée express",
    ),
    "qsw": (
        FILE_FLPT,
        "economic",
        "Quebec skilled workers (permanent residence)",
        "Travailleurs qualifiés sélectionnés par le Québec (résidence permanente)",
    ),
    "quebec-business": (
        FILE_FLPT,
        "economic",
        "Quebec business immigrants",
        "Gens d'affaires sélectionnés par le Québec",
    ),
    "self-employed": (
        FILE_FLPT,
        "economic",
        "Self-employed persons program",
        "Programme des travailleurs autonomes",
    ),
    "startup-visa": (
        FILE_FLPT,
        "economic",
        "Start-up Visa Program",
        "Programme de visa pour démarrage d'entreprise",
    ),
    "spousal-canada-roc": (
        FILE_FLPT,
        "family",
        "Spouse or partner sponsorship, living in Canada (outside Quebec)",
        "Parrainage d'un époux ou conjoint vivant au Canada (hors Québec)",
    ),
    "spousal-canada-quebec": (
        FILE_FLPT,
        "family",
        "Spouse or partner sponsorship, living in Canada (Quebec)",
        "Parrainage d'un époux ou conjoint vivant au Canada (Québec)",
    ),
    "spousal-abroad-roc": (
        FILE_FLPT,
        "family",
        "Spouse or partner sponsorship, living outside Canada (outside Quebec)",
        "Parrainage d'un époux ou conjoint vivant à l'étranger (hors Québec)",
    ),
    "spousal-abroad-quebec": (
        FILE_FLPT,
        "family",
        "Spouse or partner sponsorship, living outside Canada (Quebec)",
        "Parrainage d'un époux ou conjoint vivant à l'étranger (Québec)",
    ),
    "pgp-roc": (
        FILE_FLPT,
        "family",
        "Parents and grandparents sponsorship (outside Quebec)",
        "Parrainage des parents et grands-parents (hors Québec)",
    ),
    "pgp-quebec": (
        FILE_FLPT,
        "family",
        "Parents and grandparents sponsorship (Quebec)",
        "Parrainage des parents et grands-parents (Québec)",
    ),
    "government-refugees-roc": (
        FILE_FLPT,
        "refugees",
        "Government-assisted refugees, permanent residence (outside Quebec)",
        "Réfugiés pris en charge par le gouvernement, résidence permanente (hors Québec)",
    ),
    "government-refugees-quebec": (
        FILE_FLPT,
        "refugees",
        "Government-assisted refugees, permanent residence (Quebec)",
        "Réfugiés pris en charge par le gouvernement, résidence permanente (Québec)",
    ),
    "private-refugees-roc": (
        FILE_FLPT,
        "refugees",
        "Privately sponsored refugees, permanent residence (outside Quebec)",
        "Réfugiés parrainés par le secteur privé, résidence permanente (hors Québec)",
    ),
    "private-refugees-quebec": (
        FILE_FLPT,
        "refugees",
        "Privately sponsored refugees, permanent residence (Quebec)",
        "Réfugiés parrainés par le secteur privé, résidence permanente (Québec)",
    ),
    "protected-persons-in-canada-roc": (
        FILE_FLPT,
        "refugees",
        "Protected persons in Canada, permanent residence (outside Quebec)",
        "Personnes protégées au Canada, résidence permanente (hors Québec)",
    ),
    "protected-persons-in-canada-quebec": (
        FILE_FLPT,
        "refugees",
        "Protected persons in Canada, permanent residence (Quebec)",
        "Personnes protégées au Canada, résidence permanente (Québec)",
    ),
    "dependants-abroad-roc": (
        FILE_FLPT,
        "refugees",
        "Dependants abroad of protected persons (outside Quebec)",
        "Personnes à charge à l'étranger de personnes protégées (hors Québec)",
    ),
    "dependants-abroad-quebec": (
        FILE_FLPT,
        "refugees",
        "Dependants abroad of protected persons (Quebec)",
        "Personnes à charge à l'étranger de personnes protégées (Québec)",
    ),
    "humanitarian-roc": (
        FILE_FLPT,
        "refugees",
        "Humanitarian and compassionate grounds (outside Quebec)",
        "Considérations d'ordre humanitaire (hors Québec)",
    ),
    "humanitarian-quebec": (
        FILE_FLPT,
        "refugees",
        "Humanitarian and compassionate grounds (Quebec)",
        "Considérations d'ordre humanitaire (Québec)",
    ),
    "citizen-grants": (
        FILE_FLPT,
        "citizenship",
        "Citizenship grant (becoming a citizen)",
        "Attribution de la citoyenneté (devenir citoyen)",
    ),
    "citizen-proofs": (
        FILE_FLPT,
        "citizenship",
        "Citizenship certificate (proof of citizenship)",
        "Certificat de citoyenneté (preuve de citoyenneté)",
    ),
    # flpt-by-week: in-Canada extensions, forward-looking
    "WP-EXT": (
        FILE_FLPT_WEEK,
        "work",
        "Work permit extension from inside Canada, estimate for a new application",
        "Prolongation du permis de travail au Canada, estimation pour une nouvelle demande",
    ),
    "SP-EXT": (
        FILE_FLPT_WEEK,
        "study",
        "Study permit extension from inside Canada, estimate for a new application",
        "Prolongation du permis d'études au Canada, estimation pour une nouvelle demande",
    ),
}

# Days per unit, for the approximate comparable figure only.
DAYS_PER_UNIT: dict[str, float] = {
    "minutes": 1 / 1440,
    "hours": 1 / 24,
    "days": 1.0,
    "weeks": 7.0,
    "months": 365.25 / 12,
    "years": 365.25,
}
