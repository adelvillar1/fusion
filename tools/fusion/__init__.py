"""Fusion tool backend package.

The fusion tool is a backend-pluggable multi-model deliberation system.
A panel of LLMs runs in parallel; a judge model produces a structured
analysis (consensus / contradictions / unique insights / blind spots).
The runner in this package orchestrates backend-agnostic concerns
(recursion guard, cost guard, judge invocation); concrete backends
implement `FusionBackend.run_panel()`.
"""

from tools.fusion.analysis import (
    StructuredAnalysis,
    JUDGE_PROMPT,
    Contradiction,
    PartialCoverage,
    UniqueInsight,
)
from tools.fusion.runner import FusionRunner, FusionConfig, _fusion_depth
from tools.fusion.backends import (
    FusionBackend,
    PanelRequest,
    PanelResponse,
    BackendRegistry,
    register_backend,
    get_backend,
    list_backends,
)

__all__ = [
    "StructuredAnalysis",
    "JUDGE_PROMPT",
    "Contradiction",
    "PartialCoverage",
    "UniqueInsight",
    "FusionRunner",
    "FusionConfig",
    "_fusion_depth",
    "FusionBackend",
    "PanelRequest",
    "PanelResponse",
    "BackendRegistry",
    "register_backend",
    "get_backend",
    "list_backends",
]
