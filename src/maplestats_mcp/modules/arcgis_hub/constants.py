"""Constants for every Canadian ArcGIS Hub portal this server covers.

Every portal below was verified live (2026-09-18 to 2026-09-20) to run
the identical Hub Search API v3 and classic ArcGIS REST query API, so
one client serves all of them; the only per-portal difference is the
domain. Each portal keeps its own rate-limit bucket (`arcgis-<key>`)
so a burst against one city never throttles another.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Portal:
    domain: str
    name_en: str
    name_fr: str
    bilingual_content: bool = False
    note: str | None = None
    # See shared/arcgis.py's ArcGISHubConfig.collection. A site whose only
    # collection is "all" also lists Hub pages and apps, so its searches
    # default to `default_item_type`.
    collection: str = "dataset"
    default_item_type: str | None = None
    # False when the site's download API is broken for every item, so
    # get_dataset does not hand out dead links (rows stay queryable).
    downloads: bool = True


PORTALS: dict[str, Portal] = {
    "mb": Portal(
        "geoportal.gov.mb.ca",
        "Data MB (Manitoba)",
        "Data MB (Manitoba)",
        bilingual_content=True,
    ),
    "sk": Portal(
        "geohub.saskatchewan.ca",
        "Saskatchewan GeoHub",
        "Saskatchewan GeoHub",
        bilingual_content=True,
    ),
    "pe": Portal(
        "data.princeedwardisland.ca",
        "Prince Edward Island open-data portal",
        "Portail de données ouvertes de l'Île-du-Prince-Édouard",
        bilingual_content=True,
    ),
    "london": Portal(
        "opendata.london.ca", "City of London (Ontario) Open Data", "Ville de London (Ontario)"
    ),
    "kitchener": Portal(
        "open-kitchenergis.opendata.arcgis.com", "Kitchener GeoHub", "Kitchener GeoHub"
    ),
    "windsor": Portal(
        "open-data-portal-citywindsor.hub.arcgis.com",
        "Windsor Open Data Portal",
        "Portail de données ouvertes de Windsor",
    ),
    "saskatoon": Portal(
        "data-citysaskatoon.opendata.arcgis.com",
        "City of Saskatoon Open Data Site",
        "Site de données ouvertes de la Ville de Saskatoon",
    ),
    "victoria": Portal(
        "opendata.victoria.ca",
        "City of Victoria Open Data Portal (VicMap)",
        "Portail de données ouvertes de la Ville de Victoria",
    ),
    "surrey": Portal(
        "opendata-surrey.hub.arcgis.com",
        "City of Surrey Open Data Catalog",
        "Catalogue de données ouvertes de la Ville de Surrey",
    ),
    "ottawa": Portal(
        "open.ottawa.ca", "City of Ottawa Open Data", "Données ouvertes de la Ville d'Ottawa"
    ),
    "halifax": Portal(
        "data-hrm.hub.arcgis.com",
        "Halifax Regional Municipality (HRM) Open Data",
        "Données ouvertes de la municipalité régionale de Halifax",
    ),
    "mississauga": Portal(
        "data.mississauga.ca",
        "City of Mississauga Open Data",
        "Données ouvertes de la Ville de Mississauga",
    ),
    "peel": Portal(
        "data.peelregion.ca", "Region of Peel Open Data", "Données ouvertes de la région de Peel"
    ),
    "durham": Portal(
        "opendata.durham.ca",
        "Durham Region Open Data",
        "Données ouvertes de la région de Durham",
        note=(
            "Items point at one layer of a shared 200+-layer MapServer; leave "
            "layer_index unset so the item's own layer id is used."
        ),
    ),
    "waterloo_region": Portal(
        "rowopendata-rmw.opendata.arcgis.com",
        "Region of Waterloo Open Data",
        "Données ouvertes de la région de Waterloo",
    ),
    "metro_vancouver": Portal(
        "open-data-portal-metrovancouver.hub.arcgis.com",
        "Metro Vancouver Open Data Portal",
        "Portail de données ouvertes de Metro Vancouver",
    ),
    "york": Portal(
        "insights-york.opendata.arcgis.com",
        "York Region Open Data",
        "Données ouvertes de la région de York",
    ),
    "markham": Portal(
        "data-markham.opendata.arcgis.com",
        "City of Markham Open Data",
        "Données ouvertes de la Ville de Markham",
    ),
    "newmarket": Portal(
        "navigate-newmarket.hub.arcgis.com",
        "Town of Newmarket Open Data (NavigateNewmarket)",
        "Données ouvertes de la ville de Newmarket (NavigateNewmarket)",
    ),
    "aurora": Portal(
        "town-of-aurora-data-hub-aurora.hub.arcgis.com",
        "Town of Aurora (Ontario) Data Hub",
        "Portail de données de la ville d'Aurora (Ontario)",
        note=(
            "opendata-cityofaurora.hub.arcgis.com is Aurora, Illinois -- a "
            "different city; this portal is Aurora, Ontario."
        ),
    ),
    "medicine_hat": Portal(
        "opendata.medicinehat.ca",
        "City of Medicine Hat Open Data",
        "Données ouvertes de la ville de Medicine Hat",
    ),
    "grande_prairie": Portal(
        "opendata-cityofgp.hub.arcgis.com",
        "City of Grande Prairie Open Data",
        "Données ouvertes de la ville de Grande Prairie",
    ),
    "grande_prairie_county": Portal(
        "county-of-grande-prairie-open-data-cogp.hub.arcgis.com",
        "County of Grande Prairie Open Data",
        "Données ouvertes du comté de Grande Prairie",
        note=(
            "A separate government from the City of Grande Prairie. At least one "
            "item (Fire Permit Zones) points at a broken /arcgisadmin/ service "
            "path that answers HTTP 500 -- a portal-side metadata issue."
        ),
    ),
    "st_albert": Portal(
        "data.stalbert.ca",
        "City of St. Albert Open Data Portal",
        "Portail de données ouvertes de la ville de St. Albert",
    ),
    "lethbridge": Portal(
        "opendata.lethbridge.ca",
        "City of Lethbridge Open Data Catalogue",
        "Catalogue de données ouvertes de la ville de Lethbridge",
    ),
    "airdrie": Portal(
        "data-airdrie.opendata.arcgis.com",
        "City of Airdrie Open Data",
        "Données ouvertes de la ville d'Airdrie",
    ),
    "strathcona_county": Portal(
        "opendata-strathconacounty.hub.arcgis.com",
        "Strathcona County Open Data",
        "Données ouvertes du comté de Strathcona",
    ),
    "parkland_county": Portal(
        "opendata.parklandcounty.com",
        "Parkland County Open Data",
        "Données ouvertes du comté de Parkland",
    ),
    "sturgeon_county": Portal(
        "data-sturgeoncounty.opendata.arcgis.com",
        "Sturgeon County Atlas",
        "Atlas du comté de Sturgeon",
    ),
    "emrb": Portal(
        "emrgis.emrb.ca",
        "Edmonton Metropolitan Region Board GIS (EMRGIS)",
        "SIG de la Commission de la région métropolitaine d'Edmonton (EMRGIS)",
        note=(
            "Regional growth-plan layers for the 13 member municipalities. Also "
            "served at gis-capitalregion.opendata.arcgis.com (same 85 datasets)."
        ),
    ),
    "alberta_geological_survey": Portal(
        "geology-ags-aer.opendata.arcgis.com",
        "Alberta Geological Survey Open Data",
        "Données ouvertes de la Commission géologique de l'Alberta",
        note=(
            "Run by the Alberta Energy Regulator, like the aer_* statistical "
            "reports, but a separate platform (ArcGIS Hub, not www.aer.ca)."
        ),
    ),
    "cochrane": Portal(
        "geohub.cochrane.ca",
        "Cochrane GeoHub",
        "GeoHub de Cochrane",
        note=(
            "Town of Cochrane, Alberta. Moved from data-cochranegis.opendata.arcgis.com, "
            "whose API now refuses anonymous access (GWM_0003); the new domain answers "
            "(checked 2026-09-27)."
        ),
    ),
    "okotoks": Portal(
        "maps-okotoks.hub.arcgis.com",
        "Okotoks Open Data",
        "Données ouvertes d'Okotoks",
        note=(
            "Town of Okotoks, Alberta. Replaces okotoksmaps-okotoks.hub.arcgis.com, "
            "whose API refuses anonymous access (GWM_0003). The new site has only the "
            "'all' collection, so searches default to Feature Service (checked 2026-09-27)."
        ),
        collection="all",
        default_item_type="Feature Service",
    ),
    "oakville": Portal(
        "portal-exploreoakville.opendata.arcgis.com",
        "Town of Oakville Open Data Portal",
        "Portail de données ouvertes de la Ville d'Oakville",
        note="Halton Region, Ontario (the region itself has no open-data portal).",
    ),
    "burlington": Portal(
        "navburl-burlington.opendata.arcgis.com",
        "City of Burlington Open Data (Navigate Burlington)",
        "Données ouvertes de la Ville de Burlington (Navigate Burlington)",
        note="Halton Region, Ontario (the region itself has no open-data portal).",
    ),
    "milton": Portal(
        "discover-milton.hub.arcgis.com",
        "Town of Milton Open Data (Discover the Town of Milton)",
        "Données ouvertes de la Ville de Milton (Discover Milton)",
        note="Halton Region, Ontario (the region itself has no open-data portal).",
    ),
    "red_deer": Portal(
        "reddeer.opendata.arcgis.com",
        "City of Red Deer ArcGIS Hub",
        "Hub ArcGIS de la Ville de Red Deer",
        note=(
            "City of Red Deer AGOL org (8EWx42uKeMSu9Wcl), ~170 items: "
            "orthophotos, trails, parks, plus many Survey123 form layers. The "
            "city's curated catalogue at data.reddeer.ca is a custom ASP.NET "
            "site (no API); data-reddeer.opendata.arcgis.com returns 401. Its download "
            "API answers HTTP 500 'domain record not found' for every item (checked "
            "2026-09-27), so items carry no download links; query rows instead."
        ),
        downloads=False,
    ),
    "brampton": Portal(
        "geohub.brampton.ca",
        "City of Brampton GeoHub",
        "GeoHub de la Ville de Brampton",
        note="Peel Region, Ontario. 352 datasets confirmed live 2026-09-29 (transit GTFS, imagery, layers).",
    ),
    "kingston": Portal(
        "opendatakingston.cityofkingston.ca",
        "Open Data Kingston",
        "Données ouvertes de Kingston",
        note="Ontario. 201 datasets confirmed live 2026-09-29.",
    ),
    "kelowna": Portal(
        "opendata.kelowna.ca",
        "Open Kelowna",
        "Données ouvertes de Kelowna",
        note="British Columbia. 133 datasets confirmed live 2026-09-29.",
    ),
    "barrie": Portal(
        "opendata.barrie.ca",
        "City of Barrie Open Data",
        "Données ouvertes de la Ville de Barrie",
        note="Ontario. 113 datasets confirmed live 2026-09-29.",
    ),
    "burnaby": Portal(
        "data.burnaby.ca",
        "City of Burnaby OpenData",
        "Données ouvertes de la Ville de Burnaby",
        note="British Columbia. 66 datasets confirmed live 2026-09-29.",
    ),
    "fredericton": Portal(
        "data-fredericton.opendata.arcgis.com",
        "City of Fredericton Open Data",
        "Données ouvertes de la Ville de Fredericton",
        note="New Brunswick. 66 datasets confirmed live 2026-09-29.",
    ),
    "greater_sudbury": Portal(
        "opendata.greatersudbury.ca",
        "City of Greater Sudbury Open Data",
        "Données ouvertes du Grand Sudbury",
        note="Ontario. 50 datasets confirmed live 2026-09-29.",
    ),
    "guelph": Portal(
        "explore.guelph.ca",
        "Guelph Open Data",
        "Données ouvertes de Guelph",
        note="Ontario. 41 datasets confirmed live 2026-09-29.",
    ),
    "moncton": Portal(
        "ouvert.moncton.ca",
        "City of Moncton Open Data",
        "Données ouvertes de la Ville de Moncton",
        note="New Brunswick. 54 datasets confirmed live 2026-09-29.",
    ),
    "abbotsford": Portal(
        "opendata-abbotsford.hub.arcgis.com",
        "City of Abbotsford Open Data",
        "Données ouvertes de la Ville d'Abbotsford",
        note="British Columbia. 136 datasets confirmed live 2026-09-29.",
    ),
    "whitby": Portal(
        "geohub-whitby.hub.arcgis.com",
        "Whitby GeoHub",
        "GeoHub de Whitby",
        note="Durham Region, Ontario. 19 datasets confirmed live 2026-09-29.",
    ),
    "oshawa": Portal(
        "city-oshawa.opendata.arcgis.com",
        "City of Oshawa Open Data",
        "Données ouvertes de la Ville d'Oshawa",
        note="Durham Region, Ontario. 314 datasets confirmed live 2026-09-29.",
    ),
    "niagara_falls": Portal(
        "open.niagarafalls.ca",
        "City of Niagara Falls Open Data",
        "Données ouvertes de la Ville de Niagara Falls",
        note="Niagara Region, Ontario. 301 datasets confirmed live 2026-09-29.",
    ),
    "niagara_region": Portal(
        "open.niagararegion.ca",
        "Niagara Region Open Data",
        "Données ouvertes de la région de Niagara",
        note="Ontario. 44 datasets confirmed live 2026-09-29.",
    ),
    "st_catharines": Portal(
        "st-catharines-open-data-2-stcatharines.hub.arcgis.com",
        "St Catharines Open Data",
        "Données ouvertes de St. Catharines",
        note="Niagara Region, Ontario. 12 datasets confirmed live 2026-09-29.",
    ),
    "thunder_bay": Portal(
        "opendata.thunderbay.ca",
        "City of Thunder Bay Open Data",
        "Portail de données ouvertes de Thunder Bay",
        note="Ontario. 67 datasets confirmed live 2026-09-29.",
    ),
    "peterborough": Portal(
        "data-ptbo.opendata.arcgis.com",
        "City of Peterborough Open Data",
        "Données ouvertes SIG de Peterborough",
        note="Ontario. 94 datasets confirmed live 2026-09-29.",
    ),
    "coquitlam": Portal(
        "data.coquitlam.ca",
        "City of Coquitlam Open Data",
        "Portail de données ouvertes de Coquitlam",
        note="British Columbia. 27 datasets confirmed live 2026-09-29.",
    ),
    "saanich": Portal(
        "opendata-saanich.hub.arcgis.com",
        "Saanich Open Data",
        "Données ouvertes du district de Saanich",
        note="British Columbia. 51 datasets confirmed live 2026-09-29.",
    ),
    "kamloops": Portal(
        "mydata-kamloops.opendata.arcgis.com",
        "City of Kamloops Open Data",
        "Données ouvertes de la Ville de Kamloops",
        note="British Columbia. 156 datasets confirmed live 2026-09-29.",
    ),
    "prince_george": Portal(
        "data-cityofpg.opendata.arcgis.com",
        "City of Prince George Open Data",
        "Données ouvertes de Prince George",
        note="British Columbia. 175 datasets confirmed live 2026-09-29.",
    ),
    "delta": Portal(
        "opendata-deltabc.hub.arcgis.com",
        "City of Delta Open Data",
        "Données ouvertes de la Ville de Delta",
        note="British Columbia. 16 datasets confirmed live 2026-10-02; Open Government Licence.",
    ),
    "yellowknife": Portal(
        "opendata.yellowknife.ca",
        "City of Yellowknife Open Data Portal",
        "Portail de données ouvertes de la Ville de Yellowknife",
        note="Northwest Territories. 6 datasets confirmed live 2026-10-02 (boundary, roads, zoning, civic addresses); the city's Open Data Licence v1 allows commercial reuse with attribution.",
    ),
    "cambridge": Portal(
        "opendata-cityofcambridge.hub.arcgis.com",
        "City of Cambridge (Ontario) GeoHub",
        "GeoHub de la Ville de Cambridge (Ontario)",
        note="Waterloo Region, Ontario. 48 datasets confirmed live 2026-10-02; the city's Open Data Licence v2.1 allows commercial reuse with attribution.",
    ),
    "maple_ridge": Portal(
        "gis-mapleridge.opendata.arcgis.com",
        "City of Maple Ridge Open Data",
        "Données ouvertes de la Ville de Maple Ridge",
        note="British Columbia. 61 datasets confirmed live 2026-10-02 (aerial photography, GIS layers); Open Government Licence. A second site, opengov2-mapleridge.opendata.arcgis.com, lists 88.",
    ),
    "pickering": Portal(
        "data-cityofpickering.hub.arcgis.com",
        "City of Pickering Open Data",
        "Données ouvertes de la Ville de Pickering",
        note="Durham Region, Ontario. 268 datasets confirmed live 2026-10-02, many of them Central Lake Ontario Conservation layers; City of Pickering Open Data Licence v1 allows commercial reuse.",
    ),
    "sarnia": Portal(
        "city-of-sarnia.hub.arcgis.com",
        "City of Sarnia GeoHub",
        "GeoHub de la Ville de Sarnia",
        note="Ontario. 14 datasets confirmed live 2026-10-02; licence based on the Open Government Licence - Canada 2.0.",
    ),
    "saint_john": Portal(
        "catalogue-saintjohn.opendata.arcgis.com",
        "City of Saint John Open Data Catalogue",
        "Catalogue de données ouvertes de la Ville de Saint John",
        note="New Brunswick (Saint John, not St. John's). 233 datasets confirmed live 2026-10-02; titles are bilingual; Open Government Licence - City of Saint John.",
        bilingual_content=True,
    ),
    "port_moody": Portal(
        "data.portmoody.ca",
        "City of Port Moody Open Data",
        "Données ouvertes de la Ville de Port Moody",
        note="British Columbia. 104 datasets confirmed live 2026-10-02; the city's licence allows commercial reuse with attribution.",
    ),
    "white_rock": Portal(
        "data.whiterockcity.ca",
        "City of White Rock Open Data Portal",
        "Portail de données ouvertes de la Ville de White Rock",
        note="British Columbia. 59 datasets confirmed live 2026-10-02; White Rock Open Government License.",
    ),
    "penticton": Portal(
        "open.penticton.ca",
        "City of Penticton Open Data (Open Penticton)",
        "Données ouvertes de la Ville de Penticton",
        note="British Columbia. 136 datasets confirmed live 2026-10-02; City of Penticton Open Government Licence.",
    ),
    "orangeville": Portal(
        "open-orangeville.hub.arcgis.com",
        "Town of Orangeville Open Data",
        "Données ouvertes de la Ville d'Orangeville",
        note="Ontario. 18 datasets confirmed live 2026-10-02; Open Government Licence - Orangeville.",
    ),
    "canmore": Portal(
        "opendata-canmore.opendata.arcgis.com",
        "Town of Canmore Open Data Portal",
        "Portail de données ouvertes de la Ville de Canmore",
        note="Alberta. 19 datasets confirmed live 2026-10-02; Town of Canmore Open Data Licence.",
    ),
    "toronto_police": Portal(
        "data.torontopolice.on.ca",
        "Toronto Police Service Public Safety Data Portal",
        "Portail de données sur la sécurité publique du Service de police de Toronto",
        note="Ontario. 71 datasets confirmed live 2026-09-30 (reported crimes, shootings, victims, personnel, budget). The older torontops.hub.arcgis.com lists 111 items, mostly map layers.",
    ),
    "ottawa_police": Portal(
        "data.ottawapolice.ca",
        "Ottawa Police Service Community Safety Data Portal",
        "Portail de données sur la sécurité communautaire du Service de police d'Ottawa",
        note="Ontario. Only the 'all' collection exists (98 items, mostly PDFs and pages), so searches default to Feature Service (13 layers: hate crime, shootings, bike theft, overdose calls). Checked 2026-09-30.",
        collection="all",
        default_item_type="Feature Service",
    ),
    "conservation_halton": Portal(
        "conservationhalton-camaps.opendata.arcgis.com",
        "Conservation Halton Open Data",
        "Données ouvertes de Conservation Halton",
        note="Conservation authority, Ontario. 36 datasets confirmed live 2026-09-30.",
    ),
    "credit_valley": Portal(
        "cvc-camaps.opendata.arcgis.com",
        "Credit Valley Conservation Open Data Hub",
        "Carrefour de données ouvertes de Credit Valley Conservation",
        note="Conservation authority, Ontario. Only 2 datasets confirmed live 2026-09-30.",
    ),
    "npca": Portal(
        "gis-npca-camaps.opendata.arcgis.com",
        "Niagara Peninsula Conservation Authority Open Data",
        "Données ouvertes de l'Office de protection de la nature de la péninsule de Niagara",
        note="Conservation authority, Ontario. 31 datasets confirmed live 2026-09-30.",
    ),
    "hamilton_conservation": Portal(
        "hca-open-data-camaps.hub.arcgis.com",
        "Hamilton Conservation Authority Open Data",
        "Données ouvertes de l'Office de protection de la nature de Hamilton",
        note="Ontario. 31 datasets confirmed live 2026-09-30.",
    ),
    "cloca": Portal(
        "cloca-camaps.opendata.arcgis.com",
        "Central Lake Ontario Conservation Authority Open Data",
        "Données ouvertes de l'Office de protection de la nature du centre du lac Ontario",
        note="Ontario. 27 datasets confirmed live 2026-09-30.",
    ),
    "quinte_conservation": Portal(
        "data.quinteconservation.ca",
        "Quinte Conservation Authority Open Data",
        "Données ouvertes de l'Office de protection de la nature de Quinte",
        note="Ontario. 14 datasets confirmed live 2026-09-30.",
    ),
    "ontario_geohub": Portal(
        "ontariogeohub-lio.opendata.arcgis.com",
        "Ontario GeoHub (Land Information Ontario)",
        "Géoportail de l'Ontario (Information sur les terres de l'Ontario)",
        note="Provincial geospatial data, Ontario. 242 datasets confirmed live 2026-09-30; titles are bilingual.",
        bilingual_content=True,
    ),
    "parks_canada": Portal(
        "data-apca.opendata.arcgis.com",
        "Parks Canada Open Data",
        "Données ouvertes de Parcs Canada",
        note="Federal. 25 datasets confirmed live 2026-09-30 (trails, protected places); titles are bilingual.",
        bilingual_content=True,
    ),
}

RATE_LIMIT_PER_SECOND = 2.0
RATE_LIMIT_CAPACITY = 5.0

CACHE_TTL_SEARCH_SECONDS = 10 * 60
CACHE_TTL_ITEM_SECONDS = 60 * 60
CACHE_TTL_ROWS_SECONDS = 5 * 60

SEARCH_LIMIT_DEFAULT = 10
SEARCH_LIMIT_MAX = 100
ROWS_LIMIT_DEFAULT = 10
ROWS_LIMIT_MAX = 1000
DESCRIPTION_EXCERPT_LENGTH = 300


def rate_limit_source(portal: str) -> str:
    return f"arcgis-{portal.replace('_', '-')}"


def landing_page_url(portal: str) -> str:
    return f"https://{PORTALS[portal].domain}/datasets/"
