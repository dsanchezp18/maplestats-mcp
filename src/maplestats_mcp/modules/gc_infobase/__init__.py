"""GC InfoBase (Treasury Board of Canada Secretariat) open datasets.

GC InfoBase publishes its data as the "GC InfoBase - Open Datasets"
package on open.canada.ca: Main Estimates, Public Accounts (authorities
and expenditures by vote, standard object, transfer payments),
Departmental Plans and Results Reports (planned and actual spending and
FTEs by program, performance indicators), and the Inventory of Federal
Organizations. Confirmed live 2026-09-23. The web app's GraphQL API is
not used: introspection is disabled and its URL changes with each
deployment.
"""

MODULE_NAME = "gc_infobase"
MODULE_DESCRIPTION = (
    "GC InfoBase (Treasury Board Secretariat): federal spending and "
    "results open datasets. List the files (Main Estimates, Public "
    "Accounts authorities and expenditures by vote, standard object and "
    "transfer payment, planned and actual spending and FTEs by program, "
    "results indicators, federal organizations) and query rows by "
    "organization, fiscal year and column values, in English or French."
)
MODULE_DESCRIPTION_FR = (
    "InfoBase du GC (Secrétariat du Conseil du Trésor) : jeux de données "
    "ouverts sur les dépenses et les résultats fédéraux. Liste des "
    "fichiers (Budget principal des dépenses, Comptes publics : "
    "autorisations et dépenses par crédit, article courant et paiement de "
    "transfert, dépenses et ETP prévus et réels par programme, "
    "indicateurs de résultats, organisations fédérales) et interrogation "
    "des lignes par organisation, exercice et valeurs de colonne, en "
    "français ou en anglais."
)
