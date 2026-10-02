"""Alberta Wildfire live status (Alberta Wildfire, Government of Alberta).

Alberta Wildfire's public "Alberta Wildfire Status" map and dashboard read
from anonymous ArcGIS Online feature services owned by the ArcGIS account
`WMBappServices` (org id Eb8P5h4CJk8utIBz, services.arcgis.com). No key is
needed. The provincial counterpart of `cwfis` (which holds the national
satellite hotspots, FWI stations and situation reports) and of `bcgw` (BC).

Facts confirmed live 2026-10-02, not taken from the map's prose:

1. Licence. The open.alberta.ca dataset `alberta-wildfire-status-map` (CKAN
   licence id OGLA) is under the Open Government Licence - Alberta: a
   "worldwide, royalty-free, perpetual, non-exclusive licence to use the
   Information, including for commercial purposes"; the required attribution
   is "Contains information licensed under the Open Government Licence -
   Alberta." The ArcGIS items themselves carry only a no-warranty disclaimer.
   `services.arcgis.com/robots.txt` answers HTTP 403 (it is an API host, no
   robots file); `www.arcgis.com/robots.txt` allows everything.
2. `Wildfire_year_to_date` holds every fire point of the current year plus
   carry-over fires from earlier years (823 rows on 2026-10-02: 769 wildfires
   and 54 mutual-aid fires). It is the union of the separate "active" and
   "non active" point layers the map draws, so one query covers both. Off
   season the active set is empty; that is normal.
3. `wildfire_prev5_ytd` holds the fire points of the last six fire years,
   each cut at today's calendar date (6,821 rows for 2021-2026), so it is a
   same-date comparison set, not a full history. In it the status
   "Assistance Ended" is misspelled "Assisstance Ended" for 211 rows; the
   client folds the two spellings together.
4. Fire status date is a string "YYYY/MM/DD HH:MM:SS" with no time zone;
   the assessment date is a true date (UTC milliseconds). Size classes follow
   the Canadian standard (A to 0.1 ha, B to 4, C to 40, D to 200, E above
   200), confirmed against the area ranges in the data. The cause is null
   for mutual-aid fires.
5. The fire danger layer is 807 polygons covering the whole province, not
   only the Forest Protection Area (Edmonton and Calgary are rated). A
   point outside Alberta intersects nothing.
6. The dashboard statistics (`Wildfire_Statistics_Prod_View`, five values)
   count wildfires of the current year only: 753 and 17,771.48 ha equal the
   layer's wildfires with FIRE_YEAR 2026 exactly. Its "active" count can be
   1 while the active-fire layer is empty (a "Turned Over" fire).
7. Perimeters: the public map points at `Extinguished_Wildfire_Perimeter`
   (2 polygons, stale since early 2026); the `(PROD)` services hold 118
   extinguished and 0 active polygons, refreshed 2026-09-24, so those are
   used. Polygons exist only for some fires (none for "Turned Over").
8. Fire bans, restrictions and advisories (`alberta_fire_ban_system`) are
   polygons per municipality or park with a start date but no end date;
   entries from 2023 and 2025 were still listed. One jurisdiction can appear
   as several polygons.
"""

MODULE_NAME = "ab_wildfire"
MODULE_DESCRIPTION = (
    "Alberta Wildfire live status (Government of Alberta, open licence): "
    "current-season fire locations with status, cause, size class and forest "
    "area (active and extinguished, plus same-date comparison with the previous "
    "five years), mapped fire perimeters, fire danger rating by point or area, "
    "fire bans, restrictions and advisories, and the season statistics against "
    "5, 10 and 25-year averages. Active layers are empty off-season."
)
MODULE_DESCRIPTION_FR = (
    "État des feux de forêt en Alberta (gouvernement de l'Alberta, licence "
    "ouverte) : localisation des feux de la saison avec statut, cause, classe "
    "de superficie et zone forestière (actifs et éteints, plus comparaison à "
    "la même date des cinq années précédentes), périmètres cartographiés, "
    "danger d'incendie à un point ou sur une zone, interdictions, restrictions "
    "et avis de feu, et statistiques de la saison par rapport aux moyennes sur "
    "5, 10 et 25 ans. Les couches de feux actifs sont vides hors saison."
)
