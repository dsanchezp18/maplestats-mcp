"""National Forestry Database (NFD), Canadian Council of Forest Ministers.

The NFD (nfdp.ccfm.org, run with the Canadian Forest Service) publishes
25 tables on its Download page, each as one bilingual CSV and XLSX, a data
dictionary and, for 19 of them, a comments workbook. Checked live
2026-10-02. Terms (terms.php): "made available for public use under the
Open Government Licence - Canada version 2.0". The federal CKAN catalogue does not list these files.
"""

MODULE_NAME = "nfd"
MODULE_DESCRIPTION = (
    "National Forestry Database (nfdp.ccfm.org, Canadian Council of Forest "
    "Ministers, tools prefixed nfd_): 25 tables by province and territory, 1940 to "
    "2025. Forest fires (number and area burned by cause, month and fire size "
    "class, property losses), insects (defoliated area), roundwood harvest "
    "(volume by category, species group and tenure; area by harvesting method), "
    "wood supply, regeneration (site preparation, scarification, seeding, "
    "planting, stand tending), timber revenues and pest control (insecticides "
    "and herbicides). List tables, describe a table (dimensions, units, data "
    "dictionary, data-quality codes), query rows with province, year and "
    "category filters or sum them, and read the agencies' comments and "
    "footnotes. English or French labels. Open Government Licence - Canada."
)
MODULE_DESCRIPTION_FR = (
    "Base nationale de données forestières (nfdp.ccfm.org, Conseil canadien des "
    "ministres des forêts, outils préfixés nfd_) : 25 tableaux par province et "
    "territoire, de 1940 à 2025. Incendies de forêt (nombre et superficie "
    "brûlée selon l'origine, le mois et la classe de superficie, dommages aux "
    "propriétés), insectes (superficie défoliée), récolte de bois rond (volume "
    "par catégorie, groupe d'espèces et tenure; superficie par méthode de "
    "récolte), approvisionnement en bois, régénération (préparation de terrain, "
    "scarifiage, ensemencement, plantation, soins culturaux), revenus du bois et "
    "lutte antiparasitaire (insecticides et herbicides). Liste des tableaux, "
    "description d'un tableau (dimensions, unités, dictionnaire de données, codes "
    "de qualité), requête de lignes avec filtres par province, année et "
    "catégorie ou sommes, commentaires et renvois des organismes. Libellés en "
    "français ou en anglais. Licence du gouvernement ouvert - Canada."
)
