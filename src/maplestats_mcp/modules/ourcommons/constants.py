"""Constants for the House of Commons open data module.

Fetched live on 2026-09-30 from www.ourcommons.ca/en/open-data, and re-checked
2026-11-03. Feeds exist per language, and a member's page accepts the bare person id
in place of "first-last(id)". The French feeds moved to French paths on
www.noscommunes.ca by 2026-11-02: /members/fr/... now redirects to a 404 error page,
so French uses /deputes/fr/recherche, /position-des-partis, /conseil-des-ministres
and /{id}/fonctions. English is unchanged (/Members/en/..., as the open-data page
publishes it). An unknown person id still answers 302 to the error page in both.
"""

DOMAIN = "www.ourcommons.ca"
SITE = f"https://{DOMAIN}"
SITE_FR = "https://www.noscommunes.ca"


class _ByLang:
    """A URL template per language, used as `TEMPLATE.format(lang=..., ...)`."""

    def __init__(self, en: str, fr: str) -> None:
        self._templates = {"en": en, "fr": fr}

    def format(self, *, lang: str, **values: object) -> str:
        return self._templates[lang].format(**values)


MEMBERS_URL = _ByLang(SITE + "/Members/en/search/XML", SITE_FR + "/deputes/fr/recherche/XML")
ROLES_URL = _ByLang(
    SITE + "/Members/en/{person_id}/roles/XML", SITE_FR + "/deputes/fr/{person_id}/fonctions/XML"
)
STANDINGS_URL = _ByLang(
    SITE + "/Members/en/party-standings/XML", SITE_FR + "/deputes/fr/position-des-partis/XML"
)
# English moved from /Members/en/ministries to /members/en/ministry (found 2026-11-03 through
# the French page's language switch); the open-data page still links the old address.
MINISTRY_URL = _ByLang(
    SITE + "/members/en/ministry/xml", SITE_FR + "/deputes/fr/conseil-des-ministres/XML"
)
OPEN_DATA_PAGE = SITE + "/en/open-data"

# Members' expenditure reports (proactive disclosure), checked live 2026-11-07. The open-data
# page still shows the old PublicDisclosure/MemberExpenditures.aspx?Id=<document id> pattern,
# which answers 404; the reports moved to /ProactiveDisclosure, one page per fiscal quarter
# (/{fiscal year}/{quarter}, no id needed) holding the report's id, which names the summary
# CSV, and one id per member, which names that member's travel, hospitality and contract CSVs.
# French is on www.noscommunes.ca under /deputes with voyage, accueil and contrat.
DISCLOSURE_URL = _ByLang(
    SITE + "/ProactiveDisclosure/en/members", SITE_FR + "/ProactiveDisclosure/fr/deputes"
)
DETAIL_PATHS = {
    "en": {"travel": "travel", "hospitality": "hospitality", "contract": "contract"},
    "fr": {"travel": "voyage", "hospitality": "accueil", "contract": "contrat"},
}
CACHE_TTL_EXPENDITURES_SECONDS = 6 * 60 * 60
EXPENDITURES_LIMIT_DEFAULT = 50
EXPENDITURES_LIMIT_MAX = 500

RATE_LIMIT_SOURCE = "ourcommons"
RATE_LIMIT_PER_SECOND = 2.0
RATE_LIMIT_CAPACITY = 4.0

CACHE_TTL_LIST_SECONDS = 60 * 60
CACHE_TTL_ROLES_SECONDS = 6 * 60 * 60

MEMBERS_LIMIT_DEFAULT = 50
MEMBERS_LIMIT_MAX = 400

PROVENANCE_SOURCE = "house-of-commons-open-data"

# Each feed names parties and provinces in its own language (read live
# 2026-10-03: en "NDP", "Green Party", "British Columbia"; fr "NPD",
# "Parti vert", "Colombie-Britannique"), so a filter typed in one language
# matched nothing in the other. Each group is (the feed's en and fr values,
# extra exact-match aliases such as abbreviations). A filter that is a
# substring of a value, or equals an alias, matches every value of its group.
PARTY_GROUPS: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("Conservative", "Conservateur"), ("cpc", "pcc", "conservative party", "parti conservateur")),
    (("Liberal", "Libéral"), ("lpc", "plc", "liberal party", "parti liberal")),
    (("Bloc Québécois",), ("bq",)),
    (
        # The expenditure reports spell the caucus out in full.
        ("NDP", "NPD", "New Democratic Party", "Nouveau Parti démocratique"),
        ("new democratic party", "new democrats", "nouveau parti democratique"),
    ),
    (("Green Party", "Parti vert"), ("green", "gpc", "pvc", "vert", "verts")),
    (("Independent", "Indépendant"), ("ind",)),
)
PROVINCE_GROUPS: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("Alberta",), ("ab",)),
    (("British Columbia", "Colombie-Britannique"), ("bc", "cb")),
    (("Manitoba",), ("mb",)),
    (("New Brunswick", "Nouveau-Brunswick"), ("nb",)),
    (("Newfoundland and Labrador", "Terre-Neuve-et-Labrador"), ("nl", "tnl")),
    (("Nova Scotia", "Nouvelle-Écosse"), ("ns", "ne")),
    (("Northwest Territories", "Territoires du Nord-Ouest"), ("nt", "nwt", "tno")),
    (("Nunavut",), ("nu",)),
    (("Ontario",), ("on",)),
    (("Prince Edward Island", "Île-du-Prince-Édouard"), ("pe", "pei", "ipe")),
    (("Quebec", "Québec"), ("qc",)),
    (("Saskatchewan",), ("sk",)),
    (("Yukon",), ("yt", "yk")),
)
