"""Fisheries and Oceans Canada commercial fisheries landings (open.canada.ca).

Two DFO datasets on open.canada.ca, both under the Open Government Licence -
Canada (license_id ca-ogl-lgo, package_show read 2026-11-08), with their files
served by DFO's data hub (api-proxy.edh-cde.dfo-mpo.gc.ca), keyless:

- "Commercial Fisheries - Seafisheries Landings - Canada" (6e16f703-...):
  one long CSV per language, 1990-2024, by year, province (Atlantic total,
  NL, PE, NS, NB, QC, BC and Canada), species group and species, with
  quantity in kg (live weight) and value in dollars; "x" is suppressed.
- "Commercial Fisheries - Freshwater Landings - Canada" (e426b11c-...):
  one wide CSV per year and language, 1990-2019, species by province or
  territory, quantity in tonnes and value in thousands of dollars.

The same tables are on dfo-mpo.gc.ca/stats as HTML under the narrower
Canada.ca terms (non-commercial reproduction only). The open.canada.ca copy is
used instead because its licence allows commercial use with attribution. On
2026-11-08 the dfo-mpo.gc.ca stats pages were also redirecting to a
maintenance page while the data hub files answered normally.
"""

MODULE_NAME = "dfo_landings"
MODULE_DESCRIPTION = (
    "Fisheries and Oceans Canada commercial fisheries landings (Open Government Licence - "
    "Canada): sea fisheries 1990-2024 by year, province, species group and species, and "
    "freshwater fisheries 1990-2019 by province or territory and species, as tidy rows with "
    "quantity in tonnes (live weight) and value in dollars, in English or French."
)
MODULE_DESCRIPTION_FR = (
    "Débarquements des pêches commerciales de Pêches et Océans Canada (Licence du "
    "gouvernement ouvert - Canada) : pêches maritimes de 1990 à 2024 par année, province, "
    "groupe d'espèces et espèce, et pêches en eau douce de 1990 à 2019 par province ou "
    "territoire et espèce, en lignes ordonnées avec la quantité en tonnes (poids vif) et la "
    "valeur en dollars, en français ou en anglais."
)
