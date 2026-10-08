"""French text for plan_query: topic labels, step purposes, caveats and places.

Keyed by the English text in topics.py and places.py, so the curated maps
stay in one language and this file only translates. tests/test_planner.py
fails when an English string has no entry here (or no rule in fr()), so a
new step cannot reach a French plan in English. Tool names, argument names
and argument values stay as they are: the agent passes them to call_tool.
"""

from __future__ import annotations

import re

from maplestats_mcp.shared.i18n import french_text

FR: dict[str, str] = {
    # Housing
    "Housing: starts, rents, prices, mortgages": (
        "Logement : mises en chantier, loyers, prix, prêts hypothécaires"
    ),
    "CMHC starts, completions, rents and vacancy: category_level_1 and _2": (
        "Mises en chantier, achèvements, loyers et inoccupation de la SCHL : category_level_1 et _2"
    ),
    "column_field and row_field options for that category and geography": (
        "options column_field et row_field pour cette catégorie et cette géographie"
    ),
    "the table: category_level_1, category_level_2, column_field and row_field "
    "(row_field='TIMESERIES' for a series), geography_type and geography_id": (
        "le tableau : category_level_1, category_level_2, column_field et row_field "
        "(row_field='TIMESERIES' pour une série), geography_type et geography_id"
    ),
    "CMHC's published Excel tables: category='rental-market' or 'household-characteristics'": (
        "tableaux Excel publiés par la SCHL : category='rental-market' ou "
        "'household-characteristics'"
    ),
    "StatCan New Housing Price Index, building permits": (
        "Indice des prix des logements neufs et permis de bâtir de Statistique Canada"
    ),
    "Bank of Canada mortgage and policy rates": (
        "taux hypothécaires et taux directeur de la Banque du Canada"
    ),
    "CREA MLS® Home Price Index (resale prices): download link, attribution and terms only; "
    "no values, since CREA's terms forbid publishing them": (
        "Indice des prix des propriétés MLS® de l'ACI (prix de revente) : lien de "
        "téléchargement, attribution et conditions seulement; aucune valeur, car les "
        "conditions de l'ACI en interdisent la publication"
    ),
    "census shelter cost and tenure: level, geography_codes (DGUIDs from "
    "statcan_census_profile_search_geography) and characteristic_codes": (
        "frais de logement et mode d'occupation au recensement : level, geography_codes "
        "(DGUID tirés de statcan_census_profile_search_geography) et characteristic_codes"
    ),
    "CMHC reports by census metropolitan area and centre; StatCan price indexes are by CMA "
    "too, but the two define some areas differently, so name the geography each figure "
    "uses.": (
        "La SCHL publie par région métropolitaine de recensement et par centre; les indices "
        "de prix de Statistique Canada sont aussi par RMR, mais les deux sources délimitent "
        "certaines régions différemment : nommez la géographie de chaque chiffre."
    ),
    # Prices
    "Inflation and prices": "Inflation et prix",
    "latest headline CPI and change": "dernier IPC d'ensemble et sa variation",
    "CPI table by component or province (e.g. 18-10-0004)": (
        "tableau de l'IPC par composante ou par province (p. ex. 18-10-0004)"
    ),
    "Bank of Canada core inflation measures and target": (
        "mesures de l'inflation fondamentale et cible de la Banque du Canada"
    ),
    "CPI is not seasonally adjusted unless the series says so; compare year over year.": (
        "L'IPC n'est pas désaisonnalisé, sauf mention contraire dans la série; comparez "
        "d'une année à l'autre."
    ),
    # Labour
    "Jobs, unemployment and wages": "Emploi, chômage et salaires",
    "latest Labour Force Survey headline": (
        "derniers résultats principaux de l'Enquête sur la population active"
    ),
    "LFS tables by province, CMA, industry or age": (
        "tableaux de l'EPA par province, RMR, industrie ou âge"
    ),
    "Alberta dashboard tables, when the question is Alberta": (
        "tableaux du tableau de bord de l'Alberta, si la question porte sur l'Alberta"
    ),
    "Alberta dashboard series: table from the step before": (
        "séries du tableau de bord de l'Alberta : table de l'étape précédente"
    ),
    "NAICS or NOC codes to name an industry or job": (
        "codes SCIAN ou CNP pour nommer une industrie ou une profession"
    ),
    "LFS monthly estimates are survey based with sampling error; small areas use 3-month "
    "averages.": (
        "Les estimations mensuelles de l'EPA proviennent d'une enquête et comportent une "
        "erreur d'échantillonnage; les petites régions utilisent des moyennes mobiles de "
        "trois mois."
    ),
    # Rates
    "Interest rates, exchange rates and markets": "Taux d'intérêt, taux de change et marchés",
    "find the Valet series (e.g. FXUSDCAD, V39079)": (
        "trouver la série Valet (p. ex. FXUSDCAD, V39079)"
    ),
    "pull the series for the period": "extraire la série pour la période",
    # International
    "Canada compared with other countries": "Le Canada comparé à d'autres pays",
    "find the indicator code (query by words)": "trouver le code de l'indicateur (recherche par mots)",
    "Canada's series for the indicator, compared with G7 or OECD countries": (
        "la série du Canada pour l'indicateur, comparée aux pays du G7 ou de l'OCDE"
    ),
    # Economy
    "GDP, trade and industry output": "PIB, commerce et production des industries",
    "what StatCan released recently on the topic": (
        "ce que Statistique Canada a diffusé récemment sur le sujet"
    ),
    "GDP by industry, trade, retail tables": (
        "tableaux du PIB par industrie, du commerce et du commerce de détail"
    ),
    "pull the series once vectors are known": "extraire les séries une fois les vecteurs connus",
    "a table's dimensions for a filtered SDMX query: product_id from the search": (
        "dimensions d'un tableau pour une requête SDMX filtrée : product_id tiré de la recherche"
    ),
    "internal (interprovincial) trade flows: query='internal trade', space='stcshared', "
    "tenant='cith'": (
        "flux du commerce intérieur (interprovincial) : query='internal trade', "
        "space='stcshared', tenant='cith'"
    ),
    "HS code of the commodity (and cimt_search_partners for a country code)": (
        "code SH de la marchandise (et cimt_search_partners pour le code d'un pays)"
    ),
    "latest month in the trade database, as 'YYYY-MM'": (
        "dernier mois de la base de données sur le commerce, au format 'YYYY-MM'"
    ),
    "exports or imports by HS commodity, partner and province: direction='exports' or "
    "'imports', from_period and to_period ('YYYY-MM'), optional hs_code, partner": (
        "exportations ou importations par marchandise du SH, partenaire et province : "
        "direction='exports' ou 'imports', from_period et to_period ('YYYY-MM'), hs_code "
        "et partner facultatifs"
    ),
    "NAICS codes for the industry": "codes SCIAN de l'industrie",
    "Alberta dashboard, when the question is Alberta": (
        "tableau de bord de l'Alberta, si la question porte sur l'Alberta"
    ),
    # Population
    "Population, census and demographics": "Population, recensement et démographie",
    "find the census area's DGUID: level='census_subdivisions' (a municipality), "
    "'census_metro_areas' or 'canada_provinces_territories', and query=<place>": (
        "trouver le DGUID de la région de recensement : level='census_subdivisions' (une "
        "municipalité), 'census_metro_areas' ou 'canada_provinces_territories', et "
        "query=<lieu>"
    ),
    "find the characteristic code (query='median age', 'household income'...)": (
        "trouver le code de la caractéristique (query='median age', 'household income'...)"
    ),
    "2021 values: the same level, geography_codes and characteristic_codes": (
        "valeurs de 2021 : les mêmes level, geography_codes et characteristic_codes"
    ),
    "2016 values (dguid), to compare over time": (
        "valeurs de 2016 (dguid), pour comparer dans le temps"
    ),
    "2006-2016 cross-tabulations (2021: wds_)": "totalisations croisées de 2006 à 2016 (2021 : wds_)",
    "older or custom census tables in Beyond 20/20 format": (
        "tableaux de recensement anciens ou personnalisés au format Beyond 20/20"
    ),
    "2001-2016 census profile bulk files: year=2001, 2006, 2011 or 2016": (
        "fichiers complets des profils du recensement de 2001 à 2016 : year=2001, 2006, "
        "2011 ou 2016"
    ),
    "census boundary maps and geography layers: year=2021": (
        "cartes des limites et couches géographiques du recensement : year=2021"
    ),
    "quarterly population estimates and migration components (17-10-0009, 17-10-0040)": (
        "estimations trimestrielles de la population et composantes migratoires "
        "(17-10-0009, 17-10-0040)"
    ),
    "Census boundaries change between 2016 and 2021; check the area matches before comparing.": (
        "Les limites du recensement changent entre 2016 et 2021; vérifiez que la région "
        "est la même avant de comparer."
    ),
    # Immigration
    "Immigration and Express Entry": "Immigration et Entrée express",
    "find the table_id: monthly permanent residents, study and work permits, asylum claims "
    "(query='study permit'...)": (
        "trouver le table_id : résidents permanents mensuels, permis d'études et de "
        "travail, demandes d'asile (query='study permit'...)"
    ),
    "query that table_id by year_from, year_to and filters": (
        "interroger ce table_id avec year_from, year_to et des filtres"
    ),
    "Express Entry draws and CRS cutoffs": "rondes d'invitations d'Entrée express et seuils du SCG",
    "StatCan population estimates of immigrants and NPRs": (
        "estimations de Statistique Canada de la population d'immigrants et de résidents "
        "non permanents"
    ),
    # Health
    "Health system": "Système de santé",
    "CIHI indicator for the measure": "indicateur de l'ICIS pour la mesure",
    "values by province or region": "valeurs par province ou par région",
    "StatCan health survey and vital statistics tables": (
        "tableaux des enquêtes sur la santé et de la statistique de l'état civil de "
        "Statistique Canada"
    ),
    "Health Canada and PHAC data: portal='federal'": (
        "données de Santé Canada et de l'ASPC : portal='federal'"
    ),
    "Prescription drug prices and pharmaceutical markets": (
        "Prix des médicaments d'ordonnance et marchés pharmaceutiques"
    ),
    "PMPRB price index, price ratios, sales, R&D": (
        "indice des prix, ratios de prix, ventes et R-D du CEPMB"
    ),
    "the table's figures: year and table from the list": (
        "les chiffres du tableau : year et table tirés de la liste"
    ),
    "a drug's PMPRB price review status": "état de l'examen du prix d'un médicament par le CEPMB",
    "public drug program spending (CIHI)": "dépenses des régimes publics d'assurance médicaments (ICIS)",
    "StatCan CPI for prescribed medicines": "IPC des médicaments d'ordonnance de Statistique Canada",
    "Public health surveillance: respiratory viruses, overdoses, infectious disease": (
        "Surveillance de la santé publique : virus respiratoires, surdoses, maladies infectieuses"
    ),
    "PHAC Health Infobase dashboard data files": (
        "fichiers de données des tableaux de bord de l'Infobase de la santé de l'ASPC"
    ),
    "filter by province, date range and column values": (
        "filtrer par province, période et valeurs de colonne"
    ),
    "other PHAC open data: portal='federal'": "autres données ouvertes de l'ASPC : portal='federal'",
    "Surveillance counts are provisional and revised weekly or quarterly; suppressed cells "
    "('Suppr.', 'X', 'Mas.' in French files) are not zeros, and provinces report on "
    "different schedules.": (
        "Les comptes de surveillance sont provisoires et révisés chaque semaine ou chaque "
        "trimestre; les cellules supprimées ('Suppr.', 'X', 'Mas.' dans les fichiers "
        "français) ne sont pas des zéros, et les provinces déclarent selon des calendriers "
        "différents."
    ),
    # Energy
    "Energy production, pipelines and use": "Production d'énergie, pipelines et consommation",
    "CER pipeline throughput, exports and tolls": (
        "débit des pipelines, exportations et droits de la Régie de l'énergie du Canada"
    ),
    "Ontario zonal electricity prices (day-ahead, real-time)": (
        "prix zonaux de l'électricité en Ontario (veille, temps réel)"
    ),
    "Ontario electricity demand (IESO)": "demande d'électricité en Ontario (SIERE)",
    "Quebec electricity demand (Hydro-Quebec)": "demande d'électricité au Québec (Hydro-Québec)",
    "water flows at Hydro-Quebec dams and generating stations": (
        "débits aux barrages et centrales d'Hydro-Québec"
    ),
    "Alberta production volumes: product='oil', 'gas'...": (
        "volumes de production de l'Alberta : product='oil', 'gas'..."
    ),
    "CCEI energy information flows (efficiency, supply): query=<topic>": (
        "flux d'information sur l'énergie du CCIE (efficacité, approvisionnement) : query=<sujet>"
    ),
    "energy use by sector and province": "consommation d'énergie par secteur et par province",
    "StatCan energy supply and disposition tables": (
        "tableaux de l'offre et de l'utilisation de l'énergie de Statistique Canada"
    ),
    "Electricity demand and prices cover Ontario (IESO) and Quebec (Hydro-Quebec) only; "
    "Alberta's AESO data is not covered.": (
        "La demande et les prix de l'électricité ne couvrent que l'Ontario (SIERE) et le "
        "Québec (Hydro-Québec); les données de l'AESO de l'Alberta ne sont pas couvertes."
    ),
    # Weather
    "Weather, climate and natural hazards": "Météo, climat et risques naturels",
    "ECCC weather, climate, hydrometric, air quality: query=<topic>": (
        "météo, climat, données hydrométriques et qualité de l'air d'ECCC : query=<sujet>"
    ),
    "observations for a station or area: collection_id from the step before": (
        "observations pour une station ou une zone : collection_id de l'étape précédente"
    ),
    "national wildfire situation and season totals": (
        "situation nationale des feux de forêt et totaux de la saison"
    ),
    "Alberta fires this season by status, cause and size class": (
        "feux de cette saison en Alberta par état, cause et classe de superficie"
    ),
    "Alberta fires by status, cause and size (provincial status map)": (
        "feux en Alberta par état, cause et superficie (carte provinciale de la situation)"
    ),
    "Alberta season totals by year": "totaux de la saison en Alberta, par année",
    "Alberta fire danger rating at a point: latitude, longitude (from nrcan_geo_locate)": (
        "indice de danger d'incendie en Alberta à un point : latitude, longitude (tirées "
        "de nrcan_geo_locate)"
    ),
    "Alberta fire bans and restrictions": "interdictions et restrictions de feux en Alberta",
    "current BC wildfires": "feux de forêt en cours en C.-B.",
    "satellite fire hotspots, last 24 hours or archive": (
        "points chauds détectés par satellite, dernières 24 heures ou archives"
    ),
    "burned area by year (national)": "superficie brûlée par année (national)",
    "National Forestry Database fire statistics by province since 1970": (
        "statistiques sur les feux de la Base nationale de données sur les forêts, par "
        "province, depuis 1970"
    ),
    "Fire Weather Index by station or point": "Indice forêt-météo par station ou par point",
    "earthquakes by area and date": "séismes par zone et par date",
    "tide station near the place: its station_code": (
        "station marégraphique près du lieu : son station_code"
    ),
    "tides and coastal water levels: station_code from the step before": (
        "marées et niveaux d'eau côtiers : station_code de l'étape précédente"
    ),
    "Use nrcan_geo_locate to turn a place name into coordinates for station searches.": (
        "Utilisez nrcan_geo_locate pour convertir un nom de lieu en coordonnées avant de "
        "chercher une station."
    ),
    # Places
    "Place names and coordinates": "Noms de lieux et coordonnées",
    "coordinates of a place: query=<place name>": "coordonnées d'un lieu : query=<nom du lieu>",
    "official place names (Canadian Geographical Names)": (
        "noms de lieux officiels (Noms géographiques du Canada)"
    ),
    # Minerals
    "Mineral production and mining": "Production minérale et exploitation minière",
    "mineral production by commodity and province": (
        "production minérale par substance et par province"
    ),
    "one commodity across years (commodity name)": (
        "une substance au fil des années (nom de la substance)"
    ),
    # Pesticides
    "Pesticides and residue limits": "Pesticides et limites de résidus",
    "registered pesticide products": "produits antiparasitaires homologués",
    "one product by its registration_number, with ingredients": (
        "un produit par son registration_number, avec ses ingrédients"
    ),
    "maximum residue limits by chemical or food": (
        "limites maximales de résidus par produit chimique ou par aliment"
    ),
    # Border
    "Border crossing wait times": "Temps d'attente à la frontière",
    "current CBSA wait times by crossing and direction": (
        "temps d'attente actuels de l'ASFC par poste frontalier et par direction"
    ),
    # Public finance
    "Government spending, procurement and finances": (
        "Dépenses publiques, approvisionnement et finances"
    ),
    "PBO costings and fiscal analysis": "estimations de coûts et analyses financières du DPB",
    "Finance Canada monthly Fiscal Monitor issues (deficit, revenues, spending)": (
        "numéros mensuels de La revue financière de Finances Canada (déficit, revenus, dépenses)"
    ),
    "Fiscal Reference Tables: long federal and provincial series (table number for "
    "finance_frt_get_table)": (
        "Tableaux de référence financiers : longues séries fédérales et provinciales "
        "(numéro de tableau pour finance_frt_get_table)"
    ),
    "Estimates, Public Accounts, program spending": (
        "budgets des dépenses, Comptes publics, dépenses de programmes"
    ),
    "filter by organization and fiscal year": "filtrer par organisation et par exercice",
    "grants and contributions: portal='federal'": "subventions et contributions : portal='federal'",
    "Federal fiscal years run April to March; match them to calendar-year data explicitly.": (
        "L'exercice fédéral va d'avril à mars; faites-le correspondre explicitement aux "
        "données par année civile."
    ),
    # Parliament
    "Bills, votes, debates and regulations": "Projets de loi, votes, débats et règlements",
    "Senate votes on the bill (votes only; no Senate debates or bills)": (
        "votes du Sénat sur le projet de loi (votes seulement; ni débats ni projets de loi "
        "du Sénat)"
    ),
    "how each senator voted": "le vote de chaque sénateur",
    "current MPs by province, party or riding": (
        "députés actuels par province, parti ou circonscription"
    ),
    "one MP's roles, committees and history": "rôles, comités et parcours d'un député",
    "resulting regulations and notices": "règlements et avis qui en découlent",
    "House of Commons bill status, recorded votes and Hansard are not covered; check parl.ca "
    "and ourcommons.ca.": (
        "L'état des projets de loi, les votes par appel nominal et le hansard de la Chambre "
        "des communes ne sont pas couverts; consultez parl.ca et noscommunes.ca."
    ),
    # Business
    "Businesses, corporations and trademarks": "Entreprises, sociétés et marques de commerce",
    "federal corporation details: id_or_business_number (a corporation number or 9-digit "
    "BN; there is no search by name)": (
        "renseignements sur une société fédérale : id_or_business_number (numéro de société "
        "ou NE à 9 chiffres; aucune recherche par nom)"
    ),
    "trademark records: search_field='trademark' (or 'owner_name') and criteria": (
        "fiches de marques de commerce : search_field='trademark' (ou 'owner_name') et critères"
    ),
    "GST/HST-registered platform operators": (
        "exploitants de plateformes inscrits aux fins de la TPS/TVH"
    ),
    "business counts and dynamics by industry": (
        "nombre d'entreprises et dynamique des entreprises par industrie"
    ),
    # Transport
    "Transportation and vehicle safety": "Transports et sécurité des véhicules",
    "the agency key for the city (transit_list_national_agencies for some 100 more)": (
        "la clé de l'agence de la ville (transit_list_national_agencies pour une centaine d'autres)"
    ),
    "stops by name: agency (key) and query": "arrêts par nom : agency (clé) et query",
    "scheduled departures: agency and stop (stop_id) on a given date": (
        "départs prévus : agency et stop (stop_id) à une date donnée"
    ),
    "Edmonton transit, when the question is Edmonton": (
        "transport en commun d'Edmonton, si la question porte sur Edmonton"
    ),
    "BC highway closures, road work and incidents now: road, area or severity": (
        "fermetures de routes, travaux et incidents en cours en C.-B. : road, area ou severity"
    ),
    "Transport Canada vehicle recalls: make, model, year_from, year_to": (
        "rappels de véhicules de Transports Canada : make, model, year_from, year_to"
    ),
    "collision and traffic datasets on provincial portals: portal='on', 'bc', 'qc'...": (
        "jeux de données sur les collisions et la circulation des portails provinciaux : "
        "portal='on', 'bc', 'qc'..."
    ),
    # Crime
    "Crime and public safety": "Criminalité et sécurité publique",
    "police-reported crime by CMA (Uniform Crime Reporting)": (
        "crimes déclarés par la police par RMR (Programme de déclaration uniforme de la "
        "criminalité)"
    ),
    "Edmonton police occurrences, when Edmonton": (
        "événements signalés au service de police d'Edmonton, si la question porte sur Edmonton"
    ),
    "municipal police data, e.g. portal='toronto'": (
        "données des services de police municipaux, p. ex. portal='toronto'"
    ),
    # Elections
    "Elections and political finance": "Élections et financement politique",
    "elections with returns: the election_id": "élections avec rapports financiers : l'election_id",
    "a candidate's return in that election_id": (
        "le rapport financier d'un candidat pour cet election_id"
    ),
    "federal results by riding, 2004 to 2025: election=<year>, table='district_results', "
    "'seats' or 'turnout'": (
        "résultats fédéraux par circonscription, de 2004 à 2025 : election=<année>, "
        "table='district_results', 'seats' ou 'turnout'"
    ),
    "provincial results by riding: province='qc', 'ab', 'bc', 'sk' or 'mb' "
    "(elections_provincial_list_elections lists what is covered)": (
        "résultats provinciaux par circonscription : province='qc', 'ab', 'bc', 'sk' ou "
        "'mb' (elections_provincial_list_elections liste ce qui est couvert)"
    ),
    "seats and votes by party, provincial: province as above": (
        "sièges et votes par parti, au provincial : province comme ci-dessus"
    ),
    "poll-by-poll results: portal='federal', fq='organization:elections'": (
        "résultats par bureau de scrutin : portal='federal', fq='organization:elections'"
    ),
    # Clean tech
    "Clean technology and the environmental economy": (
        "Technologies propres et économie de l'environnement"
    ),
    "Environmental and Clean Technology Products Economic Account": (
        "Compte économique des produits environnementaux et de technologies propres"
    ),
    "federal cleantech investment 2016-2024": (
        "investissements fédéraux dans les technologies propres, 2016 à 2024"
    ),
    "clean technology use and adoption: portal='federal'": (
        "utilisation et adoption des technologies propres : portal='federal'"
    ),
    "energy use by sector, for context": "consommation d'énergie par secteur, pour mise en contexte",
    "ECTPEA figures are StatCan satellite-account estimates, revised with each release.": (
        "Les chiffres du CEPETP sont des estimations d'un compte satellite de Statistique "
        "Canada, révisées à chaque diffusion."
    ),
    # IP
    "Patents, trademarks and industrial designs": (
        "Brevets, marques de commerce et dessins industriels"
    ),
    "search trademark records: search_field='trademark' or 'owner_name'": (
        "chercher des fiches de marques de commerce : search_field='trademark' ou 'owner_name'"
    ),
    "patents by owner, inventor, IPC or title": "brevets par titulaire, inventeur, CIB ou titre",
    "one patent's parties and IPC classes: patent_number": (
        "parties et classes CIB d'un brevet : patent_number"
    ),
    "IP Horizons bulk files: ip_type='patent', 'trademark' or 'industrial_design'": (
        "fichiers complets d'Horizons de la PI : ip_type='patent', 'trademark' ou "
        "'industrial_design'"
    ),
    "column meanings for those files (ip_type)": "sens des colonnes de ces fichiers (ip_type)",
    "IP Horizons researcher datasets are quarterly bulk ZIPs of pipe-delimited CSV.": (
        "Les jeux de données pour chercheurs d'Horizons de la PI sont des ZIP trimestriels "
        "de CSV délimités par des barres verticales."
    ),
    # Competition
    "Mergers, acquisitions and competition": "Fusions, acquisitions et concurrence",
    "merger reviews and their outcomes": "examens de fusions et leurs résultats",
    "NAICS codes for the industry filter": "codes SCIAN pour filtrer par industrie",
    "Merger reports omit May-October 2023 and transactions parties asked to keep private.": (
        "Les rapports sur les fusions omettent mai à octobre 2023 et les transactions que "
        "les parties ont demandé de garder confidentielles."
    ),
    # PUMF
    "Survey microdata (PUMFs)": "Microdonnées d'enquête (FMGD)",
    "find the PUMF for the survey or topic": "trouver le FMGD de l'enquête ou du sujet",
    "the free ZIP downloads by year": "les téléchargements ZIP gratuits par année",
    "variables, value codes and weights": "variables, codes de valeurs et poids",
    "weighted totals, shares or means": "totaux, proportions ou moyennes pondérés",
    "the survey's directory entry and IMDB methodology": (
        "la fiche de l'enquête au répertoire et sa méthodologie dans l'IMDB"
    ),
    "confidential master files held in Research Data Centres": (
        "fichiers maîtres confidentiels conservés dans les centres de données de recherche"
    ),
    "Estimates from a PUMF must use its weight variable; unweighted counts describe the "
    "sample, not the population.": (
        "Les estimations tirées d'un FMGD doivent utiliser sa variable de pondération; les "
        "comptes non pondérés décrivent l'échantillon, pas la population."
    ),
    # Recalls
    "Recalls and safety alerts: food, health products, consumer products": (
        "Rappels et avis de sécurité : aliments, produits de santé, produits de consommation"
    ),
    "Health Canada, CFIA and Transport Canada notices": (
        "avis de Santé Canada, de l'ACIA et de Transports Canada"
    ),
    "affected products, lots and what to do for one notice": (
        "produits et lots touchés, et marche à suivre pour un avis"
    ),
    "counts by year, agency, category or issue: group_by='year'...": (
        "comptes par année, organisme, catégorie ou problème : group_by='year'..."
    ),
    "vehicle recalls: make, model, year_from and year_to": (
        "rappels de véhicules : make, model, year_from et year_to"
    ),
    "Recall dates in search and counts are last-updated dates, as on the site.": (
        "Les dates de rappel dans la recherche et les comptes sont les dates de dernière "
        "mise à jour, comme sur le site."
    ),
    # Agriculture
    "Agriculture, grain, livestock and food inspection": (
        "Agriculture, grains, bétail et inspection des aliments"
    ),
    "CGC weekly grain deliveries, stocks and terminal exports: worksheet='Primary' or "
    "'Terminal Exports' (cgc_weekly_describe lists them)": (
        "livraisons, stocks et exportations des silos terminaux de grains, hebdomadaires, de "
        "la CCG : worksheet='Primary' ou 'Terminal Exports' (cgc_weekly_describe les liste)"
    ),
    "CGC monthly grain exports by destination country": (
        "exportations mensuelles de grains de la CCG par pays de destination"
    ),
    "StatCan field crop area and production, livestock, farm income": (
        "superficie et production des grandes cultures, bétail et revenu agricole de "
        "Statistique Canada"
    ),
    "AAFC red meat, poultry, egg, dairy and horticulture market files: portal='federal', "
    "fq='organization:aafc-aac'": (
        "fichiers de marché d'AAC sur les viandes rouges, la volaille, les oeufs, les "
        "produits laitiers et l'horticulture : portal='federal', fq='organization:aafc-aac'"
    ),
    "CFIA avian influenza infected premises and status by province since 2021": (
        "lieux infectés par l'influenza aviaire et situation par province depuis 2021 (ACIA)"
    ),
    "CFIA yearly counts of federally reportable animal diseases, 2011 to now": (
        "comptes annuels de l'ACIA des maladies animales à déclaration obligatoire, de 2011 "
        "à aujourd'hui"
    ),
    "CFIA detections by date, province and species (CWD, scrapie, bovine TB, BSE)": (
        "détections de l'ACIA par date, province et espèce (MDC, tremblante, tuberculose "
        "bovine, ESB)"
    ),
    "CFIA rabies, aquatic animal disease and food testing data: portal='federal', "
    "fq='organization:cfia-acia'": (
        "données de l'ACIA sur la rage, les maladies des animaux aquatiques et les analyses "
        "d'aliments : portal='federal', fq='organization:cfia-acia'"
    ),
    "CGC figures are thousands of tonnes by crop year (August to July); StatCan production "
    "and stocks estimates are surveys and will not equal CGC handlings.": (
        "Les chiffres de la CCG sont en milliers de tonnes par campagne agricole (août à "
        "juillet); les estimations de production et de stocks de Statistique Canada "
        "proviennent d'enquêtes et ne correspondront pas aux manutentions de la CCG."
    ),
    "AAFC market files on open.canada.ca are bulk CSVs refreshed nightly; their DataStore "
    "copies are mostly gone or stale, so read the file URLs.": (
        "Les fichiers de marché d'AAC sur ouvert.canada.ca sont des CSV complets mis à jour "
        "chaque nuit; leurs copies DataStore sont pour la plupart absentes ou périmées, "
        "lisez donc les URL des fichiers."
    ),
    "CFIA yearly disease counts are herds or flocks; avian influenza premises are counted "
    "separately and can differ by one or two a year.": (
        "Les comptes annuels de maladies de l'ACIA portent sur des troupeaux ou des "
        "élevages; les lieux touchés par l'influenza aviaire sont comptés à part et peuvent "
        "différer d'un ou deux par année."
    ),
    # Banking
    "Consumer banking: credit cards, bank accounts and their fees": (
        "Services bancaires aux particuliers : cartes de crédit, comptes bancaires et frais"
    ),
    "cards in a province (province='ON'...): annual fee, purchase rate": (
        "cartes offertes dans une province (province='ON'...) : frais annuels, taux sur les achats"
    ),
    "one card's other rates, income and insurance: product_id, province": (
        "autres taux, revenu exigé et assurances d'une carte : product_id, province"
    ),
    "chequing or savings accounts and monthly fees (province='ON'...)": (
        "comptes chèques ou d'épargne et frais mensuels (province='ON'...)"
    ),
    "one account's transaction, NSF and overdraft fees: product_id, province": (
        "frais de transaction, d'insuffisance de fonds et de découvert d'un compte : "
        "product_id, province"
    ),
    "Bank of Canada prime and policy rates for context": (
        "taux préférentiel et taux directeur de la Banque du Canada, pour mise en contexte"
    ),
    "FCAC lists only the products institutions submit to its tools, at posted rates; it is a "
    "snapshot of today's offers, with no history.": (
        "L'ACFC ne présente que les produits que les institutions soumettent à ses outils, "
        "aux taux affichés; c'est un portrait des offres du jour, sans historique."
    ),
    # Dairy
    "Dairy supply management: milk prices, quota, production and sales": (
        "Gestion de l'offre laitière : prix du lait, quota, production et ventes"
    ),
    "CDC farm milk production by province and milk class sales (litres, kg, $): "
    "dataset='production', 'sales_p10', 'sales_by_region' or 'farms'": (
        "production de lait à la ferme par province et ventes par classe de lait de la CCL "
        "(litres, kg, $) : dataset='production', 'sales_p10', 'sales_by_region' ou 'farms'"
    ),
    "CDC special milk class component prices ($/kg)": (
        "prix des composants des classes spéciales de lait de la CCL ($/kg)"
    ),
    "CDC butter support price": "prix de soutien du beurre de la CCL",
    "national milk production target (total quota)": (
        "cible nationale de production de lait (quota total)"
    ),
    "StatCan milk production and utilization (32-10-0113-01), dairy products": (
        "production et utilisation du lait (32-10-0113-01) et produits laitiers de "
        "Statistique Canada"
    ),
    "provincial marketing boards checked and where to go instead": (
        "offices provinciaux de commercialisation vérifiés et où chercher à la place"
    ),
    "Total quota is a production target in kg of butterfat, not actual production; CDC "
    "production is in litres and StatCan's milk tables in kilolitres, so convert before "
    "comparing.": (
        "Le quota total est une cible de production en kg de matière grasse, pas la "
        "production réelle; la production de la CCL est en litres et les tableaux sur le "
        "lait de Statistique Canada en kilolitres : convertissez avant de comparer."
    ),
    "CDC component prices cover the special classes (3(d), 4(a), 4(m), 5); farm-gate blend "
    "prices are set by provincial boards and are published only as PDFs.": (
        "Les prix des composants de la CCL couvrent les classes spéciales (3(d), 4(a), "
        "4(m), 5); les prix mélangés à la ferme sont fixés par les offices provinciaux et "
        "publiés seulement en PDF."
    ),
    # Committees
    "House of Commons committees: who sits on them": (
        "Comités de la Chambre des communes : qui y siège"
    ),
    "find the MP and their person id": "trouver le député et son identifiant (person id)",
    "the MP's committee memberships with dates": "les comités dont le député est membre, avec les dates",
    "Committee meetings, witnesses and transcripts are not covered; check ourcommons.ca.": (
        "Les réunions, les témoins et les transcriptions des comités ne sont pas couverts; "
        "consultez noscommunes.ca."
    ),
    # Delta
    "StatCan daily updates, revisions and real-time (vintage) tables": (
        "Mises à jour quotidiennes, révisions et tableaux en temps réel (millésimes) de "
        "Statistique Canada"
    ),
    "which dates have a Delta File (about 47 days kept)": (
        "les dates qui ont un fichier delta (environ 47 jours conservés)"
    ),
    "cubes released or changed that day, with titles": "cubes diffusés ou modifiés ce jour-là, avec leurs titres",
    "that day's rows for one productId, by range": "les lignes de ce jour pour un productId, par plage",
    "the 19 revision-history (vintage) tables": "les 19 tableaux d'historique des révisions (millésimes)",
    "changed series since a date, when the file is huge": (
        "séries modifiées depuis une date, quand le fichier est très volumineux"
    ),
    "A Delta File has no deletions and carries corrections the next business day; values are "
    "raw, with the scalar factor not applied.": (
        "Un fichier delta ne contient pas de suppressions et intègre les corrections le jour "
        "ouvrable suivant; les valeurs sont brutes, sans le facteur scalaire appliqué."
    ),
    "Only the 19 statistics with a real-time table have a revision history; the regular "
    "table shows the latest revision.": (
        "Seules les 19 statistiques qui ont un tableau en temps réel ont un historique des "
        "révisions; le tableau ordinaire affiche la dernière révision."
    ),
    # GHG
    "Greenhouse gas emissions and air pollutants": (
        "Émissions de gaz à effet de serre et polluants atmosphériques"
    ),
    "CCEI flows for the ECCC greenhouse gas inventory, projections and air pollutants: "
    "query=<topic>": (
        "flux du CCIE pour l'inventaire des gaz à effet de serre, les projections et les "
        "polluants atmosphériques d'ECCC : query=<sujet>"
    ),
    "dimensions and codes of the flow found": "dimensions et codes du flux trouvé",
    "the series: flow and key from the steps before": (
        "la série : flow et key des étapes précédentes"
    ),
    "StatCan physical flow accounts for GHG by industry": (
        "comptes des flux physiques de GES par industrie de Statistique Canada"
    ),
    "The national inventory is revised every year back to 1990; cite the inventory edition "
    "with each figure.": (
        "L'inventaire national est révisé chaque année jusqu'à 1990; citez l'édition de "
        "l'inventaire avec chaque chiffre."
    ),
    # SDG
    "Sustainable Development Goals and quality of life": (
        "Objectifs de développement durable et qualité de vie"
    ),
    "indicator code: framework='canada' (national) or 'global' (UN), query=<topic>": (
        "code de l'indicateur : framework='canada' (national) ou 'global' (ONU), query=<sujet>"
    ),
    "the indicator's values: framework and code": "les valeurs de l'indicateur : framework et code",
    "Quality of Life framework flows: space='stcshared', agency='QOL'": (
        "flux du Cadre de qualité de vie : space='stcshared', agency='QOL'"
    ),
    # LODE
    "Facilities, buildings and addresses (open databases)": (
        "Établissements, bâtiments et adresses (bases de données ouvertes)"
    ),
    "LODE database keys: odhf (health), odef (schools), odsrf (sports), odcaf (culture), "
    "odb (buildings), oda (addresses), remoteness, proximity": (
        "clés des bases de données de l'EDOL : odhf (santé), odef (écoles), odsrf (sports), "
        "odcaf (culture), odb (bâtiments), oda (adresses), remoteness (éloignement), "
        "proximity (proximité)"
    ),
    "rows of one database: database=<key>, province or name": (
        "lignes d'une base de données : database=<clé>, province ou nom"
    ),
    "The open databases are compiled from provincial and municipal lists; coverage varies.": (
        "Les bases de données ouvertes sont compilées à partir de listes provinciales et "
        "municipales; la couverture varie."
    ),
    # Lobbying
    "Lobbying registries": "Registres des lobbyistes",
    "British Columbia registrations: query, client_name, lobbyist or firm": (
        "enregistrements de la Colombie-Britannique : query, client_name, lobbyist ou firm"
    ),
    "BC lobbying activity reports": "rapports d'activités de lobbying en C.-B.",
    "BC activity counts: group_by='ministry', 'client', 'subject_matter' or 'year'": (
        "comptes d'activités en C.-B. : group_by='ministry', 'client', 'subject_matter' ou 'year'"
    ),
    "federal Registry of Lobbyists extracts: portal='federal', q='lobbyists registry'": (
        "extraits du Registre des lobbyistes fédéral : portal='federal', q='lobbyists registry'"
    ),
    "Only the British Columbia registry has search tools; the federal registry is reached "
    "through its open-data extracts.": (
        "Seul le registre de la Colombie-Britannique a des outils de recherche; le registre "
        "fédéral est accessible par ses extraits de données ouvertes."
    ),
    # Representatives
    "Elected representatives, MPs, cabinet and party standings": (
        "Élus, députés, Cabinet et répartition des sièges"
    ),
    "MP, MLA and councillors for a postal code: postcode='K1A0A6'": (
        "député fédéral, député provincial et conseillers d'un code postal : postcode='K1A0A6'"
    ),
    "elected officials by name, office, district, party or level": (
        "élus par nom, fonction, circonscription, parti ou ordre de gouvernement"
    ),
    "the federal Cabinet and portfolios": "le Cabinet fédéral et les portefeuilles",
    "seats by party and province": "sièges par parti et par province",
    # Forests
    "Forests, harvest and wood supply": "Forêts, récolte et approvisionnement en bois",
    "National Forestry Database tables: the table_id": (
        "tableaux de la Base nationale de données sur les forêts : le table_id"
    ),
    "columns, units and jurisdictions of that table_id": (
        "colonnes, unités et administrations de ce table_id"
    ),
    "rows by province and year for that table_id": (
        "lignes par province et par année pour ce table_id"
    ),
    "StatCan lumber production and forestry GDP": (
        "production de bois d'oeuvre et PIB forestier de Statistique Canada"
    ),
    # Ontario Energy Board
    "Ontario Energy Board utility files: reliability (SAIDI/SAIFI), customers, "
    "scorecards, licences; query=<topic>": (
        "fichiers de la Commission de l'énergie de l'Ontario sur les services publics : "
        "fiabilité (SAIDI/SAIFI), clients, fiches de rendement, licences ; query=<sujet>"
    ),
    "Ontario utility rates or Regulated Price Plan prices: table='electricity_residential', "
    "'natural_gas_residential' or 'rpp_time_of_use'": (
        "tarifs des services publics de l'Ontario ou prix de la grille tarifaire réglementée : "
        "table='electricity_residential', 'natural_gas_residential' ou 'rpp_time_of_use'"
    ),
    # BC Ministry of Environment
    "British Columbia AQHI now and forecasts by area": (
        "cote air santé de la Colombie-Britannique, actuelle et prévue, par région"
    ),
    "BC snow weather stations (snow water equivalent, depth)": (
        "stations météorologiques de neige de la C.-B. (équivalent en eau de la neige, épaisseur)"
    ),
    "BC groundwater observation wells and their water levels": (
        "puits d'observation des eaux souterraines de la C.-B. et leurs niveaux d'eau"
    ),
    "BC provincial hydrometric gauges": "stations hydrométriques provinciales de la C.-B.",
    # ECCC Data Catalogue
    "National Pollutant Release Inventory releases by facility: year, province, substance": (
        "rejets de l'Inventaire national des rejets de polluants par installation : "
        "year, province, substance"
    ),
    "greenhouse gas emissions of large facilities: year, province, company": (
        "émissions de gaz à effet de serre des grandes installations : year, province, company"
    ),
    "ECCC Data Catalogue emissions and pollutant files: query=<topic>": (
        "fichiers du Catalogue de données d'ECCC sur les émissions et les polluants : query=<sujet>"
    ),
    # Health products
    "Drugs, natural health products, medical devices and adverse reactions": (
        "Médicaments, produits de santé naturels, instruments médicaux et réactions indésirables"
    ),
    "drug products by DIN, brand, company, ingredient or status": (
        "produits pharmaceutiques par DIN, marque, entreprise, ingrédient ou statut"
    ),
    "one drug's ingredients, schedule and status history": (
        "ingrédients, annexe et historique du statut d'un médicament"
    ),
    "licensed natural health products by name or company": (
        "produits de santé naturels homologués par nom ou entreprise"
    ),
    "medical device licences by name or company": (
        "licences d'instruments médicaux par nom ou entreprise"
    ),
    "Canada Vigilance adverse reaction reports by reaction term": (
        "rapports de réactions indésirables de Canada Vigilance par terme de réaction"
    ),
    "These are Health Canada product registers and spontaneous adverse-reaction reports, "
    "not prices or sales; a report does not prove a product caused the reaction.": (
        "Ce sont des registres de produits de Santé Canada et des rapports spontanés de "
        "réactions indésirables, non des prix ou des ventes ; un rapport ne prouve pas "
        "qu'un produit a causé la réaction."
    ),
    # Taxation
    "CRA tax statistics: T1 returns, tax filers, GST/HST, TFSA, charities": (
        "Statistiques fiscales de l'ARC : déclarations T1, contribuables, TPS/TVH, CELI, "
        "organismes de bienfaisance"
    ),
    "CRA statistics: portal='federal', fq='organization:cra-arc', query='T1 final "
    "statistics' (now titled Individual Income Tax Return Statistics)": (
        "statistiques de l'ARC : portal='federal', fq='organization:cra-arc', query='T1 final "
        "statistics' (désormais intitulées Individual Income Tax Return Statistics)"
    ),
    "rows of a CRA resource whose DataStore is active (charity lists): "
    "the same portal and its resource_id": (
        "lignes d'une ressource de l'ARC dont le DataStore est actif (listes d'organismes "
        "de bienfaisance) : le même portal et son resource_id"
    ),
    "businesses registered for the simplified GST/HST, by name or business number": (
        "entreprises inscrites au régime simplifié de la TPS/TVH, par nom ou numéro d'entreprise"
    ),
    "StatCan tables built from tax records (tax filers and dependants, family incomes)": (
        "tableaux de Statistique Canada tirés de données fiscales (déclarants et personnes "
        "à charge, revenus des familles)"
    ),
    "CRA's T1 statistics are published about two years after the tax year and are "
    "revised later; each edition is its own dataset, so compare editions with care.": (
        "Les statistiques T1 de l'ARC paraissent environ deux ans après l'année d'imposition "
        "et sont révisées par la suite ; chaque édition est un jeu de données distinct, "
        "il faut donc comparer les éditions avec prudence."
    ),
    "Check each dataset's licence before reusing it.": (
        "Vérifiez la licence de chaque jeu de données avant de le réutiliser."
    ),
    # Fallback
    "StatCan data products on the topic": "produits de données de Statistique Canada sur le sujet",
    "StatCan tables by keyword": "tableaux de Statistique Canada par mot-clé",
    "federal open data: portal='federal'": "données ouvertes fédérales : portal='federal'",
    "rows of a CSV or Excel file found there: the same portal and its resource_id": (
        "lignes d'un fichier CSV ou Excel trouvé là : le même portal et son resource_id"
    ),
    # Provinces
    "Ontario": "Ontario",
    "British Columbia": "Colombie-Britannique",
    "BC Stats Excel tables (labour, GDP, population)": (
        "tableaux Excel de BC Stats (travail, PIB, population)"
    ),
    "BC Geographic Warehouse layers: type_name": "couches du BC Geographic Warehouse : type_name",
    "Alberta": "Alberta",
    "Open Alberta Excel and CSV files": "fichiers Excel et CSV d'Open Alberta",
    "Alberta Economic Dashboard": "tableau de bord économique de l'Alberta",
    "Alberta Energy Regulator reports": "rapports de l'Alberta Energy Regulator",
    "Quebec": "Québec",
    "Institut de la statistique du Quebec tables: query=<topic>": (
        "tableaux de l'Institut de la statistique du Québec : query=<sujet>"
    ),
    "Manitoba": "Manitoba",
    "Saskatchewan": "Saskatchewan",
    "Prince Edward Island": "Île-du-Prince-Édouard",
    "Nova Scotia": "Nouvelle-Écosse",
    "New Brunswick": "Nouveau-Brunswick",
    "Newfoundland and Labrador": "Terre-Neuve-et-Labrador",
    "NL Statistics Agency Excel tables by topic": (
        "tableaux Excel de la NL Statistics Agency par sujet"
    ),
    "provincial open-data catalogue": "catalogue provincial de données ouvertes",
    "Northwest Territories": "Territoires du Nord-Ouest",
    "NWT Bureau of Statistics Excel tables (query by words)": (
        "tableaux Excel du Bureau de la statistique des T.N.-O. (recherche par mots)"
    ),
    "Yukon": "Yukon",
    "Yukon Bureau of Statistics tables": "tableaux du Bureau des statistiques du Yukon",
    "Nunavut": "Nunavut",
    "StatCan tables with Nunavut as a geography": (
        "tableaux de Statistique Canada qui ont le Nunavut comme géographie"
    ),
    # Cities whose French name differs
    "Montreal": "Montréal",
    "Quebec City": "Ville de Québec",
    "Trois-Rivieres": "Trois-Rivières",
    "Edmonton Police Service occurrences": "événements signalés au service de police d'Edmonton",
    "Edmonton Transit": "transport en commun d'Edmonton (Edmonton Transit)",
    "EPCOR drinking water quality": "qualité de l'eau potable d'EPCOR",
    "City of Vancouver open data": "données ouvertes de la Ville de Vancouver",
    "Region of Waterloo": "Région de Waterloo",
    "Halton Region": "Région de Halton",
    "Niagara Region": "Région de Niagara",
    "Greater Sudbury": "Grand Sudbury",
    "Delta (BC)": "Delta (C.-B.)",
    "Saint John (New Brunswick)": "Saint John (Nouveau-Brunswick)",
}
# The entries are typed with ordinary spaces ("x; y", "a : b"); french_text
# gives them French no-break spacing, as every French server message has.
FR = {english: french_text(french) for english, french in FR.items()}

# "search with portal='x' (...)": one rule for the many portal steps.
_SEARCH = re.compile(r"^search with (portal=.+?)(?: \((.+)\))?$")
_SEARCH_NOTES = {
    "city data; no provincial portal is covered": (
        "données municipales ; aucun portail provincial n'est couvert"
    ),
    "no Nunavut portal is covered": "aucun portail du Nunavut n'est couvert",
    "the city publishes on Donnees Quebec": "la ville publie sur Données Québec",
}
# A city's English name is its French name unless FR says otherwise.
_SAME_IN_FRENCH = re.compile(r"^[A-Z][A-Za-z.\- ]*(?: \((?:Ontario|Alberta)\))?$")

GUIDANCE_FR = tuple(
    french_text(line)
    for line in (
        (
            "Exécutez les étapes dans l'ordre pour chaque sujet ; la provenance de chaque résultat "
            "donne l'URL et la date de la source à citer."
        ),
        (
            "Avant de combiner des sources, harmonisez la géographie (province, RMR, ville), la "
            "période (année civile ou exercice, mois ou trimestre) et les unités, et signalez les "
            "écarts."
        ),
        (
            "Citez la source de chaque chiffre ; ne fusionnez pas en une seule série des chiffres de "
            "sources différentes."
        ),
        "Si une étape ne trouve rien, utilisez search_tools avec l'objet de l'étape comme requête.",
    )
)
LIMITS_FR = french_text(
    "carte organisée des sujets et des lieux ; tous les outils n'y figurent pas, utilisez "
    "search_tools pour tout ce que le plan ne couvre pas"
)


def out_of_scope_fr(foreign: str) -> str:
    return french_text(
        f"La question porte sur {foreign}, hors du Canada ; ce serveur ne contient que des "
        "données publiques canadiennes, donc aucun plan n'est proposé. Nommez un lieu "
        "canadien, ou posez une question sur le commerce, les taux de change ou la migration "
        "entre le Canada et ce pays."
    )


def fr(text: str, *, place: bool = False) -> str | None:
    """The French for a planner string, or None when there is none.

    place=True is for a place label: a city keeps its English name in French
    unless FR has another one.
    """
    if text in FR:
        return FR[text]
    match = _SEARCH.match(text)
    if match:
        portal, note = match.groups()
        if note is None:
            return f"recherche avec {portal}"
        note_fr = _SEARCH_NOTES.get(note)
        return None if note_fr is None else french_text(f"recherche avec {portal} ({note_fr})")
    if place and _SAME_IN_FRENCH.match(text):
        return text
    return None


def to_french(text: str, *, place: bool = False) -> str:
    """French for a planner string; the English when none exists (a test keeps that empty)."""
    return fr(text, place=place) or text
