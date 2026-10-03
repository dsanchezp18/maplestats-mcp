from maplestats_mcp import config


def test_transport_defaults_to_stdio_for_local_mcp_clients(monkeypatch):
    monkeypatch.delenv("MAPLE_TRANSPORT", raising=False)

    assert config.get_transport() == "stdio"


def test_transport_can_be_set_to_http_for_hosting(monkeypatch):
    monkeypatch.setenv("MAPLE_TRANSPORT", "http")

    assert config.get_transport() == "http"


def test_delta_scan_ceiling_reads_megabytes_and_stays_under_the_tool_timeout(monkeypatch):
    monkeypatch.delenv("MAPLE_DELTA_MAX_SCAN_MB", raising=False)
    monkeypatch.delenv("MAPLE_DELTA_MAX_SCAN_SECONDS", raising=False)
    monkeypatch.delenv("MAPLE_TOOL_TIMEOUT_SECONDS", raising=False)
    assert config.get_delta_max_scan_bytes() == 400 * 1024 * 1024
    assert config.get_delta_max_scan_seconds() == 75.0
    monkeypatch.setenv("MAPLE_DELTA_MAX_SCAN_MB", "1500")
    assert config.get_delta_max_scan_bytes() == 1500 * 1024 * 1024
    monkeypatch.setenv("MAPLE_DELTA_MAX_SCAN_MB", "lots")
    assert config.get_delta_max_scan_bytes() == 400 * 1024 * 1024
    monkeypatch.setenv("MAPLE_DELTA_MAX_SCAN_SECONDS", "300")
    assert config.get_delta_max_scan_seconds() == 90.0
    monkeypatch.setenv("MAPLE_TOOL_TIMEOUT_SECONDS", "600")
    assert config.get_delta_max_scan_seconds() == 300.0


def test_delta_index_dir_can_be_turned_off(monkeypatch, tmp_path):
    monkeypatch.setenv("MAPLE_DELTA_INDEX_DIR", "off")
    assert config.get_delta_index_dir() is None
    monkeypatch.setenv("MAPLE_DELTA_INDEX_DIR", str(tmp_path))
    assert config.get_delta_index_dir() == tmp_path
