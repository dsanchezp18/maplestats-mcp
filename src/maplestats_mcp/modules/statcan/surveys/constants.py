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

# IMDB's alphabetical index of surveys and statistical programs, one page per letter
# (index{letter}-eng.htm / -fra.htm), each linking p2SV.pl?Function=getSurvey&SDDS={id}:
# the same ids as the directory, active and inactive. Read when the directory is down
# (HTTP 404 since 2026-10-29); confirmed live 2026-11-03 (A: 57 surveys, C: 178).
IMDB_INDEX_URL_EN = "https://www23.statcan.gc.ca/imdb-bmdi/pub/index{letter}-eng.htm"
IMDB_INDEX_URL_FR = "https://www23.statcan.gc.ca/imdb-bmdi/pub/index{letter}-fra.htm"
IMDB_INDEX_LETTERS = "abcdefghijklmnopqrstuvwxyz"

IMDB_BASE_URL_EN = "https://www23.statcan.gc.ca/imdb/p2SV.pl"
IMDB_BASE_URL_FR = "https://www23.statcan.gc.ca/imdb/p2SV_f.pl"

# IMDB record headings (h4 under "Data sources and methodology", h3 "Data accuracy"),
# folded to lower case without accents, by section name. Checked live 2026-11-09 on
# the English and French records of LFS (3701), CPI (2301), the Census of Population
# (3901) and the Death database (3233): each of these records carries all eleven
# headings, with "This methodology type does not apply ..." under the ones that do
# not apply.
IMDB_SECTION_HEADINGS: dict[str, tuple[str, str]] = {
    "target_population": ("target population", "population cible"),
    "instrument_design": ("instrument design", "elaboration de l'instrument"),
    "sampling": ("sampling", "echantillonnage"),
    "data_sources": ("data sources", "sources des donnees"),
    "error_detection": ("error detection", "detection des erreurs"),
    "imputation": ("imputation", "imputation"),
    "estimation": ("estimation", "estimation"),
    "quality_evaluation": ("quality evaluation", "evaluation de la qualite"),
    "disclosure_control": ("disclosure control", "controle de la divulgation"),
    "revisions_and_seasonal_adjustment": (
        "revisions and seasonal adjustment",
        "revisions et desaisonnalisation",
    ),
    "data_accuracy": ("data accuracy", "exactitude des donnees"),
}
# Without a `section` argument every section is returned, each cut to about this
# many characters at a sentence end: the eleven sections run to about 14,000
# characters for LFS, 19,000 for CPI and 8,000 for the Death database, and a
# shortened result to 9,000-14,000 characters of JSON.
IMDB_SECTION_CHARS = 900

RATE_LIMIT_SOURCE = "statcan-surveys"
RATE_LIMIT_PER_SECOND = 3.0
RATE_LIMIT_CAPACITY = 5.0

CACHE_TTL_LIST_SECONDS = 24 * 60 * 60
CACHE_TTL_METADATA_SECONDS = 24 * 60 * 60

SEARCH_LIMIT_DEFAULT = 20
SEARCH_LIMIT_MAX = 300

# Microdata holdings pages on statcan.gc.ca (Drupal pages with plain tables,
# no session needed; checked live 2026-10-02, open licence). The French RTRA page is "ADTR" (adtr), not "dtar".
RDC_URL_EN = "https://www.statcan.gc.ca/en/microdata/data-centres/data"
RDC_URL_FR = "https://www.statcan.gc.ca/fr/microdonnees/centres-donnees/donnees"
RTRA_URL_EN = "https://www.statcan.gc.ca/en/microdata/rtra/data"
RTRA_URL_FR = "https://www.statcan.gc.ca/fr/microdonnees/adtr/donnees"
CACHE_TTL_HOLDINGS_SECONDS = 24 * 60 * 60
