"""SAS/SPSS/Stata PUMF data files: metadata, conversion to CSV, tabulation.

fixtures/tiny.sav and tiny.dta were written with pyreadstat 1.3.7 (4 rows:
PUMFID, PROV with labels 48 Alberta / 35 Ontario, WT_FINAL, HOURS with a
missing value and 99 "Not stated", REGION as text). pyreadstat cannot write
.sas7bdat; that reader is checked live on CCPI 2022 by the smoke test.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from maplestats_mcp.modules.statcan.pumf import client, statfiles, tabulate
from maplestats_mcp.shared.errors import UpstreamError
from maplestats_mcp.shared.remote_zip import ZipMember

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(params=["tiny.sav", "tiny.dta"])
def stat_file(request, tmp_path) -> Path:
    path = tmp_path / request.param
    shutil.copy(FIXTURES / request.param, path)
    return path


def test_column_names_become_upper_case_identifiers():
    assert statfiles.column_name("Municipal class") == "MUNICIPAL_CLASS"
    assert statfiles.column_name("pr") == "PR"
    assert statfiles.column_name("2nd-job") == "_2ND_JOB"
    assert statfiles._names(["a b", "A_B", "x"]) == ["A_B", "A_B_", "X"]


def test_variables_come_from_the_file_itself(stat_file):
    variables = {v.name: v for v in statfiles.read_variables(stat_file)}
    assert list(variables) == ["PUMFID", "PROV", "WT_FINAL", "HOURS", "REGION"]
    assert variables["PROV"].label == "Province"
    assert {(v.code, v.label) for v in variables["PROV"].values} == {
        ("48", "Alberta"),
        ("35", "Ontario"),
    }
    assert client.main_weight(list(variables.values())) == "WT_FINAL"


def test_conversion_writes_text_like_the_csv_pumfs(stat_file):
    target = statfiles.to_csv(stat_file)
    lines = target.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "PUMFID,PROV,WT_FINAL,HOURS,REGION"
    # Whole numbers lose '.0', a missing value is empty, decimals stay.
    assert lines[1:] == [
        "1,48,100.5,37.5,West",
        "2,48,50,,West",
        "3,35,200,40,East",
        "4,35,100,99,East",
    ]
    assert statfiles.to_csv(stat_file) == target  # reused, not converted again
    assert not list(stat_file.parent.glob("*.part"))


def test_unreadable_file_is_an_upstream_error(tmp_path):
    broken = tmp_path / "broken.sav"
    broken.write_bytes(b"not an spss file")
    with pytest.raises(UpstreamError, match="broken.sav could not be read"):
        statfiles.to_csv(broken)
    assert not (tmp_path / "broken.sav.csv").exists()


def test_pick_member_takes_a_stat_file_only_without_text_data():
    sav = ZipMember("Data/survey.sav", 0, 5_000_000, 8, 0)
    txt = ZipMember("Data/survey.txt", 0, 4_000_000, 8, 0)
    bsw = ZipMember("Data/survey_bsw.sas7bdat", 0, 90_000_000, 8, 0)
    assert tabulate._pick_member([sav, txt, bsw], None).name == "Data/survey.txt"
    assert tabulate._pick_member([sav, bsw], None).name == "Data/survey.sav"


@pytest.mark.parametrize("name", ["tiny.sav", "tiny.dta"])
async def test_tabulate_reads_a_stat_only_zip(monkeypatch, tmp_path, name):
    url = "https://www150.statcan.gc.ca/n1/pub/00-00-0000/2025001/2025.zip"
    member = ZipMember(f"Data/{name}", 0, 5_000_000, 8, 0)
    readme = ZipMember("Data/readme.txt", 0, 2_000, 8, 0)

    async def members(_url):
        return [readme, member], 1, False

    async def local_data_file(_url, _member, *, also_keep=()):
        path = tmp_path / name
        if not path.exists():
            shutil.copy(FIXTURES / name, path)
        return path

    monkeypatch.setattr(client, "_members", members)
    monkeypatch.setattr(tabulate, "local_data_file", local_data_file)

    # No codebook file in the ZIP: the variables come from the data file.
    variables, source_files, _ = await client.load_codebook(url)
    assert source_files == [f"Data/{name}"]
    assert "WT_FINAL" in {v.name for v in variables}

    table = await tabulate.tabulate(url, rows=["prov"], statistic="total")
    assert table.weight == "WT_FINAL"
    assert [(c.groups[0].code, c.groups[0].label, c.estimate) for c in table.cells] == [
        ("35", "Ontario", 300.0),
        ("48", "Alberta", 150.5),
    ]
    assert any("converted to text once" in note for note in table.notes)

    mean = await tabulate.tabulate(url, rows=["REGION"], statistic="mean", value_variable="HOURS")
    by_region = {c.groups[0].code: c.estimate for c in mean.cells}
    assert by_region["West"] == pytest.approx(37.5)  # the missing value is left out
    assert by_region["East"] == pytest.approx(40.0)  # 99 "Not stated" is a reserve code
