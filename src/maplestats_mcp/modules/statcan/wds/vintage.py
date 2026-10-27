"""A series as it stood in a past release, from StatCan's real-time (vintage) tables.

A real-time table is its regular table plus a last "Release" dimension,
one member per release date (confirmed live 2026-10-27 on the 16 tables
WDS serves, listed in statcan/delta/realtime.py). Member ids of the shared
dimensions do not always agree between the two tables (the NAICS dimension
of 12-10-0165 numbers 21 members differently from 12-10-0163; 36-10-0491
has 321 industries where 36-10-0434 has 249), so members are matched by
their English names, dimension by dimension, never by id.

Release members are named "April 20, 2026" in English and "20 avril 2026"
in French; only the English name is parsed.

latestN counts back from the real-time table's last reference period for
every release, so a release that came out before the table's end has
`..` (status 1) for the periods it could not yet contain (confirmed live
for CPI-trim, release 2026-03-16: 2026-03 is null, 2026-01 and 2026-02 are
2.4 and 2.3). Those periods are dropped: they are after the release date.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from maplestats_mcp.modules.statcan.delta.realtime import _TABLES
from maplestats_mcp.modules.statcan.wds import constants
from maplestats_mcp.modules.statcan.wds.client import (
    _LANG,
    _m,
    _observation_from_json,
    _pad_coordinate,
    _post,
    _unwrap_one,
    cube_metadata_raw,
    normalize_product_id,
)
from maplestats_mcp.modules.statcan.wds.schemas import VintageSeries
from maplestats_mcp.shared.envelope import make_provenance
from maplestats_mcp.shared.errors import InvalidInput, NotFound
from maplestats_mcp.shared.json_utils import list_or_empty

# regular product id -> real-time product id, for the tables WDS serves.
REAL_TIME_FOR = {reg: rt for rt, _, _, reg, _, _, available in _TABLES if available}
_REAL_TIME_IDS = {rt for rt, *_ in _TABLES}
_UNSERVED = {reg: rt for rt, _, _, reg, _, _, available in _TABLES if not available}


def _fold(text: str) -> str:
    return " ".join(text.casefold().split())


def _release_date(name: str) -> date | None:
    try:
        return datetime.strptime(name.strip(), "%B %d, %Y").date()
    except ValueError:
        return None


def _parse_as_of(value: str) -> date:
    try:
        return date.fromisoformat(value.strip())
    except ValueError as exc:
        raise InvalidInput(
            _m(
                f"as_of must be a date YYYY-MM-DD, got {value!r}.",
                f"as_of doit être une date AAAA-MM-JJ, reçu {value!r}.",
            )
        ) from exc


def _map_coordinate(
    regular: dict[str, Any], real_time: dict[str, Any], coordinate: str
) -> list[int]:
    """The real-time member ids for the regular coordinate's members, release excluded."""
    ids = [int(p) for p in coordinate.split(".")]
    rt_dims = {_fold(d["dimensionNameEn"]): d for d in list_or_empty(real_time, "dimension")[:-1]}
    mapped: list[int] = []
    for dim in sorted(
        list_or_empty(regular, "dimension"), key=lambda d: int(d["dimensionPositionId"])
    ):
        position = int(dim["dimensionPositionId"])
        member_id = ids[position - 1]
        member = next((m for m in list_or_empty(dim, "member") if m["memberId"] == member_id), None)
        if member is None:
            raise NotFound(
                _m(
                    f"Table {regular['productId']} has no member {member_id} in dimension "
                    f"{position} ({dim['dimensionNameEn']}).",
                    f"Le tableau {regular['productId']} n'a pas de membre {member_id} dans la "
                    f"dimension {position} ({dim['dimensionNameFr']}).",
                )
            )
        rt_dim = rt_dims.get(_fold(dim["dimensionNameEn"]))
        rt_member = None
        if rt_dim is not None:
            rt_member = next(
                (
                    m
                    for m in list_or_empty(rt_dim, "member")
                    if _fold(m["memberNameEn"]) == _fold(member["memberNameEn"])
                ),
                None,
            )
        if rt_member is None:
            raise NotFound(
                _m(
                    f"{member['memberNameEn']!r} ({dim['dimensionNameEn']}) has no revision "
                    f"history: real-time table {real_time['productId']} does not carry it. Call "
                    f"wds_get_cube_metadata on {real_time['productId']} to see what it covers.",
                    f"« {member['memberNameFr']} » ({dim['dimensionNameFr']}) n'a pas "
                    f"d'historique des révisions : le tableau en temps réel "
                    f"{real_time['productId']} ne le contient pas. Appelez wds_get_cube_metadata "
                    f"sur {real_time['productId']} pour voir ce qu'il couvre.",
                )
            )
        mapped.append(int(rt_member["memberId"]))
    return mapped


async def get_series_as_of(
    product_id: int | str, coordinate: str, as_of: str, latest_n: int = 12
) -> VintageSeries:
    pid = normalize_product_id(product_id)
    coordinate = _pad_coordinate(coordinate)
    wanted = _parse_as_of(as_of)
    if latest_n < 1:
        raise InvalidInput(_m("latest_n must be 1 or more.", "latest_n doit être 1 ou plus."))
    if pid in _REAL_TIME_IDS:
        raise InvalidInput(
            _m(
                f"{pid} is itself a real-time table: pass the series of its regular table, or "
                "read it directly with wds_get_data_from_cube_coord and a Release member.",
                f"{pid} est lui-même un tableau en temps réel : donnez la série de son tableau "
                "régulier, ou lisez-le directement avec wds_get_data_from_cube_coord et un "
                "membre de la dimension Diffusion.",
            )
        )
    rt_pid = REAL_TIME_FOR.get(pid)
    if rt_pid is None:
        if pid in _UNSERVED:
            raise NotFound(
                _m(
                    f"Table {pid}'s real-time table {_UNSERVED[pid]} is listed by StatCan but "
                    "not served by WDS, so its past releases cannot be read.",
                    f"Le tableau en temps réel {_UNSERVED[pid]} du tableau {pid} figure sur la "
                    "liste de Statistique Canada mais n'est pas servi par le SDW; ses "
                    "diffusions passées ne peuvent pas être lues.",
                )
            )
        raise NotFound(
            _m(
                f"Table {pid} has no revision history in WDS: only the tables paired with a "
                f"real-time table keep past releases ({sorted(REAL_TIME_FOR)}). See "
                "statcan_delta_list_real_time_tables, or statcan_delta_read_table for the "
                "values released on one day.",
                f"Le tableau {pid} n'a pas d'historique des révisions dans le SDW : seuls les "
                f"tableaux associés à un tableau en temps réel gardent les diffusions passées "
                f"({sorted(REAL_TIME_FOR)}). Voir statcan_delta_list_real_time_tables, ou "
                "statcan_delta_read_table pour les valeurs diffusées un jour donné.",
            )
        )

    regular, _ = await cube_metadata_raw(pid)
    real_time, _ = await cube_metadata_raw(rt_pid)
    members = _map_coordinate(regular, real_time, coordinate)

    release_dim = list_or_empty(real_time, "dimension")[-1]
    releases = sorted(
        (released, int(m["memberId"]))
        for m in list_or_empty(release_dim, "member")
        if (released := _release_date(m["memberNameEn"])) is not None
    )
    if not releases:
        raise NotFound(
            _m(
                f"Real-time table {rt_pid} lists no release dates.",
                f"Le tableau en temps réel {rt_pid} ne donne aucune date de diffusion.",
            )
        )
    on_or_before = [r for r in releases if r[0] <= wanted]
    if not on_or_before:
        raise NotFound(
            _m(
                f"Real-time table {rt_pid} starts with the release of {releases[0][0]}; "
                f"nothing was recorded on or before {wanted}.",
                f"Le tableau en temps réel {rt_pid} commence à la diffusion du "
                f"{releases[0][0]}; rien n'est enregistré au plus tard le {wanted}.",
            )
        )
    release_date, release_member = on_or_before[-1]
    rt_coordinate = _pad_coordinate(".".join(str(m) for m in [*members, release_member]))

    # Enough periods to reach back latest_n before this release: at most one
    # per month between the release and the table's last period, plus up to
    # two years of publication lag (monthly GDP for October came out
    # 2024-12-23; with no slack only one of two asked-for periods came back).
    table_end = date.fromisoformat(real_time["cubeEndDate"][:10])
    months_after = (table_end.year - release_date.year) * 12 + (
        table_end.month - release_date.month
    )
    method = "getDataFromCubePidCoordAndLatestNPeriods"
    body = [
        {
            "productId": rt_pid,
            "coordinate": rt_coordinate,
            "latestN": latest_n + max(0, months_after) + 24,
        }
    ]
    obj = _unwrap_one((await _post(method, body))[0], method)
    rows = [
        row
        for row in map(_observation_from_json, list_or_empty(obj, "vectorDataPoint"))
        if row.ref_period <= release_date
    ]
    # Trailing periods the release could not contain come back as `..`.
    while rows and rows[-1].value is None and rows[-1].status_code == 1:
        rows.pop()
    rows = rows[-latest_n:]

    notes = [
        _m(
            f"Values as published in the release of {release_date}, the latest release on or "
            f"before {wanted}, read from real-time table {rt_pid}. Current values: "
            "wds_get_data_from_cube_coord on the regular table.",
            f"Valeurs telles que publiées à la diffusion du {release_date}, la dernière au plus "
            f"tard le {wanted}, lues dans le tableau en temps réel {rt_pid}. Valeurs actuelles : "
            "wds_get_data_from_cube_coord sur le tableau régulier.",
        )
    ]
    if title_inactive := real_time.get("cubeTitleEn", "").endswith(", inactive"):
        notes.append(
            _m(
                f"WDS titles {rt_pid} inactive: it records no release after {releases[-1][0]}.",
                f"WDS indique que {rt_pid} est inactif : aucune diffusion après {releases[-1][0]}.",
            )
        )
    if wanted > releases[-1][0] and not title_inactive:
        notes.append(
            _m(
                f"as_of is after the table's latest recorded release ({releases[-1][0]}); "
                "StatCan adds a release to the real-time table about a week after it comes out.",
                f"as_of est postérieur à la dernière diffusion enregistrée ({releases[-1][0]}); "
                "Statistique Canada ajoute une diffusion au tableau en temps réel environ une "
                "semaine après sa parution.",
            )
        )
    vector = obj.get("vectorId")
    return VintageSeries(
        as_of=wanted,
        release_date=release_date,
        release_member_id=release_member,
        product_id=pid,
        coordinate=coordinate,
        real_time_product_id=rt_pid,
        real_time_coordinate=rt_coordinate,
        real_time_vector_id=int(vector) if isinstance(vector, int) and vector > 0 else None,
        earliest_release=releases[0][0],
        latest_release=releases[-1][0],
        observations=rows,
        notes=notes,
        provenance=make_provenance(
            source="statcan-wds",
            url=f"{constants.BASE_URL}{method}",
            cached=False,
            schema_name="statcan.wds.VintageSeries",
            coverage=_m(
                f"latest {len(rows)} reference periods up to the release of {release_date}",
                f"{len(rows)} dernières périodes de référence jusqu'à la diffusion du "
                f"{release_date}",
            ),
            lang=_LANG.get(),
        ),
    )
