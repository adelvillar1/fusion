"""Tests for the hermes-native backend.

Covers: per-member-FAIL (T2.1), asyncio.gather with return_exceptions=True
(T1.3), check_requirements (T1.7), PanelResponse shape.
"""

from __future__ import annotations

import asyncio
import unittest.mock as mock

import pytest

from tools.fusion.backends.base import PanelRequest
from tools.fusion.backends.hermes_native import (
    HermesNativeBackend,
    _call_single_model,
)


def _make_request(analysis_models: list[str] | None = None) -> PanelRequest:
    return PanelRequest(
        prompt="Test prompt",
        analysis_models=analysis_models or ["a", "b", "c"],
        timeout_seconds=10,
    )


# ---------------------------------------------------------------------------
# ABC conformance
# ---------------------------------------------------------------------------


def test_hermes_native_is_a_fusion_backend():
    from tools.fusion.backends.base import FusionBackend
    backend = HermesNativeBackend()
    assert isinstance(backend, FusionBackend)
    assert backend.name == "hermes-native"


def test_check_requirements_returns_bool():
    """T1.7: check_requirements returns True in v0.1 stub (real impl in v0.2)."""
    backend = HermesNativeBackend()
    assert isinstance(backend.check_requirements(), bool)


# ---------------------------------------------------------------------------
# Panel fan-out (the critical T1.3 path)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_panel_all_succeed(monkeypatch):
    """When all panel members succeed, all responses are returned."""
    monkeypatch.setattr(
        "tools.fusion.backends.hermes_native._call_single_model",
        lambda model, req: f"OK from {model}",
    )
    backend = HermesNativeBackend()
    resp = await backend.run_panel(
        _make_request(["a", "b", "c"]),
        outer_model="outer",
        judge_model="judge",
    )
    assert len(resp.responses) == 3
    assert len(resp.failed_models) == 0
    assert {r["model"] for r in resp.responses} == {"a", "b", "c"}


@pytest.mark.asyncio
async def test_run_panel_partial_failure_preserves_successes(monkeypatch):
    """T1.3 (critical) + T2.1: a single panel member's failure does
    NOT lose the other responses. The failed member appears in
    `failed_models`."""
    call_count = {"n": 0}

    def fake_call(model, req):
        call_count["n"] += 1
        if model == "b":
            raise RuntimeError("simulated model b failure")
        return f"OK from {model}"

    monkeypatch.setattr(
        "tools.fusion.backends.hermes_native._call_single_model",
        fake_call,
    )
    backend = HermesNativeBackend()
    resp = await backend.run_panel(
        _make_request(["a", "b", "c"]),
        outer_model="outer",
        judge_model="judge",
    )

    # 2 succeeded, 1 failed — the succeeded ones are preserved
    assert len(resp.responses) == 2
    assert len(resp.failed_models) == 1
    assert {r["model"] for r in resp.responses} == {"a", "c"}
    failed = resp.failed_models[0]
    assert failed["model"] == "b"
    assert "RuntimeError" in failed["reason"]
    assert "simulated model b failure" in failed["reason"]


@pytest.mark.asyncio
async def test_run_panel_all_fail(monkeypatch):
    """When all panel members fail, no responses, all in failed_models."""

    def fake_call(model, req):
        raise RuntimeError(f"all-fail: {model}")

    monkeypatch.setattr(
        "tools.fusion.backends.hermes_native._call_single_model",
        fake_call,
    )
    backend = HermesNativeBackend()
    resp = await backend.run_panel(
        _make_request(["a", "b"]),
        outer_model="outer",
        judge_model="judge",
    )
    assert resp.responses == []
    assert len(resp.failed_models) == 2
    assert {f["model"] for f in resp.failed_models} == {"a", "b"}


@pytest.mark.asyncio
async def test_run_panel_per_member_fail_not_substitute(monkeypatch):
    """T2.1: a failed member is reported, not silently substituted
    with another model."""
    seen_models: list[str] = []

    def fake_call(model, req):
        seen_models.append(model)
        if model == "x":
            raise RuntimeError("x failed")
        return f"OK from {model}"

    monkeypatch.setattr(
        "tools.fusion.backends.hermes_native._call_single_model",
        fake_call,
    )
    backend = HermesNativeBackend()
    await backend.run_panel(
        _make_request(["a", "x", "b"]),
        outer_model="outer",
        judge_model="judge",
    )
    # Each requested model was tried exactly once — no substitution
    assert sorted(seen_models) == ["a", "b", "x"]


@pytest.mark.asyncio
async def test_run_panel_backend_does_not_populate_analysis(monkeypatch):
    """T1.1: the backend's `run_panel` leaves `analysis` and
    `raw_judge_output` empty. The runner fills them in."""
    monkeypatch.setattr(
        "tools.fusion.backends.hermes_native._call_single_model",
        lambda model, req: "ok",
    )
    backend = HermesNativeBackend()
    resp = await backend.run_panel(
        _make_request(["a"]),
        outer_model="outer",
        judge_model="judge",
    )
    assert resp.analysis is None
    assert resp.raw_judge_output is None


@pytest.mark.asyncio
async def test_run_panel_uses_gather_with_return_exceptions(monkeypatch):
    """T1.3 critical: gather(return_exceptions=True) is the key
    safety property. This test asserts it by injecting a mix of
    successes and failures and verifying NO response is lost."""
    import asyncio

    async def fast_call(model, req):
        if model == "slow":
            await asyncio.sleep(0.5)  # long but within timeout
        return f"OK {model}"

    # Patch _call_single_model to be an async function via to_thread
    import tools.fusion.backends.hermes_native as mod

    monkeypatch.setattr(
        mod,
        "_call_single_model",
        # Simulate the real path: asyncio.to_thread wrapping sync fn
        lambda model, req: fast_call_sync(model, req) if False else None,
    )
    # Simpler: directly mock the inner function. The real impl uses
    # asyncio.to_thread; we replicate that semantics in the patch.
    def sync_call(model, req):
        if model == "b":
            raise RuntimeError("b fail")
        return f"OK {model}"

    monkeypatch.setattr(mod, "_call_single_model", sync_call)
    backend = HermesNativeBackend()
    resp = await backend.run_panel(
        _make_request(["a", "b", "c"]),
        outer_model="o",
        judge_model="j",
    )
    # Both 'a' and 'c' must be present even though 'b' raised
    models_returned = {r["model"] for r in resp.responses}
    assert models_returned == {"a", "c"}, (
        f"Expected a+c to survive b's failure; got {models_returned}"
    )


# ---------------------------------------------------------------------------
# Stub _call_single_model
# ---------------------------------------------------------------------------


def test_call_single_model_stub_returns_deterministic_fake():
    """v0.1 stub: returns a deterministic string per model."""
    req = PanelRequest(
        prompt="Tell me a joke", analysis_models=["claude-3"], timeout_seconds=5
    )
    out = _call_single_model("claude-3", req)
    assert "claude-3" in out
    assert "Tell me a joke" in out


# Async test infrastructure
@pytest.fixture
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()
