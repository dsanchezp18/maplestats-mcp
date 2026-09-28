"""Tests for ckan tools.py dispatch in ckan_get_organization_or_group."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

from maplestats_mcp.modules.ckan import tools
from maplestats_mcp.modules.ckan.schemas import GroupDetail, OrganizationDetail
from maplestats_mcp.shared.models import Provenance


def _prov() -> Provenance:
    return Provenance(
        source="ckan",
        url="https://example.invalid",
        queried_at=datetime.now(UTC),
        cached=False,
        schema_name="ckan.x",
    )


async def test_get_organization_or_group_dispatches(monkeypatch):
    org = OrganizationDetail(
        portal="federal",
        id="1",
        name="statcan",
        title="StatCan",
        landing_page_url="https://x",
        provenance=_prov(),
    )
    grp = GroupDetail(portal="bc", id="2", name="health", title="Health", provenance=_prov())
    monkeypatch.setattr(tools.client, "get_organization", AsyncMock(return_value=org))
    monkeypatch.setattr(tools.client, "get_group", AsyncMock(return_value=grp))

    r1 = await tools.ckan_get_organization_or_group("federal", "organization", "statcan")
    assert r1.kind == "organization" and r1.name == "statcan"
    assert r1.landing_page_url == "https://x"
    r2 = await tools.ckan_get_organization_or_group("bc", "group", "health")
    assert r2.kind == "group" and r2.landing_page_url is None
