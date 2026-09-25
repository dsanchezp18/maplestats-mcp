"""Constants for the Canada Gazette.

Confirmed live 2026-09-23:
- RSS: /rss/p1-{eng|fra}.xml (435 issues) and /rss/p2-{eng|fra}.xml
  (232 issues); there is no Part III feed. Items are issues, with titles
  like "Canada Gazette - Part I, September 19, 2026, volume 160, number 38".
- Issue page: /rp-pr/p{1|2}/{yyyy}/{yyyy-mm-dd}/html/index-{eng|fra}.html.
  Part I groups links under h2 (section), h3 (organization) and h4 (act);
  each link points to a section page anchor such as notice-avis-eng.html#ne1.
  Part II lists one page per instrument (sor-dors184-eng.html).
- A Part I notice runs from its anchor to the next anchored heading.
"""

BASE_URL = "https://gazette.gc.ca"
FEED_URL = BASE_URL + "/rss/p{part}-{lang}.xml"
ISSUE_URL = BASE_URL + "/rp-pr/p{part}/{year}/{date}/html/index-{lang}.html"
ALLOWED_HOSTS = frozenset({"gazette.gc.ca", "www.gazette.gc.ca"})

RATE_LIMIT_SOURCE = "gazette"
RATE_LIMIT_PER_SECOND = 2.0
RATE_LIMIT_CAPACITY = 4.0

CACHE_TTL_FEED_SECONDS = 60 * 60
CACHE_TTL_PAGE_SECONDS = 24 * 60 * 60

ISSUES_DEFAULT = 10
ISSUES_MAX = 100
NOTICE_TEXT_MAX = 20_000
