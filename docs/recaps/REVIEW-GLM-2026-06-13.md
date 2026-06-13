# Cross-LLM Review — Pass 1 (Gap-Analysis Lens)

**Provider:** GLM-5.1
**Model:** glm-5.1
**Latency:** 85888ms
**Tokens in/out:** 3874/8192
**Error:** none

---

# Architecture Review: Fusion Tool Design Plan

---

## TIER 1 — Blockers for delegation

### T1-1. Wire protocol is speculative and likely incorrect

**WHERE:** §4 (Wire protocol)  
**WHY:** The plan presents `x-openrouter-fusion-depth` as a header "read by OpenRouter," but provides no documentation link, no API reference, and no evidence this header exists in OpenRouter's actual API surface. If this header isn't real, the entire server-side recursion guard is fictional. Similarly, the POST body structure — putting `openrouter:fusion` in a `tools` array with `tool_choice: "required"` — implies the tool implementation makes a **separate chat-completions call** to a model that is then forced to invoke the fusion tool. This adds a redundant model round-trip (the "outer model" in the POST) whose only job is to call a tool it was forced to call. If OpenRouter exposes a direct fusion endpoint (not through chat completions), the wire protocol is wrong. If it doesn't, the architecture is wasteful and the `force`→`tool_choice` mapping is semantically confused.  
**CONCRETE FIX:** Before writing any code, produce a working `curl` or `httpx` call against the live OpenRouter API that invokes `openrouter:fusion` and returns a structured result. Document the actual request/response shape. Rewrite §4 from that ground truth. Delete `x-openrouter-fusion-depth` unless OpenRouter docs confirm it.

### T1-2. Recursion guard is incoherent

**WHERE:** §4 (Recursion guard), §7 (Unit tests)  
**WHY:** The plan specifies two independent recursion guards — a header and an env var — but neither is viable as described:

- **Env var `HERMES_FUSION_DEPTH`:** The plan says it's "set by `run_agent.py` when entering a panel." But the panel runs on OpenRouter's servers, not inside the Hermes process. The panel models don't execute the `openrouter_fusion` tool — they're LLMs generating text. The only entity that could recursively call `openrouter_fusion` is the Hermes agent itself, after receiving the fusion result. That's not recursion; that's a sequential call. The env var approach also has process-global scope — if two agents run in the same process, they'd interfere.
- **Header `x-openrouter-fusion-depth`:** Unverified (see T1-1). Even if real, the plan says "We also gate locally" with the env var, but never specifies where the local gate is checked. The acceptance criterion says "raises `RecursionError` when `HERMES_FUSION_DEPTH >= 1`" but never says who sets this variable or when it's cleared.

**CONCRETE FIX:** Replace the env-var guard with a per-request context variable (`contextvars.ContextVar[int]`) that the tool implementation increments before the OpenRouter call and decrements after. Check it at tool entry. Remove the header claim until OpenRouter docs confirm it. Add a specific acceptance criterion: "Calling `openrouter_fusion` from within a tool-result callback where fusion depth is already 1 raises `RecursionError`." Specify the lifecycle: set at tool entry, cleared at tool exit, scoped to the current agent turn.

### T1-3. Cost model is off by ~5× for the default panel, undermining the cost guard

**WHERE:** §6 (Cost model)  
**WHY:** The plan claims ~$0.06/panel-member for "Claude Opus 4.6 + GPT-5.4 Pro + Gemini 2.5 Pro" at 2K in + 4K out. At current frontier pricing trajectories ($15–30/M input, $60–150/M output), a single Opus-class member costs $0.30–0.60. Three members → $0.90–1.80, not $0.18. The total per-call would be $1.50–2.30, not $0.30. The max-panel estimate of "$2–3" is accidentally plausible only because the per-member estimate is wrong in the opposite direction at scale. The cost guard threshold (`max_panel_size: 8`) was presumably calibrated against the $0.30 baseline; at real pricing, an 8-model panel could hit $10–15/call.  
**CONCRETE FIX:** Recalculate §6 with explicit per-model pricing from OpenRouter's live pricing page. Add a `max_cost_usd` config field (not just `max_panel_size`) so the guard is denominated in dollars, not model count. A 3-model panel of Sonnet-class models and a 3-model panel of Opus-class models have radically different costs; count alone is the wrong metric.

### T1-4. `force` parameter semantics are confused and potentially dangerous

**WHERE:** §3 (Tool schema, `force` param), §4 (Wire protocol)  
**WHY:** The plan says `force` maps to `tool_choice: "required"` on the OpenRouter call. But if the wire protocol is a chat-completions call where the model is forced to call the fusion tool, then `force` is always effectively true — the tool implementation is already making a call specifically to invoke fusion. The only scenario where `force=false` (i.e., `tool_choice: "auto"`) makes sense is if the "outer model" in the POST might decide *not* to call fusion, in which case the tool returns... nothing? An error? The plan doesn't specify. Additionally, `force` is described as overriding the cost guard ("refuse tool calls with analysis_models > this size unless the user explicitly opts in via the tool's `force` param"), which conflates two unrelated concerns: forcing tool invocation vs. acknowledging cost risk.  
**CONCRETE FIX:** Split `force` into two parameters: (a) remove `tool_choice` mapping entirely — if the agent calls this tool, it wants fusion; (b) add `acknowledge_cost: bool` that's required when `len(analysis_models) > max_panel_size`. Remove `force` from the schema. Document that `tool_choice` is always `"required"` on the inner call because the call exists solely to invoke fusion.

### T1-5. Provider plugin contradicts the "off by default" philosophy and has no cost guard

**WHERE:** §2 (Out of scope), §5 (Configuration), §8 (Integration points), §9 (Open question 5)  
**WHY:** The plan states fusion is "off by default" and "opt-in" (§2, §8). But §8 item 3 and §9 item 5 propose shipping a provider plugin that exposes `openrouter/fusion` as a selectable primary model via `hermes model`. If a user selects this as their primary model, **every single prompt** goes through a 3+ model panel, multiplying cost by 3–8× with no guard, no warning, and no per-turn opt-in. The acceptance criterion for the plugin is "exist and parse without import errors" — a stub that passes import checks but is one `hermes model select` away from a $50/hour habit.  
**CONCRETE FIX:** Remove the provider plugin from v0.1 scope entirely. Move it to v0.2 with its own design doc that includes cost guards, a confirmation prompt on selection, and a per-turn budget cap. The acceptance criterion for v0.1 should have zero mention of `plugins/model-providers/fusion/`.

---

## TIER 2 — Significant, fix in this iteration

### T2-1. Missing error/failure states — half the state space is unspecified

**WHERE:** §4 (Wire protocol), §7 (Test strategy)  
**WHY:** The plan specifies two outcomes: success and `status: "error"`. It mentions judge-degradation (panel succeeds, judge fails). It does **not** specify:
- All panel members fail (what does OpenRouter return? what does the tool return?)
- Some panel members fail (partial success — does the judge still run on 1 of 3 responses?)
- A panel model is unavailable/deprecated on OpenRouter
- A panel model's context window is exceeded by the prompt
- Rate limit on one panel model but not others
- Network timeout during the (potentially long-running) fusion call
- OpenRouter returns a response shape that doesn't match expectations (API version drift)

**CONCRETE FIX:** Add a §4.1 "Error and Degradation Matrix" that enumerates: all-panel-fail, partial-panel-fail, judge-fail, timeout, rate-limit, schema-mismatch. For each, specify what the tool returns to the outer model. Add unit tests for each to §7.

### T2-2. Acceptance criteria are structural, not behavioral — a subagent can't verify correctness

**WHERE:** §10 (Acceptance criteria)  
**WHY:** Every criterion is about file existence, config resolution, or error raising. None verify that the tool actually returns correct fusion results. "All 6 unit tests pass" is meaningless if the tests are mock-heavy and don't assert on the actual response shape. "Produces a valid fixture" — what makes it valid? "Plugin files exist and parse" — empty files satisfy this.  
**CONCRETE FIX:** Replace with behavioral criteria:
- "Given a recorded fixture with `status: "ok"` and all 5 analysis fields present, the tool returns a JSON string containing `consensus`, `contradictions`, `partial_coverage`, `unique_insights`, and `blind_spots` keys."
- "Given a recorded fixture with `status: "ok"` and no `analysis` field (judge degradation), the tool returns a JSON string containing `responses` but no `analysis` key."
- "Given a recorded fixture with `status: "error"`, the tool raises a `ToolError` with the `error_reason` field in the message."
- "Given `analysis_models` with 9 entries and `max_panel_size: 8`, the tool raises `ValueError`."
- "Given `HERMES_FUSION_DEPTH=1`, the tool raises `RecursionError`."

### T2-3. Judge model = panel model is unhandled

**WHERE:** §3 (Tool schema), §5 (Configuration)  
**WHY:** If `judge_model` defaults to the outer model, and the outer model is also in `analysis_models`, the judge is evaluating its own response. This is a known bias vector in MoA literature. The plan doesn't address deduplication, warning, or rejection of this configuration.  
**CONCRETE FIX:** Add logic: if `judge_model` is in `analysis_models`, either (a) remove it from `analysis_models` with a warning, or (b) raise a `ValueError` requiring explicit opt-in. Document this in §5. Add a unit test.

### T2-4. No specification for how the tool result is encoded

**WHERE:** §4 ("We do not parse the analysis — we hand it back as JSON for the outer model to consume")  
**WHY:** Tool results in the OpenAI-compatible API are strings. The plan says the tool returns "a JSON object" but doesn't specify: is it `json.dumps(response)` as a single string? Is it split into multiple content blocks? Does it include only the analysis, or the full OpenRouter response including `responses`? The outer model's ability to use the result depends entirely on this encoding.  
**CONCRETE FIX:** Specify: "The tool returns a single string containing `json.dumps(full_response)`, where `full_response` is the OpenRouter response body. The outer model receives this as a tool-result message and must parse it."

### T2-5. `reasoning_effort` and `temperature` are applied uniformly to heterogeneous models

**WHERE:** §3 (Tool schema)  
**WHY:** `reasoning_effort