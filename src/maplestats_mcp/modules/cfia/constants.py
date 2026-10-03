"""Constants for the Canadian Food Inspection Agency (CFIA) module.

Every URL below was fetched live on 2026-09-26. inspection.canada.ca
(Drupal, WET/GCWeb theme) serves an empty robots.txt (HTTP 200, zero
bytes), so no path is disallowed and no crawl delay is asked; its pages
link the Canada.ca terms, which allow non-commercial reproduction with
the title, author and source URL, which every result's provenance
carries. URLs the site retired answer HTTP 410 (the yearly
"...-canada-2025" disease pages and the old terms page did), so a 404 or
410 here means the page moved and the module needs updating.

None of the tables has a JSON or CSV file behind it: the pages load
only the WET toolkit, analytics and Font Awesome scripts, and the
premises table is sorted and filtered client-side by wet-boew's
data-wb-tables and data-wb-fieldflow attributes over the inline HTML.
"""

SITE = "https://inspection.canada.ca"
_EN = SITE + "/en/animal-health/terrestrial-animals/diseases/reportable"
_FR = SITE + "/fr/sante-animaux/animaux-terrestres/maladies/declaration-obligatoire"

# "Federally reportable diseases for terrestrial animals in Canada":
# one Disease/Total table per year, 2011 to the current year.
REPORTABLE_PAGE = {"en": _EN + "/canada", "fr": _FR + "/au-canada"}

# "Investigations and orders of avian influenza in domestic birds by
# province": one row per infected premises since December 2021.
_AI_EN = _EN + "/avian-influenza/latest-bird-flu-situation"
_AI_FR = _FR + "/influenza-aviaire/situation-actuelle-grippe-aviaire"
HPAI_PREMISES_PAGE = {
    "en": _AI_EN + "/investigations-and-orders",
    "fr": _AI_FR + "/enquetes-ordonnances-decrets",
}
# "Status of ongoing avian influenza response by province": current and
# released premises and birds impacted, by province.
HPAI_STATUS_PAGE = {"en": _AI_EN + "/status-province", "fr": _AI_FR + "/statut-province"}

# The per-disease "data by month" pages linked from the yearly table that
# share one layout (Year, Date confirmed, Location, Animal type infected;
# BSE adds Age of animal). Equine infectious anemia is left out: its page
# is one table per province and year, stops at 2019 and was last modified
# 2023-09-18, while the yearly table counts EIA premises to 2026. Newcastle
# disease links to a movement control map, not a detection table.
DETECTION_PAGES: dict[str, dict[str, str]] = {
    "chronic_wasting_disease": {
        "en": _EN + "/cwd/herds-infected",
        "fr": _FR + "/mdc/troupeaux-infectes",
    },
    "scrapie": {
        "en": _EN + "/scrapie/flocks-infected",
        "fr": _FR + "/tremblante/troupeaux-infectes",
    },
    "bovine_tuberculosis": {
        "en": _EN + "/bovine-tuberculosis/herds-infected",
        "fr": _FR + "/tuberculose-bovine/troupeaux-infectes",
    },
    "cysticercosis": {
        "en": _EN + "/cysticercosis/herds-infected",
        "fr": _FR + "/cysticercose/troupeaux-infectes",
    },
    "bovine_spongiform_encephalopathy": {
        "en": _EN + "/canada/confirmed-cases-bse",
        "fr": _FR + "/au-canada/cas-confirmes-esb",
    },
    "trichinellosis": {
        "en": _EN + "/canada/trichinellosis",
        # The French slug really has a doubled "t" (checked 2026-09-26).
        "fr": _FR + "/au-canada/ttrichinose",
    },
    "avian_influenza": {
        "en": _EN + "/avian-influenza/avian-influenza",
        "fr": _FR + "/influenza-aviaire/influenza-aviaire",
    },
}

# Canonical diseases: English and French names, and every other spelling
# seen in the yearly tables (2011-2026, both languages) or likely to be
# typed. Matching folds case, accents and apostrophes.
DISEASES: dict[str, tuple[str, str, tuple[str, ...]]] = {
    # key: (English name, French name, other spellings)
    "anaplasmosis": ("Anaplasmosis", "Anaplasmose", ()),
    "anthrax": ("Anthrax", "Fièvre charbonneuse", ("charbon bacteridien", "maladie du charbon")),
    "avian_influenza": (
        "Avian influenza",
        "Influenza aviaire",
        (
            "notifiable avian influenza",
            "influenza aviaire a declaration obligatoire",
            "bird flu",
            "grippe aviaire",
            "hpai",
            "iahp",
        ),
    ),
    "bovine_spongiform_encephalopathy": (
        "Bovine spongiform encephalopathy",
        "Encéphalopathie spongiforme bovine",
        ("bse", "esb", "mad cow", "vache folle"),
    ),
    "bovine_tuberculosis": (
        "Bovine tuberculosis",
        "Tuberculose bovine",
        ("bovine tb", "tb", "tuberculosis", "tuberculose"),
    ),
    "chronic_wasting_disease": (
        "Chronic wasting disease",
        "Maladie débilitante chronique",
        ("cwd", "mdc"),
    ),
    "cysticercosis": (
        "Cysticercosis",
        "Cysticercose",
        ("bovine cysticercosis", "cysticercose bovine"),
    ),
    "equine_infectious_anemia": (
        "Equine infectious anemia",
        "Anémie infectieuse des équidés",
        ("eia", "aie", "equine infectious anaemia", "swamp fever"),
    ),
    "newcastle_disease": ("Newcastle disease", "Maladie de Newcastle", ("newcastle",)),
    "scrapie": (
        "Scrapie",
        "Tremblante",
        ("tremblante du mouton", "classical scrapie", "tremblante classique"),
    ),
    "trichinellosis": ("Trichinellosis", "Trichinose", ("trichinosis", "trichinella")),
}

# Province and territory codes with their English and French names, plus
# the other spellings the pages use ("Île-Prince-Édouard" in the French
# premises table).
PROVINCES: dict[str, tuple[str, str]] = {
    "AB": ("Alberta", "Alberta"),
    "BC": ("British Columbia", "Colombie-Britannique"),
    "MB": ("Manitoba", "Manitoba"),
    "NB": ("New Brunswick", "Nouveau-Brunswick"),
    "NL": ("Newfoundland and Labrador", "Terre-Neuve-et-Labrador"),
    "NS": ("Nova Scotia", "Nouvelle-Écosse"),
    "NT": ("Northwest Territories", "Territoires du Nord-Ouest"),
    "NU": ("Nunavut", "Nunavut"),
    "ON": ("Ontario", "Ontario"),
    "PE": ("Prince Edward Island", "Île-du-Prince-Édouard"),
    "QC": ("Quebec", "Québec"),
    "SK": ("Saskatchewan", "Saskatchewan"),
    "YT": ("Yukon", "Yukon"),
}
PROVINCE_ALIASES = {
    "ile-prince-edouard": "PE",
    "pei": "PE",
    "ipe": "PE",
    "newfoundland": "NL",
    "terre-neuve": "NL",
    "yukon territory": "YT",
}

RATE_LIMIT_SOURCE = "cfia"
RATE_LIMIT_PER_SECOND = 1.0
RATE_LIMIT_CAPACITY = 2.0

# The yearly table is refreshed on the 10th of each month; the premises
# and status pages change whenever a detection is confirmed or a premises
# released (several times a week during an outbreak); the per-disease
# detection pages change a few times a year.
REPORTABLE_TTL_SECONDS = 6 * 60 * 60
HPAI_TTL_SECONDS = 60 * 60
DETECTION_TTL_SECONDS = 12 * 60 * 60
# The French premises page was 614 KB on 2026-09-26.
MAX_PAGE_BYTES = 4 * 1024 * 1024

# 100 detections came to about 280 KB.
HPAI_DEFAULT_LIMIT = 25
HPAI_MAX_LIMIT = 1000

REFERENCE_TZ = "America/Toronto"
