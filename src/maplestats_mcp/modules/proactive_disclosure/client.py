"""Client for the federal proactive disclosure tables on open.canada.ca's DataStore.

Four DataStore tables (contracts over $10,000, grants and contributions,
travel expenses, hospitality expenses), read with `datastore_search`
through shared/ckan.py. What the live checks of 2026-11-03 found (see
constants.py) shapes three choices here:

1. Everything is filtered by the portal where it can be. Names, titles,
   departments and programs are per-column full-text matches (`q` as an
   object); codes are exact `filters`; a date range is sent as the list of
   its days (a POST body holds thousands), so paging stays the portal's.
2. Amounts are text upstream, so a value range or a sort by value cannot be
   done by the portal. Those requests read the matching rows' `_id`, date
   and value only (a few dozen bytes per row, up to SCAN_MAX_ROWS), filter
   and sort them here, then fetch the full rows of the requested page by
   `_id`.
3. `datastore_search_sql` is disabled, so summaries are computed here from
   the same narrow scan, with each agreement's amendment rows collapsed to
   its latest one unless the caller asks for every row.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, NoReturn

from maplestats_mcp.modules.proactive_disclosure import constants
from maplestats_mcp.modules.proactive_disclosure.constants import DatasetSpec
from maplestats_mcp.modules.proactive_disclosure.schemas import (
    ContractRecord,
    ContractSearchResult,
    DatasetInfo,
    DatasetList,
    Department,
    DisclosureSummary,
    GrantRecord,
    GrantSearchResult,
    GroupBy,
    HospitalityRecord,
    HospitalitySearchResult,
    RecordSource,
    SummaryGroup,
    TravelRecord,
    TravelSearchResult,
    ValueMode,
)
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.ckan import CkanConfig, action, to_bool
from maplestats_mcp.shared.envelope import make_provenance, raise_localized
from maplestats_mcp.shared.errors import InvalidInput, UpstreamError
from maplestats_mcp.shared.i18n import french_spacing, pick
from maplestats_mcp.shared.json_utils import list_or_empty
from maplestats_mcp.shared.licences import OGL_CANADA, licence_in

_CONFIG = CkanConfig(
    source=constants.RATE_LIMIT_SOURCE,
    base_url=constants.BASE_URL,
    rate_limit_per_second=constants.RATE_LIMIT_PER_SECOND,
    rate_limit_capacity=constants.RATE_LIMIT_CAPACITY,
    timeout=constants.REQUEST_TIMEOUT_SECONDS,
)

Scalar = str | int | float | bool | list[str]


# --------------------------------------------------------------------------
# Small parsers


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return None if text in ("", "null", "None") else text


def money(value: Any) -> float | None:
    """A DataStore amount as a number: "38900.25", "464000", "$1,200.50", "-5000"."""
    text = _text(value)
    if text is None:
        return None
    cleaned = re.sub(r"[\s$ ,]", "", text)
    try:
        return float(cleaned)
    except ValueError:
        return None


def _int(value: Any) -> int | None:
    number = money(value)
    return int(number) if number is not None else None


def _yes_no(value: Any) -> bool | None:
    text = _text(value)
    if text is None:
        return None
    if text.upper() in ("Y", "N"):
        return text.upper() == "Y"
    return to_bool(text)


def _in_lang(row: dict[str, Any], base: str, lang: str) -> str | None:
    """`<base>_fr` for a French call, else `<base>_en`; the other one when blank."""
    first, second = ("fr", "en") if lang == "fr" else ("en", "fr")
    return _text(row.get(f"{base}_{first}")) or _text(row.get(f"{base}_{second}"))


def _bilingual_title(title: Any, lang: str) -> str | None:
    """'National Defence | Défense nationale' -> one side, by the call's language."""
    text = _text(title)
    if text is None or " | " not in text:
        return text
    english, french = text.split(" | ", 1)
    return french.strip() if lang == "fr" else english.strip()


def _label(table: dict[str, tuple[str, str]], code: Any, lang: str) -> str | None:
    text = _text(code)
    if text is None or text not in table:
        return None
    english, french = table[text]
    return french if lang == "fr" else english


def _fail(exc_cls: type[ValueError], en: str, fr: str, lang: str) -> NoReturn:
    raise_localized(exc_cls, en, fr, lang)


def _spec(dataset: str, lang: str) -> DatasetSpec:
    spec = constants.DATASETS.get(dataset)
    if spec is None:
        valid = ", ".join(constants.DATASETS)
        _fail(
            InvalidInput,
            f"Unknown dataset {dataset!r}. Fix: use one of {valid}.",
            f"jeu de données inconnu {dataset!r}. Solution : utilisez {valid}.",
            lang,
        )
    return spec


def dataset_url(spec: DatasetSpec, lang: str) -> str:
    return constants.DATASET_PAGE.format(lang=lang, id=spec.dataset_id)


def _source(spec: DatasetSpec, row: dict[str, Any], lang: str) -> RecordSource:
    return RecordSource(
        dataset_id=spec.dataset_id,
        resource_id=spec.resource_id,
        record_id=_int(row.get("_id")),
        dataset_url=dataset_url(spec, lang),
    )


def _department(row: dict[str, Any], lang: str) -> Department:
    return Department(
        owner_org=_text(row.get("owner_org")),
        name=_bilingual_title(row.get("owner_org_title"), lang),
    )


# --------------------------------------------------------------------------
# Arguments -> DataStore criteria


@dataclass
class Criteria:
    """What the portal filters (filters, q) and what is filtered here (value range)."""

    filters: dict[str, Any] = field(default_factory=dict)
    q: dict[str, str] = field(default_factory=dict)
    min_value: float | None = None
    max_value: float | None = None
    shown: dict[str, Scalar] = field(default_factory=dict)

    def body(self) -> dict[str, Any]:
        body: dict[str, Any] = {}
        if self.filters:
            body["filters"] = self.filters
        if self.q:
            body["q"] = self.q
        return body

    def match(self, name: str, column: str, value: str | None) -> None:
        """A full-text match on one column, when `value` has words."""
        text = (value or "").strip()
        if text:
            self.q[column] = text
            self.shown[name] = text

    def exact(self, name: str, column: str, value: Any, shown: Scalar | None = None) -> None:
        self.filters[column] = value
        self.shown[name] = shown if shown is not None else value

    def has_value_range(self) -> bool:
        return self.min_value is not None or self.max_value is not None

    def in_range(self, value: float | None) -> bool:
        if not self.has_value_range():
            return True
        if value is None:
            return False
        if self.min_value is not None and value < self.min_value:
            return False
        return self.max_value is None or value <= self.max_value


def parse_fiscal_year(value: str | int | None, lang: str) -> int | None:
    """2024, "2024", "2024-2025", "2024-25" -> 2024 (the April it starts)."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    text = str(value).strip()
    match = re.fullmatch(r"(\d{4})(?:\s*[-/]\s*(\d{2}|\d{4}))?", text)
    if match:
        start = int(match.group(1))
        end = match.group(2)
        if (end is None or int(end) % 100 == (start + 1) % 100) and 1990 <= start <= 2100:
            return start
    _fail(
        InvalidInput,
        f"fiscal_year {value!r} is not a fiscal year. Fix: write it as 2024-2025, 2024-25 "
        "or 2024 (the year it starts on April 1).",
        f"fiscal_year {value!r} n'est pas un exercice financier. Solution : écrivez "
        "2024-2025, 2024-25 ou 2024 (l'année où il commence, le 1er avril).",
        lang,
    )


def _parse_date(value: str | None, name: str, lang: str) -> date | None:
    if value is None or not str(value).strip():
        return None
    try:
        return date.fromisoformat(str(value).strip()[:10])
    except ValueError:
        _fail(
            InvalidInput,
            f"{name} {value!r} is not a date. Fix: write it as YYYY-MM-DD.",
            f"{name} {value!r} n'est pas une date. Solution : écrivez-la AAAA-MM-JJ.",
            lang,
        )


def _days(start: date, end: date) -> list[str]:
    return [(start + timedelta(days=n)).isoformat() for n in range((end - start).days + 1)]


def _date_window(
    spec: DatasetSpec,
    crit: Criteria,
    fiscal_year: int | None,
    date_from: str | None,
    date_to: str | None,
    lang: str,
) -> None:
    start = _parse_date(date_from, "date_from", lang)
    end = _parse_date(date_to, "date_to", lang)
    if (start is None) != (end is None):
        _fail(
            InvalidInput,
            "Give both date_from and date_to, or neither. Fix: add the missing bound "
            "(a date range is sent to the portal as the list of its days), or use fiscal_year.",
            "donnez date_from et date_to, ou aucun des deux. Solution : ajoutez la borne "
            "manquante (la plage est envoyée au portail comme la liste de ses jours), ou "
            "utilisez fiscal_year.",
            lang,
        )
    if start is not None and end is not None and start > end:
        _fail(
            InvalidInput,
            f"date_from ({start}) is after date_to ({end}); swap them or widen the range.",
            f"date_from ({start}) est postérieur à date_to ({end}) ; inversez-les ou "
            "élargissez la plage.",
            lang,
        )
    if fiscal_year is not None:
        crit.shown["fiscal_year"] = f"{fiscal_year}-{fiscal_year + 1}"
        if spec.key == "contracts":
            # Contracts carry the quarter they were published in; that is how
            # the government's own search and reports group them by year.
            crit.filters["reporting_period"] = [
                f"{fiscal_year}-{fiscal_year + 1}-Q{n}" for n in range(1, 5)
            ]
        else:
            fy_start, fy_end = date(fiscal_year, 4, 1), date(fiscal_year + 1, 3, 31)
            start = max(start, fy_start) if start else fy_start
            end = min(end, fy_end) if end else fy_end
            if start > end:
                _fail(
                    InvalidInput,
                    f"The date range does not overlap fiscal year {fiscal_year}-{fiscal_year + 1}. "
                    "Fix: drop one of them.",
                    f"la plage de dates ne recoupe pas l'exercice {fiscal_year}-{fiscal_year + 1}. "
                    "Solution : retirez l'un des deux.",
                    lang,
                )
    if start is None or end is None:
        return
    span = (end - start).days + 1
    if span > constants.DATE_SPAN_MAX_DAYS:
        _fail(
            InvalidInput,
            f"The date range covers {span:,} days; at most {constants.DATE_SPAN_MAX_DAYS:,} "
            "(about ten years) can be sent. Fix: split it into several calls, or leave the "
            "dates out to search every year.",
            f"la plage de dates couvre {span} jours ; au plus {constants.DATE_SPAN_MAX_DAYS} "
            "(environ dix ans) peuvent être envoyés. Solution : découpez-la en plusieurs "
            "appels, ou retirez les dates pour chercher toutes les années.",
            lang,
        )
    crit.filters[spec.date_field] = _days(start, end)
    crit.shown[f"{spec.date_field}_from"] = start.isoformat()
    crit.shown[f"{spec.date_field}_to"] = end.isoformat()


def _value_range(
    crit: Criteria, min_value: float | None, max_value: float | None, lang: str
) -> None:
    if min_value is not None and max_value is not None and min_value > max_value:
        _fail(
            InvalidInput,
            f"min_value ({min_value}) is after max_value ({max_value}); swap them or widen "
            "the range.",
            f"min_value ({min_value}) est postérieur à max_value ({max_value}) ; "
            "inversez-les ou élargissez la plage.",
            lang,
        )
    crit.min_value, crit.max_value = min_value, max_value
    if min_value is not None:
        crit.shown["min_value"] = min_value
    if max_value is not None:
        crit.shown["max_value"] = max_value


def _code(table: dict[str, str], value: str | None, name: str, lang: str) -> str | None:
    if value is None or not value.strip():
        return None
    code = table.get(value.strip().lower())
    if code is None:
        valid = ", ".join(table)
        _fail(
            InvalidInput,
            f"{name} {value!r} is not one of {valid}.",
            f"{name} {value!r} n'est pas l'une des valeurs {valid}.",
            lang,
        )
    return code


def build_criteria(
    spec: DatasetSpec,
    *,
    department: str | None = None,
    owner_org: str | None = None,
    fiscal_year: str | int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    min_value: float | None = None,
    max_value: float | None = None,
    party: str | None = None,
    title: str | None = None,
    text: str | None = None,
    program: str | None = None,
    province: str | None = None,
    riding: str | None = None,
    disclosure_group: str | None = None,
    instrument_type: str | None = None,
    agreement_type: str | None = None,
    ministers_office: bool | None = None,
    destination: str | None = None,
    vendor: str | None = None,
    lang: str = "en",
) -> Criteria:
    """The criteria for one dataset; an argument it has no column for is refused."""
    crit = Criteria()
    allowed = _ARGS[spec.key]
    given = {
        "title": title,
        "program": program,
        "province": province,
        "riding": riding,
        "disclosure_group": disclosure_group,
        "instrument_type": instrument_type,
        "agreement_type": agreement_type,
        "ministers_office": ministers_office,
        "destination": destination,
        "vendor": vendor,
    }
    stray = [
        name for name, value in given.items() if value not in (None, "") and name not in allowed
    ]
    if stray:
        _fail(
            InvalidInput,
            f"{', '.join(stray)} cannot filter {spec.key}. Fix: drop it; {spec.key} takes "
            f"{', '.join(sorted(allowed)) or 'only the common filters'}.",
            f"{', '.join(stray)} ne peut pas filtrer {spec.key}. Solution : retirez-le ; "
            f"{spec.key} accepte {', '.join(sorted(allowed)) or 'les filtres communs seulement'}.",
            lang,
        )
    if owner_org and owner_org.strip():
        crit.exact("owner_org", "owner_org", owner_org.strip().lower())
    crit.match("department", "owner_org_title", department)
    _date_window(spec, crit, parse_fiscal_year(fiscal_year, lang), date_from, date_to, lang)
    _value_range(crit, min_value, max_value, lang)

    if spec.key == "contracts":
        crit.match("vendor", "vendor_name", party)
        crit.match("description", f"description_{lang}", text)
        code = _code(constants.INSTRUMENT_TYPE_ARGS, instrument_type, "instrument_type", lang)
        if code:
            crit.exact("instrument_type", "instrument_type", code, instrument_type)
        if ministers_office is not None:
            crit.exact(
                "ministers_office",
                "ministers_office",
                "Y" if ministers_office else "N",
                ministers_office,
            )
    elif spec.key == "grants":
        crit.match("recipient", "recipient_legal_name", party)
        crit.match("description", f"description_{lang}", text)
        crit.match("program", f"prog_name_{lang}", program)
        code = _code(constants.AGREEMENT_TYPE_ARGS, agreement_type, "agreement_type", lang)
        if code:
            crit.exact("agreement_type", "agreement_type", code, agreement_type)
        if province and province.strip():
            prov = province.strip().upper()
            if prov not in constants.PROVINCES:
                _fail(
                    InvalidInput,
                    f"province {province!r} is not a province or territory code. Fix: use one "
                    f"of {', '.join(constants.PROVINCES)}.",
                    f"province {province!r} n'est pas un code de province ou de territoire. "
                    f"Solution : utilisez {', '.join(constants.PROVINCES)}.",
                    lang,
                )
            crit.exact("province", "recipient_province", prov)
        if riding and riding.strip():
            if riding.strip().isdigit():
                crit.exact("riding", "federal_riding_number", riding.strip())
            else:
                crit.match("riding", f"federal_riding_name_{lang}", riding)
    else:
        crit.match("name", "name", party)
        crit.match("title", f"title_{lang}", title)
        purpose_column = "purpose" if spec.key == "travel" else "description"
        crit.match("purpose", f"{purpose_column}_{lang}", text)
        code = _code(constants.DISCLOSURE_GROUP_ARGS, disclosure_group, "disclosure_group", lang)
        if code:
            crit.exact("disclosure_group", "disclosure_group", code, disclosure_group)
        if spec.key == "travel":
            crit.match("destination", f"destination_{lang}", destination)
        else:
            crit.match("vendor", f"vendor_{lang}", vendor)
    return crit


# Optional arguments each dataset has a column for (beyond the common ones).
_ARGS: dict[str, frozenset[str]] = {
    "contracts": frozenset({"instrument_type", "ministers_office"}),
    "grants": frozenset({"program", "province", "riding", "agreement_type"}),
    "travel": frozenset({"title", "disclosure_group", "destination"}),
    "hospitality": frozenset({"title", "disclosure_group", "vendor"}),
}


# --------------------------------------------------------------------------
# DataStore calls


def _cache_key(body: dict[str, Any]) -> str:
    digest = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
    return f"proactive-disclosure:{digest}"


async def _datastore(
    spec: DatasetSpec, body: dict[str, Any], lang: str
) -> tuple[dict[str, Any], bool]:
    payload = {"resource_id": spec.resource_id, **body}

    async def fetch() -> Any:
        return await action(_CONFIG, "datastore_search", json_body=payload, lang=lang)

    result, cached = await cached_fetch(
        _cache_key(payload), constants.CACHE_TTL_PAGE_SECONDS, fetch
    )
    if not isinstance(result, dict):
        _fail(
            UpstreamError,
            f"proactive-disclosure: datastore_search on {spec.key} returned no result object.",
            f"proactive-disclosure : datastore_search sur {spec.key} n'a renvoyé aucun "
            "objet de résultat.",
            lang,
        )
    return result, cached


def _too_many(total: int, lang: str) -> NoReturn:
    cap = constants.SCAN_MAX_ROWS
    _fail(
        InvalidInput,
        f"{total:,} rows match these filters; a value range, a sort by value or a summary "
        f"reads at most {cap:,}. Fix: narrow the request with owner_org or department, "
        "fiscal_year or a date range, or a name filter (or, for a search, drop "
        "min_value/max_value and sort by date).",
        f"{total} lignes correspondent à ces filtres ; une plage de valeurs, un tri par "
        f"valeur ou un sommaire en lit au plus {cap}. Solution : restreignez la requête "
        "avec owner_org ou department, fiscal_year ou une plage de dates, ou un filtre de "
        "nom (ou, pour une recherche, retirez min_value/max_value et triez par date).",
        lang,
    )


async def scan(
    spec: DatasetSpec, crit: Criteria, columns: Iterable[str], lang: str
) -> tuple[list[dict[str, Any]], bool]:
    """Every row matching `crit`, with only `columns`; refuses past SCAN_MAX_ROWS."""
    fields = sorted({"_id", *columns})
    base = {**crit.body(), "fields": fields, "sort": "_id"}
    first, cached = await _datastore(
        spec, {**base, "limit": constants.PAGE_SIZE, "offset": 0}, lang
    )
    total = int(first.get("total") or 0)
    rows = list_or_empty(first, "records")
    if total > constants.SCAN_MAX_ROWS:
        _too_many(total, lang)
    # The portal caps a page below what was asked (1,000 on 2026-11-03); step by
    # what it actually returned so no rows are skipped if that cap changes.
    step = len(rows)
    if step == 0 and total > 0:
        _fail(
            UpstreamError,
            f"proactive-disclosure: {spec.key} reports {total} rows but returned none.",
            f"proactive-disclosure : {spec.key} annonce {total} lignes mais n'en renvoie aucune.",
            lang,
        )
    semaphore = asyncio.Semaphore(constants.SCAN_CONCURRENCY)

    async def page(offset: int) -> tuple[dict[str, Any], bool]:
        async with semaphore:
            return await _datastore(
                spec,
                {**base, "limit": constants.PAGE_SIZE, "offset": offset, "include_total": False},
                lang,
            )

    offsets = range(step, total, step) if step else range(0)
    pages = await asyncio.gather(*(page(offset) for offset in offsets))
    seen = {row.get("_id") for row in rows}
    for result, page_cached in pages:
        cached = cached and page_cached
        for row in list_or_empty(result, "records"):
            # The table is republished nightly; a row seen twice while paging
            # is counted once.
            if row.get("_id") not in seen:
                seen.add(row.get("_id"))
                rows.append(row)
    return rows, cached


@dataclass
class _Found:
    rows: list[dict[str, Any]]
    total: int
    scanned: int
    cached: bool


def _date_key(row: dict[str, Any], column: str) -> str:
    return _text(row.get(column)) or ""


async def _search(
    spec: DatasetSpec, crit: Criteria, sort: str, limit: int, offset: int, lang: str
) -> _Found:
    if not 1 <= limit <= constants.SEARCH_LIMIT_MAX:
        _fail(
            InvalidInput,
            f"limit must be between 1 and {constants.SEARCH_LIMIT_MAX}, got {limit}. Fix: page "
            "with offset.",
            f"limit doit être entre 1 et {constants.SEARCH_LIMIT_MAX} (reçu : {limit}). "
            "Solution : paginez avec offset.",
            lang,
        )
    if offset < 0:
        _fail(
            InvalidInput,
            f"offset must be >= 0, got {offset}.",
            f"offset doit être positif ou nul (reçu : {offset}).",
            lang,
        )
    if sort not in ("date_desc", "date_asc", "value_desc", "value_asc"):
        _fail(
            InvalidInput,
            f"sort {sort!r} is not one of date_desc, date_asc, value_desc, value_asc.",
            f"sort {sort!r} n'est pas l'une des valeurs date_desc, date_asc, value_desc, "
            "value_asc.",
            lang,
        )
    descending = sort.endswith("desc")
    if not crit.has_value_range() and sort.startswith("date"):
        order = "desc" if descending else "asc"
        result, cached = await _datastore(
            spec,
            {
                **crit.body(),
                "limit": limit,
                "offset": offset,
                # ISO dates sort correctly as text; blank dates go last.
                "sort": f"{spec.date_field} {order} nulls last, _id {order}",
            },
            lang,
        )
        return _Found(list_or_empty(result, "records"), int(result.get("total") or 0), 0, cached)

    rows, cached = await scan(spec, crit, (spec.date_field, spec.value_field), lang)
    kept = [row for row in rows if crit.in_range(money(row.get(spec.value_field)))]
    if sort.startswith("value"):
        with_value = [row for row in kept if money(row.get(spec.value_field)) is not None]
        without = [row for row in kept if money(row.get(spec.value_field)) is None]
        with_value.sort(
            key=lambda row: (money(row.get(spec.value_field)) or 0.0, row.get("_id") or 0),
            reverse=descending,
        )
        kept = with_value + without
    else:
        dated = [row for row in kept if _date_key(row, spec.date_field)]
        undated = [row for row in kept if not _date_key(row, spec.date_field)]
        dated.sort(
            key=lambda row: (_date_key(row, spec.date_field), row.get("_id") or 0),
            reverse=descending,
        )
        kept = dated + undated
    ids = [row["_id"] for row in kept[offset : offset + limit]]
    if not ids:
        return _Found([], len(kept), len(rows), cached)
    result, page_cached = await _datastore(spec, {"filters": {"_id": ids}, "limit": len(ids)}, lang)
    by_id = {row.get("_id"): row for row in list_or_empty(result, "records")}
    return _Found(
        [by_id[i] for i in ids if i in by_id], len(kept), len(rows), cached and page_cached
    )


def _provenance(
    spec: DatasetSpec,
    schema: str,
    cached: bool,
    lang: str,
    coverage: str | None = None,
    limits: str | None = None,
):
    freshness = pick(lang, spec.freshness_en, spec.freshness_fr)
    if lang == "fr":
        freshness = french_spacing(freshness)
        coverage = french_spacing(coverage) if coverage else None
        limits = french_spacing(limits) if limits else None
    return make_provenance(
        source=constants.RATE_LIMIT_SOURCE,
        url=f"{constants.BASE_URL}datastore_search?resource_id={spec.resource_id}",
        cached=cached,
        schema_name=f"proactive_disclosure.{schema}",
        freshness=freshness,
        coverage=coverage,
        limits=limits,
        lang=lang,
    )


def _page_notes(found: _Found, offset: int, lang: str) -> tuple[str, str]:
    shown = len(found.rows)
    coverage = (
        pick(
            lang,
            f"rows {offset + 1}-{offset + shown} of {found.total:,} matching",
            f"lignes {offset + 1} à {offset + shown} sur {found.total} correspondantes",
        )
        if shown
        else pick(lang, f"no rows at offset {offset}", f"aucune ligne à partir de {offset}")
    )
    limits = pick(
        lang,
        f"at most {constants.SEARCH_LIMIT_MAX} rows per call; a value range or a sort by value "
        f"reads up to {constants.SCAN_MAX_ROWS:,} matching rows",
        f"au plus {constants.SEARCH_LIMIT_MAX} lignes par appel ; une plage de valeurs ou un "
        f"tri par valeur lit jusqu'à {constants.SCAN_MAX_ROWS} lignes correspondantes",
    )
    return coverage, limits


def _page_fields(
    spec: DatasetSpec, crit: Criteria, found: _Found, limit: int, offset: int, lang: str
) -> dict[str, Any]:
    return {
        "dataset": spec.key,
        "total_matched": found.total,
        "returned_count": len(found.rows),
        "offset": offset,
        "limit": limit,
        "filters": crit.shown,
        "rows_scanned": found.scanned,
        "dataset_url": dataset_url(spec, lang),
        "resource_id": spec.resource_id,
    }


# --------------------------------------------------------------------------
# Rows -> records


def contract_record(row: dict[str, Any], lang: str) -> ContractRecord:
    spec = constants.CONTRACTS
    return ContractRecord(
        reference_number=_text(row.get("reference_number")),
        procurement_id=_text(row.get("procurement_id")),
        vendor_name=_text(row.get("vendor_name")),
        vendor_postal_code=_text(row.get("vendor_postal_code")),
        buyer_name=_text(row.get("buyer_name")),
        contract_date=_text(row.get("contract_date")),
        contract_period_start=_text(row.get("contract_period_start")),
        delivery_date=_text(row.get("delivery_date")),
        contract_value=money(row.get("contract_value")),
        original_value=money(row.get("original_value")),
        amendment_value=money(row.get("amendment_value")),
        description=_in_lang(row, "description", lang),
        comments=_in_lang(row, "comments", lang),
        instrument_type=_text(row.get("instrument_type")),
        instrument_type_label=_label(constants.INSTRUMENT_TYPES, row.get("instrument_type"), lang),
        solicitation_procedure=_text(row.get("solicitation_procedure")),
        solicitation_procedure_label=_label(
            constants.SOLICITATION_PROCEDURES, row.get("solicitation_procedure"), lang
        ),
        commodity_type=_text(row.get("commodity_type")),
        commodity_type_label=_label(constants.COMMODITY_TYPES, row.get("commodity_type"), lang),
        commodity_code=_text(row.get("commodity_code")),
        economic_object_code=_text(row.get("economic_object_code")),
        country_of_vendor=_text(row.get("country_of_vendor")),
        number_of_bids=_int(row.get("number_of_bids")),
        ministers_office=_yes_no(row.get("ministers_office")),
        former_public_servant=_yes_no(row.get("former_public_servant")),
        reporting_period=_text(row.get("reporting_period")),
        department=_department(row, lang),
        source=_source(spec, row, lang),
    )


def grant_record(row: dict[str, Any], lang: str) -> GrantRecord:
    spec = constants.GRANTS
    return GrantRecord(
        ref_number=_text(row.get("ref_number")),
        amendment_number=_int(row.get("amendment_number")),
        amendment_date=_text(row.get("amendment_date")),
        agreement_type=_text(row.get("agreement_type")),
        agreement_type_label=_label(constants.AGREEMENT_TYPES, row.get("agreement_type"), lang),
        recipient_type=_text(row.get("recipient_type")),
        recipient_type_label=_label(constants.RECIPIENT_TYPES, row.get("recipient_type"), lang),
        recipient_legal_name=_text(row.get("recipient_legal_name")),
        recipient_operating_name=_text(row.get("recipient_operating_name")),
        recipient_business_number=_text(row.get("recipient_business_number")),
        research_organization_name=_text(row.get("research_organization_name")),
        recipient_country=_text(row.get("recipient_country")),
        recipient_province=_text(row.get("recipient_province")),
        recipient_city=_text(row.get("recipient_city")),
        recipient_postal_code=_text(row.get("recipient_postal_code")),
        federal_riding_name=_in_lang(row, "federal_riding_name", lang),
        federal_riding_number=_text(row.get("federal_riding_number")),
        program_name=_in_lang(row, "prog_name", lang),
        program_purpose=_in_lang(row, "prog_purpose", lang),
        agreement_title=_in_lang(row, "agreement_title", lang),
        agreement_number=_text(row.get("agreement_number")),
        agreement_value=money(row.get("agreement_value")),
        foreign_currency_type=_text(row.get("foreign_currency_type")),
        foreign_currency_value=money(row.get("foreign_currency_value")),
        agreement_start_date=_text(row.get("agreement_start_date")),
        agreement_end_date=_text(row.get("agreement_end_date")),
        description=_in_lang(row, "description", lang),
        expected_results=_in_lang(row, "expected_results", lang),
        naics_identifier=_text(row.get("naics_identifier")),
        department=_department(row, lang),
        source=_source(spec, row, lang),
    )


def travel_record(row: dict[str, Any], lang: str) -> TravelRecord:
    spec = constants.TRAVEL
    destinations = [
        place
        for place in (
            _in_lang(row, "destination", lang),
            _in_lang(row, "destination_2", lang),
            _in_lang(row, "destination_other", lang),
        )
        if place
    ]
    return TravelRecord(
        ref_number=_text(row.get("ref_number")),
        disclosure_group=_text(row.get("disclosure_group")),
        disclosure_group_label=_label(
            constants.DISCLOSURE_GROUPS, row.get("disclosure_group"), lang
        ),
        name=_text(row.get("name")),
        title=_in_lang(row, "title", lang),
        purpose=_in_lang(row, "purpose", lang),
        start_date=_text(row.get("start_date")),
        end_date=_text(row.get("end_date")),
        destinations=destinations,
        airfare=money(row.get("airfare")),
        other_transport=money(row.get("other_transport")),
        lodging=money(row.get("lodging")),
        meals=money(row.get("meals")),
        other_expenses=money(row.get("other_expenses")),
        total=money(row.get("total")),
        comments=_in_lang(row, "additional_comments", lang),
        department=_department(row, lang),
        source=_source(spec, row, lang),
    )


def hospitality_record(row: dict[str, Any], lang: str) -> HospitalityRecord:
    spec = constants.HOSPITALITY
    vendors = [
        vendor
        for vendor in (
            _in_lang(row, "vendor", lang),
            _in_lang(row, "vendor_2", lang),
            _in_lang(row, "vendor_other", lang),
        )
        if vendor
    ]
    return HospitalityRecord(
        ref_number=_text(row.get("ref_number")),
        disclosure_group=_text(row.get("disclosure_group")),
        disclosure_group_label=_label(
            constants.DISCLOSURE_GROUPS, row.get("disclosure_group"), lang
        ),
        name=_text(row.get("name")),
        title=_in_lang(row, "title", lang),
        description=_in_lang(row, "description", lang),
        start_date=_text(row.get("start_date")),
        end_date=_text(row.get("end_date")),
        location=_in_lang(row, "location", lang),
        vendors=vendors,
        employee_attendees=_int(row.get("employee_attendees")),
        guest_attendees=_int(row.get("guest_attendees")),
        total=money(row.get("total")),
        comments=_in_lang(row, "additional_comments", lang),
        department=_department(row, lang),
        source=_source(spec, row, lang),
    )


# --------------------------------------------------------------------------
# Search functions (one per tool)


async def search_contracts(
    *,
    vendor: str | None = None,
    department: str | None = None,
    owner_org: str | None = None,
    description: str | None = None,
    fiscal_year: str | int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    min_value: float | None = None,
    max_value: float | None = None,
    instrument_type: str | None = None,
    ministers_office: bool | None = None,
    sort: str = "date_desc",
    limit: int = constants.SEARCH_LIMIT_DEFAULT,
    offset: int = 0,
    lang: str = "en",
) -> ContractSearchResult:
    spec = constants.CONTRACTS
    crit = build_criteria(
        spec,
        department=department,
        owner_org=owner_org,
        fiscal_year=fiscal_year,
        date_from=date_from,
        date_to=date_to,
        min_value=min_value,
        max_value=max_value,
        party=vendor,
        text=description,
        instrument_type=instrument_type,
        ministers_office=ministers_office,
        lang=lang,
    )
    found = await _search(spec, crit, sort, limit, offset, lang)
    coverage, limits = _page_notes(found, offset, lang)
    return ContractSearchResult(
        **_page_fields(spec, crit, found, limit, offset, lang),
        records=[contract_record(row, lang) for row in found.rows],
        provenance=_provenance(spec, "ContractSearchResult", found.cached, lang, coverage, limits),
    )


async def search_grants(
    *,
    recipient: str | None = None,
    department: str | None = None,
    owner_org: str | None = None,
    program: str | None = None,
    description: str | None = None,
    province: str | None = None,
    riding: str | None = None,
    agreement_type: str | None = None,
    fiscal_year: str | int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    min_value: float | None = None,
    max_value: float | None = None,
    sort: str = "date_desc",
    limit: int = constants.SEARCH_LIMIT_DEFAULT,
    offset: int = 0,
    lang: str = "en",
) -> GrantSearchResult:
    spec = constants.GRANTS
    crit = build_criteria(
        spec,
        department=department,
        owner_org=owner_org,
        fiscal_year=fiscal_year,
        date_from=date_from,
        date_to=date_to,
        min_value=min_value,
        max_value=max_value,
        party=recipient,
        text=description,
        program=program,
        province=province,
        riding=riding,
        agreement_type=agreement_type,
        lang=lang,
    )
    found = await _search(spec, crit, sort, limit, offset, lang)
    coverage, limits = _page_notes(found, offset, lang)
    return GrantSearchResult(
        **_page_fields(spec, crit, found, limit, offset, lang),
        records=[grant_record(row, lang) for row in found.rows],
        provenance=_provenance(spec, "GrantSearchResult", found.cached, lang, coverage, limits),
    )


async def search_travel(
    *,
    name: str | None = None,
    title: str | None = None,
    department: str | None = None,
    owner_org: str | None = None,
    disclosure_group: str | None = None,
    purpose: str | None = None,
    destination: str | None = None,
    fiscal_year: str | int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    min_value: float | None = None,
    max_value: float | None = None,
    sort: str = "date_desc",
    limit: int = constants.SEARCH_LIMIT_DEFAULT,
    offset: int = 0,
    lang: str = "en",
) -> TravelSearchResult:
    spec = constants.TRAVEL
    crit = build_criteria(
        spec,
        department=department,
        owner_org=owner_org,
        fiscal_year=fiscal_year,
        date_from=date_from,
        date_to=date_to,
        min_value=min_value,
        max_value=max_value,
        party=name,
        title=title,
        text=purpose,
        disclosure_group=disclosure_group,
        destination=destination,
        lang=lang,
    )
    found = await _search(spec, crit, sort, limit, offset, lang)
    coverage, limits = _page_notes(found, offset, lang)
    return TravelSearchResult(
        **_page_fields(spec, crit, found, limit, offset, lang),
        records=[travel_record(row, lang) for row in found.rows],
        provenance=_provenance(spec, "TravelSearchResult", found.cached, lang, coverage, limits),
    )


async def search_hospitality(
    *,
    name: str | None = None,
    title: str | None = None,
    department: str | None = None,
    owner_org: str | None = None,
    disclosure_group: str | None = None,
    description: str | None = None,
    vendor: str | None = None,
    fiscal_year: str | int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    min_value: float | None = None,
    max_value: float | None = None,
    sort: str = "date_desc",
    limit: int = constants.SEARCH_LIMIT_DEFAULT,
    offset: int = 0,
    lang: str = "en",
) -> HospitalitySearchResult:
    spec = constants.HOSPITALITY
    crit = build_criteria(
        spec,
        department=department,
        owner_org=owner_org,
        fiscal_year=fiscal_year,
        date_from=date_from,
        date_to=date_to,
        min_value=min_value,
        max_value=max_value,
        party=name,
        title=title,
        text=description,
        disclosure_group=disclosure_group,
        vendor=vendor,
        lang=lang,
    )
    found = await _search(spec, crit, sort, limit, offset, lang)
    coverage, limits = _page_notes(found, offset, lang)
    return HospitalitySearchResult(
        **_page_fields(spec, crit, found, limit, offset, lang),
        records=[hospitality_record(row, lang) for row in found.rows],
        provenance=_provenance(
            spec, "HospitalitySearchResult", found.cached, lang, coverage, limits
        ),
    )


# --------------------------------------------------------------------------
# Summary


def _fiscal_year_of(day: str | None) -> str | None:
    """'2024-07-15' -> '2024-2025'; the federal fiscal year starts April 1."""
    if not day or not re.match(r"\d{4}-\d{2}", day):
        return None
    year, month = int(day[:4]), int(day[5:7])
    start = year if month >= 4 else year - 1
    return f"{start}-{start + 1}"


def _tidy(value: Any) -> str | None:
    """A label with its runs of spaces collapsed ('Anita  Anand' -> 'Anita Anand')."""
    text = _text(value)
    return re.sub(r"\s+", " ", text) if text else None


def _normal_name(value: Any) -> str | None:
    """Spellings of one name that differ only in case, spacing or a final period."""
    text = _tidy(value)
    if text is None:
        return None
    return text.rstrip(".,").casefold() or None


def _person_key(value: Any) -> str | None:
    """One key for 'Hodgson, Tim', 'Tim Hodgson' and 'HODGSON Tim'.

    Travel and hospitality rows name the same person in either order, with
    or without a comma (seen live 2026-11-03: 'McGuinty, Eamonn' and 'Eamonn
    McGuinty' in one department), so the words are compared as a set.
    """
    text = _normal_name(value)
    if text is None:
        return None
    return " ".join(sorted(re.findall(r"[^\s,.]+", text))) or None


@dataclass(frozen=True)
class _Grouping:
    columns: tuple[str, ...]
    key: Callable[[dict[str, Any]], str | None]
    label: Callable[[dict[str, Any], str], str | None] | None = None
    # Spelling variants share a key; the label is the most common spelling.
    by_spelling: bool = False
    chronological: bool = False


def _code_grouping(column: str, table: dict[str, tuple[str, str]] | None = None) -> _Grouping:
    return _Grouping(
        (column,),
        lambda row: _text(row.get(column)),
        (lambda row, lang: _label(table, row.get(column), lang)) if table else None,
    )


def _name_grouping(column: str, person: bool = False) -> _Grouping:
    keyer = _person_key if person else _normal_name
    return _Grouping(
        (column,),
        lambda row: keyer(row.get(column)),
        lambda row, _: _tidy(row.get(column)),
        by_spelling=True,
    )


def _lang_grouping(base: str, lang: str) -> _Grouping:
    column = f"{base}_{lang}"
    return _Grouping(
        (column,),
        lambda row: _normal_name(row.get(column)),
        lambda row, _: _tidy(row.get(column)),
        by_spelling=True,
    )


def _grouping(spec: DatasetSpec, group_by: str, lang: str) -> _Grouping:
    if group_by == "department":
        return _Grouping(
            ("owner_org", "owner_org_title"),
            lambda row: _text(row.get("owner_org")),
            lambda row, lang: _bilingual_title(row.get("owner_org_title"), lang),
        )
    if group_by == "fiscal_year":
        if spec.key == "contracts":
            return _Grouping(
                ("reporting_period",),
                lambda row: (_text(row.get("reporting_period")) or "")[:9] or None,
                chronological=True,
            )
        return _Grouping(
            (spec.date_field,),
            lambda row: _fiscal_year_of(_text(row.get(spec.date_field))),
            chronological=True,
        )
    if group_by == "quarter":
        return _Grouping(
            ("reporting_period",),
            lambda row: _text(row.get("reporting_period")),
            chronological=True,
        )
    simple: dict[tuple[str, str], _Grouping] = {
        ("contracts", "vendor"): _name_grouping("vendor_name"),
        ("contracts", "commodity_type"): _code_grouping(
            "commodity_type", constants.COMMODITY_TYPES
        ),
        ("contracts", "solicitation_procedure"): _code_grouping(
            "solicitation_procedure", constants.SOLICITATION_PROCEDURES
        ),
        ("contracts", "instrument_type"): _code_grouping(
            "instrument_type", constants.INSTRUMENT_TYPES
        ),
        ("contracts", "country_of_vendor"): _code_grouping("country_of_vendor"),
        ("contracts", "economic_object_code"): _code_grouping("economic_object_code"),
        ("grants", "recipient"): _name_grouping("recipient_legal_name"),
        ("grants", "program"): _lang_grouping("prog_name", lang),
        ("grants", "province"): _code_grouping("recipient_province"),
        ("grants", "recipient_type"): _code_grouping("recipient_type", constants.RECIPIENT_TYPES),
        ("grants", "agreement_type"): _code_grouping("agreement_type", constants.AGREEMENT_TYPES),
        ("travel", "name"): _name_grouping("name", person=True),
        ("travel", "title"): _lang_grouping("title", lang),
        ("travel", "disclosure_group"): _code_grouping(
            "disclosure_group", constants.DISCLOSURE_GROUPS
        ),
        ("hospitality", "name"): _name_grouping("name", person=True),
        ("hospitality", "title"): _lang_grouping("title", lang),
        ("hospitality", "disclosure_group"): _code_grouping(
            "disclosure_group", constants.DISCLOSURE_GROUPS
        ),
        ("hospitality", "vendor"): _lang_grouping("vendor", lang),
    }
    if spec.key == "grants" and group_by == "riding":
        name_column = f"federal_riding_name_{lang}"
        return _Grouping(
            ("federal_riding_number", name_column),
            lambda row: _text(row.get("federal_riding_number")),
            lambda row, _: _text(row.get(name_column)),
        )
    grouping = simple.get((spec.key, group_by))
    if grouping is None:
        valid = ", ".join(spec.group_by)
        _fail(
            InvalidInput,
            f"{spec.key} cannot be grouped by {group_by!r}. Fix: use one of {valid}.",
            f"{spec.key} ne peut pas être regroupé par {group_by!r}. Solution : utilisez {valid}.",
            lang,
        )
    return grouping


def _latest_rows(spec: DatasetSpec, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One row per agreement: the one with the highest `latest_by` (then `_id`).

    Both tables restate an agreement's whole value on each amendment row
    (schema: contract_value "for a contract amendment ... the amended contract
    value"; agreement_value "the total ... and not the change"), so the latest
    row carries the value to sum. A row missing part of its key stands alone.
    """
    if not spec.agreement_key or spec.latest_by is None:
        return rows
    latest_by = spec.latest_by

    def order(row: dict[str, Any]) -> tuple[Any, ...]:
        raw = row.get(latest_by)
        rank: Any = _int(raw) if latest_by == "amendment_number" else (_text(raw) or "")
        if rank is None:
            rank = -1
        return (rank, row.get("_id") or 0)

    best: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in rows:
        parts = tuple(_text(row.get(column)) for column in spec.agreement_key)
        key: tuple[Any, ...] = parts if all(parts) else ("_id", row.get("_id"))
        current = best.get(key)
        if current is None or order(row) > order(current):
            best[key] = row
    return list(best.values())


async def summarize(
    *,
    dataset: str,
    group_by: GroupBy = "department",
    department: str | None = None,
    owner_org: str | None = None,
    fiscal_year: str | int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    party: str | None = None,
    title: str | None = None,
    program: str | None = None,
    province: str | None = None,
    disclosure_group: str | None = None,
    min_value: float | None = None,
    max_value: float | None = None,
    value_mode: ValueMode = "latest_per_agreement",
    top: int = constants.SUMMARY_TOP_DEFAULT,
    lang: str = "en",
) -> DisclosureSummary:
    spec = _spec(dataset, lang)
    if not 1 <= top <= constants.SUMMARY_TOP_MAX:
        _fail(
            InvalidInput,
            f"top must be between 1 and {constants.SUMMARY_TOP_MAX}, got {top}.",
            f"top doit être entre 1 et {constants.SUMMARY_TOP_MAX} (reçu : {top}).",
            lang,
        )
    if value_mode not in ("latest_per_agreement", "all_rows"):
        _fail(
            InvalidInput,
            f"value_mode {value_mode!r} is not one of latest_per_agreement, all_rows.",
            f"value_mode {value_mode!r} n'est pas l'une des valeurs latest_per_agreement, "
            "all_rows.",
            lang,
        )
    if group_by not in spec.group_by:
        valid = ", ".join(spec.group_by)
        _fail(
            InvalidInput,
            f"{spec.key} cannot be grouped by {group_by!r}. Fix: use one of {valid}.",
            f"{spec.key} ne peut pas être regroupé par {group_by!r}. Solution : utilisez {valid}.",
            lang,
        )
    grouping = _grouping(spec, group_by, lang)
    crit = build_criteria(
        spec,
        department=department,
        owner_org=owner_org,
        fiscal_year=fiscal_year,
        date_from=date_from,
        date_to=date_to,
        min_value=min_value,
        max_value=max_value,
        party=party,
        title=title,
        program=program,
        province=province,
        disclosure_group=disclosure_group,
        lang=lang,
    )
    dedupe = value_mode == "latest_per_agreement" and bool(spec.agreement_key)
    columns = {spec.value_field, *grouping.columns}
    if dedupe and spec.latest_by:
        columns |= {*spec.agreement_key, spec.latest_by}
    rows, cached = await scan(spec, crit, columns, lang)
    scanned = len(rows)
    counted = _latest_rows(spec, rows) if dedupe else rows
    counted = [row for row in counted if crit.in_range(money(row.get(spec.value_field)))]

    totals: dict[str | None, list[float]] = {}
    spellings: dict[str | None, Counter[str]] = {}
    labels: dict[str | None, str | None] = {}
    without_value = 0
    for row in counted:
        key = grouping.key(row)
        value = money(row.get(spec.value_field))
        if value is None:
            without_value += 1
        entry = totals.setdefault(key, [0, 0.0])
        entry[0] += 1
        entry[1] += value or 0.0
        if grouping.label is not None:
            label = grouping.label(row, lang)
            if grouping.by_spelling:
                if label:
                    spellings.setdefault(key, Counter())[label] += 1
            elif key not in labels or (labels[key] is None and label):
                labels[key] = label
    for key, counter in spellings.items():
        labels[key] = counter.most_common(1)[0][0]

    total_value = sum(entry[1] for entry in totals.values())
    groups = [
        SummaryGroup(
            key=key,
            label=labels.get(key) if grouping.label is not None else key,
            count=int(entry[0]),
            total_value=round(entry[1], 2),
            share_percent=round(entry[1] / total_value * 100, 2) if total_value else None,
        )
        for key, entry in totals.items()
    ]
    if grouping.chronological:
        groups.sort(key=lambda g: (g.key is None, g.key or ""))
        shown, rest = groups, []
    else:
        groups.sort(key=lambda g: (-g.total_value, -g.count, g.key or ""))
        shown, rest = groups[:top], groups[top:]

    method = pick(
        lang,
        f"Read {scanned:,} rows (columns {', '.join(sorted(columns))}) with datastore_search "
        f"in pages of {constants.PAGE_SIZE:,} and summed by MapleStats: open.canada.ca does "
        "not enable datastore_search_sql or any aggregate API. "
        + (
            "Each agreement's amendment rows were collapsed to its latest row (its "
            f"{spec.latest_by} is highest), whose value is the amended total."
            if dedupe
            else "Every row was summed as published, amendment rows included."
        ),
        f"{scanned} lignes lues (colonnes {', '.join(sorted(columns))}) avec datastore_search "
        f"par pages de {constants.PAGE_SIZE}, puis additionnées par MapleStats : "
        "ouvert.canada.ca n'active ni datastore_search_sql ni aucune API d'agrégation. "
        + (
            "Les lignes de modification de chaque entente ont été ramenées à la plus récente "
            f"(la plus haute valeur de {spec.latest_by}), dont la valeur est le total modifié."
            if dedupe
            else "Toutes les lignes ont été additionnées telles que publiées, modifications "
            "comprises."
        ),
    )
    limits = pick(
        lang,
        f"a summary reads at most {constants.SCAN_MAX_ROWS:,} matching rows; groups beyond "
        f"the top {top} are folded into other_*",
        f"un sommaire lit au plus {constants.SCAN_MAX_ROWS} lignes correspondantes ; les "
        f"groupes au-delà des {top} premiers sont regroupés dans other_*",
    )
    return DisclosureSummary(
        dataset=spec.key,
        group_by=group_by,
        value_field=spec.value_field,
        value_mode=value_mode,
        groups=shown,
        other_groups=len(rest),
        other_count=sum(g.count for g in rest),
        other_value=round(sum(g.total_value for g in rest), 2),
        total_count=len(counted),
        total_value=round(total_value, 2),
        rows_scanned=scanned,
        rows_without_value=without_value,
        filters=crit.shown,
        dataset_url=dataset_url(spec, lang),
        resource_id=spec.resource_id,
        method=french_spacing(method) if lang == "fr" else method,
        provenance=_provenance(spec, "DisclosureSummary", cached, lang, limits=limits),
    )


# --------------------------------------------------------------------------
# Dataset list


async def _dataset_info(spec: DatasetSpec, lang: str) -> tuple[DatasetInfo, bool]:
    async def fetch_package() -> Any:
        return await action(_CONFIG, "package_show", {"id": spec.dataset_id}, lang=lang)

    package, package_cached = await cached_fetch(
        f"proactive-disclosure:package:{spec.dataset_id}",
        constants.CACHE_TTL_PACKAGE_SECONDS,
        fetch_package,
    )
    resources = list_or_empty(package, "resources") if isinstance(package, dict) else []
    resource = next(
        (r for r in resources if isinstance(r, dict) and r.get("id") == spec.resource_id), None
    )
    count, count_cached = await _datastore(spec, {"limit": 0}, lang)
    licence = OGL_CANADA if lang == "en" else french_spacing(licence_in(OGL_CANADA, "fr"))
    return (
        DatasetInfo(
            dataset=spec.key,
            title=pick(lang, spec.title_en, spec.title_fr),
            dataset_id=spec.dataset_id,
            resource_id=spec.resource_id,
            dataset_url=dataset_url(spec, lang),
            search_page_url=pick(lang, spec.search_url_en, spec.search_url_fr),
            resource_in_package=resource is not None,
            datastore_active=to_bool(resource.get("datastore_active")) if resource else None,
            row_count=int(count.get("total") or 0),
            last_modified=_text(resource.get("last_modified")) if resource else None,
            value_field=spec.value_field,
            date_field=spec.date_field,
            group_by=list(spec.group_by),
            licence=licence,
        ),
        package_cached and count_cached,
    )


async def list_datasets(lang: str = "en") -> DatasetList:
    found = await asyncio.gather(
        *(_dataset_info(spec, lang) for spec in constants.DATASETS.values())
    )
    cached = all(was_cached for _, was_cached in found)
    return DatasetList(
        datasets=[info for info, _ in found],
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=f"{constants.BASE_URL}package_show",
            cached=cached,
            schema_name="proactive_disclosure.DatasetList",
            freshness=french_spacing(
                pick(lang, "package metadata cached 24 h", "métadonnées mises en cache 24 h")
            )
            if lang == "fr"
            else "package metadata cached 24 h",
            lang=lang,
        ),
    )
