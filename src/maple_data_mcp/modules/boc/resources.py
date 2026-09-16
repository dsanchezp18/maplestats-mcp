"""Zero-parameter MCP resources for the boc module.

Zero-parameter is a hard requirement: any parameter makes FastMCP treat
a decorated function as a ResourceTemplate instead of a FunctionResource.

Every series/group name below was looked up live against the real Valet
API this session (not copied from documentation prose) - series names
and codes on Valet do change over time (e.g. legacy CANSIM-style codes
alongside newer descriptive ones for the same concept), so this is
meant to be re-verified periodically rather than treated as permanent.
"""

from __future__ import annotations

from fastmcp.resources import resource

_WELL_KNOWN_SERIES_DOC = """\
# Well-known Bank of Canada Valet series and groups

Verified live against https://www.bankofcanada.ca/valet/ this session.
Use boc_search_series/boc_search_groups to find others - this is a
starting point for the series that matter most for economic analysis,
not an exhaustive list of the ~16,000 series Valet carries.

## Exchange rates

- `FXUSDCAD` - USD/CAD daily average exchange rate.
- `FXEURCAD` - EUR/CAD daily average exchange rate.
- Group `FX_RATES_DAILY` - daily average exchange rates for ~27
  currencies against CAD (published once per business day, ~16:30 ET).
- Group `CEER` family - Canadian effective exchange rate indexes
  (trade-weighted, not a single bilateral rate).

## Key interest rates

- `V39079` - target for the overnight rate (business daily), also
  called the policy interest rate.
- `STATIC_ATABLE_V39079` - the same target for the overnight rate,
  end-of-month frequency instead of business daily.
- `V80691311` - prime rate (the base lending rate financial
  institutions set from the policy rate).

## CPI / inflation

- `V41690973` - Total CPI (the headline all-items Consumer Price
  Index, monthly).
- `V41690914` - Total CPI, seasonally adjusted.
- `STATIC_TOTALCPICHANGE` - Total CPI, percentage change year-over-
  year (unadjusted).
- `CPI_TRIM`, `CPI_MEDIAN`, `CPI_COMMON` - the Bank's three preferred
  core-inflation measures (CPI-trim, CPI-median, CPI-common).
- Group `CPI_MONTHLY` - Total CPI plus all of the above core measures
  in one group.

## Commodity prices

- `W.BCPI` - weekly Bank of Canada Commodity Price Index (BCPI),
  total.
- Groups `BCPI_WEEKLY`, `BCPI_MONTHLY`, `BCPI_ANNUAL` - the BCPI family
  (total and by commodity group - energy, metals and minerals,
  forestry, agriculture, fish) at each publication frequency.
"""

_GOTCHAS_DOC = """\
# Known Bank of Canada Valet API gotchas

- **`recent`/`recent_weeks`/`recent_months`/`recent_years` cannot be
  combined with `start_date`/`end_date`.** Valet returns HTTP 400 for
  that combination; boc_get_observations/boc_get_group_observations
  raise InvalidInput for it before making a request.
- **Multi-series observation rows are not always merged by date.**
  Requesting series that share a publication frequency (e.g. two daily
  FX rates) merges them into one row per date. Requesting series of
  genuinely different frequencies together (e.g. a daily FX rate and a
  monthly CPI series) under a `recent*` filter returns separate,
  unmerged rows - each row's `values` only has the series that
  actually has data for that date. Check each row's keys rather than
  assuming every requested series appears in every row.
- **Observation values are JSON strings, not numbers**, even for a
  purely numeric series - already parsed to `float | None` in this
  module's ObservationsResult, but worth knowing if comparing against
  a raw Valet response.
- **Endpoint naming is inconsistent between single-item and
  observation responses.** `/series/{name}/json` uses `seriesDetails`
  (plural, includes a `name` field); `/observations/.../json` uses
  `seriesDetail` (singular, keyed by series code, no `name` field
  inside each entry). The same split exists for groups
  (`groupDetails` vs `groupDetail`), and `groupDetail` additionally
  has no `name` field at all - GroupObservationsResult.group.name is
  filled in from the caller's own group_name argument for this reason.
"""


@resource("docs://boc/well-known-series")
def boc_well_known_series_doc() -> str:
    """List well-known Bank of Canada Valet series/groups for FX, interest
    rates, CPI/inflation, and commodity prices."""
    return _WELL_KNOWN_SERIES_DOC


@resource("docs://boc/gotchas")
def boc_gotchas_doc() -> str:
    """List known Bank of Canada Valet API quirks that are easy to get wrong."""
    return _GOTCHAS_DOC
