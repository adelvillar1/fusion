"""OpenRouterFusionBackend — opt-in backend.

Pass-through to OpenRouter's `openrouter:fusion` server tool. Makes
a real `POST https://openrouter.ai/api/v1/chat/completions` call
with the `openrouter:fusion` tool enabled. OpenRouter runs the
panel server-side and returns a structured `analysis`.

This is the only backend that's a real network implementation in
v0.1. Users opt in by setting `OPENROUTER_API_KEY` and selecting
`backend: "openrouter-fusion"` in config.yaml (or passing
`backend="openrouter-fusion"` as a tool arg).
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import httpx

from tools.fusion.backends.base import (
    FusionBackend,
    PanelRequest,
    PanelResponse,
    register_backend,
)

logger = logging.getLogger(__name__)

OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_FUSION_TOOL_TYPE = "openrouter:fusion"


class OpenRouterFusionBackend(FusionBackend):
    name = "openrouter-fusion"

    def check_requirements(self) -> bool:
        """OpenRouter-fusion requires OPENROUTER_API_KEY."""
        return bool(os.getenv("OPENROUTER_API_KEY"))

    async def run_panel(
        self,
        request: PanelRequest,
        *,
        outer_model: str,
        judge_model: str,
    ) -> PanelResponse:
        api_key = os.getenv("OPENROUTER_API_KEY", "")

        # Build the OpenRouter request body. The fusion tool is
        # enabled as a server tool; the panel is configured via
        # `analysis_models` and the judge is configured via `model`
        # (which defaults to the outer model per OpenRouter's docs).
        body: dict[str, Any] = {
            "model": outer_model or "openrouter/auto",
            "messages": [{"role": "user", "content": request.prompt}],
            "tools": [
                {
                    "type": OPENROUTER_FUSION_TOOL_TYPE,
                    "parameters": {
                        "analysis_models": request.analysis_models,
                        "model": judge_model,  # empty/null means "use outer model"
                        "max_tool_calls": request.max_tool_calls,
                    },
                }
            ],
            "tool_choice": "required",
        }
        if request.temperature is not None:
            body["temperature"] = request.temperature
        if request.max_completion_tokens is not None:
            body["max_tokens"] = request.max_completion_tokens
        if request.reasoning_effort is not None:
            body.setdefault("extra_body", {})["reasoning"] = {
                "effort": request.reasoning_effort
            }

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        # OpenRouter's server-side recursion guard header (best-effort,
        # see plan §4.4). OpenRouter may or may not honor this.
        headers["x-openrouter-fusion-depth"] = "1"

        timeout = request.timeout_seconds
        async with httpx.AsyncClient(timeout=timeout) as client:
            try:
                resp = await client.post(OPENROUTER_API_URL, json=body, headers=headers)
            except httpx.HTTPError as exc:
                # Network-level failure → all panel models failed
                return PanelResponse(
                    responses=[],
                    failed_models=[
                        {
                            "model": m,
                            "reason": f"openrouter-fusion network error: {exc}",
                        }
                        for m in request.analysis_models
                    ],
                )

        if resp.status_code != 200:
            # OpenRouter error. Surface verbatim to the outer model.
            return PanelResponse(
                responses=[],
                failed_models=[
                    {
                        "model": "openrouter-fusion",
                        "reason": (
                            f"openrouter-fusion HTTP {resp.status_code}: "
                            f"{resp.text[:500]}"
                        ),
                    }
                ],
            )

        try:
            data = resp.json()
        except json.JSONDecodeError as exc:
            return PanelResponse(
                responses=[],
                failed_models=[
                    {
                        "model": "openrouter-fusion",
                        "reason": f"openrouter-fusion returned non-JSON: {exc}",
                    }
                ],
            )

        # The fusion tool result is in choices[0].message.tool_calls
        # (if the outer model called the tool) or in choices[0].message
        # content (if the server ran the tool server-side and
        # substituted the result).
        # The exact shape depends on whether OpenRouter runs the
        # fusion server-side or hands the tool definition back to
        # the outer model. For server-side execution, the response
        # is the fusion result directly.
        choices = data.get("choices", [])
        if not choices:
            return PanelResponse(
                responses=[],
                failed_models=[
                    {
                        "model": "openrouter-fusion",
                        "reason": "openrouter-fusion returned no choices",
                    }
                ],
            )

        first = choices[0]
        message = first.get("message", {})

        # Look for tool_calls first (outer model called the tool)
        tool_calls = message.get("tool_calls", [])
        fusion_result: dict[str, Any] | None = None
        for tc in tool_calls:
            fn = tc.get("function", {})
            if fn.get("name") == OPENROUTER_FUSION_TOOL_TYPE:
                # The function arguments are JSON-encoded
                args_raw = fn.get("arguments", "{}")
                if isinstance(args_raw, str):
                    try:
                        fusion_result = json.loads(args_raw)
                    except json.JSONDecodeError:
                        fusion_result = {"raw_arguments": args_raw}
                elif isinstance(args_raw, dict):
                    fusion_result = args_raw
                break

        # If no tool_call, the message content might BE the fusion
        # result (server-side execution path).
        if fusion_result is None:
            content = message.get("content", "")
            if isinstance(content, str):
                try:
                    fusion_result = json.loads(content)
                except json.JSONDecodeError:
                    fusion_result = {"raw_content": content}
            elif isinstance(content, dict):
                fusion_result = content

        if fusion_result is None:
            return PanelResponse(
                responses=[],
                failed_models=[
                    {
                        "model": "openrouter-fusion",
                        "reason": "openrouter-fusion returned no fusion result",
                    }
                ],
            )

        # Parse the fusion result. The shape is documented in plan
        # §4.6: { status, analysis?, responses?, failed_models?,
        # error_reason? }.
        status = fusion_result.get("status", "ok")
        if status == "error":
            error_reason = fusion_result.get("error_reason", "unknown")
            return PanelResponse(
                responses=[],
                failed_models=[
                    {
                        "model": "openrouter-fusion",
                        "reason": f"openrouter-fusion error: {error_reason}",
                    }
                ],
            )

        # status == "ok": analysis and/or responses may be present
        analysis = fusion_result.get("analysis")
        raw_responses = fusion_result.get("responses", []) or []
        raw_failed = fusion_result.get("failed_models", []) or []

        responses = [
            {
                "model": r.get("model", "unknown"),
                "content": r.get("content", ""),
            }
            for r in raw_responses
        ]
        failed_models = [
            {
                "model": r.get("model", "unknown"),
                "reason": r.get("reason", "unknown"),
            }
            for r in raw_failed
        ]

        return PanelResponse(
            responses=responses,
            failed_models=failed_models,
            analysis=analysis,  # OpenRouter already produced this server-side
            raw_judge_output=None,  # server-side, no raw output
        )


# Register on import
register_backend(OpenRouterFusionBackend())
