"""Tests for the openrouter_fusion tool stub.

These are intentionally minimal — they verify the tool registers,
the schema validates, and the stub returns a deterministic shape. The
real test suite (covering OpenRouter pass-through, recursion guard,
judge-degradation, cost guard) lands with the implementation PR, per
docs/plans/2026-06-13-fusion-tool-design.md §7.
"""

from __future__ import annotations

import json

import pytest


def test_stub_returns_expected_shape():
    from tools.fusion_tool import openrouter_fusion_stub

    result = openrouter_fusion_stub(prompt="hello", analysis_models=["a/b"])
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
    from tools.fusion_tool import TOOL_SCHEMA

    array_schema = TOOL_SCHEMA["parameters"]["properties"]["analysis_models"]
    assert array_schema["minItems"] == 1
    assert array_schema["maxItems"] == 8


def test_toolset_key_is_fusion_tools():
    from tools.fusion_tool import FUSION_TOOLSET

    assert FUSION_TOOLSET == "fusion_tools"


def test_check_requirements_returns_false_when_no_key(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    # Re-import to pick up the env-var check at call time
    import importlib
    import tools.fusion_tool as ft
    importlib.reload(ft)
    assert ft.check_requirements() is False
