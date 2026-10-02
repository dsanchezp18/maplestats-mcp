"""Curated topic map for plan_query: which sources answer which questions.

Each topic lists trigger terms (English and French, matched without
accents as whole words or prefixes of words) and the steps an agent
should take, in order, across sources. tests/test_planner.py checks
that every tool named here is registered, so a renamed tool cannot
leave a plan pointing at nothing.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PlanStep:
    tool: str
    purpose: str


@dataclass(frozen=True)
class Topic:
    key: str
    label: str
    terms: tuple[str, ...]
    steps: tuple[PlanStep, ...]
    caveats: tuple[str, ...] = ()


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
            "starts",
            "affordab",
            "dwelling",
            "condo",
            "logement",
            "loyer",
            "hypothe",
            "mises en chantier",
            "habitation",
            "inoccupation",
        ),
        (
            PlanStep(
                "cmhc_list_categories", "CMHC starts, completions, rents and vacancy by centre"
            ),
            PlanStep("cmhc_get_table_data", "pull the CMHC table for the place and period"),
            PlanStep("wds_search_cubes", "StatCan New Housing Price Index, building permits"),
            PlanStep("boc_search_series", "Bank of Canada mortgage and policy rates"),
            PlanStep("statcan_census_profile_get_data", "census shelter cost and tenure by area"),
        ),
        (
            (
                "CMHC reports by census metropolitan area and centre; StatCan price indexes are "
                "by CMA too, but the two define some areas differently, so name the geography "
                "each figure uses."
            ),
        ),
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
                "ab_economic_get_data", "Alberta dashboard series, when the question is Alberta"
            ),
            PlanStep(
                "rdaas_search_classifications", "NAICS or NOC codes to name an industry or job"
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
            "pib",
            "economie",
            "croissance",
            "exportation",
            "importation",
            "commerce",
        ),
        (
            PlanStep("statcan_daily_get_releases", "what StatCan released recently on the topic"),
            PlanStep("wds_search_cubes", "GDP by industry, trade, retail tables"),
            PlanStep("wds_get_data_from_vectors", "pull the series once vectors are known"),
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
            "demograph",
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
            PlanStep("statcan_census_profile_search_geography", "find the census area code"),
            PlanStep("statcan_census_profile_search_characteristic", "find the characteristic"),
            PlanStep("statcan_census_profile_get_data", "2021 values for the area"),
            PlanStep("statcan_census_profile_2016_get_data", "2016 values, to compare over time"),
            PlanStep("statcan_census_tables_search", "2006-2016 cross-tabulations (2021: wds_)"),
            PlanStep("borealis_search_ivt", "older or custom census tables in Beyond 20/20 format"),
            PlanStep(
                "wds_search_cubes",
                "quarterly population estimates and migration components (17-10-0009, 17-10-0040)",
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
            "immigrant",
            "resident permanent",
            "refugie",
            "permis d'etudes",
            "permis de travail",
            "entree express",
        ),
        (
            PlanStep(
                "ircc_monthly_query",
                "monthly permanent residents, study and work permits, asylum claims",
            ),
            PlanStep("ircc_list_express_entry_rounds", "Express Entry draws and CRS cutoffs"),
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
            "temps d'attente",
            "medecin",
            "infirmi",
            "urgence",
        ),
        (
            PlanStep("cihi_search_indicators", "CIHI indicator for the measure"),
            PlanStep("cihi_get_indicator_data", "values by province or region"),
            PlanStep("wds_search_cubes", "StatCan health survey and vital statistics tables"),
            PlanStep("ckan_search_datasets", "Health Canada and PHAC data: portal='federal'"),
        ),
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
            PlanStep("pmprb_get_report_table", "the table's figures by year or country"),
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
            "vaccin",
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
            "gas",
            "pipeline",
            "electricity",
            "lng",
            "wells",
            "crude",
            "energie",
            "petrole",
            "pipeline",
            "electricite",
            "puits",
            "gaz",
        ),
        (
            PlanStep("cer_list_datasets", "CER pipeline throughput, exports and tolls"),
            PlanStep("electricity_ontario_get_hourly_demand", "Ontario electricity demand (IESO)"),
            PlanStep("electricity_quebec_get_demand", "Quebec electricity demand (Hydro-Quebec)"),
            PlanStep("aer_get_production_volumes_link", "Alberta production volumes"),
            PlanStep("nrcan_energy_use_list_products", "energy use by sector and province"),
            PlanStep("wds_search_cubes", "StatCan energy supply and disposition tables"),
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
        ),
        (
            PlanStep("eccc_search_collections", "ECCC weather, climate, hydrometric, air quality"),
            PlanStep("eccc_query_items", "observations for a station or area"),
            PlanStep("nrcan_nbac_query_fires", "burned area by year (national)"),
            PlanStep("bcgw_get_active_wildfires", "current BC wildfires"),
            PlanStep("cwfis_get_hotspots", "satellite fire hotspots, last 24 hours or archive"),
            PlanStep("cwfis_get_weather_stations", "Fire Weather Index by station or point"),
            PlanStep("cwfis_get_situation_report", "national wildfire situation and season totals"),
            PlanStep("earthquakes_search", "earthquakes by area and date"),
            PlanStep("dfo_iwls_get_water_levels", "tides and coastal water levels"),
        ),
        ("Use nrcan_geo_locate to turn a place name into coordinates for station searches.",),
    ),
    Topic(
        "spending",
        "Government spending, procurement and finances",
        (
            "spending",
            "budget",
            "expenditure",
            "estimates",
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
            PlanStep("canadabuys_search_contracts", "federal contracts by supplier or buyer"),
            PlanStep("canadabuys_search_tenders", "open federal tenders"),
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
            "parliament",
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
            PlanStep("parliament_search_bills", "find the bill and its status"),
            PlanStep("parliament_get_bill", "sponsor, status and House votes"),
            PlanStep("senate_list_votes", "Senate votes on the bill"),
            PlanStep("parliament_search_hansard", "what was said about it"),
            PlanStep("gazette_list_issues", "resulting regulations and notices"),
        ),
        ("OpenParliament.ca is unofficial; confirm key facts on parl.ca.",),
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
            "incorporat",
            "platform operator",
            "entreprise",
            "societe",
            "marque de commerce",
            "compagnie",
        ),
        (
            PlanStep("ised_corporations_get_corporation", "federal corporation details"),
            PlanStep("ised_cipo_search_trademarks", "trademark records"),
            PlanStep(
                "cra_digital_economy_registry_search", "GST/HST-registered platform operators"
            ),
            PlanStep("wds_search_cubes", "business counts and dynamics by industry"),
        ),
    ),
    Topic(
        "transport",
        "Transportation and vehicle safety",
        (
            "vehicle",
            "recall",
            "car",
            "transit",
            "bus",
            "traffic",
            "collision",
            "vehicule",
            "rappel",
            "voiture",
            "autobus",
            "circulation",
            "timetable",
            "schedule",
            "horaire",
        ),
        (
            PlanStep("tc_recalls_search", "Transport Canada vehicle recalls"),
            PlanStep(
                "transit_search_stops",
                "TTC, STM, OC Transpo, Calgary, VIA Rail, GO, UP Express or BC Transit stops by name",
            ),
            PlanStep(
                "transit_get_stop_departures", "scheduled departures at a stop on a given date"
            ),
            PlanStep("ets_get_service_alerts", "Edmonton transit, when the question is Edmonton"),
            PlanStep(
                "ckan_search_datasets", "collision and traffic datasets on provincial portals"
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
            "safety",
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
            "elections",
            "candidat",
            "campagne",
            "circonscription",
            "don",
        ),
        (
            PlanStep("elections_financial_returns_list_elections", "elections with returns"),
            PlanStep("elections_financial_returns_search_candidates", "a candidate's return"),
            PlanStep("elections_results_get_table", "federal results by riding, 2004 to 2025"),
            PlanStep(
                "elections_provincial_get_results",
                "provincial results by riding: province qc, ab or bc",
            ),
            PlanStep("elections_provincial_get_seats", "seats and votes by party, provincial"),
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
        PlanStep("ised_cipo_search_trademarks", "search trademark records"),
        PlanStep("ised_ip_horizons_search_patents", "patents by owner, inventor, IPC or title"),
        PlanStep("ised_ip_horizons_get_patent", "one patent's parties and IPC classes"),
        PlanStep("ised_ip_horizons_list_files", "IP Horizons bulk patent/design/trademark files"),
        PlanStep("ised_ip_horizons_get_dictionary", "column meanings for those files"),
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
        "fusion",
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
        PlanStep("recalls_summarize", "counts by year, agency, category or issue"),
        PlanStep("tc_recalls_search", "vehicle recalls by make, model and model year"),
    ),
    ("Recall dates in search and counts are last-updated dates, as on the site.",),
)
TOPICS = (*TOPICS, RECALLS)


AGRICULTURE = Topic(
    "agriculture",
    "Agriculture, grain, livestock and food inspection",
    (
        "agricultur",
        "grain",
        "wheat",
        "canola",
        "barley",
        "durum",
        "lentil",
        "crop",
        "harvest",
        "farm",
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
        "laitier",
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
        PlanStep("cgc_weekly_query", "CGC weekly grain deliveries, stocks and terminal exports"),
        PlanStep("cgc_exports_query", "CGC monthly grain exports by destination country"),
        PlanStep("wds_search_cubes", "StatCan field crop area and production, farm income"),
        PlanStep(
            "ckan_search_datasets",
            "AAFC red meat, poultry, egg, dairy and horticulture market files: "
            "portal='federal', fq='organization:aafc-aac'",
        ),
        PlanStep(
            "cfia_reportable_diseases",
            "CFIA yearly counts of federally reportable animal diseases, 2011 to now",
        ),
        PlanStep(
            "cfia_disease_detections",
            "CFIA detections by date, province and species (CWD, scrapie, bovine TB, BSE)",
        ),
        PlanStep(
            "cfia_avian_influenza",
            "CFIA avian influenza infected premises and status by province since 2021",
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
        PlanStep("fcac_search_credit_cards", "cards in a province: annual fee, purchase rate"),
        PlanStep("fcac_get_credit_card", "one card's other rates, income and insurance"),
        PlanStep("fcac_search_bank_accounts", "chequing or savings accounts and monthly fees"),
        PlanStep("fcac_get_bank_account", "one account's transaction, NSF and overdraft fees"),
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
        "laitier",
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
            "CDC farm milk production by province and milk class sales (litres, kg, $)",
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
    "House of Commons committees: meetings, witnesses and testimony",
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
        "temoign",
        "comparution",
        "huis clos",
    ),
    (
        PlanStep("parliament_list_committees", "find the committee and its slug"),
        PlanStep("parliament_get_committee", "acronym, subcommittees and recent meetings"),
        PlanStep(
            "parliament_search_committee_meetings",
            "meetings by committee, session or date range, and which were in camera",
        ),
        PlanStep(
            "parliament_get_committee_meeting",
            "one meeting's witnesses, transcript, minutes and notice",
        ),
    ),
    (
        (
            "Committee data starts with session 39-1 (2006) and comes from OpenParliament.ca, "
            "which is unofficial; in camera meetings have no transcript."
        ),
    ),
)
TOPICS = (*TOPICS, COMMITTEES)
