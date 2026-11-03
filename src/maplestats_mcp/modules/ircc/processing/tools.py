"""MCP tools for IRCC's application processing times."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.ircc.processing import client
from maplestats_mcp.modules.ircc.processing.schemas import (
    ApplicationTypeList,
    ProcessingTimeResult,
)

Lang = Literal["en", "fr"]


@tool
async def ircc_processing_list_application_types(
    category: str | None = None, lang: Lang = "en"
) -> ApplicationTypeList:
    """List the IRCC application types that have a published processing time.

    Use for: finding the type_id to pass to ircc_processing_get_time (visitor
    visas, study and work permits from inside or outside Canada, Express Entry
    and other permanent residence programs, family sponsorship, refugees,
    citizenship, PR cards), which types vary by country of residence, and
    when IRCC last updated each. `category` is one of visit, study, work,
    family, economic, refugees, citizenship, documents, other. These are
    point-in-time estimates IRCC replaces weekly or monthly, not a series.
    Keywords: IRCC processing times, application types, immigration
    application, wait time, visa, permit, permanent residence, citizenship,
    how long, backlog.
    Mots-clés : délais de traitement IRCC, types de demande, demande
    d'immigration, temps d'attente, visa, permis, résidence permanente,
    citoyenneté, combien de temps, arriéré.
    """
    return await client.list_application_types(category, lang)


@tool
async def ircc_processing_get_time(
    application_type: str, country: str | None = None, lang: Lang = "en"
) -> ProcessingTimeResult:
    """Get IRCC's current processing time for one application type, by country where it varies.

    Use for: "how long does a work permit from inside Canada take" (type_id
    work_extension, and WP-EXT for IRCC's estimate for a new application),
    visitor visa or study permit times for applicants in a given country
    (`country` as an ISO code like IN, PH, NG or a name), Express Entry
    (cec, fsw, pnp-ee), spousal and parent sponsorship, citizenship
    (citizen-grants, citizen-proofs). `application_type` is a type_id from
    ircc_processing_list_application_types, or words from its label when
    they match one type. By-country types without `country` return every
    country, longest first. Each result gives IRCC's text, the amount and
    unit, people waiting for forward-looking types, and IRCC's
    "last updated" date: a point-in-time estimate, not a time series.
    Keywords: IRCC processing time, how long, wait time, work permit,
    study permit, visitor visa, Express Entry, spousal sponsorship,
    citizenship, PR card, immigration application.
    Mots-clés : délai de traitement IRCC, combien de temps, temps
    d'attente, permis de travail, permis d'études, visa de visiteur,
    Entrée express, parrainage du conjoint, citoyenneté, carte de RP,
    demande d'immigration.
    """
    return await client.get_processing_time(application_type, country, lang)
