from maplestats_mcp import config


def test_transport_defaults_to_stdio_for_local_mcp_clients(monkeypatch):
    monkeypatch.delenv("MAPLE_TRANSPORT", raising=False)

    assert config.get_transport() == "stdio"


def test_transport_can_be_set_to_http_for_hosting(monkeypatch):
    monkeypatch.setenv("MAPLE_TRANSPORT", "http")

    assert config.get_transport() == "http"
