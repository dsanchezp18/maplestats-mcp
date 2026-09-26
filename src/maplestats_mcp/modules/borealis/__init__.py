"""Beyond 20/20 (IVT) tables on Borealis, the Canadian Dataverse Repository.

Some Statistics Canada tables exist only as Beyond 20/20 .ivt files, and
most of those outside StatCan's own site sit on Borealis, deposited by
university libraries through the Data Liberation Initiative. Checked
live 2026-09-25 through Borealis' public Dataverse search API: 3,347 .ivt
files in 108 datasets, 3,324 downloadable without logging in (historical
censuses 1665-1871, Census of Population 1996-2021 tabulations, Census of
Agriculture 2001, Labour Force Historical Review 1997-2008, Canadian
Business Patterns and Counts, justice surveys, HART housing). This module
finds them and returns an R snippet that reads each with canivt
(mountainMath), the only maintained IVT reader.
"""

MODULE_NAME = "borealis"
MODULE_DESCRIPTION = (
    "Beyond 20/20 (.ivt) statistical tables on Borealis, the Canadian Dataverse "
    "Repository (borealisdata.ca, tools prefixed borealis_): about 3,300 IVT files "
    "deposited by Canadian university libraries, mostly Statistics Canada data "
    "that exists only in this format: historical censuses 1665-1871, Census of "
    "Population tabulations 1996-2021, Census of Agriculture 2001, the Labour Force "
    "Historical Review 1997-2008, Canadian Business Patterns and Business Counts, "
    "justice surveys and HART housing tabulations. Search by words in the dataset "
    "or file name; each hit returns its download URL, size, whether it needs a "
    "Borealis login, and an R snippet that reads it with canivt. StatCan's own "
    "2006-2016 census tables are covered by statcan_census_tables_."
)
MODULE_DESCRIPTION_FR = (
    "Tableaux statistiques Beyond 20/20 (.ivt) sur Borealis, le dépôt Dataverse "
    "canadien (borealisdata.ca, outils préfixés borealis_) : environ 3 300 fichiers "
    "IVT déposés par des bibliothèques universitaires canadiennes, surtout des "
    "données de Statistique Canada offertes uniquement dans ce format : "
    "recensements historiques de 1665 à 1871, totalisations du Recensement de la "
    "population de 1996 à 2021, Recensement de l'agriculture de 2001, Revue "
    "chronologique de la population active de 1997 à 2008, Structure des "
    "industries canadiennes et Nombre d'entreprises canadiennes. Chaque résultat "
    "donne l'URL de téléchargement, la taille, l'accès et un extrait R qui lit le "
    "fichier avec canivt."
)
