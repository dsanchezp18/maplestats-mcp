"""Job Bank wages (Employment and Social Development Canada).

The yearly "Wages" dataset on open.canada.ca (package
adad580f-76b0-4502-bd05-20c125de9116): low, median and high wages for the
516 occupations of NOC 2021, for Canada, each province and territory and
each economic region. One DataStore resource per yearly release; the
current one is found from the package at run time (package_show), so a new
release needs no code change. Checked live 2026-11-03.
"""

MODULE_NAME = "jobbank"
MODULE_DESCRIPTION = (
    "Job Bank wages from Employment and Social Development Canada (ESDC). "
    "jobbank_: low (about the 10th percentile), median and high (about the "
    "90th percentile) hourly or annual wages for the 516 NOC 2021 "
    "occupations, for 86 geographies: Canada, nine provinces and 76 "
    "economic regions (Prince Edward Island and each territory are one "
    "economic region), from the yearly Job Bank release on open.canada.ca. Search "
    "occupations by NOC code or title (English or French), get one "
    "occupation's wages by region, compare occupations in one region, list "
    "economic regions. Estimates mostly from the Labour Force Survey with "
    "other sources; many regional cells are not published."
)
MODULE_DESCRIPTION_FR = (
    "Salaires du Guichet-Emplois d'Emploi et Développement social Canada "
    "(EDSC). jobbank_ : salaires horaires ou annuels bas (environ le 10e "
    "centile), médians et élevés (environ le 90e centile) des 516 "
    "professions de la CNP 2021, pour 86 géographies : le Canada, neuf "
    "provinces et 76 régions économiques (l'Île-du-Prince-Édouard et chaque "
    "territoire forment une seule région économique), tirés de la diffusion annuelle "
    "du Guichet-Emplois sur ouvert.canada.ca. Recherche de professions par "
    "code CNP ou titre (français ou anglais), salaires d'une profession par "
    "région, comparaison de professions dans une région, liste des régions "
    "économiques. Estimations surtout tirées de l'Enquête sur la population "
    "active et d'autres sources; beaucoup de cellules régionales ne sont pas "
    "publiées."
)
