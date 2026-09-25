"""Constants for IRCC's Express Entry rounds-of-invitations JSON feed.

Verified live 2026-09-18 against both language variants: HTTP 200,
`Content-Type: application/json` with no charset parameter, 445 rounds
from drawNumber 1 (2015-01-31) to the present, newest first. The feed has
no documented rate limit or pagination -- it is one static file -- so this
module uses a conservative limiter and a multi-hour cache TTL, since a new
round is published roughly weekly, not continuously.
"""

BASE_URL_EN = "https://www.canada.ca/content/dam/ircc/documents/json/ee_rounds_123_en.json"
BASE_URL_FR = "https://www.canada.ca/content/dam/ircc/documents/json/ee_rounds_123_fr.json"

CATALOGUE_PAGE_URL = (
    "https://www.canada.ca/en/immigration-refugees-citizenship/services/"
    "immigrate-canada/express-entry/rounds-invitations.html"
)
DETAILS_URL_PREFIX = "https://www.canada.ca"

RATE_LIMIT_SOURCE = "ircc-express-entry"
RATE_LIMIT_PER_SECOND = 1.0
RATE_LIMIT_CAPACITY = 2.0

CACHE_TTL_SECONDS = 6 * 60 * 60

ROUNDS_LIMIT_DEFAULT = 20
ROUNDS_LIMIT_MAX = 1000
