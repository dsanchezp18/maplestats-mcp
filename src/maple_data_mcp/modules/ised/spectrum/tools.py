"""MCP tools for ISED's Spectrum Management System licence site data."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maple_data_mcp.modules.ised.spectrum import client
from maple_data_mcp.modules.ised.spectrum.constants import ROWS_LIMIT_DEFAULT
from maple_data_mcp.modules.ised.spectrum.schemas import LicenceQueryResult

Lang = Literal["en", "fr"]


@tool
async def ised_spectrum_query_licences(
    where: str | None = None,
    out_fields: str = "*",
    order_by: str | None = None,
    limit: int = ROWS_LIMIT_DEFAULT,
    offset: int = 0,
    lang: Lang = "en",
) -> LicenceQueryResult:
    """Query wireless spectrum licence site records from ISED's Spectrum Management System.

    Use for: finding radio/wireless spectrum licence sites by
    licensee, service type, location, or frequency, out of ~840,000
    records refreshed monthly. Filter with an ArcGIS SQL `where`
    clause on fields such as LICENSEE, SERVICE, PROV, TRANSMIT_FREQ,
    RECEIVE_FREQ, LATITUDE, LONGITUDE, STUCT_HT (structure/tower
    height), TX_PWR (transmit power). Keywords: ISED, ISDE, spectrum,
    radio licence, wireless, telecommunications, frequency, licensee,
    transmitter, antenna, tower, Spectrum Management System, SMS.
    Mots-clés : ISDE, spectre, licence radio, sans fil,
    télécommunications, fréquence, titulaire de licence, émetteur,
    antenne, tour, Système de gestion du spectre, SGS.
    """
    return await client.query_licences(
        where=where, out_fields=out_fields, order_by=order_by, limit=limit, offset=offset, lang=lang
    )
