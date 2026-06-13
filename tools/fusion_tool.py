"""openrouter_fusion tool — stub.

Real implementation lives in the implementation branch once the design
plan at ``docs/plans/2026-06-13-fusion-tool-design.md`` is approved.

This stub exists so the file is importable, the toolset key resolves,
and downstream tests can mock against it.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from tools.registry import registry

logger = logging.getLogger(__name__)


FUSION_TOOLSET = "fusion_tools"

TOOL_NAME = "openrouter_fusion"

TOOL_SCHEMA: dict[str, Any] = {
    "name": TOOL_NAME,
    "description": (
        "Run the user prompt through a panel of 1-8 models in parallel and "
        "have a judge model compare their responses, returning structured "
        "analysis (consensus, contradictions, unique insights, blind spots) "
        "plus the raw panel responses. Use for 'where do experts disagree' "
        "or high-stakes multi-perspective tasks."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "prompt": {"type": "string"},
            "analysis_models": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
                "maxItems": 8,
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
                "enum": ["low", "medium", "high", None],
            },
            "temperature": {
                "type": "number",
                "minimum": 0,
                "maximum": 2,
            },
            "force": {"type": "boolean", "default": False},
        },
        "required": ["prompt"],
        "additionalProperties": False,
    },
}


def openrouter_fusion_stub(*args: Any, **kwargs: Any) -> str:
    """Stub handler. Real implementation handles recursion guard,
    config resolution, OpenRouter pass-through, and judge-degradation
    passthrough. See the design plan §3-§4."""
    return json.dumps(
        {
            "stub": True,
            "message": (
                "openrouter_fusion is a stub. Implement per "
                "docs/plans/2026-06-13-fusion-tool-design.md §3-§4."
            ),
            "received_kwargs_keys": sorted(kwargs.keys()),
        }
    )


def check_requirements() -> bool:
    """Tool is gated on OPENROUTER_API_KEY being set, plus the
    `fusion_tools` toolset being enabled in the agent config."""
    import os

    return bool(os.getenv("OPENROUTER_API_KEY"))


registry.register(
    name=TOOL_NAME,
    toolset=FUSION_TOOLSET,
    schema=TOOL_SCHEMA,
    handler=openrouter_fusion_stub,
    check_fn=check_requirements,
    requires_env=["OPENROUTER_API_KEY"],
)
