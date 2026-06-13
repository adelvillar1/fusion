# Fusion Tool — Design Plan

**Date:** 2026-06-13
**Status:** Draft, awaiting cross-LLM review
**Author:** Alejandro del Villar (via Hermes)
**Repo:** `adelvillar1/fusion`

---

## 1. Problem statement

The Hermes Agent's built-in `moa` (Mixture-of-Agents) tool runs a panel of
LLMs in parallel and returns a single synthesized answer from an aggregator
model. This is good for "give me the best answer" tasks but bad for
"where do experts disagree" tasks — the synthesis step *hides* the
disagreement instead of surfacing it.

OpenRouter exposes a server-side tool `openrouter:fusion` (beta) that does
what MoA does, plus a structured-analysis pass: a judge model returns
`consensus`, `contradictions`, `partial_coverage`, `unique_insights`, and
`blind_spots` as JSON, and the calling model writes the final response from
that map. The result is auditable and the disagreements are explicit.

**Goal:** expose `openrouter:fusion` to Hermes as a first-class tool the
agent can call, with the same opt-in posture as `moa`.

---

## 2. Scope

### File manifest (v0.1)

| File | Purpose |
|------|---------|
| `tools/fusion_tool.py` | Tool implementation + `registry.register()` |
| `tests/test_fusion_tool.py` | 6 unit tests (schema, recursion guard, defaults, cost guard) |
| `tests/test_fusion_tool_recorded.py` | 4 recorded-fixture tests (success, judge-degraded, all-failed, partial) |
| `fixtures/openrouter-fusion-*.json` | Sanitized recorded responses |
| `scripts/record_fusion.py` | Record-mode harness against live OpenRouter (manual, never in CI) |
| `scripts/sanitize_fusion_fixture.py` | Strip Authorization headers + PII from recorded fixtures |
| `docs/architecture/recursion-guard.md` | How the ContextVar-based guard integrates with `run_agent.py` |
| `docs/architecture/cost-model.md` | Per-model pricing + panel-cost math (corrected in §6) |

### In scope (v0.1)

- A single tool `openrouter_fusion` (toolset key: `fusion_tools`)
- Configuration via `config.yaml` under `fusion.*`
- Default panel of 3 frontier models, default judge = the outer model
- Recursion guard using a `ContextVar` (NOT a process-global env var)
- Recorded-fixture test harness, offline-only CI
- Live verification of the OpenRouter wire protocol **before** implementation begins

### Out of scope (v0.1)

- **Provider plugin (`openrouter/fusion` as a selectable primary model)** —
  deferred to v0.2. Shipping it in v0.1 creates an unguarded cost-explosion
  path (every turn = $1.50+).
- **The `force` parameter and the cost-guard override** — deferred to v0.2.
  v0.1 always uses `tool_choice: "required"` and the cost guard is a hard wall.
- Per-model `reasoning` config beyond `effort` (no `max_tokens` override)
- Caching of fusion responses (left to Hermes's existing response cache)
- UI surfaces (no dashboard component yet)
- Web-search delegation to the panel models (v0.1 explicitly disables web
  tools in the inner call via `fusion.enable_web_tools: false`)
- Judge model selection across providers other than OpenRouter
- Upstream PR to hermes-agent (§8 changes ship as a separate v0.1.1 PR after
  the plugin is battle-tested locally)

---

## 3. Tool schema

Tool name: `openrouter_fusion`. Toolset: `fusion_tools`.

```python
{
    "name": "openrouter_fusion",
    "description": (
        "Run the user prompt through a panel of 1-8 models in parallel and "
        "have a judge model compare their responses, returning structured "
        "analysis (consensus, contradictions, unique insights, blind spots) "
        "plus the raw panel responses. Use for 'where do experts disagree' "
        "or high-stakes multi-perspective tasks."
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
                "minItems": 1,
                "maxItems": 16,
                "description": (
                    "Panel models. Defaults to fusion.analysis_models from "
                    "config.yaml (default: 3 frontier models). All are "
                    "routed through OpenRouter. Hard cap is schema maxItems "
                    "(16); the runtime cost guard is fusion.max_panel_size "
                    "(default 8) and refuses calls exceeding it."
                ),
            },
            "judge_model": {
                "type": "string",
                "description": (
                    "Judge model. Defaults to the outer model (zero extra "
                    "cost). If the outer model is not OpenRouter-routable, "
                    "falls back to fusion.judge_model_default from config."
                ),
            },
            "max_tool_calls": {
                "type": "integer",
                "minimum": 1,
                "maximum": 16,
                "default": 8,
                "description": (
                    "Per-panel-model tool-call limit, passed through to "
                    "OpenRouter's fusion API. NOT a Hermes-side counter."
                ),
            },
            "max_completion_tokens": {
                "type": "integer",
                "description": "Max output tokens per inner call. Provider default if unset.",
            },
            "reasoning_effort": {
                "type": ["string", "null"],
                "enum": ["low", "medium", "high"],
                "description": "Reasoning effort for panel/judge models. Translated by OpenRouter per-provider.",
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
                "description": "Max wall-clock seconds for the inner OpenRouter call. Raises TimeoutError on exceed.",
            },
        },
        "required": ["prompt"],
        "additionalProperties": False,
    },
}
```

---

## 4. Wire protocol

The tool is a thin pass-through to OpenRouter. The inner call structure:

```
POST https://openrouter.ai/api/v1/chat/completions
Headers:
  Authorization: Bearer ${OPENROUTER_API_KEY}
  Content-Type: application/json
  x-openrouter-fusion-depth: 1   # server-side best-effort (UNVERIFIED — see §4.0)

Body:
{
  "model": "<outer_model>",
  "messages": [{"role": "user", "content": "<prompt>"}],
  "tools": [
    {
      "type": "openrouter:fusion",
      "parameters": {
        "analysis_models": [...],   # from config or args
        "model": "<judge_model>",   # from config or args
        "max_tool_calls": 8,
        "max_completion_tokens": ...,  # optional
        "reasoning": {"effort": "high"},  # optional
        "temperature": ...  # optional
      }
    }
  ],
  "tool_choice": "required"   # ALWAYS required in v0.1 — the agent's tool call IS the user's intent
}
```

**HTTP client:** Use Hermes's existing async OpenRouter client
(`tools/openrouter_client.get_async_client`). Extend it minimally if it
cannot pass custom headers (`x-openrouter-fusion-depth`).

**Timeout:** The `timeout_seconds` parameter is enforced via `asyncio.wait_for`
or the underlying HTTP client's timeout. On exceed, raise `TimeoutError` with
a message the outer model can interpret ("fusion call exceeded {N}s").

The outer model invokes the tool; the tool result is a JSON object with the
shape OpenRouter documents. We do **not** parse the analysis — we hand it
back as JSON for the outer model to consume.

### §4.0 — Wire protocol verification (PREREQUISITE before implementation)

The wire shape in this section is **assumed** based on OpenRouter's docs.
Before implementation begins, the implementer MUST:

1. Make one live call to OpenRouter's fusion API using `scripts/record_fusion.py`
2. Validate the request shape matches (tool type, parameter nesting, response shape)
3. Document the date of verification + the OpenRouter API version
4. If the actual shape diverges, update this section and the schema in §3
   before writing any production code

**Do not start implementation until this is done.** A wrong wire shape is the
single most expensive bug to debug post-implementation.

### Recursion guard

**Local guard (primary defense):** A request-scoped
`contextvars.ContextVar[int]` named `_fusion_depth` lives in `run_agent.py`.
The tool dispatcher increments it on entry, clears it in `finally`. The tool
raises `RecursionError` if the value is `>= 1` on entry. Per-call scope means
two independent fusion calls in the same conversation session both succeed.

**Server-side guard (best-effort):** `x-openrouter-fusion-depth: 1` is set on
every outer call. **Whether OpenRouter actually reads this header is
unverified** — the API is in beta. The local guard is the reliable defense;
the header is defense-in-depth.

**Integration point in `run_agent.py`:** the tool dispatcher (whatever
function maps a tool call to its handler) wraps the call in:

```python
token = _fusion_depth.set(_fusion_depth.get() + 1)
try:
    result = handler(**args)
finally:
    _fusion_depth.reset(token)
```

### §4.1 — Partial and total panel failure paths

The plan must enumerate all OpenRouter response shapes, not just success
and judge-degradation. The tool's behavior is specified per path:

| Path | OpenRouter returns | Tool behavior |
|------|-------------------|---------------|
| All panel models succeed, judge succeeds | `status: ok`, `analysis` + `responses` | Pass through verbatim |
| All panel succeed, judge fails | `status: ok`, `responses` only, no `analysis` | Pass through verbatim. Outer model synthesizes. |
| Some panel models fail, some succeed | `status: ok`, `analysis` + partial `responses` + `failed_models` | Pass through verbatim. Surface `failed_models` to the outer model. |
| All panel models fail | `status: error`, `error_reason: all_panels_failed` | Raise `RuntimeError` with `error_reason` surfaced. Outer model can retry. |
| One panel model times out | `status: ok`, partial `responses` + `failed_models` | Same as "some fail." |
| Prompt exceeds a panel model's context | OpenRouter returns the model's error in `failed_models` | Pass through. Outer model sees the failure. |
| Judge produces malformed JSON | `status: error`, `error_reason: unexpected_error` | Raise `RuntimeError`. The judge's malformed output is NOT silently passed through. |
| Rate-limited on one panel model | `status: ok`, partial `responses` + `failed_models` | Same as "some fail." |
| OpenRouter credit exhaustion mid-call | `status: error`, `error_reason: insufficient_credits` | Raise `RuntimeError`. No retry. |
| Second fusion call in same turn (recursion) | OpenRouter may reject with `error_reason: fusion_invocation_capped` | Raise `RuntimeError`. The local ContextVar guard should have caught this first. |

The tool does **not** synthesize, retry, or massage any response. It is a
faithful pass-through. The outer model is responsible for handling partial
data.

### Judge-degradation

If the panel succeeds but the judge fails, OpenRouter returns
`status: "ok"` with `responses` only and **no** `analysis` field. The tool
passes this through unchanged — the outer model is responsible for
synthesizing from `responses` only. We do not synthesize on its behalf.

### Hard failures

`status: "error"` from OpenRouter is raised as a tool error with the
`error_reason` field surfaced verbatim. The outer model sees
`{"error": "...", "reason": "rate_limited"}` and can retry or fall back.

---

## 5. Configuration

```yaml
# config.yaml
fusion:
  # Default panel. Override per-call via the tool's `analysis_models` param.
  analysis_models:
    - "anthropic/claude-opus-latest"
    - "openai/gpt-latest"
    - "google/gemini-pro-latest"
  # Default judge. Defaults to the outer model (no override) when null.
  # If the outer model is not OpenRouter-routable, this fallback is used.
  judge_model: null
  judge_model_default: "anthropic/claude-sonnet-latest"
  max_tool_calls: 8
  # Hard cost guard — schema maxItems is 16; this is the runtime cap.
  # Refuses tool calls whose analysis_models array length exceeds this.
  # In v0.1 there is NO override — the guard is a hard wall.
  max_panel_size: 8
  # Default per-call wall-clock timeout. Can be overridden per-call via the
  # tool's `timeout_seconds` parameter.
  timeout_seconds: 120
  # Web tools in the inner call. v0.1 ships OFF — OpenRouter enables
  # web_search + web_fetch by default for panel models, which is a hidden
  # cost multiplier. Disabling in v0.1; v0.2 may expose as opt-in.
  enable_web_tools: false
```

**Precedence (highest first):**
1. Tool-call arguments (per-call overrides)
2. `config.yaml fusion.*` (per-user defaults)
3. Schema defaults in §3 (last-resort fallbacks)

No new env vars. All behavioral config lives in `config.yaml`. The
`OPENROUTER_API_KEY` env var is the only credential, and it's already
required by the existing OpenRouter provider plugin.

---

## 6. Cost model

> **CALIBRATION NOTE (2026-06-13):** The first draft estimated ~$0.30/call
> at default panel size 3. Cross-LLM review (DeepSeek, Mimo) caught that the
> numbers were 3-5× too low. The table below uses representative 2026
> frontier-class rates ($15/M input, $75/M output for Opus-class; the
> exact rates depend on the panel model chosen). See
> `docs/architecture/cost-model.md` for the per-model rate table.

At default panel size of 3 (Claude Opus-class + GPT-class + Gemini Pro-class),
prompt ~2K tokens, response ~4K tokens:

| Component    | Tokens in+out | $/call (approx) |
|--------------|---------------|-----------------|
| Panel member | 2K + 4K       | $0.30–$0.45     |
| 3 members    | 18K total     | $0.90–$1.35     |
| Judge (outer)| 2K in + ~6K structured-analysis out | $0.45–$0.65 |
| **Total**    |               | **~$1.30–$2.00/call** |

At max panel size of 8 with long-context prompts (50K input, 8K output),
costs can approach **$15–$30/call**. The cost guard (`max_panel_size: 8`)
caps the panel fan-out but does **not** cap the per-model cost — a 50K
input prompt on an Opus-class model is itself $0.75 of input alone.

**Mitigations:**
- v0.1 default is 3 models, 2K input, $1.30–$2.00/call.
- Users who want cheaper calls can configure cheaper panel members
  (`gpt-4.1-mini`, `claude-haiku-latest`, `gemini-flash-latest`).
- The `max_panel_size: 8` cap prevents accidental over-spend from a
  misconfigured `analysis_models` list.
- v0.2 may add a per-call dollar cap (`max_cost_usd: 5.00`) that aborts
  the call before panel fan-out based on input-size × rate estimates.

This is the same cost profile as `moa` and the same reason both tools
are off-by-default. The off-by-default posture is the primary cost defense.

---

## 7. Test strategy

- **Unit tests** (`tests/test_fusion_tool.py`): pure Python, no network.
  Use `unittest.mock` to stub the OpenRouter client. Cover:
  - Schema validation (minItems, maxItems, additionalProperties: false, no `None` in enum)
  - JSON Schema validity via `jsonschema.validate()`
  - Default param resolution (args > config > schema precedence)
  - Recursion guard: `ContextVar` increments on entry, resets in `finally`,
    raises `RecursionError` when `>= 1`. Two consecutive calls in the
    same session both succeed.
  - `tool_choice: "required"` is always set (no `force` parameter)
  - Judge-degradation passthrough (no synthesis)
  - Hard-failure passthrough (error reason surfaced)
  - All-panel-failed → `RuntimeError` with `all_panels_failed` surfaced
  - Partial-panel-failed → `failed_models` surfaced, `analysis` and
    `responses` passed through verbatim
  - Cost guard refusal when `analysis_models` exceeds `max_panel_size`
- **Recorded-fixture tests** (`tests/test_fusion_tool_recorded.py`):
  replay sanitized `fixtures/openrouter-fusion-*.json` through the tool.
  Required fixtures:
  1. `success.json` — full success, both `analysis` and `responses` populated
  2. `judge-degraded.json` — panel succeeds, judge fails, no `analysis`
  3. `all-panel-failed.json` — `status: error`, `error_reason: all_panels_failed`
  4. `partial-panel-failed.json` — 1 of 3 models fails, `failed_models` populated
- **Record-mode script** (`scripts/record_fusion.py`): standalone script
  that hits the real OpenRouter API and writes fixtures. Run manually with
  `OPENROUTER_API_KEY` set; never in CI.
- **Sanitization script** (`scripts/sanitize_fusion_fixture.py`): strips
  `Authorization` headers, PII, and any other sensitive content from
  recorded fixtures before they are committed. Manual step before commit.
- **Cross-model live test** (manual, not in CI): call the tool from a
  Hermes session with `--profile test` and verify the structured analysis
  and the partial-failure path.

No live network calls in CI. Matches the Hermes skill standards
(`AGENTS.md:921`).

---

## 8. Integration points

### v0.1 (in this repo, shipped with the tool)

1. **`run_agent.py` modification** (Hermes core): add
   `from contextvars import ContextVar` and `_fusion_depth: ContextVar[int]
   = ContextVar('fusion_depth', default=0)` at module level. Wrap the tool
   dispatcher call in `set`/`reset` (see §4). This is the only hermes-agent
   core change required for v0.1 to function correctly.

### v0.1.1 (separate PR, after the plugin is battle-tested)

The following are deferred to a separate upstream PR against hermes-agent:

2. **`model_tools.py:224` (new entry next to `moa_tools`):**
   ```python
   "fusion_tools": ["openrouter_fusion"],
   ```
3. **`model_tools.py:_DEFAULT_OFF_TOOLSETS`:**
   add `"fusion_tools"` to the off-by-default set (same gating as `moa`).
4. **`toolsets.py` / `AGENTS.md` toolsets table:**
   add `fusion` to the documented toolset keys.

For local-only use, the upstream changes are not required: the tool
registers through the auto-discovery `registry.register()` call in
`tools/fusion_tool.py` and is invokable as long as the toolset key
`fusion_tools` is in `enabled_toolsets`. The opt-in toggle is
`hermes tools enable fusion_tools`.

### Deferred to v0.2 (provider plugin)

5. **`plugins/model-providers/fusion/` directory** — full `ProviderProfile`
   for `openrouter/fusion` as a selectable primary model. Deferred because
   (a) unguarded cost-explosion path, (b) needs panel-aware model routing,
   (c) needs per-session cost caps, (d) needs a `hermes model` picker
   warning. Its own design plan will follow.

---

## 9. Open questions for review (status after Pass 1)

1. **Should the tool name be `openrouter_fusion` or just `fusion`?**
   **Resolved: `openrouter_fusion`.** Honest about the dependency; v0.2
   can rename or alias if a non-OpenRouter fusion server ships.
2. **Should we expose `web_tools` to the panel?** **Resolved: NO in
   v0.1.** `fusion.enable_web_tools: false` is the default. v0.2 may
   expose as opt-in.
3. **Default panel of 3 vs MoA's 4?** **Resolved: 3.** Matches the
   OpenRouter "Quality" preset. Override via config.
4. **Judge model = outer model by default.** **Resolved: keep this
   default.** With fallback to `judge_model_default` for non-routable
   outer models.
5. **Provider plugin (`plugins/model-providers/fusion/`):** **Resolved:
   DEFER TO v0.2.** Creates an unguarded cost-explosion path. The plugin
   is removed from v0.1 in-scope and v0.1 acceptance criteria.

### New questions surfaced by Pass 1

6. **Use `ContextVar` for the recursion guard?** Yes (see §4). The
   env-var approach is unsound.
7. **Drop the `force` parameter entirely in v0.1?** Yes (see T1.1 in
   the Pass 1 recap). The agent's tool call IS the user's intent.
8. **Live-verify the wire protocol before implementation?** Yes
   (see §4.0). Blocks implementation by 1-2 hours; saves days of
   debugging a wrong wire shape.

---

## 10. Acceptance criteria

A PR that ships v0.1 is "done" when:

- [ ] §4.0 prerequisite satisfied: live wire-protocol call recorded,
      date + OpenRouter API version documented in the plan
- [ ] `openrouter_fusion` tool registers and is gated by `fusion_tools`
      toolset. Verified by `test_fusion_tool.py::test_registers_with_correct_toolset`
- [ ] Schema is valid JSON Schema (verified by `jsonschema.validate` in
      `test_fusion_tool.py::test_schema_validity`)
- [ ] Tool default params resolve in the documented precedence order
      (args > config > schema) — verified by
      `test_fusion_tool.py::test_default_precedence`
- [ ] Recursion guard: `ContextVar` increments on entry, resets in
      `finally`, raises `RecursionError` when `>= 1`. Two consecutive
      calls in the same session both succeed.
- [ ] `tool_choice: "required"` is always sent in the inner call (no
      `force` parameter exists)
- [ ] All 11 unit tests pass; all 4 recorded-fixture tests pass
- [ ] Required fixtures exist and are sanitized:
      `success.json`, `judge-degraded.json`, `all-panel-failed.json`,
      `partial-panel-failed.json`
- [ ] `record_fusion.py` and `sanitize_fusion_fixture.py` exist and
      produce valid output
- [ ] Cost guard refuses `analysis_models` length > `max_panel_size`
      (default 8), schema `maxItems: 16`. The guard can fire.
- [ ] `run_agent.py` is modified to add the `ContextVar` (the only
      hermes-agent core change in v0.1)
- [ ] This plan's §11 CHANGELOG is updated to reflect any design
      changes made during implementation
- [ ] Pass 2 cross-LLM review (buildability lens) finds no Tier 1
      items

### Out of v0.1 scope (deferred)

- [ ] v0.1.1: upstream PR with `model_tools.py` / `toolsets.py` /
      `AGENTS.md` additions (battle-test locally first)
- [ ] v0.2: provider plugin (`plugins/model-providers/fusion/`) with
      per-session cost caps and picker warnings
- [ ] v0.2: `force` parameter and cost-guard override mechanism

---

## 11. Changelog

- **2026-06-13** — Initial draft. Pending cross-LLM review.
- **2026-06-13 (Pass 1 patches)** — Cross-LLM review (3/4 providers:
  DeepSeek, GLM, Mimo; Kimi failed with temperature bug). Applied:
  - **T1.1 + T1.2 + T1.11:** Dropped the `force` parameter entirely.
    `tool_choice: "required"` is always sent. Cost-guard override
    deferred to v0.2.
  - **T1.3:** Replaced env-var recursion guard with `ContextVar`. Added
    `run_agent.py` to integration points (now the only v0.1 hermes-agent
    core change). Marked OpenRouter's `x-openrouter-fusion-depth` header
    as unverified / best-effort.
  - **T1.4:** Re-derived cost model. Default 3-model call is now
    $1.30–$2.00, not $0.30. 8-model long-context can be $15–$30.
  - **T1.5:** Bumped schema `maxItems` to 16 (default `max_panel_size`
    stays 8) so the cost guard can actually fire.
  - **T1.6:** Deferred provider plugin to v0.2 (unguarded cost path).
    Removed from v0.1 in-scope and acceptance criteria.
  - **T1.7:** Added §4.1 "Partial and total panel failure paths" with a
    full enumeration table.
  - **T1.8:** Added §4.0 "Wire protocol verification" as a prerequisite
    step before implementation begins.
  - **T1.9:** Added §2.1 "File manifest" enumerating every file to
    create or modify.
  - **T1.10:** Fixed invalid JSON Schema for `reasoning_effort` (removed
    `None` from enum).
  - **T2.1:** Added `judge_model_default` fallback for non-routable
    outer models.
  - **T2.2:** Added `enable_web_tools: false` config flag (v0.1 ships
    with web tools disabled).
  - **T2.3:** Documented explicit precedence (args > config > schema).
  - **T2.4:** Specified HTTP client choice (Hermes's existing async
    OpenRouter client).
  - **T2.5:** Clarified `max_tool_calls` semantics (OpenRouter-side,
    not Hermes-side).
  - **T2.6:** Added `timeout_seconds` parameter with `TimeoutError`
    semantics.
  - **T2.7:** Made acceptance criteria specific and falsifiable (named
    tests, removed tautologies).
  - **T2.8:** Marked upstream PR (model_tools.py / toolsets.py /
    AGENTS.md) as v0.1.1, out of v0.1 scope.
