import logging

import pytest

from maplestats_mcp import __version__, config


def test_transport_defaults_to_stdio_for_local_mcp_clients(monkeypatch):
    monkeypatch.delenv("MAPLE_TRANSPORT", raising=False)
    monkeypatch.setattr(config, "_serves_http", False)

    assert config.get_transport() == "stdio"


def test_a_process_serving_http_without_the_variable_is_http(monkeypatch):
    # `uvicorn maplestats_mcp.asgi:app` sets no MAPLE_TRANSPORT.
    monkeypatch.delenv("MAPLE_TRANSPORT", raising=False)
    monkeypatch.setattr(config, "_serves_http", False)
    config.mark_serving_http()

    assert config.get_transport() == "http"


def test_the_variable_wins_over_a_process_serving_http(monkeypatch):
    monkeypatch.setattr(config, "_serves_http", True)
    monkeypatch.setenv("MAPLE_TRANSPORT", "stdio")

    assert config.get_transport() == "stdio"


def test_transport_can_be_set_to_http_for_hosting(monkeypatch):
    monkeypatch.setenv("MAPLE_TRANSPORT", "http")

    assert config.get_transport() == "http"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("stdio", "stdio"), ("Stdio", "stdio"), (" HTTP ", "http"), ("http", "http")],
)
def test_transport_ignores_case_and_surrounding_spaces(monkeypatch, raw, expected):
    monkeypatch.setenv("MAPLE_TRANSPORT", raw)

    assert config.get_transport() == expected


@pytest.mark.parametrize("raw", ["sdtio", "stdioo", "sse", "streamable-http", ""])
def test_unknown_transport_raises_instead_of_starting_a_http_server(monkeypatch, raw):
    monkeypatch.setenv("MAPLE_TRANSPORT", raw)

    with pytest.raises(ValueError, match="MAPLE_TRANSPORT"):
        config.get_transport()


def test_server_annotations_read_the_validated_transport(monkeypatch):
    from maplestats_mcp.server import _export_annotations

    monkeypatch.setenv("MAPLE_TRANSPORT", "http")
    assert _export_annotations().read_only_hint is True
    monkeypatch.setenv("MAPLE_TRANSPORT", "stdio")
    assert _export_annotations().read_only_hint is False
    monkeypatch.setenv("MAPLE_TRANSPORT", "sdtio")
    with pytest.raises(ValueError, match="MAPLE_TRANSPORT"):
        _export_annotations()


def test_port_defaults_and_parses(monkeypatch):
    monkeypatch.delenv("MAPLE_PORT", raising=False)
    assert config.get_port() == 8000
    monkeypatch.setenv("MAPLE_PORT", "")
    assert config.get_port() == 8000
    monkeypatch.setenv("MAPLE_PORT", " 9001 ")
    assert config.get_port() == 9001


def test_unparsable_port_raises_instead_of_binding_the_default(monkeypatch):
    # "80OO" (letter O) used to bind 8000 while the healthcheck probed "80OO".
    monkeypatch.setenv("MAPLE_PORT", "80OO")

    with pytest.raises(ValueError, match="MAPLE_PORT='80OO'"):
        config.get_port()


_NUMERIC_GETTERS = [
    ("MAPLE_MAX_CONCURRENT_REQUESTS", config.get_max_concurrent_requests, 8),
    ("MAPLE_RATE_LIMIT_REQUESTS", config.get_rate_limit_requests, 120),
    ("MAPLE_RATE_LIMIT_WINDOW_SECONDS", config.get_rate_limit_window_seconds, 60.0),
    ("MAPLE_CACHE_MAX_ENTRIES", config.get_cache_max_entries, 2000),
    ("MAPLE_CACHE_MAX_MB", config.get_cache_max_bytes, 128 * 1024**2),
    ("MAPLE_TOOL_TIMEOUT_SECONDS", config.get_tool_timeout_seconds, 120.0),
    ("MAPLE_PARSE_WORKERS", config.get_parse_workers, 4),
    ("MAPLE_PARSE_TIMEOUT_SECONDS", config.get_parse_timeout_seconds, 60.0),
    ("MAPLE_PUMF_CACHE_MAX_GB", config.get_pumf_cache_max_bytes, 5 * 1024**3),
    ("MAPLE_DELTA_MAX_SCAN_MB", config.get_delta_max_scan_bytes, 400 * 1024 * 1024),
    ("MAPLE_DELTA_MAX_SCAN_SECONDS", config.get_delta_max_scan_seconds, 75.0),
    ("MAPLE_IP_HORIZONS_CACHE_MAX_GB", config.get_ip_horizons_cache_max_bytes, 3 * 1024**3),
    ("MAPLE_LODE_CACHE_MAX_GB", config.get_lode_cache_max_bytes, 3 * 1024**3),
    ("MAPLE_ON_FIR_CACHE_MAX_MB", config.get_on_fir_cache_max_bytes, 500 * 1024**2),
    ("MAPLE_LODE_MAX_DOWNLOAD_MB", lambda: config.get_lode_max_download_bytes(250), 250_000_000),
    ("MAPLE_TRUSTED_PROXY_HOPS", config.get_trusted_proxy_hops, 1),
]


def _config_warnings(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.name == "maplestats_mcp.config"]


@pytest.mark.parametrize(("name", "getter", "default"), _NUMERIC_GETTERS)
def test_unparsable_number_warns_once_and_uses_the_default(
    monkeypatch, caplog, name, getter, default
):
    monkeypatch.setattr(config, "_warned", set())
    monkeypatch.delenv("MAPLE_TOOL_TIMEOUT_SECONDS", raising=False)
    monkeypatch.setenv(name, "12 lots")
    with caplog.at_level(logging.WARNING, logger="maplestats_mcp.config"):
        assert getter() == default
        assert getter() == default
    warnings = _config_warnings(caplog)
    assert len(warnings) == 1
    assert name in warnings[0] and "'12 lots'" in warnings[0]


@pytest.mark.parametrize(("name", "getter", "default"), _NUMERIC_GETTERS)
def test_unset_or_empty_number_uses_the_default_quietly(monkeypatch, caplog, name, getter, default):
    monkeypatch.setattr(config, "_warned", set())
    monkeypatch.delenv("MAPLE_TOOL_TIMEOUT_SECONDS", raising=False)
    with caplog.at_level(logging.WARNING, logger="maplestats_mcp.config"):
        monkeypatch.delenv(name, raising=False)
        assert getter() == default
        monkeypatch.setenv(name, "  ")
        assert getter() == default
    assert _config_warnings(caplog) == []


def test_version_flag_prints_the_version_and_exits_zero(capsys):
    from maplestats_mcp.__main__ import main

    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])

    assert exit_info.value.code == 0
    assert capsys.readouterr().out.strip() == __version__


def test_no_arguments_still_start_the_stdio_server(monkeypatch):
    from maplestats_mcp import server
    from maplestats_mcp.__main__ import main

    started: list[dict] = []
    monkeypatch.setenv("MAPLE_TRANSPORT", "stdio")
    monkeypatch.setattr(server.mcp, "run", lambda **kwargs: started.append(kwargs))

    main([])

    assert started == [{"transport": "stdio"}]


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


def test_breaker_settings_default_clamp_and_turn_off(monkeypatch):
    for name in (
        "MAPLE_BREAKER",
        "MAPLE_BREAKER_FAILURES",
        "MAPLE_BREAKER_WINDOW_SECONDS",
        "MAPLE_BREAKER_COOLDOWN_SECONDS",
    ):
        monkeypatch.delenv(name, raising=False)
    assert config.get_breaker_enabled() is True
    assert config.get_breaker_failures() == 5
    assert config.get_breaker_window_seconds() == 300.0
    assert config.get_breaker_cooldown_seconds() == 60.0
    monkeypatch.setenv("MAPLE_BREAKER", "off")
    assert config.get_breaker_enabled() is False
    monkeypatch.setenv("MAPLE_BREAKER_FAILURES", "0")
    assert config.get_breaker_failures() == 1
    monkeypatch.setenv("MAPLE_BREAKER_COOLDOWN_SECONDS", "99999")
    assert config.get_breaker_cooldown_seconds() == 3600.0
