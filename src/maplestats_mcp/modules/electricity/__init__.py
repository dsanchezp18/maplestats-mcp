"""Canadian electricity demand, supply and prices (Ontario / IESO).

Provider: the Independent Electricity System Operator's public reports
(reports-public.ieso.ca/public), keyless CSV and XML files. Terms
(ieso.ca/en/Terms-of-Use, read 2026-09-29): a limited licence to use and
reproduce content provided every reproduction carries the IESO copyright
notice, which each response's provenance limits repeats.

Other provinces were checked live on 2026-09-29 and left out:

- Alberta (AESO): the pool-price and market API needs a subscription key
  (HTTP 401, AzureApiManagementKey); the keyless ets.aeso.ca Current Supply
  Demand page is HTML, and the AESO terms allow copying "for non-commercial,
  personal or educational purposes" only.
- Quebec (Hydro-Quebec): open data is keyless (demand.json, Opendatasoft
  datasets) but licensed CC BY-NC 4.0, non-commercial only.
- British Columbia (BC Hydro): the load-data pages answer HTTP 403 to
  automated clients.
- New Brunswick (NB Power): system-information page and monthly CSV archive
  are keyless, but the terms give no permission to copy, redistribute or
  republish content without written permission.
- Saskatchewan (SaskPower) and Nova Scotia (Nova Scotia Power): no
  machine-readable demand feed found.

CER's open data covers pipelines, energy exports and scenario projections, not
system demand, so this module does not duplicate it.
"""

MODULE_NAME = "electricity"
MODULE_DESCRIPTION = (
    "Ontario electricity system data from the IESO public reports: hourly "
    "Ontario and market demand (2002 onward), 5-minute real-time demand, hourly "
    "generation by fuel (2015 onward), Ontario Zonal Prices (day-ahead hourly, "
    "real-time 5-minute; successor to HOEP since 2025-05-01) and HOEP monthly "
    "averages to 2025, the daily adequacy outlook and intertie schedules and "
    "flows. Other provinces are not covered (keyed or restricted sources)."
)
MODULE_DESCRIPTION_FR = (
    "Données du réseau d'électricité de l'Ontario (rapports publics de la SIERE) : "
    "demande horaire de l'Ontario et du marché (depuis 2002), demande en temps "
    "réel aux 5 minutes, production horaire par combustible (depuis 2015), prix "
    "zonal de l'Ontario (prévisionnel horaire, temps réel; remplace le PHEO depuis "
    "le 2025-05-01), moyennes mensuelles du PHEO jusqu'en 2025, perspective "
    "quotidienne de suffisance et échanges aux interconnexions. Les autres "
    "provinces ne sont pas couvertes."
)
