# RentSafeTO building scores by neighbourhood

**Question.** Do Toronto neighbourhoods where more households rent have
lower-scoring apartment buildings?

Every input is a City of Toronto table on open.toronto.ca, read through the
portal's CKAN DataStore API, the same way MapleStats MCP reads it. The
script is `rentsafe_by_neighbourhood.py` in this folder.

| Input | open.toronto.ca dataset | DataStore resource |
|---|---|---|
| Building scores | [Apartment Building Evaluations](https://open.toronto.ca/dataset/apartment-building-evaluation/), "2023 - current" | `244f7a02-da5c-425b-b55f-fbdd133dd732` |
| Boundaries | [Neighbourhoods](https://open.toronto.ca/dataset/neighbourhoods/), "historical 140" | `7d3ae06b-0217-4cc9-92ed-97adafca2f7b` |
| Renter share | [Neighbourhood Profiles](https://open.toronto.ca/dataset/neighbourhood-profiles/), 2016, 140-neighbourhood model | `7f8eee5e-85fb-415c-aef3-c3bd4998445f` |

All three are under the Open Government Licence – Toronto. Contains
information licensed under the Open Government Licence – Toronto.

## Through MapleStats

In a chat client connected to MapleStats, the same tables come back as tidy
rows:

1. `toronto_summarize_apartment_scores` (`group_by="ward"`) gives the ward
   picture; `toronto_get_apartment_evaluations` lists the buildings, worst
   score first, with coordinates.
2. `toronto_get_neighbourhood_profile` with `neighbourhood="Annex"` and
   `characteristic="Renter"` gives one neighbourhood's renter households
   (9,870 of 15,930 in 2016) beside the city's (525,835).
3. `ckan_datastore_search` with `portal="toronto"` reads the boundary table,
   which no curated tool covers.

`reproduce_code` turns any of these calls into an R, Python, Stata, Julia or
Power Query script that fetches the same request. For the curated tools it
replays the first page the tool requested and says so; this script adds the
paging loop, the point-in-polygon step and the join.

## Method

1. Read every RentSafeTO evaluation since 2023 (7,151 rows on 2026-11-08) and
   keep each building's latest one (3,608 buildings). Scores are text in the
   table; one is "81.1", so they are read as decimals.
2. Place each building in one of the 140 neighbourhoods by its coordinates.
   The 149 buildings with no coordinates in the table are left out; every
   building with coordinates fell inside a boundary.
3. Take each neighbourhood's renter households over all private households
   from the 2016 profile (the 25% sample tenure rows).
4. Per neighbourhood: buildings, units, mean, median and lowest score. Rank
   correlation (Spearman) between renter share and mean score, over the 122
   neighbourhoods with five or more evaluated buildings.

## Result (run on 2026-11-08)

The rank correlation is −0.16: neighbourhoods with more renters score a
little lower on average, and the relation is weak. The lowest mean scores
were University (83.7, 6 buildings), Rouge (84.0, 19), Junction Area
(85.0, 7), Dovercourt-Wallace Emerson-Junction (85.2, 17) and Rustic
(85.6, 15). Rouge has the second-lowest mean and one of the lowest renter
shares (16%), which is part of why the correlation is weak. The highest
were Markland Wood (95.7), Bedford Park-Nortown (95.7), Humber
Heights-Westmount (95.6), St. Andrew-Windfields (95.4) and
Willowridge-Martingrove-Richview (95.3). The full table is
`output/rentsafe_by_neighbourhood.csv`.

## What this does not show

- The tenure figures are from the 2016 census and the scores from 2023 to
  2026. The 2021 profiles use the City's 158-neighbourhood model and are
  published only as an Excel file, which MapleStats does not download from
  Toronto's portal (its robots.txt disallows automated file downloads).
- RentSafeTO covers buildings with three or more storeys or ten or more
  units. A neighbourhood's renters in houses, basements and small buildings
  are in the census share but not in the scores.
- A mean of building scores weights a 20-unit building like a 500-unit one.
- A correlation across neighbourhoods says nothing about any one building or
  landlord.

## Run it

```bash
uv run docs/examples/toronto/rentsafe_by_neighbourhood.py
```

The script declares its own dependencies (httpx, polars, shapely), caches
each API page under `data/raw/` (ignored by git) and writes the table to
`output/`. Delete `data/raw/` to fetch fresh data; the figures above will
move as the City adds evaluations.
