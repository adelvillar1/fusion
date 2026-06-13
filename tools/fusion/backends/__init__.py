"""Fusion backend package.

Backends register themselves at import time via `register_backend()`.
The `tools/fusion_tool.py` module imports each backend module to
trigger registration. Adding a new backend = drop a new file here
+ import it from `tools/fusion_tool.py`.
"""

from tools.fusion.backends.base import (
    FusionBackend,
    PanelRequest,
    PanelResponse,
    BackendRegistry,
    register_backend,
    get_backend,
    list_backends,
    list_available_backends,
)

# Import concrete backends so they register themselves.
# Order doesn't matter; register_backend is idempotent.
try:
    from tools.fusion.backends import hermes_native  # noqa: F401
except ImportError as exc:  # pragma: no cover
    import logging
    logging.getLogger(__name__).warning(
        "Could not import hermes_native backend: %s", exc
    )

try:
    from tools.fusion.backends import openrouter_fusion  # noqa: F401
except ImportError as exc:  # pragma: no cover
    import logging
    logging.getLogger(__name__).warning(
        "Could not import openrouter_fusion backend: %s", exc
    )

__all__ = [
    "FusionBackend",
    "PanelRequest",
    "PanelResponse",
    "BackendRegistry",
    "register_backend",
    "get_backend",
    "list_backends",
    "list_available_backends",
]
