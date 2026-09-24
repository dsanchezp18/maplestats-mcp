"""The DuckDB query layer of statcan_pumf_tabulate, on small local files.

Checked live 2026-09-24 against LFS January 2025 (Alberta: 4.00 M aged
15+, 195,955 unemployed) and EICS 2024 (fixed-width, WTPM weight).
"""

from __future__ import annotations

import pytest

from maple_data_mcp.modules.statcan.pumf import tabulate
from maple_data_mcp.modules.statcan.pumf.schemas import PumfVariable
from maple_data_mcp.shared.errors import InvalidInput
from maple_data_mcp.shared.remote_zip import ZipMember

CSV = "PROV,LFSSTAT,FINALWT,HRLYEARN\n48,1,100,3000\n48,3,50,\n35,1,200,4000\n35,1,100,2000\n"

# Fixed width: PROV cols 1-2, LFSSTAT col 3, weight cols 4-8.
FIXED = "481  100\n483   50\n351  200\n351  100\n"


def _vars() -> dict[str, PumfVariable]:
    spec = {"PROV": (1, 2), "LFSSTAT": (3, 1), "FINALWT": (4, 5), "HRLYEARN": (9, 4)}
    return {n: PumfVariable(name=n, position=p, width=w, values=[]) for n, (p, w) in spec.items()}


@pytest.mark.parametrize(("content", "fixed"), [(CSV, False), (FIXED, True)])
def test_weighted_totals_with_numeric_filter(tmp_path, content, fixed):
    path = tmp_path / ("data.csv" if not fixed else "data.txt")
    path.write_text(content)
    rows, n, total = tabulate._run_query(
        path, fixed, _vars(), ["LFSSTAT"], ["FINALWT"], "total", None, {"PROV": ["048"]}
    )
    assert rows == [("1", 1, 100.0, 100.0), ("3", 1, 50.0, 50.0)]
    assert (n, total) == (2, 150.0)


def test_weighted_mean_skips_missing_values(tmp_path):
    path = tmp_path / "data.csv"
    path.write_text(CSV)
    rows, _, _ = tabulate._run_query(
        path, False, _vars(), ["PROV"], ["FINALWT"], "mean", "HRLYEARN", {}
    )
    by_prov = {r[0]: tabulate._estimates(r, 1, 1, "mean")[0] for r in rows}
    assert by_prov["48"] == pytest.approx(3000.0)  # the blank value is excluded
    assert by_prov["35"] == pytest.approx((200 * 4000 + 100 * 2000) / 300)


def test_pick_member_prefers_csv_and_asks_when_ambiguous():
    members = [
        ZipMember("data.dat", 0, 5_000_000, 8, 0),
        ZipMember("data_v2.csv", 0, 6_000_000, 8, 0),
        ZipMember("Documents/codebook.csv", 0, 40_000, 8, 0),
        ZipMember("PUMF_BSW.txt", 0, 80_000_000, 8, 0),
    ]
    assert tabulate._pick_member(members, None).name == "data_v2.csv"
    monthly = [ZipMember(f"pub0{m}25.csv", 0, 12_000_000, 8, 0) for m in (1, 2)]
    with pytest.raises(InvalidInput, match="pub0125.csv"):
        tabulate._pick_member(monthly, None)
    assert tabulate._pick_member(monthly, "pub0225.csv").name == "pub0225.csv"


def test_census_2021_standard_error_matches_the_user_guide_example():
    # 2021 Census Individuals PUMF User Guide, ch. 3, Example 5: 16 group
    # estimates whose squared deviations sum to 48,195,757 -> SE 1,173.47.
    method = tabulate.variance_method("https://x/cen21_ind_98m0001x_part_rec21.zip")
    assert method is not None
    groups = [
        36084,
        32466,
        34953,
        33596,
        33823,
        34275,
        36084,
        34953,
        31787,
        35632,
        30657,
        31109,
        31787,
        35179,
        35406,
        34049,
    ]
    assert method.standard_error([float(g) for g in groups]) == pytest.approx(1173.47, abs=0.5)
    assert method.standard_error([1.0] * 15) is None  # a missing replicate: no SE


def test_shares_are_computed_per_replicate():
    rows = [("A", "1", 5, 30.0, 30.0, 40.0, 40.0), ("A", "2", 5, 70.0, 70.0, 60.0, 60.0)]
    estimates = [tabulate._estimates(r, 2, 2, "share") for r in rows]
    shares = tabulate._to_shares(rows, estimates, 2)
    assert shares == [[30.0, 40.0], [70.0, 60.0]]
