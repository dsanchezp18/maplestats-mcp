"""Guided-workflow MCP prompts for the boc module.

Each prompt picks its body by ``lang``; the French bodies are written
for a francophone analyst, not translated line by line. Tool names and
argument names stay in English because they are code.
"""

# No `from __future__ import annotations`: FastMCP resolves a prompt's
# parameter types by name, and the stringified `Lang` alias does not resolve.
from typing import Annotated, Literal

from fastmcp.prompts import prompt

Lang = Annotated[Literal["en", "fr"], "Language: 'en' or 'fr'"]

_FIND_AND_FETCH = {
    "en": (
        "To find and fetch Bank of Canada data about '{topic}':\n"
        "1. Check docs://boc/well-known-series first - it already lists "
        "the common exchange rate, policy/prime rate, CPI, and commodity "
        "price series names.\n"
        "2. If not covered there, call boc_search_series(query=<topic>) "
        "(or boc_search_groups for a themed family of related series) to "
        "find a candidate series/group name.\n"
        "3. Call boc_get_series(name=...) or boc_get_group(name=...) to "
        "confirm what it measures.\n"
        "4. Call boc_get_observations(series_names=[...], recent=<n>) or "
        "boc_get_group_observations(group_name=..., recent=<n>) for the "
        "latest data, or pass start_date/end_date instead of recent for a "
        "specific historical window."
    ),
    "fr": (
        "Pour trouver et obtenir des données de la Banque du Canada sur "
        "« {topic} » :\n"
        "1. Consultez d'abord docs://boc/fr/series-courantes : la ressource "
        "donne déjà les noms des séries usuelles (taux de change, taux "
        "directeur et taux préférentiel, IPC, prix des produits de base).\n"
        "2. Si le sujet n'y figure pas, appelez "
        "boc_search_series(query=<sujet>) (ou boc_search_groups pour une "
        "famille thématique de séries apparentées) afin de repérer le nom "
        "d'une série ou d'un groupe candidat.\n"
        "3. Appelez boc_get_series(name=...) ou boc_get_group(name=...) "
        "pour confirmer ce qu'il mesure.\n"
        "4. Appelez boc_get_observations(series_names=[...], recent=<n>) "
        "ou boc_get_group_observations(group_name=..., recent=<n>) pour "
        "les données les plus récentes, ou passez start_date et end_date "
        "au lieu de recent pour une période historique précise."
    ),
}

_COMPARE = {
    "en": (
        "To compare {series_names} over the same period:\n"
        "1. Call boc_get_observations(series_names=[...], "
        "start_date=..., end_date=...) with all series names in one "
        "call rather than one call per series.\n"
        "2. Check each returned row's `values` keys before assuming every "
        "series appears in every row - series of different publication "
        "frequencies (e.g. daily vs monthly) are not merged into shared "
        "rows. See docs://boc/gotchas for the confirmed details."
    ),
    "fr": (
        "Pour comparer {series_names} sur une même période :\n"
        "1. Appelez boc_get_observations(series_names=[...], "
        "start_date=..., end_date=...) en passant toutes les séries dans "
        "un seul appel plutôt qu'un appel par série.\n"
        "2. Vérifiez les clés de `values` dans chaque ligne retournée avant "
        "de supposer que toutes les séries y figurent : les séries de "
        "fréquences de publication différentes (par exemple quotidienne et "
        "mensuelle) ne sont pas fusionnées dans les mêmes lignes. Les "
        "détails confirmés se trouvent dans docs://boc/fr/pieges."
    ),
}


@prompt
def find_and_fetch_boc_series(topic: str, lang: Lang = "en") -> str:
    """Guided workflow: find a Bank of Canada Valet series on a topic and
    fetch its recent observations. Use lang="fr" for the French version."""
    return _FIND_AND_FETCH[lang].format(topic=topic)


@prompt
def compare_boc_series(series_names: str, lang: Lang = "en") -> str:
    """Guided workflow: fetch several Bank of Canada series together for
    comparison over the same date range. Use lang="fr" for the French version."""
    return _COMPARE[lang].format(series_names=series_names)
