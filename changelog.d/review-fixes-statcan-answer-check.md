### Fixed

- `rdaas_get_classification_categories_detailed` and `rdaas_get_classification_exclusions`:
  a 200 answer whose body was a web page (an RDaaS outage or maintenance page) was read
  as "no categories" and kept for 24 hours. It is now an upstream error and is never
  kept, so the next call reads the real list. A blank body, which RDaaS really sends
  for the current NAICS, and an empty JSON list are still read as an empty result.
- `wds_get_series_as_of`: a member name shared by several members of the real-time table
  (the same label under two parents, or two dimensions with one name) was matched to the
  first one found, which gave a plausible series for the wrong member. The parent member
  and then the classification code now tell them apart; when they cannot, the call
  fails and lists the candidates, with their names and parents in the language asked.
- `wds_get_data_from_vectors`: when a series of the
  Consumer Price Index came from the Bank of Canada's Valet API and its StatCan table
  was not known, the citation read "Table 00-00-0000-01", a table that does not exist.
  It now cites the Valet series that was read and the StatCan vector it carries.
- `wds_query_table`: when StatCan's captcha blocked the full-table file and the slice was
  rebuilt from WDS by coordinate, a long history could be refused as "too much to return
  inline" even though the slice was well under the 1,200-series limit (150 monthly series
  since 1990 ask 65,100 observations in one call). The rebuild now sizes each call by
  the periods it asks for, so none passes the limit. A call whose combinations are all
  unpublished no longer fails the whole query: the combinations of a table's members are
  not all series, and the other calls' rows are kept. A slice of more than the 300,000
  rows the cap allows (a daily history of many series, read one series per call) is
  refused as the file route refuses it: on the rows the calls actually return, once they
  pass the cap, not on an estimate of them made before any call, because many member
  combinations are not series and a series can start long after the table's first
  period. A sparse slice whose rows are well under the cap is read, whatever its
  combinations times periods come to. A rebuild that passes the time budget the file
  route has stops with the same "took longer than this tool's N s" error. The limits
  themselves are unchanged.
- `statcan_census_profile_get_data`: a geography and characteristic pair that was asked
  for but that the answer did not carry was left out without a word, so "not published for
  this place" read like "never asked". `provenance.coverage` now says how many pairs came
  back with no value and names them, in English and French. When the answer also carried
  values under codes other than the ones asked, the note counts them too and says they
  may be some of the missing pairs.
- `check_answer`: a percent change over one period was measured against the way the period
  was written, not the series' own period, so a correct six-month change of a semi-annual
  series was called wrong, and one cited for a day was skipped. It now uses the series'
  frequency, for monthly, bi-monthly, quarterly, semi-annual and annual series, and the
  note for any other frequency names those. The "not re-read" notes in French named their sources in English ("Statistics
  Canada WDS"); they now say the SDW of Statistique Canada and the Valet API of the Banque
  du Canada.
