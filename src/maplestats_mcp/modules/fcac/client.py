"""Client for FCAC's Credit Card Comparison Tool and Account Comparison Tool.

Both tools (itools-ioutils.fcac-acfc.gc.ca/CCCT-OCCC/ and /ACT-OCC/) are
ASP.NET WebForms applications with no JSON API and no download. What
follows was confirmed live on 2026-09-26 with plain HTTP requests, in
English and French:

1. A search is a GET of `SearchFilter-{eng|fra}.aspx` (it sets the
   `ASP.NET_SessionId` cookie and carries `__VIEWSTATE` and
   `__EVENTVALIDATION`), then a POST of those hidden fields plus the
   filter fields and the Search button. The server answers 302 to
   `SearchResult-{lang}.aspx`. The results live in the server-side
   session, so each call here uses its own client and cookie jar.
2. Province values are numeric and differ between the two tools; posting
   a province code such as "ON" redirects to `Error.aspx`. A request
   without its session (a GET of `ProductDetail-eng.aspx` in a fresh
   session) redirects to `SessionExpired-eng.aspx`. Both are treated as a
   lost session: the whole search is retried once in a new session, then
   the call fails.
3. Results come ten per page with a DataPager: the current page is a
   `<span class="btn btn-primary">`, other pages are `__doPostBack`
   links, and "..." links jump to the next or previous block of five.
   The page count label (`lblSearchResultNumber`, "95 results match your
   filters" / "61 résultats correspondent à vos filtres") is checked
   against the product ids collected, so a short walk is never cached.
4. Each product row carries its id in a hidden `hfProductID` input (the
   same id in both languages) and a "View details" submit button; the
   detail page is only reachable by posting that button from the page
   the row is on. There is no URL for a product.
5. Detail pages are blocks of a grey title (`span` whose id names the
   section, e.g. `lblAnnualFeeTitle`, `lblInteresrRateTitle` with the
   site's own typo) and a value area where labelled items are
   `<strong>Label: </strong>value`. Section keys come from those ids, so
   they are the same in both languages; labels and values are shown in
   the requested language.
6. The French pages format numbers as "30,95 $", "6 000,00 $" and
   "10,9000 %"; the English ones as "$30.95", "$6,000.00" and "10.9000%".
   French result order can differ from English for equal fees, because
   ties are sorted by the translated names.
7. The credit card form hides "student" and "secured card" behind "Show
   more optional filters" (another postback). Defaults are No; student
   Yes added 6 student cards to Ontario's 95, and secured Yes returned
   the 25 secured cards instead. "Carry a balance" did not change the
   list (95 either way), so it is not exposed.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup, Tag
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from maplestats_mcp.modules.fcac import constants
from maplestats_mcp.modules.fcac.schemas import (
    AccountDetail,
    AccountSearchResult,
    AccountSummary,
    CreditCardDetail,
    CreditCardSearchResult,
    CreditCardSummary,
    DetailItem,
    DetailSection,
)
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable
from maplestats_mcp.shared.http import is_retryable, new_client
from maplestats_mcp.shared.rate_limiter import get_limiter

_LIMITER = get_limiter(
    constants.RATE_LIMIT_SOURCE,
    rate=constants.RATE_LIMIT_PER_SECOND,
    capacity=constants.RATE_LIMIT_CAPACITY,
)
_P = constants.FIELD_PREFIX

Kind = Literal["cards", "accounts"]


class _SessionLost(Exception):
    """The tool answered with its session-expired or error page."""


@dataclass(frozen=True)
class _Row:
    product_id: str
    button: str
    tag: Tag


# --------------------------------------------------------------------- http


def _page_url(kind: Kind, page: str, lang: str) -> str:
    path = constants.CARDS_PATH if kind == "cards" else constants.ACCOUNTS_PATH
    return f"{constants.BASE_URL}{path}{page}-{constants.PAGE_LANG[lang]}.aspx"


@retry(
    retry=retry_if_exception(is_retryable),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    reraise=True,
)
async def _request(
    http: httpx.AsyncClient, method: str, url: str, data: dict[str, str] | None
) -> httpx.Response:
    response = await http.request(method, url, data=data)
    response.raise_for_status()
    return response


async def _send(
    http: httpx.AsyncClient, method: str, url: str, data: dict[str, str] | None = None
) -> tuple[httpx.Response, BeautifulSoup]:
    await _LIMITER.acquire()
    try:
        response = await _request(http, method, url, data)
    except httpx.HTTPStatusError as exc:
        raise UpstreamError(
            f"fcac: {exc.request.url} returned HTTP {exc.response.status_code}."
        ) from exc
    except httpx.HTTPError as exc:
        raise UpstreamUnavailable(f"fcac: {url} did not respond in time.") from exc
    path = response.url.path.lower()
    if "sessionexpired" in path or path.endswith("/error.aspx"):
        raise _SessionLost(str(response.url))
    return response, BeautifulSoup(response.text, "html.parser")


def _form_state(soup: BeautifulSoup, base_url: str) -> tuple[str, dict[str, str], dict[str, str]]:
    """The WebForms form's action URL, hidden fields and submit-button values."""
    form = None
    for candidate in soup.find_all("form"):
        if candidate.find("input", attrs={"name": "__VIEWSTATE"}) is not None:
            form = candidate
            break
    if form is None:
        raise _SessionLost("no WebForms form on the page")
    action = str(form.get("action") or "")
    hidden: dict[str, str] = {}
    buttons: dict[str, str] = {}
    for field in form.find_all("input"):
        name = field.get("name")
        if not isinstance(name, str):
            continue
        kind = str(field.get("type") or "").lower()
        if kind == "hidden":
            hidden[name] = str(field.get("value") or "")
        elif kind == "submit":
            buttons[name] = str(field.get("value") or "")
    return urljoin(base_url, action), hidden, buttons


async def _click(
    http: httpx.AsyncClient,
    response: httpx.Response,
    soup: BeautifulSoup,
    *,
    button: str | None = None,
    target: str | None = None,
    fields: dict[str, str] | None = None,
) -> tuple[httpx.Response, BeautifulSoup]:
    """Post the page's form back, as a submit button or a __doPostBack link."""
    action, data, buttons = _form_state(soup, str(response.url))
    # Hidden per-row fields (product ids) are part of the form; posting them
    # back unchanged is what a browser does.
    data.update(fields or {})
    if button is not None:
        data[button] = buttons.get(button, "Search")
    if target is not None:
        data["__EVENTTARGET"] = target
        data["__EVENTARGUMENT"] = ""
    return await _send(http, "POST", action, data)


# ------------------------------------------------------------------ parsing


def _text(node: Any) -> str:
    if node is None:
        return ""
    raw = node.get_text(" ") if isinstance(node, Tag) else str(node)
    return " ".join(raw.replace(" ", " ").split())


def _numbers(text: str, lang: str) -> list[float]:
    """Every number in `text`, read with the language's separators."""
    if lang == "fr":
        found = re.findall(r"\d{1,3}(?:[   ]\d{3})+(?:,\d+)?|\d+(?:,\d+)?", text)
        return [float(re.sub(r"[   ]", "", n).replace(",", ".")) for n in found]
    found = re.findall(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?", text)
    return [float(n.replace(",", "")) for n in found]


_NO_FEE = re.compile(r"^\s*(no\b|none\b|aucun|sans\b)", re.IGNORECASE)


def _amount(text: str, lang: str) -> float | None:
    """A dollar amount; 0 for "No annual fee" / "Aucun frais annuel"."""
    numbers = _numbers(text, lang)
    if numbers:
        return numbers[0]
    return 0.0 if _NO_FEE.match(text) else None


def _rates(text: str, lang: str) -> list[float]:
    pattern = r"(\d+(?:,\d+)?)\s*%" if lang == "fr" else r"(\d+(?:\.\d+)?)\s*%"
    return [float(n.replace(",", ".")) for n in re.findall(pattern, text)]


def _result_count(soup: BeautifulSoup) -> int:
    label = soup.find(id=re.compile(r"lblSearchResultNumber$"))
    if label is None:
        raise _SessionLost("no result count on the results page")
    match = re.search(r"\d[\d\s ,]*", _text(label))
    if match is None:
        raise UpstreamError(f"fcac: unreadable result count {_text(label)!r}.")
    return int(re.sub(r"\D", "", match.group()))


def _rows(soup: BeautifulSoup) -> list[_Row]:
    rows: list[_Row] = []
    for hidden in soup.find_all("input", attrs={"name": re.compile(r"\$hfProductID$")}):
        row = hidden.find_parent("div", class_="row")
        if row is None:
            continue
        # Savings rows name it btnViewItemDetailSavings.
        button = row.find("input", attrs={"name": re.compile(r"\$btnViewItemDetail\w*$")})
        if button is None:
            continue
        rows.append(_Row(str(hidden.get("value") or ""), str(button.get("name")), row))
    return rows


def _by_id(row: Tag, name: str) -> Tag | None:
    return row.find(id=re.compile(rf"_{name}\w*_\d+$"))


def _row_name(row: Tag) -> str:
    strong = row.find("strong")
    return _text(strong)


def _card_summary(row: _Row, lang: str) -> CreditCardSummary:
    tag = row.tag
    fee_text = _text(_by_id(tag, "lblAnnualFee"))
    rate_text = _text(_by_id(tag, "lblPurchaseInterestRate"))
    rates = _rates(rate_text, lang)
    rewards_tag = _by_id(tag, "lblRewardsDisplay")
    rewards = [_text(s) for s in rewards_tag.find_all("span")] if rewards_tag else []
    return CreditCardSummary(
        product_id=row.product_id,
        name=_row_name(tag),
        institution=_text(_by_id(tag, "lblOrgName")),
        annual_fee=_amount(fee_text, lang),
        annual_fee_text=fee_text,
        purchase_rate=rates[0] if rates else None,
        purchase_rate_max=rates[1] if len(rates) > 1 else None,
        currency=_text(_by_id(tag, "lblCurrency")),
        rewards=[r for r in rewards if r],
    )


def _account_summary(row: _Row, lang: str) -> AccountSummary:
    tag = row.tag
    fee_text = _text(_by_id(tag, "lblMonthlyFee"))
    # Savings rows show an interest rate instead of a monthly fee
    # (lblInterestrateSavings, "1.8000% Interest rate" / "1,8000 % Taux d'intérêt").
    rate_text = _text(_by_id(tag, "lblInterestrate"))
    rates = _rates(rate_text, lang)
    currency = _by_id(tag, "lblCurrency")
    transactions: list[str] = []
    if currency is not None and isinstance(currency.parent, Tag):
        # The bullet list holds the fee or rate, zero to three transaction
        # lines (ids Label2, Label3, lblInbranchTransactions, ...) and the currency.
        for span in currency.parent.find_all("span", id=True):
            span_id = str(span.get("id"))
            if any(k in span_id for k in ("lblMonthlyFee", "lblCurrency", "lblInterestrate")):
                continue
            if line := _text(span):
                transactions.append(line)
    return AccountSummary(
        product_id=row.product_id,
        name=_row_name(tag),
        institution=_text(_by_id(tag, "lblOrgName")),
        low_cost_no_cost=_by_id(tag, "hlLowCostNoCostSiteLink") is not None,
        monthly_fee=_amount(fee_text, lang) if fee_text else None,
        monthly_fee_text=fee_text or None,
        interest_rate=rates[0] if rates else None,
        interest_rate_text=rate_text or None,
        transactions=transactions,
        currency=_text(currency),
    )


def _next_page_target(soup: BeautifulSoup) -> str | None:
    """The __doPostBack target of the page after the current one, if any."""
    pager = soup.find("span", id=re.compile(r"_dp\w+Result$"))
    if pager is None:
        return None
    current: int | None = None
    ellipsis_after: str | None = None
    for node in pager.find_all(["a", "span"]):
        classes = node.get("class") or []
        label = _text(node)
        if node.name == "span" and "btn-primary" in classes and label.isdigit():
            current = int(label)
            continue
        if node.name != "a" or current is None:
            continue
        match = re.search(r"__doPostBack\('([^']+)'", str(node.get("href") or ""))
        if match is None:
            continue
        if label == str(current + 1):
            return match.group(1)
        if label == "..." and ellipsis_after is None:
            ellipsis_after = match.group(1)
    return ellipsis_after


# Section keys from element ids that do not name their section.
_KEY_ALIASES = {"currency_name": "currency", "label1": "account_history"}


def _section_key(element_id: str) -> str:
    key = element_id.rsplit("_", 1)[-1]
    key = key.removeprefix("lbl").removesuffix("Title")
    key = key.replace("Interesr", "Interest").replace("Namve", "Name")
    key = re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", "_", key).lower()
    return _KEY_ALIASES.get(key, key)


def _items(area: Tag) -> list[DetailItem]:
    strongs = area.find_all("strong")
    if strongs:
        items: list[DetailItem] = []
        for strong in strongs:
            label = _text(strong).rstrip(": ").strip()
            parts: list[str] = []
            for sibling in strong.next_siblings:
                if isinstance(sibling, Tag) and sibling.name in ("strong", "div"):
                    break
                parts.append(_text(sibling))
            items.append(DetailItem(label=label, value=" ".join(p for p in parts if p)))
        return items
    lines = [" ".join(line.split()) for line in area.get_text("\n").split("\n")]
    items = [DetailItem(value=line) for line in lines if line]
    link = area.find("a", href=True)
    if link is not None and items:
        # The product page cell shows a shortened URL; keep the real link.
        items[0] = DetailItem(value=str(link.get("href")))
    return items


def _sections(soup: BeautifulSoup) -> list[DetailSection]:
    sections: list[DetailSection] = []
    for header in soup.find_all("div", class_="bg-lightgrey"):
        title = header.find("span", id=True)
        area = header.find_next_sibling("div")
        if title is None or area is None:
            continue
        sections.append(
            DetailSection(
                key=_section_key(str(title.get("id"))), title=_text(title), items=_items(area)
            )
        )
    if not sections:
        raise _SessionLost("no detail sections on the product page")
    return sections


def _section(sections: Sequence[DetailSection], key: str) -> list[DetailItem]:
    for section in sections:
        if section.key == key:
            return section.items
    return []


def _item(items: Sequence[DetailItem], index: int) -> str:
    return items[index].value if len(items) > index else ""


def _first_rate(text: str, lang: str) -> float | None:
    rates = _rates(text, lang)
    return rates[0] if rates else None


def _card_detail(product_id: str, sections: list[DetailSection], lang: str) -> dict[str, Any]:
    fees = _section(sections, "annual_fee")
    rates = _section(sections, "interest_rate")
    income = _section(sections, "minimum_income_required")
    personal = _item(income, 0)
    household = _item(income, 1)
    return {
        "product_id": product_id,
        "name": _item(_section(sections, "product_name"), 0),
        "institution": _item(_section(sections, "name_of_bank"), 0),
        "currency": _item(_section(sections, "currency"), 0) or None,
        "product_url": _item(_section(sections, "product_url"), 0) or None,
        "annual_fee": _amount(_item(fees, 0), lang) if fees else None,
        "annual_fee_additional_card": _amount(_item(fees, 1), lang) if len(fees) > 1 else None,
        # The three rates come in this order in both languages: purchase,
        # cash advance, balance transfers.
        "purchase_rate": _first_rate(_item(rates, 0), lang),
        "cash_advance_rate": _first_rate(_item(rates, 1), lang),
        "balance_transfer_rate": _first_rate(_item(rates, 2), lang),
        "foreign_conversion_fee": _first_rate(
            _item(_section(sections, "foreign_conversion_fee"), 0), lang
        ),
        # "Not required" / "Non requis" has no number and stays null.
        "minimum_personal_income": (_numbers(personal, lang) or [None])[0],
        "minimum_household_income": (_numbers(household, lang) or [None])[0],
        "rewards": [i.value for i in _section(sections, "rewards")],
    }


def _account_detail(product_id: str, sections: list[DetailSection], lang: str) -> dict[str, Any]:
    fee = _section(sections, "monthly_fee")
    nsf = _section(sections, "nsf_fees")
    return {
        "product_id": product_id,
        "name": _item(_section(sections, "product_name"), 0),
        "institution": _item(_section(sections, "name_of_bank"), 0),
        "currency": _item(_section(sections, "currency"), 0) or None,
        "product_url": _item(_section(sections, "product_url"), 0) or None,
        "monthly_fee": _amount(_item(fee, 0), lang) if fee else None,
        "monthly_fee_notes": [i.value for i in fee[1:] if i.value],
        "included_transactions": _section(sections, "included_transaction"),
        # Savings accounts list one item per balance tier.
        "interest_rates": [i.value for i in _section(sections, "interest_rate") if i.value],
        "nsf_fee": _amount(_item(nsf, 0), lang) if nsf else None,
    }


# ------------------------------------------------------------------ sessions


def _search_fields(
    kind: Kind,
    province: str,
    currency: str,
    *,
    student: bool = False,
    secured: bool = False,
    account_type: str = "chequing",
    groups: Sequence[str] = (),
) -> tuple[dict[str, str], bool]:
    """Form fields for a search, and whether the optional filters must be shown."""
    if kind == "cards":
        fields = {
            _P + "ddlProvince": constants.CARD_PROVINCES[province],
            _P + "rblCurrency": constants.CARD_CURRENCIES[currency],
            _P + "rblCarryBalance": "No",
        }
        more = student or secured
        if more:
            fields[_P + "rblAreYouaStudent"] = "Yes" if student else "No"
            fields[_P + "rblLookingForSecuredCard"] = "Yes" if secured else "No"
        return fields, more
    fields = {
        _P + "ddlProvince": constants.ACCOUNT_PROVINCES[province],
        _P + "rblAccountType": constants.ACCOUNT_TYPES[account_type],
        _P + "rblCurrency": constants.ACCOUNT_CURRENCIES[currency],
    }
    for group in groups:
        index, value = constants.ACCOUNT_GROUPS[group]
        fields[f"{_P}cblDemographic${index}"] = value
    return fields, False


async def _open_results(
    http: httpx.AsyncClient, kind: Kind, lang: str, fields: dict[str, str], more: bool
) -> tuple[httpx.Response, BeautifulSoup]:
    response, soup = await _send(http, "GET", _page_url(kind, "SearchFilter", lang))
    if more:
        response, soup = await _click(
            http,
            response,
            soup,
            button=_P + "btnShowMoreFilters",
            fields={_P + "ddlProvince": fields[_P + "ddlProvince"]},
        )
    response, soup = await _click(http, response, soup, button=_P + "btnSearch", fields=fields)
    _result_count(soup)  # raises _SessionLost when this is not a result list
    return response, soup


def _client() -> httpx.AsyncClient:
    return new_client(follow_redirects=True, timeout=constants.REQUEST_TIMEOUT_SECONDS)


async def _walk(
    kind: Kind, lang: str, fields: dict[str, str], more: bool
) -> tuple[int, list[_Row]]:
    async with _client() as http:
        response, soup = await _open_results(http, kind, lang, fields, more)
        total = _result_count(soup)
        rows: list[_Row] = []
        seen: set[str] = set()
        for _ in range(constants.MAX_RESULT_PAGES):
            for row in _rows(soup):
                if row.product_id not in seen:
                    seen.add(row.product_id)
                    rows.append(row)
            target = _next_page_target(soup)
            if target is None or len(rows) >= total:
                break
            response, soup = await _click(http, response, soup, target=target)
            _result_count(soup)
    if len(rows) != total:
        raise UpstreamError(
            f"fcac: the tool reported {total} products but {len(rows)} could be read."
        )
    return total, rows


async def _with_session_retry(func: Any, *args: Any) -> Any:
    try:
        return await func(*args)
    except _SessionLost:
        pass
    try:
        return await func(*args)
    except _SessionLost as exc:
        raise UpstreamError(
            f"fcac: the comparison tool lost the search session twice ({exc})."
        ) from exc


async def _detail_sections(
    kind: Kind, lang: str, fields: dict[str, str], more: bool, product_id: str
) -> list[DetailSection]:
    async with _client() as http:
        response, soup = await _open_results(http, kind, lang, fields, more)
        for _ in range(constants.MAX_RESULT_PAGES):
            hit = next((r for r in _rows(soup) if r.product_id == product_id), None)
            if hit is not None:
                response, soup = await _click(http, response, soup, button=hit.button)
                if "productdetail" not in response.url.path.lower():
                    raise _SessionLost(str(response.url))
                return _sections(soup)
            target = _next_page_target(soup)
            if target is None:
                break
            response, soup = await _click(http, response, soup, target=target)
            _result_count(soup)
    raise NotFound(f"fcac: product {product_id} is not in this result list.")


# ------------------------------------------------------------------- public


def _check(value: str, allowed: dict[str, Any], name: str) -> None:
    if value not in allowed:
        raise InvalidInput(f"{name} must be one of {sorted(allowed)}, got {value!r}.")


def _check_lang(lang: str) -> None:
    if lang not in constants.PAGE_LANG:
        raise InvalidInput(f"lang must be 'en' or 'fr', got {lang!r}.")


def _check_limit(limit: int) -> None:
    if not 1 <= limit <= constants.LIMIT_MAX:
        raise InvalidInput(f"limit must be between 1 and {constants.LIMIT_MAX}.")


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def _matches(query: str, *texts: str) -> bool:
    haystack = _fold(" ".join(texts))
    return all(word in haystack for word in _fold(query).split())


async def _cards_listing(
    province: str, currency: str, student: bool, secured: bool, lang: str
) -> tuple[tuple[int, list[CreditCardSummary]], bool]:
    fields, more = _search_fields("cards", province, currency, student=student, secured=secured)

    async def fetch() -> tuple[int, list[CreditCardSummary]]:
        total, rows = await _with_session_retry(_walk, "cards", lang, fields, more)
        return total, [_card_summary(r, lang) for r in rows]

    key = f"fcac:cards:{lang}:{province}:{currency}:{int(student)}:{int(secured)}"
    return await cached_fetch(key, constants.CACHE_TTL_SECONDS, fetch)


async def _accounts_listing(
    province: str, account_type: str, currency: str, groups: Sequence[str], lang: str
) -> tuple[tuple[int, list[AccountSummary]], bool]:
    fields, more = _search_fields(
        "accounts", province, currency, account_type=account_type, groups=groups
    )

    async def fetch() -> tuple[int, list[AccountSummary]]:
        total, rows = await _with_session_retry(_walk, "accounts", lang, fields, more)
        return total, [_account_summary(r, lang) for r in rows]

    key = f"fcac:accounts:{lang}:{province}:{account_type}:{currency}:{','.join(groups)}"
    return await cached_fetch(key, constants.CACHE_TTL_SECONDS, fetch)


def _reward_labels(rewards: Sequence[str]) -> list[set[str]]:
    wanted = []
    for reward in rewards:
        _check(reward, constants.REWARD_LABELS, "rewards")
        wanted.append({_fold(label) for label in constants.REWARD_LABELS[reward]})
    return wanted


def _provenance(kind: Kind, lang: str, cached: bool, schema: str, limits: str | None = None):
    return make_provenance(
        source="fcac",
        url=_page_url(kind, "SearchFilter", lang),
        cached=cached,
        schema_name=schema,
        freshness=constants.FRESHNESS,
        coverage=constants.CARDS_COVERAGE if kind == "cards" else constants.ACCOUNTS_COVERAGE,
        limits=limits,
    )


async def search_credit_cards(
    province: str,
    *,
    currency: str = "CAD",
    student: bool = False,
    secured: bool = False,
    query: str = "",
    institution: str = "",
    max_annual_fee: float | None = None,
    max_purchase_rate: float | None = None,
    rewards: Sequence[str] = (),
    sort: str | None = None,
    limit: int = constants.LIMIT_DEFAULT,
    lang: str = "en",
) -> CreditCardSearchResult:
    _check(province, constants.CARD_PROVINCES, "province")
    _check(currency, constants.CARD_CURRENCIES, "currency")
    _check_lang(lang)
    _check_limit(limit)
    if sort not in (None, "annual_fee", "purchase_rate", "institution", "name"):
        raise InvalidInput(
            "sort must be one of 'annual_fee', 'purchase_rate', 'institution', 'name'."
        )
    wanted = _reward_labels(rewards)

    (total, cards), cached = await _cards_listing(province, currency, student, secured, lang)
    matched = []
    for card in cards:
        if query and not _matches(query, card.name, card.institution):
            continue
        if institution and not _matches(institution, card.institution):
            continue
        if max_annual_fee is not None and (
            card.annual_fee is None or card.annual_fee > max_annual_fee
        ):
            continue
        if max_purchase_rate is not None and (
            card.purchase_rate is None or card.purchase_rate > max_purchase_rate
        ):
            continue
        folded = {_fold(r) for r in card.rewards}
        if any(not (labels & folded) for labels in wanted):
            continue
        matched.append(card)
    if sort == "annual_fee":
        matched.sort(key=lambda c: (c.annual_fee is None, c.annual_fee or 0.0))
    elif sort == "purchase_rate":
        matched.sort(key=lambda c: (c.purchase_rate is None, c.purchase_rate or 0.0))
    elif sort == "institution":
        matched.sort(key=lambda c: (_fold(c.institution), _fold(c.name)))
    elif sort == "name":
        matched.sort(key=lambda c: _fold(c.name))
    returned = matched[:limit]
    return CreditCardSearchResult(
        province=province,  # type: ignore[arg-type]
        currency=currency,  # type: ignore[arg-type]
        student=student,
        secured=secured,
        total_listed=total,
        total_matched=len(matched),
        returned_count=len(returned),
        cards=returned,
        provenance=_provenance(
            "cards",
            lang,
            cached,
            "fcac.CreditCardSearchResult",
            limits=f"first {len(returned)} of {len(matched)} matching cards"
            if len(returned) < len(matched)
            else None,
        ),
    )


async def get_credit_card(
    product_id: str,
    province: str,
    *,
    currency: str = "CAD",
    student: bool = False,
    secured: bool = False,
    lang: str = "en",
) -> CreditCardDetail:
    _check(province, constants.CARD_PROVINCES, "province")
    _check(currency, constants.CARD_CURRENCIES, "currency")
    _check_lang(lang)
    product_id = product_id.strip().lower()
    if not re.fullmatch(r"[0-9a-f-]{36}", product_id):
        raise InvalidInput("product_id must be an FCAC product id from fcac_search_credit_cards.")
    (_, cards), _ = await _cards_listing(province, currency, student, secured, lang)
    if product_id not in {c.product_id for c in cards}:
        raise NotFound(
            f"credit card {product_id} is not listed for {province} ({currency}, student="
            f"{student}, secured={secured}); pass the options used in the search."
        )
    fields, more = _search_fields("cards", province, currency, student=student, secured=secured)

    async def fetch() -> list[DetailSection]:
        return await _with_session_retry(_detail_sections, "cards", lang, fields, more, product_id)

    key = f"fcac:card:{lang}:{province}:{currency}:{int(student)}:{int(secured)}:{product_id}"
    sections, cached = await cached_fetch(key, constants.CACHE_TTL_SECONDS, fetch)
    return CreditCardDetail(
        **_card_detail(product_id, sections, lang),
        sections=sections,
        provenance=_provenance("cards", lang, cached, "fcac.CreditCardDetail"),
    )


async def search_bank_accounts(
    province: str,
    *,
    account_type: str = "chequing",
    currency: str = "CAD",
    groups: Sequence[str] = (),
    query: str = "",
    institution: str = "",
    max_monthly_fee: float | None = None,
    low_cost_only: bool = False,
    sort: str | None = None,
    limit: int = constants.LIMIT_DEFAULT,
    lang: str = "en",
) -> AccountSearchResult:
    _check(province, constants.ACCOUNT_PROVINCES, "province")
    _check(account_type, constants.ACCOUNT_TYPES, "account_type")
    _check(currency, constants.ACCOUNT_CURRENCIES, "currency")
    for group in groups:
        _check(group, constants.ACCOUNT_GROUPS, "groups")
    _check_lang(lang)
    _check_limit(limit)
    if sort not in (None, "monthly_fee", "institution", "name"):
        raise InvalidInput("sort must be one of 'monthly_fee', 'institution', 'name'.")
    ordered_groups = sorted(set(groups), key=lambda g: constants.ACCOUNT_GROUPS[g][0])

    (total, accounts), cached = await _accounts_listing(
        province, account_type, currency, ordered_groups, lang
    )
    matched = []
    for account in accounts:
        if query and not _matches(query, account.name, account.institution):
            continue
        if institution and not _matches(institution, account.institution):
            continue
        if max_monthly_fee is not None and (
            account.monthly_fee is None or account.monthly_fee > max_monthly_fee
        ):
            continue
        if low_cost_only and not account.low_cost_no_cost:
            continue
        matched.append(account)
    if sort == "monthly_fee":
        matched.sort(key=lambda a: (a.monthly_fee is None, a.monthly_fee or 0.0))
    elif sort == "institution":
        matched.sort(key=lambda a: (_fold(a.institution), _fold(a.name)))
    elif sort == "name":
        matched.sort(key=lambda a: _fold(a.name))
    returned = matched[:limit]
    return AccountSearchResult(
        province=province,  # type: ignore[arg-type]
        account_type=account_type,  # type: ignore[arg-type]
        currency=currency,  # type: ignore[arg-type]
        groups=ordered_groups,  # type: ignore[arg-type]
        total_listed=total,
        total_matched=len(matched),
        returned_count=len(returned),
        accounts=returned,
        provenance=_provenance(
            "accounts",
            lang,
            cached,
            "fcac.AccountSearchResult",
            limits=f"first {len(returned)} of {len(matched)} matching accounts"
            if len(returned) < len(matched)
            else None,
        ),
    )


async def get_bank_account(
    product_id: str,
    province: str,
    *,
    account_type: str = "chequing",
    currency: str = "CAD",
    groups: Sequence[str] = (),
    lang: str = "en",
) -> AccountDetail:
    _check(province, constants.ACCOUNT_PROVINCES, "province")
    _check(account_type, constants.ACCOUNT_TYPES, "account_type")
    _check(currency, constants.ACCOUNT_CURRENCIES, "currency")
    for group in groups:
        _check(group, constants.ACCOUNT_GROUPS, "groups")
    _check_lang(lang)
    product_id = product_id.strip().lower()
    if not re.fullmatch(r"[0-9a-f-]{36}", product_id):
        raise InvalidInput("product_id must be an FCAC product id from fcac_search_bank_accounts.")
    ordered_groups = sorted(set(groups), key=lambda g: constants.ACCOUNT_GROUPS[g][0])
    (_, accounts), _ = await _accounts_listing(
        province, account_type, currency, ordered_groups, lang
    )
    if product_id not in {a.product_id for a in accounts}:
        raise NotFound(
            f"{account_type} account {product_id} is not listed for {province} ({currency}, "
            f"groups={ordered_groups}); pass the options used in the search."
        )
    fields, more = _search_fields(
        "accounts", province, currency, account_type=account_type, groups=ordered_groups
    )

    async def fetch() -> list[DetailSection]:
        return await _with_session_retry(
            _detail_sections, "accounts", lang, fields, more, product_id
        )

    key = (
        f"fcac:account:{lang}:{province}:{account_type}:{currency}:"
        f"{','.join(ordered_groups)}:{product_id}"
    )
    sections, cached = await cached_fetch(key, constants.CACHE_TTL_SECONDS, fetch)
    return AccountDetail(
        account_type=account_type,  # type: ignore[arg-type]
        **_account_detail(product_id, sections, lang),
        sections=sections,
        provenance=_provenance("accounts", lang, cached, "fcac.AccountDetail"),
    )
