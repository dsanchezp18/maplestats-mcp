from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from maplestats_mcp.modules.ised.ip_horizons import client, store
from maplestats_mcp.modules.ised.ip_horizons.schemas import IpHorizonsFile
from maplestats_mcp.shared.errors import InvalidInput, NotFound

# Headers and value quirks copied from the 2024-10-11 release: bilingual
# headers, pipe delimiter, literal NULL, a leading space on grant dates.
_MAIN = (
    "Patent Number - Numéro du brevet|Filing Date - Date de dépôt|"
    "Grant Date - Date de l’octroi|Application Status Code - Code du statut de la demande|"
    "Application Type Code - Code du type de la demande|"
    "Application/Patent Title English - Demande/Titre anglais du brevet|"
    "Application/Patent Title French - Demande/Titre français du brevet\n"
    "2000001|1989-10-02| 1995-03-14|EX|NON-PCT|OXYGEN SENSING METHOD AND APPARATUS|"
    "DETECTEUR D'OXYGENE ET METHODE CONNEXE\n"
    "2000002|1989-10-02| 1994-09-27|LA|NON-PCT|ROLLER MASSAGING APPARATUS|MASSEUR A ROULEAU\n"
    "2000003|2016-05-01|NULL|DE|PCT|FUEL CELL STACK|EMPILEMENT DE PILES\n"
    "2000004|-1|-1|-2|NON-PCT|OLD ROLLER|NULL\n"
)
_PARTY = (
    "Patent Number - Numéro du brevet|Interested Party Type - Type de partie intéressée|"
    "Party Name - Nom de la partie|Party City - Ville de la partie|"
    "Party Country - Pays de la partie\n"
    "2000001|Owner|PANAMETRICS, INC.|WALTHAM|United States of America\n"
    "2000001|Inventor|MEYER, EMILIO|NULL|Italy\n"
    "2000003|Owner|BALLARD POWER SYSTEMS INC.|BURNABY|Canada\n"
    "2000002|Inventor|Ballard, Jane|NULL|Canada\n"
    "2000004|Owner|OLD CO|Unknown|Canada\n"
)
_IPC = (
    "Patent Number - Numéro du brevet|"
    "IPC Classification Sequence Number - Numéro de séquence de la classification de la CIB|"
    "IPC Section Code - Code de la section de la CIB|IPC Class Code - Code de la classe de la CIB|"
    "IPC Subclass Code - Code de la sous-classe de la CIB|"
    "IPC Main Group Code - Code du groupe principal de la CIB|"
    "IPC Subgroup Code - Code du sous-groupe de la CIB\n"
    "2000001|   1|H|03|K|19|01\n"
    "2000003|   1|H|01|M|8|04\n"
)


def _file(table: str) -> IpHorizonsFile:
    return IpHorizonsFile(
        ip_type="patent",
        table=table,
        text_format=False,
        number_from=2_000_001,
        number_to=4_000_000,
        release_date=date(2024, 10, 11),
        name=table,
        url=f"https://opic-cipo.ca/x/PT_{table}_2000001_to_4000000.zip",
    )


@pytest.fixture
def tables(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    paths: dict[str, Path] = {}
    for table, text in (
        ("main", _MAIN),
        ("interested_party", _PARTY),
        ("ipc_classification", _IPC),
    ):
        csv_path = tmp_path / f"{table}.csv"
        csv_path.write_text(text, encoding="utf-8")
        paths[table] = tmp_path / f"{table}.parquet"
        store.convert_csv(csv_path, paths[table])

    async def patent_files(table: str) -> list[IpHorizonsFile]:
        return [_file(table)]

    async def local_table(file: IpHorizonsFile) -> Path:
        return paths[file.table]

    monkeypatch.setattr(client, "_patent_files", patent_files)
    monkeypatch.setattr(store, "local_table", local_table)
    return paths


def test_column_name_keeps_english_half():
    assert store.column_name("Application/Patent Title English - Demande/Titre") == (
        "application_patent_title_english"
    )
    assert store.column_name("Patent Number - Numéro du brevet") == "patent_number"


async def test_get_patent_trims_values_and_lists_parties(tables):
    record = await client.get_patent(2000001, include_classifications=True)
    assert record.patent.title_en == "OXYGEN SENSING METHOD AND APPARATUS"
    assert record.patent.grant_date == "1995-03-14"  # leading space trimmed
    assert [p.party_type for p in record.parties] == ["Owner", "Inventor"]
    assert record.parties[1].city is None  # literal NULL
    assert [c.symbol for c in record.classifications] == ["H03K 19/01"]
    assert record.classifications[0].sequence == 1
    assert record.release_date == date(2024, 10, 11)


async def test_unknown_codes_become_null(tables):
    record = await client.get_patent(2000004)
    assert record.patent.filing_date is None
    assert record.patent.status_code is None
    assert record.parties[0].city is None
    # an unknown filing date never falls inside a date range
    result = await client.search_patents(title="roller", filed_to=date(2000, 1, 1))
    assert [p.patent_number for p in result.patents] == [2000002]


async def test_get_patent_without_classifications(tables):
    record = await client.get_patent(2000003)
    assert record.classifications_included is False
    assert record.patent.grant_date is None


async def test_get_patent_missing_number(tables):
    with pytest.raises(NotFound):
        await client.get_patent(2000099)
    with pytest.raises(NotFound, match="no IP Horizons file"):
        await client.get_patent(5)


async def test_search_by_party_and_type(tables):
    anyone = await client.search_patents(party_name="ballard")
    assert anyone.total_matched == 2
    owners = await client.search_patents(party_name="ballard", party_type="owner")
    assert [p.patent_number for p in owners.patents] == [2000003]


async def test_search_by_ipc_and_date(tables):
    result = await client.search_patents(ipc="h01m 8", filed_from=date(2015, 1, 1))
    assert [p.patent_number for p in result.patents] == [2000003]
    assert (await client.search_patents(ipc="H01M 8/4")).total_matched == 1
    assert (await client.search_patents(ipc="H01M 9")).total_matched == 0
    assert (await client.search_patents(ipc="H03K 19/01")).total_matched == 1


async def test_search_by_french_title_newest_first(tables):
    result = await client.search_patents(title="a rouleau")
    assert [p.patent_number for p in result.patents] == [2000002]
    everything = await client.search_patents(filed_from=date(1980, 1, 1), limit=2)
    assert everything.total_matched == 3
    assert [p.patent_number for p in everything.patents] == [2000003, 2000002]


async def test_search_rejects_bad_input(tables):
    with pytest.raises(InvalidInput, match="at least one"):
        await client.search_patents()
    with pytest.raises(InvalidInput, match="ipc must"):
        await client.search_patents(ipc="fuel cells")
    with pytest.raises(InvalidInput, match="needs a party_name"):
        await client.search_patents(party_type="owner", title="x")
    with pytest.raises(InvalidInput, match="limit"):
        await client.search_patents(title="x", limit=0)
