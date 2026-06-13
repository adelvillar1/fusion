"""FusionBackend ABC + request/response dataclasses + backend registry.

Every concrete backend (hermes-native, openrouter-fusion, future
Anthropic batch API, etc.) implements `FusionBackend.run_panel()`. The
runner in `tools/fusion/runner.py` is backend-agnostic.

The backend does ONLY panel fan-out. It does NOT run the judge. The
runner invokes the judge after `run_panel` returns. This is the single
source of truth for "who runs the judge" (Pass 2 review T1.1).
"""

from __future__ import annotations

import abc
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class PanelRequest:
    """What the runner passes to a backend's `run_panel`."""

    prompt: str
    analysis_models: list[str]
    temperature: float | None = None
    max_completion_tokens: int | None = None
    reasoning_effort: str | None = None
    max_tool_calls: int = 8
    timeout_seconds: int = 120


@dataclass
class PanelResponse:
    """What a backend's `run_panel` returns.

    `analysis` and `raw_judge_output` are populated by the RUNNER
    after `run_panel` returns, not by the backend. The backend
    returns these fields empty (or unset) and the runner fills them
    in via judge invocation. See `tools/fusion/runner.py` and the
    Pass 2 review (T1.1).
    """

    responses: list[dict[str, Any]] = field(default_factory=list)
    failed_models: list[dict[str, str]] = field(default_factory=list)
    analysis: dict[str, Any] | None = None
    raw_judge_output: str | None = None


class FusionBackend(abc.ABC):
    """Abstract base for fusion tool backends.

    Concrete backends:
    - `HermesNativeBackend` (default; uses asyncio.gather over the
      user's existing model providers via a stubbed `_call_single_model`
      in v0.1)
    - `OpenRouterFusionBackend` (opt-in; uses httpx to call OpenRouter's
      `openrouter:fusion` server tool)
    """

    name: str = ""

    @abc.abstractmethod
    async def run_panel(
        self,
        request: PanelRequest,
        *,
        outer_model: str,
        judge_model: str,
    ) -> PanelResponse:
        """Fan out the prompt to `request.analysis_models` in parallel.

        Returns a `PanelResponse` with `responses` (successful) and
        `failed_models` (per-member-FAIL — see plan §T2.1). The
        backend MUST NOT populate `analysis` or `raw_judge_output`;
        the runner owns the judge.
        """

    @abc.abstractmethod
    def check_requirements(self) -> bool:
        """Return True if this backend can run in the current environment.

        For hermes-native: requires the user to have at least 2
        models in their `model.fallback_providers` chain (per plan
        §T1.7).

        For openrouter-fusion: requires `OPENROUTER_API_KEY` to be
        set.
        """


class BackendRegistry:
    """In-process registry of backends. New backends add themselves
    via `register_backend()` in their `__init__.py`. See plan §T2.3.
    """

    def __init__(self) -> None:
        self._backends: dict[str, FusionBackend] = {}

    def register(self, backend: FusionBackend) -> None:
        if not backend.name:
            raise ValueError("Backend must have a non-empty `name`")
        if backend.name in self._backends:
            logger.debug(
                "Backend '%s' already registered; replacing with new instance",
                backend.name,
            )
        self._backends[backend.name] = backend
        logger.info("Registered fusion backend: %s", backend.name)

    def get(self, name: str) -> FusionBackend:
        try:
            return self._backends[name]
        except KeyError as exc:
            raise KeyError(
                f"No fusion backend named '{name}'. "
                f"Available: {sorted(self._backends)}"
            ) from exc

    def names(self) -> list[str]:
        return sorted(self._backends)

    def available(self) -> list[str]:
        """Names of backends whose `check_requirements()` returns True."""
        return [name for name, b in self._backends.items() if b.check_requirements()]


# Module-level singleton. Backends call `register_backend(...)` at
# import time; the runner calls `get_backend(name)` per call.
_registry = BackendRegistry()


def register_backend(backend: FusionBackend) -> None:
    """Register a backend in the module-level registry."""
    _registry.register(backend)


def get_backend(name: str) -> FusionBackend:
    """Look up a registered backend by name."""
    return _registry.get(name)


def list_backends() -> list[str]:
    """List all registered backend names (whether available or not)."""
    return _registry.names()


def list_available_backends() -> list[str]:
    """List backend names whose `check_requirements()` returns True."""
    return _registry.available()
