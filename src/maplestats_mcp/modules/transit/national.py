"""The agencies of StatCan's Canadian Public Transit Network Database (23-26-0003).

The archive holds one inner `gtfs/<custom_id>/gtfs.zip` per feed plus
`data_sources.csv` (where each feed came from, its licence page and the
attribution line) and `validation_summary.csv` (agency name, service
window and validator notice counts). This file turns those two tables
into `Agency` entries; the client reads a feed itself with
`zipstream.read_nested_zip`.

Confirmed live 2026-10-02: `data_sources.csv` is Windows-1252 text, not
UTF-8 (a lone 0xE9 byte), and a few attribution lines already arrive as
mojibake from the database itself; they are passed through as published.
Fourteen feeds have neither a licence page nor an attribution line, and
are left out because their reuse terms cannot be confirmed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from maplestats_mcp.modules.transit import constants, gtfs
from maplestats_mcp.modules.transit.constants import Agency
from maplestats_mcp.modules.transit.zipstream import STATCAN_LIMITER
from maplestats_mcp.shared.envelope import raise_localized
from maplestats_mcp.shared.errors import UpstreamError
from maplestats_mcp.shared.remote_zip import ZipMember, list_members, read_member

CSV_MAX_BYTES = 2_000_000


@dataclass(frozen=True)
class Catalog:
    agencies: dict[str, Agency]
    members: dict[str, ZipMember]
    total_bytes: int


def member_path(custom_id: str) -> str:
    return f"{constants.NATIONAL_ROOT}gtfs/{custom_id}/gtfs.zip"


def _iso(value: str | None) -> date | None:
    try:
        return date.fromisoformat((value or "").strip())
    except ValueError:
        return None


def _count(value: str | None) -> int | None:
    text = (value or "").strip()
    return int(text) if text.isdigit() else None


def _title(custom_id: str) -> str:
    return custom_id.replace("_", " ").title()


def _status(
    custom_id: str, source: dict[str, str], present: bool
) -> tuple[str, str, str, str | None]:
    """(status, reason, French reason, live agency key) for one feed of the database."""
    live_key = constants.NATIONAL_OVERLAPS.get(custom_id)
    if live_key:
        return (
            "overlaps_live",
            f"Already read live from the agency's own site: use agency='{live_key}'.",
            f"Déjà lu en direct sur le site de l'organisme : utilisez agency='{live_key}'.",
            live_key,
        )
    if custom_id in constants.NATIONAL_EXCLUDED:
        return (
            "excluded",
            constants.NATIONAL_EXCLUDED[custom_id],
            constants.NATIONAL_EXCLUDED_FR.get(custom_id, ""),
            None,
        )
    if not present:
        return (
            "excluded",
            "Listed in data_sources.csv but absent from the archive.",
            "Inscrit dans data_sources.csv, mais absent de l'archive.",
            None,
        )
    if not source.get("license_url") and not source.get("attribution"):
        return (
            "excluded",
            (
                "The database records neither a licence page nor an attribution line for "
                "this feed, so its reuse terms cannot be confirmed."
            ),
            (
                "La base de données n'indique ni page de licence ni mention de source pour ce "
                "flux ; ses conditions de réutilisation ne peuvent donc pas être confirmées."
            ),
            None,
        )
    return "available", "", "", None


def build_agencies(
    sources: list[dict[str, str]],
    validation: list[dict[str, str]],
    archive_names: set[str],
) -> dict[str, Agency]:
    """One `Agency` per row of data_sources.csv, keyed `national:<custom_id>`."""
    checks = {row.get("custom_id", ""): row for row in validation}
    agencies: dict[str, Agency] = {}
    for source in sources:
        custom_id = source.get("custom_id", "")
        if not custom_id:
            continue
        check = checks.get(custom_id, {})
        status, reason, reason_fr, live_key = _status(
            custom_id, source, member_path(custom_id) in archive_names
        )
        province = (source.get("prov_terr") or "").strip().lower()
        name = (check.get("agency_name") or "").strip() or _title(custom_id)
        key = f"{constants.NATIONAL_PREFIX}{custom_id}"
        own_licence = source.get("license_url", "").strip()
        attribution = source.get("attribution", "").strip()
        agencies[key] = Agency(
            key=key,
            name_en=name,
            name_fr=name,
            city="",
            province=province.upper() or "CA",
            timezone=constants.PROVINCE_TIMEZONES.get(province, "America/Toronto"),
            feed_url=constants.NATIONAL_URL,
            source_page=source.get("data_page", "").strip() or constants.NATIONAL_PAGE,
            licence=(
                "Agency licence recorded by Statistics Canada"
                if own_licence
                else "No agency licence page recorded by Statistics Canada"
            ),
            licence_url=own_licence or constants.NATIONAL_LICENCE_URL,
            attribution=(
                f"{attribution} | {constants.NATIONAL_NOTICE}"
                if attribution
                else constants.NATIONAL_NOTICE
            ),
            update_cadence=constants.NATIONAL_FRESHNESS,
            licence_fr=(
                "Licence de l'organisme consignée par Statistique Canada"
                if own_licence
                else "Aucune page de licence de l'organisme consignée par Statistique Canada"
            ),
            # The agency's own credit line is kept as published (often English).
            attribution_fr=(
                f"{attribution} | {constants.NATIONAL_NOTICE_FR}"
                if attribution
                else constants.NATIONAL_NOTICE_FR
            ),
            update_cadence_fr=constants.NATIONAL_FRESHNESS_FR,
            notes_en=(
                f"Feed id {custom_id} in the StatCan database; the agency's own download is "
                f"{source.get('direct_url', '').strip() or 'not recorded'}. The compilation "
                f"is under {constants.NATIONAL_LICENCE}."
            ),
            notes_fr=(
                f"Identifiant {custom_id} dans la {constants.NATIONAL_NAME_FR} de Statistique "
                "Canada ; téléchargement de l'organisme : "
                f"{source.get('direct_url', '').strip() or 'non indiqué'}. La compilation est "
                "sous la Licence ouverte de Statistique Canada / Licence du gouvernement "
                "ouvert – Canada; chaque flux porte aussi la licence de son organisme "
                "(licence_url)."
            ),
            database="statcan",
            status=status,
            status_reason=reason,
            status_reason_fr=reason_fr,
            live_agency_key=live_key,
            window_start=_iso(check.get("feed_service_window_start")),
            window_end=_iso(check.get("feed_service_window_end")),
            validator_errors=_count(check.get("num_error")),
            validator_warnings=_count(check.get("num_warning")),
        )
    return agencies


async def _read_csv(
    url: str, members: dict[str, ZipMember], name: str, *, lang: str = "en"
) -> list[dict[str, str]]:
    member = members.get(f"{constants.NATIONAL_ROOT}{name}")
    if member is None:
        raise_localized(
            UpstreamError,
            f"{url}: the archive has no {name}.",
            f"{url} : l'archive ne contient pas {name}.",
            lang,
        )
    # read_member makes two requests (local header, then data).
    await STATCAN_LIMITER.acquire()
    await STATCAN_LIMITER.acquire()
    data = await read_member(url, member, max_bytes=CSV_MAX_BYTES)
    return gtfs.parse_table(data)


async def load_catalog(*, lang: str = "en") -> Catalog:
    """Read the archive's directory and its two metadata tables (about six requests)."""
    url = constants.NATIONAL_URL
    # list_members makes two requests (size, then the tail with the directory).
    await STATCAN_LIMITER.acquire()
    await STATCAN_LIMITER.acquire()
    listed, total = await list_members(url)
    members = {m.name: m for m in listed}
    sources = await _read_csv(url, members, "data_sources.csv", lang=lang)
    validation = await _read_csv(url, members, "validation_summary.csv", lang=lang)
    return Catalog(build_agencies(sources, validation, set(members)), members, total)
