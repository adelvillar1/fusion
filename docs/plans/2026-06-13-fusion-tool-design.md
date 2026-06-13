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
| `tools/fusion_tool.py` | Tool implementation + `registry.register()` |
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

Tool name: `openrouter_fusion` (kept for v1 compat; renamed to `fusion`
in v0.2). Toolset: `fusion_tools`.

```python
{
    "name": "openrouter_fusion",
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

```python
# tools/fusion/runner.py
class FusionRunner:
    def __init__(self, backend: FusionBackend, judge_model: str, config: FusionConfig):
        self.backend = backend
        self.judge_model = judge_model
        self.config = config

    async def run(self, prompt: str, panel_models: list[str], **kwargs) -> PanelResponse:
        # 1. Recursion guard (ContextVar) — see §4.4
        # 2. Cost guard — refuse if len(panel_models) > max_panel_size
        # 3. Backend.run_panel(...) — backend does the parallel fan-out
        # 4. If backend didn't produce analysis, run the judge separately
        #    (hermes-native does this; openrouter-fusion does it server-side)
        # 5. Return the structured response
```

The runner is the same regardless of backend. The backend decides how
to fan out (local asyncio.gather vs. server-side OpenRouter call) and
whether the judge runs inside the backend (OpenRouter) or is invoked
separately by the runner (hermes-native).

### 4.3 The hermes-native backend

```python
# tools/fusion/backends/hermes_native.py
class HermesNativeBackend(FusionBackend):
    name = "hermes-native"

    def check_requirements(self) -> bool:
        return True   # no external deps; uses existing model slots

    async def run_panel(self, request: PanelRequest, *, outer_model, judge_model) -> PanelResponse:
        # Fan out via asyncio.gather over the user's existing model providers.
        # Each panel member gets the prompt + outer model context; we call
        # the provider directly using Hermes's existing client infrastructure
        # (see auxiliary_client.py). The judge runs as one of the panel
        # members — either the explicit judge_model or a designated slot.
        # No new model-routing logic; this reuses model.fallback_providers.
```

The hermes-native backend uses the **same model clients Hermes already
uses** (`auxiliary_client.py`, the per-provider async clients in
`plugins/model-providers/*/`, the `model.fallback_providers` chain).
This means:

- If the user has Anthropic + DeepSeek + Kimi keys, the panel can be
  Claude + DeepSeek + Kimi without any new credentials.
- If a model in the panel fails, the `fallback_providers` chain activates
  per-panel-member (existing Hermes behavior).
- The user pays their existing provider rates, not OpenRouter's
  aggregator markup.
- The judge can be the `auxiliary.curator` slot (typically a strong
  reasoner like Kimi K2.6) or the outer model.

### 4.4 Recursion guard (ContextVar)

Same as v1 §4. A request-scoped `contextvars.ContextVar[int]` named
`_fusion_depth` lives in `run_agent.py`. The runner increments on
entry, resets in `finally`. Raises `RecursionError` if `>= 1`.

Per-call scope: two independent fusion calls in the same conversation
session both succeed.

### 4.5 The judge layer (shared between backends)

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
  # Default: pull 2-3 models from model.fallback_providers if unset.
  analysis_models: []   # empty = auto-populate from fallback chain

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
  - `asyncio.gather` over panel members
  - Per-panel-member fallback chain activation
  - Judge invocation via `auxiliary.curator` slot
  - Timeout enforcement via `asyncio.wait_for`
- **Recorded-fixture tests** (`tests/test_fusion_tool_recorded.py`):
  replay sanitized `tests/fixtures/fusion-*.json` through the runner.
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

1. **`run_agent.py` modification** (Hermes core): add
   `from contextvars import ContextVar` and
   `_fusion_depth: ContextVar[int] = ContextVar('fusion_depth', default=0)`
   at module level. Wrap the tool dispatcher call in `set`/`reset`.
   This is the **only hermes-agent core change required for v0.1**.

2. **`auxiliary_client.py` extension** (Hermes core): expose a
   `panel_call()` helper that takes a list of model identifiers and
   fans out via `asyncio.gather`. The hermes-native backend uses this
   helper. (May not be a true core change — could be a new module
   under `tools/fusion/`. The exact location is decided during
   implementation.)

### v0.1.1 (separate PR, after the plugin is battle-tested)

3. **`model_tools.py:224`** — add `"fusion_tools": ["openrouter_fusion"]`
4. **`model_tools.py:_DEFAULT_OFF_TOOLSETS`** — add `"fusion_tools"`
5. **`toolsets.py` / `AGENTS.md`** — add `fusion` to the documented
   toolset keys

### Deferred to v0.2 (provider plugin)

6. **`plugins/model-providers/fusion/`** — full `ProviderProfile` for
   `openrouter/fusion` as a selectable primary model. Deferred because
   (a) unguarded cost-explosion path, (b) needs panel-aware model
   routing, (c) needs per-session cost caps.

---

## 9. Open questions for review

1. **Should the v0.1 tool name be `openrouter_fusion` or just `fusion`?**
   v1 used `openrouter_fusion` to be honest about the dependency.
   v0.1's default backend is hermes-native — the `openrouter_` prefix
   is misleading. **Recommendation: rename to `fusion` in v0.1.** This
   is the v2 plan. Both v1 history and v0.2 cleanliness argue for it.
   *Punted to §9 T1 below — implementation will pick.*
2. **Should the judge be hermes-native's curator slot, or always an
   explicit model?** `auxiliary-curator` is the right default for
   hermes-native (free, configurable, typically a strong reasoner).
   But if the user hasn't configured the curator slot, fall back to
   the outer model. *T2 below.*
3. **How should hermes-native handle the `model.fallback_providers`
   chain — apply it per panel member, or run the chain sequentially?**
   Per-panel-member fallback (i.e., if Claude fails for panel member 1,
   fall back to DeepSeek for that member) is the cleanest answer. It
   means the panel is "3 model attempts" not "3 specific models or
   nothing." *T3 below.*
4. **Should the structured-analysis prompt be configurable?**
   Yes — different use cases (legal review vs. code review vs. creative
   brainstorming) want different analysis lenses. v0.1 ships a default
   prompt + a config override. *T4 below.*
5. **Web tools in panel members — both backends?** OpenRouter enables
   them by default; hermes-native's panel members are regular model
   calls that *could* have web tools enabled. v0.1 explicitly disabled
   in both. v0.2 may expose as opt-in. *T5 below.*

### New questions for Pass 2 (buildability lens)

6. **Is the backend-ABC contract the right granularity?** The current
   contract is `run_panel(request) -> PanelResponse`. Should the ABC
   also expose `resolve_judge_model(strategy) -> str` so each backend
   can implement its own judge resolution? Or should the runner do all
   judge resolution and the backend just do panel fan-out?
7. **Should the hermes-native backend use the existing `auxiliary_client`
   or a new client?** `auxiliary_client.py` is the canonical path for
   "call a single model with the right plumbing." Reusing it is the
   right call. But it doesn't expose `asyncio.gather` semantics — we
   may need to extend it.
8. **The `auxiliary.curator` slot — what if the user has it set to a
   model that's not in their fallback chain?** E.g., curator is Kimi
   K2.6 but the fallback chain is Anthropic-only. The judge call would
   need a Kimi key. Resolve by: (a) require the user to have the
   curator's provider keys set, (b) fall back to the outer model, or
   (c) skip the structured-analysis step and return raw responses.
9. **What about hermes-native's behavior when the user's
   `model.fallback_providers` is empty?** The default panel would be
   empty, the tool would refuse. Resolve by: (a) refuse with a clear
   error message, (b) fall back to the primary model alone (panel of
   1, the judge has nothing to compare).
10. **Backwards compatibility with v1's `openrouter_fusion` tool name.**
    If we rename to `fusion` in v0.1, the v1 name disappears. Anyone
    who has been calling `openrouter_fusion` in scripts breaks. Resolve
    by: (a) ship both names with the v1 name as a deprecation shim, (b)
    ship only `fusion` and accept the break.

---

## 10. Acceptance criteria

A PR that ships v0.1 is "done" when:

- [ ] `openrouter_fusion` (or `fusion` — see §9 T1) tool registers and
      is gated by `fusion_tools` toolset. Verified by
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
- [ ] Recursion guard: `ContextVar` increments on entry, resets in
      `finally`, raises `RecursionError` when `>= 1`. Two consecutive
      calls in the same session both succeed.
- [ ] Cost guard refuses `analysis_models` length > `max_panel_size`
      (default 8), schema `maxItems: 16`
- [ ] Judge strategy resolution: `outer-model` (default), `auxiliary-curator`,
      `explicit-model` (requires `judge_model` arg)
- [ ] `StructuredAnalysis` Pydantic model is shared between backends
- [ ] All 11 unit tests pass; all 4 recorded-fixture tests pass
- [ ] All 4 runner orchestration tests pass
- [ ] All hermes-native backend tests pass with mocked `auxiliary_client`
- [ ] Required fixtures exist and are sanitized
- [ ] `record_fusion.py` and `sanitize_fusion_fixture.py` exist
- [ ] `run_agent.py` is modified to add the `ContextVar`
- [ ] This plan's §11 CHANGELOG is updated to reflect any design
      changes made during implementation
- [ ] Pass 2 cross-LLM review (buildability lens) finds no Tier 1 items

### Out of v0.1 scope (deferred)

- [ ] v0.1.1: upstream PR with `model_tools.py` / `toolsets.py` /
      `AGENTS.md` additions
- [ ] v0.2: provider plugin (`plugins/model-providers/fusion/`)
- [ ] v0.2: `force` parameter and cost-guard override
- [ ] v0.2: rename tool from `openrouter_fusion` to `fusion`
      (or keep both as a compat shim)
- [ ] v0.2: Anthropic batch API backend
- [ ] v0.2: streaming tool results
- [ ] v0.2: per-call dollar cap (`max_cost_usd`)

---

## 11. Changelog

- **2026-06-13 (v2)** — Major pivot from v1. The tool is now
  backend-pluggable; `hermes-native` (using existing model slots) is
  the v0.1 default. OpenRouter's `openrouter:fusion` is an opt-in
  alternate backend. The tool no longer requires OpenRouter. The
  v1 plan is archived at
  `archive/2026-06-13-fusion-tool-design-v1-ORwrapper.md`.

- **2026-06-13 (v1 Pass 1 patches)** — Cross-LLM review applied 11
  Tier 1 + 8 Tier 2 fixes to the v1 plan. **Most of those fixes
  carry over to v2** because they were about correctness, not
  OpenRouter-specificity:
  - `force` parameter dropped → carried over
  - `ContextVar` recursion guard → carried over
  - Cost guard with `max_panel_size` + `maxItems: 16` → carried over
  - File manifest in §2 → carried over, expanded
  - `judge_model_default` fallback → carried over
  - `enable_web_tools: false` → carried over to openrouter-fusion
    backend config
  - Documented precedence → carried over
  - `timeout_seconds` parameter → carried over
  - Specific, falsifiable acceptance criteria → carried over
  - §4.1 partial-failure-paths table → generalized in v2 §4.6
  - Invalid JSON Schema fix → carried over
  - `run_agent.py` integration → carried over
  - Provider plugin deferred → carried over
  - Upstream PR deferred to v0.1.1 → carried over
  - **Removed from v2:** the §4.0 "wire protocol verification"
    prerequisite. The hermes-native backend uses Hermes's existing
    clients — no wire protocol to verify. The openrouter-fusion
    backend *does* need wire-protocol verification, but that's a
    single backend's concern, not the tool's. Moved to a backend
    implementation note.

- **2026-06-13 (v1 initial draft)** — See archive.
