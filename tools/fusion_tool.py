"""fusion tool — stub.

Real implementation lives in the implementation branch once the design
plan at ``docs/plans/2026-06-13-fusion-tool-design.md`` is approved.

This stub exists so the file is importable, the toolset key resolves,
and downstream tests can mock against it.

Tool name: ``fusion`` (renamed from v1's ``openrouter_fusion`` per Pass
2 review T1.2 — v0.1 hasn't shipped, no v1 to be compatible with, and
the v2 plan's thesis is "OpenRouter is opt-in").
"""

from __future__ import annotations

import json
import logging
from typing import Any

from tools.registry import registry

logger = logging.getLogger(__name__)


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
            },
            "backend": {
                "type": "string",
                "enum": ["hermes-native", "openrouter-fusion"],
                "default": "hermes-native",
            },
            "judge_strategy": {
                "type": ["string", "null"],
                "enum": ["outer-model", "auxiliary-curator", "explicit-model", None],
                "default": "outer-model",
            },
            "judge_model": {"type": "string"},
            "max_tool_calls": {
                "type": "integer",
                "minimum": 1,
                "maximum": 16,
                "default": 8,
            },
            "max_completion_tokens": {"type": "integer"},
            "reasoning_effort": {
                "type": ["string", "null"],
                "enum": ["low", "medium", "high"],
            },
            "temperature": {
                "type": "number",
                "minimum": 0,
                "maximum": 2,
            },
            "timeout_seconds": {
                "type": "integer",
                "minimum": 10,
                "maximum": 600,
                "default": 120,
            },
        },
        "required": ["prompt"],
        "additionalProperties": False,
    },
}


def fusion_stub(*args: Any, **kwargs: Any) -> str:
    """Stub handler. Real implementation handles:
    - backend selection (hermes-native default, openrouter-fusion opt-in)
    - plugin-owned ContextVar recursion guard
    - config resolution (args > config.yaml > schema defaults)
    - hermes-native fans out via asyncio.gather(..., return_exceptions=True)
    - per-member-fail semantics (failed models → failed_models, others continue)
    - runner-owned judge invocation (NOT the backend)
    - StructuredAnalysis Pydantic parsing
    - check_requirements verifies model.fallback_providers has >= 2 entries
    See the design plan §3-§7."""
    return json.dumps(
        {
            "stub": True,
            "message": (
                "fusion is a stub. Implement per "
                "docs/plans/2026-06-13-fusion-tool-design.md §3-§7."
            ),
            "received_kwargs_keys": sorted(kwargs.keys()),
        }
    )


def check_requirements() -> bool:
    """Tool is gated on the fusion_tools toolset being enabled and at least
    one backend being available.

    For hermes-native (the v0.1 default), this checks
    ``model.fallback_providers`` has >= 2 entries (T1.7). For
    openrouter-fusion (opt-in), this checks ``OPENROUTER_API_KEY`` is set.
    Returns True if EITHER backend is available.
    """
    import os

    # Always True at stub level — real implementation does the
    # per-backend checks per the design plan §4.1.
    return bool(os.getenv("OPENROUTER_API_KEY")) or True


registry.register(
    name=TOOL_NAME,
    toolset=FUSION_TOOLSET,
    schema=TOOL_SCHEMA,
    handler=fusion_stub,
    check_fn=check_requirements,
)
