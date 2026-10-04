"""HTTP client for Canadian Dairy Commission (CDC) data.

Sources, all fetched live on 2026-09-26:

- Special milk class component prices: one static CSV per year at
  cdc-ccl.ca/sites/default/files/pricing/pricing_history_<year>.csv,
  2002 onward (2001 and 2027 answer HTTP 404 with an HTML page). The
  site's download form only sets a cookie pointing at this file.
- The butter support price table (node 720), the yearly national milk
  production target (total quota) pages listed on node 653, and the
  Harmonized Milk Classification System tables (node 717): HTML tables.
- CDC market data (production by province, milk class sales, farms
  shipping milk): one bilingual CSV on AAFC's open-data server, listed
  on open.canada.ca under the Open Government Licence - Canada.

Quirks confirmed live and handled here:

1. Component price rows are unsorted, and a price the CDC does not set
   is written as 0 or left blank: 4(m) and (until 2024) 4(a) butterfat
   follow provincial prices, and the 4(a) solids-non-fat prices are
   posted around the 5th of the following month, so the current year's
   file carries 0 for recent 4(a) protein and other solids and for
   months not yet announced. Both become None.
2. Effective dates carry a time ("2025-01-01 00:00:00").
3. The French support price page writes decimals as "10, 5662"; the
   figures are identical in both languages, so values are read from the
   English page. With lang="fr" the row labels come from the French page
   ("2024 (mai)"), used only when its rows line up with the English ones.
4. Total quota pages changed layout over time: 2017-2019 label months
   "December 2019" (2019 has a French "Mars 2019" on the English page),
   2020 onward write only the month; 2018 is split into two tables
   ("before" and "since August 2018") and has no December; the 2023
   page publishes March as "34,889,4085", which is kept as text with a
   None value rather than guessed. Tables have a placeholder caption
   ("Caption text").
5. The milk class table uses rowspan for class 4(a), whose products sit
   in rows with a single cell, and puts footnote links in <sup> tags.
6. The market data file has province codes only for production and
   farms, East/West regions only for regional sales, and no class
   totals, so filtering never double counts a class.
"""

from __future__ import annotations

import calendar
import re
from datetime import date, datetime
from typing import Any
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup, Tag

from maplestats_mcp.modules.cdc import constants
from maplestats_mcp.modules.cdc.schemas import (
    CdcCatalogue,
    ComponentPrice,
    ComponentPriceResult,
    DatasetInfo,
    MarketDataResult,
    MarketDataRow,
    MarketDataset,
    MarketSegment,
    MilkClass,
    MilkClassResult,
    QuotaMonth,
    QuotaResult,
    RelatedSource,
    SupportPrice,
    SupportPriceResult,
)
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.csv_files import Columns, fetch_rows
from maplestats_mcp.shared.envelope import make_provenance
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable
from maplestats_mcp.shared.fr_typography import fr_or_en, french_spacing, lang_error
from maplestats_mcp.shared.http import get_raw
from maplestats_mcp.shared.licences_fr import licence_for_lang
from maplestats_mcp.shared.rate_limiter import get_limiter

_LIMITER = get_limiter(
    constants.RATE_LIMIT_SOURCE,
    rate=constants.RATE_LIMIT_PER_SECOND,
    capacity=constants.RATE_LIMIT_CAPACITY,
)

COMPONENT_CLASS_CODES = ("3D", "4A", "4M", "5A", "5B", "5C")

_MONTHS = {
    "jan": 1,
    "feb": 2,
    "fev": 2,
    "fév": 2,
    "mar": 3,
    "apr": 4,
    "avr": 4,
    "may": 5,
    "mai": 5,
    "jun": 6,
    "juin": 6,
    "jul": 7,
    "juil": 7,
    "aug": 8,
    "aou": 8,
    "aoû": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
    "déc": 12,
}


def _lang(lang: str) -> str:
    if lang not in ("en", "fr"):
        raise InvalidInput(f"cdc: lang must be 'en' or 'fr', got {lang!r}.")
    return lang


def _fr(lang: str, texts: list[str]) -> list[str]:
    """`texts` with French spacing for lang="fr" (the French strings here use plain spaces)."""
    return [french_spacing(t) for t in texts] if lang == "fr" else texts


def _provenance(lang: str, url: str, **fields: Any):
    """make_provenance for the CDC, with the licence and reproduce note in `lang`."""
    return make_provenance(
        source=constants.RATE_LIMIT_SOURCE,
        url=url,
        licence=licence_for_lang(constants.RATE_LIMIT_SOURCE, url, lang),
        lang=lang,
        **fields,
    )


def _today() -> date:
    return datetime.now(ZoneInfo(constants.REFERENCE_TZ)).date()


def month_number(text: str) -> int | None:
    """Month from an English or French name or abbreviation ('Sept.', 'Mars', 'févr.')."""
    word = text.strip().lower().rstrip(".")
    if word.startswith(("juin", "juil")):
        return _MONTHS[word[:4]]
    return _MONTHS.get(word[:3])


def normalize_class(text: str) -> str:
    """'Class 3(d)', '3 (d)', '3d' -> '3D'; '1(a) 1' -> '1A1'; 'Classe 5B/C/D' -> '5B/C/D'."""
    value = re.sub(r"[\s()]", "", text).upper()
    for prefix in ("CLASSE", "CLASS"):
        value = value.removeprefix(prefix)
    return value


def class_label(code: str) -> str:
    """'5A' -> '5(a)', the way the CDC writes classes on its pages."""
    return f"{code[0]}({code[1:].lower()})" if len(code) > 1 else code


def _price(text: str | None) -> float | None:
    value = (text or "").strip()
    if not value:
        return None
    try:
        number = float(value)
    except ValueError:
        return None
    return None if number == 0 else number


def _clean_text(node: Tag) -> str:
    for sup in node.find_all("sup"):
        sup.decompose()
    return " ".join(node.get_text(" ").split())


async def _page(url: str, lang: str = "en") -> tuple[str, bool]:
    async def fetch() -> str:
        await _LIMITER.acquire()
        try:
            response = await get_raw(url, timeout=60.0)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status == 404:
                raise lang_error(
                    NotFound, lang, f"cdc: no page at {url}.", f"cdc : aucune page à {url}."
                ) from exc
            raise lang_error(
                UpstreamError,
                lang,
                f"cdc: {url} returned HTTP {status}.",
                f"cdc : {url} a renvoyé HTTP {status}.",
            ) from exc
        except httpx.HTTPError as exc:
            raise lang_error(
                UpstreamUnavailable,
                lang,
                f"cdc: {url} did not respond in time.",
                f"cdc : {url} n'a pas répondu à temps.",
            ) from exc
        if len(response.content) > constants.MAX_PAGE_BYTES:
            raise lang_error(
                UpstreamError,
                lang,
                f"cdc: {url} is larger than expected.",
                f"cdc : {url} est plus volumineux que prévu.",
            )
        return response.text

    return await cached_fetch(f"cdc:page:{url}", constants.PAGE_TTL_SECONDS, fetch)


def _main(page: str) -> Tag:
    soup = BeautifulSoup(page, "html.parser")
    main = soup.find("main")
    return main if isinstance(main, Tag) else soup


# ---------------------------------------------------------------------------
# Catalogue
# ---------------------------------------------------------------------------

_DATASETS: list[dict[str, Any]] = [
    {
        "key": "component_prices",
        "tool": "cdc_get_component_prices",
        "format": "csv",
        "url": constants.COMPONENT_PRICES_PAGE,
        "title": {
            "en": "Special milk class component prices",
            "fr": "Prix des composants du lait des classes spéciales",
        },
        "description": {
            "en": "Monthly $/kg prices for butterfat, protein and other solids in classes "
            "3(d), 4(a), 4(m), 5(a), 5(b) and 5(c), set or announced by the CDC.",
            "fr": "Prix mensuels en $/kg de la matière grasse, des protéines et des autres "
            "solides des classes 3(d), 4(a), 4(m), 5(a), 5(b) et 5(c), fixés ou annoncés "
            "par la CCL.",
        },
        "coverage": {
            "en": "January 2002 to the latest announced month",
            "fr": "Janvier 2002 à aujourd'hui",
        },
        "frequency": {"en": "monthly (by the 15th)", "fr": "mensuelle (au plus tard le 15)"},
    },
    {
        "key": "butter_support_prices",
        "tool": "cdc_get_butter_support_prices",
        "format": "html table",
        "url": constants.SUPPORT_PRICES_PAGE,
        "title": {"en": "Butter support price", "fr": "Prix de soutien du beurre"},
        "description": {
            "en": "The price at which the CDC buys and sells butter under its programs, "
            "usually effective February 1.",
            "fr": "Prix auquel la CCL achète et vend le beurre dans le cadre de ses "
            "programmes, habituellement en vigueur le 1er février.",
        },
        "coverage": {"en": "2010 to the current year", "fr": "2010 à l'année en cours"},
        "frequency": {
            "en": "yearly, sometimes mid-year",
            "fr": "annuelle, parfois en cours d'année",
        },
    },
    {
        "key": "national_quota",
        "tool": "cdc_get_national_quota",
        "format": "html table",
        "url": constants.NATIONAL_QUOTA_INDEX,
        "title": {
            "en": "National milk production target (total quota)",
            "fr": "Cible nationale de production laitière (quota total)",
        },
        "description": {
            "en": "Monthly total quota for Canada in kilograms of butterfat, set by the CDC "
            "under the Canadian Milk Supply Management Committee's method.",
            "fr": "Quota total mensuel du Canada en kilogrammes de matière grasse, établi par "
            "la CCL selon la méthode du Comité canadien de gestion des approvisionnements "
            "de lait.",
        },
        "coverage": {"en": "January 2017 to the latest month", "fr": "Janvier 2017 à aujourd'hui"},
        "frequency": {"en": "monthly", "fr": "mensuelle"},
    },
    {
        "key": "milk_classes",
        "tool": "cdc_get_milk_classes",
        "format": "html table",
        "url": constants.MILK_CLASSES_PAGE,
        "title": {
            "en": "Harmonized Milk Classification System",
            "fr": "Système harmonisé de classification du lait",
        },
        "description": {
            "en": "Which dairy products belong to each milk class and subclass (1 to 5).",
            "fr": "Les produits laitiers de chaque classe et sous-classe de lait (1 à 5).",
        },
        "coverage": {"en": "current classification", "fr": "classification en vigueur"},
        "frequency": {"en": "when classes change", "fr": "lors des changements de classes"},
    },
    {
        "key": "market_data",
        "tool": "cdc_query_market_data",
        "format": "csv",
        "url": {
            "en": f"https://open.canada.ca/data/en/dataset/{constants.MARKET_DATA_DATASET_ID}",
            "fr": f"https://open.canada.ca/data/fr/dataset/{constants.MARKET_DATA_DATASET_ID}",
        },
        "title": {
            "en": "CDC market data: production, milk class sales, farms",
            "fr": "Données de marché de la CCL : production, ventes par classe, fermes",
        },
        "description": {
            "en": "Monthly farm milk production by province (litres), monthly milk class "
            "sales for the ten provinces and for East/West regions (litres, kg and $ of "
            "butterfat, protein and other solids), and farms shipping milk on August 1.",
            "fr": "Production mensuelle de lait à la ferme par province (litres), ventes "
            "mensuelles par classe pour les dix provinces et pour les régions Est et Ouest "
            "(litres, kg et $ de matière grasse, protéines et autres solides), et nombre de "
            "fermes expédiant du lait au 1er août.",
        },
        "coverage": {
            "en": "production from January 2016, sales from July 2020, farms 2016-2025",
            "fr": "production depuis janvier 2016, ventes depuis juillet 2020, fermes 2016-2025",
        },
        "frequency": {"en": "monthly", "fr": "mensuelle"},
    },
]

_RELATED: list[dict[str, Any]] = [
    {
        "name": "Dairy Farmers of Ontario",
        "url": "https://new.milk.org/Industry/quota-exchange-archive/",
        "status": "pdf_only",
        "detail": {
            "en": "Monthly quota exchange summaries and annual reports are PDFs; prices "
            "and producer data sit behind the industry login.",
            "fr": "Les sommaires mensuels de l'échange de quotas et les rapports annuels "
            "sont en PDF; les prix et données des producteurs exigent une connexion.",
        },
    },
    {
        "name": "Les Producteurs de lait du Québec",
        "url": "https://lait.org/notre-lait/statistiques/",
        "status": "pdf_only",
        "detail": {
            "en": "The statistics selector (farm prices, quota prices and transactions, "
            "sales by class, production) returns one PDF per month and statistic.",
            "fr": "Le sélecteur de statistiques (prix à la ferme, prix et transactions de "
            "quota, ventes par classe, production) renvoie un PDF par mois et statistique.",
        },
    },
    {
        "name": "Alberta Milk",
        "url": "https://albertamilk.com/for-industry/quota-milk-production/",
        "status": "pdf_only",
        "detail": {
            "en": "Quota summaries are monthly PDFs; the page shows only the last 14 months "
            "of average prices and components as text.",
            "fr": "Les sommaires de quota sont des PDF mensuels; la page n'affiche en texte "
            "que les 14 derniers mois de prix moyens et de composants.",
        },
    },
    {
        "name": "BC Milk Marketing Board",
        "url": "https://bcmilk.com/",
        "status": "blocked_access",
        "detail": {
            "en": "Every request gets a captcha challenge (HTTP 202).",
            "fr": "Chaque requête reçoit un test captcha (HTTP 202).",
        },
    },
    {
        "name": {"en": "Egg Farmers of Canada", "fr": "Producteurs d'œufs du Canada"},
        "url": "https://www.eggfarmers.ca/market-information-tables/",
        "status": "blocked_terms",
        "detail": {
            "en": "Weekly prices, production and imports are Tableau Public views that "
            "export CSV, but the site's terms allow personal non-commercial use only and "
            "prohibit retransmission or republication without written permission.",
            "fr": "Les prix, la production et les importations hebdomadaires sont des vues "
            "Tableau Public exportables en CSV, mais les conditions du site limitent "
            "l'utilisation à un usage personnel et non commercial et interdisent la "
            "retransmission sans permission écrite.",
        },
        "alternative": {
            "en": "wds_ tables 32-10-0121-01 and 32-10-0119-01 (StatCan egg production)",
            "fr": "tableaux wds_ 32-10-0121-01 et 32-10-0119-01 (production d'œufs, StatCan)",
        },
    },
    {
        "name": {"en": "Chicken Farmers of Canada", "fr": "Producteurs de poulet du Canada"},
        "url": "https://www.chickenfarmers.ca/market-update/",
        "status": "pdf_only",
        "detail": {
            "en": "The monthly market update is a PDF.",
            "fr": "La mise à jour mensuelle du marché est un PDF.",
        },
        "alternative": {
            "en": "wds_ table 32-10-0117-01 (StatCan poultry meat production)",
            "fr": "tableau wds_ 32-10-0117-01 (production de viande de volaille, StatCan)",
        },
    },
    {
        "name": {"en": "Turkey Farmers of Canada", "fr": "Éleveurs de dindon du Canada"},
        "url": "https://www.turkeyfarmersofcanada.ca/industry-information/industry-facts-stats/",
        "status": "pdf_only",
        "detail": {
            "en": "A yearly snapshot on the page and a 1974-2025 statistics e-book (PDF).",
            "fr": "Un portrait annuel sur la page et un recueil statistique 1974-2025 (PDF).",
        },
        "alternative": {
            "en": "wds_ tables 32-10-0117-01 and 32-10-0120-01 (StatCan)",
            "fr": "tableaux wds_ 32-10-0117-01 et 32-10-0120-01 (StatCan)",
        },
    },
    {
        "name": {
            "en": "Canadian Hatching Egg Producers",
            "fr": "Producteurs d'œufs d'incubation du Canada",
        },
        "url": "https://www.chep-poic.ca/",
        "status": "blocked_access",
        "detail": {
            "en": "The site fails TLS verification (incomplete certificate chain) and "
            "plain HTTP answers 403.",
            "fr": "Le site échoue à la vérification TLS (chaîne de certificats incomplète) "
            "et HTTP simple répond 403.",
        },
        "alternative": {
            "en": "wds_ table 32-10-0120-01 (StatCan chick placements)",
            "fr": "tableau wds_ 32-10-0120-01 (mises en place de poussins, StatCan)",
        },
    },
    {
        "name": {
            "en": "Farm Products Council of Canada",
            "fr": "Conseil des produits agricoles du Canada",
        },
        "url": "https://www.fpcc-cpac.gc.ca/",
        "status": "no_data",
        "detail": {
            "en": "No datasets on open.canada.ca (organization fpcc-cpac); its site reset "
            "connections when checked.",
            "fr": "Aucun jeu de données sur open.canada.ca (organisation fpcc-cpac); son site "
            "a coupé les connexions lors de la vérification.",
        },
    },
    {
        "name": {
            "en": "Global Affairs Canada tariff rate quota holders",
            "fr": "Détenteurs de contingents tarifaires (Affaires mondiales Canada)",
        },
        "url": {
            "en": "https://open.canada.ca/data/en/dataset?organization=dfatd-maecd",
            "fr": "https://open.canada.ca/data/fr/dataset?organization=dfatd-maecd",
        },
        "status": "use_other_tool",
        "detail": {
            "en": "Import quota holder lists for dairy, chicken, eggs and turkey (WTO, "
            "CUSMA, CPTPP) are ordinary CKAN datasets.",
            "fr": "Les listes de détenteurs de contingents d'importation (lait, poulet, "
            "œufs, dindon; OMC, ACEUM, PTPGP) sont des jeux de données CKAN ordinaires.",
        },
        "alternative": "ckan_search_datasets(portal='federal', fq='organization:dfatd-maecd')",
    },
    {
        "name": {
            "en": "Statistics Canada dairy tables",
            "fr": "Tableaux de Statistique Canada sur les produits laitiers",
        },
        "url": {
            "en": "https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=3210011301",
            "fr": "https://www150.statcan.gc.ca/t1/tbl1/fr/tv.action?pid=3210011301",
        },
        "status": "use_other_tool",
        "detail": {
            "en": "Milk production and utilization (32-10-0113-01), dairy product "
            "production (32-10-0112-01) and milk and cream sales (32-10-0114-01).",
            "fr": "Production et utilisation du lait (32-10-0113-01), production de "
            "produits laitiers (32-10-0112-01) et ventes de lait et de crème "
            "(32-10-0114-01).",
        },
        "alternative": {"en": "wds_ tools", "fr": "outils wds_"},
    },
]


def _pick(value: Any, lang: str) -> Any:
    """A per-language value from {"en": ..., "fr": ...}, or the value itself.

    Names without an official French form (Dairy Farmers of Ontario, BC
    Milk Marketing Board) stay a plain string.
    """
    return value[lang] if isinstance(value, dict) else value


def catalogue(lang: str = "en") -> CdcCatalogue:
    lang = _lang(lang)
    datasets = [
        DatasetInfo(
            key=d["key"],
            title=d["title"][lang],
            description=d["description"][lang],
            tool=d["tool"],
            source_format=d["format"],
            source_url=d["url"][lang],
            coverage=d["coverage"][lang],
            update_frequency=d["frequency"][lang],
        )
        for d in _DATASETS
    ]
    related = [
        RelatedSource(
            name=_pick(r["name"], lang),
            url=_pick(r["url"], lang),
            status=r["status"],
            detail=r["detail"][lang],
            alternative=_pick(r.get("alternative"), lang),
        )
        for r in _RELATED
    ]
    return CdcCatalogue(
        datasets=datasets,
        related_sources=related,
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=f"{constants.SITE}/{lang}",
            cached=False,
            schema_name="cdc.CdcCatalogue",
            coverage="Curated list, checked live 2026-09-26; no upstream call is made.",
        ),
    )


# ---------------------------------------------------------------------------
# Component prices
# ---------------------------------------------------------------------------


def parse_component_rows(rows: list[dict[str, str]]) -> list[ComponentPrice]:
    if not rows:
        return []
    columns = Columns(rows)
    class_col = columns.first_of(["Milk Class", "Classe de lait"])
    date_col = columns.first_of(["Effective Date", "Date d'entrée en vigueur"])
    # On 2026-09-28 the current year's CSV briefly came with French headers
    # for the three prices (and "Classe de lait") beside an English date column.
    fat_col = columns.first_of(["Butterfat($/kg)", "Butterfat ($/kg)", "M.G.($/kg)"])
    protein_col = columns.first_of(
        ["Proteins($/kg)", "Proteins ($/kg)", "Protein($/kg)", "Protéine($/kg)"]
    )
    other_col = columns.first_of(
        ["Other solids($/kg)", "Other solids ($/kg)", "Autres solides($/kg)"]
    )
    if not (class_col and date_col and fat_col and protein_col and other_col):
        raise UpstreamError(f"cdc: component price columns changed: {columns.names}.")
    parsed = []
    for row in rows:
        code = normalize_class(row.get(class_col) or "")
        raw_date = (row.get(date_col) or "").strip()[:10]
        if not code or not raw_date:
            continue
        try:
            effective = date.fromisoformat(raw_date)
        except ValueError:
            continue
        parsed.append(
            ComponentPrice(
                milk_class=class_label(code),
                milk_class_code=code,
                effective_date=effective,
                butterfat_per_kg=_price(row.get(fat_col)),
                protein_per_kg=_price(row.get(protein_col)),
                other_solids_per_kg=_price(row.get(other_col)),
            )
        )
    parsed.sort(key=lambda p: (p.effective_date, p.milk_class_code))
    return parsed


_COMPONENT_NOTES = {
    "en": [
        "Prices are $/kg of component, effective from the first of the month shown.",
        (
            "None means the CDC file has 0 or a blank: 4(m) butterfat (and 4(a) butterfat "
            "before 2024) follows the provincial 4(a) butterfat price, 4(a) solids-non-fat "
            "prices are posted around the 5th of the following month, and later months of "
            "the current year are not announced yet."
        ),
        (
            "Class 3(d) (mozzarella for fresh pizza in restaurants) is fixed from February 1 "
            "to January 31; classes 4(a), 4(m) and 5 change monthly."
        ),
    ],
    "fr": [
        "Les prix sont en $/kg de composant, en vigueur dès le premier du mois indiqué.",
        (
            "None signifie que le fichier de la CCL indique 0 ou rien : la matière grasse "
            "4(m) (et 4(a) avant 2024) suit le prix provincial de la matière grasse 4(a), les "
            "prix des solides non gras 4(a) sont publiés vers le 5 du mois suivant, et les "
            "mois à venir de l'année en cours ne sont pas encore annoncés."
        ),
        (
            "La classe 3(d) (mozzarella pour pizzas fraîches en restauration) est fixée du "
            "1er février au 31 janvier; les classes 4(a), 4(m) et 5 changent chaque mois."
        ),
    ],
}


async def get_component_prices(
    year_from: int | None = None,
    year_to: int | None = None,
    milk_class: str | None = None,
    lang: str = "en",
) -> ComponentPriceResult:
    lang = _lang(lang)
    current_year = _today().year
    defaulted = year_from is None and year_to is None
    if year_to is None:
        year_to = current_year if year_from is None else max(year_from, current_year)
    if year_from is None:
        year_from = year_to
    if year_from > year_to:
        raise InvalidInput("cdc: year_from must not be after year_to.")
    if year_from < constants.COMPONENT_PRICES_FIRST_YEAR or year_to > current_year + 1:
        raise InvalidInput(
            f"cdc: component prices are published from {constants.COMPONENT_PRICES_FIRST_YEAR} "
            f"to {current_year}; got {year_from}-{year_to}."
        )
    code = None
    if milk_class:
        code = normalize_class(milk_class)
        if code not in COMPONENT_CLASS_CODES:
            raise InvalidInput(
                f"cdc: milk_class must be one of "
                f"{[class_label(c) for c in COMPONENT_CLASS_CODES]}, got {milk_class!r}."
            )

    notes = list(_COMPONENT_NOTES[lang])

    async def year_rows(year: int) -> tuple[list[ComponentPrice], bool, str]:
        url = constants.COMPONENT_PRICES_URL.format(year=year)
        ttl = (
            constants.CURRENT_YEAR_TTL_SECONDS
            if year >= current_year
            else constants.PAST_YEAR_TTL_SECONDS
        )
        raw, cached = await fetch_rows(url, limiter=_LIMITER, ttl=ttl, context="cdc:component")
        return parse_component_rows(raw), cached, url

    rows: list[ComponentPrice] = []
    files: list[str] = []
    fetched_years: list[int] = []
    all_cached = True
    for year in range(year_from, year_to + 1):
        try:
            parsed, cached, url = await year_rows(year)
        except NotFound:
            # Early January (before the CDC posts the new year's file) or a
            # requested next year: skip it and say so. A missing past year
            # is a real error.
            if year < current_year:
                raise
            notes.append(
                f"No {year} file yet." if lang == "en" else f"Pas encore de fichier pour {year}."
            )
            continue
        rows.extend(parsed)
        files.append(url)
        fetched_years.append(year)
        all_cached &= cached
    if not fetched_years:
        if not defaulted:
            raise NotFound(f"cdc: no component price file for {year_from}-{year_to} yet.")
        parsed, all_cached, url = await year_rows(current_year - 1)
        rows, files, fetched_years = parsed, [url], [current_year - 1]
    year_from, year_to = fetched_years[0], fetched_years[-1]

    if code:
        rows = [r for r in rows if r.milk_class_code == code]
    return ComponentPriceResult(
        year_from=year_from,
        year_to=year_to,
        milk_class=class_label(code) if code else None,
        rows=rows,
        row_count=len(rows),
        source_files=files,
        notes=notes,
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=files[0] if len(files) == 1 else constants.COMPONENT_PRICES_PAGE[lang],
            cached=all_cached,
            schema_name="cdc.ComponentPriceResult",
            freshness="monthly; next month's prices are announced by the 15th",
            coverage=f"{year_from}-{year_to}",
        ),
    )


# ---------------------------------------------------------------------------
# Butter support price
# ---------------------------------------------------------------------------


def parse_number(text: str) -> float | None:
    """'10.5662' or the French page's '10, 5662' -> 10.5662."""
    value = text.replace("\xa0", "").replace(" ", "").replace(",", ".").replace("$", "")
    try:
        return float(value)
    except ValueError:
        return None


def parse_support_prices(page: str) -> list[SupportPrice]:
    main = _main(page)
    table = main.find("table")
    if not isinstance(table, Tag):
        raise UpstreamError("cdc: the support price page no longer has its table.")
    rows = []
    for tr in table.find_all("tr"):
        cells = [_clean_text(c) for c in tr.find_all("td")]
        if len(cells) < 2 or not cells[0]:
            continue
        label = cells[0]
        match = re.match(r"(\d{4})\s*(?:\(([^)]+)\))?", label)
        effective = None
        if match:
            month = month_number(match.group(2)) if match.group(2) else 2
            if month:
                effective = date(int(match.group(1)), month, 1)
        rows.append(
            SupportPrice(
                effective_label=label,
                effective_date=effective,
                butter_per_kg=parse_number(cells[1]),
            )
        )
    if not rows:
        raise UpstreamError("cdc: the support price table is empty.")
    return rows


async def _french_support_labels(rows: list[SupportPrice]) -> list[SupportPrice]:
    """The French page's row labels ("2024 (mai)", "2023 (fév.)") on the English rows.

    Used only when the French table has the same rows, dates and prices
    (it did on 2026-09-26); otherwise, or if the page fails, the English
    labels are kept rather than risk pairing a label with the wrong price.
    """
    try:
        page, _ = await _page(constants.SUPPORT_PRICES_PAGE["fr"])
        french = parse_support_prices(page)
    except (NotFound, UpstreamError, UpstreamUnavailable):
        return rows
    if len(french) != len(rows) or any(
        (f.effective_date, f.butter_per_kg) != (r.effective_date, r.butter_per_kg)
        for f, r in zip(french, rows, strict=True)
    ):
        return rows
    return [
        r.model_copy(update={"effective_label": f.effective_label})
        for f, r in zip(french, rows, strict=True)
    ]


async def get_butter_support_prices(lang: str = "en") -> SupportPriceResult:
    lang = _lang(lang)
    url = constants.SUPPORT_PRICES_PAGE["en"]
    page, cached = await _page(url)
    rows = parse_support_prices(page)
    if lang == "fr":
        rows = await _french_support_labels(rows)
    notes = {
        "en": [
            (
                "The CDC buys and sells butter at this price under its programs; it stopped "
                "buying skim milk powder in 2017, so there is no powder support price."
            ),
            (
                "A plain year means the price took effect on February 1 of that year; a month "
                "in parentheses marks a change on the first of that month."
            ),
        ],
        "fr": [
            (
                "La CCL achète et vend le beurre à ce prix dans le cadre de ses programmes; elle "
                "a cessé d'acheter de la poudre de lait écrémé en 2017, il n'y a donc plus de "
                "prix de soutien pour la poudre."
            ),
            (
                "Une année seule signifie une entrée en vigueur le 1er février; un mois entre "
                "parenthèses indique un changement le premier de ce mois."
            ),
        ],
    }[lang]
    return SupportPriceResult(
        rows=rows,
        row_count=len(rows),
        source_page=constants.SUPPORT_PRICES_PAGE[lang],
        notes=notes,
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=url,
            cached=cached,
            schema_name="cdc.SupportPriceResult",
            freshness="yearly, announced in the fall for February 1",
        ),
    )


# ---------------------------------------------------------------------------
# National milk production target (total quota)
# ---------------------------------------------------------------------------


def parse_quota_index(page: str, base_url: str) -> dict[int, str]:
    main = _main(page)
    years: dict[int, str] = {}
    for link in main.find_all("a", href=True):
        text = link.get_text(strip=True)
        if re.fullmatch(r"(19|20)\d{2}", text):
            years.setdefault(int(text), urljoin(base_url, str(link["href"])))
    return years


def parse_quota_value(text: str) -> int | None:
    value = text.replace("\xa0", " ").strip()
    if re.fullmatch(r"\d{1,3}(,\d{3})+|\d+", value):
        return int(value.replace(",", ""))
    return None


def parse_quota_page(page: str, year: int) -> list[QuotaMonth]:
    main = _main(page)
    months: dict[str, QuotaMonth] = {}
    for table in main.find_all("table"):
        for tr in table.find_all("tr"):
            cells = [_clean_text(c) for c in tr.find_all("td")]
            if len(cells) < 2 or not cells[1]:
                continue
            match = re.match(r"([^\d\s]+)\.?\s*(\d{4})?", cells[0])
            if not match:
                continue
            month = month_number(match.group(1))
            if month is None:
                continue
            row_year = int(match.group(2)) if match.group(2) else year
            period = f"{row_year:04d}-{month:02d}"
            change = parse_number(cells[2]) if len(cells) > 2 and cells[2] else None
            months.setdefault(
                period,
                QuotaMonth(
                    year=row_year,
                    month=month,
                    period=period,
                    total_quota_kg_butterfat=parse_quota_value(cells[1]),
                    published_value=cells[1],
                    change_from_year_ago_pct=change,
                ),
            )
    return sorted(months.values(), key=lambda m: m.period)


async def _french_quota_pages(english: dict[int, str]) -> dict[int, str]:
    """Year -> French page, from the French index (node 653 lists every year in both)."""
    index_url = constants.NATIONAL_QUOTA_INDEX["fr"]
    try:
        page, _ = await _page(index_url)
    except (NotFound, UpstreamError, UpstreamUnavailable):
        return english
    return {**english, **parse_quota_index(page, index_url)}


async def get_national_quota(
    year_from: int | None = None, year_to: int | None = None, lang: str = "en"
) -> QuotaResult:
    lang = _lang(lang)
    index_url = constants.NATIONAL_QUOTA_INDEX["en"]
    index_page, index_cached = await _page(index_url)
    years = parse_quota_index(index_page, index_url)
    if not years:
        raise UpstreamError("cdc: the national quota index lists no years.")
    latest = max(years)
    if year_to is None:
        year_to = latest if year_from is None else max(year_from, min(latest, _today().year))
    if year_from is None:
        year_from = year_to
    if year_from > year_to:
        raise InvalidInput("cdc: year_from must not be after year_to.")
    missing = [y for y in range(year_from, year_to + 1) if y not in years]
    if missing:
        raise NotFound(
            f"cdc: no national quota page for {missing}; the CDC publishes {min(years)}-"
            f"{latest} (earlier years by email request)."
        )
    # Figures are read from the English pages (the layouts parse_quota_page
    # knows); with lang="fr" the French page of each year is linked instead.
    linked = await _french_quota_pages(years) if lang == "fr" else years
    rows: list[QuotaMonth] = []
    pages: list[str] = []
    all_cached = index_cached
    for year in range(year_from, year_to + 1):
        page, cached = await _page(years[year])
        all_cached &= cached
        pages.append(linked.get(year, years[year]))
        year_rows = parse_quota_page(page, year)
        if not year_rows:
            raise UpstreamError(f"cdc: the {year} national quota page has no monthly figures.")
        rows.extend(r for r in year_rows if year_from <= r.year <= year_to)

    notes = [
        "Total quota is the national milk production target in kilograms of butterfat."
        if lang == "en"
        else "Le quota total est la cible nationale de production laitière en kilogrammes "
        "de matière grasse."
    ]
    malformed = [r.period for r in rows if r.total_quota_kg_butterfat is None]
    if malformed:
        notes.append(
            f"Published figures that are not valid numbers are kept as text only: {malformed}."
            if lang == "en"
            else f"Chiffres publiés invalides, conservés en texte seulement : {malformed}."
        )
    seen = {r.period for r in rows}
    gaps = []
    for year in range(year_from, year_to + 1):
        # The latest year is complete only up to its last published month.
        last = 12 if year < latest else max((r.month for r in rows if r.year == year), default=0)
        gaps.extend(f"{year:04d}-{m:02d}" for m in range(1, last + 1))
    gaps = [g for g in gaps if g not in seen]
    if gaps:
        notes.append(
            f"Months missing from the CDC pages: {gaps}."
            if lang == "en"
            else f"Mois absents des pages de la CCL : {gaps}."
        )
    if year_from <= 2018 <= year_to:
        notes.append(
            "The 2018 page splits the year into 'Total quota before August 2018' "
            "(January-July) and 'Total quota since August 2018'."
            if lang == "en"
            else "La page de 2018 sépare l'année en deux tableaux : avant août 2018 "
            "(janvier à juillet) et depuis août 2018."
        )
    return QuotaResult(
        year_from=year_from,
        year_to=year_to,
        rows=rows,
        row_count=len(rows),
        source_pages=pages,
        notes=notes,
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=pages[0] if len(pages) == 1 else constants.NATIONAL_QUOTA_INDEX[lang],
            cached=all_cached,
            schema_name="cdc.QuotaResult",
            freshness="monthly",
            coverage=f"{year_from}-{year_to}; pages exist for {min(years)}-{latest}",
        ),
    )


# ---------------------------------------------------------------------------
# Harmonized milk classes
# ---------------------------------------------------------------------------

_CLASS_CODE = re.compile(r"^(\d)\s*\(([a-z])\)(?:\s*(\d))?$")


def parse_milk_classes(page: str) -> list[MilkClass]:
    main = _main(page)
    classes: list[MilkClass] = []
    for table in main.find_all("table"):
        current: MilkClass | None = None
        for tr in table.find_all("tr"):
            cells = [_clean_text(c) for c in tr.find_all("td")]
            if not cells:
                continue
            match = _CLASS_CODE.match(cells[0])
            if match and len(cells) >= 2:
                current = MilkClass(
                    milk_class=cells[0],
                    class_group=match.group(1),
                    products=[cells[1]] if cells[1] else [],
                )
                classes.append(current)
            elif len(cells) == 1 and current is not None and cells[0]:
                # A rowspan continuation: another product line of the class above.
                current.products.append(cells[0])
    return classes


async def get_milk_classes(milk_class: str | None = None, lang: str = "en") -> MilkClassResult:
    lang = _lang(lang)
    url = constants.MILK_CLASSES_PAGE[lang]
    page, cached = await _page(url)
    classes = parse_milk_classes(page)
    if not classes:
        raise UpstreamError("cdc: the milk class page no longer has its class tables.")
    if milk_class:
        wanted = normalize_class(milk_class)
        classes = [c for c in classes if normalize_class(c.milk_class).startswith(wanted)]
        if not classes:
            raise NotFound(f"cdc: no milk class matches {milk_class!r}.")
    return MilkClassResult(
        classes=classes,
        class_count=len(classes),
        source_page=url,
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=url,
            cached=cached,
            schema_name="cdc.MilkClassResult",
            freshness="changes when provinces agree on new classes",
        ),
    )


# ---------------------------------------------------------------------------
# Market data (AAFC-hosted CDC file)
# ---------------------------------------------------------------------------

_DATASET_PREFIXES: dict[str, MarketDataset] = {
    "total production": "production",
    "provincial sales": "sales_p10",
    "sales by region": "sales_by_region",
    "farms with milk": "farms",
}
_SEGMENTS: dict[str, MarketSegment] = {
    "volume (l)": "volume",
    "butterfat sales (kg)": "butterfat_sales",
    "butterfat revenue ($)": "butterfat_revenue",
    "protein sales (kg)": "protein_sales",
    "protein revenue ($)": "protein_revenue",
    "other solids sales (kg)": "other_solids_sales",
    "other solids revenue ($)": "other_solids_revenue",
    "count": "farm_count",
}
_LABEL_COLUMNS = {
    "en": {
        "dataset": "DatasetEn_DonneesAn",
        "level1": "PrdLvl1En_PrdNv1An",
        "level2": "PrdLvl2En_PrdNv2An",
        "region": "RegionEn_RegionAn",
        "segment": "SegmentEn_SegmentAn",
    },
    "fr": {
        "dataset": "DatasetFr_DonneesFr",
        "level1": "PrdLvl1Fr_PrdNv1Fr",
        "level2": "PrdLvl2Fr_PrdNv2Fr",
        "region": "RegionFr_RegionFr",
        "segment": "SegmentFr_SegmentFr",
    },
}
PROVINCES = ("AB", "BC", "MB", "NB", "NL", "NS", "NT", "NU", "ON", "PE", "QC", "SK", "YT")
_REGIONS = {"east": "East", "est": "East", "west": "West", "ouest": "West"}


def _dataset_key(name: str) -> MarketDataset | None:
    low = name.strip().lower()
    return next((key for prefix, key in _DATASET_PREFIXES.items() if low.startswith(prefix)), None)


def _unit(segment_en: str) -> str:
    match = re.search(r"\(([^)]+)\)\s*$", segment_en)
    return match.group(1) if match else "count"


def _parse_period(text: str, *, end: bool) -> date:
    value = text.strip()
    try:
        if re.fullmatch(r"\d{4}", value):
            return date(int(value), 12, 31) if end else date(int(value), 1, 1)
        if re.fullmatch(r"\d{4}-\d{2}", value):
            year, month = int(value[:4]), int(value[5:])
            day = calendar.monthrange(year, month)[1] if end else 1
            return date(year, month, day)
        return date.fromisoformat(value)
    except ValueError as exc:
        raise InvalidInput(
            f"cdc: dates must be YYYY, YYYY-MM or YYYY-MM-DD, got {text!r}."
        ) from exc


_MARKET_NOTES = {
    "en": [
        (
            "P10 means the ten provinces; the East region is NL, PE, NS, NB, QC and ON, the "
            "West region MB, SK, AB and BC."
        ),
        (
            "Confidential figures are folded into the nearest class with the highest use: "
            "in sales_p10, 1A1 includes 1A2, 1A3, 1C and 1D; in sales_by_region, 1A includes "
            "1C and 1D, 3C includes 3B, 4D includes 4B, 4C and 4M, and 5B includes 5C."
        ),
        (
            "Revenue divided by sales (kg) for the same class and month gives the average "
            "price per kg of that component."
        ),
        "Farm counts are farms shipping milk on August 1 of each year.",
    ],
    "fr": [
        (
            "P10 désigne les dix provinces; la région Est comprend T.-N.-L., Î.-P.-É., N.-É., "
            "N.-B., Qc et Ont., la région Ouest Man., Sask., Alb. et C.-B."
        ),
        (
            "Les données confidentielles sont regroupées avec la classe voisine la plus "
            "utilisée : dans sales_p10, 1A1 inclut 1A2, 1A3, 1C et 1D; dans sales_by_region, "
            "1A inclut 1C et 1D, 3C inclut 3B, 4D inclut 4B, 4C et 4M, et 5B inclut 5C."
        ),
        (
            "Le revenu divisé par les ventes (kg) pour une même classe et un même mois donne "
            "le prix moyen au kg du composant."
        ),
        "Le nombre de fermes est celui des fermes expédiant du lait au 1er août.",
    ],
}


async def query_market_data(
    dataset: MarketDataset,
    province: str | None = None,
    region: str | None = None,
    milk_class: str | None = None,
    segment: MarketSegment | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = constants.MARKET_DATA_DEFAULT_LIMIT,
    lang: str = "en",
) -> MarketDataResult:
    lang = _lang(lang)
    if dataset not in _DATASET_PREFIXES.values():
        raise InvalidInput(
            f"cdc: dataset must be one of {sorted(_DATASET_PREFIXES.values())}, got {dataset!r}."
        )
    if not 1 <= limit <= constants.MARKET_DATA_MAX_LIMIT:
        raise InvalidInput(f"cdc: limit must be 1-{constants.MARKET_DATA_MAX_LIMIT}.")
    prov = province.strip().upper() if province else None
    if prov and prov not in PROVINCES:
        raise InvalidInput(
            f"cdc: province must be a two-letter code {PROVINCES}, got {province!r}."
        )
    reg = None
    if region:
        reg = _REGIONS.get(region.strip().lower())
        if reg is None:
            raise InvalidInput(f"cdc: region must be 'East' or 'West', got {region!r}.")
    if segment is not None and segment not in _SEGMENTS.values():
        raise InvalidInput(f"cdc: segment must be one of {sorted(_SEGMENTS.values())}.")
    wanted_class = normalize_class(milk_class) if milk_class else None
    start = _parse_period(date_from, end=False) if date_from else None
    end = _parse_period(date_to, end=True) if date_to else None

    raw, cached = await fetch_rows(
        constants.MARKET_DATA_URL,
        limiter=_LIMITER,
        ttl=constants.MARKET_DATA_TTL_SECONDS,
        context="cdc:market_data",
    )
    names = set(raw[0]) if raw else set()
    required = [
        "Date",
        "ProvState_ProvEtat",
        "Value_Valeur",
        *_LABEL_COLUMNS["en"].values(),
        *_LABEL_COLUMNS["fr"].values(),
    ]
    missing = [name for name in required if name not in names]
    if missing:
        raise UpstreamError(f"cdc: the market data file lost columns {missing}.")

    labels = _LABEL_COLUMNS[lang]
    matched: list[MarketDataRow] = []
    dataset_seen = False
    for row in raw:
        if _dataset_key(row["DatasetEn_DonneesAn"]) != dataset:
            continue
        dataset_seen = True
        try:
            period = date.fromisoformat(row["Date"].strip()[:10])
        except ValueError:
            continue
        if (start and period < start) or (end and period > end):
            continue
        row_prov = row["ProvState_ProvEtat"].strip() or None
        if prov and row_prov != prov:
            continue
        row_region = row["RegionEn_RegionAn"].strip() or None
        if reg and row_region != reg:
            continue
        segment_en = row["SegmentEn_SegmentAn"].strip()
        row_segment = _SEGMENTS.get(segment_en.lower())
        if segment and row_segment != segment:
            continue
        level1_en = row["PrdLvl1En_PrdNv1An"].strip()
        level2_en = row["PrdLvl2En_PrdNv2An"].strip()
        if wanted_class:
            norm1, norm2 = normalize_class(level1_en), normalize_class(level2_en)
            if not (norm1 == wanted_class or (norm2 and norm2.startswith(wanted_class))):
                continue
        value_text = row["Value_Valeur"].strip()
        try:
            value = float(value_text) if value_text else None
        except ValueError:
            value = None
        matched.append(
            MarketDataRow(
                period_end=period,
                dataset=dataset,
                dataset_label=row[labels["dataset"]].strip(),
                milk_class=row[labels["level1"]].strip() or None,
                milk_subclass=row[labels["level2"]].strip() or None,
                province=row_prov,
                region=row[labels["region"]].strip() or None,
                segment=row[labels["segment"]].strip(),
                unit=_unit(segment_en),
                value=value,
            )
        )
    if not dataset_seen:
        raise UpstreamError(f"cdc: the market data file has no {dataset!r} rows any more.")
    matched.sort(
        key=lambda r: (
            -r.period_end.toordinal(),
            r.milk_subclass or r.milk_class or "",
            r.province or "",
            r.region or "",
            r.segment,
        )
    )
    return MarketDataResult(
        dataset=dataset,
        total_matched=len(matched),
        returned_count=min(len(matched), limit),
        rows=matched[:limit],
        latest_date=matched[0].period_end if matched else None,
        dictionary_url=constants.MARKET_DATA_DICTIONARY[lang],
        notes=_MARKET_NOTES[lang],
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=constants.MARKET_DATA_URL,
            cached=cached,
            schema_name="cdc.MarketDataResult",
            freshness="monthly (the file is regenerated daily on AAFC's open-data server)",
            limits=f"newest {limit} rows returned" if len(matched) > limit else None,
            coverage=f"{len(matched)} matching rows",
        ),
    )
