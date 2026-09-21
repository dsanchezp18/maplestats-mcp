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
