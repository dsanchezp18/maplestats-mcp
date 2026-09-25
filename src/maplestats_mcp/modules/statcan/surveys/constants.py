"""Constants for StatCan's survey directory and IMDB survey metadata.

Confirmed live 2026-09-21, closing the "surveys A-Z directory" gap
flagged as deferred in an earlier pass. Two systems, tied together by
one numeric ID:

1. The survey directory (`www150.statcan.gc.ca/n1/en/type/surveys`,
   `/n1/fr/type/enquetes` in French) -- the same Drupal 10 platform as
   Reference/Analysis, but a genuinely different page shape (a single
   A-Z listing, ~899 surveys confirmed live, not the faceted
   `#ndm-results` search view), needing the same session-cookie
   warm-up quirk to render its `<a href="/n1/en/surveys/{id}">`
   listing links.
2. IMDB (Integrated Metadata Base, `www23.statcan.gc.ca/imdb/`) -- an
   older, separate Perl-CGI system (`p2SV.pl` for English,
   `p2SV_f.pl` for French; a `lang=fr` query parameter has no effect,
   confirmed live) holding each survey's actual "Definitions, data
   sources and methods" content: status, frequency, description,
   target population, sampling, data sources, and subjects. Confirmed
   live that the survey directory's numeric ID is exactly IMDB's own
   "Record number" (SDDS) for the same survey (id 5108 resolves to the
   same "Aboriginal Children's Survey" page on both systems), so the
   directory is the correct way to discover IDs for this API.
"""

SURVEY_LIST_URL_EN = "https://www150.statcan.gc.ca/n1/en/type/surveys"
SURVEY_LIST_URL_FR = "https://www150.statcan.gc.ca/n1/fr/type/enquetes"

IMDB_BASE_URL_EN = "https://www23.statcan.gc.ca/imdb/p2SV.pl"
IMDB_BASE_URL_FR = "https://www23.statcan.gc.ca/imdb/p2SV_f.pl"

RATE_LIMIT_SOURCE = "statcan-surveys"
RATE_LIMIT_PER_SECOND = 3.0
RATE_LIMIT_CAPACITY = 5.0

CACHE_TTL_LIST_SECONDS = 24 * 60 * 60
CACHE_TTL_METADATA_SECONDS = 24 * 60 * 60

SEARCH_LIMIT_DEFAULT = 20
SEARCH_LIMIT_MAX = 300
