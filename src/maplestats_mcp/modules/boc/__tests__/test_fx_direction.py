"""Which way the Canadian dollar moved, stated with Bank of Canada exchange rates.

An FX{A}{B} series is B per unit of A (Valet's metadata.unit, checked live 2026-11-26):
FXJPYCAD is Canadian dollars per yen, FXCADUSD US dollars per Canadian dollar. In the
Maple Test (2026-11-21) an answer read FXJPYCAD's fall from 0.00902 to 0.00887 as the
dollar weakening, the inversion done the wrong way round.
"""

from __future__ import annotations

from datetime import date

from maplestats_mcp.modules.boc import client, constants
from maplestats_mcp.modules.boc.schemas import Observation
from maplestats_mcp.shared.envelope import make_provenance


def _rows(name: str, *points: tuple[str, float]) -> list[Observation]:
    return [Observation(ref_date=date.fromisoformat(d), values={name: v}) for d, v in points]


def test_a_fall_in_cad_per_yen_is_the_dollar_strengthening():
    rows = _rows("FXJPYCAD", ("2026-10-01", 0.00902), ("2026-10-30", 0.00887))
    note = client.fx_direction("FXJPYCAD", rows) or ""
    assert "Canadian dollars per JPY: a lower value means a stronger Canadian dollar" in note
    assert "From 2026-10-01 (0.00902) to 2026-10-30 (0.00887) it fell" in note
    assert note.endswith("the Canadian dollar strengthened against JPY.")


def test_a_rise_in_cad_per_us_dollar_is_the_dollar_weakening():
    rows = _rows("FXUSDCAD", ("2026-10-30", 1.3912), ("2026-10-01", 1.3801))
    note = client.fx_direction("FXUSDCAD", rows) or ""
    assert "From 2026-10-01 (1.3801) to 2026-10-30 (1.3912) it rose" in note
    assert note.endswith("the Canadian dollar weakened against USD.")


def test_a_rise_in_us_dollars_per_cad_is_the_dollar_strengthening():
    rows = _rows("FXCADUSD", ("2026-10-01", 0.7021), ("2026-10-30", 0.7105))
    note = client.fx_direction("FXCADUSD", rows) or ""
    assert "USD per Canadian dollar: a higher value means a stronger Canadian dollar" in note
    assert note.endswith("the Canadian dollar strengthened against USD.")


def test_monthly_averages_read_the_same_way():
    rows = _rows("FXMJPYCAD", ("2026-09-01", 0.00930), ("2026-10-01", 0.00895))
    assert (client.fx_direction("FXMJPYCAD", rows) or "").endswith("strengthened against JPY.")


def test_one_value_or_no_change_gives_the_reading_without_a_move():
    one = client.fx_direction("FXJPYCAD", _rows("FXJPYCAD", ("2026-10-01", 0.00902))) or ""
    assert one.startswith("FXJPYCAD is Canadian dollars per JPY") and "From" not in one
    same = _rows("FXJPYCAD", ("2026-10-01", 0.00902), ("2026-10-02", 0.00902))
    assert (client.fx_direction("FXJPYCAD", same) or "").endswith("no change.")


def test_series_that_are_not_rates_against_cad_get_nothing():
    assert client.fx_direction("IEXE0101", []) is None
    assert client.fx_direction("FXCADUSD_CHANGES", []) is None
    assert client.fx_direction("V39079", []) is None


def test_french():
    rows = _rows("FXJPYCAD", ("2026-10-01", 0.00902), ("2026-10-30", 0.00887))
    note = client.fx_direction("FXJPYCAD", rows, "fr") or ""
    assert "en dollars canadiens par JPY" in note
    assert "Du 2026-10-01 (0,00902) au 2026-10-30 (0,00887), elle a baissé" in note
    assert "le dollar canadien s'est raffermi face à JPY" in note
    assert " :" in note  # French punctuation spacing


def test_many_exchange_rates_get_one_general_reading():
    codes = ["FXUSDCAD", "FXEURCAD", "FXJPYCAD", "FXGBPCAD"]
    notes = client._fx_direction_notes(codes, [], "en")
    assert len(notes) == 1 and notes[0].startswith("Reading Bank of Canada exchange rates")


def test_the_caveats_hold_both_the_indicative_rate_and_the_direction():
    rows = _rows("FXJPYCAD", ("2026-10-01", 0.00902), ("2026-10-30", 0.00887))
    provenance = make_provenance(
        source="boc", url="https://example.org", cached=False, schema_name="boc.Test", lang="en"
    )
    caveats = client._with_fx_caveats(provenance, ["FXJPYCAD"], "en", rows).caveats
    assert any("Indicative rate" in c for c in caveats)
    assert any(c.endswith("strengthened against JPY.") for c in caveats)


async def test_get_observations_states_the_move(httpx_mock):
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}observations/FXJPYCAD/json?recent=2",
        json={
            "seriesDetail": {
                "FXJPYCAD": {
                    "label": "JPY/CAD",
                    "description": "Daily average exchange rate of the Japanese yen in Canadian "
                    "dollars.",
                    "dimension": {"key": "d", "name": "Date"},
                }
            },
            "observations": [
                {"d": "2026-10-29", "FXJPYCAD": {"v": "0.008890"}},
                {"d": "2026-10-30", "FXJPYCAD": {"v": "0.008870"}},
            ],
        },
    )
    result = await client.get_observations(["FXJPYCAD"], recent=2)
    assert any(
        c.endswith("the Canadian dollar strengthened against JPY.")
        for c in result.provenance.caveats
    )
