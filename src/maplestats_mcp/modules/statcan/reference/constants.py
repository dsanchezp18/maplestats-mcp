"""Constants for StatCan's Drupal-based catalogue search views.

Confirmed live 2026-09-21. This one Drupal 10 faceted-search engine
backs at least three of StatCan's catalogues: "Reference resources"
(definitions, data sources, methods, and survey documentation --
distinct from The Daily (`modules/statcan/daily`), 2,031 documents
confirmed live), "Analysis" (analytical articles, "Stats in brief",
journals and periodicals -- 10,841+ documents confirmed live), and
"Data" (13,342+ items confirmed live) at
`www150.statcan.gc.ca/n1/en/type/{reference,analysis,data}`
respectively -- identical HTML structure, identical quirks, only the
path segment and document counts differ. No JSON API for any of them.

"Data" is not fully redundant with WDS/SDMX table search, confirmed
live: most of its results are ordinary table PIDs also reachable via
wds_/sdmx_, but it also indexes product families WDS has no discovery
path for at all -- notably Public Use Microdata Files (PUMFs, category
"Public use microdata"; confirmed live: searching "Public Use
Microdata Files" here returns 144 results, e.g. catalogue number
71M0001X for the Labour Force Survey PUMF, 98M0001X for the Census).
A PUMF's own catalogue-number page links to a series index page
with the real bulk download (statcan_pumf_list_files lists it) -- confirmed live for 98M0001X: a direct,
unauthenticated ~182 MB ZIP download (181,780,881 bytes, checked 2026-09-28)
(n1/pub/98m0001x/2023001/cen21_ind_98m0001x_part_rec21.zip, HTTP 200,
Content-Type: application/zip, no login or account required). That
per-product bulk-download page is its own bespoke static HTML layout
(not this Drupal engine), so it is surfaced as a link for a caller to
follow rather than parsed generically here.

Real quirk handled: the `text`/`texte` query parameter is silently
ignored -- the response still renders every document, unfiltered --
unless the requesting session has first loaded the unparameterized
base page and carries the session cookie it sets; confirmed live with
a bare `curl` reproducing this exactly (same URL, same query string,
different result depending only on whether the base page was visited
first in the same cookie jar). This client "warms up" its session with
one request to the base page before its first real search per
(catalogue, lang) pair in a process.

French uses a different, pluralized path ("references"/"analyses"/
"donnees", all confirmed live) and a different query parameter name
(`texte`, not `text`).
"""

from dataclasses import dataclass

# Since about 2026-10-29 every /n1/{lang}/type/ listing answers StatCan's 404 page to a
# request with no Referer, and the survey directory loops on redirects instead. Any
# Referer gets the real page (checked 2026-11-03: none -> 404, example.com -> 200). A
# browser following StatCan's own menu sends one, which is why the pages look up for
# visitors while scripts, link checkers and crawlers see them down; robots.txt allows
# all of /n1/. StatCan's home page is sent, since that is where these listings are
# linked from. Approved by the project owner on 2026-11-03.
REFERER = "https://www.statcan.gc.ca/"

BASE_URL_TEMPLATE = "https://www150.statcan.gc.ca/n1/{lang}/type/{path}"
# (catalogue, lang) -> (path segment, query param name for the keyword)
CATALOGUE_CONFIG = {
    ("reference", "en"): {"path": "reference", "query_param": "text"},
    ("reference", "fr"): {"path": "references", "query_param": "texte"},
    ("analysis", "en"): {"path": "analysis", "query_param": "text"},
    ("analysis", "fr"): {"path": "analyses", "query_param": "texte"},
    ("data", "en"): {"path": "data", "query_param": "text"},
    ("data", "fr"): {"path": "donnees", "query_param": "texte"},
}

RATE_LIMIT_SOURCE = "statcan-reference"
RATE_LIMIT_PER_SECOND = 3.0
RATE_LIMIT_CAPACITY = 5.0

CACHE_TTL_SECONDS = 6 * 60 * 60

SEARCH_COUNT_DEFAULT = 10
SEARCH_COUNT_MAX = 100

# --- Publications (statcan_reference_get_publication / _get_section_text) ---------
# A catalogue number's page (editions, formats) and the publication pages it links,
# both checked live 2026-11-10; see pages.py for their layout.
CATALOGUE_URL_TEMPLATE = "https://www150.statcan.gc.ca/n1/{lang}/catalogue/{number}"
# Only these hosts are fetched, redirects included: publication URLs come from
# callers, so anything else (another host, http://localhost) is refused.
ALLOWED_HOSTS = frozenset({"www150.statcan.gc.ca", "www.statcan.gc.ca"})
MAX_REDIRECTS = 5
# Publication pages are static once released; a catalogue page gains a row when a
# new edition comes out.
PAGE_CACHE_TTL_SECONDS = 24 * 60 * 60
CATALOGUE_CACHE_TTL_SECONDS = 6 * 60 * 60

TEXT_MAX_CHARS_DEFAULT = 6000
TEXT_MAX_CHARS_MAX = 40000
QUERY_MATCHES_DEFAULT = 3
# Five at most: a brief result writes a list of more than five rows as CSV.
QUERY_MATCHES_MAX = 5
# A query reads the edition's pages, those whose link titles hold its words first,
# then the shallower ones: the CPI reference paper has 15, 13-017-X 146, and the
# 2016 Macroeconomic Accounts guide nests four levels deep under its main page.
# It stops once `limit` sections hold every word and no page left has them all in
# its title. Measured cold on 2026-11-10, pages come at about 3 a second: the rate
# limit above, kept, since StatCan has blocked this project's address before
# (statcan/cimt), with each page taking 0.4 to 1.7 s to answer.
CRAWL_MAX_PAGES = 40
CRAWL_MAX_DEPTH = 3
CRAWL_CONCURRENCY = 4
EDITIONS_LISTED_MAX = 20
SECTIONS_LISTED_MAX = 150

# --- PDF editions (pdf.py) -------------------------------------------------------
# The largest StatCan PDF seen is 13-017-X2008001 at 3.3 MB (297 pages);
# 15-203-X1999000 is 1.1 MB (277 pages: text extracted in 9 s, 13 s since its
# two-column bilingual pages are laid out again, see pdf.py); 13-017-X2008001 took
# 10 to 28 s on a loaded machine (2026-11-10).
PDF_MAX_BYTES = 25 * 1024 * 1024
PDF_MAX_PAGES = 400
# Extracted text past this is not read (15-203-X: 0.9 million characters).
PDF_MAX_CHARS = 3_000_000
# Seconds of extraction before the rest of the file is left unread; the shared
# parse budget (MAPLE_PARSE_TIMEOUT_SECONDS, 60 s) stops a stuck file outright.
PDF_EXTRACT_SECONDS = 40.0


# Where a concept is defined when it is not in the publication a caller is
# likely to search (each checked live 2026-11-10). The pattern is searched in the
# folded query (lower case, no accents); a hint is not shown when the
# publication searched is one of `skip`.
@dataclass(frozen=True)
class QueryHint:
    pattern: str
    skip: frozenset[str]
    en: str
    fr: str


QUERY_HINTS: tuple[QueryHint, ...] = (
    QueryHint(
        pattern=(
            r"\br[1-8]\b|supplementary (unemployment|rate|measure)|underutili[sz]ation"
            r"|taux de chomage supplementaire|sous-utilisation"
        ),
        skip=frozenset(),
        en=(
            "The supplementary unemployment rates R1 to R8 are not defined in the Guide to "
            "the Labour Force Survey (71-543-G, any edition): their definitions are the "
            "footnotes of table 14-10-0077-01 (read them with wds_get_cube_metadata, "
            "product_id='14-10-0077-01', footnote_limit=20); R3, the rate comparable to "
            "the United States, is explained in 75-005-M2015002."
        ),
        fr=(
            "Les taux de chômage supplémentaires R1 à R8 ne sont pas définis dans le Guide de "
            "l'Enquête sur la population active (71-543-G, toutes éditions) : leurs "
            "définitions sont les notes du tableau 14-10-0077-01 (lisez-les avec "
            "wds_get_cube_metadata, product_id='14-10-0077-01', footnote_limit=20) ; R3, "
            "comparable au taux des États-Unis, est expliqué dans 75-005-M2015002."
        ),
    ),
    QueryHint(
        pattern=(
            r"gross output (approach|allocat)|selected factor income|net output approach"
            r"|production brute|revenus de certains facteurs|production nette"
            r"|provincial (gdp|gross domestic product) by industry"
        ),
        skip=frozenset({"15-203-X"}),
        en=(
            "How national GDP by industry is allocated to the provinces (the net output, "
            "gross output and selected factor incomes approaches) is described in "
            "15-203-X, Provincial Gross Domestic Product by Industry (PDF, 1984 to 1999 "
            "edition, section 2, pages 188 to 196: publication='15-203-X', query='gross "
            "output approach'). Today's estimates are derived from the provincial supply and "
            "use tables (IMDB record 1303: statcan_surveys_get_survey_metadata, "
            "survey_id=1303)."
        ),
        fr=(
            "La répartition provinciale du PIB national par industrie (méthodes de la "
            "production nette, de la production brute et de certains revenus des facteurs) "
            "est décrite dans 15-203-X, Produit intérieur brut provincial par industrie (PDF, "
            "édition 1984 à 1999, section 2, pages 188 à 196 : publication='15-203-X', "
            "query='gross output approach'). Les estimations actuelles sont tirées des "
            "tableaux des ressources et des emplois provinciaux (fiche 1303 de la BMDI : "
            "statcan_surveys_get_survey_metadata, survey_id=1303)."
        ),
    ),
)
