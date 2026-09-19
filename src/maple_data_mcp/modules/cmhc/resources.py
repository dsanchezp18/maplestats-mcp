"""Zero-parameter MCP resources for the cmhc module.

Zero-parameter is a hard requirement: any parameter makes FastMCP treat
a decorated function as a ResourceTemplate instead of a FunctionResource.

Every category name and code below was looked up live against
https://www03.cmhc-schl.gc.ca/hmip-pimh/ this session - CMHC's category
taxonomy is not exhaustively documented here (use
cmhc_list_categories/cmhc_get_table_options for the rest), just a
starting point for the categories that matter most.
"""

from __future__ import annotations

from fastmcp.resources import resource

_WELL_KNOWN_CATEGORIES_DOC = """\
# Well-known CMHC HMIP categories

Verified live against https://www03.cmhc-schl.gc.ca/hmip-pimh/ this
session, at the national (Canada) level. Pass `category_level_1`/
`category_level_2` exactly as spelled here to cmhc_get_table_options or
cmhc_get_table_data.

## Primary Rental Market (CMHC Rental Market Survey)

- category_level_1 = "Primary Rental Market"
- category_level_2 options include: "Vacancy Rate (%)", "Availability
  Rate (%)", "Average Rent ($)", "% Change of Average Rent", "Median
  Rent ($)", "Rental Universe", "Summary Statistics".
- Common column_field/row_field pairs (from cmhc_get_table_options):
  Bedroom Type=2 with Historical Time Periods=TIMESERIES (national time
  series), or Bedroom Type=2 with Provinces=21 (current cross-tab by
  province).

## New Housing Construction

- category_level_1 = "New Housing Construction"
- category_level_2 options include: "Starts (Actual)", "Starts
  (SAAR)", "Completions", "Under Construction Inventory", "Absorbed
  Units (Homeowner + Condo)", "Unabsorbed Unit Prices ($)".

## Secondary Rental Market

- category_level_1 = "Secondary Rental Market"
- Covers "Rental Condominium Apartments" and "Other Secondary Rental
  Dwellings" sub-categories.

## Seniors' Rental Housing

- category_level_1 = "Seniors' Rental Housing"
- category_level_2 options include: "Rental Housing Vacancy Rates
  (%)", "Universe, Number of Residents Living in Standard Spaces",
  "Vacancy Rate (%) and Average Rent".

## Population, Households and Housing Stock / Core Housing Need

- category_level_1 = "Population, Households and Housing Stock" or
  "Core Housing Need"
- Many category_level_2 sub-topics: household type/size, income,
  mortgages, shelter costs, structure type, period of construction, and
  more - call cmhc_list_categories for the full current list.

## Geography

- Default (no geography_type/geography_id passed) is Canada-wide
  (geography_type="Country", geography_id="1").
- Call cmhc_list_provinces for province-level ids, then pass
  geography_type="Province" with that id.
- CMA/city-level geography is not yet supported by this module.
"""

_GOTCHAS_DOC = """\
# Known CMHC HMIP quirks

- **A category/geography/field combination that does not exist returns
  HTTP 500 with an ASP.NET error page**, not a clean 404 - confirmed
  live. cmhc_get_table_options and cmhc_get_table_data raise a typed
  NotFound for this rather than a generic upstream error, but there is
  no way to check validity without calling the discovery tools first
  (cmhc_list_categories, cmhc_get_table_options).
- **Data cells can hold a suppressed/not-applicable marker instead of a
  number.** `"**"` means the value was suppressed for confidentiality
  or is not statistically reliable; `"++"` means a percent-change value
  was not statistically significant (only appears on "% Change of
  Average Rent" tables). Both surface as `value: null` with the raw
  marker preserved in `flag` - check for `null` before doing arithmetic
  on a cell's value.
- **The reliability flag legend**: `a` = Excellent, `b` = Very good,
  `c` = Good, `d` = Poor (use with caution). Every non-suppressed value
  carries one of these.
- **`lang` genuinely changes category names, not just prose** - unlike
  most modules in this project (where `lang` only changes surrounding
  labels while codes/ids stay fixed), CMHC's `category_level_1`/
  `category_level_2` values are themselves different strings per
  language (confirmed live: "Primary Rental Market" in English is
  "Marché locatif primaire" in French, both resolving to the same
  underlying table). A value returned with `lang="en"` will not resolve
  anything when passed to a tool called with `lang="fr"`.
- **Only Canada and province-level geography are supported.** CMA/city-
  level geography ids exist in HMIP but no live-confirmed discovery
  endpoint was found for them (a few plausible endpoint names were
  tried and none worked) - geography_type/geography_id must currently
  be "Country"/"1" or a province id from cmhc_list_provinces.
- **`cmhc_get_table_options` never passes column_field/row_field back
  to HMIP** - doing so narrows HMIP's own response to a partial slice
  around whatever was passed in, rather than the full set of valid
  options, so this module deliberately queries the bare category to get
  everything at once.
"""


@resource("docs://cmhc/well-known-categories")
def cmhc_well_known_categories_doc() -> str:
    """List well-known CMHC HMIP categories for rental market, housing
    starts, seniors housing, and population/household indicators."""
    return _WELL_KNOWN_CATEGORIES_DOC


@resource("docs://cmhc/gotchas")
def cmhc_gotchas_doc() -> str:
    """List known CMHC HMIP quirks that are easy to get wrong."""
    return _GOTCHAS_DOC
