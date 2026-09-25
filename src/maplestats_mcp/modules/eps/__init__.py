"""Edmonton Police Service (EPS) Community Safety Data Portal occurrences.

The EPS portal (communitysafetydataportal.edmontonpolice.ca) and its
Community Safety Map (an ArcGIS Experience app) read from public,
anonymous ArcGIS Online feature services owned by EPS's own org --
confirmed live 2026-09-22 by resolving the map's item ids through
`www.arcgis.com/sharing/rest/content/items/<id>`. None of this is in
data.edmonton.ca's Socrata catalogue (a "crime" search there returns
only 2015-era perception surveys), so `socrata_*` cannot reach it.

Facts confirmed live 2026-09-22, not taken from the portal's prose:

1. `EPS_OCC_30DAY` is misnamed: it holds a rolling ~12 months (min
   Reported_Date 2025-09-21, max 2026-09-19, 79,018 rows), not 30 days.
2. `Historic_Occurrences_CSDP_2_view` holds calendar 2023 only (81,344
   rows). Nothing public covers 2024 through mid-September 2025, so
   the two datasets are exposed separately rather than stitched into a
   continuous series that would silently hide that gap.
3. `Reported_Date` is stored as 12:00 UTC, i.e. local midnight in
   Edmonton -- a calendar date, not an incident time. There is no
   time-of-day, neighbourhood, or address field: location is only
   the nearest intersection, which EPS uses to anonymize incidents.
4. Upstream category labels are not fully clean: "Drug Violation" and
   "Drug Violations" both occur, and one Traffic group label is
   truncated ("Criminal Flights/Impaired Operation/Escape Lawful ").
   Filters match exactly, so use `eps_summarize_occurrences` to see
   the real labels before filtering on them.
5. `FME_Load_Date` (one row, `Last_Load_Date` as a DD/MM/YYYY string)
   is EPS's own record of the last refresh.
"""

MODULE_NAME = "eps"
MODULE_DESCRIPTION = (
    "Edmonton Police Service Community Safety Data Portal: reported "
    "occurrences (violent, property, disorder, drugs, weapons, traffic) "
    "by date, category, and nearest intersection -- a rolling ~12 months "
    "plus calendar 2023 -- with filtered listings, grouped counts, and "
    "the portal's last refresh date."
)
MODULE_DESCRIPTION_FR = (
    "Portail de données sur la sécurité communautaire du Service de police "
    "d'Edmonton : incidents signalés (violence, biens, désordre, drogues, "
    "armes, circulation) par date, catégorie et intersection la plus "
    "proche -- environ 12 mois glissants plus l'année 2023 -- avec listes "
    "filtrées, dénombrements groupés et date de dernière mise à jour."
)
