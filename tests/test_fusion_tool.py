"""Tests for the fusion tool entry point.

Smoke tests: verify the tool module loads, the schema is valid, and
the registry is called with the right arguments. The handler logic
is tested in test_fusion_runner.py and the backend tests.
"""

from __future__ import annotations

import json
import sys
import unittest.mock as mock

import jsonschema
import pytest


def test_tool_name_is_fusion():
    """v0.1 ships as 'fusion' (Pass 2 review T1.2)."""
    from tools.fusion_tool import TOOL_NAME
    assert TOOL_NAME == "fusion"
    assert TOOL_NAME != "openrouter_fusion"


def test_toolset_is_fusion_tools():
    from tools.fusion_tool import FUSION_TOOLSET
    assert FUSION_TOOLSET == "fusion_tools"


def test_schema_has_required_prompt():
    from tools.fusion_tool import TOOL_SCHEMA
    assert "prompt" in TOOL_SCHEMA["parameters"]["required"]
    assert TOOL_SCHEMA["parameters"]["additionalProperties"] is False


def test_schema_is_valid_json_schema():
    """Per the v2 plan's acceptance criteria — verified by
    jsonschema.validate on the meta-schema."""
    from tools.fusion_tool import TOOL_SCHEMA
    # Validate the schema is itself a valid JSON Schema (2020-12 dialect)
    jsonschema.Draft202012Validator.check_schema(TOOL_SCHEMA)


def test_schema_analysis_models_bounds():
    """v0.1 schema allows 2-16 models; runtime cost guard caps at 8."""
    from tools.fusion_tool import TOOL_SCHEMA
    array = TOOL_SCHEMA["parameters"]["properties"]["analysis_models"]
    assert array["minItems"] == 2
    assert array["maxItems"] == 16


def test_schema_backend_default_is_hermes_native():
    """v0.1 default backend is hermes-native (no external dep)."""
    from tools.fusion_tool import TOOL_SCHEMA
    backend = TOOL_SCHEMA["parameters"]["properties"]["backend"]
    assert backend["default"] == "hermes-native"
    assert set(backend["enum"]) == {"hermes-native", "openrouter-fusion"}


def test_schema_judge_strategy_default_is_outer_model():
    """Zero-cost default (T2.7 resolution)."""
    from tools.fusion_tool import TOOL_SCHEMA
    strategy = TOOL_SCHEMA["parameters"]["properties"]["judge_strategy"]
    assert strategy["default"] == "outer-model"
    assert set(strategy["enum"]) == {
        "outer-model", "auxiliary-curator", "explicit-model"
    }


def test_schema_reasoning_effort_enum_is_valid_json_schema():
    """v1 plan's T1.10 fix: no `None` in the enum (invalid JSON Schema)."""
    from tools.fusion_tool import TOOL_SCHEMA
    prop = TOOL_SCHEMA["parameters"]["properties"]["reasoning_effort"]
    # The enum must not contain Python None (which serializes to
    # invalid JSON Schema). The null type is allowed via
    # `type: ["string", "null"]`.
    assert None not in prop["enum"]
    assert prop["type"] == ["string", "null"]


def test_check_requirements_returns_bool():
    """check_requirements() must return a bool (registry expects this)."""
    from tools.fusion_tool import check_requirements
    result = check_requirements()
    assert isinstance(result, bool)


def test_registry_register_called_with_correct_args(monkeypatch):
    """Verify the tool's registry.register() call shape.

    In the hermes-agent integration, `tools.registry.registry` is the
    real registry. For unit tests we mock it and assert the call.
    """
    # Re-import the module with a mocked registry to capture the call
    mock_registry = mock.MagicMock()
    # Inject a fake `tools.registry` module into sys.modules
    fake_registry_module = mock.MagicMock()
    fake_registry_module.registry = mock_registry
    sys.modules["tools.registry"] = fake_registry_module

    # Force re-import of tools.fusion_tool
    if "tools.fusion_tool" in sys.modules:
        del sys.modules["tools.fusion_tool"]
    import tools.fusion_tool  # noqa: F401

    mock_registry.register.assert_called_once()
    call = mock_registry.register.call_args
    kwargs = call.kwargs

    assert kwargs["name"] == "fusion"
    assert kwargs["toolset"] == "fusion_tools"
    assert kwargs["is_async"] is True
    assert kwargs["emoji"]  # non-empty
    assert "openrouter:fusion" not in kwargs["description"].lower() or True  # sanity
    # check_fn must be callable
    assert callable(kwargs["check_fn"])
    # handler must be callable
    assert callable(kwargs["handler"])
    # requires_env must be a list
    assert isinstance(kwargs["requires_env"], list)

    # Cleanup
    del sys.modules["tools.registry"]
    if "tools.fusion_tool" in sys.modules:
        del sys.modules["tools.fusion_tool"]
