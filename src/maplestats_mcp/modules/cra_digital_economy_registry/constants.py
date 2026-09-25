URL_EN = (
    "https://www.canada.ca/en/revenue-agency/services/tax/businesses/topics/"
    "gst-hst-businesses/digital-economy-gsthst/confirming-simplified-gst-hst-account-number.html"
)
URL_FR = (
    "https://www.canada.ca/fr/agence-revenu/services/impot/entreprises/sujets/"
    "tps-tvh-entreprises/tpstvh-entreprises-economie-numerique/"
    "confirmer-numero-compte-tps-tvh-simplifie.html"
)
RATE_LIMIT_SOURCE = "cra_digital_economy_registry"
RATE_LIMIT_PER_SECOND = 2.0
RATE_LIMIT_CAPACITY = 2.0
# The page states it was "updated" the day this module was built -- at
# least daily -- so caching longer than a few hours risks serving a stale
# registration/de-registration status. 6h balances that against not
# re-fetching a ~470KB page on every call.
CACHE_TTL_SECONDS = 6 * 60 * 60
SEARCH_RESULTS_MAX = 200
