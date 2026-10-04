"""MCP tools for ISED's Spectrum Management System licence site data."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.ised.spectrum import client
from maplestats_mcp.modules.ised.spectrum.constants import ROWS_LIMIT_DEFAULT
from maplestats_mcp.modules.ised.spectrum.schemas import LicenceQueryResult

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
    records. Filter with an ArcGIS SQL `where` clause on fields such as
    LICENSEE, SERVICE, PROV (two-letter code), TRANSMIT_FREQ and
    RECEIVE_FREQ (MHz), LATITUDE, LONGITUDE, STUCT_HT (structure/tower
    height), TX_PWR (transmit power), e.g. "PROV='AB' AND SERVICE='CELL'".
    SERVICE holds a band code, not a name (a LIKE '%Cellular%' finds
    nothing); the 18 codes (checked live 2026-10-03): 3500B (3500 MHz
    flexible use), 600B (600 MHz), AWS (AWS-1, 1.7/2.1 GHz), AWS-3,
    AWS-4, BRS (Broadband Radio Service, 2500 MHz), BWA24 and BWA38
    (broadband wireless access, 24 and 38 GHz), CELL (cellular, 800 MHz),
    FCFS38 (38 GHz first-come first-served), FWA (fixed wireless access,
    3500 MHz), MBS (Mobile Broadband Service, 700 MHz), PCS (1900 MHz),
    PCSG (PCS G block), PS49 (public safety, 4.9 GHz), RAC (railway radio
    of the Railway Association of Canada, VHF/UHF), WBS (Wireless
    Broadband Service, 3650-3700 MHz), WCS (Wireless Communications
    Service, 2300 MHz). LAST_MOD_DATE and LAST_UPLOAD_DATE come back as
    ISO dates. The service says it is refreshed monthly, but the hosted
    copy was last edited 2024-02-08; provenance.as_of gives the date.
    Keywords: ISED, ISDE, spectrum,
    radio licence, wireless, telecommunications, frequency, licensee,
    transmitter, antenna, tower, Spectrum Management System, SMS.
    Mots-clés : ISDE, spectre, licence radio, sans fil,
    télécommunications, fréquence, titulaire de licence, émetteur,
    antenne, tour, Système de gestion du spectre, SGS.
    """
    return await client.query_licences(
        where=where, out_fields=out_fields, order_by=order_by, limit=limit, offset=offset, lang=lang
    )
