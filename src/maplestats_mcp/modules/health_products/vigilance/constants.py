"""Constants for Canada Vigilance (checked live 2026-10-03).

The API (health-products.canada.ca/api/canada-vigilance/) looks reports up
by number only. The extract is a ZIP of `$`-delimited text files on
canada.ca, 355,543,866 bytes as served (Last-Modified 2026-09-02, data to
2026-05-31, in folder cvponline_extract_20260531/). Its members, in file
order, with where each starts in the stream:

    drug_product_ingredients.txt   0 MB    (11.8 MB compressed)
    drug_products.txt              11.8 MB
    gender_lx.txt, literature_reference.txt, outcome_lx.txt
    reactions.txt                  15.4 MB (87 MB compressed, 823 MB of text)
    report_drug_indication.txt     102.7 MB
    report_drug.txt                185.7 MB
    report_links.txt               312.7 MB
    reports.txt                    320.5 MB
    report_type_lx.txt, seriousness_lx.txt, source_lx.txt

canada.ca honours a byte range only when the request accepts gzip, and
then serves ranges of a gzip-compressed copy of the ZIP
(Content-Encoding: gzip, Content-Range .../355543866). A gzip stream
cannot be entered in the middle, so the ZIP's directory at the end cannot
be read on its own and every member has to be reached by reading the
stream from its first byte. Reading through reactions.txt costs about
103 MB; the report dates and the drug list per report sit beyond 185 MB.
"""

PATH_REPORT = "canada-vigilance/report"
PATH_REPORT_DRUG = "canada-vigilance/reportdrug"
CODE_TABLES = {
    "outcome": "canada-vigilance/outcome",
    "seriousness": "canada-vigilance/seriousness",
    "source": "canada-vigilance/source",
    "gender": "canada-vigilance/gender",
    "report_type": "canada-vigilance/reporttype",
}

EXTRACT_URL = (
    "https://www.canada.ca/content/dam/hc-sc/migration/hc-sc/dhp-mps/alt_formats/zip/"
    "medeff/databasdon/extract_extrait.zip"
)
EXTRACT_PAGE = (
    "https://www.canada.ca/en/health-canada/services/drugs-health-products/medeffect-canada/"
    "adverse-reaction-database/canada-vigilance-online-database-data-extract.html"
)
REACTIONS_MEMBER = "reactions.txt"
SEARCH_PAGE = "https://www.canada.ca/en/health-canada/services/drugs-health-products/medeffect-canada/adverse-reaction-database.html"

API_FRESHNESS = "Canada Vigilance online database, updated by Health Canada"
EXTRACT_FRESHNESS = "monthly extract (data through the date in its folder name)"
API_FRESHNESS_FR = "base de données en ligne de Canada Vigilance, mise à jour par Santé Canada"
EXTRACT_FRESHNESS_FR = (
    "extrait mensuel (données jusqu'à la date indiquée dans le nom de son dossier)"
)
# Said for every report and every count, in each language.
CAUTION = (
    "A report records a suspected association, not a confirmed cause; counts of "
    "reports are not incidence rates."
)
CAUTION_FR = (
    "Une déclaration consigne une association soupçonnée, et non une cause confirmée ; "
    "le nombre de déclarations n'est pas un taux d'incidence."
)

LOOKUP_TTL_SECONDS = 6 * 60 * 60
CODES_TTL_SECONDS = 24 * 60 * 60
SCAN_TTL_SECONDS = 24 * 60 * 60

# Compressed megabytes a reaction search may read. reactions.txt ended at
# 102.7 MB in the 2026-05-31 extract; the default leaves room for growth.
SCAN_MB_DEFAULT = 120
SCAN_MB_MIN = 20
SCAN_MB_MAX = 150
SCAN_SECONDS_MAX = 95.0

REPORTS_DEFAULT = 50
REPORTS_MAX = 500
TOP_TERMS = 25
