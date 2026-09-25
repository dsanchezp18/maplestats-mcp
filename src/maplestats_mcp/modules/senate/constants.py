"""Constants for the Senate of Canada votes pages.

Confirmed live 2026-09-24: /en/in-the-chamber/votes/<session> lists the
session's votes in table#votes-table (sessions from 42-1 on); each
vote's page, /en/in-the-chamber/votes/details/<id>/<session>, lists
senators in table#sc-vote-details-table with Yea/Nay/Abstention columns
where the marked column carries data-order="aaa". French pages live
under /fr/dans-la-chambre/votes/ with the same ids.
"""

BASE_URL = "https://sencanada.ca"
LIST_PATHS = {"en": "/en/in-the-chamber/votes/", "fr": "/fr/dans-la-chambre/votes/"}
DETAIL_PATHS = {
    "en": "/en/in-the-chamber/votes/details/",
    "fr": "/fr/dans-la-chambre/votes/details/",
}

RATE_LIMIT_SOURCE = "senate"
RATE_LIMIT_PER_SECOND = 1.0
RATE_LIMIT_CAPACITY = 3.0

CACHE_TTL_SECONDS = 60 * 60
