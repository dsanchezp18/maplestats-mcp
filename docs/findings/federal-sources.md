# Federal sources

Findings moved from [`ROADMAP.md`](../../ROADMAP.md) on 2026-09-25. Each section
records what was checked, against which live responses, and what the
module does about it. Dates are when a finding was confirmed; the
status in `ROADMAP.md` is the current one.

## IRCC Immigration

**Status:** Shipped.

Express Entry rounds of invitations (tools prefixed `ircc_`): draw history,
CRS cutoffs, invitations issued, and candidate-pool CRS score distribution,
from a static JSON feed at
`canada.ca/content/dam/ircc/documents/json/ee_rounds_123_{en,fr}.json` --
confirmed live 2026-09-18 to be a different platform from CKAN, not an
open.canada.ca dataset. Real quirks found and handled: the French feed's
bytes are Windows-1252 despite a bare `application/json` content type with
no charset (decoding as UTF-8 silently mangles accents instead of raising);
numeric fields use a comma thousands separator in English vs. a literal
space in French; and two rounds from 2018-05-30 are published as "91a"/"91b"
instead of sequential numbers, so `draw_number` is a string, not an int.

IRCC's other administrative series (permanent residents, study/work permits,
asylum, citizenship) are ordinary CKAN datasets published by the `ircc`
organization on open.canada.ca and are already reachable via the existing
`ckan_search_datasets(fq="organization:cic")` on the federal module -- no
dedicated module needed for those.

## Weather / Climate (Environment Canada MSC GeoMet)

**Status:** Shipped.

api.weather.gc.ca, MSC GeoMet-OGC-API (OGC API - Features): `eccc_*`, 4
generic tools (search/list/get collection, query items) covering all ~100
published collections — weather alerts, current surface observations (SWOB),
city forecasts, AQHI, climate stations/daily/hourly/monthly/normals,
hydrometric water level/flow, marine, and long-term climate extremes —
rather than one bespoke tool per dataset. Verified live 2026-09-19: unknown
property filters are silently ignored upstream (return zero rows, not an
error) rather than validated, so the client checks filter/sortby/field names
against each collection's own `/queryables` first; `datetime` filtering
works on some collections (hydrometric-realtime) and returns HTTP 500 on
others (weather-alerts) with no way to predict which from metadata; the
server enforces no upper bound on `limit` even though some collections
exceed 400K rows (hydrometric-realtime); `climate-stations`'
LATITUDE/LONGITUDE properties are integers scaled by 1e7, not decimal
degrees.

api.weather.gc.ca, MSC GeoMet-OGC-API (OGC API - Features): `eccc_*`, 4
generic tools (search/list/get collection, query items) covering all ~100
published collections — weather alerts, current surface observations (SWOB),
city forecasts …

Audited 2026-09-19: spot-checked the AHCCD
(`ahccd-stations`/`-annual`/`-monthly`/`-seasonal`/`-trends`) and
`climate-normals` collections specifically, since neither had been queried
live beyond a one-off check at build time. No functional bug (the generic
client handles both correctly), but found the module's own gotchas doc had
overgeneralized its bilingual-field-naming claim — confirmed live that
bilingual fields use at least three different conventions depending on the
collection, not one: `_en`/`_fr` suffixes (`weather-alerts`), `E_`/`F_`
prefixes (`climate-normals`), and a single double-underscore-joined field
per concept (every `ahccd-*` collection, e.g.

`station_name__nom_station` — not two separate fields at all). Also found
and documented a real missing-value trap: AHCCD uses `-9999.9` as a sentinel
for missing pressure/temperature readings, inconsistently alongside a
genuine `null` for the same "no data" case within the same field — confirmed
live in `ahccd-annual`. The generic pass-through client does not (and should
not) auto-correct this, since it has no per-field semantic knowledge, but
`docs://eccc/gotchas` now warns explicitly rather than leaving it to be
discovered the hard way. |
