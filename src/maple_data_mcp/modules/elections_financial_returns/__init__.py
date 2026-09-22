"""Elections Canada's Political Financing candidate financial-return search
(www.elections.ca/WPAPPS/WPF/), scoped to the "Candidates" political
entity type only.

This is a separate, distinct platform from the ordinary CKAN datasets
already published under the `elections` organization on open.canada.ca
(poll-by-poll voting results, turnout, electoral boundary files, and
donor-level contribution bulk exports -- all already reachable through
the existing `ckan_federal` module's `ckan_search_datasets`/
`ckan_get_dataset`/`ckan_datastore_search`, several with DataStore-active
resources confirmed live 2026-09-21, e.g. "44th General Election:
Official Voting Results" Table 11 "Voting results by electoral
district"). This module instead covers each *candidate's* full official
campaign financial return -- 13 line-item statements (contributions
received, loans, expenses, transfers, bank reconciliation, and more)
filed under the Canada Elections Act -- which is not published in bulk
on CKAN at all and exists only behind this portal's own search-and-
report workflow.

The portal is a legacy ASP.NET MVC app with no documented public API.
It is server-session-bound: a candidate search POST and a "select
candidates" POST together produce a `queryId` scoped to that session
(confirmed live 2026-09-21 -- reusing a `queryId` without its issuing
session's cookies redirects back to the search form with HTTP 302
rather than erroring), after which any of the 13 report parts can be
downloaded as real, well-formed JSON (`downloadFormat=3`) for that
candidate. See client.py's docstring for the exact request sequence and
every quirk confirmed against live responses.

Political entity types other than Candidates (leadership contestants,
nomination contestants, registered associations, registered parties)
use a visibly different search-form shape on the same portal (confirmed
live: "Registered parties" skips the election-period picker entirely
and asks for Annual/Quarterly/General-election-expenses returns
instead) and were not mapped in this pass -- a deliberate, stated scope
limit, not an oversight.
"""

MODULE_NAME = "elections_financial_returns"
MODULE_DESCRIPTION = (
    "Elections Canada Political Financing (elections.ca/WPAPPS/WPF): search "
    "federal election candidates by name, party, or province, then retrieve "
    "any of the 13 parts of a candidate's official campaign financial return "
    "(declaration, contributions received, loans, expenses, transfers, bank "
    "reconciliation) as structured line-item data. Covers the Candidates "
    "political entity only; distinct from the bulk poll-by-poll results and "
    "donor-contribution CKAN datasets already reachable via ckan_federal."
)
MODULE_DESCRIPTION_FR = (
    "Financement politique d'Élections Canada (elections.ca/WPAPPS/WPF) : "
    "recherche de candidats aux élections fédérales par nom, parti ou "
    "province, puis récupération de l'une des 13 parties du rapport de "
    "campagne officiel d'un candidat (déclaration, contributions reçues, "
    "prêts, dépenses, transferts, rapprochement bancaire) sous forme de "
    "données structurées. Couvre uniquement l'entité politique Candidats; "
    "distinct des jeux de données CKAN de résultats par bureau de scrutin et "
    "de contributions déjà accessibles via ckan_federal."
)
