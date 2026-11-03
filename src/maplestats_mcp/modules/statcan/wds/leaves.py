"""The lowest-level members of a table dimension: the set to sum or rank over.

A leaf is a member whose memberId is no other member's parentMemberId, read
from the cached getCubeMetadata object. Leaves alone are not always safe to
add up; three patterns seen live (2026-11-03) are flagged instead of trusted:

- 18-10-0004 (CPI), products: "All-items" holds 224 leaves, but 18 other
  top-level members ("All-items excluding food", "Energy", "Goods and
  services" with its own small tree) are aggregates standing outside it.
  Leaves not under the top-level member with the most leaves are flagged
  `outside_main_hierarchy`.
- 36-10-0434 and 36-10-0402 (GDP by industry), NAICS: "Goods-producing
  industries", "Energy sector", "Public sector" are children of "All
  industries" with no children of their own, so they are leaves, yet they
  overlap the NAICS sectors. StatCan codes these special aggregates T001,
  T002... (classificationCode); they are flagged `special_aggregate`.
- Names that read as totals ("Total - Gender", "All-items", "Canada" at
  geoLevel 0) are flagged `total_name` when they happen to be leaves.

Some dimensions have no parent links at all (14-10-0287's age groups: "15
years and over" next to "15 to 24 years"), so every member is a leaf and
overlaps cannot be seen in the metadata; the result says so.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from maplestats_mcp.modules.statcan.wds import constants
from maplestats_mcp.modules.statcan.wds.client import (
    _LANG,
    _code_sets_raw,
    _fold,
    _m,
    cube_metadata_raw,
    normalize_product_id,
)
from maplestats_mcp.modules.statcan.wds.schemas import (
    LeafFlag,
    LeafMember,
    LeafMembers,
    TopLevelMember,
)
from maplestats_mcp.shared.envelope import make_provenance
from maplestats_mcp.shared.errors import (
    DataLocked,
    InvalidInput,
    NotFound,
    UpstreamError,
    UpstreamUnavailable,
)
from maplestats_mcp.shared.json_utils import list_or_empty

# Matched on the accent-folded English and French names. "All other ..." and
# "Toutes autres ..." are residual categories (CPI "All other passenger
# vehicle operating expenses"), not totals.
_TOTAL_NAME = re.compile(
    r"^(total\b|all\b(?!\s+other)|ensemble\b|(tous|toutes)\b(?!\s+(les\s+)?autres))"
    r"|\btotal\b"
)
# StatCan's special aggregates in NAICS dimensions (T001 All industries, T002
# Goods-producing industries, T016 Energy sector...), seen in 36-10-0434 and
# 36-10-0402; real NAICS codes are digits, with a letter suffix at most.
_SPECIAL_AGGREGATE = re.compile(r"^T\d{3}$")
TOP_LEVEL_LIMIT = 50
EXAMPLE_COORDINATES = 3


def _int(value: Any) -> int | None:
    try:
        return int(value) if value is not None and str(value).strip() != "" else None
    except ValueError:
        return None


def _name(member: dict[str, Any], fr: bool) -> str:
    return (member.get("memberNameFr") if fr else None) or member.get("memberNameEn") or ""


def _looks_total(member: dict[str, Any], is_root: bool) -> bool:
    names = (member.get("memberNameEn") or "", member.get("memberNameFr") or "")
    if any(_TOTAL_NAME.search(_fold(n).strip()) for n in names):
        return True
    # geoLevel 0 is Canada in every geography dimension checked (18-10-0004,
    # 14-10-0287, 36-10-0434); a national member named Canada with no geoLevel
    # is caught by the name.
    return _int(member.get("geoLevel")) == 0 or (is_root and _fold(names[0]).strip() == "canada")


async def _unit_names() -> dict[int, tuple[str | None, str | None]]:
    """memberUomCode -> (English, French), from getCodeSets; empty when unreadable."""
    try:
        codes, _ = await _code_sets_raw()
    except (UpstreamUnavailable, UpstreamError, DataLocked, NotFound):
        return {}
    names: dict[int, tuple[str | None, str | None]] = {}
    for entry in list_or_empty(codes, "uom"):
        code = _int(entry.get("memberUomCode"))
        if code is not None:
            names[code] = (entry.get("memberUomEn"), entry.get("memberUomFr"))
    return names


async def get_leaf_members(
    product_id: int | str,
    dimension: int,
    *,
    under_member_id: int | None = None,
    member_query: str | None = None,
    include_flagged: bool = False,
    limit: int = constants.LEAF_LIMIT_DEFAULT,
    offset: int = 0,
) -> LeafMembers:
    pid = normalize_product_id(product_id)
    if limit < 1 or limit > constants.MEMBER_LIMIT_MAX or offset < 0:
        raise InvalidInput(
            _m(
                f"limit must be between 1 and {constants.MEMBER_LIMIT_MAX}, offset 0 or more.",
                f"limit doit être entre 1 et {constants.MEMBER_LIMIT_MAX}, offset 0 ou plus.",
            )
        )
    fr = _LANG.get() == "fr"
    cube, was_cached = await cube_metadata_raw(pid)
    dims = list_or_empty(cube, "dimension")
    dim = next((d for d in dims if _int(d.get("dimensionPositionId")) == dimension), None)
    if dim is None:
        positions = [_int(d.get("dimensionPositionId")) for d in dims]
        raise InvalidInput(
            _m(
                f"Table {pid} has no dimension {dimension}; positions are {positions}. "
                f"wds_get_cube_metadata(product_id={pid}, member_limit=1) names them.",
                f"Le tableau {pid} n'a pas de dimension {dimension}; positions : {positions}. "
                f"wds_get_cube_metadata(product_id={pid}, member_limit=1) les nomme.",
            )
        )
    dim_name = (dim.get("dimensionNameFr") if fr else None) or dim.get("dimensionNameEn") or ""
    members = [m for m in list_or_empty(dim, "member") if _int(m.get("memberId")) is not None]
    by_id: dict[int, dict[str, Any]] = {int(m["memberId"]): m for m in members}

    def parent_of(member_id: int) -> int | None:
        # A parentMemberId absent from the dimension (none seen live) would make
        # the member unreachable from any root; treat it as a top-level member.
        parent = _int(by_id[member_id].get("parentMemberId"))
        return parent if parent in by_id and parent != member_id else None

    parent_ids = {p for i in by_id if (p := parent_of(i)) is not None}

    def ancestry(member_id: int) -> list[int]:
        """The member and its ancestors up to its top-level member (cycle-safe)."""
        chain = [member_id]
        while (parent := parent_of(chain[-1])) is not None and parent not in chain:
            chain.append(parent)
        return chain

    hierarchical = bool(parent_ids)
    all_leaves = [i for i in by_id if i not in parent_ids]
    root_of = {i: ancestry(i)[-1] for i in all_leaves}
    leaves_per_root = Counter(root_of.values())
    roots = [i for i in by_id if parent_of(i) is None]
    main_root = max(roots, key=lambda r: leaves_per_root.get(r, 0)) if roots else None

    if under_member_id is not None and under_member_id not in by_id:
        raise InvalidInput(
            _m(
                f"Dimension {dimension} ({dim_name}) of table {pid} has no member "
                f"{under_member_id}. Find its id with wds_get_cube_metadata(product_id={pid}, "
                f"dimension={dimension}, member_query='<words>').",
                f"La dimension {dimension} ({dim_name}) du tableau {pid} n'a pas de membre "
                f"{under_member_id}. Trouvez son identifiant avec wds_get_cube_metadata("
                f"product_id={pid}, dimension={dimension}, member_query='<mots>').",
            )
        )
    in_scope = [i for i in by_id if under_member_id is None or under_member_id in ancestry(i)]
    scope_leaves = [i for i in in_scope if i not in parent_ids]
    words = _fold(member_query).split() if member_query else []

    def matches(member_id: int) -> bool:
        m = by_id[member_id]
        text = f"{_fold(m.get('memberNameEn') or '')} {_fold(m.get('memberNameFr') or '')}"
        return all(w in text for w in words)

    matched = [i for i in scope_leaves if matches(i)]

    # outside_main_hierarchy only means something when the dimension has a
    # tree and more than one top-level member holds leaves; under_member_id
    # already keeps one branch.
    check_main = (
        under_member_id is None
        and hierarchical
        and sum(1 for r in roots if leaves_per_root.get(r)) > 1
    )

    def flags_for(member_id: int) -> list[LeafFlag]:
        m = by_id[member_id]
        flags: list[LeafFlag] = []
        if _looks_total(m, parent_of(member_id) is None):
            flags.append("total_name")
        if _SPECIAL_AGGREGATE.match(str(m.get("classificationCode") or "").strip()):
            flags.append("special_aggregate")
        if check_main and root_of[member_id] != main_root:
            flags.append("outside_main_hierarchy")
        return flags

    units = await _unit_names() if dim.get("hasUom") else {}

    def leaf(member_id: int, flags: list[LeafFlag]) -> LeafMember:
        m = by_id[member_id]
        parent = parent_of(member_id)
        uom = _int(m.get("memberUomCode"))
        unit_en, unit_fr = units.get(uom, (None, None)) if uom is not None else (None, None)
        return LeafMember(
            member_id=member_id,
            member_name=_name(m, fr),
            parent_member_id=parent,
            parent_name=_name(by_id[parent], fr) if parent is not None else None,
            classification_code=(m.get("classificationCode") or None),
            geo_level=_int(m.get("geoLevel")),
            unit=(unit_fr or unit_en) if fr else unit_en,
            terminated=bool(_int(m.get("terminated")) or 0),
            flags=flags,
        )

    flagged_ids = {i: f for i in matched if (f := flags_for(i))}
    selected = matched if include_flagged else [i for i in matched if i not in flagged_ids]
    page = selected[offset : offset + limit]
    leaves = [leaf(i, flagged_ids.get(i, [])) for i in page]
    flagged = (
        []
        if include_flagged
        else [leaf(i, f) for i, f in flagged_ids.items()][: constants.MEMBER_LIMIT_MAX]
    )
    ids = [x.member_id for x in leaves]

    # Other dimensions at their first top-level member: usually the total
    # (Canada, All-items, Total - Gender), so the example coordinates exist.
    defaults: list[str] = []
    for d in dims:
        if d is dim:
            defaults.append("{}")
            continue
        top = next(
            (
                str(m["memberId"])
                for m in list_or_empty(d, "member")
                if _int(m.get("parentMemberId")) is None
            ),
            None,
        ) or next((str(m["memberId"]) for m in list_or_empty(d, "member")), "1")
        defaults.append(top)
    template = ".".join(defaults)
    examples = [template.format(i) for i in ids[:EXAMPLE_COORDINATES]]
    fragment = "+".join(str(i) for i in ids)
    position_index = dims.index(dim)
    sdmx_key = ".".join(fragment if n == position_index else "" for n in range(len(dims)))

    notes = _notes(
        pid=pid,
        dimension=dimension,
        hierarchical=hierarchical,
        leaves=leaves,
        flagged=flagged_ids,
        include_flagged=include_flagged,
        main_root=by_id[main_root] if check_main and main_root is not None else None,
        main_root_id=main_root,
        no_match_parents=[i for i in in_scope if i in parent_ids and matches(i)]
        if words and not matched
        else [],
        by_id=by_id,
        fr=fr,
    )
    limits = None
    if len(page) < len(selected):
        limits = _m(
            f"{len(page)} of {len(selected)} leaves from offset {offset}; use limit/offset, "
            "under_member_id or member_query for the rest",
            f"{len(page)} des {len(selected)} membres terminaux à partir de {offset} ; "
            "utilisez limit/offset, under_member_id ou member_query pour la suite",
        )
    return LeafMembers(
        product_id=pid,
        dimension_position=dimension,
        dimension_name=dim_name,
        member_count=len(by_id),
        under_member_id=under_member_id,
        parent_count=len(in_scope) - len(scope_leaves),
        leaf_count=len(matched),
        flagged_count=len(flagged_ids),
        selected_count=len(selected),
        leaves=leaves,
        flagged_leaves=flagged,
        member_ids=ids,
        member_ids_csv=",".join(str(i) for i in ids),
        sdmx_key_fragment=fragment,
        sdmx_key=sdmx_key,
        example_coordinates=examples,
        top_level_members=[
            TopLevelMember(
                member_id=r, member_name=_name(by_id[r], fr), leaf_count=leaves_per_root.get(r, 0)
            )
            for r in roots[:TOP_LEVEL_LIMIT]
        ],
        geo_levels=dict(Counter(str(x.geo_level) for x in leaves if x.geo_level is not None)),
        notes=notes,
        provenance=make_provenance(
            source="statcan-wds",
            url=f"{constants.BASE_URL}getCubeMetadata",
            cached=was_cached,
            schema_name="statcan.wds.LeafMembers",
            coverage=_m(
                f"{len(matched)} leaves of {len(by_id)} members in dimension {dimension}",
                f"{len(matched)} membres terminaux sur {len(by_id)} dans la dimension {dimension}",
            ),
            limits=limits,
            lang=_LANG.get(),
        ),
    )


def _notes(
    *,
    pid: int,
    dimension: int,
    hierarchical: bool,
    leaves: list[LeafMember],
    flagged: dict[int, list[LeafFlag]],
    include_flagged: bool,
    main_root: dict[str, Any] | None,
    main_root_id: int | None,
    no_match_parents: list[int],
    by_id: dict[int, dict[str, Any]],
    fr: bool,
) -> list[str]:
    notes: list[str] = []
    if not hierarchical:
        notes.append(
            _m(
                "No member of this dimension has a parent, so every member is a leaf and the "
                "metadata cannot show overlaps (an age group '15 years and over' next to "
                "'15 to 24 years', rates next to counts): read the names before summing.",
                "Aucun membre de cette dimension n'a de parent : chaque membre est terminal et "
                "les métadonnées ne montrent pas les chevauchements (un groupe « 15 ans et "
                "plus » à côté de « 15 à 24 ans », des taux à côté de comptes) : lisez les noms "
                "avant d'additionner.",
            )
        )
    if flagged and not include_flagged:
        notes.append(
            _m(
                f"{len(flagged)} leaves set aside in flagged_leaves because they may "
                "double-count (totals, special aggregates, or other hierarchies); "
                "include_flagged=True keeps them.",
                f"{len(flagged)} membres terminaux mis de côté dans flagged_leaves parce "
                "qu'ils peuvent compter deux fois (totaux, agrégats spéciaux ou autres "
                "hiérarchies) ; include_flagged=True les garde.",
            )
        )
    if main_root is not None and any("outside_main_hierarchy" in f for f in flagged.values()):
        name = _name(main_root, fr)
        notes.append(
            _m(
                f"The dimension has several top-level members; the main hierarchy is "
                f"'{name}' ({main_root_id}). under_member_id picks another one.",
                f"La dimension a plusieurs membres de premier niveau ; la hiérarchie "
                f"principale est « {name} » ({main_root_id}). under_member_id en choisit une "
                "autre.",
            )
        )
    units = {x.unit for x in leaves if x.unit}
    if len(units) > 1:
        shown = ", ".join(sorted(units))
        notes.append(
            _m(
                f"The leaves are in different units ({shown}): only add up leaves that share "
                "a unit.",
                f"Les membres terminaux sont dans des unités différentes ({shown}) : "
                "n'additionnez que ceux qui ont la même unité.",
            )
        )
    levels = sorted({x.geo_level for x in leaves if x.geo_level is not None})
    if len(levels) > 1:
        notes.append(
            _m(
                f"The leaves sit at different geographic levels (geoLevel {levels}): a "
                "province with cities under it is a parent here, so the leaves are its "
                "cities, and they need not add up to the province or to Canada. To compare "
                "provinces, list geoLevel 2 members with wds_get_cube_metadata("
                f"product_id={pid}, dimension={dimension}).",
                f"Les membres terminaux sont à des niveaux géographiques différents (geoLevel "
                f"{levels}) : une province qui contient des villes est ici un parent, les "
                "membres terminaux sont donc ses villes, dont la somme n'égale pas "
                "nécessairement la province ni le Canada. Pour comparer les provinces, "
                f"listez les membres de geoLevel 2 avec wds_get_cube_metadata(product_id={pid}, "
                f"dimension={dimension}).",
            )
        )
    terminated = sum(1 for x in leaves if x.terminated)
    if terminated:
        notes.append(
            _m(
                f"{terminated} leaves are terminated: their series stopped and have no "
                "recent data.",
                f"{terminated} membres terminaux sont terminés : leurs séries ont cessé et "
                "n'ont pas de données récentes.",
            )
        )
    if no_match_parents:
        shown = "; ".join(f"{i} {_name(by_id[i], fr)}" for i in no_match_parents[:5])
        notes.append(
            _m(
                f"member_query matches no leaf, only parents ({shown}): pass one of their ids "
                "as under_member_id for the leaves below it.",
                f"member_query ne correspond à aucun membre terminal, seulement à des parents "
                f"({shown}) : passez un de leurs identifiants comme under_member_id pour "
                "obtenir les membres terminaux en dessous.",
            )
        )
    notes.append(
        _m(
            "Use: member_ids one at a time at this dimension's position in a "
            "wds_get_data_from_cube_coord coordinate (example_coordinates), or "
            "sdmx_key_fragment at this position of an sdmx_get_data key (sdmx_key), which "
            "fetches them in one call.",
            "Utilisation : chaque member_id à la position de cette dimension dans une "
            "coordonnée de wds_get_data_from_cube_coord (example_coordinates), ou "
            "sdmx_key_fragment à cette position d'une clé sdmx_get_data (sdmx_key), en un "
            "seul appel.",
        )
    )
    return notes
