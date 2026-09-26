"""Immigration, Refugees and Citizenship Canada (IRCC).

Two sub-sources:

- Express Entry rounds of invitations (this folder's client.py/tools.py):
  a static JSON feed on canada.ca that powers the rounds-invitations page,
  confirmed live 2026-09-18. It is not a CKAN dataset.
- Monthly IRCC Updates (monthly/): the 96 tab-separated ODP-*.csv tables
  behind the 12 "Monthly IRCC Updates" datasets on open.canada.ca
  (organization "cic"), checked live 2026-09-25. CKAN only lists them and
  none is DataStore-active, so the tables are read and summed here.

Other IRCC datasets (citizenship, ad hoc specialized datasets) stay
reachable through ckan_search_datasets(portal="federal",
fq="organization:cic").
"""

MODULE_NAME = "ircc"
MODULE_DESCRIPTION = (
    "Immigration, Refugees and Citizenship Canada (IRCC). ircc_: Express "
    "Entry rounds of invitations (draw history, CRS cutoffs, invitations, "
    "pool distribution). ircc_monthly_: the Monthly IRCC Updates tables, "
    "January 2015 to the latest month: permanent residents by province, "
    "CMA, census subdivision, citizenship, category, occupation, age and "
    "gender; study and work permit holders; temporary-to-permanent "
    "transitions; Express Entry admissions and invitations; asylum "
    "claimants. Counts are rounded to 5 and 1-4 suppressed. Other IRCC "
    "datasets are reachable through the federal ckan_ tools filtered to "
    "organization:cic."
)
MODULE_DESCRIPTION_FR = (
    "Immigration, Réfugiés et Citoyenneté Canada (IRCC). ircc_ : rondes "
    "d'invitations Entrée express (historique, seuils du SCG, invitations, "
    "répartition du bassin). ircc_monthly_ : les tableaux des mises à jour "
    "mensuelles d'IRCC, de janvier 2015 au dernier mois : résidents "
    "permanents par province, RMR, subdivision de recensement, "
    "citoyenneté, catégorie, profession, âge et genre; titulaires de "
    "permis d'études et de travail; passages de résident temporaire à "
    "permanent; admissions et invitations Entrée express; demandeurs "
    "d'asile. Les nombres sont arrondis à 5 et ceux de 1 à 4 supprimés. "
    "Les autres jeux de données d'IRCC sont accessibles via les outils "
    "fédéraux ckan_ filtrés sur organization:cic."
)
