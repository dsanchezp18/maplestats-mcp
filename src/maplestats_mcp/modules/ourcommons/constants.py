"""Constants for the House of Commons open data module.

Fetched live on 2026-09-30 from www.ourcommons.ca/en/open-data. robots.txt
disallows only /Embed/, /ErrorPage/, /ParlDataWidgets/, /PublicationSearch/
and /Search/; the feeds below are not among them. Feeds exist per language
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
