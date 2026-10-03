"""Water flows at Hydro-Quebec generating stations and control structures.

One file, `Donnees_VUE_CENTRALES_ET_OUVRAGES.json` on hydroquebec.com
(listed on Donnees Quebec as `donnees-hydrometriques`, CC BY-NC 4.0).
Confirmed live 2026-10-03 (2,777,390 bytes, Last-Modified a few minutes
before the read):

- `{"Site": [...]}`, 94 sites. Each has `identifiant` ('3-130'), `nom`,
  `RegionQC`, `CodeRegionQC`, `xcoord`/`ycoord` as strings (longitude,
  latitude), `zcoord` null, `date debut` ('1994/01/01', with a space in the
  key) and `Composition`, a list of 1 to 6 series.
- A series has `type_point_donnee` (the measure: 'Débit total', 'Apport
  filtré', or 'Débit turbiné - <plant>' / 'Débit déversé - <structure>'),
  `pas_temps` ('Horaire' or 'Journalier'), `type_mesure` ('Moyenne'),
  `nom_unite_mesure` ('m³/s') and `Donnees`, a dict of
  'YYYY/MM/DDTHH:MM:SSZ' -> value as a decimal string ('3087.29').
- About ten days of hourly values (245 points at most) and up to ten daily
  values per series. Sites in Nord-du-Québec and Côte-Nord lag by about four
  days (the published note says three), so the latest value differs by site.
- The 'Débit total' of a site equalled turbined plus spilled flow on the
  rows checked (La Grande-1).

The companion file for hydrometric stations (`..._STATIONS_ET_TARAGES.json`,
water levels and river flows) is 15 MB and is not read.
"""

from __future__ import annotations

import unicodedata
from datetime import UTC, datetime
from typing import Any

from maplestats_mcp.modules.electricity import constants
from maplestats_mcp.modules.electricity.quebec_client import _get_json
from maplestats_mcp.modules.electricity.schemas import (
    QuebecFacility,
    QuebecFacilityFlows,
    QuebecFacilityList,
    QuebecFlowPoint,
    QuebecFlowSeries,
    QuebecFlowSeriesInfo,
)
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError
from maplestats_mcp.shared.json_utils import list_or_empty
from maplestats_mcp.shared.models import Provenance

_KINDS = ("total", "turbined", "spilled", "inflow")
_STEPS = {"Horaire": "hourly", "Journalier": "daily"}


async def _sites() -> tuple[list[dict[str, Any]], bool]:
    async def fetch() -> list[dict[str, Any]]:
        body = await _get_json(constants.QUEBEC_FLOWS_URL, {}, "quebec_flows")
        if not isinstance(body, dict) or not isinstance(body.get("Site"), list):
            raise UpstreamError("electricity:quebec_flows: the file has no 'Site' list.")
        sites = list_or_empty(body, "Site")
        if len(sites) > constants.QUEBEC_FLOWS_MAX_FACILITIES:
            raise UpstreamError(
                f"electricity:quebec_flows lists {len(sites)} sites, more than expected."
            )
        return sites

    return await cached_fetch("electricity:quebec_flows", constants.QUEBEC_FLOWS_TTL_SECONDS, fetch)


def _kind(measure: str) -> str:
    text = measure.casefold()
    if text.startswith("débit total"):
        return "total"
    if text.startswith("débit turbiné"):
        return "turbined"
    if text.startswith("débit déversé"):
        return "spilled"
    if text.startswith("apport"):
        return "inflow"
    return "other"


def _time(stamp: str) -> datetime | None:
    try:
        return datetime.strptime(stamp, "%Y/%m/%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError:
        return None


def _number(text: Any) -> float | None:
    try:
        return float(text) if text not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _points(series: dict[str, Any]) -> list[QuebecFlowPoint]:
    data = series.get("Donnees") or {}
    points = []
    for stamp, raw in data.items() if isinstance(data, dict) else []:
        when, value = _time(str(stamp)), _number(raw)
        if when is not None and value is not None:
            points.append(QuebecFlowPoint(time=when, value=value))
    points.sort(key=lambda p: p.time)
    return points


def _info(series: dict[str, Any], points: list[QuebecFlowPoint]) -> QuebecFlowSeriesInfo:
    measure = str(series.get("type_point_donnee") or "")
    step = str(series.get("pas_temps") or "")
    return QuebecFlowSeriesInfo(
        measure=measure,
        kind=_kind(measure),
        time_step=_STEPS.get(step, step.casefold()),
        statistic=str(series.get("type_mesure") or ""),
        unit=str(series.get("nom_unite_mesure") or ""),
        points=len(points),
        first=points[0].time if points else None,
        last=points[-1].time if points else None,
        latest_value=points[-1].value if points else None,
    )


def _facility(site: dict[str, Any]) -> tuple[QuebecFacility, list[QuebecFlowSeries]]:
    series = []
    for raw in list_or_empty(site, "Composition"):
        points = _points(raw)
        series.append(QuebecFlowSeries(info=_info(raw, points), values=points))
    facility = QuebecFacility(
        facility_id=str(site.get("identifiant") or ""),
        name=str(site.get("nom") or ""),
        region=str(site.get("RegionQC") or ""),
        region_code=site.get("CodeRegionQC") or None,
        latitude=_number(site.get("ycoord")),
        longitude=_number(site.get("xcoord")),
        records_since=site.get("date debut") or None,
        series=[s.info for s in series],
    )
    return facility, series


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def _provenance(schema: str, cached: bool, coverage: str | None = None) -> Provenance:
    return make_provenance(
        source="electricity:quebec_flows",
        url=constants.QUEBEC_FLOWS_URL,
        cached=cached,
        schema_name=schema,
        freshness=(
            "Rewritten by Hydro-Quebec about hourly; about ten days of hourly flows and up to "
            "ten daily inflows per site. Nord-du-Québec and Côte-Nord sites lag about four "
            "days. Raw data, not quality-checked by Hydro-Quebec. Cached 30 minutes."
        ),
        coverage=coverage,
        limits=(
            f"Record: {constants.QUEBEC_FLOWS_PAGE}. Flows in m³/s; timestamps UTC. "
            f"{constants.QUEBEC_LICENCE}"
        ),
    )


async def list_facilities(
    query: str | None = None,
    region: str | None = None,
    kind: str | None = None,
    limit: int = 100,
) -> QuebecFacilityList:
    """Sites with their series and latest values, filtered by name/id, region or kind."""
    if not 1 <= limit <= constants.QUEBEC_FLOWS_MAX_FACILITIES:
        raise InvalidInput(
            f"limit must be between 1 and {constants.QUEBEC_FLOWS_MAX_FACILITIES}, got {limit}."
        )
    if kind is not None and kind not in _KINDS:
        raise InvalidInput(f"kind must be one of {', '.join(_KINDS)}.")
    sites, cached = await _sites()
    needle = _fold(query) if query and query.strip() else None
    wanted_region = _fold(region) if region and region.strip() else None
    facilities = []
    for site in sites:
        facility, _ = _facility(site)
        if (
            needle
            and needle not in _fold(f"{facility.name} {facility.facility_id}")
            and not any(needle in _fold(s.measure) for s in facility.series)
        ):
            continue
        if wanted_region and wanted_region not in _fold(facility.region):
            continue
        if kind and not any(s.kind == kind for s in facility.series):
            continue
        facilities.append(facility)
    facilities.sort(key=lambda f: (f.region, f.name))
    return QuebecFacilityList(
        total_facilities=len(sites),
        total_matches=len(facilities),
        facilities=facilities[:limit],
        provenance=_provenance(
            "electricity.QuebecFacilityList",
            cached,
            f"{len(facilities)} of {len(sites)} sites match; showing {min(limit, len(facilities))}.",
        ),
    )


async def get_facility_flows(
    facility: str,
    kind: str | None = None,
    start: str | None = None,
    end: str | None = None,
) -> QuebecFacilityFlows:
    """One site's series (all values), optionally one kind and a UTC time window."""
    if not facility or not facility.strip():
        raise InvalidInput("facility must be a site id (e.g. '3-130') or name.")
    if kind is not None and kind not in _KINDS:
        raise InvalidInput(f"kind must be one of {', '.join(_KINDS)}.")
    window = []
    for label, text in (("start", start), ("end", end)):
        if text:
            try:
                parsed = datetime.fromisoformat(text)
            except ValueError as exc:
                raise InvalidInput(
                    f"{label} must be an ISO date or date-time, got '{text}'."
                ) from exc
            window.append(parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC))
        else:
            window.append(None)
    sites, cached = await _sites()
    wanted = _fold(facility.strip())
    exact = [s for s in sites if _fold(str(s.get("identifiant") or "")) == wanted]
    exact = exact or [s for s in sites if _fold(str(s.get("nom") or "")) == wanted]
    found = exact or [s for s in sites if wanted in _fold(str(s.get("nom") or ""))]
    if not found:
        raise NotFound(
            f"No Hydro-Quebec site '{facility}'. Use electricity_quebec_list_facilities."
        )
    if len(found) > 1:
        names = ", ".join(f"{s.get('identifiant')} {s.get('nom')}" for s in found[:10])
        raise InvalidInput(f"'{facility}' matches several sites ({names}); pass the id.")
    record, series = _facility(found[0])
    low, high = window
    kept = []
    for one in series:
        if kind and one.info.kind != kind:
            continue
        values = [
            p
            for p in one.values
            if (low is None or p.time >= low) and (high is None or p.time <= high)
        ]
        kept.append(QuebecFlowSeries(info=one.info, values=values))
    return QuebecFacilityFlows(
        facility=record,
        series=kept,
        provenance=_provenance("electricity.QuebecFacilityFlows", cached),
    )
