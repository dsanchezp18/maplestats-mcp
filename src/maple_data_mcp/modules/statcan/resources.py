"""Zero-parameter MCP resources for the StatCan module.

Zero-parameter is a hard requirement: any parameter makes FastMCP treat
a decorated function as a ResourceTemplate instead of a FunctionResource.
"""

from __future__ import annotations

from fastmcp.resources import resource

_ADDRESSING_DOC = """\
# Statistics Canada addressing system

StatCan identifies data three ways, all resolvable into each other:

- **productId (PID)**: 10-digit table identifier. Digits 1-2 = subject
  code, 3-4 = product type, 5-8 = sequential number, 9-10 = optional
  simple-view identifier.
- **vectorId**: a stable "V" + up to 10 digits, identifying one time
  series. Carried over from legacy CANSIM table numbers for backward
  compatibility.
- **coordinate**: a dot-separated string of member ids, one per
  dimension, always exactly 10 positions (unused dimensions padded
  with "0"), e.g. "2.2.0.0.0.0.0.0.0.0".

Use wds_get_series_info_from_vector / wds_get_series_info_from_cube_pid_coord
to convert between coordinate and vectorId. SDMX queries use a shorter
key — only the non-time dimensions, no trailing zero padding (see
sdmx_get_structure to find how many non-time dimensions a table has).
"""

_GOTCHAS_DOC = """\
# Known StatCan API gotchas

- **scalarFactorCode is never auto-applied.** A raw observation `value`
  is NOT multiplied by its scalarFactorCode (e.g. "thousands"). Call
  wds_get_code_sets to see the scalar codes, or use
  maple_data_mcp.modules.statcan.wds.schemas.apply_scalar_factor.
- **12am-8:30am ET daily lock window.** WDS returns HTTP 409 for some
  methods during this window while data updates. This surfaces as a
  DataLocked error here, not a generic failure — it means "try again
  after 8:30am ET," not "something is broken."
- **SDMX large-dimension wildcarding is unreliable.** Leaving a
  dimension with more than ~30 codes wildcarded in an SDMX key returns
  a sparse, unpredictable sample, not the full set. Use
  sdmx_get_key_for_dimension to get a complete OR key instead.
- **lastNObservations cannot combine with startPeriod/endPeriod** in
  SDMX queries — StatCan returns HTTP 406 for that combination.
- **StatCan's SDMX REST endpoint returns SDMX-ML (XML), not SDMX-JSON**,
  regardless of the `format` query parameter or Accept header — this
  module parses the real XML directly.
"""


@resource("docs://statcan/addressing")
def statcan_addressing_doc() -> str:
    """Explain StatCan's productId/vectorId/coordinate addressing system."""
    return _ADDRESSING_DOC


@resource("docs://statcan/gotchas")
def statcan_gotchas_doc() -> str:
    """List known StatCan API quirks that are easy to get wrong."""
    return _GOTCHAS_DOC
