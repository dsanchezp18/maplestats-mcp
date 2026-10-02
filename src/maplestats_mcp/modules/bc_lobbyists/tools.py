"""MCP tools for the BC Office of the Registrar of Lobbyists open data."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.bc_lobbyists import client, constants
from maplestats_mcp.modules.bc_lobbyists.schemas import (
    CodeKind,
    GroupBy,
    OrlActivityReportList,
    OrlActivitySummary,
    OrlCodeList,
    OrlRegistrationDetail,
    OrlRegistrationList,
    RegistrationKind,
    RegistrationStatus,
)

Lang = Literal["en", "fr"]


@tool
async def bc_lobbyists_search_registrations(
    query: str = "",
    client_name: str = "",
    lobbyist: str = "",
    firm: str = "",
    subject_matter: str = "",
    agency: str = "",
    kind: RegistrationKind | None = None,
    status: RegistrationStatus | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = constants.SEARCH_DEFAULT_LIMIT,
    lang: Lang = "en",
) -> OrlRegistrationList:
    """Search British Columbia lobbyist registrations (clients, consultants, topics).

    Use for: who is registered to lobby the BC government, for whom and on
    what: a company or association's registrations (client or organization),
    a consulting firm's clients, one lobbyist's registrations, lobbying
    topics and subject matters (forestry, health, energy, housing), the
    ministries to be contacted, and whether a registration is still active.
    Current version of each registration since 2010, under the Lobbyists
    Transparency Act (from 2020-05-04) or the earlier Act. Words in `query`
    must all appear in the client, firm, lobbyist names, topics or client
    description; `client_name`, `lobbyist`, `firm` (consulting firm or
    filer), `agency` (ministry) and `subject_matter` (a registry subject like
    'Forestry') narrow it; `date_from` and `date_to` (YYYY-MM-DD) keep
    registrations active at any time in that period. For who actually met
    whom use bc_lobbyists_search_activity_reports. Addresses, phone numbers,
    contribution flags and gifts are not included (ORL licence).
    Keywords: BC lobbyist registry, lobbyist registration, British Columbia
    lobbying, consultant lobbyist, in-house lobbyist, lobbying client,
    Registrar of Lobbyists, Lobbyists Transparency Act, lobbying topics,
    who lobbies.
    Mots-clés : registre des lobbyistes, inscription de lobbyiste,
    Colombie-Britannique, lobbying, lobbyiste-conseil, lobbyiste interne,
    client du lobbyiste, registraire des lobbyistes, loi sur la transparence
    du lobbying, sujets de lobbying, qui fait du lobbying.
    """
    return await client.search_registrations(
        query,
        client=client_name,
        lobbyist=lobbyist,
        firm=firm,
        subject_matter=subject_matter,
        agency=agency,
        kind=kind,
        status=status,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        lang=lang,
    )


@tool
async def bc_lobbyists_get_registration(
    registration: str, lang: Lang = "en"
) -> OrlRegistrationDetail:
    """Read one BC lobbyist registration in full: every lobbyist, topic and ministry.

    Use for: the complete record of a registration found with
    bc_lobbyists_search_registrations: all lobbyists named, every topic of
    lobbying in the filer's words with its subject matters and intended
    outcomes (legislation, regulation, program or policy, contract or grant),
    ministries and entities to be contacted, client description and website,
    start and end dates. `registration` is the record id ('R-56584653'), the
    registration number ('9997-443-56') or just 'filer-client' ('9997-443')
    for the current version of that pair. An older version's number or id
    resolves to the current one.
    Keywords: lobbyist registration detail, BC lobbying registration number,
    lobbying topics, intended outcomes, ministries contacted, registrar of
    lobbyists record, lobbyists named, registration return.
    Mots-clés : détail d'une inscription de lobbyiste, numéro d'inscription,
    Colombie-Britannique, sujets de lobbying, résultats visés, ministères
    visés, registraire des lobbyistes, lobbyistes nommés, déclaration
    d'inscription.
    """
    return await client.get_registration(registration, lang=lang)


@tool
async def bc_lobbyists_search_activity_reports(
    query: str = "",
    client_name: str = "",
    lobbyist: str = "",
    office_holder: str = "",
    agency: str = "",
    subject_matter: str = "",
    kind: RegistrationKind | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    arranged_only: bool | None = None,
    limit: int = constants.SEARCH_DEFAULT_LIMIT,
    lang: Lang = "en",
) -> OrlActivityReportList:
    """Search BC lobbying activity reports: who lobbied which public office holder.

    Use for: the monthly reports lobbyists file about communications with
    senior public office holders in British Columbia since 2020-05-04: the
    meeting date, the client, the lobbyists, each office holder reached (name,
    title, ministry or MLA), and the topic and subject matter. Find who
    lobbied a minister, deputy minister or ministry, what a client lobbied
    on, which meetings a lobbyist reported, and lobbying on a subject in a
    period. `query` words must all appear in the client, people, ministries
    or topics; `office_holder` matches a name or title ('Deputy Minister');
    `agency` a ministry ('Health', 'Office of the Premier', 'Legislative
    Assembly'); `date_from` and `date_to` (YYYY-MM-DD) bound the meeting date;
    `arranged_only` true keeps reports about arranging a meeting. Newest
    first. A report is a filing, not a meeting; use
    bc_lobbyists_summarize_activity for counts.
    Keywords: BC lobbying activity report, who met minister, lobbyist
    meetings, senior public office holder, deputy minister lobbying,
    ministry lobbied, lobbying communications, British Columbia lobbying
    disclosure, meeting date.
    Mots-clés : rapport d'activité de lobbying, qui a rencontré le ministre,
    rencontres de lobbyistes, titulaire de charge publique supérieure,
    sous-ministre, ministère visé, communications de lobbying,
    Colombie-Britannique, divulgation du lobbying, date de la rencontre.
    """
    return await client.search_activity_reports(
        query,
        client=client_name,
        lobbyist=lobbyist,
        office_holder=office_holder,
        agency=agency,
        subject_matter=subject_matter,
        kind=kind,
        date_from=date_from,
        date_to=date_to,
        arranged_only=arranged_only,
        limit=limit,
        lang=lang,
    )


@tool
async def bc_lobbyists_summarize_activity(
    group_by: GroupBy,
    query: str = "",
    client_name: str = "",
    lobbyist: str = "",
    office_holder: str = "",
    agency: str = "",
    subject_matter: str = "",
    kind: RegistrationKind | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    arranged_only: bool | None = None,
    top: int = constants.SUMMARY_DEFAULT_TOP,
    lang: Lang = "en",
) -> OrlActivitySummary:
    """Count BC lobbying activity reports by client, ministry, office holder, subject or month.

    Use for: rankings and trends in BC lobbying since 2020-05-04: the clients
    reporting the most lobbying, the ministries or office holders lobbied
    most, the busiest subjects (health, forestry, energy, housing), the most
    active lobbyists, and monthly or yearly volume. `group_by` is client,
    ministry, office_holder, subject_matter, lobbyist, month or year; the
    filters are those of bc_lobbyists_search_activity_reports (all optional),
    so 'reports per ministry for one client in 2025' is one call. Counts are
    distinct reports, not meetings; rows for a report with several ministries
    or subjects add up to more than the total. Month and year rows run oldest
    to newest.
    Keywords: BC lobbying statistics, most lobbied ministry, top lobbying
    clients, lobbying by subject, lobbying trend by month, lobbying volume,
    count of lobbying reports, who lobbies most, lobbying ranking.
    Mots-clés : statistiques sur le lobbying, ministère le plus visé, clients
    les plus actifs, lobbying par sujet, tendance mensuelle, volume de
    lobbying, nombre de rapports de lobbying, Colombie-Britannique,
    classement du lobbying.
    """
    return await client.summarize_activity(
        group_by,
        query=query,
        client=client_name,
        lobbyist=lobbyist,
        office_holder=office_holder,
        agency=agency,
        subject_matter=subject_matter,
        kind=kind,
        date_from=date_from,
        date_to=date_to,
        arranged_only=arranged_only,
        top=top,
        lang=lang,
    )


@tool
async def bc_lobbyists_list_codes(
    kind: CodeKind, query: str = "", lang: Lang = "en"
) -> OrlCodeList:
    """List the BC lobbyists registry's subject matters, intended outcomes or ministries.

    Use for: the exact words the registry uses before filtering:
    `subject_matters` (Forestry, Health, Energy, Housing, COVID-19 and about
    50 more, for the `subject_matter` filter), `intended_outcomes` (the seven
    BC-xx outcomes of the 2020 Act and the six legacy IO-xx ones: legislation,
    regulation, program or policy, contract or grant, privatization, arranging
    a meeting) or `ministries` (every ministry, agency or 'Member(s) of the BC
    Legislative Assembly' named in activity reports, with the number of
    reports naming it, for the `agency` filter). `query` keeps names holding
    every word.
    Keywords: BC lobbying subject matters, lobbying intended outcomes,
    ministries lobbied, registry codes, lobbying topics list, provincial
    entities, Lobbyists Transparency Act outcomes, code list.
    Mots-clés : sujets de lobbying, résultats visés, ministères visés,
    codes du registre, liste des sujets, organismes provinciaux, loi sur la
    transparence du lobbying, Colombie-Britannique, liste de codes.
    """
    return await client.list_codes(kind, query=query, lang=lang)
