"""Tests for the fusion tool stub.

These are intentionally minimal — they verify the tool registers,
the schema validates, and the stub returns a deterministic shape. The
real test suite (covering backend-agnostic runner, hermes-native
backend, openrouter-fusion backend, judge invocation, partial-failure
paths) lands with the implementation PR, per
docs/plans/2026-06-13-fusion-tool-design.md §7.
"""

from __future__ import annotations

import json

import pytest


def test_stub_returns_expected_shape():
    from tools.fusion_tool import fusion_stub

    result = fusion_stub(prompt="hello", analysis_models=["a/b", "c/d"])
    parsed = json.loads(result)

    assert parsed["stub"] is True
    assert "implement per" in parsed["message"]
    assert "prompt" in parsed["received_kwargs_keys"]
    assert "analysis_models" in parsed["received_kwargs_keys"]


def test_schema_has_required_prompt_field():
    from tools.fusion_tool import TOOL_SCHEMA

    assert "prompt" in TOOL_SCHEMA["parameters"]["required"]
    # No unknown top-level properties
    assert TOOL_SCHEMA["parameters"]["additionalProperties"] is False


def test_analysis_models_bounds():
    """v0.1 schema allows 2-16 models; runtime cost guard caps at 8."""
    from tools.fusion_tool import TOOL_SCHEMA

    array_schema = TOOL_SCHEMA["parameters"]["properties"]["analysis_models"]
    assert array_schema["minItems"] == 2
    assert array_schema["maxItems"] == 16


def test_tool_name_is_fusion_not_openrouter_fusion():
    """v0.1 ships as 'fusion' (Pass 2 review T1.2)."""
    from tools.fusion_tool import TOOL_NAME

    assert TOOL_NAME == "fusion"
    assert TOOL_NAME != "openrouter_fusion"


def test_toolset_key_is_fusion_tools():
    from tools.fusion_tool import FUSION_TOOLSET

    assert FUSION_TOOLSET == "fusion_tools"


def test_backend_default_is_hermes_native():
    """v0.1 default backend is hermes-native (no external dep)."""
    from tools.fusion_tool import TOOL_SCHEMA

    backend = TOOL_SCHEMA["parameters"]["properties"]["backend"]
    assert backend["default"] == "hermes-native"
    assert "openrouter-fusion" in backend["enum"]


def test_judge_strategy_default_is_outer_model():
    """Zero-cost default (T2.7 resolution)."""
    from tools.fusion_tool import TOOL_SCHEMA

    strategy = TOOL_SCHEMA["parameters"]["properties"]["judge_strategy"]
    assert strategy["default"] == "outer-model"


def test_check_requirements_does_not_crash_without_openrouter_key(monkeypatch):
    """The stub's check_requirements should not raise; the real
    check is in the implementation (T1.7: >= 2 fallback_providers)."""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    import importlib
    import tools.fusion_tool as ft
    importlib.reload(ft)
    # Stub returns True; real implementation returns False when
    # the fallback chain has fewer than 2 entries.
    assert ft.check_requirements() is True
