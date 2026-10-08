"""Guided-workflow MCP prompts for the cmhc module.

Each prompt picks its body by ``lang``; the French body is written for a
francophone analyst, not translated line by line.
"""

# No `from __future__ import annotations`: FastMCP resolves a prompt's
# parameter types by name, and the stringified `Lang` alias does not resolve.
from typing import Annotated, Literal

from fastmcp.prompts import prompt

Lang = Annotated[Literal["en", "fr"], "Language: 'en' or 'fr'"]

_FIND_AND_QUERY = {
    "en": (
        "To find and fetch CMHC housing data about '{topic}':\n"
        "1. Check docs://cmhc/well-known-categories first - it already lists the "
        "common categories (Primary Rental Market, New Housing Construction, "
        "Secondary Rental Market, Seniors' Rental Housing, Population/Households, "
        "Core Housing Need) with their exact spelling.\n"
        "2. If not covered there, call cmhc_list_categories(lang=...) to see every "
        "category currently available - category names are language-dependent "
        "strings, so use the same lang for every following call.\n"
        "3. Call cmhc_get_table_options(category_level_1=..., category_level_2=...) "
        "to see the valid column_field/row_field breakdowns for that category - "
        "e.g. 'Bedroom Type' as the column with 'Historical Time Periods' as the "
        "row for a national time series, or 'Provinces' as the row for a current "
        "cross-tabulation by province.\n"
        "4. Call cmhc_get_table_data(category_level_1=..., category_level_2=..., "
        "column_field=..., row_field=...) for the actual data. Default geography "
        "is Canada-wide; call cmhc_list_provinces first and pass "
        "geography_type='Province', geography_id=<id> for one province instead.\n"
        "5. Check each cell's `value` for null before using it - it means the "
        "figure was suppressed or not applicable; the reason is in `flag`. See "
        "docs://cmhc/gotchas for the full reliability-flag legend."
    ),
    "fr": (
        "Pour trouver et obtenir des données de la SCHL sur le logement "
        "(« {topic} ») :\n"
        "1. Consultez d'abord docs://cmhc/fr/categories-courantes : la "
        "ressource donne déjà les grandes catégories (marché locatif "
        "primaire, marché du neuf, marché locatif "
        "secondaire, logements locatifs pour personnes âgées, population et "
        "ménages, besoins impérieux en matière de logement) avec leur "
        "orthographe exacte.\n"
        "2. Si la catégorie n'y figure pas, appelez "
        "cmhc_list_categories(lang='fr') pour voir toutes les catégories "
        "offertes. Les noms de catégories changent selon la langue : gardez "
        "la même lang pour tous les appels suivants.\n"
        "3. Appelez cmhc_get_table_options(category_level_1=..., "
        "category_level_2=...) pour connaître les ventilations valides de "
        "column_field et row_field pour cette catégorie, par exemple le type "
        "de logement en colonne et les périodes historiques en ligne pour une "
        "série nationale, ou les provinces en ligne pour un tableau croisé "
        "courant par province.\n"
        "4. Appelez cmhc_get_table_data(category_level_1=..., "
        "category_level_2=..., column_field=..., row_field=...) pour obtenir "
        "les données. La géographie par défaut est l'ensemble du Canada ; "
        "pour une seule province, appelez d'abord cmhc_list_provinces, puis "
        "passez geography_type='Province' et geography_id=<id>.\n"
        "5. Vérifiez si `value` est nul dans chaque cellule avant de "
        "l'utiliser : cela signifie que le chiffre est supprimé ou sans "
        "objet, et la raison se trouve dans `flag`. La légende complète des "
        "indicateurs de fiabilité est dans docs://cmhc/fr/pieges."
    ),
}


@prompt
def find_and_query_cmhc_table(topic: str, lang: Lang = "en") -> str:
    """Guided workflow: find a CMHC HMIP category on a topic and fetch its data.
    Use lang="fr" for the French version."""
    return _FIND_AND_QUERY[lang].format(topic=topic)
