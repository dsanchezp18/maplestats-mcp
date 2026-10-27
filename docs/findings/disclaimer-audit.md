# Disclaimer claim check (2026-10-27)

**Status 2026-10-27: every finding below was fixed the same day** (commits `48473ac`, `b65c25d`, `c67d9af` and the status-code commit; two ISC items were found not to be real). The list is kept as the record.

The disclaimer in the README and on the FAQ makes three claims. This page records where
the code at commit `8b54fd5` does not yet live up to them. Every module was read (client
and tools code, tests excluded); line numbers are from that commit. Nothing here returns an
error-shaped dict, no broad `except` returns a quiet success, and `shared/cache.py` never
serves stale data when an upstream fails.

- **A.** "When a result is trimmed, scaled, cleaned or computed, it says so." Holds in most
  modules, with the gaps below.
- **B.** "When a source is down or blocks the request, the tool returns an error, not a
  silent gap or a substitute value." Holds, except the items marked B.
- **C.** "Each dataset's licence and attribution are in provenance." Holds:
  `tests/test_shared_licences_limits.py` fails for any named source without a licence, and
  the dynamic sources (`ckan-*`, `socrata-*`, `arcgis-*`, `transit:*`) resolve to a
  per-record or per-agency licence.

Kinds: A1 trimmed without saying so, A2 computed without saying so, A3 cleaned without
saying so, B error turned into a gap or substitute, R `reproduce_code` script does not
reproduce the result.

## High

- [x] **R** `reproduce/probe.py:84` `choose()` replays the first request to the chosen
  endpoint. Tools that send a count request first (`ab_wildfire/client.py:525`, perimeters
  at `:890`; `eps/client.py:292`) or last (`electricity/quebec_client.py:189`, picked by
  `ok[-1]`) get a script that replays the count-only or `limit=0` request, labelled
  "exact". Fix: skip `returnCountOnly=true` and `limit=0` requests when choosing.
- [x] **B** `bc_environment/client.py:1157` a failed well-regions CSV becomes `regions={}`,
  and the region-less list is cached for 6 hours; a `region=` filter then returns 0 wells.

## Medium

- [x] **A3** `ircc/client.py:116` `_parse_int` turns blank text into 0: CRS bands dd1 to
  dd18, `drawSize` and `drawCRS` show a missing figure as 0.
- [x] **A3** `reproduce/workbook.py:413` `clean_rows` turns all-numeric text columns into
  numbers with no `CODE_COLUMNS` rule, so StatCan coordinates "2.1" and "2.10" collide
  (the bug `cleaning.py:23` fixed for scripts) and NAICS codes become numbers. The tool
  docstring says "cleaned as the R scripts clean them".
- [x] **A3** `statcan/sdmx/client.py:509` observation attributes (status, symbol) are not
  read, so a suppressed or estimated value comes back as a bare null or number.
- [x] **A3** `finance_canada/client.py:207` "-", "..", "n/a", "s.o." become null with no
  note; nil and not-available look the same.
- [x] **A3** `pmra/client.py:123` CSV rows whose column count differs from the header are
  dropped silently.
- [x] **A3** `ised/clean_growth/client.py:136` a headline figure whose pattern stops
  matching becomes null silently; `:84` an unknown scale word is read as plain dollars.
- [x] **A2** `isc/client.py:468` a residence `total` is `(men or 0) + (women or 0)`, so a
  missing sex makes the other the total; `:413` `total_reserve_hectares` skips reserves
  with no area. Neither is labelled as computed.
- [x] **A2** `electricity/client.py:631` zonal average, minimum and maximum prices are
  computed and unlabelled; `quebec_client.py:278` peak and average demand cover only the
  returned rows.
- [x] **A2** `elections_provincial/common.py:54` `valid_votes` and `vote_share` are summed
  from candidate votes, `manitoba.py:320` computes turnout; the schema reads as published.
- [x] **A1** `health_products/mdall/client.py:394` a name search with `limit>25` returns
  every device with `identifiers=[]` and no note.
- [x] **A1** `represent/client.py:851` the municipal search stops after 8 pages of 1,000
  and reports `has_more=False`.
- [x] **B** `cra_charities/client.py:134` falls back to a pinned 2024 package without saying
  it is a fallback.
- [x] **B** `cra_digital_economy_registry/client.py:176` rows missing a cell are dropped;
  a page layout change gives 0 registrants instead of an error.
- [x] **B** `aer/client.py:249` any non-200 HEAD (403, 429, 5xx) becomes "no file at this
  address", cached.
- [x] **B** `borealis/client.py:329` a 403 from the DDI export is reported as "no
  variable-level DDI", cached.

## Low

A1 (cut without a note or total): `eccc/client.py:307`, `eccc/coverages/client.py:1196`,
`gazette/client.py:140`, `tc_recalls/client.py:149`, `recalls/client.py:655`,
`pmra/client.py:264,423`, `nrcan_geo/client.py:230`, `health_products/dpd/client.py:405`,
`ckan/client.py:492`, `transit/client.py:1009`, `bc_lobbyists/client.py:956`,
`bc_environment/client.py:728`, `ab_wildfire/client.py:1136`, `cwfis/client.py:561`,
`represent/client.py:457`, `nl_stats/client.py:280`, `worldbank/client.py:150`,
`borealis/client.py:226`, `pbo/client.py:333`, `phac_infobase/client.py:774`,
`statcan/daily/client.py:156`, `statcan/sdmx_spaces/client.py:1296`, `isc/client.py:594,802`.

A2 (computed, unlabelled): `eccc_datamart/client.py:1335`, `electricity/client.py:470`,
`epcor/client.py:86`, `senate/client.py:260`.

A3 (cleaned without a note): `eccc_datamart/client.py:1104,1310`,
`ised/ip_horizons/client.py:489`, `health_products/lnhpd/client.py:229`,
`cdc/client.py:565,1286,1306`, `recalls/client.py:213`, `pmra/client.py:370`,
`nrcan_minerals/client.py:146,429`, `dfo_iwls/client.py:327`, `cgc/client.py:966`,
`bc_environment/client.py:869,1033,1577`, `electricity/client.py:458` (missing hour as 0),
`epcor/client.py:78`, `ourcommons/client.py:355,400`, `boc/client.py:225`,
`isc/client.py:186`, `reproduce/workbook.py:353,772`.

B (failure looks like "nothing there"): `health_products/api.py:134` (`missing_ok` 404 to
`[]`), `nfd/client.py:725`, `shared/arcgis.py:324`, `arcgis_hub/client.py:264`,
`statcan/cimt/client.py:404`, `cbsa_tariff/client.py:174`, `crea/client.py:207`.
