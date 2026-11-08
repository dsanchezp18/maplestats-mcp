"""Canadian electricity demand, supply and prices: Ontario (IESO), Quebec and Alberta.

Ontario (`electricity_ontario_*`): the Independent Electricity System
Operator's public reports (reports-public.ieso.ca/public), keyless CSV and XML
files. Terms (ieso.ca/en/Terms-of-Use, read 2026-09-29): a limited licence to
use and reproduce content provided every reproduction carries the IESO
copyright notice, which each response's provenance licence repeats.

Quebec (`electricity_quebec_*`): Hydro-Quebec open data
(donnees.hydroquebec.com, Opendatasoft Explore API v2.1), keyless: 15-minute
demand, generation by source, and hourly imports/exports, each with a recent
two-day window and, for demand and generation, an archive that stops in
2025-2026. Also (2026-10-03) hourly water flows (total, turbined, spilled)
and daily natural inflows at 94 generating stations and control structures,
from the JSON file hydroquebec.com publishes for the Donnees Quebec record
`donnees-hydrometriques` (see quebec_flows.py). Licence CC BY-NC 4.0 on every
dataset: credit Hydro-Quebec, non-commercial use only. Each response repeats
the attribution and the non-commercial notice in provenance licence, and
anyone redistributing the output commercially must not rely on this source.

Alberta (`electricity_alberta_*`, 2026-11-08): the AESO's public Energy
Trading System reports on ets.aeso.ca, keyless (hourly pool price and AIL,
daily averages, the Pool Monthly Summary pages, and the Current Supply Demand
page; see alberta_client.py). It was left out on 2026-09-29 because AESO's
API (api.aeso.ca) needs a subscription key (HTTP 401) and the AESO terms
(www.aeso.ca/legal/) allow copying "for non-commercial, personal or
educational purposes" only. It was added once MapleStats was confirmed as
non-commercial (free, MIT-licensed, self-funded), the same basis as
Hydro-Quebec's CC BY-NC data: the keyed API is still not used, values are
passed through unmodified, and every response repeats the AESO terms in
provenance licence (commercial_use "not_allowed") plus a commercial-use
notice. No robots.txt on ets.aeso.ca or www.aeso.ca (both HTTP 404), and the
terms say nothing against automated retrieval.

Other provinces were checked live on 2026-09-29 and left out:

- British Columbia (BC Hydro): the load-data pages answer HTTP 403 to
  automated clients.
- New Brunswick (NB Power): system-information page and monthly CSV archive
  are keyless, but the terms give no permission to copy, redistribute or
  republish content without written permission.
- Saskatchewan (SaskPower) and Nova Scotia (Nova Scotia Power): no
  machine-readable demand feed found.

CER's open data cover pipelines, energy exports and scenario projections, not
system demand, so this module does not duplicate it.
"""

MODULE_NAME = "electricity"
MODULE_DESCRIPTION = (
    "Ontario electricity system data from the IESO public reports: hourly "
    "Ontario and market demand (2002 onward), 5-minute real-time demand, hourly "
    "generation by fuel (2015 onward), Ontario Zonal Prices (day-ahead hourly, "
    "real-time 5-minute; successor to HOEP since 2025-05-01) and HOEP monthly "
    "averages to 2025, the daily adequacy outlook and intertie schedules and "
    "flows; plus Quebec (Hydro-Quebec, CC BY-NC 4.0, non-commercial): 15-minute "
    "demand, generation by source, imports and exports, and hourly water flows and daily "
    "natural inflows at 94 Hydro-Quebec dams and generating stations; plus Alberta (AESO, "
    "non-commercial use only): hourly pool price and Alberta Internal Load (1999 onward), daily "
    "and monthly pool price averages, and the current supply and demand by fuel type, "
    "interchange and asset. Other provinces are not covered."
)
MODULE_DESCRIPTION_FR = (
    "Données du réseau d'électricité de l'Ontario (rapports publics de la SIERE) : "
    "demande horaire de l'Ontario et du marché (depuis 2002), demande en temps "
    "réel aux 5 minutes, production horaire par combustible (depuis 2015), prix "
    "zonal de l'Ontario (prévisionnel horaire, temps réel; remplace le PHEO depuis "
    "le 2025-05-01), moyennes mensuelles du PHEO jusqu'en 2025, perspective "
    "quotidienne de suffisance et échanges aux interconnexions. Ainsi que le "
    "Québec (Hydro-Québec, CC BY-NC 4.0, usage non commercial) : demande aux 15 minutes, "
    "production par source, importations et exportations, et débits horaires et apports "
    "naturels quotidiens à 94 centrales et barrages d'Hydro-Québec. Ainsi que l'Alberta (AESO, "
    "usage non commercial seulement) : prix horaire du pool et charge interne de l'Alberta "
    "(depuis 1999), moyennes quotidiennes et mensuelles du prix du pool, et offre et demande "
    "actuelles par combustible, échanges et centrale. Les autres provinces ne sont pas couvertes."
)
