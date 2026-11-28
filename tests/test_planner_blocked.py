"""plan_query and search_tools know which StatCan paths answered with the bot check lately.

On 2026-11-18 StatCan answered WDS and challenged SDMX, the CIMT trade API and the catalogue
pages on the same host, so the breaker (one state per host) cannot say which tools are down.
shared/path_health.py remembers the challenges real calls and statcan_check_access saw; the
planner and search_tools mark the tools that have no other route on such a path and list the
working route first. Offline: no request is made and none is probed.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any

import pytest
from fastmcp import Client

from maplestats_mcp.catalogue import read_catalogue
from maplestats_mcp.modules.planner import blocked, client
from maplestats_mcp.modules.planner.schemas import (
    BlockedStep,
    PlaceMatch,
    QueryPlan,
    StepOut,
    TopicMatch,
)
from maplestats_mcp.modules.statcan.access import client as access
from maplestats_mcp.modules.statcan.access.schemas import EndpointStatus
from maplestats_mcp.server import mcp
from maplestats_mcp.shared import path_health
from maplestats_mcp.shared.envelope import make_provenance
from maplestats_mcp.shared.http import api_get
from maplestats_mcp.shared.usage import public_snapshot
from tests.discovery_benchmark.runner import load_queries

WWW150 = "www150.statcan.gc.ca"
CIMT_PATH = "/t1/cimt/rest/getPeriods"
PAGES_PATH = "/n1/en/type/data"
TRADE = "Canada merchandise exports by HS commodity and trading partner"
REFERENCE = "What does StatCan define as the unemployment rate? the reference definition"


@pytest.fixture
def now(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """path_health's clock, set by the test: a one-item list holding the time."""
    time = [1000.0]
    monkeypatch.setattr(path_health, "_clock", lambda: time[0])
    return time


def _challenge(*paths: str) -> None:
    for path in paths:
        path_health.record_challenge(WWW150, path)


def _plan(question: str, lang: str = "en") -> QueryPlan:
    return client.plan(question, lang)


def _dump(question: str, lang: str = "en") -> str:
    """A plan as JSON text, less the query time that differs on every call."""
    text = _plan(question, lang).model_dump_json()
    return re.sub(r'"queried_at":"[^"]*"', '"queried_at":""', text)


def _json(plan: QueryPlan) -> dict[str, Any]:
    return json.loads(plan.model_dump_json())


def _step_lists(plan: dict[str, Any]) -> list[list[dict[str, Any]]]:
    return [
        *(topic["steps"] for topic in plan["topics"]),
        *(place["steps"] for place in plan["places"]),
        plan["fallback_steps"],
    ]


# 1. What path_health remembers ----


def test_a_path_is_challenged_for_fifteen_minutes_unless_it_answers(now):
    _challenge(CIMT_PATH)
    assert path_health.challenged_now() == {"cimt"}
    now[0] += path_health.TTL_SECONDS
    assert path_health.challenged_now() == {"cimt"}
    now[0] += 1
    assert path_health.challenged_now() == frozenset()
    # An answer after a challenge clears it at once; a later challenge counts again.
    _challenge(CIMT_PATH)
    path_health.record_answer(WWW150, CIMT_PATH)
    assert path_health.challenged_now() == frozenset()
    now[0] += 1
    _challenge(CIMT_PATH)
    assert path_health.challenged_now() == {"cimt"}


@pytest.mark.parametrize(
    ("host", "path", "key"),
    [
        (WWW150, "/t1/wds/rest/getCubeMetadata", "wds"),
        (WWW150, "/t1/wds/sdmx/statcan/rest/data/DF_1/1", "sdmx"),
        (WWW150, "/t1/cimt/rest/getPeriods", "cimt"),
        (WWW150, "/n1/rss/dai-quo/0-eng.atom", "rss"),
        (WWW150, "/n1/tbl/csv/36100104-eng.zip", "files"),
        (WWW150, "/delta/20261002.zip", "files"),
        (WWW150, "/n1/delta/20261002.zip", "files"),
        (WWW150, "/n1/dai-quo/ssi/homepage/ind-hp.json", "daily"),
        (WWW150, "/n1/en/type/data", "pages"),
        (WWW150, "/n1/fr/catalogue/71M0001X", "pages"),
        (WWW150, "/n1/pub/71-607-x/2021004/exp-eng.htm", "pub"),
        (WWW150, "/n1/pub/71m0001x/2021001/2026-10-CSV.zip", "pub_zip"),
        ("www12.statcan.gc.ca", "/census-recensement/2021/dp-pd/prof/index.cfm", "census"),
        (WWW150, "/somewhere/else", None),
        ("api.statcan.gc.ca", "/census-recensement/profile/", None),
        ("example.org", "/t1/cimt/", None),
    ],
)
def test_each_path_belongs_to_the_group_challenge_notes_describes(host, path, key):
    assert path_health.path_key(host, path) == key


def test_a_host_this_does_not_follow_records_nothing():
    path_health.record_challenge("example.org", "/t1/cimt/rest/getPeriods")
    path_health.record_challenge("api.statcan.gc.ca", "/rdaas/search")
    assert path_health.challenged_now() == frozenset()
    assert path_health._seen == {}


# 2. What feeds it: real calls and statcan_check_access ----


async def test_a_challenged_call_notes_its_path_and_an_answer_clears_it(
    httpx_mock, statcan_security_check
):
    url = f"https://{WWW150}{CIMT_PATH}"
    httpx_mock.add_response(url=url, **statcan_security_check)
    with pytest.raises(Exception, match="challenge"):
        await api_get(url)
    assert path_health.challenged_now() == {"cimt"}
    # WDS answering on the same host does not clear the CIMT path.
    wds = f"https://{WWW150}/t1/wds/rest/getCodeSets"
    httpx_mock.add_response(url=wds, json={})
    await api_get(wds)
    assert path_health.challenged_now() == {"cimt"}
    httpx_mock.add_response(url=url, json={})
    await api_get(url)
    assert path_health.challenged_now() == frozenset()


async def test_a_challenge_without_its_header_is_noted_from_the_page(
    httpx_mock, statcan_security_check
):
    headers = {k: v for k, v in statcan_security_check["headers"].items() if k != "Cf-Mitigated"}
    url = f"https://{WWW150}/n1/en/type/data?text=x"
    httpx_mock.add_response(url=url, **{**statcan_security_check, "headers": headers})
    with pytest.raises(Exception, match="challenge"):
        await api_get(url)
    assert path_health.challenged_now() == {"pages"}


def _status(url: str, status: str) -> EndpointStatus:
    return EndpointStatus(
        key="k",
        service="s",
        url=url,
        status=status,  # type: ignore[arg-type]
        used_by="t",
        checked_at=datetime.now(UTC),
    )


def test_a_fresh_check_access_report_feeds_the_paths():
    access.feed_path_health(
        [
            _status(f"https://{WWW150}/t1/wds/rest/getCubeMetadata", "answers"),
            _status(f"https://{WWW150}/t1/cimt/rest/getPeriods", "blocked"),
            _status(f"https://{WWW150}/n1/en/type/data?text=unemployment", "blocked"),
            _status(f"https://{WWW150}/t1/wds/sdmx/statcan/rest/data/DF_1", "error"),
            _status("https://api.statcan.gc.ca/rdaas/search/classifications?q=NAICS", "blocked"),
        ]
    )
    assert path_health.challenged_now() == {"cimt", "pages"}


async def test_check_access_feeds_only_a_report_it_just_made(httpx_mock, cloudflare_challenge):
    for endpoint in access.constants.ENDPOINTS:
        blocked_key = endpoint.key in ("cimt", "catalogue_search")
        if blocked_key:
            httpx_mock.add_response(url=endpoint.url, **cloudflare_challenge)
        elif endpoint.post_json is not None:
            httpx_mock.add_response(url=endpoint.url, json={})
        else:
            httpx_mock.add_response(url=endpoint.url, status_code=206, content=b"PK\x03\x04")
    first = await access.check_access()
    assert path_health.challenged_now() == {"cimt", "pages"}
    # The second call is the cached report: it does not renew the paths' age.
    path_health.reset()
    second = await access.check_access()
    assert second.provenance.cached and not first.provenance.cached
    assert path_health.challenged_now() == frozenset()


# 3. plan_query ----


QUESTIONS = [(q.query, q.lang) for q in load_queries()]


def test_with_no_path_challenged_a_plan_is_exactly_what_it_was(monkeypatch):
    """Over every benchmark question, in the question's own language."""
    after = [_dump(question, lang) for question, lang in QUESTIONS]
    monkeypatch.setattr(blocked, "mark_blocked", lambda plan, french: plan)
    before = [_dump(question, lang) for question, lang in QUESTIONS]
    assert after == before
    assert not any('"blocked"' in text for text in after)


def test_a_challenge_on_a_path_no_tool_depends_on_changes_nothing():
    healthy = [_dump(question, lang) for question, lang in QUESTIONS]
    # SDMX falls back to WDS on its own, The Daily's feed to its archive, files to a script.
    _challenge("/t1/wds/sdmx/x", "/n1/rss/dai-quo/0-eng.atom", "/n1/tbl/csv/x.zip")
    path_health.record_challenge("www12.statcan.gc.ca", "/census-recensement/")
    assert [_dump(q, lang) for q, lang in QUESTIONS] == healthy


def test_the_output_schema_is_the_same_as_before_the_field_existed():
    assert "blocked" not in StepOut.model_json_schema()["properties"]
    assert StepOut(tool="a", purpose="b").model_dump_json() == (
        '{"tool":"a","purpose":"b","call":null}'
    )


def _topic_with(plan: dict[str, Any], tool: str) -> dict[str, Any]:
    return next(t for t in plan["topics"] if any(s["tool"] == tool for s in t["steps"]))


def test_a_challenged_cimt_path_marks_its_steps_and_lists_the_working_route_first():
    healthy = _json(_plan(TRADE))
    cimt = [
        s["tool"] for t in healthy["topics"] for s in t["steps"] if s["tool"].startswith("cimt_")
    ]
    assert cimt, "the trade question should plan CIMT steps"
    _challenge(CIMT_PATH)
    plan = _json(_plan(TRADE))
    topic = _topic_with(plan, cimt[0])
    steps = topic["steps"]
    # The route first: the same data through WDS, labelled as that route, with its call.
    route = steps[0]
    assert route["tool"] == "wds_get_cube_metadata"
    assert route["call"] == '{"product_id":"12-10-0011-01"}'
    assert route["purpose"].startswith("WDS, as StatCan's CIMT API is blocked")
    assert "12-10-0011-01" in route["purpose"] and "no HS detail" in route["purpose"]
    # The blocked steps stay, last, marked, with a note and no call.
    stuck = [s for s in steps if s.get("blocked")]
    assert [s["tool"] for s in stuck] == [s["tool"] for s in steps[len(steps) - len(stuck) :]]
    assert {s["tool"] for s in stuck} >= set(cimt)
    for step in stuck:
        assert step["purpose"] == "blocked (StatCan's CIMT API): do not call"
        assert "call" not in step
    for step in steps:
        if not step.get("blocked"):
            assert "blocked" not in step and "call" in step
    # Nothing is dropped, and nothing else is reordered among the working steps.
    before = [s["tool"] for t in healthy["topics"] for s in t["steps"]]
    after = [s["tool"] for t in plan["topics"] for s in t["steps"]]
    assert set(before) <= set(after)
    assert not any(s["tool"].startswith("cimt_") for s in steps if not s.get("blocked"))


def test_the_french_plan_is_in_french():
    _challenge(CIMT_PATH)
    plan = _json(_plan("Exportations canadiennes par marchandise du SH et par partenaire", "fr"))
    steps = [s for t in plan["topics"] for s in t["steps"]]
    stuck = [s for s in steps if s.get("blocked")]
    route = next(s for s in steps if s["purpose"].startswith("WDS, l'API CICM de StatCan"))
    assert route["tool"] == "wds_get_cube_metadata" and "12-10-0011-01" in route["purpose"]
    assert stuck and all(
        s["purpose"] == "bloqué (l'API CICM de StatCan) : ne pas appeler" for s in stuck
    )
    assert "blocked" not in route["purpose"] and "do not call" not in json.dumps(plan)


def test_a_challenged_catalogue_path_marks_the_reference_steps():
    healthy = _json(_plan(REFERENCE))
    reference = [
        s["tool"]
        for t in healthy["topics"]
        for s in t["steps"]
        if s["tool"].startswith("statcan_reference_")
    ]
    if not reference:
        pytest.skip("this question plans no statcan_reference_ step")
    _challenge(PAGES_PATH)
    plan = _json(_plan(REFERENCE))
    stuck = [s for t in plan["topics"] for s in t["steps"] if s.get("blocked")]
    assert {s["tool"] for s in stuck} >= set(reference)
    assert all(s["purpose"] == "blocked (StatCan's catalogue pages): do not call" for s in stuck)


def _step(tool: str) -> StepOut:
    return StepOut(tool=tool, purpose=f"purpose of {tool}", call="{}")


def _handmade(topic: list[str], place: list[str], fallback: list[str]) -> QueryPlan:
    return QueryPlan(
        question="q",
        topics=[
            TopicMatch(
                topic="t", label="T", matched_terms=[], steps=[_step(x) for x in topic], caveats=[]
            )
        ],
        places=[PlaceMatch(place="Alberta", kind="province", steps=[_step(x) for x in place])],
        fallback_steps=[_step(x) for x in fallback],
        guidance=["g"],
        provenance=make_provenance(
            source="test", url="docs://catalogue", cached=False, schema_name="test"
        ),
    )


def _tools(steps: list[StepOut]) -> list[tuple[str, bool]]:
    return [(s.tool, isinstance(s, BlockedStep)) for s in steps]


def test_a_route_is_not_added_when_the_topic_already_has_that_tool():
    _challenge(PAGES_PATH)
    plan = blocked.mark_blocked(
        _handmade(
            ["statcan_reference_search_documents", "wds_search_cubes", "boc_search_series"], [], []
        ),
        french=False,
    )
    assert _tools(plan.topics[0].steps) == [
        ("wds_search_cubes", False),
        ("boc_search_series", False),
        ("statcan_reference_search_documents", True),
    ]
    assert plan.guidance == ["g"]


def test_the_route_goes_first_once_for_several_blocked_steps_of_one_path():
    _challenge(CIMT_PATH)
    plan = blocked.mark_blocked(
        _handmade(["cimt_get_trade", "wds_get_data_from_vectors", "cimt_get_periods"], [], []),
        french=False,
    )
    assert _tools(plan.topics[0].steps) == [
        ("wds_get_cube_metadata", False),
        ("wds_get_data_from_vectors", False),
        ("cimt_get_trade", True),
        ("cimt_get_periods", True),
    ]


def test_places_and_fallback_steps_are_marked_and_ordered_but_get_no_route():
    _challenge(CIMT_PATH, PAGES_PATH)
    plan = blocked.mark_blocked(
        _handmade(
            ["boc_search_series"],
            ["cimt_get_trade", "ab_economic_get_data"],
            ["statcan_pumf_search", "ckan_search_datasets"],
        ),
        french=False,
    )
    assert _tools(plan.places[0].steps) == [
        ("ab_economic_get_data", False),
        ("cimt_get_trade", True),
    ]
    assert _tools(plan.fallback_steps) == [
        ("ckan_search_datasets", False),
        ("statcan_pumf_search", True),
    ]
    assert _tools(plan.topics[0].steps) == [("boc_search_series", False)]


def test_a_path_two_dependencies_share_is_named_by_the_one_that_matches_the_tool():
    _challenge(PAGES_PATH)
    plan = blocked.mark_blocked(
        _handmade(["cimt_get_trade", "statcan_pumf_list_files"], [], []), False
    )
    # Only the pages path is challenged: the CIMT API's tools keep their place.
    assert _tools(plan.topics[0].steps)[0] == ("wds_search_cubes", False)
    assert ("cimt_get_trade", False) in _tools(plan.topics[0].steps)
    assert ("statcan_pumf_list_files", True) in _tools(plan.topics[0].steps)


def test_no_blocked_plan_drops_a_tool_or_grows_past_its_cap():
    healthy = {q: _dump(q, lang) for q, lang in QUESTIONS}
    _challenge(CIMT_PATH, PAGES_PATH)
    longest_growth = 0
    for question, lang in QUESTIONS:
        marked = _dump(question, lang)
        before = {s["tool"] for s in _steps_of(healthy[question])}
        after = {s["tool"] for s in _steps_of(marked)}
        assert before <= after, question
        longest_growth = max(longest_growth, len(marked) - len(healthy[question]))
    # The longest growth measured on 2026-11-18 was 168 characters, for one plan in 129.
    assert longest_growth <= 400


def _steps_of(text: str) -> list[dict[str, Any]]:
    return [step for steps in _step_lists(json.loads(text)) for step in steps]


def test_blocked_plans_are_no_longer_than_today_on_average():
    healthy = [len(_dump(q, lang)) for q, lang in QUESTIONS]
    _challenge(CIMT_PATH, PAGES_PATH)
    marked = [len(_dump(q, lang)) for q, lang in QUESTIONS]
    assert sum(marked) <= sum(healthy)
    assert marked != healthy


# 4. search_tools ----


async def _search(query: str, **arguments: Any) -> list[dict[str, Any]]:
    async with Client(mcp) as session:
        result = await session.call_tool("search_tools", {"query": query, **arguments})
    return json.loads(result.content[0].text)  # type: ignore[union-attr]


async def test_search_results_are_untouched_while_no_path_is_challenged():
    results = await _search(TRADE)
    assert not any("blocked" in result for result in results)


async def test_search_lists_blocked_tools_last_with_the_working_route():
    healthy = await _search(TRADE)
    assert any(r["name"].startswith("cimt_") for r in healthy)
    _challenge(CIMT_PATH)
    results = await _search(TRADE)
    # The same tools, so the same number of results.
    assert [r["name"] for r in sorted(results, key=lambda r: r["name"])] == sorted(
        r["name"] for r in healthy
    )
    flags = [bool(r.get("blocked")) for r in results]
    assert flags == sorted(flags), "a working tool follows a blocked one"
    stuck = [r for r in results if r.get("blocked")]
    assert stuck and all(r["name"].startswith("cimt_") for r in stuck)
    for result in stuck:
        assert result["description"].startswith("Blocked now (StatCan's CIMT API): do not call;")
        assert "wds_get_cube_metadata on 12-10-0011-01" in result["description"]
        assert "arguments" not in result


async def test_search_in_full_detail_marks_the_same_way():
    _challenge(CIMT_PATH)
    results = await _search(TRADE, detail="full")
    stuck = [r for r in results if r.get("blocked")]
    assert stuck and all("inputSchema" not in r for r in stuck)
    assert all("inputSchema" in r for r in results if not r.get("blocked"))


async def test_search_for_a_tool_on_another_path_is_untouched():
    healthy = await _search("Bank of Canada policy interest rate")
    _challenge(CIMT_PATH, PAGES_PATH)
    assert await _search("Bank of Canada policy interest rate") == healthy


async def test_blocked_search_results_are_no_longer_than_today_on_average():
    queries = [q.query for q in load_queries()]
    healthy = [len(json.dumps(await _search(q))) for q in queries]
    _challenge(CIMT_PATH, PAGES_PATH)
    marked = [len(json.dumps(await _search(q))) for q in queries]
    assert sum(marked) <= sum(healthy)
    assert marked != healthy


# 5. The dependencies are honest ----


def test_each_dependency_names_tools_that_exist_and_paths_they_use():
    catalogue = read_catalogue()
    assert catalogue is not None
    names = [t["name"] for module in catalogue.values() for t in module["tools"]]
    for dependency in path_health.DEPENDENCIES:
        for prefix in dependency.prefixes:
            assert any(name.startswith(prefix) for name in names), prefix
    for key in ROUTE_KEYS:
        assert key in {d.key for d in path_health.DEPENDENCIES}
        assert blocked.ROUTES[key].tool in names
        assert key in blocked.ROUTES_FR


ROUTE_KEYS = ("cimt", "pages")


def test_the_dependencies_match_the_paths_the_tools_read():
    from maplestats_mcp.modules.statcan.cimt import constants as cimt
    from maplestats_mcp.modules.statcan.pumf import constants as pumf
    from maplestats_mcp.modules.statcan.reference import constants as reference

    assert path_health.path_key(WWW150, cimt.BASE_URL.removeprefix(f"https://{WWW150}")) == "cimt"
    for template in (
        reference.BASE_URL_TEMPLATE,
        reference.CATALOGUE_URL_TEMPLATE,
        pumf.CATALOGUE_URL,
    ):
        path = template.removeprefix(f"https://{WWW150}").format(lang="en", path="x", number="y")
        assert path_health.path_key(WWW150, path) == "pages", template
    keys = {d.key: d for d in path_health.DEPENDENCIES}
    assert keys["cimt"].prefixes == ("cimt_",)
    assert "statcan_reference_" in keys["pages"].prefixes


def test_the_delta_file_url_the_tool_asks_for_is_in_the_files_group():
    from maplestats_mcp.modules.statcan.delta import archive, constants
    from maplestats_mcp.shared.http import breaker_key

    # The tool asks for /delta/{date}.zip, which redirects to /n1/delta/: the breaker must
    # key both as "files", not leave the first one on the bare host's key.
    for template in (constants.BASE_URL, archive.ARCHIVE_URL):
        path = template.removeprefix(f"https://{WWW150}").format(date="20261002")
        assert breaker_key(WWW150, path) == f"{WWW150}/files", template


# 6. /stats ----


def test_stats_lists_the_challenged_path_groups():
    assert public_snapshot()["upstreams"]["challenged_paths"] == []
    _challenge(PAGES_PATH, CIMT_PATH)
    snapshot = public_snapshot()["upstreams"]
    assert snapshot["challenged_paths"] == ["cimt", "pages"]
    # What was there before is untouched.
    assert set(snapshot) == {"breaker", "hosts", "challenged_paths"}
