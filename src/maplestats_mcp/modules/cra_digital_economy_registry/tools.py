from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.cra_digital_economy_registry import client
from maplestats_mcp.modules.cra_digital_economy_registry.schemas import (
    DigitalEconomyRegistryResult,
)


@tool
async def cra_digital_economy_registry_search(
    query: str = "", lang: Literal["en", "fr"] = "en"
) -> DigitalEconomyRegistryResult:
    """Search CRA's public registry of digital economy businesses registered
    for the simplified GST/HST (cross-border digital products/services and
    platform-based short-term accommodation), by legal name, trade name, or
    business number. Leave query empty to see the full registry size.

    Use for: confirming whether a foreign digital-economy business (an app
    store, streaming service, short-term rental platform) is registered to
    charge GST/HST under the simplified regime; looking up a business's
    registration or de-registration date by name or business number.
    Keywords: CRA, GST, HST, digital economy, simplified GST/HST,
    registrant, registry, cross-border, platform, short-term
    accommodation, business number, tax registration.
    Mots-clés : ARC, TPS, TVH, économie numérique, TPS/TVH simplifiée,
    inscrit, registre, transfrontalier, plateforme, hébergement de
    courte durée, numéro d'entreprise, inscription fiscale.
    """
    return await client.search_registrants(query, lang=lang)
