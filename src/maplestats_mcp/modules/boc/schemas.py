"""Typed response models for the Bank of Canada Valet API module.

Field names and response shapes verified against live Valet responses
fetched this session (/lists/series/json, /lists/groups/json,
/series/FXUSDCAD/json, /groups/FX_RATES_DAILY/json, /groups/CPI_MONTHLY/json,
/observations/FXUSDCAD,FXEURCAD/json, /observations/group/FX_RATES_DAILY/json),
not guessed from documentation prose alone. Two real inconsistencies were
found and are modelled explicitly rather than smoothed over:

1. The single-series detail endpoint wraps its payload in a "seriesDetails"
   (plural) key holding one object with a "name" field, while the
   observations endpoint wraps per-series metadata in a "seriesDetail"
   (singular) key holding a *dict keyed by series code* whose values have
   no "name" field (the code is only available as the dict key). Same
   "Detail(s)" naming clash exists for groups.
2. The group-detail endpoint's payload key is "groupDetails" (plural) and
   includes "name"; the group-observations endpoint's payload key is
   "groupDetail" (singular) and has no "name" field at all (only
   label/description/link) - confirmed live against
   /groups/FX_RATES_DAILY/json vs /observations/group/FX_RATES_DAILY/json.
   GroupObservationsResult.group.name below is therefore populated by
   client.py from the caller's own input, not from the upstream payload.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel

from maplestats_mcp.shared.models import Provenance


class SeriesSummary(BaseModel):
    """One entry from /lists/series/json."""

    name: str
    label: str
    description: str


class SeriesList(BaseModel):
    series: list[SeriesSummary]
    total_count: int
    provenance: Provenance


class GroupSummary(BaseModel):
    """One entry from /lists/groups/json."""

    name: str
    label: str
    description: str


class GroupList(BaseModel):
    groups: list[GroupSummary]
    total_count: int
    provenance: Provenance


class SeriesDetail(BaseModel):
    """From /series/{name}/json's "seriesDetails" object."""

    name: str
    label: str
    description: str
    provenance: Provenance


class GroupMemberSeries(BaseModel):
    """One entry in /groups/{name}/json's "groupDetails.groupSeries" dict.

    Unlike SeriesSummary, Valet does not send a description here - only
    label + link (confirmed live) - so this is a deliberately smaller
    model, not a shortcut.
    """

    name: str
    label: str
    link: str | None = None


class GroupDetail(BaseModel):
    """From /groups/{name}/json's "groupDetails" object."""

    name: str
    label: str
    description: str
    series: list[GroupMemberSeries]
    provenance: Provenance


class SeriesInfoBrief(BaseModel):
    """One entry in an observations response's "seriesDetail" dict.

    No "name" field - the series code is only available as that dict's
    key, so client.py copies it in when building this model.
    """

    name: str
    label: str
    description: str


class Observation(BaseModel):
    """One row of an observations response.

    `values` is keyed by series code, not a fixed set of columns: Valet
    merges same-frequency series into one row per date (confirmed live
    for two daily FX series), but when series of genuinely different
    frequencies are requested together with a recent*/recent_weeks-style
    filter, it returns *unmerged* rows - each row carries only the
    series that actually has a value for that date (confirmed live
    mixing a daily FX series with a monthly CPI series under
    `recent=5`). Callers must not assume every requested series key is
    present in every row.
    """

    ref_date: date
    values: dict[str, float | None]


class GroupInfo(BaseModel):
    """Group metadata as carried on an observations-for-group response.

    `name` is populated by client.py from the caller's own group_name
    argument, not from the upstream payload - the group-observations
    endpoint's "groupDetail" object has no "name" field, unlike
    GroupDetail.name above (see this file's module docstring, point 2).
    """

    name: str
    label: str
    description: str
    link: str | None = None


class ObservationsResult(BaseModel):
    series: dict[str, SeriesInfoBrief]
    observations: list[Observation]
    provenance: Provenance


class GroupObservationsResult(BaseModel):
    group: GroupInfo
    series: dict[str, SeriesInfoBrief]
    observations: list[Observation]
    provenance: Provenance
