"""Constants for the House of Commons open data module.

Fetched live on 2026-09-30 from www.ourcommons.ca/en/open-data. Feeds exist per language
(`/members/en/...` and `/members/fr/...`), and a member's page accepts the
bare person id in place of "first-last(id)".
"""

DOMAIN = "www.ourcommons.ca"
SITE = f"https://{DOMAIN}"

MEMBERS_URL = SITE + "/members/{lang}/search/xml"
ROLES_URL = SITE + "/members/{lang}/{person_id}/roles/xml"
STANDINGS_URL = SITE + "/members/{lang}/party-standings/xml"
MINISTRY_URL = SITE + "/members/{lang}/ministries/xml"
OPEN_DATA_PAGE = SITE + "/en/open-data"

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
        ("NDP", "NPD"),
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
