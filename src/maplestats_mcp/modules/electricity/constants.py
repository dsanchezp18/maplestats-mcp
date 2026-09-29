SOURCE = "electricity"
BASE_URL = "https://reports-public.ieso.ca/public"
COPYRIGHT = (
    "Copyright 2004-2022 Independent Electricity System Operator, all rights reserved. "
    "This information is subject to the Terms of Use set out in the IESO's website "
    "(www.ieso.ca)."
)

# IESO reports use Eastern Standard Time all year round: hour-ending 1..24, with
# 24 rows on both daylight-saving change days (confirmed live 2026-09-29 in
# PUB_Demand.csv for 2026-03-08 and PUB_Demand_2025.csv for 2025-11-02).
IESO_UTC_OFFSET_HOURS = -5

RATE_LIMIT_PER_SECOND = 2.0
RATE_LIMIT_CAPACITY = 4.0

CACHE_TTL_LATEST_SECONDS = 5 * 60
CACHE_TTL_HOURLY_SECONDS = 30 * 60
CACHE_TTL_ARCHIVE_SECONDS = 6 * 60 * 60

FIRST_DEMAND_YEAR = 2002
FIRST_FUEL_YEAR = 2015
DEFAULT_LIMIT = 48
MAX_LIMIT = 2000

# Fuel column of the hourly output report -> snake_case key.
CONTROL_ACTIONS_FUEL = "control_actions"
