"""LFS PUMF standard errors: the calibrated Poisson bootstrap of its user guide.

Checked live 2026-11-08 on the October 2026 PUMF (pub1026.csv) against
Table 14-10-0287-01 (released 2026-11-06): the PUMF's unemployed by
province equal the published unadjusted estimates (Canada 1,386,544 vs
1,386.5 thousand; Alberta 191,398 vs 191.4 thousand), and the bootstrap
standard errors differ from the published ones by 0% to 15%, mostly a little
lower, as an approximation that ignores the LFS clustering would (Canada
28,390 vs 29,400; Quebec 13,668 vs 13,700; Ontario 19,149 vs 20,400; Alberta
12,139 vs 11,800; British Columbia 9,955 vs 10,600). The published standard
errors are for the seasonally adjusted series, the closest StatCan publishes.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from maplestats_mcp.modules.statcan.lang import use_lang
from maplestats_mcp.modules.statcan.pumf import tabulate
from maplestats_mcp.modules.statcan.pumf.schemas import PumfVariable
from maplestats_mcp.shared.remote_zip import ZipMember

_LFS_URL = "https://www150.statcan.gc.ca/n1/pub/71m0001x/2021001/2026-10-CSV.zip"

# Appendix C1's four records: two in domain (PROV 10, age 15-16, gender 1),
# two in (59, 15-16, 1), with the signs the guide drew for replicates 1-3.
_C1_CSV = (
    "REC_NUM,PROV,GENDER,AGE_6,AGE_12,FINALWT,LFSSTAT\n"
    "1,10,1,1,01,500,1\n"
    "2,10,1,1,01,450,3\n"
    "3,59,1,1,01,150,1\n"
    "4,59,1,1,01,250,3\n"
)
_C1_SIGNS = {1: (1, -1, -1), 2: (-1, -1, 1), 3: (1, -1, 1), 4: (-1, 1, -1)}
_NAMES = ["REC_NUM", "PROV", "GENDER", "AGE_6", "AGE_12", "FINALWT", "LFSSTAT"]


def _lfs_method() -> tabulate.VarianceMethod:
    method = tabulate.variance_method(_LFS_URL)
    assert method is not None and method.generated_replicates == 1000
    return method


def _c1_source(tmp_path: Path) -> tabulate.DataSource:
    path = tmp_path / "pub.csv"
    path.write_text(_C1_CSV)
    return tabulate.DataSource(path, False, {n: PumfVariable(name=n, values=[]) for n in _NAMES})


def test_variance_matches_the_guide_worked_example():
    # Appendix C2: total unemployed 650; the four replicates shown give a sum
    # of squared deviations / 1000 of 1,460.819654, SE 38.22067, CV 5.9%. The
    # 996 replicates the example leaves out add nothing here.
    method = _lfs_method()
    shown = [564.2078, 1432.28725, 1.263858, 1.442039]
    se = method.standard_error(650.0, shown + [650.0] * 996)
    assert se == pytest.approx(38.22067, abs=1e-4)
    assert se is not None and se / 650 == pytest.approx(0.0588, abs=1e-4)
    assert method.standard_error(650.0, shown) is None  # not 1,000 replicates


@pytest.mark.parametrize(
    ("respondents", "cv", "quality"),
    [
        (4, 0.01, "unacceptable"),  # under 5 respondents, whatever the CV
        (5, 0.149, "acceptable"),
        (5, 0.15, "marginal"),
        (30, 0.35, "marginal"),
        (30, 0.351, "unacceptable"),
        (30, None, None),
    ],
)
def test_quality_bands_follow_table_5(respondents, cv, quality):
    release = _lfs_method().release
    assert release is not None
    assert release.quality(respondents, cv) == quality


def test_bootstrap_weights_follow_appendix_c1(monkeypatch, tmp_path):
    cases = " ".join(
        f"WHEN {record} * 10 + {b} THEN {sign}.0"
        for record, signs in _C1_SIGNS.items()
        for b, sign in enumerate(signs, start=1)
    )
    monkeypatch.setattr(
        tabulate, "_poisson_sign", lambda record, b: f"(CASE {record} * 10 + {b} {cases} END)"
    )
    method = dataclasses.replace(_lfs_method(), generated_replicates=3)
    rows, n, total = tabulate._run_poisson_query(
        _c1_source(tmp_path), ["REC_NUM"], "FINALWT", "total", None, {}, method
    )
    assert (n, total) == (4, 1350.0)
    weights = {row[0]: [row[4 + 2 * b] for b in range(3)] for row in rows}
    # Appendix C1 step 5, replicate 1: 949.5247, 0.475256, 399.3327, 0.667334.
    assert weights["1"][0] == pytest.approx(949.5247, abs=1e-3)
    assert weights["2"][0] == pytest.approx(0.475256, abs=1e-5)
    assert weights["3"][0] == pytest.approx(399.3327, abs=1e-3)
    assert weights["4"][0] == pytest.approx(0.667334, abs=1e-5)
    # Equation (3): every replicate adds up to FINALWT in each domain.
    for b in range(3):
        assert weights["1"][b] + weights["2"][b] == pytest.approx(950.0)
        assert weights["3"][b] + weights["4"][b] == pytest.approx(400.0)


def test_bootstrap_calibrates_before_filtering_and_repeats(tmp_path):
    def run() -> tuple[list[tuple], int, float]:
        return tabulate._run_poisson_query(
            _c1_source(tmp_path),
            ["PROV"],
            "FINALWT",
            "total",
            None,
            {"LFSSTAT": ["3"]},
            _lfs_method(),
        )

    rows, n, total = run()
    assert (n, total) == (2, 700.0)
    assert [row[:4] for row in rows] == [("10", 1, 450.0, 450.0), ("59", 1, 250.0, 250.0)]
    assert len(rows[0]) == 4 + 2 * 1000
    assert run()[0] == rows  # a fixed seed: the same call gives the same replicates


def test_calibration_domains_follow_appendix_b():
    import duckdb

    domain = tabulate.lfs_calibration_domain(lambda name: name)
    cases = [
        # PROV, GENDER, AGE_6, AGE_12 -> domain
        ("48", "2", "1", "01", "48|2|a1"),
        ("48", "2", "2", "01", "48|2|a2"),
        ("48", "2", "4", "02", "48|2|2"),  # 22-24 joins 20-24
        ("48", "2", "", "05", "48|2|5"),  # 35-39 and 40-44 are one group
        ("48", "2", "", "06", "48|2|5"),
        ("48", "2", "", "08", "48|2|7"),
        ("48", "2", "", "12", "48|2|12"),
    ]
    with duckdb.connect() as connection:
        for prov, gender, age_6, age_12, expected in cases:
            got = connection.execute(
                f"SELECT {domain} FROM (SELECT ? AS PROV, ? AS GENDER, ? AS AGE_6, ? AS AGE_12)",
                [prov, gender, age_6, age_12],
            ).fetchone()
            assert got == (expected,)


def test_poisson_signs_are_balanced_and_independent():
    import duckdb

    sign = tabulate._poisson_sign("r", "b")
    with duckdb.connect() as connection:
        row = connection.execute(
            f"WITH s AS (SELECT r, b, {sign} AS z FROM range(1, 2001) t(r), range(1, 101) u(b)) "
            "SELECT AVG(a.z), AVG(a.z * c.z) FROM s a JOIN s c ON a.r = c.r AND c.b = a.b + 1"
        ).fetchone()
    assert row is not None
    mean, lagged = row
    assert abs(mean) < 0.01
    assert abs(lagged) < 0.01


async def test_tabulate_reports_cv_and_quality(monkeypatch, tmp_path):
    path = tmp_path / "pub1026.csv"
    path.write_text(_C1_CSV)

    async def load_codebook(url, lang="en", *, data_member=None):
        return [PumfVariable(name=n, values=[]) for n in _NAMES], [], False

    async def members(url):
        return [ZipMember("pub1026.csv", 0, 12_000_000, 8, 0)], 1, False

    async def local_data_file(url, member, *, also_keep=(), also_extract=()):
        return path

    monkeypatch.setattr(tabulate.client, "load_codebook", load_codebook)
    monkeypatch.setattr(tabulate.client, "_members", members)
    monkeypatch.setattr(tabulate, "local_data_file", local_data_file)

    table = await tabulate.tabulate(_LFS_URL, rows=["PROV"], weight="FINALWT")
    assert table.variance_method is not None and "Poisson bootstrap" in table.variance_method
    assert [c.estimate for c in table.cells] == [950.0, 400.0]
    for cell in table.cells:
        # Calibration holds each domain's total, so a province total has no error.
        assert cell.standard_error == pytest.approx(0.0, abs=1e-6)
        assert cell.quality == "unacceptable"  # 2 respondents: under 5
    assert any("Table 5" in note for note in table.notes)

    french = await tabulate.tabulate(_LFS_URL, rows=["LFSSTAT"], weight="FINALWT", lang="fr")
    use_lang("en")
    assert any("inacceptable sous 5 répondants" in note for note in french.notes)


async def test_no_generated_replicates_without_the_calibration_variables(monkeypatch, tmp_path):
    path = tmp_path / "pub1026.csv"
    path.write_text("PROV,FINALWT\n48,100\n35,200\n")

    async def load_codebook(url, lang="en", *, data_member=None):
        return [PumfVariable(name=n, values=[]) for n in ("PROV", "FINALWT")], [], False

    async def members(url):
        return [ZipMember("pub1026.csv", 0, 12_000_000, 8, 0)], 1, False

    async def local_data_file(url, member, *, also_keep=(), also_extract=()):
        return path

    monkeypatch.setattr(tabulate.client, "load_codebook", load_codebook)
    monkeypatch.setattr(tabulate.client, "_members", members)
    monkeypatch.setattr(tabulate, "local_data_file", local_data_file)

    table = await tabulate.tabulate(_LFS_URL, rows=["PROV"], weight="FINALWT")
    assert table.variance_method is None
    assert all(c.standard_error is None and c.quality is None for c in table.cells)
