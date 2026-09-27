"""MCP tools for Canadian Food Inspection Agency (CFIA) animal disease tables."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.cfia import client, constants
from maplestats_mcp.modules.cfia.schemas import (
    AvianInfluenzaResult,
    DiseaseDetectionResult,
    ReportableDiseaseResult,
)

Lang = Literal["en", "fr"]


@tool
async def cfia_reportable_diseases(
    year_from: int | None = None,
    year_to: int | None = None,
    disease: str | None = None,
    totals_by: Literal["year", "disease"] | None = None,
    lang: Lang = "en",
) -> ReportableDiseaseResult:
    """Get yearly counts of federally reportable terrestrial animal diseases in Canada (CFIA).

    Use for: how many farmed herds or flocks were confirmed with a
    federally reportable disease each year from 2011 to the current year
    (avian influenza, chronic wasting disease, equine infectious anemia,
    bovine tuberculosis, scrapie, cysticercosis, BSE, Newcastle disease,
    anthrax, anaplasmosis, trichinellosis), as published by the CFIA and
    updated on the 10th of each month (`current_as_of` gives the month
    end the counts run to). `disease` accepts a name in either language
    or an abbreviation ("CWD", "maladie débilitante chronique", "BSE",
    "tremblante"), ignoring case, accents and apostrophes; `totals_by`
    adds sums by year or by disease. Each row names the tool with one row
    per detection (cfia_disease_detections, cfia_avian_influenza). Rabies
    and aquatic diseases are CKAN datasets (organization cfia-acia).
    `lang="fr"` reads the French page (French disease names and notes).
    Keywords: reportable disease, animal disease, CFIA, chronic wasting
    disease, avian influenza, equine infectious anemia, bovine
    tuberculosis, scrapie, BSE, livestock health, herds infected.
    Mots-clés : maladie à déclaration obligatoire, maladies animales,
    ACIA, maladie débilitante chronique, influenza aviaire, anémie
    infectieuse des équidés, tuberculose bovine, tremblante, ESB, santé
    animale, troupeaux infectés.
    """
    return await client.get_reportable_diseases(year_from, year_to, disease, totals_by, lang)


@tool
async def cfia_disease_detections(
    disease: str | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
    province: str | None = None,
    animal_type: str | None = None,
    counts_by: Literal["year", "month", "province", "animal_type"] | None = None,
    lang: Lang = "en",
) -> DiseaseDetectionResult:
    """List each confirmed CFIA detection of a reportable animal disease: date, province, species.

    Use for: when and where chronic wasting disease was confirmed in farmed
    deer and elk (monthly, 2011 to now), scrapie in sheep and goat flocks,
    bovine tuberculosis and cysticercosis in cattle herds, BSE cases (with
    the animal's age), trichinellosis, and avian influenza in poultry
    before 2021. `disease` takes a name or abbreviation in English or
    French (default: all seven); filter by year, `province` (code or
    name) or `animal_type` ("elk", "wapiti", "goat"); `counts_by` groups
    rows by year, YYYY-MM month, province or animal type. `herds` counts
    the herds a row stands for ("Elk (3 herds)"), matching the yearly
    totals of cfia_reportable_diseases. For avian influenza since
    December 2021 use cfia_avian_influenza. `lang="fr"` gives French
    locations, animal types and notes; dates follow the English pages.
    Keywords: chronic wasting disease, CWD, scrapie, bovine tuberculosis,
    BSE, mad cow, cysticercosis, detections, herds infected, deer, elk,
    CFIA.
    Mots-clés : maladie débilitante chronique, MDC, tremblante,
    tuberculose bovine, ESB, vache folle, cysticercose, détections,
    troupeaux infectés, cerf, wapiti, ACIA.
    """
    return await client.get_disease_detections(
        disease, year_from, year_to, province, animal_type, counts_by, lang
    )


@tool
async def cfia_avian_influenza(
    status: Literal["current", "released", "all"] = "all",
    province: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    premises_type: Literal["commercial", "non_commercial", "captive_wild"] | None = None,
    counts_by: Literal["province", "month", "year", "premises_type"] = "province",
    limit: int = constants.HPAI_DEFAULT_LIMIT,
    lang: Lang = "en",
) -> AvianInfluenzaResult:
    """Get highly pathogenic avian influenza (HPAI, bird flu) infected premises in Canada from CFIA.

    Use for: every poultry and bird premises the CFIA has confirmed with
    avian influenza since December 2021 (about 660): premises id, date
    detected, province, municipality, commercial or non-commercial, WOAH
    poultry or non-poultry, primary control zone and its order, and
    whether it is still under CFIA quarantine (`status="current"`) or
    released. Filter by `province` (code or name), `date_from`/`date_to`
    (YYYY, YYYY-MM or YYYY-MM-DD) and `premises_type`; `counts` gives
    current and released premises by province, month, year or premises
    type. The result also carries the CFIA's status-by-province table
    with the estimated birds impacted. Newest first, up to `limit`
    (max 1000). `lang="fr"` gives French municipalities, zones (ZCP) and
    labels; dates follow the English page.
    Keywords: avian influenza, bird flu, HPAI, H5N1, infected premises,
    poultry outbreak, CFIA, quarantine, control zone, birds impacted,
    flocks.
    Mots-clés : influenza aviaire, grippe aviaire, IAHP, H5N1, lieux
    infectés, éclosion, volailles, ACIA, quarantaine, zone de contrôle
    primaire, oiseaux touchés.
    """
    return await client.get_avian_influenza(
        status, province, date_from, date_to, premises_type, counts_by, limit, lang
    )
