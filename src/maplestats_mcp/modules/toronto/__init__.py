"""City of Toronto open data: curated tools over open.toronto.ca DataStore tables.

`ckan_*` with `portal="toronto"` already searches the whole catalogue and
reads any DataStore table by resource id. This module adds a few tools for
the Toronto datasets people ask for most, returning tidy rows (renamed
columns, numbers parsed, one row per neighbourhood indicator or building)
with the dataset's citation and the Open Government Licence - Toronto.
Every request goes through `ckan.client.datastore_search`, so the portal's
rate limit and cache are shared with `ckan_*`.

Only DataStore tables are read. The CKAN host's robots.txt (read
2026-11-08) disallows `/dataset/*/resource/*/download/*`, the path of every
file on the portal, and allows `/api/`; the 2021 Neighbourhood Profiles
(XLSX), 311 service requests (yearly ZIPs) and TTC GTFS (ZIP) are files
only, so they are not read here (docs/ROADMAP.md).

Confirmed live 2026-11-08 against ckan0.cf.opendata.inter.prod-toronto.ca:

1. Neighbourhood Profiles (140-neighbourhood model) are wide tables: one
   row per indicator, one column per neighbourhood plus "City of Toronto".
   2016 has 2,383 rows and names the label column "Characteristic" (with a
   "Data Source" column); 2011, 2006 and 2001 call it "Attribute" and have
   no source column. Values are text with thousands separators in 2016
   ("525,835") and numbers in the older tables. Leading spaces in a label
   mark its level in the census hierarchy ("  Renter").
2. RentSafeTO "Apartment Building Evaluations 2023 - current" holds one row
   per evaluation (7,151 rows, 3,608 buildings by RSN), every value text
   except YEAR BUILT, YEAR EVALUATED and NO OF AREAS EVALUATED. One YEAR
   EVALUATED is 202510, so the year is taken from EVALUATION COMPLETED ON;
   one score is "81.1", so scores parse as floats. Wards are "01".."25".
3. Short-term rental registrations (8,620 rows) give the operator's
   registration number and street address per listing; this module only
   counts them (by ward, property type or FSA).
4. DineSafe's DataStore table, which answered HTTP 500/502 on 2026-10-27,
   answers again (126,282 inspection rows). `q` accepts a JSON object for a
   per-column full-text search ({"estName": "pizza"}), and the address
   carries the literal word "None" where the unit is empty.
"""

MODULE_NAME = "toronto"
MODULE_DESCRIPTION = (
    "City of Toronto open data (open.toronto.ca), curated tools over the portal's DataStore "
    "tables with tidy rows, the dataset citation and the Open Government Licence - Toronto: "
    "Neighbourhood Profiles for one of the 140 neighbourhoods (census 2016, 2011, 2006, 2001; "
    "2,000+ indicators), RentSafeTO apartment building evaluation scores by building, ward or "
    "property type, short-term rental registrations counted by ward, property type or FSA, and "
    "DineSafe restaurant inspections. English only. Use ckan_ with portal='toronto' for the "
    "rest of the catalogue; files (2021 profiles, 311 requests, TTC GTFS) are not read."
)
MODULE_DESCRIPTION_FR = (
    "Données ouvertes de la Ville de Toronto (open.toronto.ca), outils ciblés sur les tableaux "
    "DataStore du portail, en lignes ordonnées avec la citation du jeu de données et la "
    "Licence du gouvernement ouvert – Toronto : profils des 140 quartiers (recensements de "
    "2016, 2011, 2006 et 2001 ; plus de 2 000 indicateurs), notes d'évaluation des immeubles "
    "d'appartements RentSafeTO par immeuble, quartier électoral ou type de propriété, "
    "inscriptions de locations à court terme comptées par quartier électoral, type de "
    "propriété ou RTA, et inspections DineSafe des restaurants. Contenu en anglais seulement. "
    "Voir ckan_ avec portal='toronto' pour le reste du catalogue ; les fichiers (profils "
    "2021, demandes 311, GTFS de la TTC) ne sont pas lus."
)
