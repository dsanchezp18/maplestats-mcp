"""Tests on CSV rows trimmed from the live ORL mass datasets (checked 2026-10-02).

Each fixture copies a quirk seen live: UTF-8 files with a byte order mark,
the text "null" for an absent value, empty BRANCH cells, versioned
registrations (a superseded version is not a registration), a topic repeated
once per detail id, one LAR_Primary row per in-house lobbyist, the
dictionary's REG_TYPE 1/3 that is really Cons/Org, an HTML page answered with
HTTP 200 instead of a zip, and personal fields (addresses, phone numbers,
gifts, political contributions, past public offices) that must never reach a
tool result.
"""

from __future__ import annotations

import csv
import io
import json
import re
import zipfile
from datetime import date

import pytest

from maplestats_mcp.modules.bc_lobbyists import client, constants
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError

_REG_URL = f"{constants.DOWNLOAD_URL}?file={constants.REGISTRATION_ZIP}"
_LAR_URL = f"{constants.DOWNLOAD_URL}?file={constants.ACTIVITY_ZIP}"

# Strings that identify personal data in the fixtures; none may be returned.
_PERSONAL = [
    "Montiverdi",
    "4047475843",
    "Jane Gifted",
    "Donor Dave",
    "Ministerial Assistant",
    "Cooling off",
    "Business Conduct",
    "Beneficiary Person",
]


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_module._caches.clear()
    yield


def _csv(header: list[str], rows: list[dict[str, str]]) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=header, restval="null", lineterminator="\r\n")
    writer.writeheader()
    writer.writerows(rows)
    return b"\xef\xbb\xbf" + buffer.getvalue().encode("utf-8")


def _zip(members: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, body in members.items():
            info = zipfile.ZipInfo(name, date_time=(2026, 9, 20, 1, 20, 0))
            archive.writestr(info, body)
    return buffer.getvalue()


_SUBJECTS = _csv(
    ["SUBJECT_MATTER_ID", "SUBJECT_MATTER"],
    [
        {"SUBJECT_MATTER_ID": "SM-18", "SUBJECT_MATTER": "Health"},
        {"SUBJECT_MATTER_ID": "SM-15", "SUBJECT_MATTER": "Forestry"},
        {"SUBJECT_MATTER_ID": "SM-6", "SUBJECT_MATTER": "Consumer Issues"},
    ],
)
_OUTCOMES = _csv(
    ["INTENDED_OUTCOME_ID", "INTENDED_OUTCOME"],
    [
        {
            "INTENDED_OUTCOME_ID": "BC-03",
            "INTENDED_OUTCOME": "Development or enactment of any regulation",
        },
        {
            "INTENDED_OUTCOME_ID": "BC-04",
            "INTENDED_OUTCOME": "Development of any program or policy",
        },
        {
            "INTENDED_OUTCOME_ID": "IO-01",
            "INTENDED_OUTCOME": "Introduction, modification or repeal of legislation",
        },
    ],
)
_AGENCIES = _csv(
    ["BC_PUBLIC_AGENCY_ID", "BC_PUBLIC_AGENCY"],
    [
        {"BC_PUBLIC_AGENCY_ID": "GI-72", "BC_PUBLIC_AGENCY": "Office of the Premier"},
        {
            "BC_PUBLIC_AGENCY_ID": "GI-32051",
            "BC_PUBLIC_AGENCY": "Member(s) of the BC Legislative Assembly",
        },
        {"BC_PUBLIC_AGENCY_ID": "GI-61", "BC_PUBLIC_AGENCY": "Forests"},
    ],
)

_PRIMARY_HEADER = [
    "REG_ID", "REG_TYPE", "REG_NUM", "USER_PROFILE_ID", "LOBB_ACT_CODE", "FIRM_NAME",
    "FIRM_ADDRESS", "FILER_NUM", "FILER_LAST_NAME", "FILER_FIRST_NAME", "FILER_MIDDLE_NAME",
    "FILER_POSITION_TITLE", "FILER_ADDRESS", "CLIENT_ORG_PROFILE_ID", "CLIENT_ORG_NUM",
    "CLIENT_ORG_NAME", "CLIENT_ORG_ADDRESS", "DATE_OF_WRIT", "CLIENT_LOBBY_MLA_IND",
    "CLIENT_CONTRIBUTIONS_POLITICAL", "CLIENT_CONTRIBUTIONS_SPONSORSHIP",
    "CLIENT_CONTRIBUTIONS_RECALL", "CLIENT_ORG_BUS_DESC", "CLIENT_ORG_WEB_ADDRESS",
    "REG_START_DATE", "REG_PROJECTED_END_DATE", "REG_END_DATE", "REG_POSTED_DATE",
    "AFFILIATES_IND", "COALITION_IND", "CONTRIBUTORS_IND", "DIRECT_INT_IND", "GOVT_FUND_IND",
    "PREVIOUS_VERSION_REG_ID", "ARRANGE_MEETING",
]  # fmt: skip


def _primary(**fields: str) -> dict[str, str]:
    base = {"USER_PROFILE_ID": "UP-1", "LOBB_ACT_CODE": "V5", "REG_POSTED_DATE": "2026-09-01"}
    return {**base, **fields}


_PRIMARY = _csv(
    _PRIMARY_HEADER,
    [
        # Version 1 of a consultant registration, replaced by R-2 on 2026-03-01.
        _primary(
            REG_ID="R-1", REG_TYPE="Cons", REG_NUM="1846-6757-1", FIRM_NAME="Moonen & Associates",
            FIRM_ADDRESS="5330 Montiverdi Place, West Vancouver, BC", FILER_NUM="1846",
            FILER_LAST_NAME="Moonen", FILER_FIRST_NAME="John",
            FILER_ADDRESS="5330 Montiverdi Place, West Vancouver, BC", CLIENT_ORG_NUM="6757",
            CLIENT_ORG_NAME="Athiana Acres Holdings Ltd.",
            CLIENT_ORG_ADDRESS="103 - 6791 Elmbridge Way, Richmond, BC",
            CLIENT_CONTRIBUTIONS_POLITICAL="Y", CLIENT_ORG_BUS_DESC="farming",
            REG_START_DATE="2021-02-01", REG_END_DATE="2026-03-01", ARRANGE_MEETING="Y",
        ),
        _primary(
            REG_ID="R-2", REG_TYPE="Cons", REG_NUM="1846-6757-2", FIRM_NAME="Moonen & Associates",
            FIRM_ADDRESS="5330 Montiverdi Place, West Vancouver, BC", FILER_NUM="1846",
            FILER_LAST_NAME="Moonen", FILER_FIRST_NAME="John",
            FILER_ADDRESS="5330 Montiverdi Place, West Vancouver, BC", CLIENT_ORG_NUM="6757",
            CLIENT_ORG_NAME="Athiana Acres Holdings Ltd.", CLIENT_ORG_BUS_DESC="farming",
            REG_START_DATE="2026-03-01", PREVIOUS_VERSION_REG_ID="R-1", ARRANGE_MEETING="N",
        ),
        # In-house organization, active, two lobbyists, one topic stored twice.
        _primary(
            REG_ID="R-3", REG_TYPE="Org", REG_NUM="9997-443-56", FILER_NUM="9997",
            FILER_LAST_NAME="Mathiesen Newcomb", FILER_FIRST_NAME="Quinn",
            FILER_POSITION_TITLE="Chief Executive Officer", CLIENT_ORG_NUM="443",
            CLIENT_ORG_NAME="BC Dental Association",
            CLIENT_ORG_ADDRESS="540 - 1385 W. 8th Avenue, Vancouver, BC",
            CLIENT_ORG_BUS_DESC="The BCDA is the voice of dentists.",
            CLIENT_ORG_WEB_ADDRESS="https://example.org", REG_START_DATE="2026-09-16",
            ARRANGE_MEETING="null",
        ),
        # Legacy registration under the earlier Act, ended, accented client name.
        _primary(
            REG_ID="R-4", REG_TYPE="Org", REG_NUM="500-77-3", LOBB_ACT_CODE="VL", FILER_NUM="500",
            FILER_LAST_NAME="Tremblay", FILER_FIRST_NAME="Marie", CLIENT_ORG_NUM="77",
            CLIENT_ORG_NAME="Société Forestière du Nord", REG_START_DATE="2012-01-01",
            REG_END_DATE="2019-05-01", PREVIOUS_VERSION_REG_ID="null",
        ),
    ],
)  # fmt: skip

_LOBBYIST_HEADER = ["REG_ID", "LOBBYIST_ID", "LOBBYIST_LAST_NAME", "LOBBYIST_FIRST_NAME"]
_CONSULTANTS = _csv(
    _LOBBYIST_HEADER + ["FILER_NUM", "POH_IND", "CODE_CONDUCT_IND"],
    [
        {"REG_ID": "R-1", "LOBBYIST_ID": "L-9", "LOBBYIST_LAST_NAME": "Moonen",
         "LOBBYIST_FIRST_NAME": "John", "POH_IND": "Y"},
        {"REG_ID": "R-2", "LOBBYIST_ID": "L-9", "LOBBYIST_LAST_NAME": "Moonen",
         "LOBBYIST_FIRST_NAME": "John", "POH_IND": "Y"},
        {"REG_ID": "R-2", "LOBBYIST_ID": "L-10", "LOBBYIST_LAST_NAME": "Smith",
         "LOBBYIST_FIRST_NAME": "Ann", "POH_IND": "N"},
    ],
)  # fmt: skip
_INHOUSE = _csv(
    _LOBBYIST_HEADER + ["EXEMPTION_DECISION_NUMBER"],
    [
        {"REG_ID": "R-3", "LOBBYIST_ID": "L-20", "LOBBYIST_LAST_NAME": "Mathiesen Newcomb",
         "LOBBYIST_FIRST_NAME": "Quinn", "EXEMPTION_DECISION_NUMBER": "Cooling off 12"},
        {"REG_ID": "R-3", "LOBBYIST_ID": "L-21", "LOBBYIST_LAST_NAME": "Okafor",
         "LOBBYIST_FIRST_NAME": "Ngozi"},
        {"REG_ID": "R-4", "LOBBYIST_ID": "L-30", "LOBBYIST_LAST_NAME": "Tremblay",
         "LOBBYIST_FIRST_NAME": "Marie"},
    ],
)  # fmt: skip
_REG_AGENCY = _csv(
    ["REG_ID", "BC_PUBLIC_AGENCY_IDS"],
    [
        {"REG_ID": "R-2", "BC_PUBLIC_AGENCY_IDS": "GI-61"},
        {"REG_ID": "R-3", "BC_PUBLIC_AGENCY_IDS": "GI-72, GI-32051, GI-99999"},
    ],
)
_REG_TOPICS = _csv(
    ["REG_ID", "INTENDED_OUTCOME_IDS", "SUBJECT_MATTER_DETAIL_ID", "TOPIC_OF_LOBBYING", "SUBJECT_MATTER_IDS"],
    [
        {"REG_ID": "R-1", "INTENDED_OUTCOME_IDS": "BC-04", "SUBJECT_MATTER_DETAIL_ID": "1",
         "TOPIC_OF_LOBBYING": "Old topic on farmland", "SUBJECT_MATTER_IDS": "SM-15"},
        {"REG_ID": "R-2", "INTENDED_OUTCOME_IDS": "BC-04", "SUBJECT_MATTER_DETAIL_ID": "2",
         "TOPIC_OF_LOBBYING": "Farmland tax treatment of timber lots", "SUBJECT_MATTER_IDS": "SM-15"},
        {"REG_ID": "R-3", "INTENDED_OUTCOME_IDS": "BC-03, BC-04", "SUBJECT_MATTER_DETAIL_ID": "3",
         "TOPIC_OF_LOBBYING": "Support for non-hospital anesthesia facilities", "SUBJECT_MATTER_IDS": "SM-18"},
        {"REG_ID": "R-3", "INTENDED_OUTCOME_IDS": "BC-03, BC-04", "SUBJECT_MATTER_DETAIL_ID": "4",
         "TOPIC_OF_LOBBYING": "Support for non-hospital anesthesia facilities", "SUBJECT_MATTER_IDS": "SM-18"},
        {"REG_ID": "R-4", "INTENDED_OUTCOME_IDS": "IO-01", "SUBJECT_MATTER_DETAIL_ID": "5",
         "TOPIC_OF_LOBBYING": "Forest tenure reform", "SUBJECT_MATTER_IDS": "SM-15"},
    ],
)  # fmt: skip
# Members the module must never read: personal data.
_GIFTS = _csv(
    ["REG_ID", "POH_FIRST_NAME", "POH_LAST_NAME", "GIFT_DESCRIPTION"],
    [
        {
            "REG_ID": "R-3",
            "POH_FIRST_NAME": "Jane",
            "POH_LAST_NAME": "Gifted",
            "GIFT_DESCRIPTION": "Food",
        }
    ],
)
_CONDUCT = _csv(
    ["REG_ID", "CODE_CONDUCT_NAME", "CODE_CONDUCT_TELEPHONE"],
    [
        {
            "REG_ID": "R-3",
            "CODE_CONDUCT_NAME": "Business Conduct Guidelines",
            "CODE_CONDUCT_TELEPHONE": "4047475843",
        }
    ],
)
_BENEFICIARIES = _csv(
    ["REG_ID", "BENEFICIARY_TYPE", "BENEFICIARY_NAME"],
    [{"REG_ID": "R-3", "BENEFICIARY_TYPE": "Affiliate", "BENEFICIARY_NAME": "Beneficiary Person"}],
)
_CONTACTS = _csv(["REG_ID", "TARGET_NAME"], [{"REG_ID": "R-4", "TARGET_NAME": "Donor Dave"}])
_PUBLIC_OFFICE = _csv(
    ["LOBBYIST_ID", "POSITION_TITLE", "POH_DESCRIPTION_ROLE"],
    [
        {
            "LOBBYIST_ID": "L-9",
            "POSITION_TITLE": "Political Staff",
            "POH_DESCRIPTION_ROLE": "Ministerial Assistant",
        }
    ],
)


def _registration_zip(extra: dict[str, bytes] | None = None, drop: str | None = None) -> bytes:
    members = {
        "Registration_Primary_Export.csv": _PRIMARY,
        "Registration_ConsultantLobbyists_Export.csv": _CONSULTANTS,
        "Registration_InHouseLobbyists_Export.csv": _INHOUSE,
        "Registration_SubjectMatterDetails_Export.csv": _REG_TOPICS,
        "Registration_BCPublicAgency_Export.csv": _REG_AGENCY,
        "BC_Public_Agencies_Export.csv": _AGENCIES,
        "Subject_Matters_Export.csv": _SUBJECTS,
        "Intended_Outcomes_Export.csv": _OUTCOMES,
        "Registration_Gifts_Export.csv": _GIFTS,
        "Registration_CodeOfConducts_Export.csv": _CONDUCT,
        "Registration_Beneficiaries_Export.csv": _BENEFICIARIES,
        "Registration_Target_Contacts_Export.csv": _CONTACTS,
        "Registration_PublicOffice_Export.csv": _PUBLIC_OFFICE,
        **(extra or {}),
    }
    if drop:
        members.pop(drop)
    return _zip(members)


_LAR_HEADER = [
    "LAR_ID", "CLIENT_ORG_NUM", "CLIENT_ORG_NAME", "FILER_NUM", "FILER_LAST_NAME",
    "FILER_FIRST_NAME", "MEETING_DATE", "ARRANGE_MEETING", "REG_TYPE", "SUBMISSION_DATE",
    "POSTED_DATE", "PREVIOUS_VERSION_LAR_ID", "LOBBYIST_ID", "IH_LOBBYIST_LAST_NAME",
    "IH_LOBBYIST_FIRST_NAME", "COALITION_MEMBER_NAME",
]  # fmt: skip
_LAR_PRIMARY = _csv(
    _LAR_HEADER,
    [
        {"LAR_ID": "LAR-10", "CLIENT_ORG_NUM": "3260", "CLIENT_ORG_NAME": "Council of Construction",
         "FILER_NUM": "6417", "FILER_LAST_NAME": "Baspaly", "FILER_FIRST_NAME": "Dave",
         "MEETING_DATE": "2020-05-12", "ARRANGE_MEETING": "N", "REG_TYPE": "Cons",
         "SUBMISSION_DATE": "2020-05-14", "POSTED_DATE": "2020-05-14"},
        # One row per in-house lobbyist for the same report.
        {"LAR_ID": "LAR-100", "CLIENT_ORG_NUM": "1101", "CLIENT_ORG_NAME": "Bear Viewing Association",
         "FILER_NUM": "1748", "FILER_LAST_NAME": "MacRae", "FILER_FIRST_NAME": "Katherine",
         "MEETING_DATE": "2025-06-04", "ARRANGE_MEETING": "N", "REG_TYPE": "Org",
         "SUBMISSION_DATE": "2025-07-01", "POSTED_DATE": "2025-07-01", "LOBBYIST_ID": "L-1",
         "IH_LOBBYIST_LAST_NAME": "MacRae", "IH_LOBBYIST_FIRST_NAME": "Katherine",
         "COALITION_MEMBER_NAME": "Guide Outfitters"},
        {"LAR_ID": "LAR-100", "CLIENT_ORG_NUM": "1101", "CLIENT_ORG_NAME": "Bear Viewing Association",
         "FILER_NUM": "1748", "FILER_LAST_NAME": "MacRae", "FILER_FIRST_NAME": "Katherine",
         "MEETING_DATE": "2025-06-04", "ARRANGE_MEETING": "N", "REG_TYPE": "Org",
         "SUBMISSION_DATE": "2025-07-01", "POSTED_DATE": "2025-07-01", "LOBBYIST_ID": "L-2",
         "IH_LOBBYIST_LAST_NAME": "Chen", "IH_LOBBYIST_FIRST_NAME": "Li",
         "COALITION_MEMBER_NAME": "Guide Outfitters"},
        {"LAR_ID": "LAR-200", "CLIENT_ORG_NUM": "443", "CLIENT_ORG_NAME": "BC Dental Association",
         "FILER_NUM": "9997", "FILER_LAST_NAME": "Mathiesen Newcomb", "FILER_FIRST_NAME": "Quinn",
         "MEETING_DATE": "2025-07-15", "ARRANGE_MEETING": "Y", "REG_TYPE": "Org",
         "SUBMISSION_DATE": "2025-08-01", "POSTED_DATE": "2025-08-02",
         "PREVIOUS_VERSION_LAR_ID": "LAR-199", "LOBBYIST_ID": "L-20",
         "IH_LOBBYIST_LAST_NAME": "Mathiesen Newcomb", "IH_LOBBYIST_FIRST_NAME": "Quinn"},
    ],
)  # fmt: skip
_LAR_SPOH = _csv(
    ["LAR_ID", "SPOH_LAST_NAME", "SPOH_FIRST_NAME", "SPOH_TITLE", "BRANCH", "BC_PUBLIC_AGENCY"],
    [
        {"LAR_ID": "LAR-10", "SPOH_LAST_NAME": "Snoddon", "SPOH_FIRST_NAME": "Michael",
         "SPOH_TITLE": "Senior Policy Advisor", "BRANCH": "", "BC_PUBLIC_AGENCY": "Forests"},
        {"LAR_ID": "LAR-100", "SPOH_LAST_NAME": "Hughes", "SPOH_FIRST_NAME": "Trevor",
         "SPOH_TITLE": "Deputy Minister", "BRANCH": "Wildlife", "BC_PUBLIC_AGENCY": "Forests"},
        {"LAR_ID": "LAR-100", "SPOH_LAST_NAME": "Eby", "SPOH_FIRST_NAME": "David",
         "SPOH_TITLE": "Premier", "BRANCH": "null", "BC_PUBLIC_AGENCY": "Office of the Premier"},
        {"LAR_ID": "LAR-200", "SPOH_LAST_NAME": "Dix", "SPOH_FIRST_NAME": "Adrian",
         "SPOH_TITLE": "Minister", "BRANCH": "", "BC_PUBLIC_AGENCY": "Health"},
        {"LAR_ID": "LAR-200", "SPOH_LAST_NAME": "Dix", "SPOH_FIRST_NAME": "Adrian",
         "SPOH_TITLE": "Minister", "BRANCH": "", "BC_PUBLIC_AGENCY": "Health"},
    ],
)  # fmt: skip
_LAR_TOPICS = _csv(
    ["LAR_ID", "INTENDED_OUTCOME_IDS", "TOPIC_OF_LOBBYING", "SUBJECT_MATTER_IDS"],
    [
        {"LAR_ID": "LAR-10", "INTENDED_OUTCOME_IDS": "BC-04", "TOPIC_OF_LOBBYING": "Timber lots",
         "SUBJECT_MATTER_IDS": "SM-15"},
        {"LAR_ID": "LAR-100", "INTENDED_OUTCOME_IDS": "BC-03, BC-04",
         "TOPIC_OF_LOBBYING": "Commercial bear viewing licences and wildlife policy",
         "SUBJECT_MATTER_IDS": "SM-15, SM-6"},
        {"LAR_ID": "LAR-200", "INTENDED_OUTCOME_IDS": "BC-03",
         "TOPIC_OF_LOBBYING": "Oral health regulatory body", "SUBJECT_MATTER_IDS": "SM-18"},
    ],
)  # fmt: skip


def _activity_zip(extra: dict[str, bytes] | None = None) -> bytes:
    return _zip(
        {
            "LAR_Primary_Export.csv": _LAR_PRIMARY,
            "LAR_SPOH_Export.csv": _LAR_SPOH,
            "LAR_SubjectMatterDetails_Export.csv": _LAR_TOPICS,
            "Subject_Matters_Export.csv": _SUBJECTS,
            "Intended_Outcomes_Export.csv": _OUTCOMES,
            **(extra or {}),
        }
    )


def _mock_registrations(httpx_mock, body: bytes | None = None) -> None:
    httpx_mock.add_response(url=_REG_URL, content=body or _registration_zip())


def _mock_activity(httpx_mock, body: bytes | None = None) -> None:
    httpx_mock.add_response(url=_LAR_URL, content=body or _activity_zip())


# ---------------------------------------------------------- registrations


async def test_only_current_versions_are_registrations(httpx_mock):
    _mock_registrations(httpx_mock)
    result = await client.search_registrations()
    numbers = sorted(r.registration_number for r in result.registrations)
    # R-1 (version 1) was replaced by R-2, so it is not listed.
    assert numbers == ["1846-6757-2", "500-77-3", "9997-443-56"]
    assert result.total_matched == 3
    assert result.by_status == {"active": 2, "ended": 1}
    assert result.by_kind == {"consultant": 1, "in_house": 2}
    assert "3 of 4 versions" in result.note
    assert result.provenance.as_of is not None
    assert result.provenance.as_of.date() == date(2026, 9, 20)
    assert constants.ATTRIBUTION in (result.provenance.licence or "")
    assert "registrar" not in (result.provenance.limits or "").lower()
    assert result.attribution == constants.ATTRIBUTION


async def test_registration_fields_and_chain_start(httpx_mock):
    _mock_registrations(httpx_mock)
    result = await client.search_registrations(client="athiana")
    reg = result.registrations[0]
    assert reg.registration_id == "R-2"
    # The registration began with version 1, not with the current version.
    assert reg.first_registered == date(2021, 2, 1)
    assert reg.version_start == date(2026, 3, 1)
    assert reg.status == "active" and reg.ended is None
    assert reg.kind == "consultant" and reg.legislation == "lta"
    assert reg.firm == "Moonen & Associates" and reg.filer == "John Moonen"
    assert reg.lobbyists == ["John Moonen", "Ann Smith"]
    assert reg.agencies == ["Forests"]
    assert reg.arranges_meetings is False
    assert reg.topics[0].subject_matters == ["Forestry"]
    assert reg.topics[0].intended_outcomes == ["Development of any program or policy"]


async def test_absent_values_and_duplicate_topics(httpx_mock):
    _mock_registrations(httpx_mock)
    result = await client.search_registrations(client="dental")
    reg = result.registrations[0]
    assert reg.arranges_meetings is None  # the text "null"
    assert reg.firm is None and reg.ended is None
    assert reg.filer_title == "Chief Executive Officer"
    assert reg.lobbyist_count == 2
    # The same topic filed under two detail ids is one topic.
    assert reg.topic_count == 1
    assert reg.topics[0].intended_outcomes == [
        "Development or enactment of any regulation",
        "Development of any program or policy",
    ]
    # An agency id missing from the vocabulary keeps its id.
    assert reg.agencies == [
        "Office of the Premier",
        "Member(s) of the BC Legislative Assembly",
        "GI-99999",
    ]


async def test_registration_filters(httpx_mock):
    _mock_registrations(httpx_mock)
    ids = lambda r: [x.registration_id for x in r.registrations]
    assert ids(await client.search_registrations(lobbyist="ann smith")) == ["R-2"]
    # Both words must belong to one lobbyist: Ann is not Moonen.
    assert ids(await client.search_registrations(lobbyist="ann moonen")) == []
    assert ids(await client.search_registrations(firm="moonen")) == ["R-2"]
    assert ids(await client.search_registrations(subject_matter="health")) == ["R-3"]
    assert sorted(ids(await client.search_registrations(subject_matter="forest"))) == ["R-2", "R-4"]
    assert ids(await client.search_registrations(agency="premier")) == ["R-3"]
    assert ids(await client.search_registrations(query="anesthesia")) == ["R-3"]
    assert ids(await client.search_registrations(kind="consultant")) == ["R-2"]
    assert ids(await client.search_registrations(status="ended")) == ["R-4"]
    # Accents fold in both directions.
    assert ids(await client.search_registrations(client="societe forestiere")) == ["R-4"]
    # A client number works as well as a name.
    assert ids(await client.search_registrations(client="443")) == ["R-3"]
    # Active registrations come first, newest version first.
    assert ids(await client.search_registrations()) == ["R-3", "R-2", "R-4"]


async def test_registration_period_overlap(httpx_mock):
    _mock_registrations(httpx_mock)
    ids = lambda r: sorted(x.registration_id for x in r.registrations)
    assert ids(await client.search_registrations(date_from="2018-01-01", date_to="2018-12-31")) == [
        "R-4"
    ]
    assert (
        ids(await client.search_registrations(date_from="2020-01-01", date_to="2020-12-31")) == []
    )
    assert ids(await client.search_registrations(date_from="2025-01-01", date_to="2025-12-31")) == [
        "R-2"
    ]
    assert ids(await client.search_registrations(date_from="2026-09-20")) == ["R-2", "R-3"]
    with pytest.raises(InvalidInput):
        await client.search_registrations(date_from="last year")
    with pytest.raises(InvalidInput, match="after date_to"):
        await client.search_registrations(date_from="2025-12-31", date_to="2025-01-01")
    with pytest.raises(InvalidInput, match="after date_to"):
        await client.search_activity_reports(date_from="2025-12-31", date_to="2025-01-01")


async def test_search_truncates_topics_but_get_returns_all(httpx_mock):
    long_topic = "x" * 900
    topics = _csv(
        ["REG_ID", "INTENDED_OUTCOME_IDS", "SUBJECT_MATTER_DETAIL_ID", "TOPIC_OF_LOBBYING", "SUBJECT_MATTER_IDS"],
        [
            {"REG_ID": "R-3", "INTENDED_OUTCOME_IDS": "BC-03", "SUBJECT_MATTER_DETAIL_ID": str(i),
             "TOPIC_OF_LOBBYING": f"{i} {long_topic}", "SUBJECT_MATTER_IDS": "SM-18"}
            for i in range(8)
        ],
    )  # fmt: skip
    body = _registration_zip({"Registration_SubjectMatterDetails_Export.csv": topics})
    _mock_registrations(httpx_mock, body)
    listed = await client.search_registrations(client="dental")
    reg = listed.registrations[0]
    assert reg.topic_count == 8 and len(reg.topics) == constants.SEARCH_TOPICS_SHOWN
    assert reg.topics[0].topic.endswith("...") and len(reg.topics[0].topic) < 400
    detail = await client.get_registration("9997-443-56")
    assert len(detail.registrations[0].topics) == 8
    assert detail.registrations[0].topics[0].topic == f"0 {long_topic}"


async def test_get_registration_by_id_number_and_pair(httpx_mock):
    _mock_registrations(httpx_mock)
    by_number = await client.get_registration("9997-443-56")
    assert by_number.registrations[0].registration_id == "R-3"
    # An older version's id and number resolve to the current version.
    assert (await client.get_registration("r-1")).registrations[0].registration_id == "R-2"
    assert (await client.get_registration("1846-6757-1")).registrations[
        0
    ].registration_number == "1846-6757-2"
    assert (await client.get_registration("1846-6757")).registrations[0].registration_id == "R-2"
    french = await client.get_registration("R-3", lang="fr")
    assert french.registrations[0].kind_label == "Inscription d'organisation (interne)"
    assert french.registrations[0].status_label == "Active"
    assert "Exclus" in french.omitted
    with pytest.raises(NotFound):
        await client.get_registration("1-2-3")
    with pytest.raises(NotFound):
        await client.get_registration("R-404")
    with pytest.raises(InvalidInput):
        await client.get_registration("dental")
    with pytest.raises(InvalidInput):
        await client.get_registration("  ")


async def test_unknown_subject_matter_is_rejected(httpx_mock):
    _mock_registrations(httpx_mock)
    with pytest.raises(InvalidInput, match="subject matter"):
        await client.search_registrations(subject_matter="astrology")
    with pytest.raises(InvalidInput):
        await client.search_registrations(limit=0)
    with pytest.raises(InvalidInput):
        await client.search_registrations(status="pending")  # type: ignore[arg-type]
    with pytest.raises(InvalidInput):
        await client.search_registrations(kind="lawyer")


async def test_personal_fields_never_reach_results(httpx_mock):
    _mock_registrations(httpx_mock)
    _mock_activity(httpx_mock)
    outputs = [
        await client.search_registrations(limit=200),
        await client.get_registration("R-2"),
        await client.get_registration("R-3"),
        await client.search_activity_reports(limit=200),
        await client.summarize_activity("office_holder"),
        await client.list_codes("ministries"),
    ]
    text = json.dumps([o.model_dump(mode="json") for o in outputs])
    for secret in _PERSONAL:
        assert secret not in text, secret
    # Address, phone and contribution fields do not exist on the models at all.
    fields = set(client.OrlRegistration.model_fields)
    assert not {f for f in fields if "address" in f or "phone" in f or "contribution" in f}
    assert "Left out" in outputs[0].omitted


# --------------------------------------------------------------- activity


async def test_one_report_per_lar_with_all_lobbyists(httpx_mock):
    _mock_activity(httpx_mock)
    result = await client.search_activity_reports()
    assert result.total_matched == 3
    # Newest meeting first.
    assert [r.report_id for r in result.reports] == ["LAR-200", "LAR-100", "LAR-10"]
    assert result.first_meeting == date(2020, 5, 12) and result.last_meeting == date(2025, 7, 15)
    bear = result.reports[1]
    assert bear.lobbyists == ["Katherine MacRae", "Li Chen"]
    assert bear.coalition_members == ["Guide Outfitters"]
    assert bear.registration_kind == "in_house"
    assert [(h.name, h.title, h.branch, h.agency) for h in bear.office_holders] == [
        ("Trevor Hughes", "Deputy Minister", "Wildlife", "Forests"),
        ("David Eby", "Premier", None, "Office of the Premier"),
    ]
    assert bear.topics[0].subject_matters == ["Forestry", "Consumer Issues"]
    # An empty BRANCH is absent; a repeated office holder is listed once.
    health = result.reports[0]
    assert health.arranged_meeting is True
    assert [(h.name, h.branch) for h in health.office_holders] == [("Adrian Dix", None)]
    consultant = result.reports[2]
    assert consultant.registration_kind == "consultant"
    assert consultant.filer == "Dave Baspaly" and consultant.lobbyists == []


async def test_activity_filters(httpx_mock):
    _mock_activity(httpx_mock)
    ids = lambda r: [x.report_id for x in r.reports]
    assert ids(await client.search_activity_reports(office_holder="deputy minister")) == ["LAR-100"]
    assert ids(await client.search_activity_reports(office_holder="eby")) == ["LAR-100"]
    assert ids(await client.search_activity_reports(agency="health")) == ["LAR-200"]
    assert ids(await client.search_activity_reports(lobbyist="li chen")) == ["LAR-100"]
    # The consultant filer counts as a lobbyist on a consultant report.
    assert ids(await client.search_activity_reports(lobbyist="baspaly")) == ["LAR-10"]
    assert ids(await client.search_activity_reports(client="3260")) == ["LAR-10"]
    assert ids(await client.search_activity_reports(subject_matter="consumer")) == ["LAR-100"]
    assert sorted(ids(await client.search_activity_reports(subject_matter="forestry"))) == [
        "LAR-10",
        "LAR-100",
    ]
    assert ids(await client.search_activity_reports(query="oral health")) == ["LAR-200"]
    assert ids(await client.search_activity_reports(kind="consultant")) == ["LAR-10"]
    assert ids(await client.search_activity_reports(arranged_only=True)) == ["LAR-200"]
    assert ids(await client.search_activity_reports(date_from="2025-07-01")) == ["LAR-200"]
    assert ids(await client.search_activity_reports(date_to="2020-12-31")) == ["LAR-10"]
    assert ids(await client.search_activity_reports(limit=1)) == ["LAR-200"]
    with pytest.raises(InvalidInput):
        await client.search_activity_reports(date_to="2025/07/01")
    with pytest.raises(InvalidInput):
        await client.search_activity_reports(limit=500)


async def test_summaries_count_distinct_reports(httpx_mock):
    _mock_activity(httpx_mock)
    ministries = await client.summarize_activity("ministry")
    assert ministries.total_reports == 3 and ministries.groups_total == 3
    assert {r.key: r.reports for r in ministries.rows} == {
        "Forests": 2,
        "Office of the Premier": 1,
        "Health": 1,
    }
    assert ministries.rows[0].key == "Forests"
    assert ministries.rows[0].first_meeting == date(2020, 5, 12)
    # A report naming two subjects counts once under each.
    subjects = await client.summarize_activity("subject_matter")
    assert {r.key: r.reports for r in subjects.rows} == {
        "Forestry": 2,
        "Consumer Issues": 1,
        "Health": 1,
    }
    years = await client.summarize_activity("year")
    assert [(r.key, r.reports) for r in years.rows] == [("2020", 1), ("2025", 2)]
    months = await client.summarize_activity("month", top=2)
    assert [r.key for r in months.rows] == ["2025-06", "2025-07"]  # latest periods, oldest first
    # The cut is stated, since `top` means "latest", not "busiest", for periods.
    assert f"2 most recent of {months.groups_total} periods" in months.note
    assert "not the busiest" in months.note
    assert "Forests" not in ministries.note and "most recent" not in ministries.note
    months_fr = await client.summarize_activity("month", top=2, lang="fr")
    assert "pas les plus chargées" in months_fr.note
    holders = await client.summarize_activity("office_holder", agency="forests")
    assert {r.key for r in holders.rows} >= {"Trevor Hughes (Forests)", "Michael Snoddon (Forests)"}
    people = await client.summarize_activity("lobbyist")
    assert {r.key: r.reports for r in people.rows}["Dave Baspaly"] == 1
    clients = await client.summarize_activity("client", date_from="2025-01-01", top=1)
    assert clients.groups_total == 2 and len(clients.rows) == 1
    with pytest.raises(InvalidInput):
        await client.summarize_activity("weather")  # type: ignore[arg-type]
    with pytest.raises(InvalidInput):
        await client.summarize_activity("client", top=0)


async def test_list_codes(httpx_mock):
    _mock_activity(httpx_mock)
    subjects = await client.list_codes("subject_matters", query="health")
    assert [(c.code, c.name) for c in subjects.codes] == [("SM-18", "Health")]
    outcomes = await client.list_codes("intended_outcomes")
    assert outcomes.total == 3 and outcomes.codes[0].code is not None
    ministries = await client.list_codes("ministries")
    assert [(c.name, c.reports) for c in ministries.codes] == [
        ("Forests", 2),
        ("Health", 1),
        ("Office of the Premier", 1),
    ]
    with pytest.raises(InvalidInput):
        await client.list_codes("lobbyists")  # type: ignore[arg-type]


# ---------------------------------------------------------- failure modes


async def test_html_page_instead_of_zip_is_an_upstream_error(httpx_mock):
    # An expired session or maintenance page answers 200 with HTML.
    httpx_mock.add_response(url=_LAR_URL, content=b"<html><body>Sign In</body></html>")
    with pytest.raises(UpstreamError, match="did not return a ZIP"):
        await client.search_activity_reports()
    # The failure is not cached: a later good answer works.
    _mock_activity(httpx_mock)
    assert (await client.search_activity_reports()).total_matched == 3


async def test_missing_file_is_not_found(httpx_mock):
    httpx_mock.add_response(url=_LAR_URL, status_code=404)
    with pytest.raises(NotFound):
        await client.search_activity_reports()


async def test_layout_changes_name_the_file_and_column(httpx_mock):
    broken = _csv(["LAR_ID", "SPOH_LAST_NAME"], [{"LAR_ID": "LAR-1", "SPOH_LAST_NAME": "X"}])
    _mock_activity(httpx_mock, _activity_zip({"LAR_SPOH_Export.csv": broken}))
    with pytest.raises(UpstreamError, match=r"LAR_SPOH_Export.csv has no column .*SPOH_TITLE"):
        await client.search_activity_reports()


async def test_missing_member_is_an_upstream_error(httpx_mock):
    _mock_registrations(httpx_mock, _registration_zip(drop="BC_Public_Agencies_Export.csv"))
    with pytest.raises(UpstreamError, match="BC_Public_Agencies_Export.csv"):
        await client.search_registrations()


async def test_corrupt_zip_is_an_upstream_error(httpx_mock):
    httpx_mock.add_response(url=_REG_URL, content=b"PK\x03\x04 not really a zip")
    with pytest.raises(UpstreamError, match="not a readable ZIP"):
        await client.search_registrations()


async def test_results_are_cached_between_calls(httpx_mock):
    _mock_activity(httpx_mock)
    first = await client.search_activity_reports()
    second = await client.summarize_activity("year")
    assert first.provenance.cached is False
    assert second.provenance.cached is True
    assert len(httpx_mock.get_requests(url=re.compile(re.escape(constants.DOWNLOAD_URL)))) == 1
