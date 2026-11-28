"""Recorded inputs for new Maple Test runs; old evidence is never reconstructed."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

# Local source behaviour and resource budgets. Keep this explicit: copying an entire
# environment would also copy credentials. Unset values use the recorded source's defaults.
SOURCE_OPTIONS = (
    "MAPLE_TRANSPORT",
    "MAPLE_STATCAN_FALLBACK",
    "MAPLE_QUERY_SERIES",
    "MAPLE_RESPONSE_MAX_BYTES",
    "MAPLE_TOOL_TIMEOUT_SECONDS",
    "MAPLE_QUERY_MEMORY_MB",
    "MAPLE_QUERY_MAX_CONCURRENT",
    "MAPLE_PARSE_TIMEOUT_SECONDS",
    "MAPLE_PARSE_WORKERS",
    "MAPLE_MAX_CONCURRENT_REQUESTS",
    "MAPLE_MAX_REQUESTS_PER_CLIENT",
    "MAPLE_RATE_LIMIT_REQUESTS",
    "MAPLE_RATE_LIMIT_WINDOW_SECONDS",
    "MAPLE_BREAKER",
    "MAPLE_BREAKER_FAILURES",
    "MAPLE_BREAKER_WINDOW_SECONDS",
    "MAPLE_BREAKER_COOLDOWN_SECONDS",
    "MAPLE_CACHE_MAX_ENTRIES",
    "MAPLE_CACHE_MAX_MB",
    "MAPLE_LAST_GOOD_MB",
    "MAPLE_SEARCH",
    "MAPLE_SEMANTIC_DIR",
    "MAPLE_GIS",
    "MAPLE_PRELOAD",
    "MAPLE_OCR",
    "MAPLE_OCR_MEMORY_MB",
    "MAPLE_PUMF_TABULATE",
    "MAPLE_PUMF_CACHE_DIR",
    "MAPLE_PUMF_CACHE_MAX_GB",
    "MAPLE_DELTA_INDEX_DIR",
    "MAPLE_DELTA_MAX_SCAN_MB",
    "MAPLE_DELTA_MAX_SCAN_SECONDS",
    "MAPLE_DUCKDB_MEMORY_LIMIT",
    "MAPLE_DUCKDB_TEMP_DIR",
    "MAPLE_DUCKDB_TEMP_MAX_GB",
    "MAPLE_IP_HORIZONS_CACHE_DIR",
    "MAPLE_IP_HORIZONS_CACHE_MAX_GB",
    "MAPLE_LODE_CACHE_DIR",
    "MAPLE_LODE_CACHE_MAX_GB",
    "MAPLE_LODE_MAX_DOWNLOAD_MB",
    "MAPLE_CBSA_TARIFF_CACHE_DIR",
    "MAPLE_ON_FIR_CACHE_DIR",
    "MAPLE_ON_FIR_CACHE_MAX_MB",
    "MAPLE_CENSUS_CACHE_DIR",
    "MAPLE_EXPORT_DIR",
    "FROZEN_MODE",
    "PYTHONPATH",
    "TESSDATA_PREFIX",
)


def digest(value: Any) -> str:
    """Hash JSON values, independent of indentation or object-key order."""
    raw = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def file_digest(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def manifest_path(path: Path) -> Path:
    return path.with_suffix(".manifest.json")


def _command(args: list[str]) -> str | None:
    try:
        result = subprocess.run(args, capture_output=True, timeout=5, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return (
        result.stdout.decode("utf-8", errors="replace").strip() if result.returncode == 0 else None
    )


def checkout(path: Path, scope: tuple[str, ...] = ()) -> dict[str, Any]:
    """Identify an available checkout, without reading remotes or credential settings."""
    command = ["git", "-C", str(path)]
    commit = _command([*command, "rev-parse", "HEAD"])
    patch = _command([*command, "diff", "--binary", "HEAD", "--", *scope]) if commit else None
    return {
        "path": str(path.resolve()),
        "commit": commit,
        "tracked_changes_sha256": digest(patch) if patch is not None else None,
        "scope": list(scope) or ["tracked files"],
        "lock_sha256": file_digest(path / "uv.lock"),
    }


def environment(repo: Path) -> dict[str, Any]:
    cli = shutil.which("claude")
    files = ("tests/maple_test/run.py", "tests/maple_test/inputs.py", "pyproject.toml", "uv.lock")
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "claude_version": _command([cli, "--version"]) if cli else None,
        "harness_commit": _command(["git", "-C", str(repo), "rev-parse", "HEAD"]),
        "harness_files_sha256": {name: file_digest(repo / name) for name in files},
    }


def public_configuration(servers: dict[str, Any]) -> dict[str, Any]:
    """Keep public launch arguments and allowlisted effective local source options.

    URLs may come from MAPLE_HOSTED_URL: remove credentials, queries and fragments.
    Tokens used to authenticate the same endpoint may rotate between resumed sessions.
    """

    def public(value: str) -> str:
        if value.startswith(("http://", "https://")):
            parts = urlsplit(value)
            return urlunsplit((parts.scheme, parts.netloc.rsplit("@", 1)[-1], parts.path, "", ""))
        return value

    return {
        name: {
            **{k: public(v) for k, v in spec.items() if k in ("type", "command", "url")},
            **({"args": [public(v) for v in spec["args"]]} if "args" in spec else {}),
            "environment_keys": sorted(spec.get("env", {})),
            "header_keys": sorted(spec.get("headers", {})),
            "source_options": {
                option: spec.get("env", {}).get(option, os.environ.get(option))
                for option in SOURCE_OPTIONS
            }
            if "command" in spec
            else {},
        }
        for name, spec in servers.items()
    }


def make_manifest(
    path: Path,
    *,
    version: str,
    created_at: str,
    key: dict[str, Any],
    prompt_template: str,
    settings: dict[str, Any],
    planned_jobs: list[tuple[str, int]],
    execution: dict[str, Any],
) -> dict[str, Any]:
    record = {
        "schema_version": 1,
        "run_file": path.name,
        "benchmark_version": version,
        "created_at": created_at,
        "key": key,
        "key_sha256": digest(key),
        "prompt_template": prompt_template,
        "system_prompt": prompt_template.format(today=created_at[:10]),
        "settings": settings,
        "planned_jobs": [[qid, repeat] for qid, repeat in planned_jobs],
        "execution": execution,
    }
    return {**record, "manifest_sha256": digest(record)}


def write_manifest(path: Path, record: dict[str, Any]) -> None:
    # A crash may leave a sidecar without answers. Never replace that evidence either.
    try:
        stream = manifest_path(path).open("x", encoding="utf-8", newline="\n")
    except FileExistsError as exc:
        raise ValueError(
            f"Manifest already exists for {path.name}; preserve it and start a new --label"
        ) from exc
    with stream:
        json.dump(record, stream, indent=2, ensure_ascii=False)
        stream.write("\n")


def read_manifest(path: Path, version: str) -> dict[str, Any] | None:
    sidecar = manifest_path(path)
    if not sidecar.exists():
        return None
    try:
        record = json.loads(sidecar.read_text(encoding="utf-8"))
        payload = {k: v for k, v in record.items() if k != "manifest_sha256"}
        questions = record["key"]["questions"]
        ids = [q["id"] for q in questions]
        valid = (
            record["schema_version"] == 1
            and record["run_file"] == path.name
            and record["benchmark_version"] == version
            and record["manifest_sha256"] == digest(payload)
            and record["key_sha256"] == digest(record["key"])
            and len(ids) == len(set(ids))
            and all(isinstance(qid, str) for qid in ids)
            and isinstance(record["settings"], dict)
            and isinstance(record["settings"]["label"], str)
            and isinstance(record["settings"]["model"], str)
            and isinstance(record["execution"], dict)
            and record["system_prompt"]
            == record["prompt_template"].format(today=record["created_at"][:10])
            and all(
                qid in ids and type(repeat) is int and repeat >= 0
                for qid, repeat in record["planned_jobs"]
            )
            and len(record["planned_jobs"]) == len({tuple(job) for job in record["planned_jobs"]})
        )
    except (AttributeError, IndexError, KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"Invalid run manifest: {sidecar}") from exc
    if not valid:
        raise ValueError(f"Invalid or mismatched run manifest: {sidecar}")
    return record


def validate_rows(path: Path, rows: list[dict[str, Any]], record: dict[str, Any] | None) -> None:
    if record is None:
        if any(row.get("manifest_sha256") for row in rows):
            raise ValueError(f"{path.name}: recorded manifest is missing; restore its sidecar")
        return
    planned = {tuple(job) for job in record["planned_jobs"]}
    seen: set[tuple[str, int]] = set()
    for row in rows:
        job = (row.get("question_id", ""), row.get("repeat", 0))
        if (
            row.get("manifest_sha256") != record["manifest_sha256"]
            or row.get("arm") != record["settings"]["label"]
            or row.get("requested_model") != record["settings"]["model"]
            or job not in planned
            or job in seen
        ):
            raise ValueError(f"{path.name}: answer does not match its recorded inputs: {job}")
        seen.add(job)


def check_resume(saved: dict[str, Any], candidate: dict[str, Any]) -> None:
    changed = [k for k in saved if k != "manifest_sha256" and saved[k] != candidate.get(k)]
    if changed:
        raise ValueError(
            "Cannot resume with changed inputs ("
            + ", ".join(changed)
            + "); restore the recorded inputs or start a new --label"
        )


def report_notes(report: dict[str, Any]) -> list[str]:
    """The JSON report holds full hashes; its Markdown must disclose their scope too."""
    provenance = report.get("input_provenance")
    if not provenance:
        return []
    lines = ["", "## Grading inputs", ""]
    lines += [f"- {note}" for note in provenance["notes"]]
    lines += [
        "",
        f"Key SHA-256: `{provenance['key_sha256']}`.",
        f"Overrides SHA-256: `{provenance['overrides_sha256']}`.",
        f"Citation-cache SHA-256: `{provenance['citation_cache_sha256']}`.",
    ]
    return lines
