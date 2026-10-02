"""Constants for the BC lobbyists registry module (checked live 2026-10-02)."""

SITE = "https://www.lobbyistsregistrar.bc.ca"
DOWNLOAD_URL = SITE + "/app/secure/orl/lrs/do/mssDtstRprt"
OPEN_DATA_PAGE = SITE + "/the-registry/open-data/"
LICENCE_URL = (
    SITE + "/media/1285/open-data-licence-for-the-office-of-the-registrar-of-lobbyists-"
    "for-british-columbia.pdf"
)
REGISTRATION_ZIP = "ORL_Registration_Data.zip"
ACTIVITY_ZIP = "ORL_LAR_Data.zip"

# Attribution statement the licence prescribes when the ORL names none (term 4).
ATTRIBUTION = (
    "Contains information licensed under the Open Data Licence for the Office of the "
    "Registrar of Lobbyists for British Columbia."
)
# What this module leaves out, because licence term 6(a) grants no right to
# Personal Information (FOIPPA Schedule 1: information about an identifiable
# individual other than contact information).
OMITTED_EN = (
    "Left out under the licence's Personal Information exemption: street addresses, "
    "telephone numbers, lobbyists' political, sponsorship and recall contribution "
    "flags, gifts to office holders, lobbyists' former public offices and exemption "
    "decisions, codes of conduct, and the legacy target-contact files. Names, titles and "
    "organizations appear only in their business capacity (contact information)."
)
OMITTED_FR = (
    "Exclus en vertu de l'exemption des renseignements personnels de la licence : adresses, "
    "numéros de téléphone, indicateurs de contributions politiques, de parrainage et de "
    "révocation des lobbyistes, cadeaux aux titulaires de charge, anciennes charges "
    "publiques et décisions d'exemption des lobbyistes, codes de conduite et fichiers "
    "historiques des personnes ciblées. Les noms, titres et organisations figurent "
    "uniquement à titre professionnel (coordonnées)."
)

RATE_LIMIT_SOURCE = "bc_lobbyists"
RATE_LIMIT_PER_SECOND = 0.5
RATE_LIMIT_CAPACITY = 1.0

# The files are rebuilt monthly (members dated 2026-09-20 on 2026-10-02).
DATA_TTL_SECONDS = 12 * 60 * 60
# Live sizes: registrations 28 MB (260 MB unpacked, 94 MB for the largest
# member), activity 5.5 MB (39 MB unpacked).
MAX_ZIP_BYTES = 150 * 1024 * 1024
MAX_MEMBER_BYTES = 200 * 1024 * 1024
DOWNLOAD_TIMEOUT_SECONDS = 240.0

SEARCH_DEFAULT_LIMIT = 25
SEARCH_MAX_LIMIT = 200
SUMMARY_DEFAULT_TOP = 20
SUMMARY_MAX_TOP = 200
# Topic text runs to several thousand characters; searches show a shortened copy.
TOPIC_PREVIEW_CHARS = 300
SEARCH_TOPICS_SHOWN = 5
SEARCH_LOBBYISTS_SHOWN = 15

LTA_START = "2020-05-04"

# Labels shown in the language asked for; the data itself is English only.
LABELS: dict[str, tuple[str, str]] = {
    "consultant": ("Consultant lobbyist registration", "Inscription de lobbyiste-conseil"),
    "in_house": ("In-house (organization) registration", "Inscription d'organisation (interne)"),
    "lta": (
        "Lobbyists Transparency Act (from 2020-05-04)",
        "Loi sur la transparence (dès le 2020-05-04)",
    ),
    "legacy": (
        "Lobbyists Registration Act (before 2020-05-04)",
        "Loi sur l'inscription (avant le 2020-05-04)",
    ),
    "active": ("Active", "Active"),
    "ended": ("Ended", "Terminée"),
}

GROUPS = ("client", "ministry", "office_holder", "subject_matter", "lobbyist", "month", "year")
CODE_KINDS = ("subject_matters", "intended_outcomes", "ministries")
