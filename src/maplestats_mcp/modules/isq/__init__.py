"""Institut de la statistique du Québec (ISQ): detailed statistical tables.

ISQ's statistics are on statistique.quebec.ca, not on Données Québec (which
holds only 7 ISQ geography datasets). The site lists its 7,078 detailed
tables (French and English pages) in sitemap.xml. Checked live 2026-09-26:

- "Dynamic" tables are served by the database engine that powered the BDSO
  data bank (closed 2025-12-18; ISQ's tables moved to its own site). Their
  page script reads the title, column configuration, notes and data from
  /pls/ken/ken411_data_explt_v2.* by table number. robots.txt disallows
  /pls/ken/; the project owner decided on 2026-09-26 to read it anyway, on
  demand, one table per user request, rate-limited and never crawled.
- "Static" tables embed their table as HTML in the page's __NEXT_DATA__,
  with an Excel copy under /fr|en/fichier/.
"""

MODULE_NAME = "isq"
MODULE_DESCRIPTION = (
    "Institut de la statistique du Québec (statistique.quebec.ca, tools prefixed "
    "isq_): search about 7,000 detailed tables and read one. Most are ISQ's own "
    "data found nowhere else: Québec health surveys (youth, care experience), the "
    "culture and communications observatory (cinema, performing arts, books, "
    "music), arts council statistics, investment and R&D surveys, income and "
    "population by MRC and municipality, plus ISQ tabulations of StatCan data "
    "for Québec. Labels are mostly French; values keep ISQ's flags (r revised, "
    "p provisional, x confidential, F unreliable)."
)
MODULE_DESCRIPTION_FR = (
    "Institut de la statistique du Québec (statistique.quebec.ca, outils préfixés "
    "isq_) : recherche parmi environ 7 000 tableaux détaillés et lecture d'un "
    "tableau. La plupart sont des données propres à l'ISQ : enquêtes de santé "
    "québécoises (jeunes du secondaire, expérience de soins), Observatoire de la "
    "culture et des communications (cinéma, arts de la scène, livre, musique), "
    "statistiques du CALQ, enquêtes sur l'investissement et la R-D, revenu et "
    "population par MRC et municipalité, et compilations de données de "
    "Statistique Canada pour le Québec. Les signes conventionnels de l'ISQ (r, "
    "p, x, F) accompagnent les valeurs."
)
