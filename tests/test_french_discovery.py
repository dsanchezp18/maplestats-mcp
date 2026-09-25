"""French queries must find the same tools through search_tools as English ones.

Every tool carries a `Mots-clés :` line for BM25SearchTransform to index;
these pairs pin down the domain terms a francophone user actually types,
so a docstring edit that drops one fails here rather than silently.
"""

from __future__ import annotations

import re

import pytest
from fastmcp import Client

from maplestats_mcp.server import mcp

TOP_N = 3

CASES = [
    ("taux de chômage", "statcan_indicators_get_indicators"),
    ("indice des prix à la consommation", "statcan_indicators_get_indicators"),
    ("PIB par industrie", "wds_search_cubes"),
    ("classification des industries SCIAN", "rdaas_get_classification"),
    ("mises en chantier", "cmhc_list_categories"),
    ("taux directeur", "boc_search_series"),
    ("recherche de marques de commerce", "ised_cipo_search_trademarks"),
    ("ronde d'invitations entrée express", "ircc_list_express_entry_rounds"),
    ("appels d'offres du gouvernement fédéral", "canadabuys_search_tenders"),
    ("superficie brûlée feux de forêt", "nrcan_nbac_query_fires"),
    ("recherche de jeux de données ouverts Québec", "ckan_search_datasets"),
    ("qualité de l'eau potable Edmonton", "epcor_get_daily_water_quality"),
    ("table des marées pleine mer basse mer", "dfo_iwls_get_water_levels"),
    ("données économiques Alberta taux de chômage", "ab_economic_get_data"),
    ("avis de la Gazette du Canada projets de règlement", "gazette_get_issue"),
    ("projet de loi Chambre des communes état", "parliament_search_bills"),
    ("interventions au hansard période des questions", "parliament_search_speeches"),
    ("vote au Sénat sénateurs projet de loi", "senate_list_votes"),
    # Plurals and missing accents, fixed by shared/search.py (2026-09-24).
    ("loyers", "cmhc_get_table_data"),
    ("code R reproductible script Stata", "reproduce_code"),
    ("tableaux de données du recensement de 2016", "statcan_census_tables_search"),
    ("fichiers de microdonnées à grande diffusion", "statcan_pumf_search"),
    ("dictionnaire de données poids bootstrap", "statcan_pumf_get_codebook"),
    ("hôpitaux", "cihi_search_indicators"),
    ("hopital", "cihi_search_indicators"),
    ("tremblements de terre", "earthquakes_search"),
    ("entreprises fédérales", "ised_corporations_get_corporation"),
    ("rappel de véhicule Transports Canada", "tc_recalls_search"),
    ("séisme tremblement de terre magnitude", "earthquakes_search"),
    ("noms géographiques officiels lac rivière", "nrcan_geo_search_names"),
    ("taux de réadmission à l'hôpital ICIS", "cihi_get_indicator_data"),
    ("dépenses fédérales comptes publics ministère", "gc_infobase_query"),
    ("débit des pipelines Régie de l'énergie", "cer_query_file"),
    ("enquête sur la consommation d'énergie des ménages", "nrcan_energy_use_list_products"),
]


@pytest.mark.parametrize(("query", "expected"), CASES)
async def test_french_query_finds_tool(query: str, expected: str):
    async with Client(mcp) as client:
        result = await client.call_tool("search_tools", {"query": query})
    text = " ".join(getattr(block, "text", "") for block in result.content)
    names = re.findall(r'"name":\s*"([a-z0-9_]+)"', text)[:TOP_N]
    assert expected in names, f"{query!r} -> {names}"
