"""Client for the BC Registrar of Lobbyists mass datasets.

Checked live 2026-10-02 (the open data page links both zips; the licence PDF and the two XLSX data dictionaries
were read):

1. `mssDtstRprt?file=ORL_Registration_Data.zip` is 28 MB (260 MB unpacked) of
   16 CSVs and `ORL_LAR_Data.zip` is 5.5 MB (39 MB unpacked) of 5 CSVs. Both
   answer 200 `application/octet-stream` with a session cookie that is not
   needed. Files are UTF-8 with a byte order mark; an absent value is the
   text `null` (and, in LAR_SPOH BRANCH, sometimes an empty string).
2. Registrations are versioned: every REG_ID is one version, and
   PREVIOUS_VERSION_REG_ID names the version it replaced. 26,925 versions
   hold 6,661 registrations: 1,265 active (no REG_END_DATE) and 5,396 ended.
   A superseded version always has an end date, and a version appears in no
   other registration's chain, so "not named by anyone's
   PREVIOUS_VERSION_REG_ID" is the current version. The third number of
   REG_NUM is the version count; the earliest REG_START_DATE in a chain is
   when the registration began.
3. Lobbyists sit in two files (Registration_ConsultantLobbyists for
   REG_TYPE Cons, Registration_InHouseLobbyists for Org) with one row per
   lobbyist per version. SubjectMatterDetails repeats a topic once per
   SUBJECT_MATTER_DETAIL_ID (the same text twice or more under one REG_ID),
   so topics are de-duplicated on text and codes. Ministries come from
   Registration_BCPublicAgency as a comma-separated list of GI-ids that
   BC_Public_Agencies_Export.csv names (409 entries).
4. Activity reports (LAR) start 2020-05-04. LAR_Primary has one row per
   in-house lobbyist for the same LAR_ID (75,083 rows, 49,586 reports);
   the original of an amended LAR (PREVIOUS_VERSION_LAR_ID) is no longer in
   the data, so there is nothing to de-duplicate. REG_TYPE holds Cons or Org
   although the dictionary says 1 or 3. LAR_SPOH holds one row per senior
   public office holder (110,334 rows); "Member(s) of the BC Legislative
   Assembly" is an agency, with the member named.
5. Subject_Matters_Export.csv and Intended_Outcomes_Export.csv are the same
   in both zips. Intended outcomes carry BC-01 to BC-07 (2020 Act) and
   IO-01 to IO-06 (legacy).

What is left out, and why: the ORL Open Data Licence (term 6a) grants no
right to Personal Information, which is FOIPPA Schedule 1's "recorded
information about an identifiable individual other than contact
information". Contact information (name, title, business address,
business telephone of a person in a business capacity) is not Personal
Information, so lobbyist, filer and office-holder names with titles and
organizations are kept. Everything else about an individual is dropped:
street addresses (consultants often file from home: FILER_ADDRESS,
FIRM_ADDRESS, CLIENT_ORG_ADDRESS), telephone numbers, political,
sponsorship and recall contribution flags, the gifts file (office holders
named with values), Registration_PublicOffice (a lobbyist's earlier
career), POH and exemption fields, codes of conduct, beneficiaries
(affiliate and coalition members with addresses, which may be people) and
the legacy Target_Contacts and Target_Agencies files (94 MB and 50 MB). The
module never reads those members from the zip.
"""

from __future__ import annotations

import csv
import io
import re
import unicodedata
import zipfile
from collections import Counter
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import NamedTuple

import httpx

from maplestats_mcp.modules.bc_lobbyists import constants
from maplestats_mcp.modules.bc_lobbyists.schemas import (
    CodeKind,
    GroupBy,
    OrlActivityReport,
    OrlActivityReportList,
    OrlActivitySummary,
    OrlCode,
    OrlCodeList,
    OrlGroupRow,
    OrlOfficeHolder,
    OrlRegistration,
    OrlRegistrationDetail,
    OrlRegistrationList,
    OrlTopic,
)
from maplestats_mcp.shared.arg_checks import check_range
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable
from maplestats_mcp.shared.executor import run_parse
from maplestats_mcp.shared.http import get_raw
from maplestats_mcp.shared.limits import fit_to_budget, truncation_note
from maplestats_mcp.shared.models import Provenance
from maplestats_mcp.shared.rate_limiter import get_limiter

_LIMITER = get_limiter(
    constants.RATE_LIMIT_SOURCE,
    rate=constants.RATE_LIMIT_PER_SECOND,
    capacity=constants.RATE_LIMIT_CAPACITY,
)
_NUMBER = re.compile(r"^(\d+)-(\d+)(?:-(\d+))?$")


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return " ".join("".join(c for c in decomposed if not unicodedata.combining(c)).split())


def _pick(lang: str, en: str, fr: str) -> str:
    return fr if lang == "fr" else en


def _label(code: str, lang: str) -> str:
    en, fr = constants.LABELS[code]
    return _pick(lang, en, fr)


# ---------------------------------------------------------------- parsing


def _clean(value: str | None) -> str | None:
    """The files write a missing value as the text 'null' (or leave it empty)."""
    text = (value or "").strip()
    return None if text in ("", "null") else text


def _date(value: str | None) -> date | None:
    text = _clean(value)
    if text is None:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _person(first: str | None, last: str | None) -> str | None:
    name = " ".join(p for p in (_clean(first), _clean(last)) if p)
    return name or None


def _ids(value: str | None) -> tuple[str, ...]:
    return tuple(p.strip() for p in (_clean(value) or "").split(",") if p.strip())


def _open_archive(body: bytes, url: str) -> zipfile.ZipFile:
    try:
        return zipfile.ZipFile(io.BytesIO(body))
    except zipfile.BadZipFile as exc:
        raise UpstreamError(f"bc_lobbyists: {url} is not a readable ZIP file.") from exc


def _rows(archive: zipfile.ZipFile, name: str, columns: Iterable[str]) -> Iterator[dict[str, str]]:
    """Rows of one CSV member, checking the columns this module reads exist."""
    members = {i.filename.rsplit("/", 1)[-1].lower(): i for i in archive.infolist()}
    info = members.get(name.lower())
    if info is None:
        raise UpstreamError(f"bc_lobbyists: the zip has no {name}; the dataset layout changed.")
    if info.file_size > constants.MAX_MEMBER_BYTES:
        raise UpstreamError(f"bc_lobbyists: {name} unpacks to more than this module reads.")
    with archive.open(info) as raw:
        reader = csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8-sig", newline=""))
        missing = [c for c in columns if c not in (reader.fieldnames or [])]
        if missing:
            raise UpstreamError(f"bc_lobbyists: {name} has no column {missing}; layout changed.")
        yield from reader


def _as_of(archive: zipfile.ZipFile) -> datetime | None:
    stamps = [i.date_time for i in archive.infolist() if i.date_time[0] >= 1990]
    if not stamps:
        return None
    y, mo, d, h, mi, s = max(stamps)
    return datetime(y, mo, d, h, mi, s, tzinfo=UTC)


class _Topic(NamedTuple):
    text: str
    subject_matters: tuple[str, ...]
    intended_outcomes: tuple[str, ...]


def _topics(rows: Iterable[dict[str, str]], key: str) -> dict[str, list[_Topic]]:
    """Topics per record, once per distinct text and code set (the files repeat them)."""
    found: dict[str, dict[_Topic, None]] = {}
    for row in rows:
        text = _clean(row["TOPIC_OF_LOBBYING"])
        if text is None:
            continue
        topic = _Topic(text, _ids(row["SUBJECT_MATTER_IDS"]), _ids(row["INTENDED_OUTCOME_IDS"]))
        found.setdefault(row[key], {})[topic] = None
    return {k: list(v) for k, v in found.items()}


def _vocabulary(archive: zipfile.ZipFile) -> tuple[dict[str, str], dict[str, str]]:
    subjects = {
        r["SUBJECT_MATTER_ID"]: r["SUBJECT_MATTER"].strip()
        for r in _rows(
            archive, "Subject_Matters_Export.csv", ["SUBJECT_MATTER_ID", "SUBJECT_MATTER"]
        )
    }
    outcomes = {
        r["INTENDED_OUTCOME_ID"]: r["INTENDED_OUTCOME"].strip()
        for r in _rows(
            archive, "Intended_Outcomes_Export.csv", ["INTENDED_OUTCOME_ID", "INTENDED_OUTCOME"]
        )
    }
    return subjects, outcomes


def _topic_text(topics: Iterable[_Topic]) -> str:
    return _fold(" ".join(t.text for t in topics))


# ---------------------------------------------------------- registrations


@dataclass(slots=True)
class _Registration:
    registration_id: str
    number: str
    kind: str
    legislation: str
    first_registered: date | None
    version_start: date | None
    ended: date | None
    posted: date | None
    client_number: str | None
    client_name: str
    client_description: str | None
    client_website: str | None
    firm: str | None
    filer: str | None
    filer_title: str | None
    arranges_meetings: bool | None
    lobbyists: tuple[str, ...]
    agencies: tuple[str, ...]
    topics: tuple[_Topic, ...]
    client_folded: str = ""
    firm_folded: str = ""
    lobbyists_folded: tuple[str, ...] = ()
    agencies_folded: tuple[str, ...] = ()
    topics_folded: str = ""
    subject_ids: frozenset[str] = frozenset()
    blob: str = ""

    @property
    def active(self) -> bool:
        return self.ended is None


@dataclass(slots=True)
class _RegistrationStore:
    registrations: list[_Registration]
    subjects: dict[str, str]
    outcomes: dict[str, str]
    latest_of: dict[str, str]
    versions_total: int
    as_of: datetime | None
    by_id: dict[str, _Registration] = field(default_factory=dict)


def _yes_no(value: str | None) -> bool | None:
    text = _clean(value)
    return None if text is None else text.upper() == "Y"


def _chain_start(
    reg_id: str, previous: dict[str, str | None], starts: dict[str, date | None]
) -> date | None:
    """Earliest start along the chain of versions that led to `reg_id`."""
    earliest: date | None = None
    seen: set[str] = set()
    current: str | None = reg_id
    while current is not None and current not in seen:
        seen.add(current)
        start = starts.get(current)
        if start is not None and (earliest is None or start < earliest):
            earliest = start
        current = previous.get(current)
    return earliest


def parse_registrations(body: bytes, url: str) -> _RegistrationStore:
    archive = _open_archive(body, url)
    subjects, outcomes = _vocabulary(archive)
    agency_names = {
        r["BC_PUBLIC_AGENCY_ID"].strip(): r["BC_PUBLIC_AGENCY"].strip()
        for r in _rows(
            archive,
            "BC_Public_Agencies_Export.csv",
            ["BC_PUBLIC_AGENCY_ID", "BC_PUBLIC_AGENCY"],
        )
    }
    primary_columns = [
        "REG_ID", "REG_TYPE", "REG_NUM", "LOBB_ACT_CODE", "FIRM_NAME", "FILER_LAST_NAME",
        "FILER_FIRST_NAME", "FILER_POSITION_TITLE", "CLIENT_ORG_NUM", "CLIENT_ORG_NAME",
        "CLIENT_ORG_BUS_DESC", "CLIENT_ORG_WEB_ADDRESS", "REG_START_DATE", "REG_END_DATE",
        "REG_POSTED_DATE", "ARRANGE_MEETING", "PREVIOUS_VERSION_REG_ID",
    ]  # fmt: skip
    primary = list(_rows(archive, "Registration_Primary_Export.csv", primary_columns))

    previous = {r["REG_ID"]: _clean(r["PREVIOUS_VERSION_REG_ID"]) for r in primary}
    starts = {r["REG_ID"]: _date(r["REG_START_DATE"]) for r in primary}
    superseded = {p for p in previous.values() if p is not None}
    # Map every superseded version to the current one, so an old id still resolves.
    successor = {p: r_id for r_id, p in previous.items() if p is not None}
    latest_of: dict[str, str] = {}
    for old in superseded:
        current, hops = old, 0
        while current in successor and hops < 1000:
            current = successor[current]
            hops += 1
        latest_of[old] = current
    kept = {r["REG_ID"] for r in primary if r["REG_ID"] not in superseded}

    lobbyists: dict[str, dict[str, str]] = {}
    lobbyist_columns = ["REG_ID", "LOBBYIST_ID", "LOBBYIST_LAST_NAME", "LOBBYIST_FIRST_NAME"]
    for member in (
        "Registration_ConsultantLobbyists_Export.csv",
        "Registration_InHouseLobbyists_Export.csv",
    ):
        for row in _rows(archive, member, lobbyist_columns):
            if row["REG_ID"] not in kept:
                continue
            name = _person(row["LOBBYIST_FIRST_NAME"], row["LOBBYIST_LAST_NAME"])
            if name:
                lobbyists.setdefault(row["REG_ID"], {})[row["LOBBYIST_ID"]] = name
    agencies = {
        r["REG_ID"]: tuple(agency_names.get(i, i) for i in _ids(r["BC_PUBLIC_AGENCY_IDS"]))
        for r in _rows(
            archive, "Registration_BCPublicAgency_Export.csv", ["REG_ID", "BC_PUBLIC_AGENCY_IDS"]
        )
        if r["REG_ID"] in kept
    }
    topics = _topics(
        (
            r
            for r in _rows(
                archive,
                "Registration_SubjectMatterDetails_Export.csv",
                ["REG_ID", "TOPIC_OF_LOBBYING", "SUBJECT_MATTER_IDS", "INTENDED_OUTCOME_IDS"],
            )
            if r["REG_ID"] in kept
        ),
        "REG_ID",
    )

    registrations: list[_Registration] = []
    for row in primary:
        reg_id = row["REG_ID"]
        if reg_id not in kept:
            continue
        people = tuple(dict.fromkeys(lobbyists.get(reg_id, {}).values()))
        reg_topics = tuple(topics.get(reg_id, []))
        filer = _person(row["FILER_FIRST_NAME"], row["FILER_LAST_NAME"])
        reg = _Registration(
            registration_id=reg_id,
            number=row["REG_NUM"].strip(),
            kind="consultant" if row["REG_TYPE"].strip() == "Cons" else "in_house",
            legislation="lta" if row["LOBB_ACT_CODE"].strip() == "V5" else "legacy",
            first_registered=_chain_start(reg_id, previous, starts),
            version_start=starts[reg_id],
            ended=_date(row["REG_END_DATE"]),
            posted=_date(row["REG_POSTED_DATE"]),
            client_number=_clean(row["CLIENT_ORG_NUM"]),
            client_name=(_clean(row["CLIENT_ORG_NAME"]) or "").strip(),
            client_description=_clean(row["CLIENT_ORG_BUS_DESC"]),
            client_website=_clean(row["CLIENT_ORG_WEB_ADDRESS"]),
            firm=_clean(row["FIRM_NAME"]),
            filer=filer,
            filer_title=_clean(row["FILER_POSITION_TITLE"]),
            arranges_meetings=_yes_no(row["ARRANGE_MEETING"]),
            lobbyists=people,
            agencies=agencies.get(reg_id, ()),
            topics=reg_topics,
        )
        reg.client_folded = _fold(reg.client_name)
        reg.firm_folded = _fold(f"{reg.firm or ''} {reg.filer or ''}")
        reg.lobbyists_folded = tuple(_fold(p) for p in people)
        reg.agencies_folded = tuple(_fold(a) for a in reg.agencies)
        reg.topics_folded = _topic_text(reg_topics)
        reg.subject_ids = frozenset(s for t in reg_topics for s in t.subject_matters)
        reg.blob = " ".join(
            (
                reg.client_folded,
                reg.firm_folded,
                " ".join(reg.lobbyists_folded),
                reg.topics_folded,
                _fold(reg.client_description or ""),
            )
        )
        registrations.append(reg)
    if not registrations:
        raise UpstreamError(f"bc_lobbyists: {url} holds no current registrations; it changed.")
    store = _RegistrationStore(
        registrations=registrations,
        subjects=subjects,
        outcomes=outcomes,
        latest_of=latest_of,
        versions_total=len(primary),
        as_of=_as_of(archive),
    )
    store.by_id = {r.registration_id: r for r in registrations}
    return store


# --------------------------------------------------------------- activity


class _Holder(NamedTuple):
    name: str
    title: str | None
    branch: str | None
    agency: str | None


@dataclass(slots=True)
class _Report:
    report_id: str
    meeting: date | None
    client_number: str | None
    client_name: str
    kind: str | None
    filer: str | None
    lobbyists: tuple[str, ...]
    arranged: bool | None
    coalition: tuple[str, ...]
    holders: tuple[_Holder, ...]
    topics: tuple[_Topic, ...]
    submitted: date | None
    posted: date | None
    client_folded: str = ""
    people_folded: tuple[str, ...] = ()
    holders_folded: tuple[str, ...] = ()
    agencies_folded: tuple[str, ...] = ()
    topics_folded: str = ""
    subject_ids: frozenset[str] = frozenset()
    blob: str = ""


@dataclass(slots=True)
class _ActivityStore:
    reports: list[_Report]
    subjects: dict[str, str]
    outcomes: dict[str, str]
    as_of: datetime | None


def parse_activity(body: bytes, url: str) -> _ActivityStore:
    archive = _open_archive(body, url)
    subjects, outcomes = _vocabulary(archive)
    primary_columns = [
        "LAR_ID", "CLIENT_ORG_NUM", "CLIENT_ORG_NAME", "FILER_LAST_NAME", "FILER_FIRST_NAME",
        "MEETING_DATE", "ARRANGE_MEETING", "REG_TYPE", "SUBMISSION_DATE", "POSTED_DATE",
        "IH_LOBBYIST_LAST_NAME", "IH_LOBBYIST_FIRST_NAME", "COALITION_MEMBER_NAME",
    ]  # fmt: skip
    base: dict[str, dict[str, str]] = {}
    people: dict[str, dict[str, None]] = {}
    coalition: dict[str, dict[str, None]] = {}
    for row in _rows(archive, "LAR_Primary_Export.csv", primary_columns):
        lar = row["LAR_ID"]
        base.setdefault(lar, row)
        if name := _person(row["IH_LOBBYIST_FIRST_NAME"], row["IH_LOBBYIST_LAST_NAME"]):
            people.setdefault(lar, {})[name] = None
        if member := _clean(row["COALITION_MEMBER_NAME"]):
            coalition.setdefault(lar, {})[member] = None
    holders: dict[str, dict[_Holder, None]] = {}
    for row in _rows(
        archive,
        "LAR_SPOH_Export.csv",
        ["LAR_ID", "SPOH_LAST_NAME", "SPOH_FIRST_NAME", "SPOH_TITLE", "BRANCH", "BC_PUBLIC_AGENCY"],
    ):
        name = _person(row["SPOH_FIRST_NAME"], row["SPOH_LAST_NAME"])
        if name:
            holder = _Holder(
                name,
                _clean(row["SPOH_TITLE"]),
                _clean(row["BRANCH"]),
                _clean(row["BC_PUBLIC_AGENCY"]),
            )
            holders.setdefault(row["LAR_ID"], {})[holder] = None
    topics = _topics(
        _rows(
            archive,
            "LAR_SubjectMatterDetails_Export.csv",
            ["LAR_ID", "TOPIC_OF_LOBBYING", "SUBJECT_MATTER_IDS", "INTENDED_OUTCOME_IDS"],
        ),
        "LAR_ID",
    )

    reports: list[_Report] = []
    for lar, row in base.items():
        report = _Report(
            report_id=lar,
            meeting=_date(row["MEETING_DATE"]),
            client_number=_clean(row["CLIENT_ORG_NUM"]),
            client_name=(_clean(row["CLIENT_ORG_NAME"]) or "").strip(),
            kind={"Cons": "consultant", "Org": "in_house"}.get(row["REG_TYPE"].strip()),
            filer=_person(row["FILER_FIRST_NAME"], row["FILER_LAST_NAME"]),
            lobbyists=tuple(people.get(lar, {})),
            arranged=_yes_no(row["ARRANGE_MEETING"]),
            coalition=tuple(coalition.get(lar, {})),
            holders=tuple(holders.get(lar, {})),
            topics=tuple(topics.get(lar, [])),
            submitted=_date(row["SUBMISSION_DATE"]),
            posted=_date(row["POSTED_DATE"]),
        )
        report.client_folded = _fold(report.client_name)
        # A consultant report names the consultant as filer; an organization
        # report names its in-house lobbyists, with the filer as one more name.
        report.people_folded = tuple(_fold(p) for p in (*report.lobbyists, report.filer or "") if p)
        report.holders_folded = tuple(_fold(f"{h.name} {h.title or ''}") for h in report.holders)
        report.agencies_folded = tuple(_fold(h.agency or "") for h in report.holders)
        report.topics_folded = _topic_text(report.topics)
        report.subject_ids = frozenset(s for t in report.topics for s in t.subject_matters)
        report.blob = " ".join(
            (
                report.client_folded,
                " ".join(report.people_folded),
                " ".join(report.holders_folded),
                " ".join(report.agencies_folded),
                report.topics_folded,
            )
        )
        reports.append(report)
    if not reports:
        raise UpstreamError(f"bc_lobbyists: {url} holds no activity reports; it changed.")
    return _ActivityStore(
        reports=reports, subjects=subjects, outcomes=outcomes, as_of=_as_of(archive)
    )


# ------------------------------------------------------------------ fetch


def _zip_url(name: str) -> str:
    return f"{constants.DOWNLOAD_URL}?file={name}"


async def _download(name: str) -> bytes:
    url = _zip_url(name)
    await _LIMITER.acquire()
    try:
        response = await get_raw(
            constants.DOWNLOAD_URL,
            params={"file": name},
            timeout=constants.DOWNLOAD_TIMEOUT_SECONDS,
        )
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status in (404, 410):
            raise NotFound(f"bc_lobbyists: {url} is gone (HTTP {status}); the file moved.") from exc
        raise UpstreamError(f"bc_lobbyists: {url} returned HTTP {status}.") from exc
    except httpx.HTTPError as exc:
        raise UpstreamUnavailable(f"bc_lobbyists: {url} did not respond in time.") from exc
    body = response.content
    if len(body) > constants.MAX_ZIP_BYTES:
        raise UpstreamError(f"bc_lobbyists: {url} is much larger than expected; it changed.")
    # An expired session or maintenance page answers 200 with HTML, not a zip.
    if not body.startswith(b"PK"):
        raise UpstreamError(f"bc_lobbyists: {url} did not return a ZIP file (got a web page).")
    return body


async def _registrations() -> tuple[_RegistrationStore, bool]:
    async def fetch() -> _RegistrationStore:
        body = await _download(constants.REGISTRATION_ZIP)
        return await run_parse(parse_registrations, body, _zip_url(constants.REGISTRATION_ZIP))

    return await cached_fetch("bc_lobbyists:registrations", constants.DATA_TTL_SECONDS, fetch)


async def _activity() -> tuple[_ActivityStore, bool]:
    async def fetch() -> _ActivityStore:
        body = await _download(constants.ACTIVITY_ZIP)
        return await run_parse(parse_activity, body, _zip_url(constants.ACTIVITY_ZIP))

    return await cached_fetch("bc_lobbyists:activity", constants.DATA_TTL_SECONDS, fetch)


def _provenance(
    name: str,
    schema: str,
    cached: bool,
    as_of: datetime | None,
    coverage: str,
    lang: str,
    limits: str | None = None,
) -> Provenance:
    return make_provenance(
        source=constants.RATE_LIMIT_SOURCE,
        url=_zip_url(name),
        cached=cached,
        schema_name=f"bc_lobbyists.{schema}",
        as_of=as_of,
        freshness=_pick(
            lang,
            "monthly (Registrar's mass datasets)",
            "mensuelle (jeux de données massifs du registraire)",
        ),
        coverage=coverage,
        limits=limits,
        licence=f"Open Data Licence for the Office of the Registrar of Lobbyists for British "
        f"Columbia ({constants.LICENCE_URL}). Attribution: '{constants.ATTRIBUTION}' The licence "
        "grants no rights to personal information.",
    )


def _omitted(lang: str) -> str:
    return _pick(lang, constants.OMITTED_EN, constants.OMITTED_FR)


# ----------------------------------------------------------------- filters


def _parse_date(value: str | None, name: str) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError as exc:
        raise InvalidInput(f"bc_lobbyists: {name} must be YYYY-MM-DD, got {value!r}.") from exc


def _date_range(date_from: str | None, date_to: str | None) -> tuple[date | None, date | None]:
    start, end = _parse_date(date_from, "date_from"), _parse_date(date_to, "date_to")
    check_range(start, end, "date_from", "date_to")
    return start, end


def _words(text: str) -> list[str]:
    return _fold(text).split()


def _all_in(haystack: str, words: list[str]) -> bool:
    return all(w in haystack for w in words)


def _any_all_in(items: Iterable[str], words: list[str]) -> bool:
    """One item holds every word, so 'john smith' needs one John Smith, not two people."""
    return any(_all_in(item, words) for item in items)


def _subject_ids(text: str, subjects: dict[str, str]) -> frozenset[str]:
    if not text.strip():
        return frozenset()
    words = _words(text)
    found = frozenset(i for i, n in subjects.items() if _all_in(_fold(n), words))
    if not found:
        raise InvalidInput(
            f"bc_lobbyists: no subject matter matches {text!r}; "
            "see bc_lobbyists_list_codes(kind='subject_matters')."
        )
    return found


def _check_limit(limit: int, maximum: int, name: str = "limit") -> None:
    if not 1 <= limit <= maximum:
        raise InvalidInput(f"bc_lobbyists: {name} must be 1 to {maximum}.")


def _check_kind(kind: str | None) -> None:
    if kind is not None and kind not in ("consultant", "in_house"):
        raise InvalidInput("bc_lobbyists: kind must be 'consultant' or 'in_house'.")


# ----------------------------------------------------------- registrations


def _topic_model(
    topic: _Topic, subjects: dict[str, str], outcomes: dict[str, str], full: bool
) -> OrlTopic:
    text = topic.text
    if not full and len(text) > constants.TOPIC_PREVIEW_CHARS:
        text = text[: constants.TOPIC_PREVIEW_CHARS].rstrip() + "..."
    return OrlTopic(
        topic=text,
        subject_matters=[subjects.get(i, i) for i in topic.subject_matters],
        intended_outcomes=[outcomes.get(i, i) for i in topic.intended_outcomes],
    )


def _registration_model(
    reg: _Registration, store: _RegistrationStore, lang: str, full: bool
) -> OrlRegistration:
    people = (
        list(reg.lobbyists) if full else list(reg.lobbyists[: constants.SEARCH_LOBBYISTS_SHOWN])
    )
    shown = reg.topics if full else reg.topics[: constants.SEARCH_TOPICS_SHOWN]
    status = "active" if reg.active else "ended"
    return OrlRegistration(
        registration_id=reg.registration_id,
        registration_number=reg.number,
        kind=reg.kind,  # type: ignore[arg-type]
        kind_label=_label(reg.kind, lang),
        legislation=reg.legislation,  # type: ignore[arg-type]
        status=status,
        status_label=_label(status, lang),
        first_registered=reg.first_registered,
        version_start=reg.version_start,
        ended=reg.ended,
        posted=reg.posted,
        client_number=reg.client_number,
        client_name=reg.client_name,
        client_description=reg.client_description,
        client_website=reg.client_website,
        firm=reg.firm,
        filer=reg.filer,
        filer_title=reg.filer_title,
        arranges_meetings=reg.arranges_meetings,
        lobbyist_count=len(reg.lobbyists),
        lobbyists=people,
        agencies=list(reg.agencies),
        topic_count=len(reg.topics),
        topics=[_topic_model(t, store.subjects, store.outcomes, full) for t in shown],
    )


def _overlaps(reg: _Registration, start: date | None, end: date | None) -> bool:
    began = reg.first_registered or reg.version_start
    stopped = reg.ended or date.max
    return (end is None or began is None or began <= end) and (start is None or stopped >= start)


async def search_registrations(
    query: str = "",
    *,
    client: str = "",
    lobbyist: str = "",
    firm: str = "",
    subject_matter: str = "",
    agency: str = "",
    kind: str | None = None,
    status: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = constants.SEARCH_DEFAULT_LIMIT,
    lang: str = "en",
) -> OrlRegistrationList:
    """Current versions of registrations matching every filter given."""
    _check_limit(limit, constants.SEARCH_MAX_LIMIT)
    _check_kind(kind)
    if status is not None and status not in ("active", "ended"):
        raise InvalidInput("bc_lobbyists: status must be 'active' or 'ended'.")
    start, end = _date_range(date_from, date_to)
    store, cached = await _registrations()
    words, client_words = _words(query), _words(client)
    lobbyist_words, firm_words = _words(lobbyist), _words(firm)
    agency_words = _words(agency)
    subject_ids = _subject_ids(subject_matter, store.subjects)
    client_number = client.strip() if client.strip().isdigit() else None

    matched = [
        r
        for r in store.registrations
        if _all_in(r.blob, words)
        and (
            not client_words
            or _all_in(r.client_folded, client_words)
            or r.client_number == client_number
        )
        and (not lobbyist_words or _any_all_in(r.lobbyists_folded, lobbyist_words))
        and (not firm_words or _all_in(r.firm_folded, firm_words))
        and (not agency_words or _any_all_in(r.agencies_folded, agency_words))
        and (not subject_ids or r.subject_ids & subject_ids)
        and (kind is None or r.kind == kind)
        and (
            status is None
            or (r.active and status == "active")
            or (not r.active and status == "ended")
        )
        and _overlaps(r, start, end)
    ]
    matched.sort(
        key=lambda r: (not r.active, -(r.version_start or date.min).toordinal(), r.registration_id)
    )
    models = fit_to_budget(
        [_registration_model(r, store, lang, full=False) for r in matched[:limit]]
    )
    return OrlRegistrationList(
        registrations=models,
        returned_count=len(models),
        total_matched=len(matched),
        by_status=dict(Counter("active" if r.active else "ended" for r in matched)),
        by_kind=dict(Counter(r.kind for r in matched)),
        note=_pick(
            lang,
            "Only the current version of each registration is searched "
            f"({len(store.registrations)} of {store.versions_total} versions in the file). "
            "Topics and lobbyists are shortened here; bc_lobbyists_get_registration gives all.",
            "Seule la version courante de chaque inscription est interrogée "
            f"({len(store.registrations)} versions sur {store.versions_total} dans le fichier). "
            "Les sujets et lobbyistes sont abrégés ici; bc_lobbyists_get_registration les donne tous.",
        ),
        omitted=_omitted(lang),
        provenance=_provenance(
            constants.REGISTRATION_ZIP,
            "OrlRegistrationList",
            cached,
            store.as_of,
            _pick(
                lang,
                f"registration returns filed since 2010, {len(store.registrations)} registrations",
                f"déclarations d'inscription depuis 2010, {len(store.registrations)} inscriptions",
            ),
            lang,
            truncation_note(
                returned=len(models),
                total=len(matched),
                unit="matching registrations (active first, then most recently changed)",
                how_to_get_more="narrow the filters or raise limit "
                f"(max {constants.SEARCH_MAX_LIMIT}; responses are also capped near 200 KB)",
            ),
        ),
    )


async def get_registration(registration: str, *, lang: str = "en") -> OrlRegistrationDetail:
    """One registration by id ('R-56584653') or number ('9997-443-56' or '9997-443')."""
    wanted = registration.strip()
    if not wanted:
        raise InvalidInput("bc_lobbyists: pass a registration id like 'R-56584653' or a number.")
    store, cached = await _registrations()
    found: list[_Registration] = []
    if wanted.upper().startswith("R-"):
        reg_id = store.latest_of.get(wanted.upper(), wanted.upper())
        if reg_id in store.by_id:
            found = [store.by_id[reg_id]]
    elif match := _NUMBER.match(wanted):
        pair = f"{match.group(1)}-{match.group(2)}-"
        found = [r for r in store.registrations if r.number == wanted]
        # A three-part number of an older version, or a bare filer-client
        # pair, falls back to the current version(s) of that pair.
        found = found or [r for r in store.registrations if (r.number + "-").startswith(pair)]
    else:
        raise InvalidInput(
            "bc_lobbyists: registration must look like 'R-56584653', '9997-443-56' or '9997-443'."
        )
    if not found:
        raise NotFound(
            f"bc_lobbyists: no current registration {wanted!r}; search with "
            "bc_lobbyists_search_registrations."
        )
    found = found[:20]
    return OrlRegistrationDetail(
        registrations=[_registration_model(r, store, lang, full=True) for r in found],
        omitted=_omitted(lang),
        provenance=_provenance(
            constants.REGISTRATION_ZIP,
            "OrlRegistrationDetail",
            cached,
            store.as_of,
            _pick(lang, "current version of the registration", "version courante de l'inscription"),
            lang,
        ),
    )


# --------------------------------------------------------------- activity


def _holder_model(holder: _Holder) -> OrlOfficeHolder:
    return OrlOfficeHolder(
        name=holder.name, title=holder.title, branch=holder.branch, agency=holder.agency
    )


def _report_model(report: _Report, store: _ActivityStore) -> OrlActivityReport:
    return OrlActivityReport(
        report_id=report.report_id,
        meeting_date=report.meeting,
        client_number=report.client_number,
        client_name=report.client_name,
        registration_kind=report.kind,  # type: ignore[arg-type]
        filer=report.filer,
        lobbyists=list(report.lobbyists),
        arranged_meeting=report.arranged,
        coalition_members=list(report.coalition),
        office_holders=[_holder_model(h) for h in report.holders],
        topics=[
            _topic_model(t, store.subjects, store.outcomes, full=False)
            for t in report.topics[: constants.SEARCH_TOPICS_SHOWN]
        ],
        topic_count=len(report.topics),
        submitted=report.submitted,
        posted=report.posted,
    )


def _filter_reports(
    store: _ActivityStore,
    *,
    query: str,
    client: str,
    lobbyist: str,
    office_holder: str,
    agency: str,
    subject_matter: str,
    kind: str | None,
    date_from: str | None,
    date_to: str | None,
    arranged_only: bool | None,
) -> list[_Report]:
    _check_kind(kind)
    start, end = _date_range(date_from, date_to)
    words, client_words = _words(query), _words(client)
    lobbyist_words, holder_words = _words(lobbyist), _words(office_holder)
    agency_words = _words(agency)
    subject_ids = _subject_ids(subject_matter, store.subjects)
    client_number = client.strip() if client.strip().isdigit() else None
    return [
        r
        for r in store.reports
        if _all_in(r.blob, words)
        and (
            not client_words
            or _all_in(r.client_folded, client_words)
            or r.client_number == client_number
        )
        and (not lobbyist_words or _any_all_in(r.people_folded, lobbyist_words))
        and (not holder_words or _any_all_in(r.holders_folded, holder_words))
        and (not agency_words or _any_all_in(r.agencies_folded, agency_words))
        and (not subject_ids or r.subject_ids & subject_ids)
        and (kind is None or r.kind == kind)
        and (arranged_only is None or r.arranged is arranged_only)
        and (start is None or (r.meeting is not None and r.meeting >= start))
        and (end is None or (r.meeting is not None and r.meeting <= end))
    ]


def _span(reports: list[_Report]) -> tuple[date | None, date | None]:
    days = [r.meeting for r in reports if r.meeting is not None]
    return (min(days), max(days)) if days else (None, None)


def _activity_note(lang: str) -> str:
    return _pick(
        lang,
        "Lobbying activity reports since 2020-05-04 (Lobbyists Transparency Act): one "
        "report per client, month and communication, naming the senior public office "
        "holders reached. Registrations are searched with bc_lobbyists_search_registrations.",
        "Rapports d'activité de lobbying depuis le 2020-05-04 (Loi sur la transparence du "
        "lobbying) : un rapport par client, mois et communication, nommant les titulaires de "
        "charge publique supérieure joints. Les inscriptions se cherchent avec "
        "bc_lobbyists_search_registrations.",
    )


def _activity_coverage(store: _ActivityStore, lang: str) -> str:
    return _pick(
        lang,
        f"{len(store.reports)} activity reports, meetings from 2020-05-04",
        f"{len(store.reports)} rapports d'activité, rencontres depuis le 2020-05-04",
    )


async def search_activity_reports(
    query: str = "",
    *,
    client: str = "",
    lobbyist: str = "",
    office_holder: str = "",
    agency: str = "",
    subject_matter: str = "",
    kind: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    arranged_only: bool | None = None,
    limit: int = constants.SEARCH_DEFAULT_LIMIT,
    lang: str = "en",
) -> OrlActivityReportList:
    """Activity reports matching every filter given, newest meeting first."""
    _check_limit(limit, constants.SEARCH_MAX_LIMIT)
    _date_range(date_from, date_to)  # fail before the download
    store, cached = await _activity()
    matched = _filter_reports(
        store,
        query=query,
        client=client,
        lobbyist=lobbyist,
        office_holder=office_holder,
        agency=agency,
        subject_matter=subject_matter,
        kind=kind,
        date_from=date_from,
        date_to=date_to,
        arranged_only=arranged_only,
    )
    matched.sort(key=lambda r: ((r.meeting or date.min).toordinal(), r.report_id), reverse=True)
    reports = fit_to_budget([_report_model(r, store) for r in matched[:limit]])
    first, last = _span(matched)
    return OrlActivityReportList(
        reports=reports,
        returned_count=len(reports),
        total_matched=len(matched),
        first_meeting=first,
        last_meeting=last,
        note=_activity_note(lang),
        omitted=_omitted(lang),
        provenance=_provenance(
            constants.ACTIVITY_ZIP,
            "OrlActivityReportList",
            cached,
            store.as_of,
            _activity_coverage(store, lang),
            lang,
            truncation_note(
                returned=len(reports),
                total=len(matched),
                unit="matching reports",
                order="latest",
                how_to_get_more="narrow the dates or filters or raise limit "
                f"(max {constants.SEARCH_MAX_LIMIT}; responses are also capped near 200 KB)",
            ),
        ),
    )


def _group_keys(report: _Report, group_by: str, store: _ActivityStore) -> list[str]:
    match group_by:
        case "client":
            return [report.client_name]
        case "ministry":
            return list(dict.fromkeys(h.agency or "(not stated)" for h in report.holders))
        case "office_holder":
            return list(
                dict.fromkeys(
                    f"{h.name} ({h.agency})" if h.agency else h.name for h in report.holders
                )
            )
        case "subject_matter":
            return list(
                dict.fromkeys(
                    store.subjects.get(s, s) for t in report.topics for s in t.subject_matters
                )
            )
        case "lobbyist":
            return list(
                dict.fromkeys(report.lobbyists or ((report.filer,) if report.filer else ()))
            )
        case "month":
            return [report.meeting.strftime("%Y-%m")] if report.meeting else []
        case "year":
            return [str(report.meeting.year)] if report.meeting else []
    return []


async def summarize_activity(
    group_by: GroupBy,
    *,
    query: str = "",
    client: str = "",
    lobbyist: str = "",
    office_holder: str = "",
    agency: str = "",
    subject_matter: str = "",
    kind: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    arranged_only: bool | None = None,
    top: int = constants.SUMMARY_DEFAULT_TOP,
    lang: str = "en",
) -> OrlActivitySummary:
    """Distinct activity reports counted by client, ministry, office holder, subject..."""
    if group_by not in constants.GROUPS:
        raise InvalidInput(f"bc_lobbyists: group_by must be one of {list(constants.GROUPS)}.")
    _check_limit(top, constants.SUMMARY_MAX_TOP, "top")
    store, cached = await _activity()
    matched = _filter_reports(
        store,
        query=query,
        client=client,
        lobbyist=lobbyist,
        office_holder=office_holder,
        agency=agency,
        subject_matter=subject_matter,
        kind=kind,
        date_from=date_from,
        date_to=date_to,
        arranged_only=arranged_only,
    )
    counts: Counter[str] = Counter()
    days: dict[str, list[date]] = {}
    for report in matched:
        for key in _group_keys(report, group_by, store):
            counts[key] += 1
            if report.meeting is not None:
                days.setdefault(key, []).append(report.meeting)
    series = group_by in ("month", "year")
    if series:
        # A time series reads oldest to newest and stays contiguous, so `top`
        # keeps the latest periods, not the busiest (the docstring says so).
        ordered = sorted(counts)[-top:]
    else:
        ordered = [k for k, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:top]]
    note = _pick(
        lang,
        "Each row counts distinct reports, so a report naming two ministries counts once "
        "for each; rows can add up to more than total_reports. Reports are not meetings: "
        "one meeting can be reported by several lobbyists or clients.",
        "Chaque ligne compte des rapports distincts : un rapport nommant deux ministères "
        "compte une fois pour chacun, donc les lignes peuvent dépasser total_reports. Un "
        "rapport n'est pas une rencontre : une rencontre peut être déclarée par plusieurs "
        "lobbyistes ou clients.",
    )
    if series:
        note += " " + _pick(
            lang,
            f"Rows are the {len(ordered)} most recent of {len(counts)} periods, oldest to "
            "newest (not the busiest); the latest period can be incomplete.",
            f"Les lignes sont les {len(ordered)} périodes les plus récentes sur {len(counts)}, "
            "de la plus ancienne à la plus récente (pas les plus chargées); la dernière "
            "période peut être incomplète.",
        )
    rows = [
        OrlGroupRow(
            key=k,
            reports=counts[k],
            first_meeting=min(days[k]) if k in days else None,
            last_meeting=max(days[k]) if k in days else None,
        )
        for k in ordered
    ]
    return OrlActivitySummary(
        group_by=group_by,
        rows=rows,
        groups_total=len(counts),
        total_reports=len(matched),
        note=note,
        omitted=_omitted(lang),
        provenance=_provenance(
            constants.ACTIVITY_ZIP,
            "OrlActivitySummary",
            cached,
            store.as_of,
            _activity_coverage(store, lang),
            lang,
        ),
    )


# ------------------------------------------------------------------ codes


async def list_codes(kind: CodeKind, *, query: str = "", lang: str = "en") -> OrlCodeList:
    """Subject matters, intended outcomes, or the ministries named in activity reports."""
    if kind not in constants.CODE_KINDS:
        raise InvalidInput(f"bc_lobbyists: kind must be one of {list(constants.CODE_KINDS)}.")
    store, cached = await _activity()
    words = _words(query)
    codes: list[OrlCode]
    if kind == "ministries":
        counts = Counter(
            a for r in store.reports for a in {h.agency for h in r.holders if h.agency}
        )
        codes = [
            OrlCode(name=n, reports=c)
            for n, c in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
        ]
    else:
        source = store.subjects if kind == "subject_matters" else store.outcomes
        codes = [OrlCode(code=i, name=n) for i, n in sorted(source.items(), key=lambda kv: kv[1])]
    codes = [c for c in codes if _all_in(_fold(c.name), words)]
    return OrlCodeList(
        kind=kind,
        codes=codes,
        total=len(codes),
        provenance=_provenance(
            constants.ACTIVITY_ZIP,
            "OrlCodeList",
            cached,
            store.as_of,
            _activity_coverage(store, lang),
            lang,
        ),
    )
