# Cross-LLM Review — Pass 1 (Gap-Analysis Lens)

> **Date:** 2026-06-13
> **Artifact:** `docs/plans/2026-06-13-fusion-tool-design.md` (12.5 KB)
> **Brief:** Pattern 4 from `cross-llm-review` skill (gap-analysis shape, 10 focus areas)
> **System prompt:** "Senior backend / agent-platform architect with deep expertise in LLM tool-use protocols, OpenRouter and Anthropic API surface, prompt caching, and cost economics"
> **Providers called:** 4 (DeepSeek-v4-pro, GLM-5.1, Mimo-m2.5-pro, Kimi-k2.6)
> **Providers that completed:** 3/4 (Kimi failed with the documented temperature bug — `HTTP 400: "invalid temperature: only 1 is allowed for this model"`; not retried per the skill's "do not retry Kimi in the same session" rule)
> **Output limit hit:** GLM and DeepSeek at 8192 tokens (capped at limit, not truncated mid-sentence). Mimo at 4940 (briefer style, completed naturally).

## Consensus legend
- 🔴 **3/3 agree** — every model that completed flagged this; high confidence
- 🟠 **2/3 agree** — strong consensus; investigate
- 🟡 **1 model only** — novel insight; may still be valid

---

## Tier 1 — Blockers for delegation (must fix before plan approval)

### 🔴 T1.1: `force` parameter conflates two orthogonal concerns (cost-guard bypass + `tool_choice` override)
**Flagged by:** DeepSeek, GLM, Mimo
**Plan location:** §3 (schema), §5 (config cost-guard comment), §10 (acceptance criteria)
**Issue:** The `force` parameter is described in §3 as "model is told to call this tool even when it judges the task doesn't warrant it" (a `tool_choice` concern), but §5 says the cost guard can be overridden "via the tool's `force` param." A user setting `force=true` for reliability would silently bypass the spending cap. The acceptance criterion "Cost guard refuses … unless overridden" doesn't name the override mechanism.
**Concrete fix:**
- Split into two parameters: `force_tool_choice: bool` (default `false`, maps to `tool_choice: "required"`) and `override_cost_guard: bool` (default `false`, allows `analysis_models` length to exceed `max_panel_size`).
- OR (simpler) remove `force` from v0.1 entirely. `tool_choice: "auto"` is the safe default, and cost-guard override is a v0.2 problem.
- **Recommendation:** simpler path. Defer both `force` and cost-guard override to v0.2. v0.1 always uses `tool_choice: "required"` (the agent's tool call IS the user's intent — see T1.2) and the cost guard is a hard wall.

### 🔴 T1.2: `tool_choice: "auto"` when `force=false` is a silent-degradation bug
**Flagged by:** Mimo
**Plan location:** §4 (wire protocol: `"tool_choice": "required" if force else "auto"`)
**Issue:** The Hermes agent has already decided to call `openrouter_fusion`. With `tool_choice: "auto"`, the OpenRouter-side model can decide *not* to invoke the fusion tool and answer directly. The user asked for multi-model deliberation and gets a single-model answer with no error. This is silent degradation, not a feature.
**Concrete fix:** Always set `tool_choice: "required"` on the inner call. The agent's decision to invoke the tool *is* the user's intent. Remove the `force → tool_choice` mapping entirely. Combined with T1.1's recommendation, this means deleting the `force` parameter and removing the `tool_choice` conditional from §4.

### 🔴 T1.3: Recursion guard env-var design is unsound and unspecified
**Flagged by:** DeepSeek, GLM, Mimo
**Plan location:** §4 (Recursion guard), §8 (Integration points — missing `run_agent.py`)
**Issue:** The plan uses `HERMES_FUSION_DEPTH` as a process-global env var, but:
1. **Never describes reset** — once set, it would block all subsequent independent fusion calls for the rest of the agent process (multi-turn).
2. **Process-global, not request-scoped** — concurrent tool calls or any background task that touches the var will race.
3. **Wiring not enumerated** — §8 lists 3 integration points (model_tools.py, toolsets.py, AGENTS.md), none of which set the var. `run_agent.py` is the natural place but isn't named. An implementer discovers on Day 1 that they need to change the agent loop and thread a value through the tool dispatcher.
4. **Test is meaningless** — acceptance criterion "RecursionError when `HERMES_FUSION_DEPTH >= 1`" tests a mechanism that cannot prevent the actual recursion scenario (a panel model re-invoking fusion at the OpenRouter-server level, where Hermes has no header injection ability).
5. **The OpenRouter depth header is unverified** — the plan claims `x-openrouter-fusion-depth: 1` is "read by OpenRouter, not by us" but cites no source. If it's not real, the server-side guard is a no-op.

**Concrete fix:**
- Replace env-var with **request-scoped `contextvars.ContextVar`** that the tool executor increments/clears.
- Add `run_agent.py` to §8 as a fourth integration point: "Add `_fusion_depth: ContextVar[int] = ContextVar(...)` to `run_agent.py`; tool dispatcher increments on entry, clears in `finally`."
- Add an acceptance criterion: "Two consecutive fusion calls in the same session succeed (the guard is per-call, not per-session)."
- For the OpenRouter header: either **verify it exists** with a live test call before implementation, or **drop the claim entirely** and rely on the local guard alone (the server-side enforcement is best-effort, not the primary mechanism).
- Note: the panel models run server-side inside OpenRouter, so even a verified header doesn't help if a panel model re-invokes fusion — OpenRouter would have to enforce it. The local guard is the *only* reliable defense.

### 🟠 T1.4: Cost estimates in §6 are implausibly low (~3-5× underestimate)
**Flagged by:** DeepSeek, Mimo
**Plan location:** §6 (Cost model)
**Issue:** The plan says Claude Opus-class at 2K input + 4K output = `$0.06/panel member`. At typical Opus-class pricing ($15/M input, $75/M output), that's `$0.03 + $0.30 = $0.33` per member, not `$0.06`. Three members = ~$1.00, not $0.18. Judge with 2K in + 6K structured-analysis out = ~$0.48, not $0.12. Realistic estimate: **~$1.50/call** at default, not $0.30. At panel of 8 with long context, $8-15/call, not $2-3.
**Concrete fix:** Re-derive §6 with explicit per-model rates in a footnote table. Either price from current known rates, or state the assumption ("assumes 5× price reduction from current Opus-class rates by 2026"). Adjust `max_panel_size` default and the cost guard threshold accordingly.

### 🟠 T1.5: Cost guard can never fire — `maxItems: 8` in schema, `max_panel_size: 8` in config
**Flagged by:** GLM
**Plan location:** §3 (Tool schema: `analysis_models.maxItems: 8`), §5 (Configuration: `max_panel_size: 8`)
**Issue:** The schema rejects any `analysis_models` array longer than 8. The cost guard refuses calls with `analysis_models > max_panel_size: 8`. The guard will therefore *never* reject a request. The acceptance criterion "Cost guard refuses … unless overridden" is unsatisfiable as written.
**Concrete fix:** Set schema `maxItems: 16` (or higher than the default `max_panel_size: 8`) so the guard actually kicks in for users who haven't lowered the cap. Or remove the cost guard and rely on the schema's `maxItems: 8` as the hard cap. **Recommendation:** schema `maxItems: 16`, default `max_panel_size: 8`. Users who want to disable the guard can set `max_panel_size: 16` in config. Document the interaction.

### 🟠 T1.6: Provider plugin in v0.1 creates an unguarded cost-explosion path
**Flagged by:** DeepSeek, Mimo
**Plan location:** §2 (In scope: provider-plugin stub), §8 (missing integration point), §9 (open question #5)
**Issue:** Shipping `openrouter/fusion` as a selectable primary model means `hermes model set openrouter/fusion` would route **every** agent turn through a full panel + judge at ~$1.50/turn (per the corrected cost estimate). A 50-turn session = $75 with no warning. The recursion guard cannot prevent this — it only blocks *nested* fusion, not *top-level* fusion on every turn. This directly contradicts the "opt-in, off-by-default" philosophy.
**Concrete fix:** **Move the provider plugin to v0.2.** Remove from §2 in-scope and remove the corresponding §10 acceptance criterion. The provider plugin design (panel-aware model routing, depth-aware request crafting) is non-trivial and needs its own plan. v0.1 is the tool only. If the user later wants `openrouter/fusion` as a primary model, the upstream Hermes-agent side needs (a) a model-level cost counter, (b) a per-session spend cap, and (c) a prominent warning in the picker. None of that is in v0.1 scope.

### 🟠 T1.7: Partial panel failure paths are completely unhandled
**Flagged by:** DeepSeek, Mimo
**Plan location:** §4 (Hard failures, Judge-degradation), §7 (test strategy), §10 (acceptance criteria)
**Issue:** The plan only defines two outcome states: (a) "panel succeeds + judge fails → status: ok with responses only" and (b) "`status: error`" (hard failure). It never describes: (i) all panel members fail, (ii) some panel members fail (partial responses), (iii) panel returns mixed success/failure, (iv) judge produces malformed JSON, (v) prompt exceeds a panel model's context window, (vi) rate-limit on one panel model cascades or doesn't.
**Concrete fix:** Add a §4.1 "Partial and total panel failure" subsection that enumerates each path with the expected OpenRouter response shape and the tool's behavior. Add a recorded fixture and an acceptance criterion for at minimum: all-panel-failed, partial-panel-failed (1 of 3 fails), malformed-judge-JSON.

### 🟠 T1.8: Wire protocol in §4 is unverified against live OpenRouter API
**Flagged by:** DeepSeek, Mimo
**Plan location:** §4 (Wire protocol)
**Issue:** The plan shows the tool handler POSTing `/api/v1/chat/completions` with `tools: [{type: "openrouter:fusion"}]`. This is an *assumption* about how the server tool works. OpenRouter documents that the panel runs server-side, but the wire shape for the outer model's response (does the fusion tool appear as a `tool_calls` block in the outer response? does the panel run inside the outer request? does the tool handler make a second POST?) is not pinned down. If the actual API uses a different mechanism (e.g., a separate endpoint, different parameter names, different tool type string), the entire §4 is wrong. Beta APIs change.
**Concrete fix:** Add a §4 prerequisite step: "Before implementation, make one live call to OpenRouter's fusion API using the `scripts/record_fusion.py` harness. Validate the request/response shape matches §4. Document the date of verification in the plan."

### 🟡 T1.9: Implementation file manifest is missing
**Flagged by:** DeepSeek
**Plan location:** §2 (no file list), §8 (vague "single-line additions")
**Issue:** The plan references `tests/test_fusion_tool.py`, `scripts/record_fusion.py`, `plugins/model-providers/fusion/`, `tools/fusion_tool.py`, and modifications to `model_tools.py`/`toolsets.py`/`AGENTS.md` — but there's no consolidated file manifest. An implementer's first question ("what file do I create?") is partially answered.
**Concrete fix:** Add §2.1 "File manifest" listing every file to create or modify with a one-line description of each.

### 🟡 T1.10: JSON Schema for `reasoning_effort` is invalid
**Flagged by:** DeepSeek
**Plan location:** §3 (Tool schema)
**Issue:** `"type": ["string", "null"], "enum": ["low", "medium", "high", None]` is not valid JSON Schema. JSON Schema has no Python `None`; the null type is `"null"`. The `enum` should not contain `None`. An implementer copying this schema verbatim will get validation errors.
**Concrete fix:** `"type": ["string", "null"], "enum": ["low", "medium", "high"]`. Test the schema with a JSON Schema validator as an acceptance criterion.

### 🟡 T1.11: `force + max_panel_size` interaction is ambiguous in acceptance criteria
**Flagged by:** GLM, DeepSeek
**Plan location:** §10 (acceptance criteria)
**Issue:** "Cost guard refuses `analysis_models` of size > `max_panel_size` unless overridden" doesn't say **what** the override is (a config flag? a tool arg? a CLI flag?). Coupled with T1.1's flag, this acceptance criterion is two issues at once.
**Concrete fix:** Resolved automatically by T1.1's recommendation (defer `force` to v0.2). In v0.1, the cost guard is a hard wall with no override. Update §10 to remove the "unless overridden" clause.

---

## Tier 2 — Significant (fix in this iteration)

### T2.1: `judge_model: null` is undefined for non-OpenRouter outer models
**Flagged by:** Mimo
**Plan location:** §3, §5
**Issue:** If the outer model is a local model (Ollama) or a non-OpenRouter provider, defaulting `judge_model` to the outer model would fail because OpenRouter can't route to that model.
**Concrete fix:** When `judge_model` is null and the outer model is not OpenRouter-routable, fall back to `config.yaml fusion.judge_model_default` (e.g., `anthropic/claude-sonnet-latest`). Document in §3.

### T2.2: `web_tools` passthrough is a hidden cost multiplier
**Flagged by:** Mimo
**Plan location:** §9 (open question #2)
**Issue:** OpenRouter's docs say panel models have `web_search` and `web_fetch` enabled. The plan says "v0.1 passes through, but we don't document it in the tool description." Undocumented network egress that costs money is a bug.
**Concrete fix:** Add a `fusion.enable_web_tools: false` config flag, default off. Document explicitly. v0.1 ships with web tools disabled in the inner call.

### T2.3: Config precedence is ambiguous
**Flagged by:** Mimo
**Plan location:** §5
**Issue:** Schema defaults, config.yaml values, and tool-call args can all supply the same parameter. The plan says defaults come from config but doesn't name the precedence.
**Concrete fix:** Explicitly: "Tool-call args > `config.yaml fusion.*` > schema defaults." Document in §5.

### T2.4: HTTP client choice is unspecified
**Flagged by:** DeepSeek, Mimo
**Plan location:** §4
**Issue:** §4 shows a raw HTTP POST but never names the client. Hermes has `tools/openrouter_client.py` (or similar); MoA's `_run_reference_model_safe` is the reference pattern. An implementer has to discover this on Day 1.
**Concrete fix:** Specify in §4: "Use Hermes's existing OpenRouter client (`tools/openrouter_client.get_async_client`). Extend it minimally if it can't pass custom headers (e.g., `x-openrouter-fusion-depth`)."

### T2.5: `max_tool_calls` semantics are unclear
**Flagged by:** Mimo
**Plan location:** §3, §4
**Issue:** Is this a per-panel-model tool-call limit (passed to OpenRouter), or a local limit on how many times the agent can call `openrouter_fusion` per turn? The plan uses it both ways in different sections.
**Concrete fix:** It's the per-panel-model limit on OpenRouter's side. That's the only sensible interpretation. Clarify in §3 that this is passed through to OpenRouter and is **not** a Hermes-side counter. Verify OpenRouter's API accepts it during the live verification step (T1.8).

### T2.6: No timeout / cancellation semantics
**Flagged by:** Mimo
**Plan location:** §4
**Issue:** A 3-panel + judge call can take 30-120 seconds. The plan doesn't specify HTTP timeout, agent-turn timeout, or what the user sees during the wait.
**Concrete fix:** Add `timeout_seconds: int = 120` to the schema. If the OpenRouter call exceeds it, raise `TimeoutError` with a message the outer model can interpret. Document in §4.

### T2.7: Acceptance criteria are partially tautological / circular
**Flagged by:** DeepSeek
**Plan location:** §10
**Issue:** "All 6 unit tests pass; all 4 recorded-fixture tests pass" is circular — the tests define their own passing. "This plan is updated to reflect any design changes" is a process requirement, not a technical criterion.
**Concrete fix:** Replace each with a specific, falsifiable check (e.g., "Test `test_fusion_tool_registers` asserts `registry.get('openrouter_fusion').toolset == 'fusion_tools'`"). The "all tests pass" line is what CI enforces; drop it from the plan.

### T2.8: Upstream PR to hermes-agent has unclear scope
**Flagged by:** DeepSeek
**Plan location:** §8
**Issue:** Three upstream changes are listed but their scope isn't gated. Are they in v0.1 or v0.1.1? If v0.1, who reviews/merges? If v0.1.1, what ships first?
**Concrete fix:** Explicitly mark §8 changes as **out of scope for v0.1**. v0.1 is the plugin only (this repo). Upstream changes ship as a separate PR after the plugin is battle-tested locally.

---

## Tier 3 — File as follow-up plan

### T3.1: Provider plugin design (deferred from v0.1)
A full `ProviderProfile` for `openrouter/fusion` that supports model-level request crafting, depth-aware headers, and per-session cost caps. Needs its own plan.

### T3.2: Streaming tool results
A 60-second blocking call is a bad UX. Evaluate streaming the panel responses as they arrive in v0.2.

### T3.3: Observability
Structured logging: model names, token counts, latency per panel member, estimated cost. Per-session cost counter.

### T3.4: Fixture sanitization tooling
A `scripts/sanitize_fusion_fixture.py` that strips `Authorization` headers, PII, and identifies by content-type. Manual sanitization is error-prone.

### T3.5: Provider plugin validation tests
Real `ProviderProfile` field tests (not just "imports without error"). Includes the `hermes model` picker integration.

---

## Questions for the human reviewer (5)

1. **Defer the provider plugin to v0.2?** This is the cleanest resolution to T1.6. If you want it in v0.1, the plan needs a per-session cost cap and a model-selection warning. Recommend: defer.
2. **Drop the `force` parameter entirely (T1.1, T1.2)?** Combined recommendation: yes. The agent's tool call IS the user's intent. `tool_choice: "required"` always. Cost-guard override is a config file change, not a tool arg. Recommend: drop.
3. **Live-verify the wire protocol before implementation (T1.8)?** This blocks implementation by 1-2 hours but catches a class of "the API isn't what the plan assumed" bugs that would cost days. Recommend: yes, do it first.
4. **Use `contextvars.ContextVar` for the recursion guard (T1.3)?** Replaces the env-var with a request-scoped counter. Slightly more code in `run_agent.py` but correct under concurrency and multi-turn. Recommend: yes.
5. **Set the schema `maxItems` higher than the default `max_panel_size` (T1.5)?** Currently they're both 8, which makes the cost guard dead code. Recommend: schema `maxItems: 16`, default `max_panel_size: 8`. Users can raise the cap in config.

---

## Per-model summary

| Model | Strongest at | Caught that others missed |
|-------|-------------|---------------------------|
| **DeepSeek-v4-pro** | Comprehensive taxonomy; caught the cost math, recursion-guard wiring, HTTP-client gap, and the "force" conflation in one pass | T1.10 (invalid JSON Schema for `reasoning_effort`), T2.7 (tautological acceptance criteria) |
| **GLM-5.1** | Concrete code-level analysis; flagged the `maxItems`/`max_panel_size` contradiction, the wire-protocol ambiguity, and the missing file manifest | T1.5 (cost guard dead code) — only reviewer to spot that the cost guard literally cannot fire |
| **Mimo-m2.5-pro** | UX/ergonomic + cost angle; flagged the silent-degradation `tool_choice: "auto"` bug, the provider-plugin cost path, the timeout gap, and the web-tools cost multiplier | T1.2 (silent degradation with `tool_choice: "auto"`) — the most user-visible bug in the plan |
| **Kimi-k2.6** | (Failed with the temperature bug — exact same error as the 2026-06-12 review) | — |

---

## Recommended patch order (Tier 1 first)

1. **T1.1 + T1.2 + T1.11** — drop `force`, always set `tool_choice: "required"`, simplify the cost-guard acceptance criterion. ~30 min of plan edits.
2. **T1.3** — replace env-var with `ContextVar`, add `run_agent.py` to §8. ~20 min of plan edits + 1 unit test.
3. **T1.5** — bump schema `maxItems` to 16. Trivial.
4. **T1.4** — re-derive §6 cost table. ~15 min of research.
5. **T1.6** — defer provider plugin to v0.2. Updates §2, §8, §10.
6. **T1.7** — add §4.1 partial-failure enumeration. ~20 min.
7. **T1.8** — live verification step. Blocks implementation by 1-2 hours but catches shape mismatches.
8. **T1.9 + T1.10** — file manifest, JSON Schema fix. Trivial.
9. **T2.1–T2.8** — batch edits to §3, §4, §5, §10.

After patches: run Pass 2 with the **buildability lens** (Pattern 4b). The "do NOT re-flag" list will include everything in T1.1-T1.11.

---

## Raw provider outputs

- `docs/recaps/REVIEW-DEEPSEEK-2026-06-13.md` (8192 tokens, complete)
- `docs/recaps/REVIEW-GLM-2026-06-13.md` (8192 tokens, complete)
- `docs/recaps/REVIEW-MIMO-2026-06-13.md` (4940 tokens, complete — briefer style)
- `docs/recaps/REVIEW-KIMI-2026-06-13.md` (failed; HTTP 400 temperature)
