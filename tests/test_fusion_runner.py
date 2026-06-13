"""Tests for the FusionRunner — backend-agnostic orchestration.

Covers: recursion guard, cost guard, backend selection, judge strategy
resolution, judge invocation assembly (T1.1: runner owns the judge).
"""

from __future__ import annotations

import asyncio
import unittest.mock as mock

import pytest

from tools.fusion.backends.base import (
    FusionBackend,
    PanelRequest,
    PanelResponse,
)
from tools.fusion.runner import (
    FusionRunner,
    FusionConfig,
    _fusion_depth,
)


# ---------------------------------------------------------------------------
# Test backend
# ---------------------------------------------------------------------------


class _EchoBackend(FusionBackend):
    """Test backend that returns the prompt as the response for each model."""

    name = "echo-test"

    def __init__(self) -> None:
        self.calls: list[PanelRequest] = []

    def check_requirements(self) -> bool:
        return True

    async def run_panel(
        self,
        request: PanelRequest,
        *,
        outer_model: str,
        judge_model: str,
    ) -> PanelResponse:
        self.calls.append(request)
        return PanelResponse(
            responses=[
                {"model": m, "content": f"echo[{m}]: {request.prompt}"}
                for m in request.analysis_models
            ],
            failed_models=[],
        )


class _FailingBackend(FusionBackend):
    """Test backend that raises."""

    name = "failing-test"

    def check_requirements(self) -> bool:
        return True

    async def run_panel(self, request, *, outer_model, judge_model):
        raise RuntimeError("backend kaboom")


# ---------------------------------------------------------------------------
# Recursion guard
# ---------------------------------------------------------------------------


def test_recursion_guard_runs_clean_baseline():
    """The ContextVar starts at 0 outside any call."""
    assert _fusion_depth.get() == 0


@pytest.mark.asyncio
async def test_recursion_guard_resets_after_successful_call():
    """After a successful call, the depth returns to its pre-call value."""
    runner = FusionRunner(backend=_EchoBackend(), config=FusionConfig())
    pre = _fusion_depth.get()

    await runner.run(
        prompt="hello",
        panel_models=["a", "b"],
    )

    assert _fusion_depth.get() == pre


@pytest.mark.asyncio
async def test_recursion_guard_resets_after_exception():
    """A backend that raises still resets the ContextVar (try/finally)."""
    runner = FusionRunner(backend=_FailingBackend(), config=FusionConfig())
    pre = _fusion_depth.get()

    with pytest.raises(RuntimeError, match="backend kaboom"):
        await runner.run(prompt="hello", panel_models=["a", "b"])

    assert _fusion_depth.get() == pre


@pytest.mark.asyncio
async def test_recursion_guard_raises_recursion_error_on_nested_call():
    """If we manually set depth=1 then call, the runner raises
    RecursionError (defense in depth: the guard fires before the call)."""
    runner = FusionRunner(backend=_EchoBackend(), config=FusionConfig())

    token = _fusion_depth.set(1)
    try:
        with pytest.raises(RecursionError, match="recursively"):
            await runner.run(prompt="hello", panel_models=["a", "b"])
    finally:
        _fusion_depth.reset(token)


# ---------------------------------------------------------------------------
# Cost guard
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cost_guard_refuses_too_many_panel_models():
    """Per T1.5/T2.1: cost guard refuses when analysis_models > max_panel_size."""
    backend = _EchoBackend()
    runner = FusionRunner(
        backend=backend,
        config=FusionConfig(max_panel_size=3),
    )

    with pytest.raises(ValueError, match="exceeds max_panel_size"):
        await runner.run(
            prompt="hello",
            panel_models=["a", "b", "c", "d", "e"],  # 5 > 3
        )

    # Backend was not called
    assert backend.calls == []


@pytest.mark.asyncio
async def test_cost_guard_allows_exactly_max_panel_size():
    """Exactly max_panel_size is allowed (<=)."""
    backend = _EchoBackend()
    runner = FusionRunner(
        backend=backend,
        config=FusionConfig(max_panel_size=3),
    )

    await runner.run(prompt="hello", panel_models=["a", "b", "c"])
    assert len(backend.calls) == 1


# ---------------------------------------------------------------------------
# Judge strategy resolution
# ---------------------------------------------------------------------------


def test_judge_strategy_default_is_outer_model():
    """Default: outer-model (zero cost)."""
    runner = FusionRunner(
        backend=_EchoBackend(),
        default_judge_model="claude-3",
    )
    # resolve_judge_model takes the strategy + judge_model kwargs
    resolved = runner._resolve_judge_model(
        judge_strategy=None, judge_model=None
    )
    assert resolved == "claude-3"


def test_judge_strategy_explicit_model_requires_judge_model():
    """T2.5: explicit-model strategy must have a judge_model set."""
    runner = FusionRunner(backend=_EchoBackend(), default_judge_model="x")
    with pytest.raises(ValueError, match="judge_strategy='explicit-model'"):
        runner._resolve_judge_model(
            judge_strategy="explicit-model", judge_model=None
        )


def test_judge_strategy_explicit_model_uses_judge_model():
    runner = FusionRunner(backend=_EchoBackend(), default_judge_model="x")
    resolved = runner._resolve_judge_model(
        judge_strategy="explicit-model", judge_model="kimi-k2.6"
    )
    assert resolved == "kimi-k2.6"


def test_judge_strategy_auxiliary_curator_falls_back_to_outer():
    """T2.5: if auxiliary-curator is requested but no curator is
    configured, fall back to outer-model."""
    runner = FusionRunner(
        backend=_EchoBackend(),
        default_judge_model="claude-3",
        # No judge_model_default set
    )
    resolved = runner._resolve_judge_model(
        judge_strategy="auxiliary-curator", judge_model=None
    )
    assert resolved == "claude-3"


# ---------------------------------------------------------------------------
# Runner owns the judge (T1.1)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runner_fills_analysis_after_backend_returns():
    """The runner's `_invoke_judge` is called after backend.run_panel.

    For v0.1, _invoke_judge is stubbed (returns None, raw). The
    assertion is that the runner populates `raw_judge_output` on
    the response.
    """
    backend = _EchoBackend()
    runner = FusionRunner(backend=backend, default_judge_model="claude-3")

    result = await runner.run(prompt="hi", panel_models=["a", "b"])

    # Backend's run_panel returned empty analysis; runner filled it
    assert result.raw_judge_output is not None
    assert "stub judge" in result.raw_judge_output
    # v0.1 stub returns analysis=None (real judge is v0.2)
    assert result.analysis is None


# ---------------------------------------------------------------------------
# Judge input assembly (T2.8)
# ---------------------------------------------------------------------------


def test_judge_input_assembly_includes_all_responses():
    """T2.8: the assembled input has each response in the documented format."""
    backend = _EchoBackend()
    runner = FusionRunner(backend=backend, default_judge_model="claude-3")
    panel = PanelResponse(
        responses=[
            {"model": "a", "content": "first response"},
            {"model": "b", "content": "second response"},
        ],
        failed_models=[],
    )
    prompt = "What is the capital of France?"

    assembled = runner._assemble_judge_input(
        prompt=prompt,
        panel_response=panel,
        judge_prompt="JUDGE_PROMPT_TEXT",
    )

    assert prompt in assembled
    assert "[Response 1 from a]" in assembled
    assert "first response" in assembled
    assert "[Response 2 from b]" in assembled
    assert "second response" in assembled
    assert "JUDGE_PROMPT_TEXT" in assembled


def test_judge_input_assembly_includes_failed_models_note():
    """T2.8: failed_models are surfaced in the judge input."""
    runner = FusionRunner(backend=_EchoBackend(), default_judge_model="x")
    panel = PanelResponse(
        responses=[{"model": "a", "content": "ok"}],
        failed_models=[{"model": "b", "reason": "timeout"}],
    )
    assembled = runner._assemble_judge_input(
        prompt="hi",
        panel_response=panel,
        judge_prompt="JUDGE",
    )
    assert "1 panel models failed" in assembled
    assert "b" in assembled
