"""CRA's public registry of digital economy businesses registered for the
simplified GST/HST (canada.ca, not open.canada.ca CKAN).

Confirmed live 2026-09-21: this registry is genuinely not published as a
CKAN dataset under the `cra-arc` organization (a `package_search` for its
own title/topic returns nothing matching) -- it exists only as a plain,
server-rendered HTML page, disclosed under the legal authority of the
Excise Tax Act, listing which digital economy businesses (cross-border
digital products/services, platform-based short-term accommodation)
have registered for the simplified GST/HST since 2021-07-01. The page
states it was "updated on" the day this module was built, so it
refreshes at least daily.

The page renders as a jQuery DataTables table, but -- confirmed live by
diffing the raw server HTML against the live DOM -- the *entire* dataset
(2,347 rows the day this was built) is server-rendered in one plain GET,
not paginated or AJAX-loaded; DataTables only handles client-side
display paging in the browser. One `httpx` GET and a BeautifulSoup parse
is therefore enough to retrieve every row, no session or pagination
handling needed (unlike modules/elections_financial_returns/, which
genuinely does require both).
"""

MODULE_NAME = "cra_digital_economy_registry"
MODULE_DESCRIPTION = (
    "CRA's public registry of digital economy businesses (cross-border "
    "digital products/services, platform-based short-term accommodation) "
    "registered for the simplified GST/HST under the Excise Tax Act "
    "(canada.ca, not CKAN). Search by legal name, trade name, or business "
    "number to confirm whether a business may charge GST/HST under the "
    "simplified regime."
)
MODULE_DESCRIPTION_FR = (
    "Registre public de l'ARC des entreprises de l'économie numérique "
    "(produits et services numériques transfrontaliers, hébergement de "
    "courte durée par plateforme) inscrites à la TPS/TVH simplifiée en "
    "vertu de la Loi sur la taxe d'accise (canada.ca, pas CKAN). "
    "Recherche par nom légal, nom commercial ou numéro d'entreprise pour "
    "confirmer si une entreprise peut facturer la TPS/TVH sous le régime "
    "simplifié."
)
