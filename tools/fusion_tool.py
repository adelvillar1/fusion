"""fusion tool — entry point.

This is the only file the agent actually imports. It registers the
tool with Hermes's `tools.registry` and exposes an async handler
that delegates to `FusionRunner.run()`.

Tool name: `fusion` (renamed from v1's `openrouter_fusion` per Pass
2 review T1.2). Toolset: `fusion_tools`.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from tools.fusion import FusionRunner, FusionConfig, list_backends
from tools.fusion.backends import PanelResponse

logger = logging.getLogger(__name__)


# Lazy registry import: the plugin is meant to be installed into
# hermes-agent's `tools/` package, where `tools.registry` resolves
# to the agent's registry. For unit tests run from this repo (where
# the fusion plugin's own `tools/` is on the path), `tools.registry`
# would not exist. We attempt the import; if it fails, the module
# still loads and tests can patch around it.
try:
    from tools.registry import registry as _hermes_registry
    _REGISTRY_AVAILABLE = True
except ImportError:
    _hermes_registry = None
    _REGISTRY_AVAILABLE = False


FUSION_TOOLSET = "fusion_tools"

TOOL_NAME = "fusion"

TOOL_SCHEMA: dict[str, Any] = {
    "name": TOOL_NAME,
    "description": (
        "Run the user prompt through a panel of 2-16 models in parallel "
        "and have a judge model produce structured analysis (consensus, "
        "contradictions, unique insights, blind spots) plus the raw "
        "panel responses. Use for 'where do experts disagree' or "
        "high-stakes multi-perspective tasks. Default backend (hermes-native) "
        "uses your existing model providers — no external dependency."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "prompt": {"type": "string"},
            "analysis_models": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 2,
                "maxItems": 16,
                "description": (
                    "Panel models. Defaults to fusion.analysis_models from "
                    "config.yaml (or first 3 of model.fallback_providers if "
                    "empty). Hard cap is schema maxItems (16); runtime cost "
                    "guard is fusion.max_panel_size (default 8)."
                ),
            },
            "backend": {
                "type": "string",
                "enum": ["hermes-native", "openrouter-fusion"],
                "default": "hermes-native",
                "description": (
                    "Which backend to use. 'hermes-native' is the default "
                    "and works with your existing model providers (no "
                    "external dep). 'openrouter-fusion' passes through to "
                    "OpenRouter's server tool and requires OPENROUTER_API_KEY."
                ),
            },
            "judge_strategy": {
                "type": "string",
                "enum": ["outer-model", "auxiliary-curator", "explicit-model"],
                "default": "outer-model",
                "description": (
                    "How to pick the judge model. 'outer-model' (default, zero "
                    "extra cost) = the same model that invoked this tool. "
                    "'auxiliary-curator' = the agent's configured curator "
                    "slot. 'explicit-model' = use the judge_model arg."
                ),
            },
            "judge_model": {
                "type": "string",
                "description": (
                    "Explicit judge model. Required when judge_strategy is "
                    "'explicit-model'. Ignored otherwise."
                ),
            },
            "max_tool_calls": {
                "type": "integer",
                "minimum": 1,
                "maximum": 16,
                "default": 8,
                "description": (
                    "Per-panel-model tool-call limit. Backend-specific: "
                    "openrouter-fusion passes through to OpenRouter; "
                    "hermes-native v0.1 accepts but ignores this parameter."
                ),
            },
            "max_completion_tokens": {
                "type": "integer",
                "description": "Max output tokens per panel/judge response.",
            },
            "reasoning_effort": {
                "type": ["string", "null"],
                "enum": ["low", "medium", "high"],
                "description": "Reasoning effort for panel/judge models.",
            },
            "temperature": {
                "type": "number",
                "minimum": 0,
                "maximum": 2,
                "description": "Sampling temperature. Provider default if unset.",
            },
            "timeout_seconds": {
                "type": "integer",
                "minimum": 10,
                "maximum": 600,
                "default": 120,
                "description": (
                    "Max wall-clock seconds. Raises TimeoutError on exceed."
                ),
            },
        },
        "required": ["prompt"],
        "additionalProperties": False,
    },
}


# Module-level config + runner. Built once at registration time.
# Per-call overrides are passed as kwargs to runner.run().
def _build_config() -> FusionConfig:
    """Build the FusionConfig from environment / defaults.

    v0.1: hard-coded defaults from the plan §5. v0.2 will read
    from the user's config.yaml.
    """
    return FusionConfig(
        backend="hermes-native",
        analysis_models=[],
        judge_strategy="outer-model",
        judge_model=None,
        judge_model_default=None,
        max_panel_size=8,
        timeout_seconds=120,
    )


# Singleton runner (config is built once; overrides happen at run time)
_runner: FusionRunner | None = None


def _get_runner() -> FusionRunner:
    global _runner
    if _runner is None:
        _runner = FusionRunner(config=_build_config())
    return _runner


async def fusion_handler(
    *,
    prompt: str,
    analysis_models: list[str] | None = None,
    backend: str = "hermes-native",
    judge_strategy: str = "outer-model",
    judge_model: str | None = None,
    max_tool_calls: int = 8,
    max_completion_tokens: int | None = None,
    reasoning_effort: str | None = None,
    temperature: float | None = None,
    timeout_seconds: int = 120,
    **_: Any,
) -> str:
    """The async tool handler. Delegates to `FusionRunner.run()`.

    Returns a JSON string for Hermes's tool-result protocol. The
    string contains the full `PanelResponse` shape (responses,
    failed_models, analysis, raw_judge_output).
    """
    runner = _get_runner()
    panel = list(analysis_models) if analysis_models else []

    try:
        result: PanelResponse = await runner.run(
            prompt=prompt,
            panel_models=panel,
            backend_name=backend,
            judge_strategy=judge_strategy,
            judge_model=judge_model,
            max_tool_calls=max_tool_calls,
            max_completion_tokens=max_completion_tokens,
            reasoning_effort=reasoning_effort,
            temperature=temperature,
            timeout_seconds=timeout_seconds,
        )
    except RecursionError as exc:
        return json.dumps(
            {"error": "recursion", "message": str(exc)},
            indent=2,
        )
    except ValueError as exc:
        return json.dumps(
            {"error": "configuration", "message": str(exc)},
            indent=2,
        )

    # Serialize PanelResponse to JSON for the outer model
    return json.dumps(
        {
            "responses": result.responses,
            "failed_models": result.failed_models,
            "analysis": result.analysis,
            "raw_judge_output": result.raw_judge_output,
        },
        indent=2,
    )


def check_requirements() -> bool:
    """Tool is callable if at least one backend is available.

    For hermes-native: the stub returns True (the v0.1 stub's
    `_call_single_model` works without real providers). v0.2 will
    tighten this to check `model.fallback_providers` has >= 2 entries.

    For openrouter-fusion: requires `OPENROUTER_API_KEY`.

    Returns True if EITHER backend is available.
    """
    try:
        from tools.fusion.backends import list_available_backends
        return bool(list_available_backends())
    except Exception:  # pragma: no cover
        return True  # fail-open for the stub


# Eagerly initialize the backend registry (registers hermes-native and
# openrouter-fusion). This is the side-effecting import.
_ = list_backends  # silence linter
try:
    from tools.fusion.backends import (  # noqa: F401
        list_available_backends as _ensure_backends_loaded,
    )
except Exception:  # pragma: no cover
    pass


# Hermes registry.register() requires: name, toolset, schema, handler,
# check_fn, requires_env, is_async, description, emoji.
# Only register if running inside hermes-agent (i.e., `tools.registry`
# is importable). For unit tests run from the plugin repo in
# isolation, the import is mocked.
if _REGISTRY_AVAILABLE and _hermes_registry is not None:
    _hermes_registry.register(
        name=TOOL_NAME,
        toolset=FUSION_TOOLSET,
        schema=TOOL_SCHEMA,
        handler=fusion_handler,
        check_fn=check_requirements,
        requires_env=[],
        is_async=True,
        description=TOOL_SCHEMA["description"],
        emoji="🔀",
    )
