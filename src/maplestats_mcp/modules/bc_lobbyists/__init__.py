"""British Columbia Office of the Registrar of Lobbyists (ORL) open data.

The ORL publishes two monthly "mass dataset" zips of CSVs behind its public
registry (lobbyistsregistrar.bc.ca): every registration return filed since
2010 and every lobbying activity report (who lobbied which public office
holder, on what) since the Lobbyists Transparency Act took effect on
2020-05-04. Licence: Open Data Licence for the ORL (worldwide, royalty-free,
commercial use allowed, attribution required, no right to Personal
Information). Checked live 2026-10-02; see client.py for what is dropped.
"""

MODULE_NAME = "bc_lobbyists"
MODULE_DESCRIPTION = (
    "British Columbia lobbyists registry (Office of the Registrar of Lobbyists), tools "
    "prefixed bc_lobbyists_: search registrations (client, consultant firm, lobbyists, "
    "topics, ministries targeted, active or ended, period) and lobbying activity reports "
    "since 2020-05-04 (who met which senior public office holder, which ministry, on "
    "what subject), count activity by client, ministry, office holder, subject or month, "
    "and list the registry's subject matters, intended outcomes and ministries. Monthly "
    "open data under the ORL Open Data Licence; addresses, telephone numbers, political "
    "contribution flags, gifts and lobbyists' past public offices are left out because "
    "the licence grants no rights to Personal Information. The federal registry is "
    "blocked to automated access (see the roadmap)."
)
MODULE_DESCRIPTION_FR = (
    "Registre des lobbyistes de la Colombie-Britannique (ORL), outils préfixés bc_lobbyists_ : "
    "recherche des inscriptions (client, cabinet-conseil, lobbyistes, sujets, ministères visés, actives ou terminées, période) "
    "et des rapports d'activité de lobbying depuis le 2020-05-04 (qui a rencontré quel "
    "titulaire de charge publique supérieure, quel ministère, sur quel sujet), décompte de "
    "l'activité par client, ministère, titulaire, sujet ou mois, et liste des sujets, "
    "résultats visés et ministères du registre. Données ouvertes mensuelles sous la licence "
    "de données ouvertes de l'ORL ; les adresses, numéros de téléphone, indicateurs de "
    "contributions politiques, cadeaux et anciennes charges publiques des lobbyistes sont "
    "exclus, la licence n'accordant aucun droit sur les renseignements personnels. Le "
    "registre fédéral est inaccessible aux requêtes automatisées (voir la feuille de route)."
)
