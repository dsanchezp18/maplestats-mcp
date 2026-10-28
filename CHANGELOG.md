# Changelog

All notable changes are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project
uses [semantic versioning](https://semver.org/) while it is in beta.
Changes not yet released are in [`changelog.d/`](changelog.d/), one file
each; `scripts/build_changelog.py` writes them in here at release time.

## [Unreleased]

## [0.4.3] - 2026-10-28

This release adds five sources (BIS, the CBSA Customs Tariff, Indigenous Services
Canada, Ontario's Financial Information Return, CRTC telecom prices and market reports),
moving averages and smoothed changes, `provenance.commercial_use` and `caveats` on every
result, and the fixes from the accuracy audit. Two changes can break a caller: some
output fields are now `null` where a blank used to read as 0 (`ircc_*` Express Entry
rounds, `eccc_datamart_npri_facilities`, `hc_device_*`), and several `nwt_stats_*` topic
slugs were merged or removed after the NWT Bureau of Statistics relaunched its site.

### Added

- A disclaimer on accuracy and use: a "What to watch for" section in the README, a
  "Can I rely on the answers?" FAQ entry on the website in English and French, and a line
  in the site footer. Values come as published and any trimming, scaling, cleaning or
  computation is labelled; answers an AI assistant writes from them are AI-generated and
  should be checked against the source; MapleStats is provided as is and is not
  professional, legal or financial advice.
- `plan_query`: four topics for administrative records, in English and French:
  building permits and construction (StatCan table 34-10-0292, CMHC starts, and
  permit records for Calgary, Edmonton, Winnipeg, Vancouver, Toronto, Montreal,
  Laval, Regina, Halifax, Surrey, Victoria and five more Ontario cities), business
  licences (city licence registers and StatCan's Canadian Business Counts),
  restaurant and food premises inspections (Toronto DineSafe, Montreal, Quebec's
  MAPAQ counts, Fraser Health through Surrey) and planning and development
  applications (rezonings, development permits, site plans). Each step names the
  portal and dataset to read with the existing readers, checked live on 2026-10-27,
  and the step for a city named in the question comes first.
- Bank for International Settlements statistics (`bis_`, 4 tools), over the BIS
  SDMX API (no key; free reuse with the BIS cited). `bis_compare_countries`
  puts Canada beside the G7, the euro area or other economies on 13 preset
  indicators: policy rates, household and private debt service ratios,
  credit-to-GDP gaps, household, private and government credit as a share of
  GDP, residential property prices, consumer price inflation and effective
  exchange rates, with Canada's rank. `bis_list_datasets`,
  `bis_describe_dataset` and `bis_get_series` reach any series of the 28 BIS
  datasets (international banking, debt securities, derivatives, CPMI payment
  statistics) by SDMX key, with a CSV link for each query.
- Canada's Customs Tariff from the CBSA (`cbsa_tariff_`, 3 tools), read from
  CBSA's Microsoft Access editions in English and French, 2018 onward.
  `cbsa_tariff_lookup` gives a tariff number's description, unit of measure,
  headings and the lines under it, with the Most-Favoured-Nation, General
  Tariff and every preferential rate (CUSMA, CETA, CPTPP, the UK, Korea and
  other agreements) as written and as a percentage. `cbsa_tariff_search`
  finds lines by words or HS chapter, and `cbsa_tariff_list_editions` lists
  the editions and their effective dates; both lookup and search take an
  edition or a date. The digits are the HS codes `cimt_get_trade` takes.
  Each edition is read once into Parquet (`MAPLE_CBSA_TARIFF_CACHE_DIR`).
  New dependency: `access-parser` 0.0.6 (Apache 2.0, pure Python).
- `docs/library.md`: how to use MapleStats as a Python library without MCP (the
  async client and tool functions, the typed results and provenance, cache, rate
  limits, settings, language and errors), with examples run against the live
  sources. The module APIs are not yet a stable public API; semantic versioning
  covers the MCP tools.
- Fitness-for-use rules: short English and French cautions on when and how a
  number can be used, each resting on an official Statistics Canada, Bank of
  Canada or CMHC page it cites (LFS vs SEPH, LFS sampling variability, the SEPH
  January 2026 level shift, 2021 Census random rounding and boundary changes,
  MBM vs LIM vs LICO and MBM bases, CPI and core-inflation revisions, monthly vs
  quarterly GDP and chained dollars, NAICS and NOC versions, PUMF weights and
  release rules, CMHC Rental Market Survey reliability codes). They match tools
  by name prefix and StatCan tables by product id in any spelling
  (`shared/fitness.py::notes_for`), and are listed with their sources in
  `docs://planner/fitness-rules` (French: `docs://planner/fr/regles-d-usage`).
- `plan_query`: a topic's caveats now end with the fitness-for-use notes for the
  tools and tables its steps name (and for a table number in the question), in
  the plan's language, each note once per plan.
- Indigenous Services Canada and CIRNAC (`isc_`, 5 tools), in English and French.
  `isc_search_first_nations` finds a First Nation by name, band number or
  province among the 646 registry groups of ISC's registered population dataset
  (OGL - Canada); `isc_get_first_nation_profile` reads CIRNAC's First Nation
  Profiles: official name, address, tribal council, reserves with their
  hectares, membership authority, election system, chief and council, and
  geographic zone; `isc_get_registered_population` gives the population
  registered under the Indian Act by sex and residence for the latest month,
  with the yearly figures since 2023; `isc_list_drinking_water_advisories` lists
  long-term drinking water advisories on public systems, current and lifted
  since November 2015, from the file behind ISC's map; and
  `isc_list_short_term_advisories` lists short-term advisories south of 60
  (British Columbia's are the First Nations Health Authority's). Profiles and
  advisories fall under the Canada.ca terms (non-commercial reproduction with
  attribution).
- Every result's `provenance` has a new `commercial_use` field saying whether the
  publisher's terms allow commercial reuse without asking: `allowed`,
  `not_allowed` (non-commercial use only, or written permission needed, as for
  the Canada.ca terms, CIHI, CMHC, the PBO, the AER, the CBSA's Customs Tariff,
  CREA, the Institut de la statistique du Québec and Parliament), `varies`
  (CKAN, ArcGIS Hub, Socrata, Borealis and other platforms whose datasets or
  feeds each carry their own licence) or `unknown` (terms silent, conflicting or
  not found). It comes from one table next to the licence texts in
  `shared/licences.py`, checked against each publisher's terms page, not from
  parsing the text; `provenance.licence` is unchanged. Null where no licence
  applies, as for `plan_query`.
- `wds_get_data_from_vectors`, `wds_get_data_from_cube_coord`,
  `wds_get_data_by_reference_period_range`, `wds_get_bulk_vector_data_by_range`,
  `wds_get_changed_series_data` and `wds_get_series_as_of`: each observation now says
  what its codes mean, beside the integers: `status` ("use with caution", "too
  unreliable to be published"), `symbol` ("preliminary", "revised") and
  `security_level`, in the call's language, decoded from WDS getCodeSets (the same
  wording `statcan_delta`'s legend uses). When getCodeSets does not answer, the codes
  come back undecoded and provenance.limits says so.
- `wds_get_data_from_vectors`, `wds_get_data_from_cube_coord`,
  `wds_get_data_by_reference_period_range`, `sdmx_get_data`, `sdmx_get_vector_data`
  and `boc_get_observations` take an optional `transform` (`diff`, `pct_change`,
  `yoy_diff`, `yoy_pct_change`, `annualized_pct_change`, or `index` with
  `index_base`) and `frequency` (`monthly`, `quarterly`, `annual`, with `aggregation`
  `average`, `sum` or `end_of_period`). The published values stay in `observations`;
  the computed ones come in a separate `transformed` block with the exact formula
  ("Computed by MapleStats: yoy_pct_change = 100 * (x_t / x_{t-12} - 1)"), the unit
  and notes. History for the lag is fetched before the requested window, year-over-year
  compares the same period a year earlier by date (a gap cannot shift it), missing
  values stay missing, and periods the data only partly cover are not aggregated. A
  percent change of a series already in percent or a rate (StatCan uom "Percent",
  Valet unit "Percent": an unemployment rate, the policy rate) comes back as the
  change in percentage points, and says so. Checked live: CPI all-items
  yoy_pct_change for September 2026 is 3.09, The Daily's 3.1%.
- `reproduce_code` repeats these transforms in R, Python, Stata (in its Python block)
  and Julia: the script fetches the same levels, as far back as the tool did, and
  applies the same formula. No Excel (Power Query) query is given for a transformed
  call, and the notes say why.
- Ontario's municipal Financial Information Return (`on_fir_`, 5 tools), from the
  Ministry of Municipal Affairs and Housing's yearly CSV files, 2000 to 2025 (Open
  Government Licence - Ontario). `on_fir_get_schedule` reads one municipality's
  schedule with its labels (revenue, expenses by function, taxation, reserves, debt,
  tangible capital assets, statistics); `on_fir_compare` puts one line side by side
  across municipalities or up to 10 years, per capita and within one tier;
  `on_fir_list_schedules`, `on_fir_search_municipalities` and `on_fir_search_lines`
  find the year, the MUNID and the line code. A year is downloaded once (about 10 MB)
  and kept as Parquet in `MAPLE_ON_FIR_CACHE_DIR` (cap `MAPLE_ON_FIR_CACHE_MAX_MB`,
  default 500). The newest year is incomplete until every return is filed, and each
  result says how many of the 444 municipalities have filed.
- An optional hybrid `search_tools` (Phase 2 of the discovery plan), off by default:
  with `MAPLE_SEARCH=hybrid` and the `semantic` extra (`pip install
  "maplestats-mcp[semantic]"`, then `python -m maplestats_mcp.shared.semantic build`),
  BM25 is fused with a local multilingual embedding model (multilingual-e5-small, int8,
  MIT) by reciprocal rank fusion. Only tool metadata is indexed and queries are embedded
  on the server, never sent to an API. It ranks more first answers right, French above
  all, but not more in the top five, and costs about 220 MB of memory, so it stays off;
  `tests/discovery_benchmark/phase2.md` has the measurements. Without the extra or the
  index, hybrid mode logs why and searches by BM25.
- `provenance.caveats` on every tool result: the fitness-for-use cautions that
  MapleStats' rules (`docs://planner/fitness-rules`) attach to the table or source a call
  used, in the call's language. An empty list when no rule applies.
- One response-size budget for every tool. When a result's JSON is larger than
  `MAPLE_RESPONSE_MAX_BYTES` (default 200,000 bytes), the server keeps a prefix
  of its largest lists (the most recent rows for a time series listed oldest
  first, and an even share across lists of the same field, such as each
  series' observations), so the result still matches the tool's output schema,
  and adds a sentence to `provenance.limits` saying what was cut and how to get
  the rest: narrower arguments, the source's download tool, or
  `reproduce_code`. Results within the budget are unchanged; geometry is never
  cut. Tools that had no bound of their own, and per-tool caps set above the
  budget, are now held to it.
- Six cross-source workflow prompts, in English and French (`lang`), shown in
  a client's prompt menu: `labour_market_snapshot` (Labour Force Survey
  headline and SEPH earnings, with the caution against comparing the two),
  `refresh_with_latest_release` (release calendar, The Daily, changed tables,
  revisions and vintages), `housing_affordability_scan` (CMHC rents and
  vacancy, CPI shelter, Bank of Canada rates), `inflation_check` (all-items
  CPI, the Bank of Canada's core measures and their first estimates with
  `wds_get_series_as_of`), `compare_province_with_peers` and
  `find_and_cite_dataset`. Each ends by asking the assistant to cite the
  provenance and pass on its caveats.
- `telecom_get_city_plan_prices`: CRTC mobile and Internet plan prices by census
  metropolitan area (Edmonton, Toronto, Montréal and the other 21 CMAs), year by year
  from 2016, from the "Prix-Prices" sheet of the CRTC's year-end price workbook. The
  averages are computed by MapleStats (the mean of every reported price, and the mean
  of each provider's lowest price, the CRTC's own method), with the number of prices
  and providers behind each, and optionally the provider and brand rows. `city` takes
  one CMA or several, accents and case ignored ('Montreal', 'Ottawa'). From 2024 the
  CRTC surveys one CMA per province or territory; for a CMA with no rows in a year the
  notes say so and point to the CRTC's provincial urban average.
- `telecom_get_plan_prices`: `province` also takes several provinces or territories at
  once, as a list or a comma-separated string (`['AB', 'ON']`, `'AB, ON, QC'`). A
  single code still works as before.
- CRTC Communications Market Reports, tools prefixed `telecom_` (4 tools):
  `telecom_get_plan_prices` gives the CRTC's year-end average advertised monthly
  prices of mobile plans by data allowance (talk-only, 1 GB to 200 GB; 3G, LTE, 5G or
  the lowest price) and of home Internet plans by speed, for Canada, each province and
  territory, urban and rural areas, 2016 to 2025; `telecom_list_market_tables` and
  `telecom_get_market_table` read the annual retail mobile and fixed Internet sector
  tables (revenue per GB, ARPU, data usage, subscribers, market shares of Bell, Rogers,
  TELUS and other providers, churn, plan size distribution) as tidy series by year, in
  English or French, flag the years that count mobile phone services only (2020 on) and
  leave out the derived growth columns; `telecom_get_quarterly_trends` gives quarterly
  revenues, subscribers, lines, minutes and data traffic for mobile, Internet, wireline
  and TV distribution from 2014 Q1, sorted by quarter. Open Government Licence - Canada.
- `plan_query`: a telecom topic (mobile and Internet plan prices, subscribers and
  competition) in English and French, which also points to StatCan's cellular services
  CPI (vector v1212387935) and notes that ISED's price comparison studies and the
  CRTC's low-cost plan reports are not read by any tool.
- `wds_get_data_from_vectors`, `wds_get_data_from_cube_coord`,
  `wds_get_data_by_reference_period_range`, `sdmx_get_data`, `sdmx_get_vector_data`
  and `boc_get_observations` take `transform="moving_average"` with a new optional
  `window` (2 to 120 periods): a trailing moving average, labelled "Computed by
  MapleStats: moving_average_3 = mean(x_{t-2}, x_{t-1}, x_t)". It composes with
  `frequency` (`frequency="annual", window=3` averages each year first, then takes the
  3-year moving average), is found by date, not by row, so a window that reaches a
  missing or unpublished period is null rather than shorter, and the history the
  window needs is fetched before the requested span, which alone is returned. A
  moving average of a rate (unemployment rate, CPI inflation) stays in the rate's
  unit; no percentage-point conversion applies, and the notes say so. Only trailing
  averages are computed (no centred ones), and daily series need `frequency` first.
  Checked live: the 3-year moving average of the annual unemployment rate (table
  14-10-0327) for 2025 is 6.17, (5.4 + 6.3 + 6.8) / 3. `transformed` gains a
  `window` field.
- `reproduce_code` repeats the moving average in R, Python, Julia and Stata (in its
  Python block).
- `window` now also smooths a change: with `transform` set to `diff`, `pct_change`,
  `yoy_diff`, `yoy_pct_change` or `annualized_pct_change`, the six data tools
  (`wds_get_data_from_vectors`, `wds_get_data_from_cube_coord`,
  `wds_get_data_by_reference_period_range`, `sdmx_get_data`, `sdmx_get_vector_data`,
  `boc_get_observations`) compute the change first, then its trailing moving average
  over `window` periods, matched by date and null when any change in the window is
  missing. So `transform="yoy_pct_change", frequency="annual", window=3` gives the
  3-year moving average of yearly inflation in one call (or `window=36` on the
  monthly 12-month rate). The formula says so ("Computed by MapleStats: moving
  average over 3 years of yoy_pct_change = mean(y_{t-2}, y_{t-1}, y_t), y_t = 100 *
  (x_t / x_{t-1} - 1)"), the history fetched covers both the lag and the window, and
  for a series in percent or a rate the percentage-point change is what gets
  averaged, as the notes say. `transform="moving_average"` is unchanged (the moving
  average of the levels). `window` with `index` is refused with an explanation:
  averaging the index and indexing the average differ, so neither is guessed.
  Checked live: for CPI all-items (v41690973), 2025 is 2.78, the mean of the yearly
  changes in the annual averages for 2023 (3.88), 2024 (2.38) and 2025 (2.07); the
  SDMX tool gives the same.
- `reproduce_code` repeats the smoothing in R, Python, Julia and Stata (in its Python
  block); the generated Python, run live, matched the tool for a WDS call and two
  Bank of Canada calls (monthly CPI, and daily series averaged to months, one of them
  a rate).
- `wds_get_series_as_of`: a StatCan series as it was published on a past date, before later
  revisions. Give the series of a regular table (`vector_id`, or `product_id` + `coordinate`)
  and `as_of`; the values come from the latest release on or before that date, read from
  the table's real-time (vintage) table, with `release_date` saying which release. Works for
  the 16 tables WDS pairs with a real-time table (CPI core measures, monthly and quarterly
  GDP, SEPH employment and earnings, retail, wholesale, manufacturing, trade, balance of
  payments, capital expenditures); any other table is an error, not current data.

### Changed

- `plan_query`: a question about building permits now leads with the building
  permits topic rather than housing; housing still follows it.
- Fields MapleStats computes are now described as computed, with a sentence in
  `provenance.limits` where the computation covers less than the whole result:
  `electricity_ontario_get_realtime_demand` (`average_ontario_demand_mw`, and over how many
  intervals), `electricity_ontario_get_prices` (average, minimum and maximum, unweighted),
  `electricity_ontario_get_adequacy_outlook` (minimum excess and peak forecast),
  `electricity_ontario_get_intertie_flows` (mean flows), `electricity_quebec_get_demand`
  (peak and average over the returned rows only), `electricity_quebec_get_generation`
  (shares are over the returned rows, not every matched row as the schema said),
  `epcor_get_daily_water_quality` (`date` is inferred from a year-less label),
  `senate_get_vote` (yeas, nays and abstentions counted from the ballots, and how many
  malformed rows were skipped) and `ourcommons_get_party_standings` (totals summed by
  province).
- `ircc_list_express_entry_rounds`, `ircc_get_express_entry_round` and
  `ircc_get_latest_express_entry_round`: `invitations_issued`, `crs_cutoff` and every
  `crs_distribution` count (`band_*`, `total`) are now nullable. A blank or missing figure
  in IRCC's feed used to come back as 0, which reads as "no candidates" or "a cutoff of
  0"; it is now null. Every round in the feed had all figures on 2026-10-27, so current
  answers are unchanged.
- `eccc_datamart_npri_facilities`: a record's `year` is now nullable; a row with a blank
  reporting year came back as year 0.
- `hc_device_search_devices` and `hc_device_get_licence`: a device's `licence_number` is
  now nullable; a device with no published licence number came back as licence 0.
- Changelog entries are now one file per change in `changelog.d/` instead of edits to the
  Unreleased section of `CHANGELOG.md`, so pull requests open at the same time no longer
  conflict over it. `scripts/build_changelog.py --version X` writes them into `CHANGELOG.md`
  at release time, and `tests/test_changelog.py` checks each fragment. The tool-surface check
  (`scripts/check_tool_surface.py`) accepts a breaking change named in a fragment.
- CI runs the R and Julia reproduce tests in their own `r-julia` job, with the R library and
  Julia packages cached, instead of on the Python 3.12 leg. The slowest job went from 216 to
  370 s to 138 to 173 s on `main` (2026-10-23 to 2026-10-25), and a skip in that job fails it.
- MapleStats now accepts fastmcp 4.2 (`fastmcp>=4.0.3,<4.3`; it was capped
  below 4.2). `search_tools` and `call_tool` are now built from fastmcp's
  public APIs instead of overriding private methods of its BM25 search, and
  the search index is MapleStats' own. Their names, schemas, descriptions,
  output and ranking are unchanged.
- The English discovery case "ocean water temperature buoy" now expects
  `dfo_iwls_search_stations`, its top result; `dfo_iwls_get_water_levels` had
  matched on "water" alone.
- `provenance.commercial_use` is `not_allowed` for Hydro-Québec results and for Elections
  Quebec and Elections Alberta results (non-profit reuse only), `allowed` for Elections BC
  results (Elections BC Open Data Licence), and `unknown` for Saskatchewan and Manitoba,
  which state no terms; these sources share a multi-publisher licence entry that alone
  would say `varies`.
- `reproduce_workbook`: the Source sheet has a new "Changes made" row listing
  what cleaning changed (columns renamed, text trimmed, empty text left blank,
  text converted to numbers or dates, long integers kept as text), and its
  Attribution row now gives the notice the publisher's terms ask for. For
  Statistics Canada data it is the Open Licence's "Adapted from Statistics
  Canada, <product>, <date>. This does not constitute an endorsement by
  Statistics Canada of this product." once cleaning changed anything, and its
  "Source: Statistics Canada, <product>, <date>. Reproduced and distributed on
  an 'as is' basis with the permission of Statistics Canada." otherwise (in
  French with `lang="fr"`); the product is the table number and the title given.
  For the Bank of Canada and Creative Commons Attribution licences, which ask
  that changes be indicated, the attribution says changes were made. The
  tool results' own `provenance.licence` is unchanged.
- `nwt_stats_list_files`, `nwt_stats_search_files`: the NWT Bureau of
  Statistics relaunched statsnwt.ca, and every topic page now answers a
  redirect or 404 at its old address. The topics point at the new pages, and
  each file's `section` now starts with the collapsible block it sits in
  (for instance "2021 Census > February 9, 2022: Population and Dwelling
  Counts"). Exports of a table shown on a page (`/en/download-xlsx/...`)
  are listed and read as .xlsx files. "(Excel)" and "(Excel File)" are
  dropped from link titles. The module lists about 375 files on 39 topics,
  down from about 630 on 49.
- `search_tools` puts the tools that take an exact identifier first: a tool's own
  name (`boc_get_observations`), a tool-family prefix (`cmhc_dt_`), a StatCan table
  number (`14-10-0287-01`, `14100287`) or a vector (`v41690973`, also how old Bank of
  Canada series are named). A query that was only a table number (`36100434`) used to
  return nothing. The output format is unchanged, and the reviewed discovery benchmark
  scores the same (the boosts only reorder tools below the first accepted one there);
  29 identifier probes go from 0.59 to 0.76 at rank 1.
- The website's tool search applies the same identifier boosts as `search_tools` (a tool
  name or family prefix, a StatCan table number, a vector id), and its index lists tools
  in the server's order, so a search such as `v41690973` or `14-10-0287` ranks the same in
  the browser as through the server.

### Removed

- `nwt_stats_*` topic slugs: `census-2021`, `census-2016`, `census-2011`,
  `census-2006`, `census-2001` and `census-1996` are merged into `census`,
  one page for all six censuses; `oil-gas` and `minerals` are merged into
  `oil-gas-minerals`. `manufacturing`, `community-data` (the statistical
  profile of each community), `statistics-quarterly`, `socio-economic-scan`
  and `community-statistics-summary` are removed: the relaunched site has no
  page for them. A call naming a removed slug is refused with the list of
  current topics.

### Fixed

- `bc_env_get_snow_station_data`, `bc_env_get_snow_readings` and `bc_env_get_streamflow`:
  a cell holding text that is not a number became a null value with nothing said; the notes
  now count those cells, and `bc_env_get_streamflow` also counts rows skipped for having
  fewer than the file's 10 columns.
- `epcor_get_daily_water_quality`: a cell holding text other than a number or EPCOR's "--"
  missing marker (a "<0.01", say) became null with nothing said; `provenance.limits` now
  names those cells.
- `bc_env_list_wells`: when the groundwater-trends table that gives each well's region
  failed, every well came back without a region and that list was cached for 6 hours, so a
  `region=` filter returned 0 wells. The list now says the regions are missing, is not
  cached, and a `region=` filter raises an error instead.
- `aer_get_well_licence_archive_link` and `aer_get_production_volumes_link`: any answer
  other than 200 (a 403, a 429 or a 5xx) was reported as "no file at this address" and
  cached. Only 404 and 410 mean the file is absent now; anything else raises an error and
  is not cached.
- `arcgis_hub_get_dataset`: when the portal's layer list or download API failed,
  `download_urls` was an empty list with nothing to tell it from an item with no downloads.
  `provenance.limits` now says the lookup failed (and, for Red Deer, that the portal's
  download API fails for every item), and a failed lookup is no longer cached for an hour.
- `ourcommons_get_party_standings` and `ourcommons_get_ministry`: a row without a seat
  count or an order of precedence read as 0; it is now an error naming the missing field.
- `electricity_ontario_*`: an hour or interval number missing from an IESO file became
  hour 0; it is now an error naming the missing field.
- `reproduce_code`: for tools that ask the source only for a row count before or after
  their data query (`ab_wildfire_get_fires`, `ab_wildfire_get_fire_perimeters`,
  `eps_list_occurrences` with ArcGIS `returnCountOnly=true`; `electricity_quebec_*` with
  Opendatasoft `limit=0`), the script replayed the count request and returned no rows while
  labelled "exact". Count-only requests are now skipped when choosing the request to replay.
- `reproduce_workbook`: code columns (StatCan coordinates, vector and product ids, DGUIDs,
  postal codes, NAICS, NOC and SGC codes) stay text, as `reproduce_code`'s scripts keep
  them, so coordinates "2.1" and "2.10" no longer collide as the number 2.1. The response's
  notes now say how the rows were cleaned, which columns were converted from text and which
  were kept as codes, and name the fields of the tool's result left out of the rows (a
  total, a truncated flag, a second list); their values go on the Source sheet.
- `represent_search_representatives` with `level="municipal"`: the scan stopped after 8
  pages of 1,000 and reported `has_more=false` with a partial total. It now says the scan
  stopped and sets `has_more`. A representative set that grows past one page of 1,000 is
  read page by page instead of cut at 1,000. `represent_lookup_postcode` and
  `represent_lookup_point` list boundary sets past the 25 whose details are loaded (marked
  `detail_loaded=false`) instead of leaving them out, and a note says how many lack details.
- `ab_wildfire_get_fire_restrictions`: each layer was read with one page of 2,000 polygons
  and a fuller layer was cut silently; further pages are now read.
- `cwfis_get_weather_stations` by point: when the search box holds more stations than one
  request returns, `provenance.limits` says nearer stations may be missing.
- `bc_env_list_wells` and `bc_env_list_snow_stations`: a BC Geographic Warehouse layer
  that outgrows the 5,000-feature request is now an error rather than a silent cut.
- `transit_get_stop_departures`: a station with more than 50 child stops now says
  departures cover the first 50.
- `bc_lobbyists_get_registration`: a filer-client pair matching more than 20 registrations
  now says how many were left out.
- `ckan_list_organizations` and `ckan_list_groups` (BC portal): a facet roster that fills
  its 500-entry limit now says more may exist.
- `nrcan_minerals_get_production` and `nrcan_minerals_get_series`: 1991-1998 values
  marked revised ("386 ʳ") were read as not available; they are now numbers. A new
  `value_as_published` keeps each cell's text, and `provenance.limits` counts values that
  are not numbers and data rows shorter than the header. `nrcan_minerals_get_series` names
  the years where the commodity matched rows in several groups and the group whose row
  it shows.
- `hc_nhp_get_product`: a dose age, dose or frequency given only as a minimum or a
  maximum lost the figure ("year(s)" for "19+ year(s)"); it is now shown as "19+" or
  "≤12". `provenance.limits` says these texts, and `potency`, are composed by MapleStats,
  and that the source's 0 for "not given" is left out.
- `ised_clean_growth_get_federal_investment`: an amount with a scale word other than
  billion or million was read as plain dollars; it is now null. Each table row has a new
  `value_as_published`, `headline.not_found` lists headline figures whose sentence was not
  found in the page, and `provenance.limits` names both.
- `pmra_get_residue_limits` has a new `mrl_as_published` with the extract's own text, and
  says when a value is not a number. The PMRA tools count extract rows skipped for a wrong
  number of cells in `provenance.limits`, and `pmra_get_product` raises an upstream error
  when the record's row is malformed instead of answering "no product".
- `ised_ip_horizons_get_patent` and `ised_ip_horizons_search_patents` say in
  `provenance.limits` when -1/-2 codes, "Unknown" provinces or non-ISO dates in the files
  were returned as null.
- Rows dropped while reading a file are now counted in `provenance.limits` or `notes`:
  `cdc_get_component_prices` (unreadable class or date), `cdc_query_market_data`
  (unreadable dates, and values that are not numbers), `cgc_exports_describe` and
  `cgc_exports_query` (short rows, unreadable year, month or tonnage),
  `recalls_search` and `recalls_summarize` (rows with no numeric notice id),
  `dfo_iwls_get_water_levels` (time steps with a null value) and
  `eccc_datamart_ghgrp_facilities` (rows with no readable year, new `rows_without_year`).
- `eccc_datamart_ghgrp_facilities`: `total_co2e_sum` counted a blank total as 0 without
  saying so. It is now labelled as computed by MapleStats, and a new `total_co2e_blank`
  (with a note) counts the matching records it leaves out.
- `cra_charities_search`, `cra_charities_get_charity` and `cra_charities_get_directors`:
  when open.canada.ca's search finds no list with the tables a tool needs, the pinned 2024
  list is used as before, but `provenance.limits` now says it is a fallback, why, and
  that a newer list may exist.
- `cra_digital_economy_registry_search`: a registry table with no readable row (a layout
  change) raised nothing and answered 0 registrants; it is now an upstream error. Rows
  skipped for a missing cell are counted in `provenance.limits`.
- `nfd_describe_table`: a data dictionary that failed to download or open left
  `dictionary_title`, `source` and `last_updated` null with no word, and the failure was
  cached for hours. The response now says so in `quirks` and `provenance.limits`, and the
  next call tries the dictionary again.
- Health Canada drug, natural health product, device and vigilance tools: a sub-table
  lookup that answered HTTP 404 with an error message (an endpoint the API no longer has)
  was read as "no rows"; only the empty 404 the API sends for no rows is, and the other is
  now an upstream error.
- Lists cut for size now say so. `eccc_search_collections` gives the number of all
  matches in `coverage` and a `provenance.limits` sentence when `limit` cut them;
  `gazette_list_issues` has a new `total_in_feed` and says when `limit` cut the feed;
  `nrcan_geo_locate` has a new `total_found` and says when `limit` cut the results or the
  Geolocator sent results without coordinates; `pmra_search_products` says when
  `by_product_type` lists only the 15 most frequent types, and `pmra_get_residue_limits`
  when `chemicals` lists only the first 50; `hc_drug_search_ingredients` has a new
  `strength_count` per ingredient and says when `strengths` was cut to 8;
  `recalls_summarize` says when a cut on years leaves out the undated ("unknown") group.
- `hc_device_search_devices`: a name search returning more than 25 devices skips the
  model-number lookups, so every `identifiers` list was empty with nothing saying why. A
  new `identifiers_included` field and a `provenance.limits` sentence now say so.
- `tc_recalls_search`: when a search matches more than the 100,000 rows read, a new
  `all_rows_read` field is false and `note` says that `total_matched` is a lower bound and
  that the newest recalls may be missing (it was said only in `provenance.limits`).
- `eccc_coverages_get_data`: a request (one scenario, percentile or season) that returned
  no value is named in `notes`, rather than its rows being silently absent.
- `finance_frt_get_table`, `finance_fiscal_monitor_get_tables`: cells published as "-",
  "..", "n/a" or "s.o." all became null, so nil and not available looked the same. A new
  `symbols` list keeps each marker as published, with its row and column; a Fiscal Monitor
  column holding only markers is no longer dropped as empty.
- `isc_*`: whole numbers were read by stripping every non-digit, so "12.5" became 125 and
  "-3" became 3. Only thousands separators are dropped now; anything else that is not a
  whole number is null.
- `isc_get_registered_population`: a residence's `total` was `men + women` with a missing
  figure read as 0, so a blank sex made the other one the total; it is now null when either
  is missing, and the all-residence `men` and `women` sums are null when any residence lacks
  the figure. These fields, and `isc_get_first_nation_profile`'s `total_reserve_hectares`,
  are now described as computed by MapleStats; the profile adds `reserves_without_hectares`,
  the reserves with no published area that the total leaves out.
- `elections_provincial_get_results`: vote shares, valid votes and Manitoba's turnout that
  MapleStats computes (where the source publishes none) read as published. New
  `vote_share_computed`, `valid_votes_computed` and `turnout_computed` flags say which ones
  are computed, and `elections_provincial_get_seats` describes its totals and shares as
  computed.
- `borealis_odesi_search_variables`: any HTTP 403 from the DDI export read as "no
  variable-level DDI" and was cached. Only Borealis's own "Export Failed" answer means that
  now; another 403 (a proxy or firewall refusing the request) is an error, not cached.
- `cimt_get_trade`, `cimt_get_top_commodities`, `cimt_get_series`, `cimt_search_commodities`:
  when StatCan's commodity or unit code list failed to load, descriptions and units were
  silently missing (top commodities were named by their code). The trade values are still
  returned, and `provenance.limits` now says which names could not be loaded.
- `cbsa_tariff_list_editions`, `cbsa_tariff_lookup`, `cbsa_tariff_search`: a year page
  answering HTTP 404 read as "no editions that year" and was cached for six hours, so
  `latest` could fall back to an older edition without saying so. A year asked for with no
  page is now a NotFound naming the page, never cached; the default two-year listing returns
  the year it could read, with a new `missing_years` and a limits note; and an edition by
  date only steps back past the current year when that year's page is not posted yet.
- `crea_get_hpi_links`: a failed check for the month's zip (no answer, HTTP 403 or 5xx)
  looked like "no zip yet" and was cached for the month. A new `zip_check` (`found`,
  `not_found`, `failed`) and a limits sentence tell the two apart, and a failed check is not
  cached.
- Results cut without saying so now say so:
  - `borealis_search_ivt`: new `total_matched` and `truncated`, and `provenance.limits`
    says how many IVT files were left out and that files come from the top 10 datasets.
  - `nl_stats_read_file`: a sheet longer than 20,000 rows was read to that cap with
    `total_rows` counting only the rows read; `truncated` is now true and the limits say
    so, and each entry of `sheets` has a `truncated` flag.
  - `pbo_get_publication`: charts (SVG), images and print-only blocks were dropped
    silently; a new `left_out` counts them by kind and the limits name them. An HTML slice
    without a table, which was dropped, is now part of `text`; a cut text is named in the
    limits too.
  - `phac_infobase_describe_dataset`: `geo_values` stops at 40 places; a new
    `geo_value_count` gives how many there are, and the limits say when it is cut.
  - `statcan_daily_get_releases`: new `total_in_feed` and `truncated`, with a limits note
    when `limit` cut the feed.
  - `sdmx_space_search`: facets stop at 6, each with its 8 most frequent values; a new
    `value_count` per facet and a limits note say when either cap cut them.
- `worldbank_*`: the WDI indicator list was read as one page of 2,000 with no check; the
  next pages are now read when there are more, and a list short of its stated total is an
  error rather than a search that silently misses indicators.
- `nfd_*` tools: the National Forestry Database moved from nfdp.ccfm.org to
  national-forestry-database.ca (French pages on
  base-donnees-national-forets.ca), and every tool refused the redirect to the
  new host. The module now reads the new hosts over http (their https
  certificate chain is incomplete) and still accepts the old one. A link that
  ends on the NFIS "not found" page, as the fire tables' comments links did on
  2026-10-26, is reported as a missing file instead of a refused redirect.
- `nwt_stats_read_file`: the census and community survey pages link their
  files on bearnet.gov.nt.ca, a staging host that asks for a login. Those
  links are read from the same path on www.statsnwt.ca, where the files
  answer.
- `sdmx_get_data`, `sdmx_get_vector_data`: each observation's own SDMX attributes
  (STATUS_CAN, SYMBOL, SECURITY_LEVEL) are read and decoded into `status_code`/`status`,
  `symbol_code`/`symbol` and `security_level_code`/`security_level`. A suppressed or
  estimated value used to come back as a bare null or number, and a value StatCan
  writes as "NaN" (status F) came back as NaN instead of null.
- `boc_get_observations`, `boc_get_group_observations`: a value Valet sends as text
  that is not a number is still null in `values`, but its text now comes back in the
  row's `non_numeric`, and provenance.coverage counts them; before, it became a null
  with no note. `series` entries also carry Valet's `unit` and `frequency` metadata.

## [0.4.2] - 2026-10-24

0.4.1 was prepared on 2026-10-20 but never published, so its changes ship here too.

### Added

- A circuit breaker per upstream host (`shared/breaker.py`). After 5 failures in a row
  within 5 minutes (timeouts, connection errors, 5xx answers, Cloudflare challenges) a host
  is paused for 60 seconds: its tools fail at once with `UpstreamUnavailable`, in English or
  French, naming the host and when to try again, instead of each caller waiting out another
  timeout. After the cooldown one request goes through as a probe and an answer closes the
  breaker. A call and its retries (`shared/http.py`, `shared/retrying.py` and the modules'
  own retry loops) count as one failure, and 4xx answers never count. Settings:
  `MAPLE_BREAKER` (`0` turns it off), `MAPLE_BREAKER_FAILURES`,
  `MAPLE_BREAKER_WINDOW_SECONDS`, `MAPLE_BREAKER_COOLDOWN_SECONDS`.
- `docs://status`, a bilingual resource listing the hosts paused now and when each is
  tried again.
- `/stats` adds `latency_ms` (each tool's p50 and p95 over its last 500 calls) and
  `upstreams` (the breaker settings, and per host its error counts by kind, refused
  requests, times opened and current state). Still in memory, with no arguments and no
  client addresses; the FAQ and privacy page say so.
- A breaking-change check on the tool surface: `tests/test_tool_surface.py` compares
  `tool_catalogue.json` with its version at the merge base with `origin/main` and fails while a
  breaking change (tool or parameter removed or renamed, type narrowed, required parameter
  added, output field removed) names a tool this Unreleased section does not mention.
  `uv run python scripts/check_tool_surface.py` prints the breaking, additive and other changes.
  CI now checks out the full history for it.
- A weekly `Newest FastMCP` workflow that runs pyright and the test suite against the newest
  `fastmcp`, past the `<4.2` cap, and reports a failure in its run summary without blocking
  merges.

### Changed

- The server imports a module's code only when one of its tools is first called. `tools/list`
  and `search_tools` now read `tool_catalogue.json`, a generated listing of every tool (name,
  title, docstring, schemas, annotations), so importing the server took 5.8 s instead of 20.4 s
  in interleaved runs on 2026-10-23 (Windows, Python 3.12). The first call into a module pays its
  import once (1.5 s for `boc`, 3.2 s for `statcan/wds` in the same runs); later calls are
  unchanged. Listings, search results and the discovery benchmark's scores are identical. Without
  the catalogue file, or for a module it does not list, the server loads modules at startup as
  before. Regenerate it with `uv run python scripts/build_tool_catalogue.py`;
  `tests/test_tool_catalogue.py` fails while it is stale.
- Website: the Connect page's hosting table now lists `MAPLE_CLIENT_IP_HEADER`,
  `MAPLE_TRUSTED_PROXY_HOPS`, `MAPLE_DUCKDB_MEMORY_LIMIT`, `MAPLE_DELTA_MAX_SCAN_MB`,
  `MAPLE_DELTA_MAX_SCAN_SECONDS` and `MAPLE_DELTA_INDEX_DIR`, which the README already
  documented, and a test fails when a setting in `config.py` is missing from it.
- Hosting: the public endpoint keeps Render's 750 free instance hours to itself. The chat
  demo runs in its own Render workspace from `chat/render.yaml`, at
  `https://maplestats-chat-ydx4.onrender.com`, and the site links there. The FAQ (English and
  French) and README say what a cold start costs (35 s measured, up to a minute) and that the
  hosted endpoint is off until the 1st if the month's hours run out.
- Dependabot opens one grouped pull request a month for each ecosystem, covering the server
  and the chat demo together, and collects security fixes into one pull request instead of
  one per advisory and lockfile.
- Dependencies: `duckdb` 2.0 (the open-database and microdata readers were checked against
  it) and, for the chat demo, `anthropic` 2.1.

### Removed

- Smithery publishing: the release workflow's `smithery` job, `scripts/build_smithery_bundle.py`,
  the pinned CLI in `.github/smithery/`, and the Smithery badge in the README and site.
  Smithery answered the 0.4.0 publish with HTTP 403 ("Updating servers has been removed")
  and shuts down its API and CLI on 2026-10-31.
- `keepalive.yml`: GitHub ran its 10-minute schedule only about every four hours, so it never
  kept the free instance awake.

### Fixed

- `bc_env_list_streamflow_gauges` and `bc_env_get_streamflow` with `parameter="stage"`:
  `Stage.csv` now carries 2- to 15-minute readings and grows about 1.3 MB a day (29.7 MB on
  2026-10-20), so the 64 MB cap set in 0.4.0 would run out by mid-November. The gauge list
  now streams the file and keeps one row per station, and past 64 MB a single gauge is read
  by range; with no `start`, that range read covers the last 14 days first and says so in
  the notes.
- `nrcan_nbac_query_fires` with `include_geometry=true`: a GeoJSON answer over the 20 MB
  response cap (the five largest 2023 BC fires are 33 MB) now returns the fires without
  geometry, counted in `geometry_omitted`, instead of an error.
- Range reads (transit GTFS feeds, zip members, sorted archives): a 200 answer to a range
  request from a host that advertises `Accept-Ranges: bytes` is retried twice after 3 s.
  RTC Québec's CDN answered one such request in full on 2026-10-19 and honoured it later.
- `cwfis_get_forecast`: once the fire season ends the SCRIBE forecast layer is empty
  (2026-10-20), and every station name answered "No forecast station name contains ...".
  An empty layer now gets its own message pointing to `cwfis_get_fire_danger`.
- The Cloudflare-challenge error named Statistics Canada for every host, including
  Alberta's economic dashboard, in both languages; it now says the publisher.
- Live smoke tests: `smoke_test_arcgis_hub` rechecks only its failing portals after a
  minute (a full pass takes 15 minutes, so the workflow's whole-script rerun ran out of
  time), the smoke job timeout is 40 minutes, `smoke_test_ab_economic` skips on a GitHub
  runner that Cloudflare challenges, as `smoke_test_modules` already did, and
  `smoke_test_bc_environment` reads a current stage series.

### Security

- `fastmcp` 4.1.3 in the lockfile. 4.1.2 applies component authorization after transforms
  and stops denied resources falling through matching templates. `certifi` 2026.10.23 and
  `opentelemetry-api` 1.45.1 clear the other open Dependabot alerts. Installs with `uvx`
  already resolve these within `pyproject.toml`'s ranges.

## [0.4.0] - 2026-10-20

### Removed

- `statcan/census_tables` (`statcan_census_tables_*`) and `statcan/census_profile_2016`
  (`statcan_census_profile_2016_*`): Statistics Canada's www12 host answers automated
  clients with a bot challenge, 503 errors or timeouts. The 2021 profile, the archive
  download links and WDS tables 17100122 and 17100123 (2016 indicators down to health
  regions) remain. The matching `reproduce_code` builder, planner steps and smoke tests
  went with them.

### Added

- `plan_query`: a `statcan_tables` topic for whole tables, bulk series and vector IDs. It is
  chosen by words such as "full table", a CSV or a vector near "StatCan", and "reconcile"
  near a workbook of vectors, or by a table number like 36-10-0222 or a vector ID like
  v41690973, and starts with `wds_get_full_table_download`. A question
  about reconciling a workbook of vector IDs against a published table used to get only
  provincial portals.
- `cra_charities` module: search CRA's annual List of charities by name, city, province
  or designation, look one up by business number, and list its directors and officers
  (open.canada.ca DataStore, Open Government Licence - Canada).

### Changed

- `MAPLE_DUCKDB_MEMORY_LIMIT` limits DuckDB's memory for queries over downloaded files, and
  `MAPLE_CLIENT_IP_HEADER` (such as `CF-Connecting-IP`) keys the per-client rate limit on the
  caller's own address behind Cloudflare. The hosted instance sets both, and allows 8
  concurrent requests (was 4).
- `fastmcp` is capped below 4.2, because the server uses internals of 4.1.
- The README, FAQ and Connect page say the first request to the hosted server after a quiet
  spell can take up to a minute.
- CI: a new `Docker images` workflow builds the server and chat images and checks that the
  server image starts and answers `/health`. Render deploys from those Dockerfiles, and no
  workflow built them before. CI also runs the chat demo's lint and tests (`chat/`).
- `search_tools` answers are about 38% smaller (a compact answer is 12 to 20 KB, by query): the
  Provenance schema that every tool's result carries is shown once as a short description
  instead of five full copies. Input schemas and the tools' own result schemas are unchanged.
- The server instructions and the docstrings of the WDS vector tools now say that vectors come
  back inline and suit a handful of series, and point to `wds_get_full_table_download` (a CSV
  link with a `VECTOR` column) for a whole table or hundreds of series.
- Discovery: `search_tools` now puts `wds_search_cubes` first for "consumer price index monthly"
  and "population estimates by province" (they led with a real-estate index and PUMF
  tabulation), and `bcgw_get_active_wildfires` ahead of the BC air-quality tool for
  "wildfires British Columbia". Docstring keywords only; the three cases are in
  `tests/test_english_discovery.py`.
- `search_tools` keeps the Provenance definition when another field still refers to it, instead
  of leaving a dangling `$ref`. The compact-answer test now compares sizes against the same
  tools' full schemas over several queries rather than a fixed byte limit.
- The server's Docker image is built on `python:3.14-slim` (it was `python:3.12-slim`), pinned
  by digest. The package classifiers list Python 3.14, and CI tests it.
- Website: the home page's "See it in action" section is a question box, a plain GET form to
  the chat demo that works without JavaScript, beside four example questions and the demo's
  caveats, instead of a stack of example rows.
- Website: the privacy page also covers the chat demo (questions go to a third-party language
  model provider, Anthropic by default) and the website itself (GitHub Pages). The FAQ says the
  server does not write tool arguments down and that HTTP access logs can include the network
  address.
- Website: pages count visits with GoatCounter (page, referrer, browser, operating system, screen
  size and country as aggregate counts; no cookies, no IP address stored), in a GoatCounter site
  shared with other hostnames, so every path starts with the host. The privacy page and the FAQ
  say so; the MCP server and the chat demo are not counted.

### Fixed

- `boc_get_group`: the Bank of Canada renamed the group payload from `groupDetails` to
  `groupDetail` in October 2026, so every group lookup failed with "its payload may have
  changed". Both names are now read.
- `bc_env_list_streamflow_gauges` and `bc_env_get_streamflow` with `parameter="stage"`:
  `Stage.csv` now carries 2- to 15-minute readings and passed the 16 MB download cap 19 days
  into the water year (about 500 MB by September). The gauge list now streams the file and
  keeps one row per station, and a single gauge is read by range; with no `start`, that
  range read covers the last 14 days first and says so in the notes.
- `nrcan_nbac_query_fires` with `include_geometry=true`: a GeoJSON answer over the 20 MB
  response cap (the five largest 2023 BC fires are 33 MB) now returns the fires without
  geometry, counted in `geometry_omitted`, instead of an error.
- Range reads (transit GTFS feeds, zip members, sorted archives): a 200 answer to a range
  request from a host that advertises `Accept-Ranges: bytes` is retried twice after 3 s.
  RTC Québec's CDN answered one such request in full on 2026-10-19 and honoured it later.
- The Cloudflare-challenge error named StatCan for every host, including Alberta's
  economic dashboard; it now says the publisher.
- Live smoke tests: `smoke_test_arcgis_hub` rechecks only its failing portals after a
  minute (a full pass takes 15 minutes, so the workflow's whole-script rerun ran out of
  time), the smoke job timeout is 40 minutes, `smoke_test_ab_economic` skips on a GitHub
  runner that Cloudflare challenges, as `smoke_test_modules` already did, and
  `smoke_test_bc_environment` reads a current stage series.
- A TLS verification failure on PHAC's host is reported as such instead of as a timeout.
- Caller-facing typed errors (about 70, across fcac, nfd, IP Horizons, provincial elections,
  health products, CMHC data tables, the reproduce builders and the shared Cloudflare
  challenge) now follow `lang="fr"`. A LODE download that answers 404 raises `NotFound`, and
  its redirects get the shared host check.
- A server started with `uvicorn maplestats_mcp.asgi:app` (no `MAPLE_TRANSPORT`) counts as
  HTTP, so `reproduce_workbook` no longer writes to the server's own disk and the export tools
  describe themselves as hosted.
- Idle MCP sessions on the hosted server are dropped after 5 minutes instead of 30.
- `plan_query`: the `statcan_tables` topic no longer fires on the disease or map sense of
  "vector". "Vector" and "vecteur" count only within 60 characters of a word that places them
  in a table (table, series, StatCan, CANSIM, workbook, ID, a v-number), so "tick vectors",
  "maladies transmises par les vecteurs" and "vector GIS data" get the usual `search_tools`
  fallback instead of a plan for StatCan vectors; "vector-borne", "vector control", "maladies
  à vecteur", "vector data", "vector file", "vector layer" and "vector map" never count.
- `plan_query`: "reconcile" and "rapprochement" count only within 60 characters of a vector, a
  workbook or a published table, so "reconciliation with First Nations: table of land claims"
  and "le rapprochement des partis selon les séries de sondages" no longer pick
  `statcan_tables`; "truth and reconciliation" and "bank reconciliation" never count.
- `plan_query`: "CSV", "bulk download", "bulk data" and "téléchargement en bloc" count only
  within 60 characters of a word that names StatCan (StatCan, Statistics Canada, CANSIM, WDS,
  a cube, a vector), so "CSV download of Toronto building permits" and "bulk data on Calgary
  property assessments" no longer get a plan for StatCan tables.
- `plan_query`: a table number must be a real StatCan one (subject 10 to 46 or 98, product
  type 10, sequence not a year), so dates such as 15-01-2024 or 10-10-2023 no longer match.
  New cues: a vector ID on its own ("v41690973", which also puts `wds_get_series_info` first),
  a bare productId next to the word "table" ("table 14100287", "table 3610022201"), and the
  French plurals "tableaux complets" and "télécharger les tableaux". `matched_terms` names the
  cue word ("reconcile"), not the whole stretch of the question around it, and the full-table
  step says that `product_id` is the table number.
- Discovery in French: "estimations de population par province" now starts with
  `wds_search_cubes`, as its English twin already did. The PUMF tabulation tool's French
  keywords still said "estimation de population"; they now say "total pondéré", matching the
  English "weighted total".
- Chat demo: the page can no longer be framed by another site (`frame-ancestors 'none'`,
  `X-Frame-Options: DENY`), and a `?q=` link sends its question by itself only when it comes
  from the website; from anywhere else it fills the box and waits for a click. Each question
  is a billed model call, so a page that embedded or linked the demo could otherwise spend
  its daily limit through its own visitors' browsers. A question that fails is put back in
  the box, so trying again does not mean retyping it. Every website page now states its
  referrer policy (`strict-origin-when-cross-origin`), so the demo can tell a visitor came
  from the website without relying on a host header or browser default, and a test checks
  that the origin the demo trusts is the website's.
- Chat demo image: `chat/Dockerfile` installs from `chat/uv.lock` with `--locked`, as the
  server's image does, instead of resolving the newest versions at build time. It now uses
  the server image's base, `python:3.14-slim` pinned by digest, instead of an unpinned
  `python:3.12-slim`, and Dependabot bumps both digests in one pull request.
- `plan_query`: a vector ID beside the word "vector" ("vector v41690973") counts as one
  `statcan_tables` cue, not two; the ID counted once as itself and again as the word's
  neighbour.
- Chat demo: a request that fails after a billed model call stays counted against the
  hourly and daily limits (only a failure before any call is refunded), and the failure
  log names the HTTP status.
- Logs: failed resource reads and prompt renders no longer log their arguments or
  tracebacks, as failed tool calls already did not.
- `reproduce_workbook`: the attribution line names the licence's own jurisdiction
  (Yukon, Newfoundland and Labrador, Northwest Territories and others), not only
  Canada, Alberta, British Columbia and Ontario.
- `reproduce_code`: a request body that is neither JSON nor form fields now gives no
  script, with a note, instead of a script that silently drops the body; a missing
  response field is an upstream error, not invalid input.
- `cra_charities`: each tool uses the newest list that has the table it reads, business
  numbers accept ASCII digits only, and a truncated directors list says so.
- Smoke scripts: an upstream outage skips only the checks after it, so earlier failures
  still fail the run.
- Downloads stop at their byte cap instead of reading the whole file first and rejecting
  it afterwards: `csv_files` (CER, GC InfoBase, CDC, election results), `remote_zip` (a
  host that stops honouring `Range` no longer makes the server buffer a multi-gigabyte
  archive), and the file readers in bc_lobbyists, recalls, cgc, ircc_monthly, nfd,
  finance_canada, phac_infobase, elections_provincial, cfia, ised_clean_growth, isq,
  nl_stats, cihi, pmra, nrcan_minerals and pmprb. A central directory larger than 64 MB
  is refused.
- A page whose expected content is missing is now an upstream error instead of an empty
  result cached as a success: `cmhc_list_categories` and `cmhc_list_provinces` (24 h),
  CIHI's indicator library (7 days), NL Stats topic pages (6 h), and an Earthquakes
  Canada 404 (which read as "no earthquakes").
- `statcan_surveys_get_survey_metadata`: a 5xx answer is no longer cached for a day.
- `sdmx_get_structure` and `sdmx_get_key_for_dimension`: when the SDMX structure document
  is empty and the dimensions are rebuilt from WDS, every member is read (paged at 2,000),
  not the first 100; a geography or NAICS dimension with more than 100 members used to be
  silently truncated and its OR key incomplete.
- `plan_query`: the French word for gold ("or") no longer matches the English conjunction
  and sends questions to the minerals tools; "yield" and "dollar" alone no longer put the
  Bank of Canada first for "canola yield" or "a million dollar question"; duplicate plural
  terms no longer double-count a topic; "minéraux critiques" and "tps/tvh" match again;
  "London, England" and "Victoria, Australia" are out of scope instead of Ontario or BC.
- `electricity` (Hydro-Québec): the recent-generation and trade queries share the 5-minute
  cache again; the cutoff time was written to the second into the cache key.
- `boc`: a Valet payload missing `seriesDetails`, `groupDetails` or a date column is an
  upstream error naming the field, not a `KeyError`.
- `oeb_get_dataset_file`: a numeric `file` position counts within the chosen release; "0"
  and positions past the end are invalid input. Zero-padded codes stay strings.
- `reproduce_code("reproduce_workbook", ...)` is invalid input and no longer writes a
  workbook as a side effect; `reproduce_workbook` writes header cells as text, so a series
  name starting with "=" cannot become a formula; the Julia POST body is escaped once, so
  a "$" in it yields valid JSON.
- Typed errors where a bare exception or the wrong class escaped: PUMF tabulation
  (DuckDB errors, a missing replicate id variable, cache eviction on Windows), Delta CSV
  rows, CIMT province codes, WDS failed-envelope links and code sets, SDMX 400/403,
  AER daily well licences (a 404 was "did not respond"), DriveBC protocol errors,
  Health Canada non-JSON answers, BC election results, Borealis searches (Solr operators
  in the query are now literal, a 400 is invalid input), CKAN organization lists,
  ECCC coverage 406/409 answers, Competition Bureau weekly rows, CRA charities null
  totals, NRCan Geonames bounding boxes (validated before the request), the arcgis_hub
  download-format probe, and IRCC monthly totals (an unreadable cell is counted and
  noted instead of failing the table).
- French: `transit` stop-time errors, the `_example` template's `lang`, and the CMHC,
  Finance Canada and ISED clean-growth number parsers (a French decimal comma was read
  as a thousands separator or the reverse). Notes in `ab_opendata`, `bc_environment`,
  `bc_lobbyists`, `boc`, `crea`, `eccc_datamart`, `represent` and `transit` now agree in
  gender and number ("lectures limitées") and address the reader as "vous" ("Ne supposez pas",
  "vérifiez"); `bc_lobbyists` says "lobbyisme", and the locked-data message names Statistique
  Canada, not StatCan.
- Website: the home page's chat card no longer widens past its column on phones, and its
  example questions open the chat demo with the question asked instead of doing nothing. The
  chat page asks a `?q=` question on arrival, scrolls to the start of an answer, shows a focus
  ring, and explains a non-JSON gateway error while the host wakes instead of printing a JSON
  parse error.
- `/stats`: `reproduce_code` and `reproduce_workbook` call the server again in-process, and
  that inner call counted as a second call by the caller; it no longer does.
- A response that does not fit a tool's model is an upstream error ("the source answered in a
  shape this tool does not expect"), no longer reported as invalid arguments, and the error
  does not echo the values.
- Retries read `Retry-After` as whole seconds or an HTTP date, the same as the rate-limit
  handling; a header made of non-ASCII digits (such as "²") no longer raises.
- `MAPLE_TRANSPORT` accepts only `stdio` or `http` and `MAPLE_PORT` must be an integer;
  a typo used to start an HTTP server while the client waited on stdin, or bind 8000
  while the health check probed the typo. Other numeric variables warn once when ignored.
- `uvicorn maplestats_mcp.asgi:app` now applies the `MAPLE_REQUIRE_AUTH` refusal and the
  external-bind warning, which only `python -m maplestats_mcp` did before.
- `maplestats-mcp --version` prints the version, as SECURITY.md asks reporters to run.
- A subdomain wildcard in `MAPLE_ALLOWED_ORIGINS` matches an origin with a port.
- CI runs the tests that execute the generated R and Julia scripts on the 3.12 leg; they
  skipped on every run because the runner had neither. `setup-uv` is pinned to the
  Dockerfiles' uv version, every workflow declares `permissions`, Dependabot covers
  `chat/uv.lock`, and `server.json` lists the hosted Streamable HTTP endpoint.
- Docs: the README environment table lists `MAPLE_USAGE_STATS`, the LODE cache variables
  and `MAPLE_EXPORT_DIR`; four broken relative links in `docs/`; the roadmap's release
  and monitoring rows; the connect page's volume count.

### Security

- `reproduce_code`: the tool name is validated against the registry and sanitised before it
  is written into the Stata `log using` line; a crafted name used to inject a `shell` line
  into the generated do-file. The PUMF builder checks the ZIP URL against StatCan's host
  the way the PUMF tools do, instead of emitting a script that downloads and unzips any
  URL it was given.
- `isq`: a table URL is accepted only when its host is exactly `statistique.quebec.ca`;
  a string-prefix check let `statistique.quebec.ca.example.net` and
  `statistique.quebec.ca@example.net` through (server-side request forgery).
- `csv_files` and `nfd` re-check the host allow-list on every redirect hop; the chat demo's
  `/api/chat` requires `Content-Type: application/json` (a cross-site "simple" POST from
  any web page could spend the model budget) and trusts `X-Forwarded-For` only on Render
  or when `CHAT_TRUST_PROXY_HEADERS=1`; its CDN scripts carry integrity hashes and
  DOMPurify is 3.4.17; the Smithery publish step installs from a lockfile with integrity
  checks instead of `npx`; a repeated `X-Forwarded-For` header line can no longer choose
  its own rate-limit bucket.
- `reproduce_code` refuses a redirect, on a request it replays, to anywhere other than the
  request's own site or a file host (never an IP address, localhost or plain http), the rule
  `remote_zip` already applied.

## [0.3.0] - 2026-10-10

### Added

- Issue reporting: a `docs://report-issue` resource and server instructions
  for drafting a bug report when a tool misbehaves. The client shows the final
  text and files it only after the user approves that exact text.
- Prompts follow `lang`, with French bodies, and the eight `docs://` resources
  have French twins.
- Planner: a taxation topic (CRA T1, TFSA, GST/HST, charities) and routes for
  bc_environment, eccc_datamart, health_products and oeb.
- Earthquakes: each result carries a `lookup_id` (the UTC minute the service
  accepts as `eventid`).
- Website: "See it in action" section linking a chat demo, and Claude and
  ChatGPT custom-connector steps on the Connect page.
- Website: touch icon, favicon fallback and web manifest; sitemap `lastmod`.
- Website: a privacy page. Server error logs keep only the exception type, not
  tool arguments or error text.
- Security policy, code of conduct and this changelog. Dependabot keeps the
  pinned actions, Docker base image and Python dependencies current.

### Changed

- Website: moved to <https://maplestats.danielstats.io/>. The old GitHub Pages
  address redirects there, and the hosted server accepts browser calls from
  the new domain only (plus localhost).
- Website: the FAQ's "last updated" date and the About page's "checked in"
  month come from the build date.
- StatCan census notes point `census_tables` users to the 2021 profile.

### Fixed

- Hosted server: rate limits read `X-Forwarded-For` from the right
  (`MAPLE_TRUSTED_PROXY_HOPS`) and apply before the token check; timed-out
  calls count in `/stats`.
- Upstream XML is parsed with defusedxml (Borealis, StatCan Daily, WFS,
  electricity). Bulk downloads and unpacked ZIP members are capped at the
  cache size, and failed unpacking raises typed errors and cleans up.
- Earthquakes: catalogue ids are refused with a message naming the accepted
  minute form. EPCOR: `as_of` is the newest day with a value. Transit: exo's
  moved GTFS feeds.

## [0.2.0] - 2026-10-04

### Added

- 358 tools in 69 modules.

### Changed

- French throughout: errors, notes, provenance, limits and licences of every
  module, the planner's plans and `reproduce_code`'s notes, and the French
  website pages.
- Search: more French function words as stop words, with a parity test for
  the in-page search.
- README: current tool and module counts, every module in the coverage table.
- FAQ: sources not built or removed, and new sources' reuse conditions.

## [0.1.1] - 2026-09-28

### Added

- Case-study pages ("Demos") and release notes on the website.
- Issue templates for bug reports and source requests.
- Registry and listing badges (PyPI, MCP Registry, Smithery, Glama, M8ven).

### Changed

- Near-duplicate Statistics Canada, RDaaS, Bank of Canada and CKAN tools
  merged.
- The three visible tools' descriptions sharpened; English tool discovery
  tested against 98 realistic questions.
- Bank of Canada list tools accept `limit` without a query.

### Fixed

- CDC price CSV with French headers is accepted; an empty Edmonton Police
  Service load-date table now raises a clear "reload in progress" error.

## [0.1.0] - 2026-09-27

First public release: one MCP server for Canadian open data, with
`plan_query`, `search_tools` and `call_tool` in front of every module,
published to PyPI and the MCP Registry.

### Added

- Statistics Canada, Bank of Canada, CMHC, federal agency, provincial,
  territorial and municipal modules, and the CKAN, ArcGIS Hub and Socrata
  portal modules.
- Read-only annotations on every tool.
- PMPRB and Parliamentary Budget Officer modules.
- The bilingual website, generated from the running server.

### Fixed

- Statistics Canada WDS observation release times are read as Eastern time.

[Unreleased]: https://github.com/dsanchezp18/maplestats-mcp/compare/v0.4.2...HEAD
[0.4.2]: https://github.com/dsanchezp18/maplestats-mcp/compare/v0.4.0...v0.4.2
[0.4.0]: https://github.com/dsanchezp18/maplestats-mcp/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/dsanchezp18/maplestats-mcp/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/dsanchezp18/maplestats-mcp/compare/v0.1.1...v0.2.0
[0.1.1]: https://github.com/dsanchezp18/maplestats-mcp/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/dsanchezp18/maplestats-mcp/releases/tag/v0.1.0
