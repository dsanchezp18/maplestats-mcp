"""Constants for the StatCan Web Data Service (WDS) submodule.

Base URL, rate limit, and cache TTLs per the official user guide
(https://www.statcan.gc.ca/en/developers/wds/user-guide) and the
benchmark audit in docs/statcan-api-standard.md.
"""

BASE_URL = "https://www150.statcan.gc.ca/t1/wds/rest/"

# StatCan documents 25 req/s per IP; stay conservatively below it.
RATE_LIMIT_SOURCE = "statcan-wds"
RATE_LIMIT_PER_SECOND = 20.0
RATE_LIMIT_CAPACITY = 20.0

CACHE_TTL_CUBES_LIST_SECONDS = 60 * 60  # 1h
CACHE_TTL_CUBE_METADATA_SECONDS = 24 * 60 * 60  # 24h
CACHE_TTL_CODE_SETS_SECONDS = 7 * 24 * 60 * 60  # 7d
CACHE_TTL_OBSERVATIONS_SECONDS = 60 * 60  # 1h

# WDS coordinates are always exactly this many dot-separated dimensions.
COORDINATE_DIMENSIONS = 10

# Response caps. Uncapped, wds_search_cubes with no query was 4.4 MB, one census
# table's metadata 1.25 MB and getCodeSets 309 kB (checked 2026-10-02).
SEARCH_LIMIT_DEFAULT = 25
SEARCH_LIMIT_MAX = 500
MEMBER_LIMIT_DEFAULT = 100
MEMBER_LIMIT_MAX = 2000
# wds_get_leaf_members: 18-10-0004's 249 CPI leaves and 36-10-0434's 188 NAICS
# leaves fit in one page; a census geography does not.
LEAF_LIMIT_DEFAULT = 500
# Footnotes, not members, made most of a metadata answer: 28.7 of 36.6 KB for
# 14-10-0287 on 2026-11-03, each in English and French. The cap counts distinct
# texts (client.get_cube_metadata merges repeats); footnote_limit raises it.
FOOTNOTE_LIMIT_DEFAULT = 10
CODE_SET_LIMIT_DEFAULT = 100

# wds_query_series: the server runs one read-only SQL query over the fetched
# observations and returns only its result. The vector cap keeps it a "handful
# of series" tool (whole tables go to wds_get_full_table_download); 3,000
# periods reaches back to 1914 for a monthly series (the CPI has 1,353).
QUERY_MAX_VECTORS = 20

# WDS refuses more than 300 objects in one list (HTTP 416, "The number of object in
# the list exceeds the limit - 300", live 2026-11-03) and answers a vector id past a
# 32-bit integer with HTTP 406 "JSON syntax error". Both are checked before the call,
# so a caller gets a clear invalid_input instead of an upstream error to retry.
WDS_MAX_LIST = 300
MAX_VECTOR_ID = 2_147_483_647
QUERY_MAX_LATEST_N = 3000
# Inline vector data: vectors x latest_n periods. 300 vectors x 5,000 periods
# would put ~1.5 M observations (hundreds of MB) in one reply; 60,000 still
# covers 20 monthly series back to 1775 or 300 series over 16 years.
INLINE_MAX_OBSERVATIONS = 60_000
QUERY_ROW_CAP = 500
QUERY_MAX_SQL_CHARS = 10_000
QUERY_MAX_SECONDS = 20.0
# The 500-row cap did not bound bytes: `SELECT repeat('x', 10000000) FROM
# range(500)` produced 5 GB of text (2026-11-03). `SELECT * FROM obs LIMIT 500`
# is about 300,000 characters, so the cap leaves room for that (the response
# budget middleware then trims rows) and stops anything far past it.
QUERY_MAX_RESULT_CHARS = 1_000_000
# One text cell: list(value) over 3,000 periods is about 20,000 characters.
QUERY_MAX_CELL_CHARS = 50_000

# The cube list is about 5 MB. Probed 2026-09-27 from GitHub runners: usually
# under a second, but one runner took 31-70 s on every try, past the shared
# 30 s default.
CUBES_LIST_TIMEOUT_SECONDS = 120.0

# Where a value a table leaves ".." (not available) for its latest periods is
# published instead, by product id: the series' members that must match (dimension
# name -> member name, English), then where the value is, in English and French,
# as the end of a sentence starting "StatCan publishes". Only pairs
# checked live go here. 36-10-0711's current-dollar "All industries" series is ".."
# for 2024 and 2025 in every province and territory (2026-11-09), while 36-10-0222
# (expenditure-based, annual) has current-price GDP for both years: Alberta 474,050
# and 482,370 million dollars (2023: 438,874.6 at basic prices in 0711, 453,093 at
# market prices in 0222). 36-10-0402, which 0711 replaced, is ".."
# for Alberta from 2022, so it is no alternative.
UNAVAILABLE_ELSEWHERE: dict[int, tuple[dict[str, str], str, str]] = {
    36100711: (
        {
            "Prices": "Current dollars",
            "North American Industry Classification System (NAICS)": "All industries",
        },
        (
            "current-price GDP for these years in table 36-10-0222-01 (GDP, expenditure-based, "
            "provincial and territorial, annual: 'Current prices', 'Gross domestic product at "
            "market prices'). That is GDP at market prices, not basic prices, so it differs from "
            "this table's total by taxes less subsidies on products; say which one you report."
        ),
        (
            "le PIB en dollars courants pour ces années dans le tableau 36-10-0222-01 (PIB en "
            "termes de dépenses, provinces et territoires, annuel : « Aux prix courants », « Produit "
            "intérieur brut aux prix du marché »). C'est le PIB aux prix du marché, pas aux prix "
            "de base : il diffère du total de ce tableau des impôts moins les subventions sur les "
            "produits ; précisez lequel vous donnez."
        ),
    ),
}
