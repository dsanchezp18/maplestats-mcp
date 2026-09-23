"""EPCOR Edmonton drinking-water and wastewater quality (epcor.com).

EPCOR runs Edmonton's two water treatment plants (E.L. Smith and
Rossdale) and publishes no API; both tools here read public HTML pages.

Confirmed live 2026-09-22:

1. The "Daily Water Quality" page embeds one iframe per plant from
   `apps.epcor.ca/DailyWaterQuality/Default.aspx?zone=ELS|Rossdale`, an
   ASP.NET page whose values sit in `<span id="<Measure>Label<N>">`
   elements for the last 7 days (N = 1..7): hardness, pH, temperature,
   total chlorine residual, alkalinity, conductivity, and caustic soda
   dose. Dates are labels like "SEP-15" with no year, so the year is
   inferred from today in Edmonton (a December label read in January
   belongs to last year). Missing readings show as "--". EPCOR marks
   these values as unvalidated monitoring data.
2. The "Water Quality Reports" page links ~250 PDFs (monthly summaries,
   bacteriological summaries, detailed monthly reports, annual
   reports, for both water and wastewater, 2019 onward). File names
   switch from underscores to hyphens mid-2025 and include at least
   one typo (`2025-03_..._monthly-report..pdf`), so URLs cannot be
   built from a pattern; `list_water_quality_reports` parses the live
   index instead and normalizes each name.
"""

MODULE_NAME = "epcor"
MODULE_DESCRIPTION = (
    "EPCOR Edmonton water quality: daily treated-water readings for the E.L. "
    "Smith and Rossdale plants (hardness, pH, temperature, chlorine, "
    "alkalinity, conductivity, caustic soda, last 7 days) and an index of "
    "monthly/annual drinking-water and wastewater quality report PDFs."
)
MODULE_DESCRIPTION_FR = (
    "Qualité de l'eau d'EPCOR à Edmonton : mesures quotidiennes de l'eau "
    "traitée aux usines E.L. Smith et Rossdale (dureté, pH, température, "
    "chlore, alcalinité, conductivité, soude caustique, 7 derniers jours) "
    "et index des rapports PDF mensuels et annuels sur l'eau potable et les "
    "eaux usées."
)
