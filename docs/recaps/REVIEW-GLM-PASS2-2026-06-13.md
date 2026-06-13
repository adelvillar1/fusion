# Cross-LLM Review — Pass 2 (Buildability / Subagent-Interpretation Lens)

**Provider:** GLM-5.1
**Model:** glm-5.1
**Latency:** 69199ms
**Tokens in/out:** 9919/8192
**Error:** none

**Artifact:** `docs/plans/2026-06-13-fusion-tool-design.md` (v2, 32 KB, 705 lines)

**Brief:** Pattern 4b from `cross-llm-review` skill — buildability lens with explicit
"do NOT re-flag" list of v1 fixes that carried over to v2.

---

# Pass 2 Review: Fusion Tool Design v2 (Buildability Lens)

## TIER 1 — Blockers for delegation

### T1.1 — The judge cannot run as a panel member (§4.3 contradicts §4.2)

**WHERE:** §4.3 says *"The judge runs as one of the panel members — either the explicit judge_model or a designated slot."* §4.2 step 4 says *"If backend didn't produce analysis, run the judge separately."*

**WHY:** The judge needs all panel responses as input to produce `StructuredAnalysis`. If the judge runs as a concurrent panel member via `asyncio.gather`, it cannot see the other responses. A subagent implementing §4.3 literally will produce a judge call that receives zero panel responses and generates garbage. §4.2 is correct; §4.3 is wrong.

**FIX:** Delete the sentence *"The judge runs as one of the panel members"* from §4.3. Replace with: *"The judge runs as a **second phase** after all panel members complete. The runner orchestrates this: the backend fans out the panel, returns responses, and the runner invokes the judge with the panel's outputs."* Add a note: *"The judge model MUST NOT be called concurrently with the panel. It requires all panel responses as input."*

---

### T1.2 — Runner has no model client to invoke the judge (§4.2 step 4 is unimplementable)

**WHERE:** §4.2 step 4: *"If backend didn't produce analysis, run the judge separately (hermes-native does this; openrouter-fusion does it server-side)."*

**WHY:** The runner is described as "backend-agnostic" but needs to invoke a model (the judge) for hermes-native. The runner has no reference to `auxiliary_client`, no model routing, no provider keys. A subagent will either (a) import model client code into the runner (breaking backend-agnosticism), (b) add a `run_judge()` method to the ABC (which OpenRouter doesn't need), or (c) have the hermes-native backend always run the judge internally and never return `analysis=None` (making step 4 dead code for hermes-native).

**FIX:** Add a second abstract method to `FusionBackend`:

```python
@abstractmethod
async def run_judge(
    self,
    panel_responses: list[dict],
    judge_model: str,
    **kwargs,
) -> tuple[StructuredAnalysis | None, str | None]:
    """Run the judge on panel responses. Returns (analysis, raw_output).
    Backends that run the judge server-side return (analysis, None).
    Backends that skip the judge return (None, None)."""
```

For `HermesNativeBackend`, `run_judge` calls `auxiliary_client` with the judge model. For `OpenRouterFusionBackend`, `run_judge` returns `(None, None)` because the judge ran server-side inside `run_panel`. The runner calls `run_judge` only if `PanelResponse.analysis is None`. This keeps the runner backend-agnostic and gives each backend explicit control over judge invocation.

---

### T1.3 — Circular import: ContextVar in `run_agent.py`, runner imports it (§4.4, §8)

**WHERE:** §4.4: *"A request-scoped `contextvars.ContextVar[int]` named `_fusion_depth` lives in `run_agent.py`."* §8: *"add `_fusion_depth: ContextVar[int] = ContextVar('fusion_depth', default=0)` at module level"* in `run_agent.py`.

**WHY:** Import chain: `run_agent.py` → tool registry → `fusion_tool.py` → `runner.py` → needs `_fusion_depth` from `run_agent.py`. This is a circular import. A subagent will either hit `ImportError` at runtime or create a fragile workaround.

**FIX:** Define `_fusion_depth` in a standalone module with no upstream imports:

```
tools/fusion/guard.py   # contains _fusion_depth: ContextVar[int] = ContextVar(...)
```

Both `run_agent.py` and `runner.py` import from `tools/fusion/guard.py`. No cycle. The `run_agent.py` modification becomes: `from tools.fusion.guard import _fusion_depth` and wrap the tool dispatch in `_fusion_depth.set(_fusion_depth.get() + 1)` / `finally: _fusion_depth.reset(token)`.

---

### T1.4 — Cost guard can't check panel size when `analysis_models` is auto-populated (§4.2 step 2, §5)

**WHERE:** §4.2 step 2: *"Cost guard — refuse if len(panel_models) > max_panel_size"*. §5: *"analysis_models: [] # empty = auto-populate from fallback chain"*.

**WHY:** When `analysis_models=[]`, the runner receives an empty list. The cost guard sees `len([]) = 0 < 8` and passes. The backend then auto-populates 3-8 models from the fallback chain. The actual cost exceeds what the guard checked. A subagent will implement the guard before resolution, making it ineffective for the default case.

**FIX:** Model resolution must happen BEFORE the cost guard. Add an explicit resolution step to the runner:

```python
async def run(self, prompt, panel_models, **kwargs):
    # 0. Resolve panel models (empty list → auto-populate from config)
    resolved_models = self._resolve_panel_models(panel_models)
    # 1. Recursion guard
    # 2. Cost guard — check len(resolved_models)
    if len(resolved_models) > self.config.max_panel_size:
        raise ValueError(...)
    # 3. Backend.run_panel with resolved_models
```

Define `_resolve_panel_models` in the runner (not the backend) since it reads from `FusionConfig.analysis_models` and `model.fallback_providers`. The backend receives a fully-resolved list.

---

### T1.5 — `analysis_models` auto-population rule is undefined (§5)

**WHERE:** §5: *"analysis_models: [] # empty = auto-populate from fallback chain"*

**WHY:** A subagent has zero guidance on how many models to select, which models to prefer, or what to do if the fallback chain has 1 model or 10. This is a core behavioral spec, not an implementation detail.

**FIX:** Add an explicit rule to §5:

> When `analysis_models` is empty, the runner auto-populates from `model.fallback_providers`:
> - Take the first **3** models from the chain (or fewer if the chain is shorter).
> - Deduplicate by provider (don't call the same provider twice with different model IDs unless the user explicitly listed them).
> - If the chain has fewer than 2 models, refuse with: *"Fusion requires at least 2 distinct models. Configure `model.fallback_providers` with 2+ models or specify `analysis_models` explicitly."*
> - The auto-populated list is capped by `max_panel_size` (default 8).

---

### T1.6 — `check_requirements()` for hermes-native returns True even with zero providers (§4.1)

**WHERE:** §4.1: *"hermes-native always returns True"* and `check_requirements` returns `True` with comment *"no external deps; uses existing model slots"*.

**WHY:** If the user has no providers configured (empty `fallback_providers`), hermes-native can't run any panel members. `check_requirements` returning `True` means the tool will attempt fan-out, get zero responses, and hit the all-panel-failed path. The error message will be opaque. A subagent will implement `return True` literally.

**FIX:** `HermesNativeBackend.check_requirements()` should verify:

```python
def check_requirements(self) -> bool:
    return len(self._get_available_models()) >= 2
```

Where `_get_available_models()` reads from the config's `model.fallback_providers`. If < 2 models are available, `check_requirements` returns `False`, and the tool returns a clear error: *"hermes-native backend requires at least 2 models in `model.fallback_providers`. Found {n}. Configure providers or use a different backend."*

---

### T1.7 — Per-panel-member fallback semantics are undecided (§9 Q3)

**WHERE:** §9 Q3: *"How should hermes-native handle the `model.fallback_providers` chain — apply it per panel member, or run the chain sequentially?"*

**WHY:** This is a core behavioral decision that changes the entire fan-out implementation. A subagent cannot implement the hermes-native backend without it. Option (a) "per-member fallback" means each panel slot tries models in order; option (b) "fail the member" means one failure removes that slot. These produce different `PanelResponse` shapes and different cost profiles.

**FIX:** Make a decision in the plan. I recommend **option (b): fail the member, report in `failed_models`**. Rationale: per-member fallback hides which model actually responded (the user asked for Claude but got DeepSeek), making the structured analysis misleading. If Claude fails, report it as a failure. The user can add DeepSeek to the panel explicitly. Add to §4.3:

> *"If a panel member's primary model fails, the member is reported in `failed_models` with the failure reason. The backend does NOT activate the fallback chain for individual panel members. The fallback chain is used only for model resolution (populating the panel list), not for per-member retry."*

---

## TIER 2 — Will cause confusion or rework

### T2.1 — `PanelResponse.analysis` typed as `dict | None` should be `StructuredAnalysis | None` (§4.1)

**WHERE:** §4.1 `PanelResponse.analysis: dict | None`

**WHY:** §4.5 defines `StructuredAnalysis` as a Pydantic model. If `analysis` is a `dict`, then hermes-native must `.model_dump()` its parsed `StructuredAnalysis` into a dict, and the runner must re-parse it back. This round-trip serialization is wasteful and error-prone. The OpenRouter backend would need to parse its JSON response into `StructuredAnalysis` anyway (for validation). Both backends should produce typed output.

**FIX:** Change `PanelResponse.analysis` to `StructuredAnalysis | None`. Both backends parse their judge output into `StructuredAnalysis` before returning. The runner works with typed data throughout.

---

### T2.2 — Backend registry mechanism is unspecified (§4.1, §2)

**WHERE:** §2 lists `tools/fusion/backends/__init__.py` as "Backend registry" but doesn't describe the mechanism.

**WHY:** A subagent needs to know: is it a dict? A class decorator? An entry point? How does the tool select a backend by name? How does a new backend register itself?

**FIX:** Add to §4.1:

```python
# tools/fusion/backends/__init__.py
_REGISTRY: dict[str, type[FusionBackend]] = {}

def register_backend(cls: type[FusionBackend]) -> type[FusionBackend]:
    _REGISTRY[cls.name] = cls
    return cls

def get_backend(name: str) -> FusionBackend:
    if name not in _REGISTRY:
        raise ValueError(f"Unknown fusion backend: {name!r}. Available: {list(_REGISTRY.keys())}")
    return _REGISTRY[name]()
```

Backends use `@register_backend` as a class decorator. The tool looks up backends by name via `get_backend(config.backend)`.

---

### T2.3 — `auxiliary_client.py` extension: core change or local module? (§8)

**WHERE:** §8: *"May not be a true core change — could be a new module under `tools/fusion/`."*

**WHY:** "May or may not" is not implementable. A subagent will guess, and the wrong choice creates either (a) an unnecessary core dependency or (b) duplicated client logic.

**FIX:** Make a decision. For v0.1, create `tools/fusion/panel_client.py` as a local module that wraps `auxiliary_client` calls. It imports `auxiliary_client.call_model()` and adds `asyncio.gather` semantics on top. No core change needed. If profiling shows this should be in core, promote it in v0.2. Add to §8: *"v0.1 decision: `tools/fusion/panel_client.py` wraps `auxiliary_client` locally. No core change required."*

---

### T2.4 — Tool name is still undecided (§9 T1, §2, §10)

**WHERE:** §2: *"The `openrouter_fusion` name stays for v0.1"*, §9 T1: *"Recommendation: rename to `fusion` in v0.1"*, §10: *"openrouter_fusion (or fusion — see §9 T1)"*

**WHY:** A subagent cannot implement the tool registration without a definitive name. The acceptance criteria reference both names with an "or."

**FIX:** Pick one. The plan's own recommendation is `fusion`. Use `fusion` as the tool name. If v1 compat is needed, add a one-line alias in the tool registry: `"openrouter_fusion": fusion_tool` with a deprecation warning. Update §2, §3, §10 to use `fusion` consistently.

---

### T2.5 — Curator slot fallback when provider is unavailable (§9 Q8)

**WHERE:** §9 Q8: *"What if the user has it set to a model that's not in their fallback chain?"*

**WHY:** A subagent implementing `judge_strategy: auxiliary-curator` needs to know what happens when the curator's provider has no API key. The plan asks the question but doesn't answer it.

**FIX:** Add to §4.5 or §5:

> *"If `judge_strategy` is `auxiliary-curator` and the curator model's provider is unavailable (no API key, provider down), fall back to `outer-model` and log a warning: `'Curator model {model} unavailable; falling back to outer model {outer_model}'`. If the outer model is also unavailable, skip the judge and return raw panel responses."*

---

### T2.6 — `max_tool_calls` is meaningless for hermes-native in v0.1 (§3)

**WHERE:** §3: *"hermes-native caps the per-panel-member iteration count"*

**WHY:** In v0.1, panel members are plain model calls with no tool-use loop (§2 out-of-scope: "Web-search delegation to panel models — v0.1 explicitly disabled"). A "per-panel-member iteration count" doesn't exist for a single completion call. A subagent will either (a) implement a mini-agent loop per panel member (massive scope creep) or (b) ignore the parameter silently (misleading).

**FIX:** Add to §3: *"For hermes-native in v0.1, `max_tool_calls` is accepted but ignored — panel members make single completion calls without tool use. v0.2 may enable tool-calling panel members."* Update the schema description to: *"Max