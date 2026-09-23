"""Constants for the Justice Laws Website XML service.

Confirmed live 2026-09-23:
- `/eng/XML/Legis.xml` (~5 MB) lists every Act and regulation twice,
  once per language. Acts share one UniqueId (e.g. "A-1") across
  languages; regulations do not ("SOR-2007-151" vs "DORS-2007-151"),
  and are paired instead through `id`/`olid` attributes.
- Each document is at `/{eng|fra}/XML/{UniqueId}.xml`; large statutes
  run to several megabytes. Sections are `Body/Section` elements with a
  `Label`, `MarginalNote`, nested `Subsection`/`Paragraph` labels and
  `lims:lastAmendedDate` attributes.
- An unknown document answers HTTP 404.
"""

BASE_URL = "https://laws-lois.justice.gc.ca"
INDEX_URL = f"{BASE_URL}/eng/XML/Legis.xml"
LIMS_NS = "{http://justice.gc.ca/lims}"

RATE_LIMIT_SOURCE = "justice-laws"
RATE_LIMIT_PER_SECOND = 2.0
RATE_LIMIT_CAPACITY = 4.0

CACHE_TTL_INDEX_SECONDS = 24 * 60 * 60
CACHE_TTL_DOCUMENT_SECONDS = 24 * 60 * 60

SEARCH_LIMIT_DEFAULT = 20
SEARCH_LIMIT_MAX = 100
OUTLINE_SECTIONS_MAX = 400
SECTION_TEXT_MAX = 20_000
