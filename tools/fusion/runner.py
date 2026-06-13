"""FusionRunner — backend-agnostic orchestration.

The runner owns:
- Recursion guard (plugin-owned `ContextVar`, not in hermes-agent core
  per Pass 2 T1.4+T1.5)
- Cost guard (refuses when analysis_models length > max_panel_size)
- Judge invocation (the runner fills in `analysis` and
  `raw_judge_output` after `run_panel` returns; the backend does NOT
  run the judge — per Pass 2 T1.1)

The backend is responsible ONLY for panel fan-out.
"""

from __future__ import annotations

import asyncio
import logging
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

from tools.fusion.analysis import (
    StructuredAnalysis,
    parse_judge_output,
)
from tools.fusion.backends import (
    FusionBackend,
    PanelRequest,
    PanelResponse,
    get_backend,
)

logger = logging.getLogger(__name__)


# Plugin-owned recursion guard (T1.4+T1.5). The plugin MUST NOT import
# from run_agent.py (circular import + wrong direction). Per-call
# scope: two independent fusion calls in the same conversation
# session both succeed.
_fusion_depth: ContextVar[int] = ContextVar("fusion_depth", default=0)


@dataclass
class FusionConfig:
    """Per-plugin configuration, built once at tool-registration time.

    Per-call overrides are passed as kwargs to `runner.run()`. See
    the precedence rule in plan §5: args > config > schema.
    """

    backend: str = "hermes-native"
    analysis_models: list[str] = field(default_factory=list)
    judge_strategy: str = "outer-model"  # outer-model | auxiliary-curator | explicit-model
    judge_model: str | None = None  # only when judge_strategy == "explicit-model"
    judge_model_default: str | None = None
    max_panel_size: int = 8
    timeout_seconds: int = 120

    def resolve_panel_models(self) -> list[str]:
        """Return the explicit panel if set, else empty list (backend
        auto-populates from fallback chain)."""
        return list(self.analysis_models)


class FusionRunner:
    """The single orchestrator for fusion tool calls.

    `runner.run()` does (in order):
    1. Set/reset the recursion-guard ContextVar
    2. Resolve the backend (from config or per-call override)
    3. Apply the cost guard
    4. Build a `PanelRequest`
    5. Call `backend.run_panel(request)` — backend fans out the panel
    6. If the panel returned any responses, invoke the judge model
       and populate `analysis` / `raw_judge_output`
    7. Return the `PanelResponse`
    """

    def __init__(
        self,
        backend: FusionBackend | None = None,
        config: FusionConfig | None = None,
        *,
        default_judge_model: str | None = None,
    ) -> None:
        self.config = config or FusionConfig()
        self._default_judge_model = default_judge_model
        # If a backend is passed explicitly, use it; otherwise the
        # backend is looked up per-call (allows runtime backend
        # selection via tool args).
        self._explicit_backend = backend

    async def run(
        self,
        prompt: str,
        panel_models: list[str],
        *,
        backend_name: str | None = None,
        judge_strategy: str | None = None,
        judge_model: str | None = None,
        timeout_seconds: int | None = None,
        max_tool_calls: int | None = None,
        max_completion_tokens: int | None = None,
        temperature: float | None = None,
        reasoning_effort: str | None = None,
        **kwargs: Any,
    ) -> PanelResponse:
        """Run a fusion deliberation. Returns a `PanelResponse`.

        Per-call overrides take precedence over `FusionConfig` (which
        takes precedence over schema defaults). The runner enforces
        the recursion guard and cost guard.
        """
        # 1. Recursion guard: per-call scope, set/reset around the call.
        token = _fusion_depth.set(_fusion_depth.get() + 1)
        try:
            if _fusion_depth.get() > 1:
                raise RecursionError(
                    f"fusion tool invoked recursively "
                    f"(depth={_fusion_depth.get()}). The fusion tool "
                    f"cannot call itself; if you need a nested "
                    f"deliberation, use a different tool."
                )

            # 2. Resolve backend (per-call > config > registry default)
            backend = self._resolve_backend(backend_name)

            # 3. Cost guard
            if len(panel_models) > self.config.max_panel_size:
                raise ValueError(
                    f"analysis_models length {len(panel_models)} exceeds "
                    f"max_panel_size {self.config.max_panel_size}. "
                    f"Either pass fewer analysis_models or raise "
                    f"fusion.max_panel_size in config.yaml."
                )

            # 4. Build request
            request = PanelRequest(
                prompt=prompt,
                analysis_models=list(panel_models),
                temperature=temperature,
                max_completion_tokens=max_completion_tokens,
                reasoning_effort=reasoning_effort,
                max_tool_calls=max_tool_calls or 8,
                timeout_seconds=timeout_seconds or self.config.timeout_seconds,
            )

            # 5. Backend panel fan-out
            outer_model = self._default_judge_model or "outer-model"
            judge_model_resolved = self._resolve_judge_model(
                judge_strategy=judge_strategy,
                judge_model=judge_model,
            )
            panel_response = await backend.run_panel(
                request,
                outer_model=outer_model,
                judge_model=judge_model_resolved,
            )

            # 6. Runner invokes the judge (NOT the backend). Per Pass 2
            # T1.1: the runner owns the judge. The backend's run_panel
            # leaves analysis / raw_judge_output empty.
            if panel_response.responses:
                analysis, raw = await self._invoke_judge(
                    prompt=prompt,
                    panel_response=panel_response,
                    judge_model=judge_model_resolved,
                )
                panel_response.analysis = analysis
                panel_response.raw_judge_output = raw

            return panel_response
        finally:
            _fusion_depth.reset(token)

    def _resolve_backend(self, backend_name: str | None) -> FusionBackend:
        if self._explicit_backend is not None:
            return self._explicit_backend
        name = backend_name or self.config.backend
        return get_backend(name)

    def _resolve_judge_model(
        self,
        *,
        judge_strategy: str | None,
        judge_model: str | None,
    ) -> str:
        """Resolve which model runs the judge pass.

        Resolution order (per plan §4.5):
        1. `explicit-model` strategy — use the `judge_model` arg
        2. `auxiliary-curator` strategy — use `default_judge_model`
           (Hermes's curator slot). Fall back to outer-model if the
           curator's provider is unavailable (T2.5).
        3. `outer-model` (default) — use `default_judge_model`
        """
        strategy = judge_strategy or self.config.judge_strategy
        explicit = judge_model or self.config.judge_model

        if strategy == "explicit-model":
            if not explicit:
                raise ValueError(
                    "judge_strategy='explicit-model' requires judge_model "
                    "to be set (either as a tool arg or in config.yaml "
                    "fusion.judge_model)."
                )
            return explicit

        if strategy == "auxiliary-curator":
            curator = self._default_judge_model or self.config.judge_model_default
            if curator:
                return curator
            logger.warning(
                "judge_strategy='auxiliary-curator' but no curator model "
                "configured; falling back to outer-model"
            )

        # Default: outer-model
        return self._default_judge_model or "outer-model"

    async def _invoke_judge(
        self,
        *,
        prompt: str,
        panel_response: PanelResponse,
        judge_model: str,
    ) -> tuple[dict[str, Any] | None, str | None]:
        """Invoke the judge model with the assembled panel input.

        v0.1: stubbed. The runner assembles the input and would call
        the judge model here, but the real invocation is left to
        v0.2 (which will use Hermes's auxiliary_client).

        For now, the runner returns a placeholder `raw_judge_output`
        describing what it would have done, and `analysis=None` to
        signal that no analysis is available.

        The structured output for the outer model is the panel
        responses + `failed_models` — the outer model can synthesize
        from those if it wants.
        """
        from tools.fusion.analysis import JUDGE_PROMPT

        n = len(panel_response.responses)
        assembled_input = self._assemble_judge_input(
            prompt=prompt,
            panel_response=panel_response,
            judge_prompt=JUDGE_PROMPT.format(N=n),
        )

        # TODO (v0.2): actually call the judge model here. For v0.1
        # we return None analysis with a placeholder raw output that
        # describes what the runner did. Tests can verify the input
        # assembly by inspecting the raw_judge_output stub.
        raw = (
            f"[stub judge v0.1] would have called {judge_model} with "
            f"prompt='{prompt[:80]}...' and {n} panel responses "
            f"(assembled input is {len(assembled_input)} chars; "
            f"real judge invocation is v0.2)"
        )
        logger.info("judge stub: %s", raw[:200])
        return None, raw

    @staticmethod
    def _assemble_judge_input(
        *, prompt: str, panel_response: PanelResponse, judge_prompt: str
    ) -> str:
        """Assemble the judge input per plan §4.5."""
        lines = [
            f"Original user prompt: {prompt}",
            "",
            f"You have been given the following {len(panel_response.responses)} "
            f"responses to the same prompt:",
            "",
        ]
        for i, resp in enumerate(panel_response.responses, start=1):
            model = resp.get("model", "unknown")
            content = resp.get("content", "")
            lines.append(f"[Response {i} from {model}]")
            lines.append(content)
            lines.append("")
        if panel_response.failed_models:
            lines.append(
                f"Note: {len(panel_response.failed_models)} panel models "
                f"failed: {[m.get('model', '?') for m in panel_response.failed_models]}"
            )
            lines.append("")
        lines.append(judge_prompt)
        return "\n".join(lines)
