"""Client for the Medical Devices Active Licence Listing (MDALL) API.

Checked live 2026-10-03 (see also ../api.py and constants.py):

1. `licence?licence_name=` and `device?device_name=` are fast substring
   filters, but `licence?company_id=` is a substring match too and took
   65 s for one company, and `device?licence_number=` is ignored (all
   302,429 devices come back). So licences are searched in the whole
   licence table (21 MB, cached six hours as compact rows), and a
   licence's devices are read by streaming the device table once and
   keeping that licence's rows.
2. `company?company_name=` is a substring filter; `company?id=` and
   `licence?id=` answer one object, an all-null one with id 0 when unknown.
3. `deviceidentifier?id=` takes a device id and answers that device's
   model or catalogue numbers; `?device_identifier=` is a substring search.
4. The company table has no lang parameter; licence type labels come back
   in French with lang=fr ("Famille d'instruments"), and trade names are
   the same in both languages.
"""

from __future__ import annotations

import asyncio
from collections import Counter
from typing import Any

from maplestats_mcp.modules.health_products import api
from maplestats_mcp.modules.health_products.mdall import constants
from maplestats_mcp.modules.health_products.mdall.schemas import (
    Device,
    DeviceCompany,
    DeviceLicence,
    DeviceLicenceDetail,
    DeviceLicenceList,
    DeviceList,
)
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.errors import InvalidInput, NotFound

# licence number, status code, risk class, name, first issued, end date,
# licence type code, company id
LicenceRow = tuple[int, str, int | None, str, str, str, str, int]
CompanyRow = tuple[str, str, str, str, str, str, str]
# Identifiers are fetched one request per device, so only for short lists.
_IDENTIFIER_DEVICES_MAX = 25


def _fold(value: str) -> str:
    return " ".join(value.casefold().split())


def _int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


async def _licences() -> tuple[list[LicenceRow], bool]:
    async def fetch() -> list[LicenceRow]:
        rows = api.as_list(await api.get_json(constants.PATH_LICENCE, lang="en", timeout=120.0))
        return [
            (
                int(r["original_licence_no"]),
                r.get("licence_status") or "",
                _int(r.get("appl_risk_class")),
                api.text(r.get("licence_name")) or "",
                r.get("first_licence_status_dt") or "",
                r.get("end_date") or "",
                r.get("licence_type_cd") or "",
                _int(r.get("company_id")) or 0,
            )
            for r in rows
            if r.get("original_licence_no")
        ]

    return await cached_fetch("hc_mdall:licences", constants.TABLE_TTL_SECONDS, fetch)


async def _companies() -> dict[int, CompanyRow]:
    async def fetch() -> dict[int, CompanyRow]:
        rows = api.as_list(await api.get_json(constants.PATH_COMPANY, lang=None, timeout=120.0))
        out: dict[int, CompanyRow] = {}
        for r in rows:
            if not r.get("company_id"):
                continue
            address = ", ".join(
                x for x in (api.text(r.get(f"addr_line_{i}")) for i in (1, 2, 3)) if x
            )
            out[int(r["company_id"])] = (
                api.text(r.get("company_name")) or "",
                address,
                api.text(r.get("city")) or "",
                api.text(r.get("region_cd")) or "",
                api.text(r.get("country_cd")) or "",
                api.text(r.get("postal_code")) or "",
                r.get("company_status") or "",
            )
        return out

    data, _ = await cached_fetch("hc_mdall:companies", constants.TABLE_TTL_SECONDS, fetch)
    return data


def _licence(row: LicenceRow, companies: dict[int, CompanyRow], lang: str) -> DeviceLicence:
    number, status, risk, name, first, end, kind, company_id = row
    labels = constants.LICENCE_STATUSES.get(status)
    kind_label = None
    if kind:
        kind_label = (
            constants.LICENCE_TYPES_FR.get(kind)
            if lang == "fr"
            else {
                "D": "Single Device",
                "S": "System",
                "K": "Test Kit",
                "F": "Device Family",
                "G": "Device Group",
                "Y": "Device Group Family",
            }.get(kind)
        )
    company = companies.get(company_id)
    return DeviceLicence(
        licence_number=number,
        licence_name=name or None,
        status=(labels[1] if lang == "fr" else labels[0]) if labels else status or None,
        status_code=status or None,
        risk_class=risk,
        licence_type=kind_label or kind or None,
        first_issued=first or None,
        end_date=end or None,
        company_id=company_id or None,
        company_name=company[0] if company else None,
    )


def _company(company_id: int, row: CompanyRow) -> DeviceCompany:
    name, address, city, region, country, postal, status = row
    return DeviceCompany(
        company_id=company_id,
        name=name,
        address=address or None,
        city=city or None,
        region=region or None,
        country=country or None,
        postal_code=postal or None,
        active=None if not status else status == "A",
    )


async def search_licences(
    name: str = "",
    *,
    company: str = "",
    active_only: bool = True,
    risk_class: int | None = None,
    limit: int = constants.LIMIT_DEFAULT,
    lang: str = "en",
) -> DeviceLicenceList:
    name, company = name.strip(), company.strip()
    if len(name) < 2 and len(company) < 2:
        api.fail(
            InvalidInput,
            "Give at least 2 characters of a licence (device) name or company.",
            "donnez au moins 2 caractères d'un nom d'homologation (instrument) ou d'une "
            "entreprise.",
            lang,
        )
    if risk_class is not None and risk_class not in (2, 3, 4):
        api.fail(
            InvalidInput,
            "risk_class must be 2, 3 or 4; class I devices are not licensed.",
            "risk_class doit valoir 2, 3 ou 4 ; les instruments de classe I ne sont pas "
            "homologués.",
            lang,
        )
    if not 1 <= limit <= constants.LIMIT_MAX:
        api.fail(
            InvalidInput,
            f"limit must be between 1 and {constants.LIMIT_MAX}.",
            f"limit doit être compris entre 1 et {constants.LIMIT_MAX}.",
            lang,
        )
    rows, cached = await _licences()
    companies = await _companies()
    if name:
        needle = _fold(name)
        rows = [r for r in rows if needle in _fold(r[3])]
    if company:
        needle = _fold(company)
        ids = {cid for cid, c in companies.items() if needle in _fold(c[0])}
        rows = [r for r in rows if r[7] in ids]
    if active_only:
        rows = [r for r in rows if not r[5]]
    if risk_class is not None:
        rows = [r for r in rows if r[2] == risk_class]
    rows = sorted(rows, key=lambda r: (bool(r[5]), r[3], r[0]))
    page = [_licence(r, companies, lang) for r in rows[:limit]]
    filters = ", ".join(
        part
        for part in (
            f"name contains '{name}'" if name else "",
            f"company contains '{company}'" if company else "",
            "active only" if active_only else "",
            f"class {risk_class}" if risk_class else "",
        )
        if part
    )
    filters_fr = ", ".join(
        part
        for part in (
            f"le nom contient '{name}'" if name else "",
            f"l'entreprise contient '{company}'" if company else "",
            "actives seulement" if active_only else "",
            f"classe {risk_class}" if risk_class else "",
        )
        if part
    )
    return DeviceLicenceList(
        licences=page,
        returned_count=len(page),
        total_matched=len(rows),
        by_risk_class=dict(
            sorted(Counter(f"class {r[2]}" if r[2] else "unknown" for r in rows).items())
        ),
        provenance=api.provenance(
            api.url_for(constants.PATH_LICENCE),
            cached=cached,
            schema="DeviceLicenceList",
            freshness=constants.FRESHNESS,
            coverage=f"{len(page)} of {len(rows)} licences: {filters}",
            limits="whole licence table cached up to 6 h",
            lang=lang,
            freshness_fr=constants.FRESHNESS_FR,
            coverage_fr=f"{len(page)} homologations sur {len(rows)} : {filters_fr}",
            limits_fr="table complète des homologations en cache jusqu'à 6 h ; les noms "
            "commerciaux sont ceux déposés",
        ),
    )


def _device(row: dict[str, Any], identifiers: list[str] | None = None) -> Device:
    return Device(
        device_id=int(row["device_id"]),
        licence_number=int(row.get("original_licence_no") or 0),
        trade_name=api.text(row.get("trade_name")),
        first_licensed=api.text(row.get("first_licence_dt")),
        end_date=api.text(row.get("end_date")),
        identifiers=identifiers or [],
    )


async def _identifiers(keys: list[tuple[int, int]]) -> dict[tuple[int, int], list[str]]:
    """Model numbers per (device id, licence number).

    One device id can sit on several licences (DEXCOM G7 ANDROID CGM APP,
    1048489, is on 109685 and 115760), and `deviceidentifier?id=` answers
    the rows of every licence, so they are kept per licence.
    """
    device_ids = sorted({d for d, _ in keys})
    answers = await asyncio.gather(
        *(
            api.get_json(constants.PATH_IDENTIFIER, {"id": d}, lang=None, missing_ok=True)
            for d in device_ids
        )
    )
    out: dict[tuple[int, int], set[str]] = {key: set() for key in keys}
    for device_id, answer in zip(device_ids, answers, strict=True):
        for r in api.as_list(answer):
            key = (device_id, _int(r.get("original_licence_no")) or 0)
            label = api.text(r.get("device_identifier"))
            if key in out and label:
                out[key].add(label)
    return {key: sorted(labels) for key, labels in out.items()}


def _key(row: dict[str, Any]) -> tuple[int, int]:
    return int(row["device_id"]), _int(row.get("original_licence_no")) or 0


async def get_licence(licence_number: int, *, lang: str = "en") -> DeviceLicenceDetail:
    if licence_number <= 0:
        api.fail(
            InvalidInput,
            "licence_number must be a positive number, e.g. 102449.",
            "licence_number doit être un nombre positif, p. ex. 102449.",
            lang,
        )

    async def fetch() -> DeviceLicenceDetail:
        rows, _ = await _licences()
        row = next((r for r in rows if r[0] == licence_number), None)
        if row is None:
            api.fail(
                NotFound,
                f"No medical device licence has number {licence_number}.",
                f"aucune homologation d'instrument médical ne porte le numéro {licence_number}.",
                lang,
            )
        companies = await _companies()
        devices = [
            r
            async for r in api.stream_objects(constants.PATH_DEVICE, lang=None)
            if r.get("original_licence_no") == licence_number and r.get("device_id")
        ]
        devices.sort(key=lambda r: (bool(r.get("end_date")), r.get("trade_name") or ""))
        identifiers: dict[tuple[int, int], list[str]] = {}
        if len(devices) <= _IDENTIFIER_DEVICES_MAX:
            identifiers = await _identifiers([_key(r) for r in devices])
        company = companies.get(row[7])
        return DeviceLicenceDetail(
            licence=_licence(row, companies, lang),
            company=_company(row[7], company) if company else None,
            devices=[_device(r, identifiers.get(_key(r))) for r in devices],
            device_count=len(devices),
            mdall_page=constants.SEARCH_PAGE,
            provenance=api.provenance(
                f"{api.url_for(constants.PATH_LICENCE)}?id={licence_number}&type=json",
                cached=False,
                schema="DeviceLicenceDetail",
                freshness=constants.FRESHNESS,
                limits=(
                    None
                    if len(devices) <= _IDENTIFIER_DEVICES_MAX
                    else f"identifiers omitted for licences with over {_IDENTIFIER_DEVICES_MAX} "
                    "devices; search them with hc_device_search_devices"
                ),
                lang=lang,
                freshness_fr=constants.FRESHNESS_FR,
                limits_fr=(
                    None
                    if len(devices) <= _IDENTIFIER_DEVICES_MAX
                    else f"identifiants omis pour les homologations de plus de "
                    f"{_IDENTIFIER_DEVICES_MAX} instruments ; cherchez-les avec "
                    "hc_device_search_devices"
                ),
            ),
        )

    detail, cached = await cached_fetch(
        f"hc_mdall:licence:{licence_number}:{lang}", constants.LOOKUP_TTL_SECONDS, fetch
    )
    if cached:
        detail = detail.model_copy(
            update={"provenance": detail.provenance.model_copy(update={"cached": True})}
        )
    return detail


async def search_devices(
    name: str = "",
    *,
    identifier: str = "",
    active_only: bool = True,
    limit: int = constants.LIMIT_DEFAULT,
    lang: str = "en",
) -> DeviceList:
    name, identifier = name.strip(), identifier.strip()
    if bool(name) == bool(identifier):
        api.fail(
            InvalidInput,
            "Give either a device name or a device identifier (model number).",
            "donnez soit un nom d'instrument, soit un identifiant d'instrument (numéro de modèle).",
            lang,
        )
    if len(name or identifier) < 3:
        api.fail(
            InvalidInput,
            "Give at least 3 characters to search for.",
            "donnez au moins 3 caractères à chercher.",
            lang,
        )
    if not 1 <= limit <= constants.LIMIT_MAX:
        api.fail(
            InvalidInput,
            f"limit must be between 1 and {constants.LIMIT_MAX}.",
            f"limit doit être compris entre 1 et {constants.LIMIT_MAX}.",
            lang,
        )
    # Trade names and identifiers are not translated by the API.
    state = {"state": "active"} if active_only else {}
    if name:
        path = constants.PATH_DEVICE
        rows = [
            r
            for r in api.as_list(
                await api.get_json(path, {"device_name": name, **state}, lang=None, timeout=90.0)
            )
            if r.get("device_id")
        ]
        rows.sort(key=lambda r: (r.get("trade_name") or "", r["device_id"]))
        page = rows[:limit]
        keys = [_key(r) for r in page]
        found = await _identifiers(keys) if len(keys) <= _IDENTIFIER_DEVICES_MAX else {}
        devices = [_device(r, found.get(_key(r))) for r in page]
        total = len(rows)
    else:
        path = constants.PATH_IDENTIFIER
        rows = api.as_list(
            await api.get_json(
                path, {"device_identifier": identifier, **state}, lang=None, timeout=90.0
            )
        )
        grouped: dict[tuple[int, int], list[dict[str, Any]]] = {}
        for r in rows:
            if r.get("device_id"):
                grouped.setdefault(_key(r), []).append(r)
        keys = sorted(grouped)[:limit]
        device_ids = sorted({d for d, _ in keys})
        details = await asyncio.gather(
            *(api.get_json(constants.PATH_DEVICE, {"id": d}, lang=None) for d in device_ids)
        )
        names = {
            device_id: api.text(r.get("trade_name"))
            for device_id, answer in zip(device_ids, details, strict=True)
            for r in api.as_list(answer)
            if not api.is_blank(r, "device_id")
        }
        devices = []
        for key in keys:
            first = grouped[key][0]
            labels = sorted(
                {x for r in grouped[key] if (x := api.text(r.get("device_identifier")))}
            )
            devices.append(_device({**first, "trade_name": names.get(key[0])}, labels))
        total = len(grouped)
    return DeviceList(
        devices=devices,
        returned_count=len(devices),
        total_matched=total,
        provenance=api.provenance(
            api.url_for(path),
            cached=False,
            schema="DeviceList",
            freshness=constants.FRESHNESS,
            coverage=(
                f"{len(devices)} of {total} devices whose "
                + (f"name contains '{name}'" if name else f"identifier contains '{identifier}'")
                + (", active only" if active_only else "")
            ),
            lang=lang,
            freshness_fr=constants.FRESHNESS_FR,
            coverage_fr=(
                f"{len(devices)} instruments sur {total} dont "
                + (
                    f"le nom contient '{name}'"
                    if name
                    else f"l'identifiant contient '{identifier}'"
                )
                + (", actifs seulement" if active_only else "")
            ),
            limits_fr="Les noms commerciaux et les identifiants sont ceux déposés, non traduits.",
        ),
    )
