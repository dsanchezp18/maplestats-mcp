"""The DuckDB query layer of statcan_pumf_tabulate, on small local files.

Checked live 2026-09-24 against LFS January 2025 (Alberta: 4.00 M aged
15+, 195,955 unemployed) and EICS 2024 (fixed-width, WTPM weight).
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path

import pytest

from maplestats_mcp.modules.statcan.lang import use_lang
from maplestats_mcp.modules.statcan.pumf import tabulate
from maplestats_mcp.modules.statcan.pumf.schemas import PumfVariable
from maplestats_mcp.shared.errors import InvalidInput, UpstreamError
from maplestats_mcp.shared.remote_zip import ZipMember

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
    source = tabulate.DataSource(path, fixed, _vars())
    rows, n, total = tabulate._run_query(
        source, ["LFSSTAT"], ["FINALWT"], "total", None, {"PROV": ["048"]}
    )
    assert rows == [("1", 1, 100.0, 100.0), ("3", 1, 50.0, 50.0)]
    assert (n, total) == (2, 150.0)


def test_weighted_mean_skips_missing_values(tmp_path):
    path = tmp_path / "data.csv"
    path.write_text(CSV)
    source = tabulate.DataSource(path, False, _vars())
    rows, _, _ = tabulate._run_query(source, ["PROV"], ["FINALWT"], "mean", "HRLYEARN", {})
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


async def test_member_errors_in_french():
    use_lang("fr")
    monthly = [ZipMember(f"pub0{m}25.csv", 0, 12_000_000, 8, 0) for m in (1, 2)]
    with pytest.raises(InvalidInput, match="plusieurs fichiers de données"):
        tabulate._pick_member(monthly, None)
    with pytest.raises(InvalidInput, match="Aucun fichier 'x.csv' dans le ZIP"):
        tabulate._pick_member(monthly, "x.csv")
    use_lang("en")
    with pytest.raises(InvalidInput, match="several data files"):
        tabulate._pick_member(monthly, None)


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
    se = method.standard_error(33865.0, [float(g) for g in groups])
    assert se == pytest.approx(1173.47, abs=0.5)
    assert method.standard_error(33865.0, [1.0] * 15) is None  # a missing replicate: no SE


def test_shares_are_computed_per_replicate():
    rows = [("A", "1", 5, 30.0, 30.0, 40.0, 40.0), ("A", "2", 5, 70.0, 70.0, 60.0, 60.0)]
    estimates = [tabulate._estimates(r, 2, 2, "share") for r in rows]
    shares = tabulate._to_shares(rows, estimates, 2)
    assert shares == [[30.0, 40.0], [70.0, 60.0]]


def test_bootstrap_centres_on_the_full_sample_estimate():
    # EICS/CSWC guides, eq. (1): sum((X*(b) - X)^2) / 1000, X the full-sample estimate.
    method = tabulate.variance_method("https://x/n1/pub/89m0025x/2022001/2024.zip")
    assert method is not None and method.centre == "estimate"
    replicates = [101.0] * 500 + [99.0] * 500
    assert method.standard_error(100.0, replicates) == pytest.approx(1.0)
    assert method.standard_error(90.0, replicates) == pytest.approx(10.0499, abs=1e-3)


def test_replicate_weights_are_joined_from_a_separate_file(tmp_path):
    main_file = tmp_path / "main.txt"
    main_file.write_text("0000148  100\n0000235  200\n")  # PUMFID 1-5, PROV 6-7, WT 8-12
    bsw_file = tmp_path / "bsw.txt"
    bsw_file.write_text("00001  110   90\n00002  210  190\n")  # PUMFID, BSW1 6-10, BSW2 11-15
    main = tabulate.DataSource(
        main_file,
        True,
        {
            "PUMFID": PumfVariable(name="PUMFID", position=1, width=5, values=[]),
            "PROV": PumfVariable(name="PROV", position=6, width=2, values=[]),
            "WT": PumfVariable(name="WT", position=8, width=5, values=[]),
        },
    )
    bsw = tabulate.DataSource(
        bsw_file,
        True,
        {
            "PUMFID": PumfVariable(name="PUMFID", position=1, width=5, values=[]),
            "BSW1": PumfVariable(name="BSW1", position=6, width=5, values=[]),
            "BSW2": PumfVariable(name="BSW2", position=11, width=5, values=[]),
        },
    )
    rows, n, total = tabulate._run_query(
        main, ["PROV"], ["WT", "BSW1", "BSW2"], "total", None, {}, bsw, "PUMFID"
    )
    assert rows == [
        ("35", 1, 200.0, 200.0, 210.0, 210.0, 190.0, 190.0),
        ("48", 1, 100.0, 100.0, 110.0, 110.0, 90.0, 90.0),
    ]
    assert (n, total) == (2, 300.0)


def test_duckdb_failure_becomes_upstream_error(tmp_path):
    """A file DuckDB cannot read (here: a column the CSV lacks) is not a raw BinderException."""
    path = tmp_path / "data.csv"
    path.write_text(CSV)
    source = tabulate.DataSource(path, False, _vars())
    with pytest.raises(UpstreamError, match="could not be tabulated"):
        tabulate._run_query(source, ["NOT_A_COLUMN"], ["FINALWT"], "total", None, {})


def test_unreadable_data_file_becomes_upstream_error(tmp_path):
    source = tabulate.DataSource(tmp_path / "gone.csv", False, _vars())
    with pytest.raises(UpstreamError, match="could not be tabulated"):
        tabulate._run_query(source, ["PROV"], ["FINALWT"], "total", None, {})


_EICS_URL = "https://www150.statcan.gc.ca/n1/pub/89m0025x/2022001/2024.zip"


def _bootstrap_setup(monkeypatch, tmp_path, *, main_has_id: bool, layout_has_id: bool):
    """Stub the network and file layers so tabulate() reaches the replicate-id check."""
    method = tabulate.variance_method(_EICS_URL)
    assert method is not None and method.id_variable == "PUMFID"
    main_columns = {
        "PROV": PumfVariable(name="PROV", position=6, width=2, values=[]),
        "WTPM": PumfVariable(name="WTPM", position=8, width=5, values=[]),
    }
    if main_has_id:
        main_columns["PUMFID"] = PumfVariable(name="PUMFID", position=1, width=5, values=[])
    layout_columns = {
        name: PumfVariable(name=name, position=6 + i, width=5, values=[])
        for i, name in enumerate(method.replicates)
    }
    if layout_has_id:
        layout_columns["PUMFID"] = PumfVariable(name="PUMFID", position=1, width=5, values=[])
    main_path = tmp_path / "main.txt"
    main_path.write_text("0000148  100\n")

    async def load_codebook(url, lang="en"):
        return list(main_columns.values()), [], False

    async def members(url):
        return [ZipMember("pumf_main.txt", 0, 5_000_000, 8, 0)], 1, False

    async def local_data_file(url, member, *, also_keep=()):
        return main_path

    async def replicate_source(url, members, file_marker, main_path=None):
        return tabulate.DataSource(tmp_path / "bsw.txt", True, layout_columns)

    monkeypatch.setattr(tabulate.client, "load_codebook", load_codebook)
    monkeypatch.setattr(tabulate.client, "_members", members)
    monkeypatch.setattr(tabulate, "local_data_file", local_data_file)
    monkeypatch.setattr(tabulate, "_replicate_source", replicate_source)


@pytest.mark.parametrize(
    ("main_has_id", "layout_has_id", "where"),
    [(False, True, "main codebook"), (True, False, "bootstrap weight layout")],
)
async def test_missing_record_id_is_named_not_a_bare_key_error(
    monkeypatch, tmp_path, main_has_id, layout_has_id, where
):
    _bootstrap_setup(monkeypatch, tmp_path, main_has_id=main_has_id, layout_has_id=layout_has_id)
    with pytest.raises(InvalidInput, match=f"'PUMFID'.*{where}"):
        await tabulate.tabulate(_EICS_URL, rows=["PROV"], weight="WTPM")


async def test_missing_record_id_message_follows_lang(monkeypatch, tmp_path):
    _bootstrap_setup(monkeypatch, tmp_path, main_has_id=False, layout_has_id=True)
    with pytest.raises(InvalidInput, match="'PUMFID'.*dictionnaire principal"):
        await tabulate.tabulate(_EICS_URL, rows=["PROV"], weight="WTPM", lang="fr")
    use_lang("en")


def _cache_file(path, size, age_seconds):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    stamp = time.time() - age_seconds
    os.utime(path, (stamp, stamp))
    return path


def test_cache_cap_removes_oldest_files_but_never_the_target_or_part_files(monkeypatch, tmp_path):
    monkeypatch.setattr(tabulate.config, "get_pumf_cache_max_bytes", lambda: 15)
    oldest = _cache_file(tmp_path / "a" / "old.csv", 10, 400)
    target = _cache_file(tmp_path / "b" / "target.csv", 10, 300)  # older than `newer`
    newer = _cache_file(tmp_path / "c" / "newer.csv", 10, 100)
    partial = _cache_file(tmp_path / "d" / "archive.zip.part", 500, 900)
    in_progress = _cache_file(tmp_path / "e" / "data.csv.part", 500, 800)

    tabulate._enforce_cache_cap(tmp_path, target)

    assert target.exists()  # the file this call is about to read stays, though not newest
    assert not oldest.exists()
    assert not newer.exists()  # still over the cap, so the next-oldest goes
    assert partial.exists()  # another call's download in progress
    assert in_progress.exists()


def test_cache_cap_also_keeps_files_the_same_call_still_needs(monkeypatch, tmp_path):
    monkeypatch.setattr(tabulate.config, "get_pumf_cache_max_bytes", lambda: 5)
    main = _cache_file(tmp_path / "a" / "main.txt", 10, 500)
    other = _cache_file(tmp_path / "b" / "other.txt", 10, 400)
    replicates = _cache_file(tmp_path / "c" / "bsw.txt", 10, 300)

    tabulate._enforce_cache_cap(tmp_path, replicates, main)

    assert main.exists() and replicates.exists()
    assert not other.exists()


def test_cache_cap_survives_a_file_it_cannot_remove(monkeypatch, tmp_path, caplog):
    """Windows refuses to delete a file a reader has open; that must not fail the call."""
    monkeypatch.setattr(tabulate.config, "get_pumf_cache_max_bytes", lambda: 5)
    locked = _cache_file(tmp_path / "a" / "locked.csv", 10, 500)
    removable = _cache_file(tmp_path / "b" / "removable.csv", 10, 400)
    target = _cache_file(tmp_path / "c" / "target.csv", 10, 100)
    real_unlink = Path.unlink

    def unlink(self, missing_ok=False):
        if self.name == "locked.csv":
            raise PermissionError("[WinError 32] file in use")
        real_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", unlink)

    with caplog.at_level(logging.WARNING):
        tabulate._enforce_cache_cap(tmp_path, target)

    assert locked.exists()
    assert not removable.exists()  # eviction went on past the locked file
    assert target.exists()
    assert "locked.csv" in caplog.text
