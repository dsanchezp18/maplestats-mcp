"""Tests on lines trimmed from CBSA's wait times files (2026-10-03)."""

from __future__ import annotations

from datetime import timedelta

import pytest

from maplestats_mcp.modules.cbsa import client, constants
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import InvalidInput, UpstreamError


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_module._caches.clear()
    yield


# The real files: ";; " separators, a trailing ";; " on every line, a BOM, CRLF-free.
_EN = (
    "﻿Customs Office;; Location;; Last updated;; Commercial Flow - Canada bound;; "
    "Commercial Flow - U.S. bound;; Travellers Flow - Canada bound;; Travellers Flow - U.S. "
    "bound;;\n"
    "St. Stephen;; St. Stephen, NB/Calais, ME;; 2026-10-03 13:54 ADT;; Not Applicable;; "
    "--;; 5 minutes;; --;; \n"
    "Peace Bridge;; Fort Erie, ON/Buffalo, NY;; 2026-10-03 13:20 EDT;; No Delay;; --;; "
    "26 minutes;; --;; \n"
    "Ambassador Bridge;; Windsor, ON/Detroit, MI;; 2026-10-03 12:50 EDT;; Closed;; --;; "
    "1 minute;; --;; \n"
    "North Portal;; North Portal, SK/Portal, ND;; 2026-10-03 11:15 CST;; No Delay;; --;; "
    "No Delay;; --;; \n"
    "\n"
).encode()

_FR = (
    "﻿Bureau de l'ASFC;; Emplacement;; Mis à jour;; Débit / Expéditions commerciales - "
    "Vers le Canada;; Débit / Expéditions commerciales - Vers les États-Unis;; Débit / "
    "Voyageurs - Vers le Canada;; Débit / Voyageurs - Vers les États-Unis;;\n"
    "Pont Peace;; Fort Erie, ON/Buffalo, NY;; 2026-10-03 13:20 HAE;; Aucun délai;; --;; "
    "26 minutes;; --;; \n"
    "Pont des Mille-Îles;; Lansdowne, ON/Alexandria Bay, NY;; 2026-10-03 13:15 HAE;; "
    "Ne s'applique pas;; --;; Aucun délai;; --;; \n"
).encode()


def test_wait_values():
    assert client.parse_wait("No Delay").minutes == 0
    assert client.parse_wait("Aucun délai").status == "no_delay"
    assert client.parse_wait("1 minute").minutes == 1
    assert client.parse_wait("26 minutes").minutes == 26
    assert client.parse_wait("--").status == "not_reported"
    assert client.parse_wait("Ne s'applique pas").status == "not_applicable"
    assert client.parse_wait("Fermé").status == "closed"
    assert client.parse_wait("Lane maintenance").status == "other"


def test_update_time_zones():
    eastern = client.parse_updated("2026-10-03 13:20 EDT")
    assert eastern is not None and eastern.utcoffset() == timedelta(hours=-4)
    french = client.parse_updated("2026-10-03 13:54 HAA")
    assert french is not None and french.utcoffset() == timedelta(hours=-3)
    assert client.parse_updated("2026-10-03 13:54 XYZ") is None


def test_parse_file_fields():
    crossings = client.parse_file(_EN.decode("utf-8-sig"))
    assert [c.office for c in crossings] == [
        "St. Stephen",
        "Peace Bridge",
        "Ambassador Bridge",
        "North Portal",
    ]
    peace = crossings[1]
    assert (peace.province, peace.us_state) == ("ON", "NY")
    assert peace.travellers_canada_bound is not None
    assert peace.travellers_canada_bound.minutes == 26
    assert peace.travellers_us_bound is not None
    assert peace.travellers_us_bound.status == "not_reported"
    assert crossings[3].updated_at is not None
    assert crossings[3].updated_at.utcoffset() == timedelta(hours=-6)
    with pytest.raises(UpstreamError):
        client.parse_file("<html>moved</html>")


async def test_filters_and_longest(httpx_mock):
    httpx_mock.add_response(url=constants.CSV_URL["en"], content=_EN)
    everything = await client.border_wait_times()
    assert everything.total_crossings == 4
    assert everything.longest_travellers_wait == "Peace Bridge"
    ontario = await client.border_wait_times(province="Ontario", direction="canada_bound")
    assert [c.office for c in ontario.crossings] == ["Peace Bridge", "Ambassador Bridge"]
    assert ontario.crossings[0].travellers_us_bound is None
    windsor = await client.border_wait_times(crossing="windsor")
    assert windsor.returned_count == 1
    assert windsor.crossings[0].commercial_canada_bound is not None
    assert windsor.crossings[0].commercial_canada_bound.status == "closed"
    assert "000fe5aa" in windsor.historical_data
    with pytest.raises(InvalidInput):
        await client.border_wait_times(province="Atlantis")


async def test_french_file(httpx_mock):
    httpx_mock.add_response(url=constants.CSV_URL["fr"], content=_FR)
    result = await client.border_wait_times(crossing="mille iles", lang="fr")
    crossing = result.crossings[0]
    assert crossing.office == "Pont des Mille-Îles"
    assert crossing.commercial_canada_bound is not None
    assert crossing.commercial_canada_bound.status == "not_applicable"
    assert result.longest_travellers_wait is None
    assert result.historical_data.startswith("Historique :")
    assert (result.provenance.coverage or "").startswith("une trentaine de postes")
    assert "Agence des services frontaliers du Canada" in (result.provenance.licence or "")
    assert "« location »" in (result.provenance.limits or "").replace(" ", " ")


async def test_french_errors():
    with pytest.raises(InvalidInput, match="province inconnue"):
        await client.border_wait_times(province="Atlantis", lang="fr")
    with pytest.raises(InvalidInput, match="^Entrée invalide : cbsa : direction"):
        await client.border_wait_times(direction="sideways", lang="fr")
