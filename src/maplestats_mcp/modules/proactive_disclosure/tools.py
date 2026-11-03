"""MCP tools for the federal proactive disclosure tables (open.canada.ca DataStore)."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.proactive_disclosure import client, constants
from maplestats_mcp.modules.proactive_disclosure.schemas import (
    AgreementTypeArg,
    ContractSearchResult,
    DatasetList,
    DatasetName,
    DisclosureGroupArg,
    DisclosureSummary,
    GrantSearchResult,
    GroupBy,
    HospitalitySearchResult,
    InstrumentTypeArg,
    SortOrder,
    TravelSearchResult,
    ValueMode,
)

Lang = Literal["en", "fr"]


@tool
async def disclosure_search_contracts(
    vendor: str | None = None,
    department: str | None = None,
    owner_org: str | None = None,
    description: str | None = None,
    fiscal_year: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    min_value: float | None = None,
    max_value: float | None = None,
    instrument_type: InstrumentTypeArg | None = None,
    ministers_office: bool | None = None,
    sort: SortOrder = "date_desc",
    limit: int = constants.SEARCH_LIMIT_DEFAULT,
    offset: int = 0,
    lang: Lang = "en",
) -> ContractSearchResult:
    """Search federal contracts over $10,000 (proactive disclosure) by vendor, department, date, value.

    Use for: who a federal department contracted with and for how much: a
    vendor's contracts across government (vendor, words of its name), one
    department's contracts (department, words of its name, or owner_org
    code such as 'dnd-mdn', 'pwgsc-tpsgc'), a fiscal_year ('2024-2025',
    grouped by the quarter each row was published), a contract_date range
    (date_from and date_to, YYYY-MM-DD, both), a contract value range
    (min_value, max_value in CAD), words of the description of work,
    contracts for ministers' offices, amendments only or standing offers.
    Each amendment is its own row and its contract_value is the amended
    total including taxes, so do not add rows up: use disclosure_summarize.
    sort by date (default, newest first) or value; limit up to 100, page
    with offset. Every record carries its dataset and resource ids and the
    Open Government Portal page to cite.
    Keywords: federal contracts, government procurement, contracts over
    $10,000, proactive disclosure, vendor, supplier, contract value,
    amendment, sole source, non-competitive, standing offer, consulting
    contracts, department spending.
    Mots-clés : contrats fédéraux, marchés publics, approvisionnement,
    divulgation proactive, contrats de plus de 10 000 $, fournisseur,
    valeur du contrat, modification de contrat, fournisseur unique, non
    concurrentiel, offre à commandes, dépenses ministérielles.
    """
    return await client.search_contracts(
        vendor=vendor,
        department=department,
        owner_org=owner_org,
        description=description,
        fiscal_year=fiscal_year,
        date_from=date_from,
        date_to=date_to,
        min_value=min_value,
        max_value=max_value,
        instrument_type=instrument_type,
        ministers_office=ministers_office,
        sort=sort,
        limit=limit,
        offset=offset,
        lang=lang,
    )


@tool
async def disclosure_search_grants(
    recipient: str | None = None,
    department: str | None = None,
    owner_org: str | None = None,
    program: str | None = None,
    description: str | None = None,
    province: str | None = None,
    riding: str | None = None,
    agreement_type: AgreementTypeArg | None = None,
    fiscal_year: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    min_value: float | None = None,
    max_value: float | None = None,
    sort: SortOrder = "date_desc",
    limit: int = constants.SEARCH_LIMIT_DEFAULT,
    offset: int = 0,
    lang: Lang = "en",
) -> GrantSearchResult:
    """Search federal grants and contributions (proactive disclosure) by recipient, program, riding.

    Use for: which organizations or people received federal grants or
    contributions and how much: a recipient (words of its legal name), a
    funding department (department or owner_org code), a program (words of
    its name), the recipient's province (two-letter code), a federal riding
    (name words or number), grant, contribution or other transfer, an
    agreement start date range (date_from and date_to, YYYY-MM-DD, or
    fiscal_year '2024-2025'), and an agreement value range in CAD. Each
    amendment is a new row with the same ref_number restating the whole
    agreement_value, so use disclosure_summarize for totals. sort by date or
    value; limit up to 100, page with offset. Every record carries its
    dataset and resource ids and the Open Government Portal page to cite.
    Keywords: grants and contributions, federal funding, transfer payments,
    proactive disclosure, recipient, funding program, riding, constituency,
    contribution agreement, subsidy, nonprofit funding, business support.
    Mots-clés : subventions et contributions, financement fédéral, paiements
    de transfert, divulgation proactive, bénéficiaire, programme de
    financement, circonscription, entente de contribution, aide financière,
    organismes sans but lucratif, soutien aux entreprises.
    """
    return await client.search_grants(
        recipient=recipient,
        department=department,
        owner_org=owner_org,
        program=program,
        description=description,
        province=province,
        riding=riding,
        agreement_type=agreement_type,
        fiscal_year=fiscal_year,
        date_from=date_from,
        date_to=date_to,
        min_value=min_value,
        max_value=max_value,
        sort=sort,
        limit=limit,
        offset=offset,
        lang=lang,
    )


@tool
async def disclosure_search_travel(
    name: str | None = None,
    title: str | None = None,
    department: str | None = None,
    owner_org: str | None = None,
    disclosure_group: DisclosureGroupArg | None = None,
    purpose: str | None = None,
    destination: str | None = None,
    fiscal_year: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    min_value: float | None = None,
    max_value: float | None = None,
    sort: SortOrder = "date_desc",
    limit: int = constants.SEARCH_LIMIT_DEFAULT,
    offset: int = 0,
    lang: Lang = "en",
) -> TravelSearchResult:
    """Search travel expenses of federal ministers and senior officials (proactive disclosure).

    Use for: a minister's, political staffer's or senior official's trips:
    who travelled (name, words in any order; names are often published
    'Last First'), their title or position (title words, e.g. 'Minister of
    National Defence', 'Deputy Minister'), the department, ministers and
    their exempt staff (disclosure_group='ministers') or senior officers
    and employees ('senior_officials'), the purpose or destination, a trip
    start date range (date_from and date_to, YYYY-MM-DD, or fiscal_year),
    and the trip's total cost in CAD (min_value, max_value). Each record
    breaks the total into airfare, other transport, lodging, meals and
    other expenses. Monthly disclosures; the newest months are incomplete.
    sort by date or value; limit up to 100, page with offset. Totals by
    person, title or department: disclosure_summarize(dataset='travel').
    Keywords: travel expenses, ministers travel, ministerial expenses,
    senior officials, deputy minister, proactive disclosure, airfare,
    hotel, per diem, trip cost, exempt staff, government travel.
    Mots-clés : frais de déplacement, dépenses de voyage, voyages des
    ministres, dépenses ministérielles, cadres supérieurs, sous-ministre,
    divulgation proactive, billets d'avion, hébergement, repas, personnel
    exonéré, déplacements gouvernementaux.
    """
    return await client.search_travel(
        name=name,
        title=title,
        department=department,
        owner_org=owner_org,
        disclosure_group=disclosure_group,
        purpose=purpose,
        destination=destination,
        fiscal_year=fiscal_year,
        date_from=date_from,
        date_to=date_to,
        min_value=min_value,
        max_value=max_value,
        sort=sort,
        limit=limit,
        offset=offset,
        lang=lang,
    )


@tool
async def disclosure_search_hospitality(
    name: str | None = None,
    title: str | None = None,
    department: str | None = None,
    owner_org: str | None = None,
    disclosure_group: DisclosureGroupArg | None = None,
    description: str | None = None,
    vendor: str | None = None,
    fiscal_year: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    min_value: float | None = None,
    max_value: float | None = None,
    sort: SortOrder = "date_desc",
    limit: int = constants.SEARCH_LIMIT_DEFAULT,
    offset: int = 0,
    lang: Lang = "en",
) -> HospitalitySearchResult:
    """Search hospitality expenses of federal ministers and senior officials (proactive disclosure).

    Use for: meals, receptions and events hosted by a minister, political
    staffer or senior official: who hosted (name words), their title, the
    department, ministers and their staff (disclosure_group='ministers') or
    senior officers ('senior_officials'), words of the event's purpose
    (description), the restaurant or vendor, an event date range (date_from
    and date_to, YYYY-MM-DD, or fiscal_year), and the total cost in CAD.
    Each record gives the location, vendors, number of officials and guests
    attending, and total cost. Quarterly disclosures. sort by date or value;
    limit up to 100, page with offset. Totals: disclosure_summarize(
    dataset='hospitality').
    Keywords: hospitality expenses, ministers hospitality, receptions,
    business meals, events, senior officials, proactive disclosure,
    entertainment costs, guests, catering, restaurant, deputy minister.
    Mots-clés : frais d'accueil, dépenses d'accueil, accueil des ministres,
    réceptions, repas d'affaires, événements, cadres supérieurs,
    divulgation proactive, invités, traiteur, restaurant, sous-ministre.
    """
    return await client.search_hospitality(
        name=name,
        title=title,
        department=department,
        owner_org=owner_org,
        disclosure_group=disclosure_group,
        description=description,
        vendor=vendor,
        fiscal_year=fiscal_year,
        date_from=date_from,
        date_to=date_to,
        min_value=min_value,
        max_value=max_value,
        sort=sort,
        limit=limit,
        offset=offset,
        lang=lang,
    )


@tool
async def disclosure_summarize(
    dataset: DatasetName,
    group_by: GroupBy = "department",
    department: str | None = None,
    owner_org: str | None = None,
    fiscal_year: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    party: str | None = None,
    title: str | None = None,
    program: str | None = None,
    province: str | None = None,
    disclosure_group: DisclosureGroupArg | None = None,
    min_value: float | None = None,
    max_value: float | None = None,
    value_mode: ValueMode = "latest_per_agreement",
    top: int = constants.SUMMARY_TOP_DEFAULT,
    lang: Lang = "en",
) -> DisclosureSummary:
    """Total federal contracts, grants, travel or hospitality spending (count, sum) grouped by a field.

    Use for: top departments by contract value in a fiscal year, top vendors
    of one department, a recipient's grants by program, grants and
    contributions by province or riding, a minister's travel cost by fiscal
    year, travel or hospitality totals by person, title or department.
    dataset: contracts, grants, travel or hospitality. group_by: department
    (all), fiscal_year (all; April to March), vendor, quarter,
    commodity_type, solicitation_procedure, instrument_type,
    country_of_vendor, economic_object_code (contracts); recipient,
    program, province, riding, recipient_type, agreement_type (grants);
    name, title, disclosure_group (travel, hospitality); vendor
    (hospitality). Filters as in the search tools: department words or
    owner_org code, fiscal_year or date_from and date_to, party (vendor,
    recipient or person's name words), title (travel, hospitality),
    program and province (grants), disclosure_group, min_value and
    max_value. The default value_mode counts each contract or grant once
    at its most recent amended value; 'all_rows' sums every row as
    published, which double-counts amendments. The portal
    has no SQL or aggregate API, so the matching rows (up to 100,000) are
    read and summed here; narrow by fiscal year or department when refused.
    Keywords: total contract value, spending by department, top vendors,
    procurement totals, grants by province, funding by riding, travel
    costs, hospitality costs, proactive disclosure, aggregate, sum, ranking.
    Mots-clés : valeur totale des contrats, dépenses par ministère,
    principaux fournisseurs, total des marchés, subventions par province,
    financement par circonscription, coûts de déplacement, frais d'accueil,
    divulgation proactive, somme, classement, agrégat.
    """
    return await client.summarize(
        dataset=dataset,
        group_by=group_by,
        department=department,
        owner_org=owner_org,
        fiscal_year=fiscal_year,
        date_from=date_from,
        date_to=date_to,
        party=party,
        title=title,
        program=program,
        province=province,
        disclosure_group=disclosure_group,
        min_value=min_value,
        max_value=max_value,
        value_mode=value_mode,
        top=top,
        lang=lang,
    )


@tool
async def disclosure_list_datasets(lang: Lang = "en") -> DatasetList:
    """List the federal proactive disclosure tables: ids, row counts, last update, fields, licence.

    Use for: citing the contracts over $10,000, grants and contributions,
    travel expenses and hospitality expenses tables (dataset id, DataStore
    resource id, open.canada.ca page, the government's own search page),
    checking when each was last updated and how many rows it holds, and
    which value and date columns and group_by fields each one has for
    disclosure_summarize. Also flags a resource that has moved out of its
    package. lang picks English or French titles and links.
    Keywords: proactive disclosure, open.canada.ca, dataset id, resource id,
    contracts dataset, grants dataset, travel expenses dataset, hospitality
    dataset, Treasury Board, last updated, citation, Open Government Licence.
    Mots-clés : divulgation proactive, ouvert.canada.ca, identifiant du jeu
    de données, ressource, contrats, subventions et contributions, frais de
    déplacement, frais d'accueil, Conseil du Trésor, mise à jour, citation,
    licence du gouvernement ouvert.
    """
    return await client.list_datasets(lang)
