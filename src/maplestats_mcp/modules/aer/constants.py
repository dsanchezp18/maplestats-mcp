WWW_DOMAIN = "www.aer.ca"
STATIC_DOMAIN = "static.aer.ca"
RATE_LIMIT_SOURCE = "aer"
# No published rate limit found; kept conservative like this project's
# other unpublished-limit legacy government portals.
RATE_LIMIT_PER_SECOND = 3.0
RATE_LIMIT_CAPACITY = 5.0

TIMEZONE = "America/Edmonton"

CACHE_TTL_DAILY_SECONDS = 6 * 60 * 60
CACHE_TTL_LINK_SECONDS = 24 * 60 * 60

# ST1 daily well-licence report -- confirmed live 2026-09-22 this must be
# fetched from static.aer.ca directly (see module docstring for why).
DAY_CODES = {
    "sunday": "SUN",
    "monday": "MON",
    "tuesday": "TUE",
    "wednesday": "WED",
    "thursday": "THU",
    "friday": "FRI",
    "saturday": "SAT",
}
WELL_LICENCE_DAILY_URL = f"https://{STATIC_DOMAIN}/prd/data/well-lic/WELLS{{day_code}}.TXT"

# Confirmed live 2026-09-22: the current year publishes one ZIP per
# month; every prior year publishes a single ZIP for the whole year.
# The path prefix also genuinely changes at the 2023/2024 boundary
# (2024 onward uses "/prd/data/well-lic/", 2023 and earlier use
# "/data/well-lic/" with no "prd" segment) -- confirmed by reading the
# real links on the ST1 archive page, not guessed.
WELL_LICENCE_MONTHLY_ZIP_URL = (
    f"https://{WWW_DOMAIN}/prd/data/well-lic/dwll{{year}}-{{month:02d}}.zip"
)
WELL_LICENCE_YEARLY_ZIP_URL_NEW = f"https://{WWW_DOMAIN}/prd/data/well-lic/dwll{{year}}.zip"
WELL_LICENCE_YEARLY_ZIP_URL_OLD = f"https://{WWW_DOMAIN}/data/well-lic/dwll{{year}}.zip"
WELL_LICENCE_YEARLY_URL_PATH_BOUNDARY_YEAR = 2024

# ST3 monthly production volumes/prices -- confirmed live 2026-09-22
# against every "_current.xlsx" link on the ST3 report page.
PRODUCTION_PRODUCTS = {
    "butane": "Butane",
    "ethane": "Ethane",
    "gas": "Gas",
    "ngl": "NGL",
    "oil": "Oil",
    "propane": "Propane",
    "sulphur": "Sulphur",
    "oil_prices": "prices_oil",
}
PRODUCTION_VOLUMES_URL = f"https://{WWW_DOMAIN}/documents/sts/st3/{{product_path}}_current.xlsx"
