"""House of Commons open data: members, roles, party standings and the Ministry."""

from __future__ import annotations

import unicodedata
from datetime import datetime
from typing import Literal
from xml.etree.ElementTree import Element

import httpx
from defusedxml import ElementTree

from maplestats_mcp.modules.ourcommons import constants
from maplestats_mcp.modules.ourcommons.schemas import (
    AssociationRole,
    CaucusRole,
    CommitteeRole,
    ElectionRun,
    Member,
    MemberList,
    MemberRoles,
    Minister,
    Ministry,
    PartyStanding,
    PartyStandings,
    PartyTotal,
    PositionRole,
    SeatRole,
)
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable
from maplestats_mcp.shared.fr_typography import fr_or_en, lang_error
from maplestats_mcp.shared.http import get_raw
from maplestats_mcp.shared.rate_limiter import get_limiter

Lang = Literal["en", "fr"]
Node = Element

_LIMITER = get_limiter(
    constants.RATE_LIMIT_SOURCE,
    rate=constants.RATE_LIMIT_PER_SECOND,
    capacity=constants.RATE_LIMIT_CAPACITY,
)


def _fold(text: str) -> str:
    stripped = unicodedata.normalize("NFKD", text)
    return "".join(c for c in stripped if not unicodedata.combining(c)).casefold().strip()


Groups = tuple[tuple[tuple[str, ...], tuple[str, ...]], ...]


def _needles(wanted: str, groups: Groups) -> tuple[str, ...]:
    """The filter plus the en and fr feed values of every group it names.

    An exact alias (a code such as "ab") stands for its group alone; as a raw
    substring "ab" would also hit "Labrador".
    """
    key = _fold(wanted)
    for values, aliases in groups:
        if key in aliases:
            return tuple(_fold(v) for v in values)
    found = [key]
    for values, _aliases in groups:
        if any(key in _fold(v) for v in values):
            found.extend(_fold(v) for v in values)
    return tuple(dict.fromkeys(found))


def _text(node: Node | None, tag: str) -> str:
    child = None if node is None else node.find(tag)
    return (child.text or "").strip() if child is not None and child.text else ""


def _when(node: Node | None, tag: str) -> datetime | None:
    value = _text(node, tag)
    return datetime.fromisoformat(value) if value else None


def _int(node: Node | None, tag: str) -> int | None:
    value = _text(node, tag)
    return int(value) if value.isdigit() else None


def _check_lang(lang: str) -> None:
    if lang not in ("en", "fr"):
        raise InvalidInput("ourcommons: lang must be 'en' or 'fr'.")


async def _xml(
    url: str, context: str, ttl: int, lang: str = "en", context_fr: str = ""
) -> tuple[Node, bool]:
    async def fetch() -> Node:
        await _LIMITER.acquire()
        try:
            response = await get_raw(url, timeout=60.0)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status in (301, 302, 404):
                # An unknown person id answers 302 to an error page.
                raise lang_error(
                    NotFound,
                    lang,
                    f"ourcommons: {context} not found.",
                    f"ourcommons : {context_fr} introuvable.",
                ) from exc
            raise lang_error(
                UpstreamError,
                lang,
                f"ourcommons: {url} returned HTTP {status}.",
                f"ourcommons : {url} a renvoyé HTTP {status}.",
            ) from exc
        except httpx.HTTPError as exc:
            raise lang_error(
                UpstreamUnavailable,
                lang,
                f"ourcommons: {url} did not respond in time.",
                f"ourcommons : {url} n'a pas répondu à temps.",
            ) from exc
        try:
            return ElementTree.fromstring(response.content)
        except ElementTree.ParseError as exc:
            raise lang_error(
                NotFound,
                lang,
                f"ourcommons: {context} returned no XML.",
                f"ourcommons : {context_fr} : aucun XML renvoyé.",
            ) from exc

    return await cached_fetch(f"ourcommons:{url}", ttl, fetch)


def parse_members(root: Node) -> list[Member]:
    return [
        Member(
            person_id=int(_text(m, "PersonId")),
            honorific=_text(m, "PersonShortHonorific") or None,
            first_name=_text(m, "PersonOfficialFirstName"),
            last_name=_text(m, "PersonOfficialLastName"),
            constituency=_text(m, "ConstituencyName"),
            province=_text(m, "ConstituencyProvinceTerritoryName"),
            party=_text(m, "CaucusShortName"),
            elected=_when(m, "FromDateTime"),
        )
        for m in root.findall("MemberOfParliament")
    ]


async def list_members(
    province: str | None = None,
    party: str | None = None,
    constituency: str | None = None,
    name: str | None = None,
    limit: int = constants.MEMBERS_LIMIT_DEFAULT,
    lang: Lang = "en",
) -> MemberList:
    _check_lang(lang)
    if not 1 <= limit <= constants.MEMBERS_LIMIT_MAX:
        raise lang_error(
            InvalidInput,
            lang,
            f"ourcommons: limit must be 1 to {constants.MEMBERS_LIMIT_MAX}.",
            f"ourcommons : limit doit être compris entre 1 et {constants.MEMBERS_LIMIT_MAX}.",
        )
    url = constants.MEMBERS_URL.format(lang=lang)
    root, cached = await _xml(
        url, "the member list", constants.CACHE_TTL_LIST_SECONDS, lang, "liste des députés"
    )
    members = parse_members(root)

    # Province and party accept either language whatever the feed's lang.
    checks = (
        (_needles(province, constants.PROVINCE_GROUPS) if province else (), "province"),
        (_needles(party, constants.PARTY_GROUPS) if party else (), "party"),
        ((_fold(constituency),) if constituency else (), "constituency"),
        ((_fold(name),) if name else (), "name"),
    )

    def keep(member: Member) -> bool:
        values = {
            "province": member.province,
            "party": member.party,
            "constituency": member.constituency,
            "name": f"{member.first_name} {member.last_name}",
        }
        return all(
            not needles or any(n in _fold(values[field]) for n in needles)
            for needles, field in checks
        )

    members = [m for m in members if keep(m)]
    return MemberList(
        members=members[:limit],
        total_members=len(members),
        truncated=len(members) > limit,
        provenance=make_provenance(
            source=constants.PROVENANCE_SOURCE,
            url=url,
            cached=cached,
            schema_name="ourcommons.MemberList",
            freshness=fr_or_en(
                lang,
                "Current members; the House of Commons updates the feed as seats change.",
                "Députés actuels ; la Chambre des communes met le fil à jour quand les sièges "
                "changent.",
            ),
            coverage=fr_or_en(
                lang,
                "Sitting members only (vacant seats are absent). Use "
                "ourcommons_get_member_roles for a former member's history.",
                "Députés en fonction seulement (les sièges vacants sont absents). Utilisez "
                "ourcommons_get_member_roles pour l'historique d'un ancien député.",
            ),
            limits=(
                fr_or_en(
                    lang,
                    f"Showing {limit} of {len(members)} members.",
                    f"{limit} députés affichés sur {len(members)}.",
                )
                if len(members) > limit
                else None
            ),
            lang=lang,
        ),
    )


def parse_roles(
    root: Node, person_id: int, source_url: str, cached: bool, lang: str = "en"
) -> MemberRoles:
    seats_root = root.find("MemberOfParliamentRoles")
    seat_nodes = [] if seats_root is None else seats_root.findall("MemberOfParliamentRole")
    if not seat_nodes:
        raise lang_error(
            NotFound,
            lang,
            f"ourcommons: no member with person id {person_id}.",
            f"ourcommons : aucun député avec l'identifiant de personne {person_id}.",
        )
    first = seat_nodes[0]

    def section(name: str, item: str) -> list[Node]:
        node = root.find(name)
        return [] if node is None else node.findall(item)

    return MemberRoles(
        person_id=person_id,
        honorific=_text(first, "PersonShortHonorific") or None,
        first_name=_text(first, "PersonOfficialFirstName"),
        last_name=_text(first, "PersonOfficialLastName"),
        seats=[
            SeatRole(
                constituency=_text(s, "ConstituencyName"),
                province=_text(s, "ConstituencyProvinceTerritoryName"),
                party=_text(s, "CaucusShortName"),
                start=_when(s, "FromDateTime"),
                end=_when(s, "ToDateTime"),
            )
            for s in seat_nodes
        ],
        caucus_roles=[
            CaucusRole(
                party=_text(c, "CaucusShortName"),
                parliament=_int(c, "ParliamentNumber"),
                start=_when(c, "FromDateTime"),
                end=_when(c, "ToDateTime"),
            )
            for c in section("CaucusMemberRoles", "CaucusMemberRole")
        ],
        parliamentary_positions=[
            PositionRole(
                title=_text(p, "Title"),
                start=_when(p, "FromDateTime"),
                end=_when(p, "ToDateTime"),
            )
            for p in section("ParliamentaryPositionRoles", "ParliamentaryPositionRole")
        ],
        committee_roles=[
            CommitteeRole(
                committee=_text(c, "CommitteeName"),
                role=_text(c, "AffiliationRoleName"),
                parliament=_int(c, "ParliamentNumber"),
                session=_int(c, "SessionNumber"),
                start=_when(c, "FromDateTime"),
                end=_when(c, "ToDateTime"),
            )
            for c in section("CommitteeMemberRoles", "CommitteeMemberRole")
        ],
        associations=[
            AssociationRole(
                organization=_text(a, "Organization"),
                role=_text(a, "AssociationMemberRoleType"),
                title=_text(a, "Title") or None,
            )
            for a in section(
                "ParliamentaryAssociationsandInterparliamentaryGroupRoles",
                "ParliamentaryAssociationsandInterparliamentaryGroupRole",
            )
        ],
        election_history=[
            ElectionRun(
                election_type=_text(e, "ElectionEventTypeName"),
                election_date=_when(e, "ElectionEndDate"),
                constituency=_text(e, "ConstituencyName"),
                province=_text(e, "ConstituencyProvinceTerritoryName"),
                party=_text(e, "PoliticalPartyName"),
                result=_text(e, "ResolvedElectionResultTypeName"),
            )
            for e in section("ElectionCandidateRoles", "ElectionCandidateRole")
        ],
        provenance=make_provenance(
            source=constants.PROVENANCE_SOURCE,
            url=source_url,
            cached=cached,
            schema_name="ourcommons.MemberRoles",
            coverage=fr_or_en(
                lang,
                "All roles, current and past, that the House of Commons records for "
                "this person; the feed's history starts in the 1990s for former members.",
                "Tous les rôles, actuels et passés, que la Chambre des communes consigne pour "
                "cette personne ; l'historique du fil commence dans les années 1990 pour les "
                "anciens députés.",
            ),
            lang=lang,
        ),
    )


async def get_member_roles(person_id: int, lang: Lang = "en") -> MemberRoles:
    _check_lang(lang)
    if person_id < 1:
        raise lang_error(
            InvalidInput,
            lang,
            "ourcommons: person_id must be a positive integer.",
            "ourcommons : person_id doit être un entier positif.",
        )
    url = constants.ROLES_URL.format(lang=lang, person_id=person_id)
    root, cached = await _xml(
        url,
        f"person id {person_id}",
        constants.CACHE_TTL_ROLES_SECONDS,
        lang,
        f"identifiant de personne {person_id}",
    )
    return parse_roles(root, person_id, url, cached, lang)


async def get_party_standings(lang: Lang = "en") -> PartyStandings:
    _check_lang(lang)
    url = constants.STANDINGS_URL.format(lang=lang)
    root, cached = await _xml(
        url, "party standings", constants.CACHE_TTL_LIST_SECONDS, lang, "répartition des sièges"
    )
    rows = [
        PartyStanding(
            province=_text(s, "ProvinceTerritoryName"),
            party=_text(s, "CaucusShortName"),
            seats=_int(s, "SeatCount") or 0,
        )
        for s in root.findall("PartyStanding")
    ]
    totals: dict[str, int] = {}
    for row in rows:
        totals[row.party] = totals.get(row.party, 0) + row.seats
    return PartyStandings(
        total_seats=sum(totals.values()),
        by_party=[
            PartyTotal(party=party, seats=seats)
            for party, seats in sorted(totals.items(), key=lambda kv: -kv[1])
        ],
        by_province=rows,
        provenance=make_provenance(
            source=constants.PROVENANCE_SOURCE,
            url=url,
            cached=cached,
            schema_name="ourcommons.PartyStandings",
            freshness=fr_or_en(
                lang,
                "Current standings of sitting members.",
                "Répartition actuelle des députés en fonction.",
            ),
            lang=lang,
        ),
    )


async def get_ministry(lang: Lang = "en") -> Ministry:
    _check_lang(lang)
    url = constants.MINISTRY_URL.format(lang=lang)
    root, cached = await _xml(
        url, "the Ministry", constants.CACHE_TTL_LIST_SECONDS, lang, "le Conseil des ministres"
    )
    return Ministry(
        ministers=[
            Minister(
                person_id=int(_text(m, "PersonId")),
                order_of_precedence=_int(m, "OrderOfPrecedence") or 0,
                honorific=_text(m, "PersonShortHonorific") or None,
                first_name=_text(m, "PersonOfficialFirstName"),
                last_name=_text(m, "PersonOfficialLastName"),
                title=_text(m, "Title"),
                province=_text(m, "ProvinceTerritoryName"),
                start=_when(m, "FromDateTime"),
                end=_when(m, "ToDateTime"),
            )
            for m in root.findall("Minister")
        ],
        provenance=make_provenance(
            source=constants.PROVENANCE_SOURCE,
            url=url,
            cached=cached,
            schema_name="ourcommons.Ministry",
            freshness=fr_or_en(
                lang,
                "The current Ministry (Cabinet), in order of precedence.",
                "Le Conseil des ministres actuel, par ordre de préséance.",
            ),
            lang=lang,
        ),
    )
