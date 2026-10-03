"""HTTP client for the StatCan Web Data Service (WDS).

Every method wraps `shared.http.api_get`/`api_post`, respects the
statcan-wds rate limiter, and unwraps WDS's `[{"status": "SUCCESS",
"object": {...}}]` envelope. A 409 response is StatCan's documented
signal that data is locked during its 12am-8:30am ET daily update
window (see constants.py) — this is surfaced as DataLocked, not
retried and not reported as a generic failure, since retrying during
the lock window cannot succeed.

Every table here, including StatCan's "real-time" (revision-history)
tables, is read through WDS on www150. The separate real-time viewer
(/rtdat-oadtr-service/) is disallowed by StatCan's robots.txt and is
never called.
"""

from __future__ import annotations

import re
import unicodedata
from calendar import monthrange
from contextvars import ContextVar
from datetime import UTC, date, datetime
from typing import Any, Literal, NoReturn
from zoneinfo import ZoneInfo

import httpx

from maplestats_mcp.modules.statcan.wds import constants
from maplestats_mcp.modules.statcan.wds.schemas import (
    ChangedCubeEntry,
    ChangedCubeList,
    ChangedSeriesEntry,
    ChangedSeriesList,
    CodeSetEntry,
    CodeSets,
    CubeDimension,
    CubeMetadata,
    CubeSummary,
    CubeSummaryList,
    DimensionMember,
    FailedVector,
    Footnote,
    FullTableDownloadLink,
    ObservationRow,
    SeriesInfo,
    VectorData,
    VectorDataSet,
    VectorSeries,
)
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance
from maplestats_mcp.shared.errors import (
    DataLocked,
    InvalidInput,
    NotFound,
    UpstreamError,
    UpstreamUnavailable,
)
from maplestats_mcp.shared.http import api_get, api_post
from maplestats_mcp.shared.json_utils import list_or_empty
from maplestats_mcp.shared.rate_limiter import get_limiter

CodeSetCategory = Literal[
    "scalar",
    "frequency",
    "symbol",
    "status",
    "uom",
    "survey",
    "subject",
    "classification_type",
    "security_level",
    "terminated",
]


def _limiter():
    return get_limiter(
        constants.RATE_LIMIT_SOURCE,
        rate=constants.RATE_LIMIT_PER_SECOND,
        capacity=constants.RATE_LIMIT_CAPACITY,
    )


# Error text follows the tool's `lang`. A ContextVar keeps `lang` out of every
# client signature: a tool calls use_lang() once and the raise helpers read it.
_LANG: ContextVar[str] = ContextVar("wds_lang", default="en")


def use_lang(lang: str) -> None:
    _LANG.set("fr" if lang == "fr" else "en")


def _m(en: str, fr: str) -> str:
    return fr if _LANG.get() == "fr" else en


_DASHED_PID = re.compile(r"^\d{2}-\d{2}-\d{4}(?:-\d{2})?$")


def normalize_product_id(value: int | str) -> int:
    """An 8-digit productId from any way a table is written.

    WDS accepts exactly 8 digits (confirmed live 2026-10-02: 1810000401 gets
    HTTP 406 "ProductId value must be 8 numbers long"). StatCan prints table
    numbers as 18-10-0004-01, whose first 8 digits are the productId and whose
    last two are the "simple view" suffix, so dashed numbers and 10-digit ids
    are cut down to 8 here.
    """
    text = str(value).strip()
    digits = text.replace("-", "") if _DASHED_PID.match(text) else text
    if not digits.isdigit() or len(digits) not in (8, 10):
        raise InvalidInput(
            _m(
                f"{value!r} is not a StatCan table number: use the 8-digit productId "
                "(18100004), or 18-10-0004 / 18-10-0004-01.",
                f"{value!r} n'est pas un numéro de tableau de Statistique Canada : utilisez "
                "l'identifiant à 8 chiffres (18100004), ou 18-10-0004 / 18-10-0004-01.",
            )
        )
    return int(digits[:8])


def _upstream_message(exc: httpx.HTTPStatusError) -> str:
    """WDS puts its reason in a JSON `message`; empty for a bare 404."""
    try:
        body = exc.response.json()
    except ValueError:
        return ""
    return str(body.get("message", "")) if isinstance(body, dict) else ""


def _raise_if_locked(exc: httpx.HTTPStatusError, method: str) -> NoReturn:
    """Map a WDS HTTP status to the typed error it means (confirmed live
    2026-10-02: 406 = rejected parameter with a reason, 404 = nothing found,
    409 = lock window)."""
    status = exc.response.status_code
    reason = _upstream_message(exc)
    if status == 409:
        raise DataLocked(
            _m(
                f"{method} is locked during StatCan's daily update window "
                "(12am-8:30am ET). Retry after 8:30am ET.",
                f"{method} est verrouillée pendant la mise à jour quotidienne de Statistique "
                "Canada (0 h - 8 h 30 HE). Réessayez après 8 h 30 HE.",
            )
        ) from exc
    if status == 406:
        raise InvalidInput(
            _m(
                f"{method} rejected the request (HTTP 406): {reason or 'parameter not valid'}.",
                f"{method} a rejeté la requête (HTTP 406) : {reason or 'paramètre non valide'}.",
            )
        ) from exc
    if status == 404:
        raise NotFound(
            _m(
                f"{method}: nothing found" + (f" ({reason})" if reason else "") + ".",
                f"{method} : aucun résultat" + (f" ({reason})" if reason else "") + ".",
            )
        ) from exc
    if status == 429 or status >= 500:
        raise UpstreamUnavailable(
            _m(
                f"{method} failed with HTTP {status} after retries. Try again shortly.",
                f"{method} a échoué (HTTP {status}) après plusieurs essais. Réessayez bientôt.",
            )
        ) from exc
    raise UpstreamError(
        _m(
            f"{method} returned HTTP {status}" + (f": {reason}" if reason else "") + ".",
            f"{method} a renvoyé HTTP {status}" + (f" : {reason}" if reason else "") + ".",
        )
    ) from exc


def _raise_unavailable(method: str, exc: httpx.HTTPError) -> NoReturn:
    """Wrap any non-status httpx failure (timeout, connect error, etc.) as
    the documented UpstreamUnavailable rather than letting a raw httpx
    exception escape once shared/http.py's retry budget is exhausted."""
    raise UpstreamUnavailable(
        _m(
            f"{method} did not respond in time (already retried by "
            "shared/http.py). This endpoint is known to be occasionally "
            "slow; try again shortly.",
            f"{method} n'a pas répondu à temps (déjà réessayée). Ce service est parfois "
            "lent ; réessayez bientôt.",
        )
    ) from exc


async def _post(method: str, body: list[dict[str, Any]] | dict[str, Any]) -> Any:
    await _limiter().acquire()
    url = f"{constants.BASE_URL}{method}"
    try:
        return await api_post(url, json_body=body)
    except httpx.HTTPStatusError as exc:
        _raise_if_locked(exc, method)
    except httpx.HTTPError as exc:
        _raise_unavailable(method, exc)


async def _get(
    method: str,
    path_suffix: str = "",
    params: dict[str, Any] | None = None,
    timeout: float = 30.0,
) -> Any:
    await _limiter().acquire()
    url = f"{constants.BASE_URL}{method}{path_suffix}"
    try:
        return await api_get(url, params=params, timeout=timeout)
    except httpx.HTTPStatusError as exc:
        _raise_if_locked(exc, method)
    except httpx.HTTPError as exc:
        _raise_unavailable(method, exc)


def _unwrap_one(item: dict[str, Any], method: str) -> Any:
    """Unwrap one `{"status": "SUCCESS", "object": ...}` envelope.

    Return type is genuinely `Any`, not `dict` — WDS's `object` field is
    a dict for most methods (e.g. getCubeMetadata) but a list for the
    changed-list methods (getChangedCubeList/getChangedSeriesList),
    confirmed live. Callers annotate the shape they expect.

    Two "not found" shapes, both confirmed live 2026-10-02: status FAILED with
    a text object ("The cube product ID 99999999 does not exist"), and status
    SUCCESS whose object carries a non-zero `responseStatusCode` with
    empty fields (a vector that does not exist, a coordinate outside the table).
    """
    if item.get("status") != "SUCCESS":
        detail = item.get("object")
        text = str(detail)
        if "does not exist" in text or "NOT_AVAILABLE" in text:
            raise NotFound(
                _m(
                    f"{method}: {text}",
                    f"{method} : l'identifiant demandé n'existe pas ou n'est pas disponible "
                    "dans le Service de données Web.",
                )
            )
        raise UpstreamError(
            _m(
                f"{method} returned status={item.get('status')!r}: {detail!r}",
                f"{method} a renvoyé le statut {item.get('status')!r} : {detail!r}",
            )
        )
    obj = item["object"]
    if isinstance(obj, dict) and obj.get("responseStatusCode") not in (None, 0):
        raise NotFound(
            _m(
                f"{method}: no match for the requested identifier "
                f"(responseStatusCode={obj['responseStatusCode']}).",
                f"{method} : aucune correspondance pour l'identifiant demandé "
                f"(responseStatusCode={obj['responseStatusCode']}).",
            )
        )
    return obj


def _pad_coordinate(coordinate: str) -> str:
    parts = coordinate.split(".")
    if len(parts) > constants.COORDINATE_DIMENSIONS:
        raise InvalidInput(
            _m(
                f"Coordinate {coordinate!r} has {len(parts)} dimensions; "
                f"WDS coordinates have at most {constants.COORDINATE_DIMENSIONS}.",
                f"La coordonnée {coordinate!r} compte {len(parts)} dimensions; "
                f"les coordonnées du SDW en comptent au plus {constants.COORDINATE_DIMENSIONS}.",
            )
        )
    for part in parts:
        if not part.isdigit():
            raise InvalidInput(
                _m(
                    f"Coordinate part {part!r} is not numeric in {coordinate!r}",
                    f"La partie {part!r} de la coordonnée {coordinate!r} n'est pas numérique.",
                )
            )
    while len(parts) < constants.COORDINATE_DIMENSIONS:
        parts.append("0")
    return ".".join(parts)


# StatCan's "real-time data tables" (www.statcan.gc.ca/en/dai/btd/rct, 19 of them
# checked 2026-10-02) are ordinary WDS tables whose titles say so: "Historical
# (real-time) releases of ...", "Vintages of releases of ...", plus the Real-time
# Local Business Condition Index. Reading the flag off the title keeps new
# real-time tables flagged without a list to maintain.
_REAL_TIME = re.compile(r"real[- ]time|vintages? of releases", re.IGNORECASE)


def _cube_summary_from_json(obj: dict[str, Any]) -> CubeSummary:
    return CubeSummary(
        product_id=int(obj["productId"]),
        cansim_id=obj.get("cansimId") or None,
        cube_title_en=obj["cubeTitleEn"],
        cube_title_fr=obj["cubeTitleFr"],
        cube_start_date=obj["cubeStartDate"],
        cube_end_date=obj["cubeEndDate"],
        release_time=obj["releaseTime"],
        archived=str(obj.get("archived", obj.get("archiveStatusCode", "0"))) not in {"0", "2"},
        frequency_code=int(obj["frequencyCode"]),
        subject_codes=list_or_empty(obj, "subjectCode"),
        survey_codes=list_or_empty(obj, "surveyCode"),
        dimension_count=obj.get("dimensionCount"),
        real_time=bool(_REAL_TIME.search(obj["cubeTitleEn"])),
    )


async def get_all_cubes_list(*, lite: bool = True) -> CubeSummaryList:
    method = "getAllCubesListLite" if lite else "getAllCubesList"
    cache_key = f"wds:{method}"

    async def fetch() -> list[dict[str, Any]]:
        return await _get(method, timeout=constants.CUBES_LIST_TIMEOUT_SECONDS)

    data, was_cached = await cached_fetch(cache_key, constants.CACHE_TTL_CUBES_LIST_SECONDS, fetch)
    cubes = [_cube_summary_from_json(obj) for obj in data]
    return CubeSummaryList(
        cubes=cubes,
        total_count=len(cubes),
        returned_count=len(cubes),
        provenance=make_provenance(
            source="statcan-wds",
            url=f"{constants.BASE_URL}{method}",
            cached=was_cached,
            schema_name="statcan.wds.CubeSummaryList",
            freshness="daily at 8:30am ET",
        ),
    )


def _fold(text: str) -> str:
    """Lower-case without accents, so 'chomage' finds 'chômage'."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


# Words that carry no topic in a natural-language query ("monthly unemployment
# rate for Alberta"); a table title rarely contains them, so requiring them
# would make most phrased queries return nothing.
_STOPWORDS = frozenset(
    [
        "a",
        "an",
        "and",
        "by",
        "for",
        "from",
        "in",
        "of",
        "on",
        "or",
        "the",
        "to",
        "with",
        "de",
        "du",
        "des",
        "la",
        "le",
        "les",
        "et",
        "en",
        "au",
        "aux",
        "pour",
        "par",
        "sur",
    ]
)


def _table_number_key(query: str) -> str | None:
    """The digits of a table number or PID if `query` is one, else None."""
    text = query.strip()
    if _DASHED_PID.match(text) or (text.isdigit() and len(text) in (8, 10)):
        return text.replace("-", "")[:8]
    return None


async def search_cubes(
    query: str | None = None,
    *,
    limit: int = constants.SEARCH_LIMIT_DEFAULT,
    offset: int = 0,
    lite: bool = True,
) -> CubeSummaryList:
    """Search the cached table inventory, or page through all of it.

    A query that is a table number (18-10-0004, 18-10-0004-01), an 8- or
    10-digit PID or an old CANSIM number (326-0020) finds that table. Any
    other query must match every word in the English or French title; when no
    title holds every word, the tables matching the most words are returned
    and the shortfall is stated in provenance.coverage.
    """
    if limit < 1 or limit > constants.SEARCH_LIMIT_MAX:
        raise InvalidInput(
            _m(
                f"limit must be between 1 and {constants.SEARCH_LIMIT_MAX}, got {limit}.",
                f"limit doit être entre 1 et {constants.SEARCH_LIMIT_MAX}, reçu {limit}.",
            )
        )
    if offset < 0:
        raise InvalidInput(_m("offset must be 0 or more.", "offset doit être 0 ou plus."))
    inventory = await get_all_cubes_list(lite=lite)
    cubes = inventory.cubes
    note: str | None = None
    if query is not None and query.strip():
        number = _table_number_key(query)
        cansim = re.sub(r"[^0-9]", "", query)
        if number is not None:
            matches = [c for c in cubes if str(c.product_id) == number]
        elif re.fullmatch(r"\d{3}-\d{4}", query.strip()):
            matches = [c for c in cubes if c.cansim_id and re.sub(r"\D", "", c.cansim_id) == cansim]
        else:
            all_words = [w for w in _fold(query).split() if w]
            words = [w for w in all_words if w not in _STOPWORDS] or all_words
            haystacks = [f"{_fold(c.cube_title_en)} {_fold(c.cube_title_fr)}" for c in cubes]
            scores = [sum(w in h for w in words) for h in haystacks]
            best = max(scores, default=0)
            wanted = len(words) if best == len(words) else best
            matches = [c for c, s in zip(cubes, scores, strict=True) if wanted and s >= wanted]
            if wanted and wanted < len(words):
                note = (
                    f"no table title contains all {len(words)} words; showing the tables "
                    f"whose titles match {wanted} of them. Words such as a province are often "
                    "dimension members, not title words: open the table with "
                    "wds_get_cube_metadata."
                )
    else:
        matches = cubes
    page = matches[offset : offset + limit]
    capped = len(matches) > offset + len(page)
    limits = (
        f"showing {len(page)} of {len(matches)} tables from offset {offset}; "
        "raise offset to see the rest"
        if capped
        else None
    )
    return CubeSummaryList(
        cubes=page,
        total_count=len(matches),
        returned_count=len(page),
        offset=offset,
        provenance=make_provenance(
            source="statcan-wds",
            url=inventory.provenance.url,
            cached=inventory.provenance.cached,
            schema_name="statcan.wds.CubeSummaryList",
            freshness="daily at 8:30am ET",
            coverage=note or f"{len(cubes)} tables searched",
            limits=limits,
        ),
    )


def _members_for(
    dim: dict[str, Any], *, member_query: str | None, member_limit: int, member_offset: int
) -> tuple[list[DimensionMember], int, int]:
    """(members returned, members in the dimension, members matching the query)."""
    raw = list_or_empty(dim, "member")
    words = _fold(member_query).split() if member_query else []
    if words:
        matched = [
            m
            for m in raw
            if all(w in f"{_fold(m['memberNameEn'])} {_fold(m['memberNameFr'])}" for w in words)
        ]
    else:
        matched = raw
    page = matched[member_offset : member_offset + member_limit]
    members = [
        DimensionMember(
            member_id=int(m["memberId"]),
            parent_member_id=m.get("parentMemberId"),
            member_name_en=m["memberNameEn"],
            member_name_fr=m["memberNameFr"],
            classification_code=m.get("classificationCode"),
            geo_level=m.get("geoLevel"),
            terminated=bool(int(m.get("terminated", 0) or 0)),
        )
        for m in page
    ]
    return members, len(raw), len(matched)


async def get_cube_metadata(
    product_id: int | str,
    *,
    dimension: int | None = None,
    member_query: str | None = None,
    member_limit: int = constants.MEMBER_LIMIT_DEFAULT,
    member_offset: int = 0,
    footnote_limit: int = constants.FOOTNOTE_LIMIT_DEFAULT,
) -> CubeMetadata:
    """Table metadata. Member lists and footnotes are capped (a census table's
    metadata runs past 1 MB); provenance.limits says what was cut."""
    pid = normalize_product_id(product_id)
    if member_limit < 1 or member_limit > constants.MEMBER_LIMIT_MAX:
        raise InvalidInput(
            _m(
                f"member_limit must be between 1 and {constants.MEMBER_LIMIT_MAX}.",
                f"member_limit doit être entre 1 et {constants.MEMBER_LIMIT_MAX}.",
            )
        )
    if member_offset < 0 or footnote_limit < 0:
        raise InvalidInput(
            _m(
                "member_offset and footnote_limit must be 0 or more.",
                "member_offset et footnote_limit doivent être 0 ou plus.",
            )
        )
    cache_key = f"wds:getCubeMetadata:{pid}"

    async def fetch() -> dict[str, Any]:
        items = await _post("getCubeMetadata", [{"productId": pid}])
        return _unwrap_one(items[0], "getCubeMetadata")

    obj, was_cached = await cached_fetch(
        cache_key, constants.CACHE_TTL_CUBE_METADATA_SECONDS, fetch
    )

    all_dimensions = list_or_empty(obj, "dimension")
    if dimension is not None and not any(
        int(d["dimensionPositionId"]) == dimension for d in all_dimensions
    ):
        raise InvalidInput(
            _m(
                f"Table {pid} has no dimension {dimension}; positions are "
                f"{[int(d['dimensionPositionId']) for d in all_dimensions]}.",
                f"Le tableau {pid} n'a pas de dimension {dimension}; positions : "
                f"{[int(d['dimensionPositionId']) for d in all_dimensions]}.",
            )
        )
    dimensions: list[CubeDimension] = []
    cut: list[str] = []
    for dim in all_dimensions:
        position = int(dim["dimensionPositionId"])
        if dimension is not None and position != dimension:
            members, total, matched = [], len(list_or_empty(dim, "member")), 0
        else:
            members, total, matched = _members_for(
                dim,
                member_query=member_query,
                member_limit=member_limit,
                member_offset=member_offset,
            )
            if matched > member_offset + len(members):
                cut.append(f"dimension {position}: {len(members)} of {matched} members")
        dimensions.append(
            CubeDimension(
                dimension_position_id=position,
                dimension_name_en=dim["dimensionNameEn"],
                dimension_name_fr=dim["dimensionNameFr"],
                has_uom=bool(dim.get("hasUom")),
                member_count=total,
                members_matched=matched,
                members=members,
            )
        )

    all_footnotes = list_or_empty(obj, "footnote")
    footnotes = [
        Footnote(
            footnote_id=int(fn["footnoteId"]),
            text_en=fn.get("footnotesEn", ""),
            text_fr=fn.get("footnotesFr", ""),
        )
        for fn in all_footnotes[:footnote_limit]
    ]
    limit_notes = list(cut)
    if len(all_footnotes) > footnote_limit:
        limit_notes.append(f"footnotes: {footnote_limit} of {len(all_footnotes)}")
    limits = (
        "truncated (" + "; ".join(limit_notes) + "); use dimension, member_query, "
        "member_limit/member_offset and footnote_limit to see more"
        if limit_notes
        else None
    )

    return CubeMetadata(
        product_id=int(obj["productId"]),
        cansim_id=obj.get("cansimId") or None,
        cube_title_en=obj["cubeTitleEn"],
        cube_title_fr=obj["cubeTitleFr"],
        cube_start_date=obj["cubeStartDate"],
        cube_end_date=obj["cubeEndDate"],
        frequency_code=int(obj["frequencyCode"]),
        n_series=int(obj["nbSeriesCube"]),
        n_datapoints=int(obj["nbDatapointsCube"]),
        release_time=obj["releaseTime"],
        archive_status_en=obj.get("archiveStatusEn", ""),
        archive_status_fr=obj.get("archiveStatusFr", ""),
        subject_codes=list_or_empty(obj, "subjectCode"),
        survey_codes=list_or_empty(obj, "surveyCode"),
        footnotes=footnotes,
        footnote_count=len(all_footnotes),
        dimensions=dimensions,
        provenance=make_provenance(
            source="statcan-wds",
            url=f"{constants.BASE_URL}getCubeMetadata",
            cached=was_cached,
            schema_name="statcan.wds.CubeMetadata",
            limits=limits,
        ),
    )


def _series_info(obj: dict[str, Any], method: str) -> SeriesInfo:
    terminated = obj.get("terminated")
    return SeriesInfo(
        product_id=int(obj["productId"]),
        coordinate=obj["coordinate"],
        vector_id=int(obj["vectorId"]),
        series_title_en=obj.get("SeriesTitleEn"),
        series_title_fr=obj.get("SeriesTitleFr"),
        frequency_code=obj.get("frequencyCode"),
        scalar_factor_code=obj.get("scalarFactorCode"),
        decimals=obj.get("decimals"),
        terminated=None if terminated is None else bool(int(terminated)),
        member_uom_code=obj.get("memberUomCode"),
        provenance=make_provenance(
            source="statcan-wds",
            url=f"{constants.BASE_URL}{method}",
            cached=False,
            schema_name="statcan.wds.SeriesInfo",
        ),
    )


async def get_series_info_from_cube_pid_coord(product_id: int | str, coordinate: str) -> SeriesInfo:
    pid = normalize_product_id(product_id)
    coordinate = _pad_coordinate(coordinate)
    items = await _post(
        "getSeriesInfoFromCubePidCoord", [{"productId": pid, "coordinate": coordinate}]
    )
    obj = _unwrap_one(items[0], "getSeriesInfoFromCubePidCoord")
    return _series_info(obj, "getSeriesInfoFromCubePidCoord")


async def get_series_info_from_vector(vector_id: int) -> SeriesInfo:
    items = await _post("getSeriesInfoFromVector", [{"vectorId": vector_id}])
    obj = _unwrap_one(items[0], "getSeriesInfoFromVector")
    return _series_info(obj, "getSeriesInfoFromVector")


def _observation_from_json(dp: dict[str, Any]) -> ObservationRow:
    ref_period_raw = dp.get("refPer") or dp.get("refPerRaw")
    if not ref_period_raw:
        raise UpstreamError(
            _m(
                f"Observation is missing refPer/refPerRaw: {dp!r}",
                f"Il manque refPer/refPerRaw dans l'observation : {dp!r}",
            )
        )
    release_time = dp.get("releaseTime")
    # `.get(key, 0)` only applies its default when the key is absent —
    # WDS sends these as explicit JSON null on some cubes (the same
    # quirk `terminated` below and json_utils.list_or_empty() guard
    # against), so `or 0` is needed to catch the present-but-null case
    # too; otherwise int(None) raises an unhandled TypeError.
    scalar = int(dp.get("scalarFactorCode", 0) or 0)
    return ObservationRow(
        ref_period=date.fromisoformat(ref_period_raw),
        value=dp.get("value"),
        decimals=int(dp.get("decimals", 0) or 0),
        scalar_factor_code=scalar,
        scale_multiplier=10**scalar,
        symbol_code=int(dp.get("symbolCode", 0) or 0),
        status_code=int(dp.get("statusCode", 0) or 0),
        security_level_code=int(dp.get("securityLevelCode", 0) or 0),
        release_time=_release_time_utc(release_time) if release_time else None,
    )


# WDS sends releaseTime without a zone ("2026-09-14T08:30"). It is Ottawa
# local time: StatCan publishes at 8:30 a.m. Eastern, and getAllCubesListLite
# reports the same release as "2026-09-14T12:30:00Z" (confirmed live against
# table 18-10-0004). Stamping it UTC put every release four or five hours
# early, so a zone-less value is read in America/Toronto and converted; a
# value that already carries a zone is kept as sent.
_WDS_ZONE = ZoneInfo("America/Toronto")


def _release_time_utc(raw: str) -> datetime:
    parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_WDS_ZONE)
    return parsed.astimezone(UTC)


def _series_from_json(obj: dict[str, Any]) -> VectorSeries:
    return VectorSeries(
        product_id=int(obj["productId"]),
        coordinate=obj["coordinate"],
        vector_id=int(obj["vectorId"]),
        observations=[_observation_from_json(dp) for dp in list_or_empty(obj, "vectorDataPoint")],
    )


def _vector_data_from_json(obj: dict[str, Any], *, source_url: str, cached: bool) -> VectorData:
    series = _series_from_json(obj)
    return VectorData(
        **series.model_dump(),
        provenance=make_provenance(
            source="statcan-wds",
            url=source_url,
            cached=cached,
            schema_name="statcan.wds.VectorData",
        ),
    )


def _vector_data_set(
    items: list[dict[str, Any]],
    vector_ids: list[int],
    *,
    method: str,
    cached: bool,
) -> VectorDataSet:
    """Keep the vectors WDS served and list the ones it could not.

    A batch is one HTTP call but one envelope per vector: confirmed live
    2026-10-02, [41690973, 999999999] gives SUCCESS for the first and FAILED
    (responseStatusCode 3) for the second, so one bad id must not fail the rest.
    Items come back in request order.
    """
    series: list[VectorSeries] = []
    failed: list[FailedVector] = []
    for position, item in enumerate(items):
        vector_id = vector_ids[position] if position < len(vector_ids) else 0
        try:
            series.append(_series_from_json(_unwrap_one(item, method)))
        except (NotFound, UpstreamError) as exc:
            detail = item.get("object")
            code = detail.get("responseStatusCode") if isinstance(detail, dict) else None
            reason = (
                f"no data for this vector (WDS responseStatusCode {code})"
                if code is not None
                else str(exc)
            )
            failed.append(FailedVector(vector_id=vector_id, reason=reason))
    if not series and failed:
        raise NotFound(
            _m(
                f"{method}: none of the vectors {[f.vector_id for f in failed]} returned data "
                f"({failed[0].reason}).",
                f"{method} : aucun des vecteurs {[f.vector_id for f in failed]} n'a de données "
                f"({failed[0].reason}).",
            )
        )
    return VectorDataSet(
        series=series,
        failed=failed,
        provenance=make_provenance(
            source="statcan-wds",
            url=f"{constants.BASE_URL}{method}",
            cached=cached,
            schema_name="statcan.wds.VectorDataSet",
            limits=(f"{len(failed)} vector(s) returned no data, see `failed`" if failed else None),
        ),
    )


async def get_data_from_vectors_and_latest_n_periods(
    vector_ids: list[int], latest_n: int
) -> VectorDataSet:
    if not vector_ids:
        raise InvalidInput(_m("vector_ids must not be empty.", "vector_ids ne doit pas être vide."))
    if latest_n < 1:
        raise InvalidInput(_m("latest_n must be 1 or more.", "latest_n doit être 1 ou plus."))
    method = "getDataFromVectorsAndLatestNPeriods"
    cache_key = f"wds:{method}:{sorted(vector_ids)}:{latest_n}"

    async def fetch() -> list[dict[str, Any]]:
        body = [{"vectorId": v, "latestN": latest_n} for v in vector_ids]
        return await _post(method, body)

    items, was_cached = await cached_fetch(
        cache_key, constants.CACHE_TTL_OBSERVATIONS_SECONDS, fetch
    )
    return _vector_data_set(items, vector_ids, method=method, cached=was_cached)


async def get_data_from_cube_pid_coord_and_latest_n_periods(
    product_id: int | str, coordinate: str, latest_n: int
) -> VectorData:
    pid = normalize_product_id(product_id)
    coordinate = _pad_coordinate(coordinate)
    if latest_n < 1:
        raise InvalidInput(_m("latest_n must be 1 or more.", "latest_n doit être 1 ou plus."))
    body = [{"productId": pid, "coordinate": coordinate, "latestN": latest_n}]
    items = await _post("getDataFromCubePidCoordAndLatestNPeriods", body)
    obj = _unwrap_one(items[0], "getDataFromCubePidCoordAndLatestNPeriods")
    return _vector_data_from_json(
        obj,
        source_url=f"{constants.BASE_URL}getDataFromCubePidCoordAndLatestNPeriods",
        cached=False,
    )


_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DATETIME = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$")
_MONTH = re.compile(r"^\d{4}-\d{2}$")


def _release_datetime(value: str, name: str, *, end: bool) -> str:
    """`YYYY-MM-DDTHH:MM`; a bare date is widened to the start or end of that day.

    WDS answers a bare date with HTTP 406 "Wrong date format" (confirmed live
    2026-10-02), so the format is checked here with a message that says so.
    """
    text = value.strip()
    if _DATE.match(text):
        text = f"{text}T{'23:59' if end else '00:00'}"
    if not _DATETIME.match(text):
        raise InvalidInput(
            _m(
                f"{name} must be YYYY-MM-DDTHH:MM (e.g. 2024-01-01T08:30) or YYYY-MM-DD, "
                f"got {value!r}.",
                f"{name} doit être AAAA-MM-JJTHH:MM (p. ex. 2024-01-01T08:30) ou AAAA-MM-JJ, "
                f"reçu {value!r}.",
            )
        )
    try:
        datetime.fromisoformat(text)
    except ValueError as exc:
        raise InvalidInput(
            _m(
                f"{name} is not a real date-time: {value!r}.",
                f"{name} n'est pas valide : {value!r}.",
            )
        ) from exc
    return text


def _ref_period(value: str, name: str, *, end: bool) -> str:
    """`YYYY-MM-DD`; a `YYYY-MM` month is widened to its first or last day."""
    text = value.strip()
    if _MONTH.match(text):
        year, month = int(text[:4]), int(text[5:])
        if not 1 <= month <= 12:
            raise InvalidInput(
                _m(f"{name} has no month {month}: {value!r}.", f"{name} : mois invalide {value!r}.")
            )
        day = monthrange(year, month)[1] if end else 1
        text = f"{text}-{day:02d}"
    if not _DATE.match(text):
        raise InvalidInput(
            _m(
                f"{name} must be YYYY-MM-DD (or YYYY-MM), got {value!r}.",
                f"{name} doit être AAAA-MM-JJ (ou AAAA-MM), reçu {value!r}.",
            )
        )
    try:
        date.fromisoformat(text)
    except ValueError as exc:
        raise InvalidInput(
            _m(f"{name} is not a real date: {value!r}.", f"{name} n'est pas valide : {value!r}.")
        ) from exc
    return text


async def get_bulk_vector_data_by_range(
    vector_ids: list[int], start_release_datetime: str, end_release_datetime: str
) -> VectorDataSet:
    """`start_release_datetime`/`end_release_datetime` are full
    `YYYY-MM-DDTHH:MM` (a bare date is widened to that day). Unlike every
    other WDS POST method, this one's body is a single flat object, not a
    one-item list — confirmed live; wrapping it in a list also produces a 406.
    """
    method = "getBulkVectorDataByRange"
    if not vector_ids:
        raise InvalidInput(_m("vector_ids must not be empty.", "vector_ids ne doit pas être vide."))
    start = _release_datetime(start_release_datetime, "start_release_datetime", end=False)
    end = _release_datetime(end_release_datetime, "end_release_datetime", end=True)
    body = {
        "vectorIds": [str(v) for v in vector_ids],
        "startDataPointReleaseDate": start,
        "endDataPointReleaseDate": end,
    }
    items = await _post(method, body)
    return _vector_data_set(items, vector_ids, method=method, cached=False)


async def get_data_from_vector_by_reference_period_range(
    vector_ids: list[int], start_ref_period: str, end_ref_period: str
) -> VectorDataSet:
    """`start_ref_period`/`end_ref_period` are `YYYY-MM-DD`; WDS rejects
    `YYYY-MM` with HTTP 406, so a month is widened to its first/last day."""
    method = "getDataFromVectorByReferencePeriodRange"
    if not vector_ids:
        raise InvalidInput(_m("vector_ids must not be empty.", "vector_ids ne doit pas être vide."))
    params = {
        "vectorIds": ",".join(str(v) for v in vector_ids),
        "startRefPeriod": _ref_period(start_ref_period, "start_ref_period", end=False),
        "endReferencePeriod": _ref_period(end_ref_period, "end_ref_period", end=True),
    }
    data = await _get(method, params=params)
    return _vector_data_set(data, vector_ids, method=method, cached=False)


async def get_changed_series_list() -> ChangedSeriesList:
    """Unlike getChangedCubeList, WDS documents this method as never
    accepting a date parameter — it always reflects today's changes."""
    method = "getChangedSeriesList"
    data = await _get(method)
    # Confirmed live: the response is ONE {"status", "object"} envelope
    # whose "object" is the list of entries — not one envelope per
    # entry, which is the shape getBulkVectorDataByRange etc. use.
    entries_raw: list[dict[str, Any]] = (
        _unwrap_one(data, method) if isinstance(data, dict) else data
    )
    entries = [
        ChangedSeriesEntry(
            product_id=int(obj["productId"]),
            coordinate=obj.get("coordinate", ""),
            vector_id=int(obj.get("vectorId", 0)),
            release_time=obj.get("releaseTime", ""),
        )
        for obj in entries_raw
    ]
    return ChangedSeriesList(
        series=entries,
        provenance=make_provenance(
            source="statcan-wds",
            url=f"{constants.BASE_URL}{method}",
            cached=False,
            schema_name="statcan.wds.ChangedSeriesList",
        ),
    )


async def get_changed_cube_list(date_str: str | None = None) -> ChangedCubeList:
    """Unlike getChangedSeriesList, WDS requires an explicit date here —
    a bare call with no date returns HTTP 404, not "today" by default.
    Defaults to today's date in Eastern Time (WDS's own reference
    timezone) client-side when none is given. The date must be YYYY-MM-DD:
    a DD/MM/YYYY path is a bare 404 upstream (confirmed live 2026-10-02)."""
    method = "getChangedCubeList"
    if date_str is None:
        date_str = datetime.now(ZoneInfo("America/Toronto")).date().isoformat()
    elif not _DATE.match(date_str.strip()):
        raise InvalidInput(
            _m(
                f"date must be YYYY-MM-DD, got {date_str!r}.",
                f"date doit être AAAA-MM-JJ, reçu {date_str!r}.",
            )
        )
    else:
        date_str = _ref_period(date_str, "date", end=False)
    data = await _get(method, path_suffix=f"/{date_str}")
    # Same envelope shape as getChangedSeriesList — see its comment above.
    entries_raw: list[dict[str, Any]] = (
        _unwrap_one(data, method) if isinstance(data, dict) else data
    )
    entries = [
        ChangedCubeEntry(product_id=int(obj["productId"]), release_time=obj.get("releaseTime", ""))
        for obj in entries_raw
    ]
    return ChangedCubeList(
        cubes=entries,
        provenance=make_provenance(
            source="statcan-wds",
            url=f"{constants.BASE_URL}{method}",
            cached=False,
            schema_name="statcan.wds.ChangedCubeList",
        ),
    )


async def get_changed_series_data_from_vector(vector_id: int) -> VectorData:
    """Newly changed points for one vector. WDS answers HTTP 404 "No changed
    data found" for a vector that did not change today: that is NotFound."""
    items = await _post("getChangedSeriesDataFromVector", [{"vectorId": vector_id}])
    obj = _unwrap_one(items[0], "getChangedSeriesDataFromVector")
    data = _vector_data_from_json(
        obj, source_url=f"{constants.BASE_URL}getChangedSeriesDataFromVector", cached=False
    )
    if data.vector_id != vector_id:
        raise UpstreamError(
            f"getChangedSeriesDataFromVector returned vector {data.vector_id} for {vector_id}."
        )
    return data


async def get_changed_series_data_from_cube_pid_coord(
    product_id: int | str, coordinate: str
) -> VectorData:
    """Resolve the coordinate to its vector first, then ask for that vector.

    getChangedSeriesDataFromCubePidCoord matches the coordinate in whichever
    table changed today, not in the table asked for: confirmed live
    2026-10-02, {"productId": 18100004, "coordinate": "2.2"} returned vector
    74740 of table 23100066. Going through the vector endpoint, and checking
    the table that comes back, cannot return another table's series.
    """
    pid = normalize_product_id(product_id)
    info = await get_series_info_from_cube_pid_coord(pid, coordinate)
    data = await get_changed_series_data_from_vector(info.vector_id)
    if data.product_id != pid:
        raise UpstreamError(
            f"getChangedSeriesDataFromVector returned table {data.product_id} for a series of "
            f"table {pid}."
        )
    return data


async def _require_known_table(pid: int) -> None:
    """WDS hands out a download URL for any number, existing or not (confirmed
    live 2026-10-02: 99999999 gets a link that 404s), so check the inventory."""
    inventory = await get_all_cubes_list(lite=True)
    if not any(c.product_id == pid for c in inventory.cubes):
        raise NotFound(
            _m(
                f"No StatCan table has productId {pid}.",
                f"Aucun tableau de Statistique Canada n'a l'identifiant {pid}.",
            )
        )


async def get_full_table_download_csv(
    product_id: int | str, lang: str = "en"
) -> FullTableDownloadLink:
    method = "getFullTableDownloadCSV"
    pid = normalize_product_id(product_id)
    await _require_known_table(pid)
    data = await _get(method, path_suffix=f"/{pid}/{lang}")
    return FullTableDownloadLink(
        product_id=pid,
        format="csv",
        language=lang,
        download_url=data.get("object", data) if isinstance(data, dict) else str(data),
        provenance=make_provenance(
            source="statcan-wds",
            url=f"{constants.BASE_URL}{method}/{pid}/{lang}",
            cached=False,
            schema_name="statcan.wds.FullTableDownloadLink",
        ),
    )


async def get_full_table_download_sdmx(product_id: int | str) -> FullTableDownloadLink:
    """Unlike getFullTableDownloadCSV, this method takes no lang segment —
    the SDMX file it links to is bilingual (English/French in the same
    document), so `language` below reflects that rather than a caller
    choice."""
    method = "getFullTableDownloadSDMX"
    pid = normalize_product_id(product_id)
    await _require_known_table(pid)
    data = await _get(method, path_suffix=f"/{pid}")
    return FullTableDownloadLink(
        product_id=pid,
        format="sdmx",
        language="en+fr",
        download_url=data.get("object", data) if isinstance(data, dict) else str(data),
        provenance=make_provenance(
            source="statcan-wds",
            url=f"{constants.BASE_URL}{method}/{pid}",
            cached=False,
            schema_name="statcan.wds.FullTableDownloadLink",
        ),
    )


async def get_code_sets(
    *,
    category: CodeSetCategory | None = None,
    query: str | None = None,
    limit: int = constants.CODE_SET_LIMIT_DEFAULT,
) -> CodeSets:
    """Code-set descriptions, optionally one category and/or filtered by
    description text. The full response is ~300 kB (subject, survey and
    terminated lists are long), so each category is capped at `limit`
    entries and provenance.limits says what was cut."""
    if limit < 1:
        raise InvalidInput(_m("limit must be 1 or more.", "limit doit être 1 ou plus."))
    cache_key = "wds:getCodeSets"

    async def fetch() -> dict[str, Any]:
        data = await _get("getCodeSets")
        return data["object"]

    obj, was_cached = await cached_fetch(cache_key, constants.CACHE_TTL_CODE_SETS_SECONDS, fetch)
    words = _fold(query).split() if query else []
    counts: dict[str, int] = {}
    cut: list[str] = []

    def entries(
        name: str, key: str, code_field: str, en_field: str, fr_field: str
    ) -> list[CodeSetEntry]:
        raw = list_or_empty(obj, key)
        counts[name] = len(raw)
        if category is not None and category != name:
            return []
        found = [
            CodeSetEntry(
                code=int(e[code_field]),
                description_en=e.get(en_field),
                description_fr=e.get(fr_field),
            )
            for e in raw
        ]
        if words:
            found = [
                e
                for e in found
                if all(
                    w in _fold(f"{e.description_en or ''} {e.description_fr or ''}") for w in words
                )
            ]
        if len(found) > limit:
            cut.append(f"{name}: {limit} of {len(found)}")
        return found[:limit]

    # Field names below are verified against a live getCodeSets response,
    # not guessed — several differ from the pattern the other categories
    # use (no "Desc" infix for survey/subject/classificationType; a
    # completely different key set for terminated).
    result = CodeSets(
        counts=counts,
        scalar=entries(
            "scalar", "scalar", "scalarFactorCode", "scalarFactorDescEn", "scalarFactorDescFr"
        ),
        frequency=entries(
            "frequency", "frequency", "frequencyCode", "frequencyDescEn", "frequencyDescFr"
        ),
        symbol=entries("symbol", "symbol", "symbolCode", "symbolDescEn", "symbolDescFr"),
        status=entries("status", "status", "statusCode", "statusDescEn", "statusDescFr"),
        uom=entries("uom", "uom", "memberUomCode", "memberUomEn", "memberUomFr"),
        survey=entries("survey", "survey", "surveyCode", "surveyEn", "surveyFr"),
        subject=entries("subject", "subject", "subjectCode", "subjectEn", "subjectFr"),
        classification_type=entries(
            "classification_type",
            "classificationType",
            "classificationTypeCode",
            "classificationTypeEn",
            "classificationTypeFr",
        ),
        security_level=entries(
            "security_level",
            "securityLevel",
            "securityLevelCode",
            "securityLevelDescEn",
            "securityLevelDescFr",
        ),
        terminated=entries("terminated", "terminated", "codeId", "codeTextEn", "codeTextFr"),
        provenance=make_provenance(
            source="statcan-wds",
            url=f"{constants.BASE_URL}getCodeSets",
            cached=was_cached,
            schema_name="statcan.wds.CodeSets",
            limits=(
                "capped per category (" + "; ".join(cut) + "); raise limit or narrow with "
                "category/query"
                if cut
                else None
            ),
        ),
    )
    return result
