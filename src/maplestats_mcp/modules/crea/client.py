"""Client for CREA's MLS® Home Price Index links. See the module docstring
for why no CREA value is read and for the file naming confirmed live.

The only request this module makes is a HEAD on the monthly zip URL (a
second one when the short month spelling misses). It never downloads the
zip and never calls the statistics site's pages or data endpoints.
"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import httpx

from maplestats_mcp.modules.crea import constants
from maplestats_mcp.modules.crea.schemas import CreaHpiLinks, CreaPage, OpenAlternative
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance
from maplestats_mcp.shared.http import new_client, send_with_retry
from maplestats_mcp.shared.i18n import french_spacing, normalize_lang
from maplestats_mcp.shared.rate_limiter import get_limiter

_LIMITER = get_limiter(
    constants.SOURCE,
    rate=constants.RATE_LIMIT_PER_SECOND,
    capacity=constants.RATE_LIMIT_CAPACITY,
)

# A HEAD needs no redirects: the zip answered 200 directly, and a missing
# month answered 404 directly (checked 2026-10-03).
_client = new_client(timeout=20.0)

_PAGE_TITLES = {
    "hpi_tool": ("MLS® HPI tool and data download", "Outil IPP MLS® et téléchargement"),
    "national_statistics": (
        "CREA national statistics (Stats Centre)",
        "Statistiques nationales de l'ACI",
    ),
    "quarterly_forecasts": ("CREA quarterly forecasts", "Prévisions trimestrielles de l'ACI"),
    "housing_market_snapshot": (
        "Housing market snapshot",
        "Aperçu du marché de l'habitation",
    ),
    "terms": ("CREA Terms of Use", "Conditions d'utilisation de l'ACI"),
}

_ATTRIBUTION = {
    "en": "Source: The Canadian Real Estate Association (CREA), MLS® Home Price Index",
    "fr": (
        "Source : l'Association canadienne de l'immeuble (ACI), Indice des prix des propriétés MLS®"
    ),
}

_TERMS = {
    "en": [
        (
            "Private, non-commercial use: you may download the content to run your own "
            "analyses, graphs and charts."
        ),
        (
            "Publishing or displaying the content, in whole or in part, including in "
            "analyses, graphs, charts, results or forecasts, needs CREA's prior written "
            "consent."
        ),
        (
            "No commercial use, resale or commercial distribution of the content or of "
            "anything derived from it."
        ),
        "CREA must be attributed as the source in any display.",
    ],
    "fr": [
        (
            "Usage privé et non commercial : vous pouvez télécharger le contenu pour faire "
            "vos propres analyses, graphiques et tableaux."
        ),
        (
            "Publier ou présenter le contenu, en tout ou en partie, y compris dans des "
            "analyses, graphiques, résultats ou prévisions, exige le consentement écrit "
            "préalable de l'ACI."
        ),
        (
            "Aucun usage commercial, revente ni distribution commerciale du contenu ou de ce "
            "qui en est tiré."
        ),
        "L'ACI doit être citée comme source dans toute présentation.",
    ],
}

_TIMING = {
    "en": (
        "Monthly, around the 15th, with CREA's national statistics release. The file is "
        "named for the release month and holds the index to the previous month "
        "(MLS_HPI_Sept_2026.zip, posted 14 September 2026, runs to August 2026)."
    ),
    "fr": (
        "Mensuel, vers le 15, avec la diffusion des statistiques nationales de l'ACI. Le "
        "fichier porte le nom du mois de diffusion et couvre jusqu'au mois précédent "
        "(MLS_HPI_Sept_2026.zip, mis en ligne le 14 septembre 2026, va jusqu'à août 2026)."
    ),
}

_ALTERNATIVES = {
    "en": [
        OpenAlternative(
            name="Statistics Canada New Housing Price Index",
            measure=(
                "Contractors' selling prices of new single-family houses of the same "
                "specification, monthly by CMA; not resale prices."
            ),
            tools=["wds_get_cube_metadata", "wds_get_data_from_cube_coord"],
            table_id="18-10-0205-01",
        ),
        OpenAlternative(
            name="Canadian Housing Statistics Program (CHSP): residential sale price",
            measure=(
                "Sale prices paid by buyers of residential property, from land and "
                "assessment records, by province or territory for occasional reference "
                "years (2018 to 2024); not an index and not monthly."
            ),
            tools=["wds_get_cube_metadata", "wds_get_full_table_download"],
            table_id="46-10-0030-01",
        ),
        OpenAlternative(
            name="CMHC housing starts and completions",
            measure="New construction activity, not prices.",
            tools=["cmhc_list_categories", "cmhc_get_table_data"],
        ),
    ],
    "fr": [
        OpenAlternative(
            name="Indice des prix des logements neufs de Statistique Canada",
            measure=(
                "Prix de vente demandés par les entrepreneurs pour des maisons neuves "
                "unifamiliales aux caractéristiques identiques, mensuel par RMR ; pas des "
                "prix de revente."
            ),
            tools=["wds_get_cube_metadata", "wds_get_data_from_cube_coord"],
            table_id="18-10-0205-01",
        ),
        OpenAlternative(
            name=(
                "Programme de la statistique du logement canadien (PSLC) : prix de vente "
                "des propriétés résidentielles"
            ),
            measure=(
                "Prix de vente payés par les acheteurs de propriétés résidentielles, "
                "tirés des registres fonciers et d'évaluation, par province ou territoire "
                "pour des années de référence occasionnelles (2018 à 2024) ; ni un indice "
                "ni une série mensuelle."
            ),
            tools=["wds_get_cube_metadata", "wds_get_full_table_download"],
            table_id="46-10-0030-01",
        ),
        OpenAlternative(
            name="Mises en chantier et achèvements de la SCHL",
            measure="Activité de construction neuve, pas des prix.",
            tools=["cmhc_list_categories", "cmhc_get_table_data"],
        ),
    ],
}

_LIMITS = {
    "en": (
        "No CREA values are returned and no CREA file is read. CREA's Terms of Use allow "
        "downloading for private, non-commercial analysis only; publishing or displaying "
        "the content needs CREA's prior written consent; commercial use is forbidden; any "
        "display must attribute CREA."
    ),
    "fr": (
        "Aucune valeur de l'ACI n'est renvoyée et aucun fichier de l'ACI n'est lu. Les "
        "conditions d'utilisation de l'ACI permettent le téléchargement pour une analyse "
        "privée et non commerciale seulement ; publier ou présenter le contenu exige le "
        "consentement écrit préalable de l'ACI ; tout usage commercial est interdit ; toute "
        "présentation doit citer l'ACI."
    ),
}


def release_month(today: date) -> tuple[int, int]:
    """(year, month) of the newest release expected to be out on `today`."""
    if today.day >= constants.RELEASE_SETTLED_DAY:
        return today.year, today.month
    if today.month == 1:
        return today.year - 1, 12
    return today.year, today.month - 1


def candidate_urls(year: int, month: int) -> list[str]:
    """The zip URL under each spelling seen live, short first; no duplicates."""
    spellings = [constants.SHORT_MONTHS[month], constants.FULL_MONTHS[month]]
    urls = [constants.ZIP_URL.format(month=name, year=year) for name in spellings]
    return list(dict.fromkeys(urls))


async def _head(url: str) -> httpx.Response | None:
    """The HEAD response, or None when the host did not answer."""
    await _LIMITER.acquire()
    try:
        return await send_with_retry(_client, "HEAD", url)
    except httpx.HTTPError:
        # A missing confirmation falls back to the HPI tool page; it is not an
        # error for a tool whose job is to point at CREA's own pages.
        return None


async def _find_zip(year: int, month: int) -> dict[str, str | int | None]:
    for url in candidate_urls(year, month):
        response = await _head(url)
        if response is None:
            break
        if response.status_code == 200:
            size = response.headers.get("content-length", "")
            return {
                "url": url,
                "last_modified": response.headers.get("last-modified"),
                "size": int(size) if size.isdigit() else None,
            }
    return {"url": None, "last_modified": None, "size": None}


async def get_hpi_links(*, lang: str = "en", today: date | None = None) -> CreaHpiLinks:
    """Links, timing, attribution and terms for CREA's MLS® HPI; no values."""
    lang = normalize_lang(lang)
    today = today or datetime.now(ZoneInfo(constants.TIMEZONE)).date()
    year, month = release_month(today)

    async def fetch() -> dict[str, str | int | None]:
        return await _find_zip(year, month)

    found, was_cached = await cached_fetch(
        f"crea:hpi-zip:{year}-{month:02d}", constants.CACHE_TTL_LINK_SECONDS, fetch
    )
    zip_url = found["url"]
    size = found["size"]
    last_modified = found["last_modified"]
    hpi_tool = constants.PAGES["hpi_tool"][lang]

    # French text takes no-break spaces before its punctuation.
    def say(text: str) -> str:
        return french_spacing(text) if lang == "fr" else text

    pages = [
        CreaPage(
            key=key,
            title=_PAGE_TITLES[key][0 if lang == "en" else 1],
            url=urls[lang],
        )
        for key, urls in constants.PAGES.items()
    ]
    return CreaHpiLinks(
        release_month=f"{year}-{month:02d}",
        zip_url=zip_url if isinstance(zip_url, str) else None,
        zip_confirmed=isinstance(zip_url, str),
        zip_last_modified=last_modified if isinstance(last_modified, str) else None,
        zip_size_bytes=size if isinstance(size, int) else None,
        download_from=zip_url if isinstance(zip_url, str) else hpi_tool,
        pages=pages,
        release_timing=say(_TIMING[lang]),
        attribution=say(_ATTRIBUTION[lang]),
        terms_summary=[say(term) for term in _TERMS[lang]],
        open_alternatives=[
            item.model_copy(update={"name": say(item.name), "measure": say(item.measure)})
            for item in _ALTERNATIVES[lang]
        ],
        provenance=make_provenance(
            source=constants.SOURCE,
            url=zip_url if isinstance(zip_url, str) else hpi_tool,
            cached=was_cached,
            schema_name="crea.CreaHpiLinks",
            freshness=say(_TIMING[lang]),
            limits=say(_LIMITS[lang]),
            licence=f"{_ATTRIBUTION[lang]}. {constants.PAGES['terms'][lang]}",
            lang=lang,
        ),
    )
