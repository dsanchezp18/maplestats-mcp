"""Federal cleantech investment, 2016-2024, from the Clean Growth Hub page.

The Clean Technology Data Strategy publishes its federal investment
figures only as a web page and a PDF infographic (checked 2026-09-25;
no CSV, API or open.canada.ca dataset). The page carries three HTML
tables (agreement value by year, share of agreements by province or
territory, value by cleantech subsector) and the headline figures in
prose; this client turns both into numbers. Quirks handled:

1. Values are text: "0.20 billion" (EN), "0,20\xa0milliards" (FR),
   "16%" / "16\xa0%". They become dollars and percentages.
2. Footnote references sit inside labels as <sup> links ("Other 5
   subsectors" + "table 3 note 3"); they are removed before reading.
3. Headline figures appear only in prose; they are read from the English
   page with anchored patterns (numbers are identical in French), and a
   pattern that stops matching yields None rather than a wrong number.
4. The older 2016-2022 URL now redirects to this page, so there is one
   edition.
"""

from __future__ import annotations

import re
from typing import Any

import httpx
from bs4 import BeautifulSoup

from maplestats_mcp.modules.ised.clean_growth import constants
from maplestats_mcp.modules.ised.clean_growth.schemas import FederalInvestment, Headline, ValueRow
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance
from maplestats_mcp.shared.errors import InvalidInput, UpstreamError, UpstreamUnavailable
from maplestats_mcp.shared.http import get_raw
from maplestats_mcp.shared.rate_limiter import get_limiter

_LIMITER = get_limiter(
    constants.RATE_LIMIT_SOURCE,
    rate=constants.RATE_LIMIT_PER_SECOND,
    capacity=constants.RATE_LIMIT_CAPACITY,
)
_SCALE = {"billion": 1e9, "milliard": 1e9, "milliards": 1e9, "million": 1e6, "millions": 1e6}


def parse_amount(text: str) -> float | None:
    """'0.20 billion' or '0,20 milliards' as dollars."""
    match = re.search(r"([\d.,]+)\s*([a-z]+)", text.replace("\xa0", " ").lower())
    if match is None:
        return None
    number = float(match.group(1).replace(",", "."))
    return round(number * _SCALE.get(match.group(2), 1.0), 2)


def parse_percent(text: str) -> float | None:
    match = re.search(r"([\d.,]+)\s*%", text.replace("\xa0", " "))
    return float(match.group(1).replace(",", ".")) if match else None


def _clean(node: Any) -> str:
    for sup in node.find_all("sup"):
        sup.decompose()
    return " ".join(node.get_text(" ").split())


def parse_tables(page: str) -> list[list[ValueRow]]:
    soup = BeautifulSoup(page, "html.parser")
    tables = []
    for table in soup.find_all("table"):
        rows = []
        for tr in table.find_all("tr")[1:]:
            cells = [_clean(cell) for cell in tr.find_all(["th", "td"])]
            if len(cells) < 2 or not cells[0]:
                continue
            is_share = "%" in cells[1]
            rows.append(
                ValueRow(
                    label=cells[0],
                    value_cad=None if is_share else parse_amount(cells[1]),
                    share_percent=parse_percent(cells[1]) if is_share else None,
                )
            )
        tables.append(rows)
    return tables


def _number(pattern: str, text: str, scale: float = 1.0) -> float | None:
    match = re.search(pattern, text)
    if match is None:
        return None
    return round(float(match.group(1).replace(",", "")) * scale, 2)


def parse_headline(page: str) -> Headline:
    """Headline figures from the English page's prose."""
    soup = BeautifulSoup(page, "html.parser")
    main = soup.find("main") or soup
    text = _clean(main)

    def whole(pattern: str) -> int | None:
        value = _number(pattern, text)
        return int(value) if value is not None else None

    period = re.search(r"From (\d{4}) to (\d{4})", text)
    return Headline(
        period=f"{period.group(1)}-{period.group(2)}" if period else None,
        programs=whole(r"data from (\d+) participating federal programs"),
        organizations=whole(r"across (\d+) organizations"),
        committed_cad=_number(r"\$([\d.]+) billion has been committed", text, 1e9),
        agreements=whole(r"Over ([\d,]+) funding agreements"),
        median_agreement_cad=_number(r"median agreement value is \$([\d,]+)", text),
        for_profit_cad=_number(r"received almost \$([\d.]+) billion", text, 1e9),
        non_repayable_share_percent=_number(r"non-repayable contributions \((\d+)%\)", text),
        development_cad=_number(r"Development \(\$([\d.]+) billion\)", text, 1e9),
        business_support_cad=_number(r"Business Support \(\$([\d.]+) billion\)", text, 1e9),
        adoption_cad=_number(r"Adoption \(\$([\d.]+) billion\)", text, 1e9),
        jobs_created_or_maintained=whole(r"over ([\d,]+) jobs have been created"),
    )


def parse_notes(page: str) -> list[str]:
    """The page's table notes, in its own language."""
    soup = BeautifulSoup(page, "html.parser")
    notes = []
    for block in soup.select("aside.wb-fnote dd, section.wb-fnote dd, .fn-lnk + p, dd"):
        text = _clean(block)
        text = re.sub(r"\s*(Return to|Retour à).*$", "", text)
        if len(text) > 30 and text not in notes:
            notes.append(text)
    return notes


async def _page(lang: str) -> tuple[str, bool]:
    url = constants.PAGE_URLS[lang]

    async def fetch() -> str:
        await _LIMITER.acquire()
        try:
            response = await get_raw(url, timeout=60.0)
        except httpx.HTTPStatusError as exc:
            raise UpstreamError(
                f"ised_clean_growth: {url} returned HTTP {exc.response.status_code}."
            ) from exc
        except httpx.HTTPError as exc:
            raise UpstreamUnavailable(f"ised_clean_growth: {url} did not respond in time.") from exc
        if len(response.content) > constants.MAX_PAGE_BYTES:
            raise UpstreamError(f"ised_clean_growth: {url} is larger than expected.")
        return response.text

    return await cached_fetch(f"ised-clean-growth:{lang}", constants.CACHE_TTL_SECONDS, fetch)


async def federal_investment(lang: str = "en") -> FederalInvestment:
    if lang not in constants.PAGE_URLS:
        raise InvalidInput(f"ised_clean_growth: lang must be 'en' or 'fr', got {lang!r}.")
    english, cached = await _page("en")
    page, page_cached = (english, cached) if lang == "en" else await _page(lang)
    tables = parse_tables(page)
    if len(tables) < 3 or not all(tables[:3]):
        raise UpstreamError(
            "ised_clean_growth: the investment page no longer has its three data tables."
        )
    return FederalInvestment(
        headline=parse_headline(english),
        by_year=tables[0],
        by_province=tables[1],
        by_subsector=tables[2],
        notes=parse_notes(page),
        pdf_url=constants.PDF_URLS[lang],
        records_dataset=f"https://open.canada.ca/data/{lang}/dataset/{constants.GRANTS_DATASET_ID}",
        records_resource_id=constants.GRANTS_RESOURCE_ID,
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=constants.PAGE_URLS[lang],
            cached=cached and page_cached,
            schema_name="ised_clean_growth.FederalInvestment",
            freshness="updated with each Clean Growth Hub release (2016-2024 edition)",
            limits=(
                "Aggregates as published; projects were identified from proactive "
                "disclosure of grants and contributions up to March 31, 2025."
            ),
        ),
    )
