"""Tests for the openrouter-fusion backend.

Uses `unittest.mock` to stub `httpx.AsyncClient` — no live network
calls (per the Hermes skill standards at ~/.hermes/hermes-agent/AGENTS.md:921).
"""

from __future__ import annotations

import json
import os
import unittest.mock as mock

import pytest

from tools.fusion.backends.base import PanelRequest
from tools.fusion.backends.openrouter_fusion import (
    OpenRouterFusionBackend,
    OPENROUTER_API_URL,
)


def _make_request() -> PanelRequest:
    return PanelRequest(
        prompt="What is the capital of France?",
        analysis_models=["anthropic/claude-opus-4.6", "openai/gpt-5.4-pro"],
        max_tool_calls=8,
        timeout_seconds=10,
    )


# ---------------------------------------------------------------------------
# ABC conformance + requirements
# ---------------------------------------------------------------------------


def test_openrouter_fusion_is_a_fusion_backend():
    from tools.fusion.backends.base import FusionBackend
    backend = OpenRouterFusionBackend()
    assert isinstance(backend, FusionBackend)
    assert backend.name == "openrouter-fusion"


def test_check_requirements_false_without_api_key(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    backend = OpenRouterFusionBackend()
    assert backend.check_requirements() is False


def test_check_requirements_true_with_api_key(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-fake-test-key")
    backend = OpenRouterFusionBackend()
    assert backend.check_requirements() is True


# ---------------------------------------------------------------------------
# Wire format (T1.8: optional verification)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_panel_constructs_correct_request_body(monkeypatch):
    """Verify the body sent to OpenRouter has the expected fusion shape."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-fake")

    captured: dict = {}

    class _MockResponse:
        status_code = 200

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "status": "ok",
                                    "responses": [
                                        {"model": "m1", "content": "r1"},
                                    ],
                                    "analysis": {"consensus": ["r1"]},
                                }
                            )
                        }
                    }
                ]
            }

    class _MockClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

        async def post(self, url, json=None, headers=None):
            captured["url"] = url
            captured["body"] = json
            captured["headers"] = headers
            return _MockResponse()

    monkeypatch.setattr(
        "tools.fusion.backends.openrouter_fusion.httpx.AsyncClient",
        _MockClient,
    )

    backend = OpenRouterFusionBackend()
    resp = await backend.run_panel(
        _make_request(),
        outer_model="anthropic/claude-sonnet-4.6",
        judge_model="anthropic/claude-sonnet-4.6",
    )

    # URL is correct
    assert captured["url"] == OPENROUTER_API_URL
    # Body has the fusion tool enabled
    body = captured["body"]
    assert "tools" in body
    assert body["tools"][0]["type"] == "openrouter:fusion"
    # tool_choice is always "required" (v0.1 contract)
    assert body["tool_choice"] == "required"
    # analysis_models are passed
    assert body["tools"][0]["parameters"]["analysis_models"] == [
        "anthropic/claude-opus-4.6", "openai/gpt-5.4-pro"
    ]
    # Auth header set
    assert captured["headers"]["Authorization"] == "Bearer sk-fake"
    # Server-side recursion guard header (best-effort)
    assert captured["headers"].get("x-openrouter-fusion-depth") == "1"

    # Response parsed
    assert len(resp.responses) == 1
    assert resp.responses[0]["model"] == "m1"
    assert resp.analysis == {"consensus": ["r1"]}


@pytest.mark.asyncio
async def test_run_panel_handles_error_status(monkeypatch):
    """OpenRouter status:error → all-failed response with error_reason."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-fake")

    class _MockResponse:
        status_code = 200

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "status": "error",
                                    "error_reason": "all_panels_failed",
                                }
                            )
                        }
                    }
                ]
            }

    class _MockClient:
        def __init__(self, *a, **kw):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            return None
        async def post(self, *a, **kw):
            return _MockResponse()

    monkeypatch.setattr(
        "tools.fusion.backends.openrouter_fusion.httpx.AsyncClient",
        _MockClient,
    )

    backend = OpenRouterFusionBackend()
    resp = await backend.run_panel(
        _make_request(),
        outer_model="x",
        judge_model="y",
    )
    assert resp.responses == []
    assert len(resp.failed_models) == 1
    assert "all_panels_failed" in resp.failed_models[0]["reason"]


@pytest.mark.asyncio
async def test_run_panel_handles_http_error(monkeypatch):
    """Non-200 HTTP → all-failed response with HTTP status."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-fake")

    class _MockResponse:
        status_code = 402
        text = "Out of credits"

        def json(self):
            raise json.JSONDecodeError("err", "x", 0)

    class _MockClient:
        def __init__(self, *a, **kw):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            return None
        async def post(self, *a, **kw):
            return _MockResponse()

    monkeypatch.setattr(
        "tools.fusion.backends.openrouter_fusion.httpx.AsyncClient",
        _MockClient,
    )

    backend = OpenRouterFusionBackend()
    resp = await backend.run_panel(
        _make_request(),
        outer_model="x",
        judge_model="y",
    )
    assert resp.responses == []
    assert "402" in resp.failed_models[0]["reason"]


@pytest.mark.asyncio
async def test_run_panel_handles_tool_call_response(monkeypatch):
    """OpenRouter may return the fusion result in tool_calls[0].function.arguments
    rather than message.content (the outer model called the tool itself)."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-fake")

    class _MockResponse:
        status_code = 200

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "tool_calls": [
                                {
                                    "function": {
                                        "name": "openrouter:fusion",
                                        "arguments": json.dumps(
                                            {
                                                "status": "ok",
                                                "responses": [
                                                    {"model": "m1", "content": "from tool_call"},
                                                ],
                                                "analysis": {"consensus": ["x"]},
                                            }
                                        ),
                                    }
                                }
                            ]
                        }
                    }
                ]
            }

    class _MockClient:
        def __init__(self, *a, **kw):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            return None
        async def post(self, *a, **kw):
            return _MockResponse()

    monkeypatch.setattr(
        "tools.fusion.backends.openrouter_fusion.httpx.AsyncClient",
        _MockClient,
    )

    backend = OpenRouterFusionBackend()
    resp = await backend.run_panel(
        _make_request(),
        outer_model="x",
        judge_model="y",
    )
    assert len(resp.responses) == 1
    assert resp.responses[0]["content"] == "from tool_call"
    assert resp.analysis == {"consensus": ["x"]}
