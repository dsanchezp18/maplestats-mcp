### Changed

- `eccc_query_items`: a query of `climate-normals`, `climate-monthly`,
  `climate-daily` or `climate-hourly` by station (`CLIMATE_IDENTIFIER`, `STN_ID` or
  `STATION_NAME`) that matches no row now says why in `note`, from
  `climate-stations`: whether such a station exists, its record dates, and whether
  it has that kind of data at all (`HAS_NORMALS_DATA`, `HAS_MONTHLY_SUMMARY`,
  `HAS_HOURLY_DATA`). A station with `HAS_NORMALS_DATA = N` has no published
  normals, and the note says to report that. In the Maple Test, a question on the
  1981-2010 normal of Toronto City Centre (opened 2009) got zero rows and an answer
  that the normal was "not in the data I could reach" rather than that none is
  published.
