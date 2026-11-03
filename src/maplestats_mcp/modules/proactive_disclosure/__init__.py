"""Federal proactive disclosure: contracts, grants and contributions, travel, hospitality.

Four government-wide DataStore tables on open.canada.ca, each a
"Proactive Publication" dataset that every federal organization reports
into (the per-department CSVs on the portal are slices of these). Read
live 2026-11-03; see constants.py for what was confirmed.
"""

MODULE_NAME = "proactive_disclosure"
MODULE_DESCRIPTION = (
    "Federal proactive disclosure (Treasury Board's government-wide Proactive "
    "Publication tables on open.canada.ca, tools prefixed disclosure_): contracts "
    "over $10,000 (1.3 million rows), grants and contributions (1.4 million), "
    "and travel and hospitality expenses of ministers, their staff and senior officials. "
    "Search by vendor, recipient or person, title, department, program, province, "
    "riding, fiscal year, date range and value range, with paging; summarize totals "
    "(count and sum of value) by department, vendor or recipient, program, fiscal year "
    "and more, computed by MapleStats from the rows because the portal has no SQL or "
    "aggregate API. Amendment rows are collapsed to each agreement's latest by default, "
    "since every amendment restates the agreement's whole value. Every row carries its "
    "dataset and resource ids and the open.canada.ca page to cite (Open Government "
    "Licence - Canada)."
)
MODULE_DESCRIPTION_FR = (
    "Divulgation proactive fédérale (tableaux pangouvernementaux de publication proactive "
    "du Conseil du Trésor sur ouvert.canada.ca, outils préfixés disclosure_) : contrats de "
    "plus de 10 000 $ (1,3 million de lignes depuis 2004), subventions et contributions "
    "(1,4 million), et dépenses de voyage et d'accueil des ministres, de leur personnel et "
    "des cadres supérieurs. Recherche par fournisseur, bénéficiaire ou personne, titre, "
    "ministère, programme, province, circonscription, exercice, plage de dates et de "
    "valeurs, avec pagination ; sommaires (nombre et somme des valeurs) par ministère, "
    "fournisseur ou bénéficiaire, programme, exercice et plus, calculés par MapleStats à "
    "partir des lignes, faute d'API SQL ou d'agrégation sur le portail. Les lignes de "
    "modification sont ramenées par défaut à la plus récente de chaque entente, chaque "
    "modification reprenant la valeur totale. Chaque ligne indique ses identifiants de jeu "
    "de données et de ressource et la page d'ouvert.canada.ca à citer (Licence du "
    "gouvernement ouvert - Canada)."
)
