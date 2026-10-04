# Elected officials and districts (Open North Represent)

**Status:** Shipped 2026-10-02 as `modules/represent/` (5 tools, prefix `represent_`).

Source: `https://represent.opennorth.ca`, the Represent Civic Information API run
by Open North, a nonprofit. It is not a government site. It complements the
`ourcommons_` tools (official House of Commons feeds) by adding provincial and
municipal officials and a postal code or point lookup.

## Terms checked live (2026-10-02)

- `/api/` documents every endpoint and states "Represent is free up to 60
  requests per minute (86,400 queries/day)"; above that the server may answer
  HTTP 503. The shared limiter paces calls to 1 a second.
- `/privacy/` covers server logs only.
  `/terms/` and `/about/` are 404. No general terms of use exist, and nothing
  forbids automated use; the API page invites bulk download ("send a request to
  `/representatives/?limit=1000` and follow the next link").
- Licences are per boundary set (`licence_url` on the set detail): federal
  districts use the Open Government Licence - Canada, Alberta's districts the
  Alberta open licence. Representative records are scraped from official sites
  (`data_url` points at the scraper feed) and carry no licence field, so their
  licence is unverified. Every response states this in `provenance.limits`.

## Endpoints used and what was confirmed

| Tool | Endpoints | Notes |
|---|---|---|
| `represent_lookup_postcode` | `/postcodes/{CODE}/`, then `/boundary-sets/{slug}/` per distinct set | Code uppercased, spaces removed. `include_set_details` skips the per-set calls. |
| `represent_lookup_point` | `/boundaries/?contains=lat,lon`, `/representatives/?point=lat,lon` | Exact; a point is in one district per set. |
| `represent_search_representatives` | `/representatives/[set/]?name__icontains=...` | Filters `name`, `elected_office`, `district_name`, `party_name` (substring, case-insensitive). |
| `represent_list_boundary_sets` | `/boundary-sets/`, then each set's detail | 524 sets at 2026-10-02. |
| `represent_list_representative_sets` | `/representative-sets/?limit=1000` | 121 sets: 1 federal, 12 provincial, 108 municipal. |

Not built: `/boundaries/{set}/{slug}/` shapes (GeoJSON/KML/WKT), `/elections/`
(empty at 2026-10-02) and `/candidates/` (597 Quebec candidates, a past
election).

## Quirks

- **Licence and date are on the detail endpoint only.** `/boundary-sets/` rows
  have `name`, `domain` and urls; `licence_url` and `last_updated` appear only
  on `/boundary-sets/{slug}/`. A postal code lookup therefore fetches up to
  about 14 set details (cached 24 hours), which is 1 to 9 seconds under the
  1 request a second pace. `list_boundary_sets` fetches details for at most 25
  sets per call.
- **Representative sets have no date.** `/representative-sets/{slug}/` holds
  `name`, `data_url` and relations only. Staleness is therefore reported for
  boundaries (`last_updated`, `age_years`, `possibly_stale` beyond 5 years) and
  never for people; each person's `source_url` is the page to confirm on.
- **Old boundary sets are returned.** Postal codes and points match the 2003 and
  2013 federal representation orders (last updated 2011-11-28 and 2017-08-23) as
  well as the 2023 one (2024-12-17); representatives point to the current set.
- **`representatives_concordance` is absent, not null,** on many postal codes,
  With `sets=`, only `representatives_centroid` comes back, and only for sets a
  representative set uses: K2J6B6 with the 2023 order returns its MP, with
  `federal-electoral-districts` (the unsuffixed slug, which is the 2013 order)
  no representative key at all (checked 2026-10-03). The tool adds a note in
  that case.
- **A postal code can miss a level.** H3B4W8 (Montreal) returned a mayor and an
  MNA but no MP, while the point 45.524, -73.596 returned the MP. The tool adds
  a note when federal or provincial is absent.
- **Errors:** an unknown postcode or boundary set is 404 with an HTML page; a
  bad `point` is 400 with plain text; an unknown representative set slug is 200
  with an empty list (so the tool checks the set exists first); a missing
  trailing slash is 301.
- `limit` above 1000 is clamped. `Accept-Language: fr` changes nothing in the
  JSON, so `lang` only picks the language of this server's own notes.
- Level is not a field. It is derived from the set slug: `house-of-commons`
  federal; slugs ending `-legislature` plus `quebec-assemblee-nationale`
  provincial; the rest municipal. Nunavut has no legislature set (Iqaluit
  returns only the MP).
- Empty strings stand for absent values (`party_name`, `email`, `gender` are
  `""`), read as `null`. Offices come as `{type, postal, tel, fax}` with keys
  missing when unknown.

## Live verification (2026-10-02)

Postal codes in all provinces and territories returned the expected levels:
T5J0N3 (Edmonton: mayor, MLA, MP), M5H2N2 (Toronto), H3B4W8 (Montreal, no MP),
V6B1A1 (Vancouver: 19 representatives including park commissioners), K1A0A6,
R3C0V8, S4P3Y2, B3J1S9, E3B5H1, A1C5M3, C1A7N8, Y1A2C6, X1A2P2, X0A0H0 (MP
only), G1R4P5, T2P2M5, V8W1P6, K0A1K0, T9H2Z9, J4B1A1. Points in Edmonton,
Toronto, Montreal, Vancouver, Yellowknife, the Yukon and PEI returned
districts and officials; (0, 0) returned none. Search by name ("Carney" gives
one MP), office ("Mayor" 336), party, level and set all worked, and
`census-divisions`, `census-subdivisions` and the federal electoral districts
sets showed `licence_url` and `last_updated` (2016-11-08 and 2017-08-23, both
flagged possibly stale).
