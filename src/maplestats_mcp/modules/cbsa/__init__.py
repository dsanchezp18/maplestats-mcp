"""Canada Border Services Agency (CBSA): current land border wait times.

CBSA publishes one small CSV per language with the current wait at about
30 land crossings (commercial and traveller lanes, both directions),
rewritten every few minutes, under the Open Government Licence - Canada.
Checked live 2026-10-03; see client.py.
"""

MODULE_NAME = "cbsa"
MODULE_DESCRIPTION = (
    "Canada Border Services Agency current land border wait times, tools prefixed cbsa_: "
    "the wait in minutes at about 30 Canada-U.S. crossings (Peace Bridge, Ambassador "
    "Bridge, Pacific Highway, Lacolle and others) for commercial and traveller lanes, "
    "Canada-bound and U.S.-bound, with each crossing's own update time, filtered by "
    "province, crossing or direction, in English or French. Open Government Licence - "
    "Canada. Historical wait-time files are open.canada.ca datasets (ckan_, portal "
    "'federal')."
)
MODULE_DESCRIPTION_FR = (
    "Temps d'attente actuels à la frontière terrestre de l'Agence des services frontaliers "
    "du Canada (ASFC), outils préfixés cbsa_ : l'attente en minutes à une trentaine de "
    "postes frontaliers canado-américains (pont Peace, pont Ambassador, Pacific Highway, "
    "Lacolle, etc.) pour les voies commerciales et des voyageurs, vers le Canada et vers "
    "les États-Unis, avec l'heure de mise à jour de chaque poste, filtrés par province, "
    "poste ou direction, en français ou en anglais. Licence du gouvernement ouvert – "
    "Canada. Les fichiers historiques sont des jeux de données d'open.canada.ca (ckan_)."
)
