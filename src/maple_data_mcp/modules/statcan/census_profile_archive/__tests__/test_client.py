from __future__ import annotations

import pytest

from maple_data_mcp.modules.statcan.census_profile_archive import client
from maple_data_mcp.shared.errors import InvalidInput


async def test_list_geography_levels_2016():
    result = await client.list_geography_levels(2016)
    assert result.year == 2016
    assert "canada_provinces_territories" in result.levels
    assert len(result.levels) == 34
    assert "IVT" in result.formats


async def test_list_geography_levels_2001_has_fewer_levels():
    result = await client.list_geography_levels(2001)
    assert len(result.levels) == 5
    assert result.formats == ["CSV", "TAB"]


async def test_list_geography_levels_invalid_year_raises():
    with pytest.raises(InvalidInput):
        await client.list_geography_levels(1996)


async def test_get_download_link_2016_geono_style():
    result = await client.get_download_link(2016, "canada_provinces_territories", "csv")
    assert result.file_format == "CSV"
    assert (
        result.url
        == "https://www12.statcan.gc.ca/census-recensement/2016/dp-pd/prof/details/download-telecharger/comp/GetFile.cfm?Lang=E&FILETYPE=CSV&GEONO=059"
    )


async def test_get_download_link_2011_ctlg_style():
    result = await client.get_download_link(2011, "census_divisions", "tab")
    assert (
        result.url
        == "https://www12.statcan.gc.ca/census-recensement/2011/dp-pd/prof/details/download-telecharger/comprehensive/comp_download.cfm?CTLG=98-316-XWE2011001&FMT=TAB701"
    )


async def test_get_download_link_invalid_level_raises():
    with pytest.raises(InvalidInput):
        await client.get_download_link(2006, "dissemination_areas", "csv")


async def test_get_download_link_invalid_format_raises():
    with pytest.raises(InvalidInput):
        await client.get_download_link(2016, "canada_provinces_territories", "IVT2000")


async def test_get_download_link_french_2016_uses_lang_f():
    result = await client.get_download_link(2016, "canada_provinces_territories", "csv", "fr")
    assert "Lang=F" in result.url
    assert result.language == "fr"


@pytest.mark.parametrize(
    ("year", "catalogue"),
    [(2011, "98-316-XWF2011001"), (2006, "92-591-XF"), (2001, "93F0053XIF")],
)
async def test_get_download_link_french_legacy_uses_french_catalogue(year, catalogue):
    result = await client.get_download_link(year, "census_divisions", "csv", "fr")
    assert f"CTLG={catalogue}&" in result.url
