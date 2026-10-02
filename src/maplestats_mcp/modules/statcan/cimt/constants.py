"""Constants for StatCan's Canadian International Merchandise Trade (CIMT) web application API.

Undocumented API, confirmed live 2026-10-02. The CIMT web application
(www150.statcan.gc.ca/n1/pub/71-607-x/2021004/exp-eng.htm for exports,
imp-eng.htm for imports) calls a JSON REST service at
/t1/cimt/rest/<method>/<positional path parameters>. The method names
and the order of their path parameters were read out of the page's own
JavaScript (2021004/js/cimt4.min.js) and every method was then called
live; nothing here comes from published documentation, because there is
none. The code lists the application uses (countries, US states,
provinces, units of measure, HS chapters, headings, HS6, HS8, HS10) are
static JavaScript files next to the page. StatCan can change either
without notice.

Quirks confirmed live (each one is handled in client.py):

- Without a `Referer` header from the 71-607-x pages the service answers
  HTTP 404 with an HTML error page, even though the same URL answers 200
  JSON with it. The header is what the web application's own browser
  requests send; this client sends the same one.
- A 9-digit or otherwise malformed commodity code, or a parameter value
  the service does not know, answers HTTP 406. A reference period after
  the latest published month answers HTTP 500. A well-formed request with
  no matching trade answers 200 with `{"count": 0, "trade": []}`.
- Exports are published at 8 digits (HS8) and imports at 10 digits
  (HS10); `hs6flag=1` aggregates both to 6 digits. A commodity code
  matches by prefix, but only at the level the flag selects: `27090010`
  with `hs6flag=1` returns no rows.
- `maxRows` truncates silently: `count` is the full row count and `trade`
  holds only the first `maxRows` rows in no particular order.
- `origin` is a parenthesised list, `(35,24)`. `(1)` is Canada as a
  whole; mixing 1 with a province returns only Canada.
- Exports include re-exports. In the chart endpoints the estimate flag
  `E` splits them: exports 1 = domestic value, 2 = re-export value,
  3 = domestic quantity; imports 1 = value, 2 = quantity. Flag 4
  (re-export quantity, exports only) is inferred: it is never used by the
  application's JavaScript, but 36,214,319 + 1,123 equals the report's
  36,215,442 for HS 710812 in July 2026. The report endpoint itself
  already adds domestic and re-export value together.
- Totals reconcile with WDS table 12-10-0011-01 (customs basis,
  unadjusted): July 2026 total exports 73,175,629,507 dollars here and
  73,175.6 million there, imports 71,965,730,064 and 71,965.7.
"""

BASE_URL = "https://www150.statcan.gc.ca/t1/cimt/rest"
CODES_BASE_URL = "https://www150.statcan.gc.ca/n1/pub/71-607-x/2021004"

# The service refuses requests without a Referer from the application's pages.
REFERER_BY_DIRECTION = {
    "exports": f"{CODES_BASE_URL}/exp-eng.htm",
    "imports": f"{CODES_BASE_URL}/imp-eng.htm",
}

# statcan.gc.ca/robots.txt asks for a 2 second crawl delay for all agents.
RATE_LIMIT_SOURCE = "statcan-cimt"
RATE_LIMIT_PER_SECOND = 0.5
RATE_LIMIT_CAPACITY = 1.0

CACHE_TTL_PERIODS_SECONDS = 60 * 60
CACHE_TTL_DATA_SECONDS = 60 * 60
CACHE_TTL_CODES_SECONDS = 7 * 24 * 60 * 60

# `trade_type` path parameter.
TRADE_TYPE = {"exports": 0, "imports": 1}

# Code-list identifiers in the URL path: the CIMT id for "all countries" and
# for the United States, the Canada-wide "province", and "all US states".
WORLD_ID = 1000
US_ID = 9
CANADA_ID = 1
ALL_STATES_ID = 100

# The large code lists are 2.5 MB (HS6), 3.3 MB (HS8) and 16 MB (HS10).
CODES_TIMEOUT_SECONDS = 120.0

ROWS_DEFAULT = 500
ROWS_MAX = 5000
SEARCH_LIMIT_DEFAULT = 20
SEARCH_LIMIT_MAX = 100

# The five-year window the chart endpoints return ends at the reference period.
CHART_YEARS = 5

# Province and territory codes are StatCan's two-digit SGC codes; the
# abbreviations are Canada Post's. provinces.js carries only the names.
PROVINCE_ABBREVIATIONS = {
    "NL": 10,
    "PE": 11,
    "NS": 12,
    "NB": 13,
    "QC": 24,
    "ON": 35,
    "MB": 46,
    "SK": 47,
    "AB": 48,
    "BC": 59,
    "YT": 60,
    "NT": 61,
    "NU": 62,
}

# What each estimate flag of the chart endpoints means, by direction.
ESTIMATE_MEASURES = {
    "exports": {
        1: "domestic_value",
        2: "reexport_value",
        3: "domestic_quantity",
        4: "reexport_quantity",
    },
    "imports": {1: "value", 2: "quantity"},
}
