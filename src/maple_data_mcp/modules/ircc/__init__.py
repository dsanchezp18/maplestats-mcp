"""Immigration, Refugees and Citizenship Canada (IRCC) - Express Entry rounds.

Scope note: IRCC's administrative series datasets (permanent residents,
study/work permits, asylum claimants, citizenship) are ordinary CKAN
packages published by the "ircc" organization on open.canada.ca, already
reachable through the existing federal module with e.g.
ckan_search_datasets(query="permanent residents", fq="organization:ircc")
-- see modules/ckan_federal/. Building a second, duplicate CKAN client for
the same portal would not add capability.

What genuinely needed its own adaptor, confirmed live 2026-09-18, is the
Express Entry rounds-of-invitations history: it is not a CKAN dataset at
all, but a static JSON feed served from canada.ca's content-delivery path
(https://www.canada.ca/content/dam/ircc/documents/json/ee_rounds_123_en.json)
that powers the public rounds-invitations page. This module covers that
feed only.
"""

MODULE_NAME = "ircc"
MODULE_DESCRIPTION = (
    "Immigration, Refugees and Citizenship Canada (IRCC) Express Entry "
    "rounds of invitations: draw history, CRS score cutoffs, invitations "
    "issued, and candidate-pool CRS score distribution, from IRCC's "
    "canada.ca JSON feed (tools prefixed ircc_). Other IRCC administrative "
    "series (permanent residents, study/work permits, asylum, citizenship) "
    "are ordinary open.canada.ca CKAN datasets already reachable through "
    "the federal ckan_ tools filtered to organization:ircc."
)
MODULE_DESCRIPTION_FR = (
    "Immigration, Réfugiés et Citoyenneté Canada (IRCC), rondes "
    "d'invitations Entrée express : historique des rondes, seuils du SCG, "
    "invitations émises et répartition des scores SCG du bassin de "
    "candidats, à partir du flux JSON canada.ca d'IRCC (outils préfixés "
    "ircc_). Les autres séries administratives d'IRCC (résidents "
    "permanents, permis d'études et de travail, asile, citoyenneté) sont "
    "des jeux de données CKAN ordinaires d'open.canada.ca déjà "
    "accessibles via les outils fédéraux ckan_ filtrés sur "
    "organization:ircc."
)
