"""CanadaBuys, the Government of Canada's procurement portal (PSPC).

Confirmed live 2026-09-22: CanadaBuys publishes its tender and award
notices as plain bilingual CSV files under
`canadabuys.canada.ca/opendata/pub/`, listed as resources of the
open.canada.ca packages "CanadaBuys tender notices" and "CanadaBuys
award notices". There is no row-level API and the files are not
DataStore-active, so this module downloads the CSV and filters it
in-process: the open-tenders file (~6.5MB, ~900 rows, refreshed daily)
and one award-notice file per fiscal year (~14MB, ~4,000 rows for the
current year so far, also refreshed daily).
"""

MODULE_NAME = "canadabuys"
MODULE_DESCRIPTION = (
    "CanadaBuys federal procurement notices (PSPC open data CSVs): search "
    "currently open or newly posted tender notices, search award notices "
    "by supplier, buying organization, or keyword for any fiscal year "
    "since 2022-2023, and fetch the full detail of one notice by its "
    "reference number."
)
MODULE_DESCRIPTION_FR = (
    "Avis d'approvisionnement fédéraux d'AchatsCanada (fichiers CSV de "
    "données ouvertes de SPAC) : recherche d'appels d'offres ouverts ou "
    "nouvellement publiés, recherche d'avis d'attribution par fournisseur, "
    "organisation acheteuse ou mot-clé pour tout exercice depuis "
    "2022-2023, et détail complet d'un avis par numéro de référence."
)
