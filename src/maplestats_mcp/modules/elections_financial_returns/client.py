"""Client for Elections Canada's Political Financing candidate financial-
return search (www.elections.ca/WPAPPS/WPF/EN/CC/), scoped to the
"Candidates" political entity -- see the module docstring for why the
other four entity types are out of scope.

This is a legacy ASP.NET MVC app with no documented public API. Every
behavior below was confirmed live 2026-09-21 with a raw `curl` cookie
jar (not just this client), so none of it depends on browser-specific
quirks:

- A bare POST to `CC/Index?...` with no prior GET on that exact URL
  silently returns the empty search form again (474-byte response, no
  `#foundcnt`/`#SelectedClientIds` results) rather than erroring --
  this deployment requires a warm-up GET on the same URL first to
  establish its ASP.NET session cookie before a POST is honoured. This
  module keeps its own `httpx.AsyncClient` (not `shared/http.py`'s
  shared one, the same justified exception used by
  `modules/statcan/reference/client.py`) so the cookie jar persists
  across the warm-up, search, select, and download steps of one call.
- **Candidate search** is a POST to `CC/Index?act=...&selectedEvent=...
  &reportOption=2&returnStatus=...&selectedReportType=...
  &displayIntroduction=False&displayDescription=False`, form body
  `ReturnStatus`, `ReportOption`, `EntityLastName`, `EntityFirstName`,
  `SelectedPartyIds`, `SelectedProvinceId`, `SelectedDistrictId`,
  `EdaSelectedProvinceId` (each `-1` for "no filter"), and
  `AddCandidates=Find Candidates`. No anti-forgery token is required
  (checked for and genuinely absent from the form). The response is
  the same page re-rendered with a populated `<select id=
  "SelectedClientIds">` -- one `<option value="{client_id}">{Last},
  {First} / {Party} / {District}</option>` per match, plus `#foundcnt`
  for the true total. Confirmed live: an unfiltered search on the 45th
  general election returned 1,926 candidates in this one unpaginated
  response -- `constants.CANDIDATE_SEARCH_MAX` caps what this module
  returns to a caller; narrow with `last_name`/`party_id`/
  `province_id` rather than relying on that cap.
- **Selecting candidate(s) for a report** is a second POST to the same
  URL, body `SelectedClientIds={client_id}&SearchSelected=Search
  Selected` (plus the same `ReturnStatus`/`ReportOption`). This
  responds with an HTTP 302 to
  `CC/DetailedReport?...&queryId={guid}&selectedPart=1` -- the `guid`
  is this server-side session's report handle, confirmed live to be
  meaningless without the cookies from the session that created it
  (reusing a captured `queryId` from a different cookie jar redirects
  straight back to the search form with HTTP 302, not an error status).
- Confirmed live: `CC/Download?...&queryId=...&selectedPart=...
  &downloadFormat=3` (JSON; 1=CSV, 4=XML also exist but were not
  pursued here) only succeeds after the `queryId`'s `DetailedReport`
  page has actually been fetched once with a GET -- attempting the
  Download step immediately after the 302 from the select-candidate
  POST, without that intermediate GET, itself redirects back to the
  search form. One `DetailedReport` GET per `queryId` is enough; every
  other `selectedPart` for the same `queryId` downloads directly
  afterward with no further `DetailedReport` visit needed (confirmed
  live across two different parts in the same session).
- The downloaded JSON is genuine, well-formed JSON -- no HTML to parse
  for this step -- but its second-level shape is **not fixed across
  parts**: every part has an `EXPORT_HEADER` array, but the row data
  itself comes back under a different key depending on the part
  (`DETAIL_DATA` alone for Part 1/2f/6-summary-shaped parts;
  `GROUP_DATA` + `DETAIL_DATA` + `TOTAL_DATA` for Part 2a/3a's
  transaction-list parts; `SUMMARY_DATA` for Part 6), confirmed live
  across five different parts for the same candidate. `sections` below
  keeps every key present in the response rather than assuming one
  fixed shape.
- `returnStatus` and `selectedPart` on the Download call are read
  fresh per request, independent of what the `queryId`'s session was
  originally created with -- confirmed live by downloading the same
  `queryId` with `returnStatus=2` after it was created under
  `returnStatus=1`, which succeeded and returned Elections Canada's
  reviewed data instead of an error. Only the *candidate selection*
  itself is bound to the `queryId`'s session.
"""

from __future__ import annotations

import json
import re
from urllib.parse import urlencode

import httpx
from bs4 import BeautifulSoup

from maplestats_mcp.modules.elections_financial_returns import constants
from maplestats_mcp.modules.elections_financial_returns.schemas import (
    Candidate,
    CandidateSearchResult,
    ElectionList,
    ElectionOption,
    FilterOption,
    FinancialReturnPart,
)
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable
from maplestats_mcp.shared.http import new_client
from maplestats_mcp.shared.rate_limiter import get_limiter

_LIMITER = get_limiter(
    constants.RATE_LIMIT_SOURCE,
    rate=constants.RATE_LIMIT_PER_SECOND,
    capacity=constants.RATE_LIMIT_CAPACITY,
)

_client = new_client(http2=False)
_warmed: set[str] = set()


def _resolve(mapping: dict[str, str], value: str, name: str) -> str:
    try:
        return mapping[value]
    except KeyError as exc:
        raise InvalidInput(f"{name} must be one of {sorted(mapping)}, got {value!r}.") from exc


def _search_url(
    act_code: str, election_id: str, report_code: str, status_code: str, lang: str = "en"
) -> str:
    return (
        f"{constants.BASE_URLS[lang]}/Index?act={act_code}&selectedEvent={election_id}"
        f"&reportOption={constants.REPORT_OPTION_COMPLETE}&returnStatus={status_code}"
        f"&selectedReportType={report_code}&displayIntroduction=False&displayDescription=False"
    )


def _decode(content: bytes) -> str:
    """The Download JSON's bytes, decoded without trusting httpx's guess.

    The response names no charset, and httpx's fallback turned accented
    names into U+FFFD replacement characters (live 2026-10-03: the
    "Association libérale provinciale Orléans" supplier in part 3A of
    client 56572, election 62).
    UTF-8 is tried first; other elections.ca files are Windows-1252, the
    fallback when the bytes are not valid UTF-8.
    """
    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError:
        return content.decode("cp1252")


async def _warm_up(url: str, *, force: bool = False) -> None:
    if url in _warmed and not force:
        return
    try:
        response = await _client.get(url)
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise UpstreamError(
            "elections_financial_returns returned HTTP "
            f"{exc.response.status_code} during session warm-up."
        ) from exc
    except httpx.HTTPError as exc:
        raise UpstreamUnavailable(
            "elections_financial_returns did not respond in time during session warm-up."
        ) from exc
    _warmed.add(url)


def _has_search_results(html: str) -> bool:
    """Whether a candidate-search POST was honoured.

    Confirmed live 2026-09-22: a genuine zero-match search still renders
    `<span id="foundcnt">0</span>`, while a POST the server ignores
    because the ASP.NET session is missing or expired renders only the
    empty search form with no `#foundcnt` at all. The process-level
    `_warmed` flag cannot see a server-side session expiry, so without
    this check an expired session would be returned (and cached) as a
    successful search with zero candidates.
    """
    return BeautifulSoup(html, "html.parser").find(id="foundcnt") is not None


def _parse_select_options(soup: BeautifulSoup, select_id: str) -> list[FilterOption]:
    select = soup.find("select", id=select_id)
    if select is None:
        return []
    options: list[FilterOption] = []
    for option in select.find_all("option"):
        value = option.get("value")
        if not isinstance(value, str) or value == "-1":
            continue
        options.append(FilterOption(id=value, label=option.get_text(strip=True)))
    return options


def _parse_candidates(
    html: str,
) -> tuple[list[Candidate], int, list[FilterOption], list[FilterOption]]:
    soup = BeautifulSoup(html, "html.parser")

    total_found = 0
    found_span = soup.find(id="foundcnt")
    if found_span is not None:
        digits = re.sub(r"[^0-9]", "", found_span.get_text())
        total_found = int(digits) if digits else 0

    candidates: list[Candidate] = []
    select = soup.find("select", id="SelectedClientIds")
    if select is not None:
        for option in select.find_all("option"):
            value = option.get("value")
            if not isinstance(value, str) or not value:
                continue
            text = option.get_text(strip=True)
            # Confirmed live: "Last, First / Party / Electoral District" --
            # capped to 3 parts, since neither a party nor a district name
            # is expected to contain the literal " / " separator itself.
            parts = text.split(" / ", 2)
            if len(parts) != 3:
                continue
            name_part, party, district = parts
            if ", " in name_part:
                last_name, first_name = name_part.split(", ", 1)
            else:
                last_name, first_name = name_part, ""
            candidates.append(
                Candidate(
                    client_id=value,
                    last_name=last_name,
                    first_name=first_name,
                    party=party,
                    electoral_district=district,
                )
            )

    parties = _parse_select_options(soup, "PartyList")
    provinces = _parse_select_options(soup, "ProvinceList")
    return candidates, total_found, parties, provinces


async def list_elections(*, act: str = "after_2019", lang: str = "en") -> ElectionList:
    """List the general elections and by-elections available for a Candidates
    financial-return search under a given Canada Elections Act period.

    Discovered live rather than hardcoded, since new by-elections are added
    to this list over time (a 2026-04-13 by-election was already listed as
    upcoming when this module was built 2026-09-21).
    """
    act_code = _resolve(constants.ACT_PERIODS, act, "act")
    url = (
        f"{constants.HOME_URLS[lang]}/RefreshEventList"
        f"?selectedAct=CC_{act_code}&selectedEntityCode={constants.ENTITY_CODE_CANDIDATES}"
    )
    cache_key = f"elections-financial-returns:events:{lang}:{act_code}"

    async def fetch() -> list[ElectionOption]:
        await _LIMITER.acquire()
        try:
            response = await _client.get(url)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise UpstreamError(
                f"elections_financial_returns:list_elections returned HTTP "
                f"{exc.response.status_code}."
            ) from exc
        except httpx.HTTPError as exc:
            raise UpstreamUnavailable(
                "elections_financial_returns:list_elections did not respond in time."
            ) from exc
        # Confirmed live: this endpoint's JSON body is itself a JSON-encoded
        # string wrapping the actual array -- two decode passes are needed.
        try:
            inner = json.loads(response.text)
            entries = json.loads(inner)
        except (json.JSONDecodeError, TypeError) as exc:
            raise UpstreamError(
                "elections_financial_returns:list_elections returned an unexpected response shape."
            ) from exc
        options: list[ElectionOption] = []
        for entry in entries:
            value = entry.get("Value")
            text = entry.get("Text")
            if not value or value == "-1" or not text:
                continue
            group = entry.get("Group")
            group_name = group.get("Name") if isinstance(group, dict) else None
            options.append(ElectionOption(id=str(value), label=str(text), group=group_name))
        return options

    elections, was_cached = await cached_fetch(cache_key, constants.CACHE_TTL_SECONDS, fetch)
    return ElectionList(
        act=act,
        elections=elections,
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=url,
            cached=was_cached,
            schema_name="elections_financial_returns.ElectionList",
        ),
    )


async def _check_election(election_id: str, act: str, lang: str) -> None:
    """Refuse an election id the act period does not list.

    The portal answers an unknown selectedEvent with an ordinary empty
    result (live 2026-10-03: election "9999" gave "0 found"), which would
    read as "no candidates" rather than "no such election".
    """
    elections = (await list_elections(act=act, lang=lang)).elections
    if not any(e.id == election_id for e in elections):
        known = ", ".join(f"{e.id} ({e.label})" for e in elections[:8])
        raise NotFound(
            f"elections_financial_returns: no election {election_id!r} under act {act!r}; "
            f"see elections_financial_returns_list_elections (e.g. {known})."
        )


async def _search_html(url: str, form: dict[str, str]) -> tuple[str, bool]:
    """One candidate-search POST (cached), re-warming a lost session once."""
    cache_key = f"elections-financial-returns:search:{url}:{sorted(form.items())}"

    async def post_search() -> str:
        try:
            response = await _client.post(url, data=form)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise UpstreamError(
                f"elections_financial_returns:search_candidates returned HTTP "
                f"{exc.response.status_code}."
            ) from exc
        except httpx.HTTPError as exc:
            raise UpstreamUnavailable(
                "elections_financial_returns:search_candidates did not respond in time."
            ) from exc
        return response.text

    async def fetch() -> str:
        await _LIMITER.acquire()
        await _warm_up(url)
        html = await post_search()
        if _has_search_results(html):
            return html

        await _warm_up(url, force=True)
        html = await post_search()
        if not _has_search_results(html):
            _warmed.discard(url)
            raise UpstreamError(
                "elections_financial_returns:search_candidates: the portal returned its empty "
                "search form even after refreshing the session, so no results can be trusted. "
                "Try again shortly."
            )
        return html

    return await cached_fetch(cache_key, constants.CACHE_TTL_SECONDS, fetch)


def _search_form(
    status_code: str,
    lang: str,
    *,
    last_name: str = "",
    first_name: str = "",
    party_id: str = "-1",
    province_id: str = "-1",
    district_id: str = "-1",
) -> dict[str, str]:
    return {
        "ReturnStatus": status_code,
        "ReportOption": constants.REPORT_OPTION_COMPLETE,
        "EntityLastName": last_name.strip(),
        "EntityFirstName": first_name.strip(),
        "SelectedPartyIds": party_id,
        "SelectedProvinceId": province_id,
        "SelectedDistrictId": district_id,
        "EdaSelectedProvinceId": "-1",
        "AddCandidates": constants.FIND_BUTTON[lang],
    }


async def search_candidates(
    election_id: str,
    *,
    act: str = "after_2019",
    report_type: str = "campaign_returns",
    return_status: str = "submitted",
    last_name: str = "",
    first_name: str = "",
    party_id: str = "-1",
    province_id: str = "-1",
    district_id: str = "-1",
    offset: int = 0,
    limit: int | None = None,
    lang: str = "en",
) -> CandidateSearchResult:
    """Search Candidates for one election under a given Act period, returning
    each match's `client_id` for use with `get_financial_return_part`.

    `available_parties`/`available_provinces` in the result are the
    portal's own filter dropdown options for this act/election/report_type
    combination, parsed from the same response -- use their `id` values for
    `party_id`/`province_id` on a follow-up, narrower search. The portal
    returns every match in one response (1,927 for the 45th general
    election), so `offset`/`limit` page over that cached list.
    """
    act_code = _resolve(constants.ACT_PERIODS, act, "act")
    report_code = _resolve(constants.REPORT_TYPES, report_type, "report_type")
    status_code = _resolve(constants.RETURN_STATUS, return_status, "return_status")
    election_id = election_id.strip()
    if not election_id:
        raise InvalidInput("election_id must not be empty.")
    page_size = constants.CANDIDATE_SEARCH_MAX if limit is None else limit
    if not 1 <= page_size <= constants.CANDIDATE_SEARCH_MAX:
        raise InvalidInput(
            f"limit must be between 1 and {constants.CANDIDATE_SEARCH_MAX}, got {limit}."
        )
    if offset < 0:
        raise InvalidInput(f"offset must be 0 or more, got {offset}.")
    await _check_election(election_id, act, lang)

    url = _search_url(act_code, election_id, report_code, status_code, lang)
    form = _search_form(
        status_code,
        lang,
        last_name=last_name,
        first_name=first_name,
        party_id=party_id,
        province_id=province_id,
        district_id=district_id,
    )
    html, was_cached = await _search_html(url, form)
    candidates, total_found, parties, provinces = _parse_candidates(html)
    page = candidates[offset : offset + page_size]
    has_more = offset + len(page) < len(candidates)
    coverage = None
    if has_more or offset:
        coverage = f"candidates {offset + 1}-{offset + len(page)} of {len(candidates)}"
        if has_more:
            coverage += f"; next page: offset={offset + len(page)}"

    return CandidateSearchResult(
        election_id=election_id,
        candidates=page,
        returned_count=len(page),
        total_found=total_found,
        offset=offset,
        has_more=has_more,
        available_parties=parties,
        available_provinces=provinces,
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=url,
            cached=was_cached,
            schema_name="elections_financial_returns.CandidateSearchResult",
            coverage=coverage,
        ),
    )


async def _check_candidate_in_election(
    candidate_client_id: str, election_id: str, act_code: str, status_code: str, lang: str
) -> None:
    """Refuse a client id that is not a candidate in the requested election.

    The portal serves a candidate's return under any selectedEvent and labels
    it with that event (live 2026-10-03: client 56572 with election 53, the
    2021 general election, returned his 2025 Nepean return headed "44th
    general election"). The election's full candidate list (one cached
    search) settles it.
    """
    report_code = constants.REPORT_TYPES["campaign_returns"]
    url = _search_url(act_code, election_id, report_code, status_code, lang)
    html, _ = await _search_html(url, _search_form(status_code, lang))
    candidates, _total, _parties, _provinces = _parse_candidates(html)
    if not any(c.client_id == candidate_client_id for c in candidates):
        raise NotFound(
            f"elections_financial_returns: candidate {candidate_client_id!r} did not run in "
            f"election {election_id!r}; take client_id from "
            "elections_financial_returns_search_candidates for the same election."
        )


async def get_financial_return_part(
    candidate_client_id: str,
    part: str,
    *,
    election_id: str,
    act: str = "after_2019",
    return_status: str = "submitted",
    lang: str = "en",
) -> FinancialReturnPart:
    """Retrieve one part of a candidate's Complete Financial Return.

    `candidate_client_id` comes from a prior `search_candidates` call.
    `part` is one of the 13 codes in `constants.PART_LABELS` (e.g. "1" for
    the Declaration, "2A" for Contributions Received, "3A" for Expenses,
    "6" for the Bank Reconciliation).
    """
    candidate_client_id = candidate_client_id.strip()
    if not candidate_client_id:
        raise InvalidInput("candidate_client_id must not be empty.")
    part_code = part.strip().upper()
    if part_code not in constants.PART_LABELS:
        raise InvalidInput(f"part must be one of {sorted(constants.PART_LABELS)}, got {part!r}.")
    act_code = _resolve(constants.ACT_PERIODS, act, "act")
    status_code = _resolve(constants.RETURN_STATUS, return_status, "return_status")
    election_id = election_id.strip()
    if not election_id:
        raise InvalidInput("election_id must not be empty.")
    await _check_election(election_id, act, lang)
    await _check_candidate_in_election(
        candidate_client_id, election_id, act_code, status_code, lang
    )
    # This tool always requests the "Campaign Returns" report type, since
    # that is the only one exposing the 13-part Complete Financial Return
    # this function covers -- see constants.py.
    report_code = constants.REPORT_TYPES["campaign_returns"]
    base_url = constants.BASE_URLS[lang]

    cache_key = (
        f"elections-financial-returns:part:{lang}:{act_code}:{election_id}:{status_code}:"
        f"{candidate_client_id}:{part_code}"
    )

    select_form = {
        "ReturnStatus": status_code,
        "ReportOption": constants.REPORT_OPTION_COMPLETE,
        "SelectedClientIds": candidate_client_id,
        "SearchSelected": constants.SELECT_BUTTON[lang],
    }

    async def open_report(search_url: str) -> tuple[str, str]:
        """Select the candidate and open the report; returns the Download and report URLs."""

        async def select_candidate() -> httpx.Response:
            try:
                return await _client.post(search_url, data=select_form)
            except httpx.HTTPError as exc:
                raise UpstreamUnavailable(
                    "elections_financial_returns:get_financial_return_part did not respond "
                    "in time while selecting the candidate."
                ) from exc

        # A selection POST on an expired session re-renders the form (HTTP
        # 200) instead of redirecting -- re-warm once before treating a
        # missing redirect as an upstream failure.
        select_response = await select_candidate()
        if select_response.status_code != 302:
            await _warm_up(search_url, force=True)
            select_response = await select_candidate()
        if select_response.status_code != 302:
            _warmed.discard(search_url)
            raise UpstreamError(
                "elections_financial_returns:get_financial_return_part: expected a "
                f"redirect after candidate selection, got HTTP {select_response.status_code}."
            )
        location = select_response.headers.get("location", "")
        query_id_match = re.search(r"queryId=([0-9a-fA-F]+)", location)
        if query_id_match is None:
            raise NotFound(
                f"elections_financial_returns:get_financial_return_part: no matching "
                f"candidate {candidate_client_id!r} for election {election_id!r}."
            )
        query_id = query_id_match.group(1)
        detail_url = f"https://www.elections.ca{location}" if location.startswith("/") else location

        try:
            # Required once per queryId before Download will serve any part
            # -- see module docstring.
            await _client.get(detail_url)
        except httpx.HTTPError as exc:
            raise UpstreamUnavailable(
                "elections_financial_returns:get_financial_return_part did not respond "
                "in time while opening the report session."
            ) from exc

        return detail_url, (
            f"{base_url}/Download?act={act_code}&selectedEvent={election_id}"
            f"&returnStatus={status_code}&reportOption={constants.REPORT_OPTION_COMPLETE}"
            f"&queryId={query_id}&selectedClientId={candidate_client_id}"
            f"&selectedPart={part_code}&currentReturnPage=0&totalReturnPages=0"
            f"&downloadFormat={constants.DOWNLOAD_FORMAT_JSON}&current200Page=0&total200Pages=0"
        )

    async def download(download_url: str) -> httpx.Response:
        try:
            return await _client.get(download_url)
        except httpx.HTTPError as exc:
            raise UpstreamUnavailable(
                "elections_financial_returns:get_financial_return_part did not respond "
                "in time while downloading the report."
            ) from exc

    async def fetch() -> dict[str, object]:
        search_url = _search_url(act_code, election_id, report_code, status_code, lang)
        await _LIMITER.acquire()
        await _warm_up(search_url)
        detail_url, download_url = await open_report(search_url)
        download_response = await download(download_url)
        if download_response.status_code != 200:
            # Confirmed live: an expired session or queryId redirects (HTTP
            # 302) back to the search form rather than erroring. The pairing
            # was checked above, so this is a lost session: re-warm, select
            # again and retry once before giving up.
            await _warm_up(search_url, force=True)
            detail_url, download_url = await open_report(search_url)
            download_response = await download(download_url)
        if download_response.status_code != 200:
            _warmed.discard(search_url)
            raise UpstreamUnavailable(
                "elections_financial_returns:get_financial_return_part: the portal kept "
                "sending the report download back to its search form after a fresh session "
                f"(HTTP {download_response.status_code}). Try again shortly."
            )
        try:
            body = json.loads(_decode(download_response.content))
        except json.JSONDecodeError as exc:
            raise UpstreamError(
                "elections_financial_returns:get_financial_return_part returned a "
                "non-JSON response."
            ) from exc
        if not isinstance(body, dict):
            raise UpstreamError(
                "elections_financial_returns:get_financial_return_part returned an "
                "unexpected response shape."
            )
        return {
            "body": body,
            "download_url": download_url,
            # The queryId in download_url belongs to this session and expires
            # with it, so the request chain is spelled out for provenance.
            "request": (
                f"Request (session-bound; the queryId in url expires with the session): GET "
                f"{search_url} to start a session, POST the same URL with form fields "
                f"{urlencode(select_form)}, GET the redirect it returns ({detail_url}), then "
                "GET the Download URL with a fresh queryId."
            ),
        }

    result, was_cached = await cached_fetch(cache_key, constants.CACHE_TTL_SECONDS, fetch)
    body = result["body"]
    assert isinstance(body, dict)
    # The French download names its header RUBRIQUE_EXPORTER (and its row
    # sections DONNÉES_DÉTAIL etc., confirmed live 2026-10-03).
    header_key = "RUBRIQUE_EXPORTER" if "RUBRIQUE_EXPORTER" in body else "EXPORT_HEADER"
    export_header_list = body.get(header_key) or []
    export_header = export_header_list[0] if export_header_list else {}
    sections = {
        key: value for key, value in body.items() if key != header_key and isinstance(value, list)
    }

    return FinancialReturnPart(
        candidate_client_id=candidate_client_id,
        election_id=election_id,
        part_code=part_code,
        part_label=constants.PART_LABELS[part_code],
        return_status=return_status,
        export_header={str(k): str(v) for k, v in export_header.items()},
        sections=sections,
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=str(result["download_url"]),
            cached=was_cached,
            schema_name="elections_financial_returns.FinancialReturnPart",
            limits=str(result.get("request") or "") or None,
        ),
    )
