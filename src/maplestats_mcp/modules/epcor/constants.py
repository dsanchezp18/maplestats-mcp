SOURCE = "epcor"
DAILY_URL = "https://apps.epcor.ca/DailyWaterQuality/Default.aspx"
TIMEZONE = "America/Edmonton"

# Plant key -> the `zone` query value the iframe uses (confirmed live).
PLANTS = {"els": "ELS", "rossdale": "Rossdale"}
PLANT_NAMES = {"els": "E.L. Smith", "rossdale": "Rossdale"}

# Span-id prefix -> (output field, unit). Confirmed live on both plants.
MEASURES = {
    "Hardness": ("total_hardness", "mg/L as CaCO3"),
    "ph": ("ph", "pH"),
    "Temp": ("temperature", "°C"),
    "Chlorine": ("total_chlorine_residual", "mg/L"),
    "Alkalinity": ("alkalinity", "mg/L as CaCO3"),
    "Conductivity": ("conductivity", "µS/cm"),
    "SodaDose": ("caustic_soda_dose", "mg/L"),
}

RATE_LIMIT_PER_SECOND = 1.0
RATE_LIMIT_CAPACITY = 3.0

CACHE_TTL_DAILY_SECONDS = 60 * 60
