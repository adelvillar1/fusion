"""HermesNativeBackend — v0.1 default backend.

Fans out via `asyncio.gather(..., return_exceptions=True)` so a
single panel member's failure does NOT lose the others' responses
(per Pass 2 review T1.3 — critical bug if missing).

Per-member-FAIL semantics (per Pass 2 review T2.1): if a panel
member fails, it appears in `failed_models` and the panel
continues with the remaining members. The user gets the panel they
asked for, with explicit failure surfacing.

`_call_single_model` is a STUB in v0.1. v0.2 will wire it to
Hermes's `auxiliary_client.py` (or equivalent) to make real
provider calls. The stub returns a deterministic fake response
per model so tests can verify the gather + exception logic without
needing real network calls.
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any

from tools.fusion.backends.base import (
    FusionBackend,
    PanelRequest,
    PanelResponse,
    register_backend,
)

logger = logging.getLogger(__name__)


def _call_single_model(model: str, request: PanelRequest) -> str:
    """STUB: call a single model and return its text response.

    v0.1 returns a deterministic fake response. v0.2 will replace
    this with a real call to Hermes's auxiliary_client.

    The stub is intentionally minimal — the implementation must
    not assume any specific provider's API. Tests mock this
    function to inject controlled responses (success / failure /
    timeout) and verify the gather-with-exceptions logic.
    """
    prompt_preview = request.prompt[:60].replace("\n", " ")
    return (
        f"[stub v0.1] model={model} prompt='{prompt_preview}...' "
        f"temp={request.temperature} max_tokens={request.max_completion_tokens}"
    )


class HermesNativeBackend(FusionBackend):
    name = "hermes-native"

    def check_requirements(self) -> bool:
        """Per plan §T1.7: returns True only if the user's
        model.fallback_providers chain has >= 2 entries.

        Reads `~/.hermes/config.yaml` directly (the plugin does
        not import from hermes_cli — that would be a reverse-
        dependency). v0.1 of the stub is permissive: returns True
        even if the config can't be read, because the stub's
        `_call_single_model` works without real providers.

        TODO (v0.2): tighten to return False when the fallback
        chain has <2 entries.
        """
        # TODO (v0.2): parse ~/.hermes/config.yaml and check
        # model.fallback_providers has >= 2 entries. For now, the
        # stub works without any real providers, so we return True
        # to keep the tool callable in v0.1.
        return True

    async def run_panel(
        self,
        request: PanelRequest,
        *,
        outer_model: str,
        judge_model: str,
    ) -> PanelResponse:
        # Per-member-FAIL semantics (Pass 2 T2.1). Critical: use
        # return_exceptions=True so a single failure does NOT lose
        # the others (Pass 2 T1.3).
        tasks = [
            asyncio.create_task(
                asyncio.wait_for(
                    asyncio.to_thread(_call_single_model, model, request),
                    timeout=request.timeout_seconds,
                )
            )
            for model in request.analysis_models
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        responses: list[dict[str, Any]] = []
        failed_models: list[dict[str, str]] = []
        for model, result in zip(request.analysis_models, results):
            if isinstance(result, Exception):
                failed_models.append(
                    {
                        "model": model,
                        "reason": f"{type(result).__name__}: {result}",
                    }
                )
            else:
                responses.append({"model": model, "content": str(result)})

        return PanelResponse(
            responses=responses,
            failed_models=failed_models,
        )


# Register on import
register_backend(HermesNativeBackend())
