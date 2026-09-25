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
    "hamilton": Portal("open.hamilton.ca", "Open Hamilton", "Open Hamilton"),
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
    "red_deer": Portal(
        "reddeer.opendata.arcgis.com",
        "City of Red Deer ArcGIS Hub",
        "Hub ArcGIS de la Ville de Red Deer",
        note=(
            "City of Red Deer AGOL org (8EWx42uKeMSu9Wcl), ~170 items: "
            "orthophotos, trails, parks, plus many Survey123 form layers. The "
            "city's curated catalogue at data.reddeer.ca is a custom ASP.NET "
            "site (no API); data-reddeer.opendata.arcgis.com returns 401."
        ),
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
