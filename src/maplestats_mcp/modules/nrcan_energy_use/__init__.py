"""NRCan Office of Energy Efficiency energy-use data (National Energy Use Database).

oee.nrcan.gc.ca publishes the Comprehensive Energy Use Database (energy
use and GHG emissions by sector and province since 2000) and the tables
of NRCan's energy-use surveys: the Survey of Household Energy Use
(SHEU, also by CMA), commercial/institutional (SCIEU), multi-unit
residential (SECMURB), arenas (SECA), industrial consumption (ICE), and
household appliance shipments. Every table is served by one
`showTable.cfm` route in English and French. There is no JSON API;
tables are parsed from the published HTML, confirmed live 2026-09-23.
"""

MODULE_NAME = "nrcan_energy_use"
MODULE_DESCRIPTION = (
    "Natural Resources Canada energy-use data (Office of Energy "
    "Efficiency): the Comprehensive Energy Use Database (energy use and "
    "GHG emissions by sector and province, 2000 onward) and survey tables "
    "from the Survey of Household Energy Use (SHEU, SHEU-CMA), commercial "
    "and institutional buildings (SCIEU), multi-unit residential "
    "buildings, arenas, industrial consumption (ICE) and appliance "
    "shipments. List a product's tables, then read any table in English "
    "or French."
)
MODULE_DESCRIPTION_FR = (
    "Données sur la consommation d'énergie de Ressources naturelles "
    "Canada (Office de l'efficacité énergétique) : la Base de données "
    "complète sur la consommation d'énergie (consommation d'énergie et "
    "émissions de GES par secteur et province depuis 2000) et les "
    "tableaux des enquêtes sur la consommation d'énergie : ménages (EMCE, "
    "aussi par RMR), secteur commercial et institutionnel (EECI), "
    "immeubles résidentiels à logements multiples, arénas, industrie "
    "(CIE) et appareils ménagers. Liste des tableaux d'un produit, puis "
    "lecture de tout tableau en français ou en anglais."
)
