"""What each WDS series measures, attached to every data result.

WDS data methods return a vector's numbers and codes, but not what the
numbers are: no table title, no member names, no unit. An agent then has to
guess whether $82,500 is a family or an individual income, or whether it is
in current or constant dollars, and both guesses were wrong in a public
benchmark (CanData's GTA ground truth, 2026-10-22). This module fills
`VectorSeries.context` from three cached WDS reads:

- getSeriesInfoFromVector (one batched POST, cached a day): the series
  title and memberUomCode. The batch answers out of request order (checked
  live 2026-11-02 with 3823103, 41695188 and 96415851), so items are keyed
  by the vectorId they echo.
- getCubeMetadata (already cached a day by the client): the table title,
  dimension and member names, the table's period range and release time.
- getCodeSets (already cached a week): unit, scale and frequency text.
  memberUomCode 455 is "2024 constant dollars" and 81 is "Dollars" (checked
  live 2026-11-02), which is the whole difference between real and nominal
  growth in the benchmark's GT-08.

Context is best effort: when a metadata read fails the data still come back,
with `context` left null and a note in provenance.limits.
"""

from __future__ import annotations

import asyncio
from datetime import date
from typing import Any

from maplestats_mcp.modules.statcan.wds import auto_notes, client, constants
from maplestats_mcp.modules.statcan.wds.schemas import (
    SeriesContext,
    SeriesMember,
    VectorSeries,
)
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.errors import DataLocked, NotFound, UpstreamError, UpstreamUnavailable
from maplestats_mcp.shared.fitness import rules_for
from maplestats_mcp.shared.i18n import pick
from maplestats_mcp.shared.json_utils import list_or_empty

_SOFT_ERRORS = (NotFound, UpstreamError, UpstreamUnavailable, DataLocked)
_TABLE_PAGE = "https://www150.statcan.gc.ca/t1/tbl1/{lang}/tv.action?pid={pid:08d}01"


def table_number(product_id: int) -> str:
    """34100133 -> 34-10-0133-01, the form StatCan prints and cites."""
    digits = f"{product_id:08d}"
    return f"{digits[:2]}-{digits[2:4]}-{digits[4:8]}-01"


def table_url(product_id: int, lang: str = "en") -> str:
    return _TABLE_PAGE.format(lang="fr" if lang == "fr" else "en", pid=product_id)


async def series_info_raw(vector_ids: list[int]) -> dict[int, dict[str, Any]]:
    """getSeriesInfoFromVector objects by vector id (cached a day); missing ids left out."""
    return await _series_info_raw(vector_ids)


async def _series_info_raw(vector_ids: list[int]) -> dict[int, dict[str, Any]]:
    method = "getSeriesInfoFromVector"

    async def fetch() -> list[dict[str, Any]]:
        return await client._post(method, [{"vectorId": v} for v in vector_ids])

    items, _ = await cached_fetch(
        f"wds:{method}:{sorted(vector_ids)}", constants.CACHE_TTL_CUBE_METADATA_SECONDS, fetch
    )
    found: dict[int, dict[str, Any]] = {}
    for item in items:
        obj = item.get("object") if isinstance(item, dict) else None
        if (
            item.get("status") == "SUCCESS"
            and isinstance(obj, dict)
            and obj.get("responseStatusCode") in (None, 0)
        ):
            found[int(obj["vectorId"])] = obj
    return found


def _code_text(codes: dict[str, Any], key: str, code_field: str, stem: str, code: Any, lang: str):
    if code is None:
        return None
    suffix = "Fr" if lang == "fr" else "En"
    for entry in list_or_empty(codes, key):
        if str(entry.get(code_field)) == str(code):
            return entry.get(f"{stem}{suffix}") or entry.get(f"{stem}En")
    return None


def _parse_day(raw: Any) -> date | None:
    try:
        return date.fromisoformat(str(raw)[:10])
    except ValueError:
        return None


def unit_notes(unit: str | None, lang: str) -> list[str]:
    """Plain-language notes on what a unit of measure implies for comparisons."""
    if not unit:
        return []
    low = unit.lower()
    if "constant" in low and "dollar" in low:
        return [
            client._m(
                f"Unit is {unit}: inflation-adjusted (real) dollars. Growth computed from it is "
                "real growth. Do not set it beside growth in a current-dollar (nominal) series, "
                "such as rents, without converting one of them or saying they differ.",
                f"Unité : {unit}, soit des dollars corrigés de l'inflation (réels). La croissance "
                "calculée est réelle ; ne la comparez pas à celle d'une série en dollars courants "
                "(nominaux), comme les loyers, sans convertir l'une des deux ou le signaler.",
            )
        ]
    if low in {"dollars", "current dollars", "dollars courants"}:
        return [
            client._m(
                "Unit is current (nominal) dollars, not adjusted for inflation.",
                "Unité : dollars courants (nominaux), non corrigés de l'inflation.",
            )
        ]
    if "=100" in low.replace(" ", ""):
        return [
            client._m(
                f"Unit is an index ({unit}), not a price or dollar level: quote changes as "
                "percentages of the index.",
                f"Unité : un indice ({unit}), pas un prix ni un montant ; exprimez les "
                "variations en pourcentage de l'indice.",
            )
        ]
    return []


# Enough periods for a monthly series back to 1914 (1,353 for the CPI, checked
# live 2026-11-02); WDS answered latestN=2000 without complaint.
_SPAN_LATEST_N = 3000


async def series_span(vector_id: int) -> tuple[date, date] | None:
    """First and last reference periods that carry a value, or None if unknown.

    Rows before a series starts come back with value null (3823103, Toronto
    two-bedroom rent, has rows from 1987 and values from 1992: checked live
    2026-11-02), so the span is read from non-null values, not row dates.
    """
    method = "getDataFromVectorsAndLatestNPeriods"

    async def fetch() -> list[dict[str, Any]]:
        return await client._post(method, [{"vectorId": vector_id, "latestN": _SPAN_LATEST_N}])

    try:
        items, _ = await cached_fetch(
            f"wds:span:{vector_id}", constants.CACHE_TTL_OBSERVATIONS_SECONDS, fetch
        )
        obj = client._unwrap_one(items[0], method)
    except _SOFT_ERRORS:
        return None
    days = [
        day
        for dp in list_or_empty(obj, "vectorDataPoint")
        if dp.get("value") is not None and (day := _parse_day(dp.get("refPer"))) is not None
    ]
    return (min(days), max(days)) if days else None


def _empty_window_note(series: VectorSeries, span: tuple[date, date] | None) -> str:
    if span is not None:
        first, last = span
        return client._m(
            f"No observations in the requested window. This series has values from {first} "
            f"to {last} only. Do not estimate a value for a period it does not cover.",
            f"Aucune observation dans la période demandée. Cette série a des valeurs du "
            f"{first} au {last} seulement. N'estimez pas de valeur hors de cette période.",
        )
    return client._m(
        "No observations in the requested window. Call wds_get_data_from_vectors with "
        f"vector_ids=[{series.vector_id}] and a large latest_n to see the periods this "
        "series covers. Do not estimate a value for a period it does not cover.",
        "Aucune observation dans la période demandée. Appelez wds_get_data_from_vectors avec "
        f"vector_ids=[{series.vector_id}] et un grand latest_n pour voir les périodes que "
        "couvre cette série. N'estimez pas de valeur hors de cette période.",
    )


def citation(series: VectorSeries, title: str | None, table_release: str | None, lang: str) -> str:
    """A citation an assistant can copy: publisher, table, vector, release date.

    Answers in public benchmarks (CanData's GTA set, the Maple Test) cited the
    table and vector less often when they had to assemble them from separate
    fields; a ready string is the form an assistant quotes most reliably.
    The release is the newest observation's, else the table's.
    """
    releases = [o.release_time for o in series.observations if o.release_time is not None]
    released = max(releases).date().isoformat() if releases else (table_release or "")[:10]
    number = table_number(series.product_id)
    if lang == "fr":
        text = f"Statistique Canada. Tableau {number}"
        text += f", {title}" if title else ""
        text += f". Vecteur v{series.vector_id}."
        return text + (f" Diffusé le {released}." if released else "")
    text = f"Statistics Canada. Table {number}"
    text += f", {title}" if title else ""
    text += f". Vector v{series.vector_id}."
    return text + (f" Released {released}." if released else "")


def unavailable_elsewhere(
    product_id: int, cube: dict[str, Any], coordinate: str, lang: str
) -> str | None:
    """Where the latest periods a series leaves ".." are published instead, when a
    pair checked live in constants.UNAVAILABLE_ELSEWHERE covers the series."""
    entry = constants.UNAVAILABLE_ELSEWHERE.get(product_id)
    if entry is None:
        return None
    wanted, text_en, text_fr = entry
    have = {
        str(dim.get("dimensionNameEn") or ""): str(member.get("memberNameEn") or "")
        for dim, member in auto_notes.series_members(cube, coordinate)
    }
    if any(have.get(dim) != member for dim, member in wanted.items()):
        return None
    return pick(lang, f"StatCan publishes {text_en}", f"Statistique Canada publie {text_fr}")


def _context_for(
    series: VectorSeries,
    info: dict[str, Any] | None,
    cube: dict[str, Any] | None,
    codes: dict[str, Any] | None,
    lang: str,
    span: tuple[date, date] | None = None,
    empty: bool | None = None,
    flags: list[auto_notes.Flag] | None = None,
) -> SeriesContext:
    suffix = "Fr" if lang == "fr" else "En"
    members: list[SeriesMember] = []
    geography: str | None = None
    unit_code: Any = info.get("memberUomCode") if info else None
    if cube is not None:
        ids = series.coordinate.split(".")
        for dim in list_or_empty(cube, "dimension"):
            position = int(dim["dimensionPositionId"])
            if position > len(ids) or ids[position - 1] in ("", "0"):
                continue
            member_id = int(ids[position - 1])
            match = next(
                (m for m in list_or_empty(dim, "member") if int(m["memberId"]) == member_id),
                None,
            )
            if match is None:
                continue
            name = match.get(f"memberName{suffix}") or match.get("memberNameEn") or ""
            dim_name = dim.get(f"dimensionName{suffix}") or dim.get("dimensionNameEn") or ""
            members.append(SeriesMember(dimension=dim_name, member=name, member_id=member_id))
            if geography is None and dim.get("dimensionNameEn", "").startswith("Geograph"):
                geography = name
            if unit_code is None and match.get("memberUomCode") is not None:
                unit_code = match.get("memberUomCode")
    scalar_code = info.get("scalarFactorCode") if info else None
    if scalar_code is None and series.observations:
        scalar_code = series.observations[0].scalar_factor_code
    frequency_code = info.get("frequencyCode") if info else None
    if frequency_code is None and cube is not None:
        frequency_code = cube.get("frequencyCode")
    unit = scale = frequency = None
    if codes is not None:
        unit = _code_text(codes, "uom", "memberUomCode", "memberUom", unit_code, lang)
        scale = _code_text(
            codes, "scalar", "scalarFactorCode", "scalarFactorDesc", scalar_code, lang
        )
        frequency = _code_text(
            codes, "frequency", "frequencyCode", "frequencyDesc", frequency_code, lang
        )
    first = _parse_day(cube.get("cubeStartDate")) if cube else None
    last = _parse_day(cube.get("cubeEndDate")) if cube else None
    rule_keys = frozenset(rule.key for rule in rules_for("", {"product_id": series.product_id}))
    derived, overrides_unit = auto_notes.metadata_notes(
        cube, info, series.coordinate, lang, rule_keys
    )
    # A chained- or constant-dollar member outranks the unit: 36-10-0104 and
    # 34-10-0292 give those series memberUomCode 81, "Dollars", which read as
    # current dollars before 2026-11-03.
    notes = [] if overrides_unit else unit_notes(unit, lang)
    notes.extend(derived)
    if flags is None:
        flags = [(o.ref_period, o.status_code, o.security_level_code) for o in series.observations]
    notes.extend(auto_notes.flag_notes(flags, frequency_code, lang))
    if (
        cube is not None
        and auto_notes.trailing_unavailable(flags)
        and (elsewhere := unavailable_elsewhere(series.product_id, cube, series.coordinate, lang))
    ):
        notes.append(elsewhere)
    if scale and scalar_code not in (None, 0):
        notes.append(
            client._m(
                f"Values are in {scale}: multiply value by scale_multiplier for the full figure.",
                f"Valeurs en {scale} : multipliez value par scale_multiplier pour le chiffre entier.",
            )
        )
    if (not series.observations) if empty is None else empty:
        notes.append(_empty_window_note(series, span))
    title = (cube.get(f"cubeTitle{suffix}") or cube.get("cubeTitleEn")) if cube else None
    return SeriesContext(
        citation=citation(series, title, cube.get("releaseTime") if cube else None, lang),
        table_id=table_number(series.product_id),
        table_title=title,
        table_url=table_url(series.product_id, lang),
        series_title=(info.get(f"SeriesTitle{suffix}") or info.get("SeriesTitleEn"))
        if info
        else None,
        unit=unit,
        scale=scale,
        frequency=frequency,
        geography=geography,
        members=members,
        table_release_time=cube.get("releaseTime") if cube else None,
        first_period=first,
        last_period=last,
        notes=notes,
    )


async def prefetch(vector_ids: list[int], product_ids: list[int] | None = None) -> None:
    """Fill the caches describe() reads (series info, then each table's metadata).

    Run beside the data request, so a cold wds_get_data_from_vectors waits for the
    slower of the two chains instead of every request in turn (6.4 s median on the
    hosted server, 2026-11-06). A caller that knows its tables already
    (wds_get_data_from_cube_coord) passes `product_ids`, and their metadata is
    fetched at once, beside the data; with no `vector_ids` the series info is left
    for describe(), which learns the vector ids from the data. A failure here is
    ignored: describe() asks again and reports what it could not read.
    """
    known = sorted(set(product_ids or []))
    try:
        if not vector_ids:
            await asyncio.gather(
                *(client.cube_metadata_raw(pid) for pid in known), return_exceptions=True
            )
            return
        infos = await _series_info_raw(sorted(set(vector_ids)))
        found = {int(obj["productId"]) for obj in infos.values() if obj.get("productId")}
        await asyncio.gather(
            *(client.cube_metadata_raw(pid) for pid in sorted(found | set(known))),
            return_exceptions=True,
        )
    except (*_SOFT_ERRORS, KeyError, ValueError, TypeError):  # describe() asks again
        return


async def describe(series: list[VectorSeries]) -> tuple[list[VectorSeries], str | None]:
    """`series` with `context` filled, and a limits note when metadata could not be read."""
    if not series:
        return series, None
    empty = {s.vector_id for s in series if not s.observations}
    try:
        infos = await _series_info_raw(sorted({s.vector_id for s in series}))
    except _SOFT_ERRORS:
        infos = None
    contexts, note = await _contexts(series, infos, empty)
    return [
        s.model_copy(update={"context": c}) for s, c in zip(series, contexts, strict=True)
    ], note


async def describe_vectors(
    vector_ids: list[int],
    empty: set[int],
    flags: dict[int, list[auto_notes.Flag]] | None = None,
) -> tuple[dict[int, SeriesContext], str | None]:
    """Context for series known only by vector id (SDMX results), keyed by vector id.

    `empty` holds the vectors whose result had no observations in the window.
    A vector WDS cannot describe is left out. `flags` holds each vector's
    (period, status code, security level code), for the E/F/x notes.
    """
    if not vector_ids:
        return {}, None
    try:
        infos = await _series_info_raw(sorted(set(vector_ids)))
    except _SOFT_ERRORS:
        return {}, client._m(
            "series context is missing: getSeriesInfoFromVector did not answer",
            "le contexte des séries manque : getSeriesInfoFromVector n'a pas répondu",
        )
    stubs = [
        VectorSeries(
            product_id=int(info["productId"]),
            coordinate=str(info["coordinate"]),
            vector_id=vector_id,
            observations=[],
        )
        for vector_id, info in infos.items()
        if vector_id in set(vector_ids)
    ]
    contexts, note = await _contexts(stubs, infos, empty, flags or {})
    return {stub.vector_id: c for stub, c in zip(stubs, contexts, strict=True)}, note


async def _contexts(
    series: list[VectorSeries],
    infos: dict[int, dict[str, Any]] | None,
    empty: set[int],
    flags: dict[int, list[auto_notes.Flag]] | None = None,
) -> tuple[list[SeriesContext], str | None]:
    lang = "fr" if client._LANG.get() == "fr" else "en"
    missing: list[str] = [] if infos is not None else ["getSeriesInfoFromVector"]
    infos = infos or {}
    # Every table's metadata, the code sets and the spans are independent requests;
    # asked together, a three-table answer waits for the slowest, not the sum.
    product_ids = list(dict.fromkeys(s.product_id for s in series))
    empty_ids = list(empty)
    cube_results, code_result, span_results = await asyncio.gather(
        asyncio.gather(
            *(client.cube_metadata_raw(pid) for pid in product_ids), return_exceptions=True
        ),
        asyncio.gather(client._code_sets_raw(), return_exceptions=True),
        asyncio.gather(*(series_span(v) for v in empty_ids)),
    )
    cubes: dict[int, dict[str, Any] | None] = {}
    for product_id, outcome in zip(product_ids, cube_results, strict=True):
        if isinstance(outcome, _SOFT_ERRORS):
            cubes[product_id] = None
            missing.append(f"getCubeMetadata {product_id}")
        elif isinstance(outcome, BaseException):
            raise outcome
        else:
            cubes[product_id] = outcome[0]
    codes_outcome = code_result[0]
    if isinstance(codes_outcome, _SOFT_ERRORS):
        codes = None
        missing.append("getCodeSets")
    elif isinstance(codes_outcome, BaseException):
        raise codes_outcome
    else:
        codes = codes_outcome[0]
    spans = dict(zip(empty_ids, span_results, strict=True))
    contexts = [
        _context_for(
            s,
            infos.get(s.vector_id),
            cubes.get(s.product_id),
            codes,
            lang,
            spans.get(s.vector_id),
            empty=s.vector_id in empty,
            flags=None if flags is None else flags.get(s.vector_id, []),
        )
        for s in series
    ]
    note = (
        client._m(
            "series context is incomplete: " + ", ".join(missing) + " did not answer",
            "le contexte des séries est incomplet : " + ", ".join(missing) + " n'a pas répondu",
        )
        if missing
        else None
    )
    return contexts, note
