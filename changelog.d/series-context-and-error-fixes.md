### Added

- WDS data tools (`wds_get_data_from_vectors`, `wds_get_data_from_cube_coord`,
  `wds_get_data_by_reference_period_range`, `wds_get_bulk_vector_data_by_range`,
  `wds_get_changed_series_data`): each series now carries `context`, with the table
  number, title and page URL, the series title, the unit of measure (for example
  "Dollars" or "2024 constant dollars"), scale, frequency, geography, every
  dimension's member label, the table's last release time and period range, and
  notes on reading the unit (current vs constant dollars, index levels). A series
  with no observations in the requested window says which periods it does have.
- Fitness-for-use caveats for the CPI tables 18-10-0004 and 18-10-0005 (annual
  average vs December over December; mortgage interest cost is published for Canada
  only, and Toronto has six CPI series), the CMHC Rental Market Survey tables
  34-10-0127, 34-10-0130 and 34-10-0133 (survey rent vs asking rent; which structures
  each covers), and the income tables 11-10-0190, 11-10-0238 and 11-10-0239
  (families vs individuals; constant dollars).

### Changed

- `provenance.caveats` now also follows the tables a result contains, so a call by
  vector ID gets the same caveats as a call naming the table.
- Every failed tool call ends with a suggested fix ("Fix: ..."), by error class, when
  the module did not give one. A WDS coordinate with no series now says whether a
  member ID is wrong (naming the dimension) or the combination is not published
  (naming each member), instead of passing on WDS's bare status.
- `reproduce_workbook` saves files only when `MAPLE_EXPORT_DIR` is set; without it, a
  local server returns the workbook as base64, as a hosted one does. By default every
  tool, `call_tool` included, is now annotated read-only and idempotent. Set
  `MAPLE_EXPORT_DIR` to keep saving workbooks to a folder.
