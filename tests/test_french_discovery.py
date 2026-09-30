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
    ("demande d'électricité Ontario par heure", "electricity_ontario_get_hourly_demand"),
    ("production hydroélectrique Hydro-Québec par source", "electricity_quebec_get_generation"),
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
    ("rappel d'aliments allergène ACIA", "recalls_search"),
    ("statistiques de rappels par année", "recalls_summarize"),
    ("rappel d'aliments allergènes", "recalls_search"),
    ("rappel alimentaire", "recalls_search"),
    ("rappel de jouets", "recalls_search"),
    ("produits visés par le rappel numéro de lot", "recalls_get"),
    ("comités de la Chambre des communes", "parliament_list_committees"),
    ("sous-comités et sigle du comité", "parliament_get_committee"),
    ("réunions du comité à huis clos", "parliament_search_committee_meetings"),
    ("témoins comité des finances", "parliament_get_committee_meeting"),
    ("qui a témoigné devant le comité", "parliament_get_committee_meeting"),
    ("séisme tremblement de terre magnitude", "earthquakes_search"),
    ("noms géographiques officiels lac rivière", "nrcan_geo_search_names"),
    ("taux de réadmission à l'hôpital ICIS", "cihi_get_indicator_data"),
    ("dépenses fédérales comptes publics ministère", "gc_infobase_query"),
    ("débit des pipelines Régie de l'énergie", "cer_query_file"),
    ("enquête sur la consommation d'énergie des ménages", "nrcan_energy_use_list_products"),
    ("surdoses d'opioïdes décès par province", "phac_infobase_query"),
    ("charge virale eaux usées", "phac_infobase_list_datasets"),
    ("livraisons de canola aux silos primaires", "cgc_weekly_query"),
    ("exportations de blé par pays de destination", "cgc_exports_query"),
    ("prix des composants du lait classes spéciales", "cdc_get_component_prices"),
    ("quota total cible nationale de production laitière", "cdc_get_national_quota"),
    ("prix de soutien du beurre", "cdc_get_butter_support_prices"),
    # French review of phac_infobase, cgc, fcac and cdc (2026-09-26), with
    # Quebec usage ("influenza", "forfait bancaire", "chèque sans provision").
    ("surveillance de l'influenza au Québec", "phac_infobase_list_datasets"),
    ("dictionnaire de données santé infobase", "phac_infobase_describe_dataset"),
    ("taux de positivité COVID par province", "phac_infobase_query"),
    ("statistiques hebdomadaires sur le grain", "cgc_weekly_describe"),
    ("stocks de blé dans les silos terminaux", "cgc_weekly_query"),
    ("pays de destination des exportations de grain", "cgc_exports_describe"),
    ("exportations de céréales vers la Chine", "cgc_exports_query"),
    ("comparer les cartes de crédit", "fcac_search_credit_cards"),
    ("carte de crédit remise en argent sans frais annuels", "fcac_search_credit_cards"),
    ("assurance voyage carte de crédit", "fcac_get_credit_card"),
    ("compte chèque sans frais", "fcac_search_bank_accounts"),
    ("forfait bancaire caisse populaire", "fcac_search_bank_accounts"),
    ("frais pour chèque sans provision", "fcac_get_bank_account"),
    ("frais d'insuffisance de fonds compte-chèques", "fcac_get_bank_account"),
    ("offices de commercialisation du lait", "cdc_list_datasets"),
    ("producteurs d'œufs gestion de l'offre", "cdc_list_datasets"),
    ("classification harmonisée du lait", "cdc_get_milk_classes"),
    ("tableaux Excel agence de la statistique Terre-Neuve-et-Labrador", "nl_stats_list_files"),
    ("population trimestrielle Terre-Neuve-et-Labrador feuille Excel", "nl_stats_read_file"),
    ("tableaux du Bureau de la statistique du Yukon", "yukon_stats_list_tables"),
    ("loyer et taux d'inoccupation Yukon Whitehorse", "yukon_stats_query_table"),
    ("résultats électoraux par circonscription candidat élu", "elections_results_get_table"),
    ("élections générales fédérales résultats officiels", "elections_results_list_elections"),
    ("production de lait par province", "cdc_query_market_data"),
    ("nombre de fermes laitières", "cdc_query_market_data"),
    # CFIA animal disease tables (2026-09-26).
    ("maladies à déclaration obligatoire animaux terrestres", "cfia_reportable_diseases"),
    ("nombre annuel de cas de maladies animales ACIA", "cfia_reportable_diseases"),
    ("maladie débilitante chronique chez les cerfs et wapitis", "cfia_disease_detections"),
    ("tuberculose bovine détections", "cfia_disease_detections"),
    ("vache folle ESB cas confirmés", "cfia_disease_detections"),
    ("grippe aviaire lieux infectés", "cfia_avian_influenza"),
    ("influenza aviaire hautement pathogène par province", "cfia_avian_influenza"),
    ("éclosion de grippe aviaire dans les élevages de volailles", "cfia_avian_influenza"),
]


@pytest.mark.parametrize(("query", "expected"), CASES)
async def test_french_query_finds_tool(query: str, expected: str):
    async with Client(mcp) as client:
        result = await client.call_tool("search_tools", {"query": query})
    text = " ".join(getattr(block, "text", "") for block in result.content)
    names = re.findall(r'"name":\s*"([a-z0-9_]+)"', text)[:TOP_N]
    assert expected in names, f"{query!r} -> {names}"
