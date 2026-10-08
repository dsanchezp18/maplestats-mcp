"""Guided-workflow MCP prompts for the eccc module.

Each prompt picks its body by ``lang``; the French body is written for a
francophone analyst, not translated line by line. Literal braces in the
bodies are doubled because the bodies go through ``str.format``.
"""

# No `from __future__ import annotations`: FastMCP resolves a prompt's
# parameter types by name, and the stringified `Lang` alias does not resolve.
from typing import Annotated, Literal

from fastmcp.prompts import prompt

Lang = Annotated[Literal["en", "fr"], "Language: 'en' or 'fr'"]

_FIND_AND_QUERY = {
    "en": (
        "To find and fetch MSC GeoMet (Environment and Climate Change Canada) data about "
        "'{topic}':\n"
        "1. Check docs://eccc/well-known-collections first - it already lists the "
        "collection ids that matter most (weather-alerts, swob-realtime, "
        "aqhi-observations-realtime, climate-normals, hydrometric-realtime, "
        "marineweather-realtime, and more) with example property filters for each.\n"
        "2. If not covered there, call eccc_search_collections(query=<topic>) to find a "
        "candidate collection id among the ~100 this server publishes.\n"
        "3. Call eccc_get_collection(collection_id=...) to confirm what it covers and see "
        "its full list of queryable property names - an unrecognized property name is "
        "silently ignored upstream and returns zero rows rather than an error, so check "
        "here before filtering.\n"
        "4. Call eccc_query_items(collection_id=..., filters={{...}}, bbox=[...], limit=...) "
        "for the actual rows. Prefer filtering by a station id/province/other property or a "
        "narrow bbox over paging through an entire large collection. Try datetime_filter "
        "only after the above - support for it genuinely varies by collection (see "
        "docs://eccc/gotchas)."
    ),
    "fr": (
        "Pour trouver et obtenir des données de MSC GeoMet (Environnement et "
        "Changement climatique Canada) sur « {topic} » :\n"
        "1. Consultez d'abord docs://eccc/fr/collections-courantes : la "
        "ressource donne déjà les identifiants de collection les plus utiles "
        "(weather-alerts, swob-realtime, aqhi-observations-realtime, "
        "climate-normals, hydrometric-realtime, marineweather-realtime, et "
        "d'autres) avec des exemples de filtres par propriété.\n"
        "2. Si le sujet n'y figure pas, appelez "
        "eccc_search_collections(query=<sujet>, lang='fr') pour repérer un "
        "identifiant candidat parmi la centaine de collections publiées.\n"
        "3. Appelez eccc_get_collection(collection_id=...) pour confirmer ce "
        "qu'elle couvre et lire la liste complète de ses propriétés "
        "interrogeables. Un nom de propriété inconnu est ignoré sans erreur "
        "par le service, qui renvoie alors zéro ligne : vérifiez donc ici "
        "avant de filtrer.\n"
        "4. Appelez eccc_query_items(collection_id=..., filters={{...}}, "
        "bbox=[...], limit=...) pour obtenir les lignes. Filtrez de "
        "préférence par identifiant de station, province ou autre propriété, "
        "ou par une zone bbox étroite, plutôt que de parcourir une grande "
        "collection page par page. N'essayez datetime_filter qu'ensuite : sa "
        "prise en charge varie vraiment d'une collection à l'autre (voir "
        "docs://eccc/fr/pieges)."
    ),
}

_SEVERE_WEATHER = {
    "en": (
        "To check for active weather alerts affecting '{location}':\n"
        '1. Call eccc_query_items(collection_id="weather-alerts", '
        'filters={{"province": <2-letter code for {location}>}}) - or pass a bbox around '
        "{location} instead if you have its coordinates.\n"
        '2. Read each returned feature\'s `properties.status_en` ("alert" means still '
        'active; "ended" means it has expired), `alert_type`, `risk_colour_en`, '
        "`feature_name_en` (the specific affected area), and `alert_text_en` (the full "
        "alert text).\n"
        "3. weather-alerts does not support datetime_filter (see docs://eccc/gotchas) - "
        "filter by province/bbox only."
    ),
    "fr": (
        "Pour vérifier les alertes météorologiques en vigueur à « {location} » :\n"
        '1. Appelez eccc_query_items(collection_id="weather-alerts", '
        'filters={{"province": <code à 2 lettres de la province de {location}>}}) '
        "ou passez plutôt une zone bbox autour de {location} si vous en "
        "connaissez les coordonnées.\n"
        "2. Lisez, pour chaque entité retournée, `properties.status_en` "
        '("alert" : toujours en vigueur ; "ended" : expirée), `alert_type`, '
        "`risk_colour_en`, `feature_name_en` (le secteur touché) et "
        "`alert_text_fr` (le texte complet de l'alerte en français ; "
        "`alert_text_en` donne la version anglaise).\n"
        "3. La collection weather-alerts ne prend pas en charge "
        "datetime_filter (voir docs://eccc/fr/pieges) : filtrez uniquement "
        "par province ou par bbox."
    ),
}


@prompt
def find_and_query_eccc_collection(topic: str, lang: Lang = "en") -> str:
    """Guided workflow: find an MSC GeoMet collection on a topic and query its data.
    Use lang="fr" for the French version."""
    return _FIND_AND_QUERY[lang].format(topic=topic)


@prompt
def eccc_severe_weather_check(location: str, lang: Lang = "en") -> str:
    """Guided workflow: check for active weather alerts affecting a Canadian location.
    Use lang="fr" for the French version."""
    return _SEVERE_WEATHER[lang].format(location=location)
