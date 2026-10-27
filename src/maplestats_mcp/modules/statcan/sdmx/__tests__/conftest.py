"""SDMX data calls decode observation flags with WDS getCodeSets; reuse the
WDS tests' optional mock of it."""

from maplestats_mcp.modules.statcan.wds.__tests__.conftest import _code_sets  # noqa: F401
