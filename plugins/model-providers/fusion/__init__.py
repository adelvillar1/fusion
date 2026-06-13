"""Fusion provider profile.

This plugin exposes ``openrouter/fusion`` as a selectable model in
``hermes model`` and the slash command. It does NOT add a new inference
backend — the underlying API is still OpenRouter's ``/api/v1/chat/completions``
with the ``openrouter:fusion`` server tool enabled. The plugin's job is
to make the fusion alias discoverable as a primary model, so the user can
set ``model.default: openrouter/fusion`` and have the entire agent loop
deliberate through a panel of models by default.

The companion tool ``openrouter_fusion`` (in ``tools/fusion_tool.py``) is
the explicit per-call entry point; this plugin is the "always-on"
config-time entry point.
"""

from providers import register_provider
from providers.base import ProviderProfile


class FusionProfile(ProviderProfile):
    """Profile that re-uses OpenRouter's auth + endpoint, but advertises
    only the ``openrouter/fusion`` model alias.
    """

    # The fusion alias is a server-routed model on OpenRouter. Auth and
    # endpoint mirror the openrouter plugin. We don't fetch a model list
    # from OpenRouter — the alias is fixed.

    @property
    def name(self) -> str:
        return "fusion"

    @property
    def base_url(self) -> str:
        return "https://openrouter.ai/api/v1"

    @property
    def env_vars(self) -> tuple[str, ...]:
        return ("OPENROUTER_API_KEY",)

    @property
    def auth_type(self) -> str:
        return "api_key"

    def fetch_models(self, *, api_key: str | None = None, timeout: float = 8.0) -> list[str] | None:
        # Single fixed alias. We do not hit the OpenRouter /models endpoint
        # because the alias is server-routed, not a model on the catalog.
        return ["openrouter/fusion"]


register_provider(FusionProfile())
