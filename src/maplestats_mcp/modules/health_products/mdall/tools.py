"""MCP tools for Health Canada's Medical Devices Active Licence Listing (MDALL)."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.health_products import api
from maplestats_mcp.modules.health_products.mdall import client
from maplestats_mcp.modules.health_products.mdall.schemas import (
    DeviceLicenceDetail,
    DeviceLicenceList,
    DeviceList,
)

Lang = Literal["en", "fr"]


@tool
async def hc_device_search_licences(
    name: str = "",
    company: str = "",
    active_only: bool = True,
    risk_class: Literal[2, 3, 4] | None = None,
    limit: int = 50,
    lang: Lang = "en",
) -> DeviceLicenceList:
    """Search Health Canada medical device licences (MDALL) by device name or company.

    Use for: whether a medical device is licensed for sale in Canada:
    licence number, licence name, device class (2, 3 or 4 by risk; class I
    devices need no licence), licence type (single device, family, system,
    test kit), first issue date, cancellation date and the manufacturer.
    `name` matches the licence name (e.g. 'insulin pump', 'pacemaker',
    'COVID-19 test'); `company` matches the manufacturer. Active licences
    only unless active_only is false (74,000 licences since 1999). Counts by
    class come with every result. Pass a licence number to
    hc_device_get_licence for its devices and model numbers.
    Keywords: medical device licence, MDALL, device class, Class II III IV,
    licensed medical devices, manufacturer, diagnostic test kit, implant,
    Health Canada device approval.
    Mots-clés : homologation des instruments médicaux, LIMH, instruments
    médicaux homologués, classe d'instrument, fabricant, trousse de
    diagnostic, implant, homologation de Santé Canada.
    """
    return await api.in_lang(
        lang,
        client.search_licences(
            name,
            company=company,
            active_only=active_only,
            risk_class=risk_class,
            limit=limit,
            lang=lang,
        ),
    )


@tool
async def hc_device_get_licence(licence_number: int, lang: Lang = "en") -> DeviceLicenceDetail:
    """One medical device licence with its devices and model numbers.

    Use for: what a medical device licence covers: every device (trade
    name) on it with the date it was added or removed, their model or
    catalogue numbers (for licences with up to 25 devices), the licence
    status, class and type, and the manufacturer's name and address.
    Keywords: device licence number, MDALL licence, licensed devices list,
    model number, catalogue number, manufacturer address, device trade
    name, licence status.
    Mots-clés : numéro d'homologation, homologation d'instrument médical,
    liste des instruments, numéro de modèle, numéro de catalogue, adresse du
    fabricant, nom commercial, statut de l'homologation, Santé Canada.
    """
    return await api.in_lang(lang, client.get_licence(licence_number, lang=lang))


@tool
async def hc_device_search_devices(
    name: str = "",
    identifier: str = "",
    active_only: bool = True,
    limit: int = 50,
    lang: Lang = "en",
) -> DeviceList:
    """Search licensed medical devices by trade name or model number (MDALL).

    Use for: finding a specific medical device by the name on the product
    (e.g. 'Dexcom G7', 'hip stem') or by a model, catalogue or part number
    on its label, with the licence number it is sold under and the dates
    it was added to or removed from that licence. Give `name` or
    `identifier`, not both. Active devices only unless active_only is false.
    Keywords: medical device search, trade name, model number, catalogue
    number, device identifier, device licence, MDALL device, labelled
    product.
    Mots-clés : recherche d'instrument médical, nom commercial, numéro de
    modèle, numéro de catalogue, identifiant d'instrument, homologation,
    produit étiqueté, appareil médical, Santé Canada.
    """
    return await api.in_lang(
        lang,
        client.search_devices(
            name, identifier=identifier, active_only=active_only, limit=limit, lang=lang
        ),
    )
