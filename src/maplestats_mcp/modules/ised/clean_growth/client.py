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
   pattern that stops matching yields None rather than a wrong number;
   `headline.not_found` and `provenance.limits` name those figures.
5. A table amount whose scale word is not billion/million (or that has
   none) is left null, never read as plain dollars; `value_as_published`
   keeps every cell's text and `provenance.limits` counts the unread ones.
4. The older 2016-2022 URL now redirects to this page, so there is one
   edition.
"""

from __future__ import annotations

import re
from typing import Any, NoReturn

import httpx
from bs4 import BeautifulSoup

from maplestats_mcp.modules.ised.clean_growth import constants
from maplestats_mcp.modules.ised.clean_growth.schemas import FederalInvestment, Headline, ValueRow
from maplestats_mcp.shared import file_download
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance, raise_typed
from maplestats_mcp.shared.errors import InvalidInput, UpstreamError
from maplestats_mcp.shared.i18n import french_spacing, reset_call_lang, set_call_lang
from maplestats_mcp.shared.limits import join_limits
from maplestats_mcp.shared.rate_limiter import get_limiter

_LIMITER = get_limiter(
    constants.RATE_LIMIT_SOURCE,
    rate=constants.RATE_LIMIT_PER_SECOND,
    capacity=constants.RATE_LIMIT_CAPACITY,
)
_FRESHNESS = {
    "en": "updated with each Clean Growth Hub release (2016-2024 edition)",
    "fr": "mis à jour à chaque diffusion du Carrefour de la croissance propre (édition 2016-2024)",
}
_LIMITS = {
    "en": (
        "Aggregates as published; projects were identified from proactive "
        "disclosure of grants and contributions up to March 31, 2025."
    ),
    "fr": (
        "Agrégats tels que publiés ; les projets ont été repérés dans la divulgation "
        "proactive des subventions et contributions jusqu'au 31 mars 2025."
    ),
}


def _raise(exc_cls: type[ValueError], en: str, fr: str, lang: str) -> NoReturn:
    """English stays the plain message; French gets the typed template."""
    if lang == "fr":
        raise_typed(exc_cls, fr, "fr")
    raise exc_cls(en)


_SCALE = {"billion": 1e9, "milliard": 1e9, "milliards": 1e9, "million": 1e6, "millions": 1e6}


def _to_float(digits: str, lang: str) -> float:
    """English groups thousands with commas ("1,200"); French writes the decimal as a
    comma ("1,5") and groups with spaces, so "1,5" is 1.5 in French and 15 in English."""
    return float(digits.replace(",", ".")) if lang == "fr" else float(digits.replace(",", ""))


def _spaces(text: str, lang: str) -> str:
    """The text with no-break spaces as plain ones; in French, a space between digit
    groups ("1 200 milliards") is a thousands separator and is removed."""
    plain = text.replace("\xa0", " ").replace("\u202f", " ")
    return re.sub(r"(?<=\d) (?=\d{3}\b)", "", plain) if lang == "fr" else plain


def parse_amount(text: str, lang: str) -> float | None:
    """'0.20 billion' (en) or '0,20 milliards' (fr) as dollars; '1,200 million' is 1.2e9.

    None when the scale word is not one we know: reading "0.20 trillion" or a
    bare "0.20" as dollars would be off by a factor of a million or more.
    """
    match = re.search(r"([\d.,]+)\s*([a-z]+)", _spaces(text, lang).lower())
    if match is None or match.group(2) not in _SCALE:
        return None
    return round(_to_float(match.group(1), lang) * _SCALE[match.group(2)], 2)


def parse_percent(text: str, lang: str) -> float | None:
    match = re.search(r"([\d.,]+)\s*%", _spaces(text, lang))
    return _to_float(match.group(1), lang) if match else None


def _clean(node: Any) -> str:
    for sup in node.find_all("sup"):
        sup.decompose()
    return " ".join(node.get_text(" ").split())


def parse_tables(page: str, lang: str) -> list[list[ValueRow]]:
    """The page's tables; `lang` is the page's language, which decides what a comma means."""
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
                    value_as_published=cells[1],
                    value_cad=None if is_share else parse_amount(cells[1], lang),
                    share_percent=parse_percent(cells[1], lang) if is_share else None,
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
    headline = Headline(
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
    headline.not_found = [
        name for name, value in headline.model_dump(exclude={"not_found"}).items() if value is None
    ]
    return headline


def _unread_note(headline: Headline, tables: list[list[ValueRow]], lang: str) -> str | None:
    """Say which published figures could not be read, rather than leaving bare nulls."""
    unread = sum(
        1
        for table in tables
        for row in table
        if row.value_cad is None and row.share_percent is None and row.value_as_published
    )
    parts = []
    if headline.not_found:
        names = ", ".join(headline.not_found)
        parts.append(
            f"Les chiffres clés suivants n'ont pas été trouvés dans le texte de la page et sont "
            f"nuls : {names}"
            if lang == "fr"
            else f"These headline figures were not found in the page text and are null: {names}"
        )
    if unread:
        parts.append(
            f"Valeurs de tableau qui n'ont pas pu être lues (voir value_as_published) : {unread}"
            if lang == "fr"
            else f"Table values that could not be read (see value_as_published): {unread}"
        )
    return join_limits(*parts)


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


async def _page(lang: str, msg_lang: str = "en") -> tuple[str, bool]:
    """One edition of the page; `msg_lang` is the language of any error."""
    url = constants.PAGE_URLS[lang]

    async def fetch() -> str:
        # Streamed under MAX_PAGE_BYTES and kept to ISED's own host on every
        # redirect hop (the older edition's URL redirects here). The shared
        # download writes its errors in the call's language, so set it to msg_lang.
        token = set_call_lang(msg_lang)
        try:
            downloaded = await file_download.download(
                url,
                allow_host=lambda host: host == constants.HOST,
                limiter_for=lambda _host: _LIMITER,
                max_bytes=constants.MAX_PAGE_BYTES,
                context="ised_clean_growth",
                timeout=60.0,
            )
        finally:
            reset_call_lang(token)
        headers = {"content-type": downloaded.content_type}
        return httpx.Response(200, headers=headers, content=downloaded.body).text

    return await cached_fetch(f"ised-clean-growth:{lang}", constants.CACHE_TTL_SECONDS, fetch)


async def federal_investment(lang: str = "en") -> FederalInvestment:
    if lang not in constants.PAGE_URLS:
        raise InvalidInput(f"ised_clean_growth: lang must be 'en' or 'fr', got {lang!r}.")
    # The headline figures are read from the English prose (see module docstring).
    english, cached = await _page("en", lang)
    page, page_cached = (english, cached) if lang == "en" else await _page(lang, lang)
    tables = parse_tables(page, lang)
    if len(tables) < 3 or not all(tables[:3]):
        _raise(
            UpstreamError,
            "ised_clean_growth: the investment page no longer has its three data tables.",
            "ised_clean_growth : la page des investissements n'a plus ses trois tableaux "
            "de données.",
            lang,
        )
    headline = parse_headline(english)
    freshness = _FRESHNESS[lang]
    limits = join_limits(_LIMITS[lang], _unread_note(headline, tables[:3], lang)) or ""
    if lang == "fr":
        freshness, limits = french_spacing(freshness), french_spacing(limits)
    return FederalInvestment(
        headline=headline,
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
            freshness=freshness,
            limits=limits,
            lang=lang,
        ),
    )
