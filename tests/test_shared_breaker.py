"""The per-host circuit breaker in shared/breaker.py, driven through the shared clients."""

from __future__ import annotations

import json

import httpx
import pytest
from fastmcp import Client
from mcp.types import TextResourceContents

from maplestats_mcp.server import mcp
from maplestats_mcp.shared import retrying
from maplestats_mcp.shared.breaker import (
    BREAKER,
    CircuitBreaker,
    CircuitOpen,
    one_call,
    render_status,
)
from maplestats_mcp.shared.errors import CloudflareChallenge, UpstreamUnavailable
from maplestats_mcp.shared.http import api_get, get_raw, new_client
from maplestats_mcp.shared.i18n import reset_call_lang, set_call_lang
from maplestats_mcp.shared.usage import UsageStats, public_snapshot

HOST = "www150.statcan.gc.ca"
URL = f"https://{HOST}/t1/wds/rest/getAllCubesListLite"


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> FakeClock:
    fake = FakeClock()
    monkeypatch.setattr(BREAKER, "_clock", fake)
    return fake


@pytest.fixture
def two_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    """Open after two failures, so each test needs few mocked calls."""
    monkeypatch.setenv("MAPLE_BREAKER_FAILURES", "2")
    monkeypatch.setenv("MAPLE_BREAKER_COOLDOWN_SECONDS", "60")
    monkeypatch.setenv("MAPLE_BREAKER_WINDOW_SECONDS", "300")


async def _open(httpx_mock) -> None:
    """Two failing calls: the second one's first failure opens the breaker, so its retry is refused."""
    await _fail_once(httpx_mock)
    httpx_mock.add_response(url=URL, status_code=503)
    with pytest.raises(CircuitOpen):
        await api_get(URL)


def _host(name: str = HOST) -> dict:
    return BREAKER.snapshot()["hosts"][name]


async def _fail_once(httpx_mock, status: int = 503) -> None:
    """One api_get call whose three attempts all fail."""
    for _ in range(3):
        httpx_mock.add_response(url=URL, status_code=status)
    with pytest.raises(httpx.HTTPStatusError):
        await api_get(URL)


async def test_opens_after_failures_and_refuses_without_sending(httpx_mock, two_failures, clock):
    await _open(httpx_mock)
    sent = len(httpx_mock.get_requests())
    with pytest.raises(CircuitOpen) as refused:
        await api_get(URL)
    assert len(httpx_mock.get_requests()) == sent
    assert isinstance(refused.value, UpstreamUnavailable)
    assert HOST in str(refused.value) and "Try again after" in str(refused.value)
    assert _host()["state"] == "open"
    assert _host()["refused"] == 2


async def test_retries_count_as_one_failure(httpx_mock, two_failures):
    await _fail_once(httpx_mock)
    assert _host()["state"] == "closed"
    assert _host()["errors"]["server_error"] == 1


async def test_timeouts_count_once_per_call(httpx_mock, two_failures):
    for _ in range(3):
        httpx_mock.add_exception(httpx.ReadTimeout("slow"), url=URL)
    with pytest.raises(httpx.ReadTimeout):
        await api_get(URL)
    assert _host()["errors"]["timeout"] == 1
    assert _host()["state"] == "closed"


async def test_get_with_retry_counts_once_and_skips_deterministic_statuses(
    httpx_mock, two_failures, monkeypatch
):
    async def no_sleep(seconds: float) -> None:
        return None

    monkeypatch.setattr(retrying.asyncio, "sleep", no_sleep)
    url = "https://www.statcan.gc.ca/en/survey"
    for _ in range(retrying.RETRY_ATTEMPTS):
        httpx_mock.add_response(url=url, status_code=502)
    async with new_client() as client:
        response = await retrying.get_with_retry(client, url)
    assert response.status_code == 502
    assert _host("www.statcan.gc.ca")["errors"]["server_error"] == 1

    # IMDB's unknown-survey 500 is an answer, not an outage.
    httpx_mock.add_response(url=url, status_code=500, is_reusable=True)
    async with new_client() as client:
        for _ in range(3):
            await retrying.get_with_retry(
                client, url, retry_statuses=retrying.RETRY_STATUSES - {500}
            )
    assert _host("www.statcan.gc.ca")["state"] == "closed"
    assert _host("www.statcan.gc.ca")["errors"]["server_error"] == 1


async def test_caller_errors_do_not_trip_it(httpx_mock, two_failures):
    httpx_mock.add_response(url=URL, status_code=404, is_reusable=True)
    for _ in range(5):
        with pytest.raises(httpx.HTTPStatusError):
            await api_get(URL)
    assert HOST not in BREAKER.snapshot()["hosts"]
    httpx_mock.reset()
    httpx_mock.add_response(url=URL, status_code=406, is_reusable=True)
    for _ in range(5):
        assert (await get_raw(URL)).status_code == 406
    assert HOST not in BREAKER.snapshot()["hosts"]


async def test_an_answer_resets_the_count(httpx_mock, two_failures):
    await _fail_once(httpx_mock)
    httpx_mock.add_response(url=URL, json={"ok": True})
    await api_get(URL)
    await _fail_once(httpx_mock)
    assert _host()["state"] == "closed"


async def test_old_failures_fall_out_of_the_window(httpx_mock, two_failures, clock):
    await _fail_once(httpx_mock)
    clock.now += 301
    await _fail_once(httpx_mock)
    assert _host()["state"] == "closed"


async def test_probe_after_cooldown_closes_on_success(httpx_mock, two_failures, clock):
    await _open(httpx_mock)
    clock.now += 61
    assert _host()["state"] == "half_open"
    httpx_mock.add_response(url=URL, json={"ok": True})
    assert await api_get(URL) == {"ok": True}
    assert _host()["state"] == "closed"


async def test_failed_probe_reopens_for_another_cooldown(httpx_mock, two_failures, clock):
    await _open(httpx_mock)
    clock.now += 61
    httpx_mock.add_response(url=URL, status_code=503)
    # The probe failed, so the retry inside the same call is refused.
    with pytest.raises(CircuitOpen):
        await api_get(URL)
    assert len(httpx_mock.get_requests()) == 5
    assert _host()["state"] == "open"
    assert _host()["times_opened"] == 2
    with pytest.raises(CircuitOpen):
        await api_get(URL)


def test_one_probe_at_a_time(monkeypatch, two_failures):
    breaker = CircuitBreaker(clock=FakeClock())
    with one_call():
        breaker.record_failure(HOST, "timeout")
    with one_call():
        breaker.record_failure(HOST, "timeout")
    breaker._clock.now += 61  # type: ignore[attr-defined]
    assert breaker.before_request(HOST) is True
    with pytest.raises(CircuitOpen):
        breaker.before_request(HOST)
    # A cancelled probe lets the next request probe instead.
    breaker.release(HOST, probe=True)
    assert breaker.before_request(HOST) is True


async def test_cloudflare_challenges_count(httpx_mock, two_failures, cloudflare_challenge):
    for _ in range(2):
        httpx_mock.add_response(url=URL, **cloudflare_challenge)
        with pytest.raises(CloudflareChallenge):
            await api_get(URL)
    assert _host()["errors"]["cloudflare"] == 2
    assert _host()["state"] == "open"


async def test_cloudflare_challenge_without_its_header_counts_once(
    httpx_mock, two_failures, cloudflare_challenge
):
    headers = {k: v for k, v in cloudflare_challenge["headers"].items() if k != "Cf-Mitigated"}
    httpx_mock.add_response(url=URL, **{**cloudflare_challenge, "headers": headers})
    with pytest.raises(CloudflareChallenge):
        await api_get(URL)
    assert _host()["errors"]["cloudflare"] == 1


async def test_turned_off_it_sends_every_request(httpx_mock, two_failures, monkeypatch):
    monkeypatch.setenv("MAPLE_BREAKER", "0")
    for _ in range(4):
        await _fail_once(httpx_mock)
    assert _host()["state"] == "closed"
    assert _host()["errors"]["server_error"] == 4
    assert "off" in render_status()


async def test_refusal_is_in_french_for_a_french_call(httpx_mock, two_failures):
    await _open(httpx_mock)
    token = set_call_lang("fr")
    try:
        with pytest.raises(CircuitOpen) as refused:
            await api_get(URL)
    finally:
        reset_call_lang(token)
    message = str(refused.value)
    assert "Réessayez après" in message and HOST in message
    assert "Try again" not in message


def test_addresses_are_not_tracked(two_failures):
    breaker = CircuitBreaker()
    for host in ("127.0.0.1", "::1", "localhost", "10.1.2.3"):
        breaker.record_failure(host, "network")
        breaker.record_failure(host, "network")
        breaker.before_request(host)
    assert breaker.snapshot()["hosts"] == {}


async def test_status_resource_lists_open_hosts(httpx_mock, two_failures):
    async with Client(mcp) as client:
        before = await client.read_resource("docs://status")
        await _open(httpx_mock)
        after = await client.read_resource("docs://status")
    assert isinstance(before[0], TextResourceContents)
    assert isinstance(after[0], TextResourceContents)
    assert "No host is paused" in before[0].text
    text = after[0].text
    assert f"- {HOST}: paused until" in text
    assert "suspendu jusqu'à" in text


async def test_stats_add_latency_and_upstream_health(httpx_mock, two_failures):
    await _fail_once(httpx_mock)
    snap = public_snapshot()
    assert snap["upstreams"]["breaker"]["failures_to_open"] == 2
    assert snap["upstreams"]["hosts"][HOST]["errors"]["server_error"] == 1
    assert "getAllCubesListLite" not in json.dumps(snap)


def test_latency_percentiles_per_tool():
    stats = UsageStats(("boc_get_observations",))
    for ms in range(1, 101):
        stats.record("boc_get_observations", True, ms / 1000)
    stats.record("boc_get_observations", False)
    latency = stats.snapshot()["latency_ms"]["boc_get_observations"]
    assert latency == {"p50_ms": 50, "p95_ms": 95, "samples": 100}


async def test_tool_calls_record_their_duration():
    from maplestats_mcp.shared.usage import STATS

    async with Client(mcp) as client:
        await client.call_tool("search_tools", {"query": "private words for latency"})
    snap = STATS.snapshot()
    assert snap["latency_ms"]["search_tools"]["samples"] >= 1
    assert "private words" not in json.dumps(snap)
