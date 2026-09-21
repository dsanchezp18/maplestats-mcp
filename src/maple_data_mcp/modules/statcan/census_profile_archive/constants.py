"""Constants for archived (pre-2021) Census Profile bulk downloads.

Confirmed live 2026-09-20. StatCan's 2021 Census Profile Web Data
Service (`modules/statcan/census_profile`) has no equivalent for
earlier censuses -- the full Census Profile SDMX dataflow list contains
only 2021 dataflows, confirmed by listing every dataflow the API
serves. Earlier years (2001, 2006, 2011, 2016) are archived,
server-rendered ColdFusion pages with no query API at all, but each
exposes a working, unauthenticated bulk-download resolver:

- 2016 uses `GetFile.cfm?Lang=E&FILETYPE={fmt}&GEONO={geono}` --
  confirmed live for multiple GEONO values.
- 2001/2006/2011 (CSV/TAB only) share one resolver,
  `comp_download.cfm?CTLG={catalogue}&FMT={fmt}{level_code}` -- same
  query shape, only the catalogue number and available level codes
  differ per year. Confirmed live for all three years.

1996 has no equivalent bulk-download page under this URL scheme
(`census-recensement/1996/dp-pd/prof/...` 404s) and was not further
investigated in this pass. IVT/XML formats for 2001/2006/2011 use a
*different* catalogue number and numeric FMT scheme than CSV/TAB
(confirmed live) and are not covered here -- CSV/TAB already cover the
useful, non-proprietary case (IVT is a Beyond 20/20 proprietary
format).

Geography level coverage genuinely shrinks going back in time --
2016 has 34 level/region combinations, 2011 has 14, 2006 and 2001 each
have only 5 -- this is a real property of what StatCan published for
each census, not a gap in this client.
"""

_LEGACY_BASE_URL = (
    "https://www12.statcan.gc.ca/census-recensement/2011/dp-pd/prof/details/"
    "download-telecharger/comprehensive/comp_download.cfm"
)
_2016_BASE_URL = (
    "https://www12.statcan.gc.ca/census-recensement/2016/dp-pd/prof/details/"
    "download-telecharger/comp/GetFile.cfm"
)

# year -> {"style": "geono" | "ctlg", "base_url", "catalogue" (ctlg style only),
#          "formats", "levels": {level_key: level_code}}
YEAR_CONFIG: dict[int, dict] = {
    2016: {
        "style": "geono",
        "base_url": _2016_BASE_URL,
        "formats": ["CSV", "TAB", "IVT", "XML"],
        "levels": {
            "canada_provinces_territories": "059",
            "census_metro_areas_and_agglomerations": "041",
            "cma_ca_and_census_subdivisions": "042",
            "census_subdivisions_nl": "061",
            "census_subdivisions_pe": "062",
            "census_subdivisions_ns": "063",
            "census_subdivisions_nb": "064",
            "census_subdivisions_qc": "065",
            "census_subdivisions_on": "066",
            "census_subdivisions_mb": "067",
            "census_subdivisions_sk": "068",
            "census_subdivisions_ab": "069",
            "census_subdivisions_bc": "070",
            "census_subdivisions_yt": "071",
            "census_subdivisions_nt": "072",
            "census_subdivisions_nu": "073",
            "census_divisions": "060",
            "canada_pr_cd_csd": "055",
            "canada_pr_cd_csd_da": "044",
            "canada_pr_cd_csd_da_atlantic": "044_ATLANTIC",
            "canada_pr_cd_csd_da_quebec": "044_QUEBEC",
            "canada_pr_cd_csd_da_ontario": "044_ONTARIO",
            "canada_pr_cd_csd_da_prairies": "044_PRAIRIES",
            "canada_pr_cd_csd_da_british_columbia": "044_BRITISH_COLUMBIA",
            "canada_pr_cd_csd_da_territories": "044_TERRITORIES",
            "cma_tracted_ca_and_census_tracts": "043",
            "economic_regions": "049",
            "population_centres": "048",
            "canada_pr_federal_electoral_districts": "045",
            "designated_places": "047",
            "forward_sortation_areas": "046",
            "aggregate_dissemination_areas": "050",
            "dissolved_census_subdivisions": "057",
            "health_regions": "058",
        },
    },
    2011: {
        "style": "ctlg",
        "base_url": _LEGACY_BASE_URL,
        "catalogue": "98-316-XWE2011001",
        "formats": ["CSV", "TAB"],
        "levels": {
            "canada_provinces_territories": "101",
            "census_divisions": "701",
            "census_subdivisions": "301",
            "census_metro_areas_and_agglomerations": "201",
            "census_tracts": "401",
            "federal_electoral_districts_2003": "501",
            "federal_electoral_districts_2013": "511",
            "economic_regions": "901",
            "designated_places": "1301",
            "population_centres": "801",
            "dissemination_areas": "1501",
            "dissolved_census_subdivisions": "1401",
            "forward_sortation_areas": "1601",
            "health_regions": "1701",
        },
    },
    2006: {
        "style": "ctlg",
        "base_url": _LEGACY_BASE_URL,
        "catalogue": "92-591-XE",
        "formats": ["CSV", "TAB"],
        "levels": {
            "canada_provinces_territories": "101",
            "census_divisions": "701",
            "census_subdivisions": "301",
            "census_metro_areas_and_agglomerations": "201",
            "health_regions": "1701",
        },
    },
    2001: {
        "style": "ctlg",
        "base_url": _LEGACY_BASE_URL,
        "catalogue": "93F0053XIE",
        "formats": ["CSV", "TAB"],
        "levels": {
            "canada_provinces_territories": "101",
            "census_divisions": "701",
            "census_subdivisions": "301",
            "census_metro_areas_and_agglomerations": "201",
            "health_regions": "1701",
        },
    },
}
