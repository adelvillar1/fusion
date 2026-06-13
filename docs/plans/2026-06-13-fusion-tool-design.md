# Fusion Tool — Design Plan v2 (Hermes-native, backend-pluggable)

**Date:** 2026-06-13
**Status:** Draft, awaiting Pass 2 cross-LLM review
**Author:** Alejandro del Villar (via Hermes)
**Repo:** `adelvillar1/fusion`
**Supersedes:** `archive/2026-06-13-fusion-tool-design-v1-ORwrapper.md` (v1 was
a thin wrapper around OpenRouter's `openrouter:fusion` server tool. v2
generalizes the tool and ships a `hermes-native` backend as the v0.1 default.)

---

## 1. Problem statement

Hermes Agent's built-in `moa` (Mixture-of-Agents) tool runs a panel of LLMs
in parallel and returns a single synthesized answer from an aggregator
model. This is good for "give me the best answer" tasks but bad for
"where do experts disagree" tasks — the synthesis step *hides* the
disagreement instead of surfacing it.

External systems (OpenRouter's `openrouter:fusion`, Anthropic's batch API,
academic multi-agent frameworks) do **multi-model deliberation with
structured analysis**: a panel runs in parallel, a judge compares
responses, and the caller receives a structured map of consensus,
contradictions, unique insights, and blind spots. The caller can then
either accept the map as the answer (auditable) or synthesize a final
response (best-answer-with-evidence).

**Goal:** give Hermes Agent first-class multi-model deliberation with
structured analysis, with no external dependency in the default path.

**v1 mistake (corrected here):** The first plan wrapped OpenRouter's
`openrouter:fusion` server tool. That made OpenRouter a hard dependency
for the only shipped backend, locked the user into OpenRouter pricing
(even on models the user already pays for via direct API keys), and
excluded users who don't use OpenRouter at all. v2 fixes this by
making the tool backend-pluggable and shipping a `hermes-native` backend
that uses Hermes's existing model slots to fan out locally.

---

## 2. Scope

### File manifest (v0.1)

| File | Purpose |
|------|---------|
| `tools/fusion_tool.py` | Tool implementation + `registry.register()` (tool name: `fusion`) |
| `tools/fusion/` | Package: backend-agnostic core |
| `tools/fusion/__init__.py` | Re-exports |
| `tools/fusion/analysis.py` | Shared `StructuredAnalysis` Pydantic model + judge prompt |
| `tools/fusion/runner.py` | Async fan-out + judge orchestration (backend-agnostic) |
| `tools/fusion/backends/__init__.py` | Backend registry |
| `tools/fusion/backends/base.py` | `FusionBackend` ABC: `async def run_panel(...)` |
| `tools/fusion/backends/hermes_native.py` | **v0.1 default.** asyncio.gather over `model.fallback_providers` chain |
| `tools/fusion/backends/openrouter_fusion.py` | Optional backend. Pass-through to OpenRouter's `openrouter:fusion` server tool. |
| `tests/test_fusion_tool.py` | 11 unit tests |
| `tests/test_fusion_runner.py` | Runner orchestration tests (mocked backends) |
| `tests/test_fusion_hermes_native.py` | hermes-native backend tests (mocked model slots) |
| `tests/test_fusion_backends.py` | Backend ABC conformance + registry tests |
| `tests/fixtures/` | Recorded responses for the hermes-native backend |
| `tests/test_fusion_tool_recorded.py` | 4 recorded-fixture tests (success, judge-degraded, all-failed, partial) |
| `scripts/record_fusion.py` | Record-mode harness against live backends (manual) |
| `scripts/sanitize_fusion_fixture.py` | Strip PII / credentials from recorded fixtures |
| `docs/architecture/recursion-guard.md` | How the `ContextVar`-based guard integrates with `run_agent.py` |
| `docs/architecture/cost-model.md` | Per-backend pricing + panel-cost math |
| `docs/architecture/backends.md` | Backend ABC + how to write a new one |

### In scope (v0.1)

- A single tool `openrouter_fusion` (kept name for v1 history; renames
  in v0.2 — see T2 below) in the `fusion_tools` toolset
- Pluggable backends via a `FusionBackend` ABC
- `hermes-native` backend (v0.1 default, **no external dependency**)
- `openrouter-fusion` backend (opt-in, requires `OPENROUTER_API_KEY`)
- Structured analysis via a shared `StructuredAnalysis` Pydantic model
  produced by a judge model
- Judge model selection: `outer-model` (zero cost) | `auxiliary-curator`
  (uses Hermes's existing curator slot) | `explicit-model`
- Recursion guard via `ContextVar` (per-call scope)
- Cost guard via `max_panel_size` (per-backend)
- Recorded-fixture test harness, offline-only CI

### Out of scope (v0.1)

- **Renaming the tool.** The `openrouter_fusion` name stays for v0.1
  (avoids churn; reflects v1 history). v0.2 renames to `fusion` once
  the hermes-native backend is well-tested and the OpenRouter-specific
  name is no longer load-bearing. The toolset key `fusion_tools` is
  already backend-agnostic.
- **Anthropic batch API backend** — v0.2.
- **Provider plugin (`openrouter/fusion` as a selectable primary model)** —
  deferred to v0.2 (unguarded cost-explosion path; same blocker as v1).
- **Streaming tool results** — v0.2.
- **Observability/metrics** — v0.2 (basic logging in v0.1).
- **The `force` parameter and cost-guard override** — deferred to v0.2.
  v0.1 always uses the user's intent (the agent's tool call) and the
  cost guard is a hard wall.
- **Web-search delegation to panel models** — v0.1 explicitly disabled.
- **Upstream PR to hermes-agent** — deferred to v0.1.1 (battle-test locally first).

---

## 3. Tool schema

Tool name: **`fusion`** (renamed from v1's `openrouter_fusion` per Pass
2 T1.2 — v0.1 hasn't shipped, no v1 to be compatible with, and the
v2 plan's thesis is "OpenRouter is opt-in"). Toolset: `fusion_tools`.

```python
{
    "name": "fusion",
    "description": (
        "Run the user prompt through a panel of 2-8 models in parallel and "
        "have a judge model produce a structured analysis (consensus, "
        "contradictions, unique insights, blind spots) plus the raw panel "
        "responses. Use for 'where do experts disagree' or high-stakes "
        "multi-perspective tasks. The default backend (hermes-native) uses "
        "your existing model providers — no external dependency."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description": "The prompt to send to the panel.",
            },
            "analysis_models": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 2,
                "maxItems": 16,
                "description": (
                    "Panel models. Defaults to fusion.analysis_models from "
                    "config.yaml (default: 2-3 models from your existing "
                    "model.fallback_providers chain). Hard cap is schema "
                    "maxItems (16); runtime cost guard is "
                    "fusion.max_panel_size (default 8)."
                ),
            },
            "backend": {
                "type": "string",
                "enum": ["hermes-native", "openrouter-fusion"],
                "default": "hermes-native",
                "description": (
                    "Which backend to use. 'hermes-native' is the default "
                    "and uses your existing model providers (no external "
                    "dependency). 'openrouter-fusion' passes through to "
                    "OpenRouter's server tool and requires OPENROUTER_API_KEY."
                ),
            },
            "judge_strategy": {
                "type": ["string", "null"],
                "enum": ["outer-model", "auxiliary-curator", "explicit-model", None],
                "default": "outer-model",
                "description": (
                    "How to pick the judge model. 'outer-model' = the same "
                    "model that invoked this tool (zero extra cost). "
                    "'auxiliary-curator' = the agent's configured curator "
                    "slot (typically a strong reasoning model). "
                    "'explicit-model' = set judge_model explicitly."
                ),
            },
            "judge_model": {
                "type": "string",
                "description": (
                    "Explicit judge model. Required when judge_strategy is "
                    "'explicit-model'. For 'outer-model' / 'auxiliary-curator' "
                    "the value is ignored."
                ),
            },
            "max_tool_calls": {
                "type": "integer",
                "minimum": 1,
                "maximum": 16,
                "default": 8,
                "description": (
                    "Max tool-calling steps the panel/judge models can make. "
                    "Backend-specific interpretation; hermes-native caps the "
                    "per-panel-member iteration count, openrouter-fusion "
                    "passes to OpenRouter's per-panel-member limit."
                ),
            },
            "max_completion_tokens": {
                "type": "integer",
                "description": "Max output tokens per panel/judge response.",
            },
            "reasoning_effort": {
                "type": ["string", "null"],
                "enum": ["low", "medium", "high"],
                "description": "Reasoning effort for panel/judge models.",
            },
            "temperature": {
                "type": "number",
                "minimum": 0,
                "maximum": 2,
                "description": "Sampling temperature. Provider default if unset.",
            },
            "timeout_seconds": {
                "type": "integer",
                "minimum": 10,
                "maximum": 600,
                "default": 120,
                "description": "Max wall-clock seconds. Raises TimeoutError on exceed.",
            },
        },
        "required": ["prompt"],
        "additionalProperties": False,
    },
}
```

---

## 4. Architecture: backend-pluggable

The tool is a thin orchestrator. The real work happens in backends.

### 4.1 The `FusionBackend` ABC

```python
# tools/fusion/backends/base.py
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

@dataclass
class PanelRequest:
    prompt: str
    analysis_models: list[str]              # backend-resolved
    temperature: float | None
    max_completion_tokens: int | None
    reasoning_effort: str | None
    max_tool_calls: int
    timeout_seconds: int

@dataclass
class PanelResponse:
    responses: list[dict]                    # [{"model": str, "content": str, ...}, ...]
    failed_models: list[dict]                # [{"model": str, "reason": str}, ...]
    # Backends fill ONE of:
    analysis: dict | None                    # StructuredAnalysis JSON (if judge ran)
    raw_judge_output: str | None             # raw judge model output (if analysis failed to parse)

class FusionBackend(ABC):
    name: str                                # "hermes-native" | "openrouter-fusion"

    @abstractmethod
    async def run_panel(
        self,
        request: PanelRequest,
        *,
        outer_model: str,                    # for backend routing decisions
        judge_model: str,                    # resolved by the runner before this call
    ) -> PanelResponse: ...

    @abstractmethod
    def check_requirements(self) -> bool: ...  # returns True if backend can run
                                                # (e.g. hermes-native always; openrouter-fusion
                                                #  requires OPENROUTER_API_KEY)
```

### 4.2 The runner (backend-agnostic orchestration)

The **runner owns the judge.** Backends only do panel fan-out; the runner
post-processes the panel response to produce the structured analysis.
This is the single source of truth for "who runs the judge" and is
consistent with the cost model in §6.1 (judge receives 18K+ input tokens
concatenated from all panel responses).

```python
# tools/fusion/runner.py
from contextvars import ContextVar

# Plugin-owned recursion guard (not in hermes-agent core).
# A subagent implementing this MUST define its own ContextVar — do NOT
# import one from run_agent.py (circular import; hermes-agent doesn't
# know about the plugin).
_fusion_depth: ContextVar[int] = ContextVar('fusion_depth', default=0)

class FusionRunner:
    def __init__(self, backend: FusionBackend, default_judge_model: str, config: FusionConfig):
        self.backend = backend
        self.default_judge_model = default_judge_model
        self.config = config  # built once from config.yaml at tool registration

    async def run(self, prompt: str, panel_models: list[str], **overrides) -> PanelResponse:
        # 1. Recursion guard: ContextVar.set/reset around the whole call
        token = _fusion_depth.set(_fusion_depth.get() + 1)
        try:
            # 2. Cost guard — refuse if len(panel_models) > max_panel_size
            self._check_cost_guard(panel_models)

            # 3. Backend fan-out (backend does NOT do the judge)
            request = PanelRequest(prompt=prompt, analysis_models=panel_models, ...)
            panel_response = await self.backend.run_panel(request, ...)

            # 4. Runner invokes the judge (NOT the backend)
            if panel_response.responses:
                judge_model = self._resolve_judge_model(overrides)
                analysis, raw = await self._invoke_judge(prompt, panel_response, judge_model)
                panel_response.analysis = analysis
                panel_response.raw_judge_output = raw

            return panel_response
        finally:
            _fusion_depth.reset(token)
```

The runner is the same regardless of backend. The backend decides how
to fan out (local `asyncio.gather` vs. server-side OpenRouter call) and
returns a `PanelResponse` with empty `analysis` and empty
`raw_judge_output`. The runner fills those fields in.

**Note on `max_tool_calls` for hermes-native v0.1:** this parameter is
accepted in the schema and passed to the backend, but the hermes-native
backend **ignores it** in v0.1 (panel members make single completion
calls; no tool-calling loop). Only the openrouter-fusion backend
currently uses it. v0.2 may add tool-use loops to hermes-native panel
members.

### 4.3 The hermes-native backend

```python
# tools/fusion/backends/hermes_native.py
class HermesNativeBackend(FusionBackend):
    name = "hermes-native"

    def check_requirements(self) -> bool:
        """Hermes-native needs at least 2 models in the fallback chain.
        If fewer are configured, the tool is not callable and check_requirements
        returns False so the agent sees a clear 'fusion not available' status
        instead of a confusing runtime error.
        """
        cfg = _load_hermes_config()
        providers = cfg.get("model", {}).get("fallback_providers", [])
        return len(providers) >= 2

    async def run_panel(self, request: PanelRequest, *, outer_model, judge_model) -> PanelResponse:
        # v0.1 semantics: per-member-fail, NOT per-member-substitute.
        # If a panel member fails, it appears in `failed_models` and the
        # panel continues with the remaining members. The user gets the
        # panel they asked for, with explicit failure surfacing.
        # Per-member-substitute is v0.2 (requires resolved_model tracking).
        #
        # CRITICAL: asyncio.gather(..., return_exceptions=True) is required
        # so a single panel member's failure does NOT crash the whole call
        # and lose the successful responses. The §4.6 partial-failure-paths
        # contract depends on this.
        tasks = [
            _call_single_model(model, request)
            for model in request.analysis_models
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        responses, failed_models = [], []
        for model, result in zip(request.analysis_models, results):
            if isinstance(result, Exception):
                failed_models.append({
                    "model": model,
                    "reason": f"{type(result).__name__}: {result}",
                })
            else:
                responses.append({"model": model, "content": result})
        return PanelResponse(responses=responses, failed_models=failed_models)
```

The hermes-native backend uses the **same model clients Hermes already
uses** (`auxiliary_client.py`, the per-provider async clients in
`plugins/model-providers/*/`, the `model.fallback_providers` chain).
This means:

- If the user has Anthropic + DeepSeek + Kimi keys, the panel can be
  Claude + DeepSeek + Kimi without any new credentials.
- If a model in the panel fails (timeout, auth, rate limit), the
  **per-member-fail** path puts it in `failed_models`; the other
  members' responses are preserved.
- The user pays their existing provider rates, not OpenRouter's
  aggregator markup.
- The judge is invoked by the **runner** (see §4.2) after
  `run_panel` returns, not by the backend.

### 4.4 Recursion guard (plugin-owned ContextVar)

The recursion guard is a **plugin-owned** `ContextVar` defined in
`tools/fusion/runner.py`. The plugin MUST NOT import from
`~/.hermes/hermes-agent/run_agent.py` — that would be a circular import
(plugin → core → plugin) and is the wrong direction anyway. The
ContextVar is set/reset by the runner (see §4.2 pseudocode). The
upstream PR (v0.1.1) may add a shared registry in hermes-agent for
plugins to publish ContextVars they need the agent loop to wrap, but
that's not required for v0.1.

Per-call scope: two independent fusion calls in the same conversation
session both succeed (each call gets its own `set`/`reset` cycle).

### 4.5 The judge layer (shared between backends)

The runner invokes the judge model (the backend does NOT run the judge).
The judge receives the user's prompt plus all panel responses
concatenated, and produces a `StructuredAnalysis` JSON.

```python
# tools/fusion/analysis.py
JUDGE_PROMPT = """You are a meta-analyst. You have been given {N} responses
to the same prompt from different models. Compare them and produce a
structured JSON analysis.

Output ONLY this JSON shape (no other text):

{
  "consensus": ["Points all or most responses agree on"],
  "contradictions": [{"topic": "...", "stances": [{"model": "...", "stance": "..."}]}],
  "partial_coverage": [{"models": ["..."], "point": "Only some models raised this"}],
  "unique_insights": [{"model": "...", "insight": "Something only one model raised"}],
  "blind_spots": ["Topics no response addressed"]
}

Be honest about disagreements. Do not manufacture consensus."""

class StructuredAnalysis(BaseModel):
    consensus: list[str]
    contradictions: list[Contradiction]
    partial_coverage: list[PartialCoverage]
    unique_insights: list[UniqueInsight]
    blind_spots: list[str]
```

**Judge input assembly (runner-side):** the runner concatenates panel
responses into a single user message:

```
You have been given the following {N} responses to the same prompt:

[Response 1 from {model_1}]
{content_1}

[Response 2 from {model_2}]
{content_2}

...

{JUDGE_PROMPT}
```

The 18K input token count in §6.1 assumes 3 panel members × 6K average
response. The judge is invoked with `tool_choice: "required"` on the
inner call (so the OpenRouter backend's structured-analysis path is
also explicit), or via direct provider call for hermes-native.

**`judge_strategy` resolution (runner-side):**
1. `outer-model` (default, zero extra cost) — the same model that
   invoked the fusion tool
2. `auxiliary-curator` — the agent's configured curator slot (e.g.,
   Kimi K2.6). **Fallback:** if the curator's provider is unavailable,
   log a warning and fall back to `outer-model`. If the outer model is
   also unavailable, skip the judge and return raw panel responses
   (the outer model can synthesize from them).
3. `explicit-model` — use `judge_model` from the tool args

Both backends use this prompt and parse into `StructuredAnalysis`. The
OpenRouter backend gets the structured analysis for free (the server
tool does it). The hermes-native backend invokes the judge model
explicitly as a second round-trip (one extra model call).

### 4.6 Partial and total panel failure paths

The runner is backend-agnostic about failures. The backend reports
`failed_models` in its `PanelResponse`; the runner passes that through
to the outer model. Failure paths:

| Path | Backend returns | Runner behavior |
|------|----------------|-----------------|
| All panel members succeed, judge succeeds | `analysis` + `responses` | Pass through verbatim |
| All panel succeed, judge fails | `responses` only, no `analysis` | Pass through. Outer model synthesizes. |
| Some panel members fail | `analysis` (if judge ran) + partial `responses` + `failed_models` | Pass through verbatim. |
| All panel members fail | `responses: []` + `failed_models` (all entries) | Raise `RuntimeError`. Outer model can retry. |
| One panel model times out | `failed_models` includes it | Pass through. |
| Prompt exceeds a model's context | Backend puts it in `failed_models` | Pass through. |
| Judge produces malformed JSON | `raw_judge_output` populated, no `analysis` | Pass through. Outer model sees the raw judge output. |
| Backend credit exhaustion | Backend raises mid-fan-out | `RuntimeError`. No retry. |
| Second fusion call in same turn (recursion) | Runner raises `RecursionError` before backend call | Caught at the runner. |

The runner does **not** synthesize, retry, or massage responses. It is
a faithful pass-through. The outer model handles partial data.

---

## 5. Configuration

```yaml
# config.yaml
fusion:
  # Default backend. v0.1 ships hermes-native (no deps) and
  # openrouter-fusion (requires OPENROUTER_API_KEY).
  backend: "hermes-native"

  # Default panel. Override per-call via the tool's `analysis_models` param.
  # Default: take the first 3 entries of model.fallback_providers.
  # Auto-population rule: if `analysis_models` is empty, the runner reads
  # model.fallback_providers and uses the first 3 entries (or all of them
  # if fewer than 3). If the chain has <2 entries, check_requirements
  # returns False and the tool is not callable (clear error to user).
  analysis_models: []   # empty = auto-populate (first 3 of fallback chain)

  # Judge model selection.
  judge_strategy: "outer-model"   # outer-model | auxiliary-curator | explicit-model
  judge_model: null               # only used when judge_strategy == "explicit-model"
  judge_model_default: "kimi-k2.6"  # fallback if outer-model isn't routable

  max_tool_calls: 8
  # Hard cost guard — schema maxItems is 16; this is the runtime cap.
  # In v0.1 there is NO override — the guard is a hard wall.
  max_panel_size: 8
  timeout_seconds: 120

  # Per-backend config.
  backends:
    hermes-native:
      # Use the user's existing model.fallback_providers chain.
      # Inherit reasoning/temperature/timeout from fusion.* above.
      # No additional config needed in v0.1.
      pass
    openrouter-fusion:
      # Pass-through to OpenRouter's openrouter:fusion server tool.
      # Requires OPENROUTER_API_KEY.
      max_panel_size: 8   # OpenRouter's own hard cap
      # Web tools in OpenRouter's panel: v0.1 ships disabled
      # (matches v1 plan's safety posture).
      enable_web_tools: false
```

**Precedence (highest first):**
1. Tool-call arguments (per-call overrides)
2. `config.yaml fusion.*` (per-user defaults)
3. Schema defaults in §3 (last-resort fallbacks)

No new env vars. The only credential is whichever provider keys the
user already has set in `~/.hermes/.env` (for `hermes-native`) or
`OPENROUTER_API_KEY` (for `openrouter-fusion`).

---

## 6. Cost model

The cost profile is **radically different from v1** because hermes-native
reuses the user's existing provider relationships.

### 6.1 hermes-native (default, v0.1)

At default panel size of 3 (pulled from `model.fallback_providers`),
prompt ~2K tokens, response ~4K tokens:

| Component    | Tokens in+out | Cost basis |
|--------------|---------------|------------|
| Panel member | 2K + 4K       | User's direct provider rate (e.g., $0.03 Anthropic input + $0.30 Opus output) |
| 3 members    | 18K total     | Sum of per-provider rates (~$0.20–$0.40 if all cheap models; ~$1.00–$1.50 if all frontier) |
| Judge (curator slot, typically Kimi K2.6) | 18K in + ~2K structured-analysis out | User's Kimi rate (~$0.05–$0.10) |
| **Total**    |               | **~$0.25–$1.60/call** (varies wildly by panel model choice) |

**Key insight:** the user controls cost by choosing the panel. A panel
of `claude-haiku-latest` + `gpt-4.1-mini` + `gemini-flash-latest` is
~10× cheaper than a panel of all-Opus. The hermes-native backend
respects the user's existing budget and routing decisions.

### 6.2 openrouter-fusion (opt-in)

OpenRouter charges its aggregator markup on top of provider rates
(typically 5% credit fee). At panel of 3 with frontier models, $1.30–$2.00
per call (per v1 §6 corrected estimates). Useful when:

- The user wants the OpenRouter-specific structured-analysis pass
  (server-side judge, may be more reliable than hermes-native's
  curator-slot judge)
- The user has only OpenRouter credits, no direct provider keys
- The user wants OpenRouter's specific model routing (e.g., Pareto
  router, free-tier routing)

### 6.3 Cost guard

`max_panel_size: 8` caps the panel fan-out in both backends. v0.1 has
**no override**. The guard is a hard wall.

v0.2 may add a per-call dollar cap (`max_cost_usd: 5.00`) that aborts
before fan-out based on input-size × rate estimates.

---

## 7. Test strategy

- **Unit tests** (`tests/test_fusion_tool.py`): pure Python, no network.
  Use `unittest.mock` to stub the backend registry. Cover:
  - Schema validation (minItems, maxItems, additionalProperties: false,
    no `None` in enum)
  - JSON Schema validity via `jsonschema.validate()`
  - Default param resolution (args > config > schema precedence)
  - Backend selection (default `hermes-native`, opt-in `openrouter-fusion`)
  - Judge strategy resolution (outer-model / auxiliary-curator / explicit-model)
  - Recursion guard: `ContextVar` increments on entry, resets in `finally`,
    raises `RecursionError` when `>= 1`. Two consecutive calls succeed.
  - Cost guard refusal when `analysis_models` exceeds `max_panel_size`
- **Runner tests** (`tests/test_fusion_runner.py`): pure Python with a
  mock backend. Cover:
  - Backend failure propagation
  - Judge invocation (when backend doesn't do it server-side)
  - Judge-degradation passthrough
  - `failed_models` surface
  - All-panel-failed → `RuntimeError`
  - Partial-panel-failed → `failed_models` surfaced
- **Backend ABC tests** (`tests/test_fusion_backends.py`): every
  concrete backend must implement the ABC contract. Run against
  `HermesNativeBackend` with mocked model clients and against
  `OpenRouterFusionBackend` with a mocked `httpx.AsyncClient`.
- **hermes-native backend tests** (`tests/test_fusion_hermes_native.py`):
  mocked `auxiliary_client` calls, verifying:
  - `asyncio.gather(..., return_exceptions=True)` is used (a single
    failure does NOT lose the other responses)
  - Per-member-fail: a failed member appears in `failed_models`,
    other members' responses are preserved
  - Judge invocation via `auxiliary.curator` slot OR outer model
    (depending on `judge_strategy`)
  - Timeout enforcement via `asyncio.wait_for`
  - `check_requirements` returns False when fallback chain has <2
    models (with a test that doesn't have fallback_providers set)
- **Recorded-fixture tests** (`tests/test_fusion_tool_recorded.py`):
  replay sanitized `tests/fixtures/fusion-*.json` through the runner.
  Fixture format matches the `PanelResponse` shape:
  ```json
  {
    "backend": "hermes-native",
    "panel_request": {
      "prompt": "...",
      "analysis_models": ["claude-...", "deepseek-..."]
    },
    "expected_panel_response": {
      "responses": [{"model": "...", "content": "..."}, ...],
      "failed_models": [],
      "analysis": {"consensus": [...], "contradictions": [...], ...},
      "raw_judge_output": null
    }
  }
  ```
  Required fixtures:
  1. `success.json` — full success, both `analysis` and `responses` populated
  2. `judge-degraded.json` — panel succeeds, judge fails, no `analysis`
  3. `all-panel-failed.json` — `responses: []`, all models in `failed_models`
  4. `partial-panel-failed.json` — 1 of 3 models fails, `failed_models` populated
- **Record-mode script** (`scripts/record_fusion.py`): standalone script
  that hits a real backend and writes fixtures. Run manually; never in CI.
- **Sanitization script** (`scripts/sanitize_fusion_fixture.py`): strips
  PII and credentials from recorded fixtures before commit.
- **Cross-model live test** (manual): call the tool from a Hermes
  session with `--profile test` and verify both backends end-to-end.

No live network calls in CI. Matches the Hermes skill standards.

---

## 8. Integration points

### v0.1 (in this repo, shipped with the tool)

**No hermes-agent core changes are required for v0.1 to function.**
The plugin is self-contained:

1. **`tools/fusion/runner.py` defines the plugin's own `ContextVar[int]`
   named `_fusion_depth`** (see §4.4). The runner manages set/reset
   around each call. The plugin does not import from `run_agent.py`.

2. **`auxiliary_client.py` extension** (still in this repo, not in
   hermes-agent core): expose a `_panel_call()` helper that takes a
   list of model identifiers and fans out via
   `asyncio.gather(..., return_exceptions=True)`. The hermes-native
   backend uses this helper. (May end up being a function in
   `tools/fusion/backends/hermes_native.py` itself rather than an
   extension to `auxiliary_client.py` — the exact location is decided
   during implementation. The behavior is the same either way.)

### v0.1.1 (separate PR, after the plugin is battle-tested)

The v0.1.1 PR is **atomic** — all 5 items ship together as a coherent
unit. No ordering risk.

3. **`model_tools.py:224`** — add `"fusion_tools": ["fusion"]`
4. **`model_tools.py:_DEFAULT_OFF_TOOLSETS`** — add `"fusion_tools"`
5. **`toolsets.py` / `AGENTS.md`** — add `fusion` to the documented
   toolset keys
6. **Optional: `run_agent.py` patch** — if the upstream maintainers
   agree, add a shared ContextVar registry so the plugin's
   `_fusion_depth` is visible to the agent loop for tool-budget
   accounting. **Not required for v0.1** — the plugin self-guards
   today.

### Deferred to v0.2 (provider plugin)

7. **`plugins/model-providers/fusion/`** — full `ProviderProfile` for
   `openrouter/fusion` as a selectable primary model. Deferred because
   (a) unguarded cost-explosion path, (b) needs panel-aware model
   routing, (c) needs per-session cost caps.

---

## 9. Open questions for review (status after Pass 1 and Pass 2)

### Resolved in Pass 1 (carried into v2)

1. ~~Should the v0.1 tool name be `openrouter_fusion` or just `fusion`?~~
   **Resolved (Pass 2): `fusion`.** Renamed in v0.1 (T1.2). v0.1 hasn't
   shipped, no v1 to be compatible with. Schema description and AC
   updated throughout the plan.
2. ~~Should the judge be hermes-native's curator slot, or always an
   explicit model?~~ **Resolved (Pass 2 T2.5):** `outer-model` default;
   `auxiliary-curator` falls back to `outer-model` if unavailable;
   `outer-model` unavailable → skip the judge, return raw responses.
   See §4.5 resolution order.
3. ~~How should hermes-native handle the `model.fallback_providers`
   chain — apply it per panel member, or run the chain sequentially?~~
   **Resolved (Pass 2 T2.1):** v0.1 uses per-member-FAIL (a failed
   member appears in `failed_models`, others continue). Per-member-
   SUBSTITUTE is v0.2 (requires `resolved_model` tracking).
4. ~~Should the structured-analysis prompt be configurable?~~
   **Resolved (Pass 1): hard-coded default `JUDGE_PROMPT` in v0.1;
   config override is v0.2.** The plan's §4.5 documents the
   `StructuredAnalysis` Pydantic model so a config override is a
   trivial v0.2 follow-up.
5. ~~Web tools in panel members — both backends?~~ **Resolved (Pass 1):
   disabled in v0.1 in both backends (`enable_web_tools: false` in
   openrouter-fusion config; hermes-native doesn't have a tool-call
   loop in v0.1).** v0.2 may expose as opt-in.

### Resolved in Pass 2

6. ~~Is the backend-ABC contract the right granularity?~~ **Resolved
   (Pass 2 T3.1 follow-up): the current contract is fine for v0.1.
   `resolve_judge_model` per backend is a v0.2 exploration.**
7. ~~Should the hermes-native backend use the existing
   `auxiliary_client` or a new client?~~ **Resolved (Pass 2 §8.2):** the
   helper lives inside the plugin (`tools/fusion/`), not in
   `auxiliary_client.py`. The plugin is self-contained.
8. ~~Curator slot when its provider isn't in fallback_providers?~~
   **Resolved (Pass 2 T2.5): fall back to `outer-model`, then skip
   the judge. See §4.5.**
9. ~~What about hermes-native's behavior when
   `model.fallback_providers` is empty?~~ **Resolved (Pass 2 T1.7):
   `check_requirements` returns False; tool is not callable; clear
   error message to user.**
10. ~~Backwards compat with v1's `openrouter_fusion` tool name.~~
    **Resolved (Pass 2 T1.2): no compat shim needed. v0.1 ships as
    `fusion`.** If a v1 prototype is out there, the rename is a
    one-line search-and-replace.

### Resolved (Pass 1, backfilled during Pass 2 cleanup)

- `max_tool_calls` is **ignored by hermes-native in v0.1** (no
  tool-call loop). Only openrouter-fusion uses it. See §4.2 note.
- `analysis_models=[]` auto-population = first 3 of fallback chain.
  See §5.
- Backend registry is explicit (`register_backend()` in plugin
  `__init__.py`), not Hermes's PluginManager. See §4.1.
- `FusionConfig` built once at tool registration; per-call overrides
  via kwargs to `run()`. See §4.2.
- v0.1.1 PR is atomic (all 5 items in one PR). No ordering risk. See §8.

---

## 10. Acceptance criteria

A PR that ships v0.1 is "done" when:

- [ ] The tool is named **`fusion`** (not `openrouter_fusion`) and
      registers in the `fusion_tools` toolset. Verified by
      `test_fusion_tool.py::test_registers_with_correct_toolset`
- [ ] Schema is valid JSON Schema (verified by `jsonschema.validate`)
- [ ] Tool default params resolve in the documented precedence order
      (args > config > schema)
- [ ] `FusionBackend` ABC is implemented by both `HermesNativeBackend`
      and `OpenRouterFusionBackend`
- [ ] `hermes-native` is the default backend; works with no
      `OPENROUTER_API_KEY` set (verified by a test that runs without
      the env var)
- [ ] `openrouter-fusion` is opt-in via the `backend` parameter or
      `fusion.backend` config; refuses if `OPENROUTER_API_KEY` unset
- [ ] Recursion guard: plugin's own `ContextVar[int]` in
      `tools/fusion/runner.py`, increments on entry, resets in
      `finally`, raises `RecursionError` when `>= 1`. Two consecutive
      calls in the same session both succeed.
- [ ] Cost guard refuses `analysis_models` length > `max_panel_size`
      (default 8), schema `maxItems: 16`
- [ ] Judge strategy resolution: `outer-model` (default), `auxiliary-curator`
      (falls back to `outer-model` if unavailable), `explicit-model`
      (requires `judge_model` arg)
- [ ] Runner owns the judge invocation (not the backend). The
      `analysis` field is populated by the runner after `run_panel`
      returns. The backend's `run_panel` leaves `analysis` and
      `raw_judge_output` empty.
- [ ] hermes-native uses `asyncio.gather(..., return_exceptions=True)`
      so a single panel member's failure does NOT lose the others
- [ ] hermes-native is per-member-FAIL (not per-member-substitute) in
      v0.1: a failed member appears in `failed_models`, the panel
      continues with the remaining members
- [ ] hermes-native `check_requirements` returns False when
      `model.fallback_providers` has <2 entries
- [ ] `StructuredAnalysis` Pydantic model is shared between backends
- [ ] All 11 unit tests pass; all 4 recorded-fixture tests pass
- [ ] All 4 runner orchestration tests pass
- [ ] All hermes-native backend tests pass with mocked `auxiliary_client`
- [ ] Required fixtures exist, are sanitized, and match the
      `PanelResponse` shape documented in §7
- [ ] `record_fusion.py` and `sanitize_fusion_fixture.py` exist
- [ ] This plan's §11 CHANGELOG is updated to reflect any design
      changes made during implementation
- [ ] Pass 3 cross-LLM review (or focused re-review) confirms no
      remaining Tier 1 items

### Out of v0.1 scope (deferred)

- [ ] v0.1.1: upstream PR with `model_tools.py` / `toolsets.py` /
      `AGENTS.md` additions (atomic PR, all 5 items together)
- [ ] v0.2: provider plugin (`plugins/model-providers/fusion/`) with
      per-session cost caps and picker warnings
- [ ] v0.2: `force` parameter and cost-guard override mechanism
- [ ] v0.2: per-member-substitute fallback semantics
- [ ] v0.2: tool-use loops in hermes-native panel members
- [ ] v0.2: Anthropic batch API backend
- [ ] v0.2: streaming tool results
- [ ] v0.2: per-call dollar cap (`max_cost_usd`)
- [ ] v0.2: configurable `JUDGE_PROMPT`

---

## 11. Changelog

- **2026-06-13 (v2 Pass 2 patches)** — Cross-LLM Pass 2 review
  (4/4 providers: DeepSeek, GLM, Kimi, Mimo). Buildability lens.
  8 Tier 1 + 9 Tier 2 items found, 5 Tier 3 follow-ups filed. All
  Tier 1 + Tier 2 patched into the v2 plan. See
  `docs/recaps/SESSION-RECAP-2026-06-13-CROSS-LLM-REVIEW-PASS2.md`.
  Highlights:
  - **T1.1:** Judge location contradiction (§4.2 vs §4.3 vs §6.1)
    resolved. The **runner owns the judge**, not the backend. The
    backend's `run_panel` returns empty `analysis` / empty
    `raw_judge_output`; the runner fills them in.
  - **T1.2:** Tool **renamed from `openrouter_fusion` to `fusion`**
    in v0.1. v0.1 hasn't shipped, no v1 compat to preserve. The
    "OpenRouter" name in the tool contradicted the v2 thesis.
  - **T1.3:** `asyncio.gather(..., return_exceptions=True)` is now
    **mandatory** in the hermes-native backend. Without it, a single
    panel member's failure would crash the call and lose the
    successful responses — directly contradicting the §4.6 partial-
    failure-paths contract.
  - **T1.4 + T1.5:** The recursion-guard `ContextVar` is now
    **plugin-owned** in `tools/fusion/runner.py`. The plugin no
    longer references `run_agent.py` (which doesn't exist in this
    repo anyway — it's in hermes-agent core). v0.1.1 upstream PR
    may add a shared ContextVar registry in hermes-agent for plugins
    to publish their guards, but that's a v0.1.1 / v0.2 follow-up.
  - **T1.6:** `max_tool_calls` is **ignored by hermes-native in v0.1**
    (no tool-call loop in single completion calls). Only the
    openrouter-fusion backend uses it.
  - **T1.7:** hermes-native `check_requirements` now verifies
    `model.fallback_providers` has ≥2 entries, returns False
    otherwise. Tool is not callable until configured.
  - **T1.8:** `analysis_models=[]` auto-population = first 3 of
    fallback chain (or all of them if fewer than 3).
  - **T2.1:** Per-member-FAIL semantics for hermes-native in v0.1
    (per-member-substitute is v0.2).
  - **T2.2:** `FusionConfig` built once at tool registration; per-call
    overrides via kwargs.
  - **T2.3:** Backend registry is explicit (`register_backend()` in
    plugin `__init__.py`), not Hermes's PluginManager.
  - **T2.4:** Recorded-fixture format documented in §7
    (`PanelResponse`-shaped JSON).
  - **T2.5:** `judge_strategy: auxiliary-curator` falls back to
    `outer-model`, then to skip-the-judge.
  - **T2.6:** `max_tool_calls` dead-weight fix (see T1.6).
  - **T2.7:** `judge_strategy` default contradiction resolved
    (`outer-model` is the default per §3; §4.5 example updated).
  - **T2.8:** Judge input assembly format documented
    ("You have been given the following {N} responses...").
  - **T2.9:** v0.1.1 PR atomicity confirmed (all 5 items in one PR).

- **2026-06-13 (v2 Pass 1 patches)** — Cross-LLM Pass 1 review
  (3/4 providers: DeepSeek, GLM, Mimo; Kimi failed with temperature
  bug). 11 Tier 1 + 8 Tier 2 items found. Most fixes carried over
  from v1 (they were about correctness, not OpenRouter-specificity).
  See `docs/recaps/SESSION-RECAP-2026-06-13-CROSS-LLM-REVIEW.md`.
  Highlights: dropped `force` parameter, switched to `ContextVar`
  guard, re-derived cost model, bumped schema `maxItems` to 16,
  deferred provider plugin, added §4.0 wire-protocol verification
  (since removed in v2 Pass 2), added file manifest, fixed JSON
  Schema, added `judge_model_default` fallback, added
  `enable_web_tools: false`, documented precedence, added
  `timeout_seconds`, made AC specific, marked upstream PR as v0.1.1.

- **2026-06-13 (v2 pivot)** — User clarified: "I don't want to use
  openrouter, I want hermes agent to have this functionality." v1
  made OpenRouter a hard dependency for the only shipped backend.
  v2 makes the tool backend-pluggable: `hermes-native` (default, no
  external dep) and `openrouter-fusion` (opt-in). See
  `docs/recaps/SESSION-RECAP-2026-06-13-PIVOT-TO-HERMES-NATIVE.md`.

- **2026-06-13 (v1 initial draft)** — See archive:
  `archive/2026-06-13-fusion-tool-design-v1-ORwrapper.md`.
