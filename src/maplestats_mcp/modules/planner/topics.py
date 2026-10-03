"""Curated topic map for plan_query: which sources answer which questions.

Each topic lists trigger terms (English and French, matched without
accents) and the steps an agent should take, in order, across sources.
A term matches whole words, with an English or French plural ("rent"
meets "rents", "industry" meets "industries"); a term ending in "*" is
a stem and matches any word it begins ("affordab*" meets
"affordability"). A step's own `terms` move it to the front of its
topic when the question used one of them, so an earthquake question
starts with the earthquake tool, not the first weather step. A topic's
`shadows` are phrases blanked out before its terms are tried ("house of
commons" is not housing). tests/test_planner.py checks that every tool
named here is registered, so a renamed tool cannot leave a plan pointing
at nothing, and that each step's required arguments are named in its
purpose or come from an earlier step of the same source.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PlanStep:
    tool: str
    purpose: str
    terms: tuple[str, ...] = ()


@dataclass(frozen=True)
class Topic:
    key: str
    label: str
    terms: tuple[str, ...]
    steps: tuple[PlanStep, ...]
    caveats: tuple[str, ...] = ()
    shadows: tuple[str, ...] = ()


_TRADE_TERMS = (
    "trade",
    "export",
    "import",
    "exports",
    "imports",
    "exportation",
    "importation",
    "commodity",
    "tariff",
    "hs code",
    "marchandise",
)
_ELECTRICITY_PRICE_TERMS = (
    "electricity price",
    "power price",
    "hoep",
    "prix de l'electricite",
    "price of electricity",
)
_WEATHER_TERMS = (
    "weather",
    "climate",
    "temperature",
    "precipitation",
    "rain",
    "snow",
    "air quality",
    "flood",
    "river",
    "streamflow",
    "hydrometric",
    "meteo",
    "climat",
    "qualite de l'air",
    "inondation",
    "riviere",
    "cours d'eau",
    "debit journalier",
    "weather forecast",
    "previsions meteo",
)
_TRANSIT_TERMS = (
    "transit",
    "bus",
    "train",
    "autobus",
    "timetable",
    "bus schedule",
    "transit schedule",
    "train schedule",
    "departure",
    "horaire",
    "metro",
    "stop",
)
_VEHICLE_TERMS = (
    "vehicle",
    "car",
    "truck",
    "airbag",
    "vehicule",
    "voiture",
    "camion",
    "honda",
    "toyota",
    "ford",
    "chevrolet",
    "tesla",
    "nissan",
    "hyundai",
    "kia",
    "mazda",
    "subaru",
    "volkswagen",
    "jeep",
)
_ANIMAL_DISEASE_TERMS = (
    "animal disease",
    "reportable disease",
    "chronic wasting",
    "scrapie",
    "bovine tuberculosis",
    "bse",
    "maladie animale",
    "maladies animales",
    "maladie a declaration obligatoire",
    "maladies a declaration obligatoire",
    "maladie debilitante chronique",
    "tremblante",
    "tuberculose bovine",
)
_FINANCE_TERMS = (
    "donation",
    "donor",
    "political contribution",
    "campaign",
    "financial return",
    "don politique",
    "dons politiques",
    "dons aux partis",
    "contributions politiques",
    "financement des partis",
    "financement politique",
    "campagne",
)
_PROVINCIAL_TERMS = (
    "provincial",
    "provinciale",
    "quebec",
    "alberta",
    "british columbia",
    "colombie-britannique",
    "saskatchewan",
    "manitoba",
)
_TIDE_TERMS = ("tide", "water level", "maree", "niveau d'eau")
_FIRE_TERMS = ("wildfire", "fire", "forest fire", "feu de foret", "feux de foret", "incendie")


TOPICS: tuple[Topic, ...] = (
    Topic(
        "housing",
        "Housing: starts, rents, prices, mortgages",
        (
            "housing",
            "house",
            "home",
            "rent",
            "rental",
            "vacancy",
            "mortgage",
            "housing starts",
            "affordab*",
            "dwelling",
            "condo",
            "building permit",
            "logement",
            "loyer",
            "hypothe*",
            "mises en chantier",
            "permis de batir",
            "permis de construire",
            "habitation",
            "inoccupation",
            "mls",
            "crea",
            "prix des maisons",
        ),
        (
            PlanStep(
                "cmhc_list_categories",
                "CMHC starts, completions, rents and vacancy: category_level_1 and _2",
            ),
            PlanStep(
                "cmhc_get_table_options",
                "column_field and row_field options for that category and geography",
            ),
            PlanStep(
                "cmhc_get_table_data",
                "the table: category_level_1, category_level_2, column_field and row_field "
                "(row_field='TIMESERIES' for a series), geography_type and geography_id",
            ),
            PlanStep(
                "cmhc_dt_list_tables",
                "CMHC's published Excel tables: category='rental-market' or "
                "'household-characteristics'",
            ),
            PlanStep(
                "wds_search_cubes",
                "StatCan New Housing Price Index, building permits",
                ("building permit", "permis de batir", "permis de construire", "house"),
            ),
            PlanStep(
                "boc_search_series",
                "Bank of Canada mortgage and policy rates",
                ("mortgage", "hypothe*"),
            ),
            PlanStep(
                "crea_get_hpi_links",
                "CREA MLS® Home Price Index (resale prices): download link, attribution and "
                "terms only; no values, since CREA's terms forbid publishing them",
                ("mls", "crea", "resale", "home price", "house price", "prix des maisons"),
            ),
            PlanStep(
                "statcan_census_profile_get_data",
                "census shelter cost and tenure: level, geography_codes (DGUIDs from "
                "statcan_census_profile_search_geography) and characteristic_codes",
            ),
        ),
        (
            (
                "CMHC reports by census metropolitan area and centre; StatCan price indexes are "
                "by CMA too, but the two define some areas differently, so name the geography "
                "each figure uses."
            ),
        ),
        ("house of commons", "house of assembly", "house vote", "white house"),
    ),
    Topic(
        "prices",
        "Inflation and prices",
        (
            "inflation",
            "cpi",
            "consumer price",
            "prices",
            "cost of living",
            "food price",
            "gas price",
            "gasoline",
            "indice des prix",
            "ipc",
            "cout de la vie",
            "prix",
        ),
        (
            PlanStep("statcan_indicators_get_indicators", "latest headline CPI and change"),
            PlanStep("wds_search_cubes", "CPI table by component or province (e.g. 18-10-0004)"),
            PlanStep("boc_search_series", "Bank of Canada core inflation measures and target"),
        ),
        ("CPI is not seasonally adjusted unless the series says so; compare year over year.",),
        # Electricity prices are the energy topic's Ontario price tool, not the CPI.
        _ELECTRICITY_PRICE_TERMS,
    ),
    Topic(
        "labour",
        "Jobs, unemployment and wages",
        (
            "unemployment",
            "employment",
            "jobs",
            "labour",
            "labor",
            "wage",
            "earnings",
            "workforce",
            "chomage",
            "emploi",
            "salaire",
            "main-d'oeuvre",
            "travail",
        ),
        (
            PlanStep("statcan_indicators_get_indicators", "latest Labour Force Survey headline"),
            PlanStep("wds_search_cubes", "LFS tables by province, CMA, industry or age"),
            PlanStep(
                "ab_economic_list_tables", "Alberta dashboard tables, when the question is Alberta"
            ),
            PlanStep(
                "ab_economic_get_data", "Alberta dashboard series: table from the step before"
            ),
            PlanStep(
                "rdaas_search_classifications",
                "NAICS or NOC codes to name an industry or job",
                ("industry", "occupation", "noc", "naics", "profession"),
            ),
        ),
        (
            "LFS monthly estimates are survey based with sampling error; small areas use 3-month averages.",
        ),
    ),
    Topic(
        "rates",
        "Interest rates, exchange rates and markets",
        (
            "interest rate",
            "policy rate",
            "overnight rate",
            "rate hike",
            "rate cut",
            "mortgage rate",
            "bank of canada",
            "exchange rate",
            "dollar",
            "fx",
            "bond",
            "yield",
            "prime rate",
            "taux directeur",
            "taux d'interet",
            "hausse des taux",
            "baisse des taux",
            "taux hypothecaire",
            "banque du canada",
            "taux de change",
            "obligation",
        ),
        (
            PlanStep("boc_search_series", "find the Valet series (e.g. FXUSDCAD, V39079)"),
            PlanStep("boc_get_observations", "pull the series for the period"),
        ),
    ),
    Topic(
        "international",
        "Canada compared with other countries",
        (
            "compared to other countries",
            "compared with other countries",
            "g7",
            "oecd",
            "world bank",
            "international comparison",
            "peer countries",
            "ppp",
            "comparaison internationale",
            "banque mondiale",
            "ocde",
            "autres pays",
            "pays du g7",
        ),
        (
            PlanStep("worldbank_search_indicators", "find the indicator code (query by words)"),
            PlanStep(
                "worldbank_get_canada_series",
                "Canada's series for the indicator, compared with G7 or OECD countries",
            ),
        ),
    ),
    Topic(
        "economy",
        "GDP, trade and industry output",
        (
            "gdp",
            "economy",
            "economic growth",
            "recession",
            "trade",
            "exports",
            "imports",
            "industry",
            "manufacturing",
            "retail sales",
            "produit interieur brut",
            "pib",
            "economie",
            "croissance",
            "exportation",
            "importation",
            "commerce",
            "commerce interieur",
            "internal trade",
            "interprovincial trade",
        ),
        (
            PlanStep("statcan_daily_get_releases", "what StatCan released recently on the topic"),
            PlanStep("wds_search_cubes", "GDP by industry, trade, retail tables"),
            PlanStep("wds_get_data_from_vectors", "pull the series once vectors are known"),
            PlanStep(
                "sdmx_get_structure",
                "a table's dimensions for a filtered SDMX query: product_id from the search",
            ),
            PlanStep(
                "sdmx_space_search",
                "internal (interprovincial) trade flows: query='internal trade', "
                "space='stcshared', tenant='cith'",
                ("internal trade", "interprovincial trade", "commerce interieur"),
            ),
            PlanStep(
                "cimt_search_commodities",
                "HS code of the commodity (and cimt_search_partners for a country code)",
                _TRADE_TERMS,
            ),
            PlanStep(
                "cimt_get_periods", "latest month in the trade database, as 'YYYY-MM'", _TRADE_TERMS
            ),
            PlanStep(
                "cimt_get_trade",
                "exports or imports by HS commodity, partner and province: direction='exports' "
                "or 'imports', from_period and to_period ('YYYY-MM'), optional hs_code, partner",
                _TRADE_TERMS,
            ),
            PlanStep("rdaas_search_classifications", "NAICS codes for the industry"),
            PlanStep(
                "ab_economic_list_indicators", "Alberta dashboard, when the question is Alberta"
            ),
        ),
    ),
    Topic(
        "population",
        "Population, census and demographics",
        (
            "population",
            "census",
            "demograph*",
            "median age",
            "language",
            "household",
            "income",
            "indigenous",
            "recensement",
            "menage",
            "revenu",
            "langue",
            "autochtone",
        ),
        (
            PlanStep(
                "statcan_census_profile_search_geography",
                "find the census area's DGUID: level='census_subdivisions' (a municipality), "
                "'census_metro_areas' or 'canada_provinces_territories', and query=<place>",
            ),
            PlanStep(
                "statcan_census_profile_search_characteristic",
                "find the characteristic code (query='median age', 'household income'...)",
            ),
            PlanStep(
                "statcan_census_profile_get_data",
                "2021 values: the same level, geography_codes and characteristic_codes",
            ),
            PlanStep(
                "statcan_census_profile_2016_get_data", "2016 values (dguid), to compare over time"
            ),
            PlanStep("statcan_census_tables_search", "2006-2016 cross-tabulations (2021: wds_)"),
            PlanStep("borealis_search_ivt", "older or custom census tables in Beyond 20/20 format"),
            PlanStep(
                "statcan_census_profile_archive_list_geography_levels",
                "2001-2016 census profile bulk files: year=2001, 2006, 2011 or 2016",
                ("2001", "2006", "2011", "historical census"),
            ),
            PlanStep(
                "statcan_geo_list_services",
                "census boundary maps and geography layers: year=2021",
                ("boundary", "boundaries", "map", "limites", "carte"),
            ),
            PlanStep(
                "wds_search_cubes",
                "quarterly population estimates and migration components (17-10-0009, 17-10-0040)",
                ("population estimate", "estimates", "migration", "growth", "quarterly"),
            ),
        ),
        (
            "Census boundaries change between 2016 and 2021; check the area matches before comparing.",
        ),
    ),
    Topic(
        "immigration",
        "Immigration and Express Entry",
        (
            "immigration",
            "immigrant",
            "express entry",
            "permanent resident",
            "refugee",
            "study permit",
            "work permit",
            "crs",
            "asylum",
            "international student",
            "resident permanent",
            "residents permanents",
            "refugie",
            "demandeur d'asile",
            "demandeurs d'asile",
            "permis d'etudes",
            "permis de travail",
            "entree express",
        ),
        (
            PlanStep(
                "ircc_monthly_list_tables",
                "find the table_id: monthly permanent residents, study and work permits, "
                "asylum claims (query='study permit'...)",
            ),
            PlanStep("ircc_monthly_query", "query that table_id by year_from, year_to and filters"),
            PlanStep(
                "ircc_list_express_entry_rounds",
                "Express Entry draws and CRS cutoffs",
                ("express entry", "crs", "entree express"),
            ),
            PlanStep("wds_search_cubes", "StatCan population estimates of immigrants and NPRs"),
        ),
    ),
    Topic(
        "health",
        "Health system",
        (
            "health",
            "hospital",
            "wait time",
            "physician",
            "doctor",
            "nurse",
            "emergency",
            "readmission",
            "mortality",
            "sante",
            "hopital",
            "hopitaux",
            "temps d'attente",
            "medecin",
            "infirmi*",
            "urgence",
        ),
        (
            PlanStep("cihi_search_indicators", "CIHI indicator for the measure"),
            PlanStep("cihi_get_indicator_data", "values by province or region"),
            PlanStep("wds_search_cubes", "StatCan health survey and vital statistics tables"),
            PlanStep("ckan_search_datasets", "Health Canada and PHAC data: portal='federal'"),
        ),
        (),
        ("list of hospitals", "hospital locations"),
    ),
    Topic(
        "drug_prices",
        "Prescription drug prices and pharmaceutical markets",
        (
            "drug price",
            "drug cost",
            "medicine price",
            "patented drug",
            "patented medicine",
            "pharmaceutical",
            "pmprb",
            "prix des medicaments",
            "medicaments brevetes",
            "medicament brevete",
            "pharmaceutique",
            "cepmb",
        ),
        (
            PlanStep("pmprb_list_report_tables", "PMPRB price index, price ratios, sales, R&D"),
            PlanStep("pmprb_get_report_table", "the table's figures: year and table from the list"),
            PlanStep("pmprb_search_patented_medicines", "a drug's PMPRB price review status"),
            PlanStep("cihi_search_indicators", "public drug program spending (CIHI)"),
            PlanStep("wds_search_cubes", "StatCan CPI for prescribed medicines"),
        ),
    ),
    Topic(
        "public_health",
        "Public health surveillance: respiratory viruses, overdoses, infectious disease",
        (
            "influenza",
            "flu",
            "covid",
            "rsv",
            "wastewater",
            "opioid",
            "overdose",
            "measles",
            "mpox",
            "tuberculosis",
            "vaccin*",
            "outbreak",
            "notifiable",
            "grippe",
            "rougeole",
            "surdose",
            "opioide",
            "eaux usees",
            "tuberculose",
            "eclosion",
            "vrs",
            "virus respiratoire",
            "declaration obligatoire",
        ),
        (
            PlanStep("phac_infobase_list_datasets", "PHAC Health Infobase dashboard data files"),
            PlanStep("phac_infobase_query", "filter by province, date range and column values"),
            PlanStep("ckan_search_datasets", "other PHAC open data: portal='federal'"),
        ),
        (
            (
                "Surveillance counts are provisional and revised weekly or quarterly; suppressed "
                "cells ('Suppr.', 'X', 'Mas.' in French files) are not zeros, and provinces "
                "report on different schedules."
            ),
        ),
    ),
    Topic(
        "energy",
        "Energy production, pipelines and use",
        (
            "energy",
            "oil",
            "natural gas",
            "gas production",
            "gas well",
            "oil and gas",
            "pipeline",
            "electricity",
            *_ELECTRICITY_PRICE_TERMS,
            "power demand",
            "lng",
            "wells",
            "crude",
            "energie",
            "petrole",
            "electricite",
            "puits",
            "gaz naturel",
        ),
        (
            PlanStep(
                "cer_list_datasets",
                "CER pipeline throughput, exports and tolls",
                ("pipeline", "lng", "crude"),
            ),
            PlanStep(
                "electricity_ontario_get_prices",
                "Ontario zonal electricity prices (day-ahead, real-time)",
                _ELECTRICITY_PRICE_TERMS,
            ),
            PlanStep(
                "electricity_ontario_get_hourly_demand",
                "Ontario electricity demand (IESO)",
                ("electricity", "electricite", "power demand"),
            ),
            PlanStep(
                "electricity_quebec_get_demand",
                "Quebec electricity demand (Hydro-Quebec)",
                ("electricity", "electricite", "power demand"),
            ),
            PlanStep(
                "aer_get_production_volumes_link",
                "Alberta production volumes: product='oil', 'gas'...",
                ("oil", "natural gas", "gas production", "wells", "puits", "petrole"),
            ),
            PlanStep(
                "sdmx_space_search",
                "CCEI energy information flows (efficiency, supply): query=<topic>",
            ),
            PlanStep("nrcan_energy_use_list_products", "energy use by sector and province"),
            PlanStep("wds_search_cubes", "StatCan energy supply and disposition tables"),
        ),
        (
            (
                "Electricity demand and prices cover Ontario (IESO) and Quebec (Hydro-Quebec) "
                "only; Alberta's AESO data is not covered."
            ),
        ),
    ),
    Topic(
        "environment",
        "Weather, climate and natural hazards",
        (
            "weather",
            "climate",
            "temperature",
            "precipitation",
            "rain",
            "snow",
            "air quality",
            "wildfire",
            "fire",
            "flood",
            "earthquake",
            "tide",
            "water level",
            "meteo",
            "climat",
            "precipitation",
            "qualite de l'air",
            "feu de foret",
            "incendie",
            "inondation",
            "seisme",
            "maree",
            "streamflow",
            "river",
            "riviere",
            "cours d'eau",
            "debit journalier",
            "hydrometric",
            "weather forecast",
            "previsions meteo",
        ),
        (
            PlanStep(
                "eccc_search_collections",
                "ECCC weather, climate, hydrometric, air quality: query=<topic>",
                _WEATHER_TERMS,
            ),
            PlanStep(
                "eccc_query_items",
                "observations for a station or area: collection_id from the step before",
                _WEATHER_TERMS,
            ),
            PlanStep(
                "cwfis_get_situation_report",
                "national wildfire situation and season totals",
                _FIRE_TERMS,
            ),
            PlanStep(
                "ab_wildfire_summarize_fires",
                "Alberta fires this season by status, cause and size class",
                _FIRE_TERMS,
            ),
            PlanStep(
                "ab_wildfire_get_fires",
                "Alberta fires by status, cause and size (provincial status map)",
                _FIRE_TERMS,
            ),
            PlanStep(
                "ab_wildfire_get_season_statistics", "Alberta season totals by year", _FIRE_TERMS
            ),
            PlanStep(
                "ab_wildfire_get_fire_danger",
                "Alberta fire danger rating at a point: latitude, longitude "
                "(from nrcan_geo_locate)",
                ("fire danger", "fire ban", *_FIRE_TERMS),
            ),
            PlanStep(
                "ab_wildfire_get_fire_restrictions",
                "Alberta fire bans and restrictions",
                ("fire ban", "fire restriction", "interdiction de feux"),
            ),
            PlanStep("bcgw_get_active_wildfires", "current BC wildfires", _FIRE_TERMS),
            PlanStep(
                "cwfis_get_hotspots",
                "satellite fire hotspots, last 24 hours or archive",
                _FIRE_TERMS,
            ),
            PlanStep("nrcan_nbac_query_fires", "burned area by year (national)", _FIRE_TERMS),
            PlanStep(
                "nfd_list_tables",
                "National Forestry Database fire statistics by province since 1970",
                _FIRE_TERMS,
            ),
            PlanStep(
                "cwfis_get_weather_stations", "Fire Weather Index by station or point", _FIRE_TERMS
            ),
            PlanStep(
                "earthquakes_search", "earthquakes by area and date", ("earthquake", "seisme")
            ),
            PlanStep(
                "dfo_iwls_search_stations",
                "tide station near the place: its station_code",
                _TIDE_TERMS,
            ),
            PlanStep(
                "dfo_iwls_get_water_levels",
                "tides and coastal water levels: station_code from the step before",
                _TIDE_TERMS,
            ),
        ),
        ("Use nrcan_geo_locate to turn a place name into coordinates for station searches.",),
    ),
    Topic(
        "places",
        "Place names and coordinates",
        (
            "coordinates",
            "latitude",
            "longitude",
            "geocode",
            "place name",
            "toponym*",
            "coordonnees",
            "nom de lieu",
        ),
        (
            PlanStep("nrcan_geo_locate", "coordinates of a place: query=<place name>"),
            PlanStep(
                "nrcan_geo_search_names", "official place names (Canadian Geographical Names)"
            ),
        ),
    ),
    Topic(
        "spending",
        "Government spending, procurement and finances",
        (
            "spending",
            "budget",
            "expenditure",
            "main estimates",
            "supplementary estimates",
            "budget des depenses",
            "public accounts",
            "contract",
            "procurement",
            "tender",
            "grant",
            "transfer payment",
            "depenses",
            "comptes publics",
            "marche public",
            "appel d'offres",
            "subvention",
            "contrat",
        ),
        (
            PlanStep("pbo_search_publications", "PBO costings and fiscal analysis"),
            PlanStep("gc_infobase_list_files", "Estimates, Public Accounts, program spending"),
            PlanStep("gc_infobase_query", "filter by organization and fiscal year"),
            PlanStep("ckan_search_datasets", "grants and contributions: portal='federal'"),
        ),
        ("Federal fiscal years run April to March; match them to calendar-year data explicitly.",),
    ),
    Topic(
        "legislation",
        "Bills, votes, debates and regulations",
        (
            "bill",
            "law",
            "legislation",
            "parliament*",
            "mp",
            "senate",
            "senator",
            "vote",
            "hansard",
            "debate",
            "regulation",
            "gazette",
            "projet de loi",
            "loi",
            "parlement",
            "depute",
            "senat",
            "senateur",
            "debat",
            "reglement",
        ),
        (
            PlanStep(
                "senate_list_votes",
                "Senate votes on the bill (votes only; no Senate debates or bills)",
                ("senate", "senator", "senat", "senateur"),
            ),
            PlanStep("senate_get_vote", "how each senator voted"),
            PlanStep("ourcommons_list_members", "current MPs by province, party or riding"),
            PlanStep("ourcommons_get_member_roles", "one MP's roles, committees and history"),
            PlanStep("gazette_list_issues", "resulting regulations and notices"),
        ),
        (
            (
                "House of Commons bill status, recorded votes and Hansard are not covered; "
                "check parl.ca and ourcommons.ca."
            ),
        ),
    ),
    Topic(
        "business",
        "Businesses, corporations and trademarks",
        (
            "company",
            "corporation",
            "business",
            "firm",
            "trademark",
            "incorporat*",
            "business number",
            "platform operator",
            "entreprise",
            "societe",
            "marque de commerce",
            "compagnie",
        ),
        (
            PlanStep(
                "ised_corporations_get_corporation",
                "federal corporation details: id_or_business_number (a corporation number "
                "or 9-digit BN; there is no search by name)",
                ("corporation", "incorporat*", "business number", "societe"),
            ),
            PlanStep(
                "ised_cipo_search_trademarks",
                "trademark records: search_field='trademark' (or 'owner_name') and criteria",
                ("trademark", "marque de commerce"),
            ),
            PlanStep(
                "cra_digital_economy_registry_search",
                "GST/HST-registered platform operators",
                ("platform operator",),
            ),
            PlanStep("wds_search_cubes", "business counts and dynamics by industry"),
        ),
    ),
    Topic(
        "transport",
        "Transportation and vehicle safety",
        (
            "vehicle",
            "car",
            "transit",
            "bus",
            "train",
            "traffic",
            "collision",
            "vehicule",
            "voiture",
            "autobus",
            "circulation",
            "timetable",
            "bus schedule",
            "transit schedule",
            "train schedule",
            "departure",
            "horaire",
        ),
        (
            PlanStep(
                "transit_list_agencies",
                "the agency key for the city (transit_list_national_agencies for some 100 more)",
                _TRANSIT_TERMS,
            ),
            PlanStep(
                "transit_search_stops", "stops by name: agency (key) and query", _TRANSIT_TERMS
            ),
            PlanStep(
                "transit_get_stop_departures",
                "scheduled departures: agency and stop (stop_id) on a given date",
                _TRANSIT_TERMS,
            ),
            PlanStep(
                "ets_get_service_alerts",
                "Edmonton transit, when the question is Edmonton",
                _TRANSIT_TERMS,
            ),
            PlanStep(
                "tc_recalls_search",
                "Transport Canada vehicle recalls: make, model, year_from, year_to",
                _VEHICLE_TERMS,
            ),
            PlanStep(
                "ckan_search_datasets",
                "collision and traffic datasets on provincial portals: portal='on', 'bc', 'qc'...",
                ("traffic", "collision", "circulation"),
            ),
        ),
    ),
    Topic(
        "crime",
        "Crime and public safety",
        (
            "crime",
            "police",
            "theft",
            "assault",
            "homicide",
            "public safety",
            "community safety",
            "criminalite",
            "vol",
            "agression",
            "securite",
        ),
        (
            PlanStep("wds_search_cubes", "police-reported crime by CMA (Uniform Crime Reporting)"),
            PlanStep("eps_summarize_occurrences", "Edmonton police occurrences, when Edmonton"),
            PlanStep("ckan_search_datasets", "municipal police data, e.g. portal='toronto'"),
        ),
        (),
        ("securite des produits", "avis de securite", "securite alimentaire", "vol direct"),
    ),
    Topic(
        "elections",
        "Elections and political finance",
        (
            "election",
            "candidate",
            "campaign",
            "riding",
            "electoral",
            "donation",
            "donor",
            "political contribution",
            "candidat",
            "campagne",
            "circonscription",
            "don politique",
            "dons politiques",
            "dons aux partis",
            "contributions politiques",
            "financement des partis",
            "financement politique",
        ),
        (
            PlanStep(
                "elections_financial_returns_list_elections",
                "elections with returns: the election_id",
                _FINANCE_TERMS,
            ),
            PlanStep(
                "elections_financial_returns_search_candidates",
                "a candidate's return in that election_id",
                _FINANCE_TERMS,
            ),
            PlanStep(
                "elections_results_get_table",
                "federal results by riding, 2004 to 2025: election=<year>, "
                "table='district_results', 'seats' or 'turnout'",
            ),
            PlanStep(
                "elections_provincial_get_results",
                "provincial results by riding: province='qc', 'ab', 'bc' or 'sk' "
                "(elections_provincial_list_elections lists what is covered)",
                _PROVINCIAL_TERMS,
            ),
            PlanStep(
                "elections_provincial_get_seats",
                "seats and votes by party, provincial: province as above",
                _PROVINCIAL_TERMS,
            ),
            PlanStep(
                "ckan_search_datasets",
                "poll-by-poll results: portal='federal', fq='organization:elections'",
            ),
        ),
    ),
)

CLEANTECH = Topic(
    "cleantech",
    "Clean technology and the environmental economy",
    (
        "clean technology",
        "cleantech",
        "clean tech",
        "environmental goods",
        "green economy",
        "clean energy jobs",
        "technologies propres",
        "economie verte",
    ),
    (
        # Clean Technology Data Strategy (NRCan, ISED, StatCan): its statistics
        # are the ECTPEA tables (checked 2026-09-24: 36-10-0366, -0372, -0411...).
        PlanStep(
            "wds_search_cubes", "Environmental and Clean Technology Products Economic Account"
        ),
        PlanStep(
            "ised_clean_growth_get_federal_investment", "federal cleantech investment 2016-2024"
        ),
        PlanStep("ckan_search_datasets", "clean technology use and adoption: portal='federal'"),
        PlanStep("nrcan_energy_use_list_products", "energy use by sector, for context"),
    ),
    ("ECTPEA figures are StatCan satellite-account estimates, revised with each release.",),
)
INTELLECTUAL_PROPERTY = Topic(
    "ip",
    "Patents, trademarks and industrial designs",
    (
        "patent",
        "trademark",
        "industrial design",
        "intellectual property",
        "cipo",
        "ip horizons",
        "brevet",
        "marque de commerce",
        "propriete intellectuelle",
    ),
    (
        PlanStep(
            "ised_cipo_search_trademarks",
            "search trademark records: search_field='trademark' or 'owner_name'",
            ("trademark", "marque de commerce"),
        ),
        PlanStep(
            "ised_ip_horizons_search_patents",
            "patents by owner, inventor, IPC or title",
            ("patent", "brevet"),
        ),
        PlanStep(
            "ised_ip_horizons_get_patent",
            "one patent's parties and IPC classes: patent_number",
            ("patent", "brevet"),
        ),
        PlanStep(
            "ised_ip_horizons_list_files",
            "IP Horizons bulk files: ip_type='patent', 'trademark' or 'industrial_design'",
        ),
        PlanStep("ised_ip_horizons_get_dictionary", "column meanings for those files (ip_type)"),
    ),
    ("IP Horizons researcher datasets are quarterly bulk ZIPs of pipe-delimited CSV.",),
)
COMPETITION = Topic(
    "competition",
    "Mergers, acquisitions and competition",
    (
        "merger",
        "acquisition",
        "competition bureau",
        "antitrust",
        "takeover",
        "fusions et acquisitions",
        "fusion d'entreprises",
        "fusion de societes",
        "projet de fusion",
        "bureau de la concurrence",
        "concurrence",
    ),
    (
        PlanStep("competition_bureau_search_mergers", "merger reviews and their outcomes"),
        PlanStep("rdaas_search_classifications", "NAICS codes for the industry filter"),
    ),
    ("Merger reports omit May-October 2023 and transactions parties asked to keep private.",),
)
TOPICS = (*TOPICS, CLEANTECH, INTELLECTUAL_PROPERTY, COMPETITION)

MICRODATA = Topic(
    "microdata",
    "Survey microdata (PUMFs)",
    (
        "microdata",
        "pumf",
        "public use",
        "respondent",
        "record-level",
        "microdonnees",
        "fmgd",
        "donnees d'enquete",
    ),
    (
        PlanStep("statcan_pumf_search", "find the PUMF for the survey or topic"),
        PlanStep("statcan_pumf_list_files", "the free ZIP downloads by year"),
        PlanStep("statcan_pumf_get_codebook", "variables, value codes and weights"),
        PlanStep("statcan_pumf_tabulate", "weighted totals, shares or means"),
        PlanStep(
            "statcan_surveys_search_surveys",
            "the survey's directory entry and IMDB methodology",
            ("survey", "methodology", "enquete", "methodologie"),
        ),
        PlanStep(
            "statcan_surveys_search_rdc_holdings",
            "confidential master files held in Research Data Centres",
            ("rdc", "research data centre", "master file", "fichier maitre"),
        ),
    ),
    (
        (
            "Estimates from a PUMF must use its weight variable; unweighted counts describe the "
            "sample, not the population."
        ),
    ),
)
TOPICS = (*TOPICS, MICRODATA)

RECALLS = Topic(
    "recalls",
    "Recalls and safety alerts: food, health products, consumer products",
    (
        "recall",
        "food recall",
        "drug recall",
        "vehicle recall",
        "car recall",
        "safety alert",
        "allergen",
        "listeria",
        "salmonella",
        "product safety",
        "rappel",
        "rappel d'aliment",
        "allergene",
        "avis de securite",
        "securite des produits",
    ),
    (
        PlanStep("recalls_search", "Health Canada, CFIA and Transport Canada notices"),
        PlanStep("recalls_get", "affected products, lots and what to do for one notice"),
        PlanStep(
            "recalls_summarize", "counts by year, agency, category or issue: group_by='year'..."
        ),
        PlanStep(
            "tc_recalls_search",
            "vehicle recalls: make, model, year_from and year_to",
            _VEHICLE_TERMS,
        ),
    ),
    ("Recall dates in search and counts are last-updated dates, as on the site.",),
)
TOPICS = (*TOPICS, RECALLS)


AGRICULTURE = Topic(
    "agriculture",
    "Agriculture, grain, livestock and food inspection",
    (
        "agricultur*",
        "grain",
        "wheat",
        "canola",
        "barley",
        "durum",
        "lentil",
        "crop",
        "harvest",
        "farm",
        # "forest harvest" is forestry; see AGRICULTURE's shadows.
        "livestock",
        "cattle",
        "hog",
        "slaughter",
        "dairy",
        "poultry",
        "egg",
        "animal disease",
        "avian influenza",
        "bird flu",
        "hpai",
        "reportable disease",
        "chronic wasting",
        "scrapie",
        "bovine tuberculosis",
        "bse",
        "food inspection",
        "ble",
        "cereale",
        "orge",
        "lentille",
        "legumineuse",
        "silo",
        "recolte",
        "betail",
        "abattage",
        "laitier*",
        "volaille",
        "oeuf",
        "grippe aviaire",
        "influenza aviaire",
        "maladie a declaration obligatoire",
        "maladies a declaration obligatoire",
        "maladie animale",
        "maladies animales",
        "maladie debilitante chronique",
        "tremblante",
        "tuberculose bovine",
        "inspection des aliments",
    ),
    (
        PlanStep(
            "cgc_weekly_query",
            "CGC weekly grain deliveries, stocks and terminal exports: worksheet='Primary' "
            "or 'Terminal Exports' (cgc_weekly_describe lists them)",
        ),
        PlanStep(
            "cgc_exports_query",
            "CGC monthly grain exports by destination country",
            ("export", "exportation"),
        ),
        PlanStep(
            "wds_search_cubes",
            "StatCan field crop area and production, livestock, farm income",
            ("livestock", "cattle", "hog", "farm income", "betail"),
        ),
        PlanStep(
            "ckan_search_datasets",
            "AAFC red meat, poultry, egg, dairy and horticulture market files: "
            "portal='federal', fq='organization:aafc-aac'",
        ),
        PlanStep(
            "cfia_avian_influenza",
            "CFIA avian influenza infected premises and status by province since 2021",
            ("avian influenza", "bird flu", "hpai", "grippe aviaire", "influenza aviaire"),
        ),
        PlanStep(
            "cfia_reportable_diseases",
            "CFIA yearly counts of federally reportable animal diseases, 2011 to now",
            _ANIMAL_DISEASE_TERMS,
        ),
        PlanStep(
            "cfia_disease_detections",
            "CFIA detections by date, province and species (CWD, scrapie, bovine TB, BSE)",
            _ANIMAL_DISEASE_TERMS,
        ),
        PlanStep(
            "ckan_search_datasets",
            "CFIA rabies, aquatic animal disease and food testing data: "
            "portal='federal', fq='organization:cfia-acia'",
        ),
    ),
    (
        (
            "CGC figures are thousands of tonnes by crop year (August to July); StatCan "
            "production and stocks estimates are surveys and will not equal CGC handlings."
        ),
        (
            "AAFC market files on open.canada.ca are bulk CSVs refreshed nightly; their "
            "DataStore copies are mostly gone or stale, so read the file URLs."
        ),
        (
            "CFIA yearly disease counts are herds or flocks; avian influenza premises are "
            "counted separately and can differ by one or two a year."
        ),
    ),
    ("forest harvest", "timber harvest", "harvest of wood", "recolte de bois"),
)
TOPICS = (*TOPICS, AGRICULTURE)


BANKING = Topic(
    "banking",
    "Consumer banking: credit cards, bank accounts and their fees",
    (
        "credit card",
        "bank account",
        "chequing",
        "checking account",
        "savings account",
        "bank fee",
        "banking fee",
        "nsf",
        "overdraft",
        "fcac",
        "carte de credit",
        "cartes de credit",
        "compte bancaire",
        "comptes bancaires",
        "compte-cheque",
        "compte cheque",
        "compte d'epargne",
        "comptes d'epargne",
        "frais bancaire",
        "forfait bancaire",
        "caisse populaire",
        "insuffisance de fonds",
        "cheque sans provision",
        "acfc",
    ),
    (
        PlanStep(
            "fcac_search_credit_cards",
            "cards in a province (province='ON'...): annual fee, purchase rate",
            ("credit card", "carte de credit", "cartes de credit"),
        ),
        PlanStep(
            "fcac_get_credit_card",
            "one card's other rates, income and insurance: product_id, province",
            ("credit card", "carte de credit", "cartes de credit"),
        ),
        PlanStep(
            "fcac_search_bank_accounts",
            "chequing or savings accounts and monthly fees (province='ON'...)",
        ),
        PlanStep(
            "fcac_get_bank_account",
            "one account's transaction, NSF and overdraft fees: product_id, province",
        ),
        PlanStep("boc_search_series", "Bank of Canada prime and policy rates for context"),
    ),
    (
        (
            "FCAC lists only the products institutions submit to its tools, at posted rates; "
            "it is a snapshot of today's offers, with no history."
        ),
    ),
)
TOPICS = (*TOPICS, BANKING)

# StatCan's own name for its tables, used when nothing else matches.
FALLBACK_STEPS: tuple[PlanStep, ...] = (
    PlanStep("statcan_reference_search_data", "StatCan data products on the topic"),
    PlanStep("wds_search_cubes", "StatCan tables by keyword"),
    PlanStep("ckan_search_datasets", "federal open data: portal='federal'"),
    PlanStep(
        "ckan_read_resource",
        "rows of a CSV or Excel file found there: the same portal and its resource_id",
    ),
)


DAIRY = Topic(
    "dairy",
    "Dairy supply management: milk prices, quota, production and sales",
    (
        "dairy",
        "milk",
        "butter",
        "cheese",
        "supply management",
        "milk quota",
        "marketing board",
        "lait",
        "laitier*",
        "beurre",
        "fromage",
        "gestion de l'offre",
        "matiere grasse",
        "commission canadienne du lait",
        "ccl",
    ),
    (
        PlanStep(
            "cdc_query_market_data",
            "CDC farm milk production by province and milk class sales (litres, kg, $): "
            "dataset='production', 'sales_p10', 'sales_by_region' or 'farms'",
        ),
        PlanStep("cdc_get_component_prices", "CDC special milk class component prices ($/kg)"),
        PlanStep("cdc_get_butter_support_prices", "CDC butter support price"),
        PlanStep("cdc_get_national_quota", "national milk production target (total quota)"),
        PlanStep(
            "wds_search_cubes",
            "StatCan milk production and utilization (32-10-0113-01), dairy products",
        ),
        PlanStep(
            "cdc_list_datasets", "provincial marketing boards checked and where to go instead"
        ),
    ),
    (
        (
            "Total quota is a production target in kg of butterfat, not actual production; CDC "
            "production is in litres and StatCan's milk tables in kilolitres, so convert before "
            "comparing."
        ),
        (
            "CDC component prices cover the special classes (3(d), 4(a), 4(m), 5); farm-gate "
            "blend prices are set by provincial boards and are published only as PDFs."
        ),
    ),
)
TOPICS = (*TOPICS, DAIRY)


COMMITTEES = Topic(
    "committees",
    "House of Commons committees: who sits on them",
    (
        "committee",
        "committee meeting",
        "standing committee",
        "witness",
        "testimony",
        "testified",
        "in camera",
        "comite",
        "comite permanent",
        "temoin",
        "temoign*",
        "comparution",
        "huis clos",
    ),
    (
        PlanStep("ourcommons_list_members", "find the MP and their person id"),
        PlanStep("ourcommons_get_member_roles", "the MP's committee memberships with dates"),
    ),
    (("Committee meetings, witnesses and transcripts are not covered; check ourcommons.ca."),),
)
TOPICS = (*TOPICS, COMMITTEES)

STATCAN_UPDATES = Topic(
    "statcan_updates",
    "StatCan daily updates, revisions and real-time (vintage) tables",
    (
        "delta file",
        "bulk update",
        "released today",
        "daily release",
        "what changed",
        "real-time table",
        "real time table",
        "real-time data",
        "vintage",
        "revision history",
        "historical release",
        "first release",
        "fichier delta",
        "mise a jour en bloc",
        "historique des revisions",
        "donnees en temps reel",
        "tableau en temps reel",
    ),
    (
        PlanStep("statcan_delta_list_files", "which dates have a Delta File (about 47 days kept)"),
        PlanStep("statcan_delta_list_tables", "cubes released or changed that day, with titles"),
        PlanStep("statcan_delta_read_table", "that day's rows for one productId, by range"),
        PlanStep("statcan_delta_list_real_time_tables", "the 19 revision-history (vintage) tables"),
        PlanStep(
            "wds_get_changed_series_data", "changed series since a date, when the file is huge"
        ),
    ),
    (
        (
            "A Delta File has no deletions and carries corrections the next business day; "
            "values are raw, with the scalar factor not applied."
        ),
        (
            "Only the 19 statistics with a real-time table have a revision history; the regular "
            "table shows the latest revision."
        ),
    ),
)
TOPICS = (*TOPICS, STATCAN_UPDATES)


EMISSIONS = Topic(
    "emissions",
    "Greenhouse gas emissions and air pollutants",
    (
        "greenhouse gas",
        "ghg",
        "emission",
        "carbon",
        "co2",
        "methane",
        "air pollutant",
        "black carbon",
        "gaz a effet de serre",
        "ges",
        "carbone",
        "polluant atmospherique",
    ),
    (
        PlanStep(
            "sdmx_space_search",
            "CCEI flows for the ECCC greenhouse gas inventory, projections and air pollutants: "
            "query=<topic>",
        ),
        PlanStep("sdmx_space_get_structure", "dimensions and codes of the flow found"),
        PlanStep("sdmx_space_get_data", "the series: flow and key from the steps before"),
        PlanStep("wds_search_cubes", "StatCan physical flow accounts for GHG by industry"),
    ),
    (
        (
            "The national inventory is revised every year back to 1990; cite the inventory "
            "edition with each figure."
        ),
    ),
)
_SDG_TERMS = (
    "sdg",
    "sustainable development goal",
    "2030 agenda",
    "objectifs de developpement durable",
    "objectif de developpement durable",
    "programme 2030",
)
SDG = Topic(
    "sdg",
    "Sustainable Development Goals and quality of life",
    (*_SDG_TERMS, "quality of life", "qualite de vie"),
    (
        PlanStep(
            "statcan_sdg_search_indicators",
            "indicator code: framework='canada' (national) or 'global' (UN), query=<topic>",
            _SDG_TERMS,
        ),
        PlanStep(
            "statcan_sdg_get_indicator_data",
            "the indicator's values: framework and code",
            _SDG_TERMS,
        ),
        PlanStep(
            "sdmx_space_list_flows",
            "Quality of Life framework flows: space='stcshared', agency='QOL'",
            ("quality of life", "qualite de vie"),
        ),
    ),
)
FACILITIES = Topic(
    "facilities",
    "Facilities, buildings and addresses (open databases)",
    (
        "facilit*",
        "list of hospitals",
        "list of schools",
        "school",
        "building footprint",
        "address register",
        "remoteness",
        "proximity",
        "library",
        "arena",
        "museum",
        "etablissements de sante",
        "ecole",
        "empreinte",
        "eloignement",
        "proximite",
        "bibliotheque",
    ),
    (
        PlanStep(
            "statcan_lode_list_databases",
            "LODE database keys: odhf (health), odef (schools), odsrf (sports), odcaf "
            "(culture), odb (buildings), oda (addresses), remoteness, proximity",
        ),
        PlanStep("statcan_lode_query", "rows of one database: database=<key>, province or name"),
    ),
    ("The open databases are compiled from provincial and municipal lists; coverage varies.",),
)
LOBBYING = Topic(
    "lobbying",
    "Lobbying registries",
    ("lobby", "lobbying", "lobbyist", "lobbyiste", "lobbyisme", "groupe de pression"),
    (
        PlanStep(
            "bc_lobbyists_search_registrations",
            "British Columbia registrations: query, client_name, lobbyist or firm",
        ),
        PlanStep("bc_lobbyists_search_activity_reports", "BC lobbying activity reports"),
        PlanStep(
            "bc_lobbyists_summarize_activity",
            "BC activity counts: group_by='ministry', 'client', 'subject_matter' or 'year'",
        ),
        PlanStep(
            "ckan_search_datasets",
            "federal Registry of Lobbyists extracts: portal='federal', q='lobbyists registry'",
        ),
    ),
    (
        (
            "Only the British Columbia registry has search tools; the federal registry is "
            "reached through its open-data extracts."
        ),
    ),
)
_LOCAL_REP_TERMS = (
    "mla",
    "mpp",
    "mna",
    "mayor",
    "councillor",
    "city council",
    "maire",
    "conseiller municipal",
    "representative",
)
_CABINET_TERMS = (
    "cabinet",
    "minister",
    "prime minister",
    "ministre",
    "premier ministre",
    "conseil des ministres",
)
REPRESENTATIVES = Topic(
    "representatives",
    "Elected representatives, MPs, cabinet and party standings",
    (
        *_LOCAL_REP_TERMS,
        *_CABINET_TERMS,
        "my mp",
        "who represents",
        "member of parliament",
        "party standings",
        "seats in the house",
        "postal code",
        "mon depute",
        "deputes",
        "code postal",
    ),
    (
        PlanStep(
            "represent_lookup_postcode",
            "MP, MLA and councillors for a postal code: postcode='K1A0A6'",
            ("postal code", "my mp", "who represents", "code postal", "mon depute"),
        ),
        PlanStep(
            "represent_search_representatives",
            "elected officials by name, office, district, party or level",
            _LOCAL_REP_TERMS,
        ),
        PlanStep(
            "ourcommons_list_members",
            "current MPs by province, party or riding",
            ("member of parliament", "deputes", "my mp", "mon depute"),
        ),
        PlanStep("ourcommons_get_ministry", "the federal Cabinet and portfolios", _CABINET_TERMS),
        PlanStep(
            "ourcommons_get_party_standings",
            "seats by party and province",
            ("party standings", "seats in the house"),
        ),
    ),
)
FORESTRY = Topic(
    "forestry",
    "Forests, harvest and wood supply",
    (
        "forest",
        "forestry",
        "timber",
        "logging",
        "lumber",
        "wood supply",
        "tree planting",
        "foret",
        "forestier*",
        "bois d'oeuvre",
        "reboisement",
    ),
    (
        PlanStep("nfd_list_tables", "National Forestry Database tables: the table_id"),
        PlanStep("nfd_describe_table", "columns, units and jurisdictions of that table_id"),
        PlanStep("nfd_query_table", "rows by province and year for that table_id"),
        PlanStep("wds_search_cubes", "StatCan lumber production and forestry GDP"),
    ),
    shadows=("forest fire", "feu de foret", "feux de foret"),
)
TOPICS = (*TOPICS, EMISSIONS, SDG, FACILITIES, LOBBYING, REPRESENTATIVES, FORESTRY)

# Places this server has no data for. A question naming one of them, with no
# Canadian place and nothing that crosses the border (trade, exchange rates,
# immigration), gets an out-of-scope note instead of Canadian plans.
FOREIGN_PLACES: tuple[str, ...] = (
    "united states",
    "usa",
    "america",
    "american",
    "mexico",
    "united kingdom",
    "britain",
    "england",
    "france",
    "paris",
    "germany",
    "berlin",
    "europe",
    "european union",
    "china",
    "beijing",
    "japan",
    "tokyo",
    "india",
    "australia",
    "new york",
    "california",
    "texas",
    "florida",
    "chicago",
    "los angeles",
    "brazil",
    "italy",
    "spain",
    "russia",
    "etats-unis",
    "americain*",
    "mexique",
    "royaume-uni",
    "angleterre",
    "allemagne",
    "chine",
    "japon",
    "inde",
    "australie",
    "bresil",
    "italie",
    "espagne",
    "russie",
)
# Matched on the question as typed, so "US" counts and the pronoun "us" does not.
FOREIGN_CODES: tuple[str, ...] = ("US", "USA", "UK", "EU")
CROSS_BORDER_TERMS: tuple[str, ...] = (
    *_TRADE_TERMS,
    "exchange rate",
    "taux de change",
    "dollar",
    "fx",
    "immigra*",
    "refugee",
    "refugie",
    "visitor",
    "touris*",
    "traveller",
    "border",
    "frontiere",
    "partner",
    "canada",
    "canadian",
    "canadien*",
    "federal",
)
