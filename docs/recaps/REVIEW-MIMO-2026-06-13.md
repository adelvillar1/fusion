# Cross-LLM Review — Pass 1 (Gap-Analysis Lens)

**Provider:** Mimo-m2.5-pro
**Model:** mimo-v2.5-pro
**Latency:** 99128ms
**Tokens in/out:** 3905/4940
**Error:** none

---

# Fusion Tool Design Plan — Architect Review

---

## TIER 1: Blockers (must fix before delegation)

### 1. Wire-protocol header `x-openrouter-fusion-depth` is almost certainly fabricated

**WHERE:** §4 (Wire protocol), §4 (Recursion guard)

**WHAT:** The plan sets `x-openrouter-fusion-depth: 1` as a custom HTTP header and claims "read by OpenRouter, not by us." There is no publicly documented `x-openrouter-fusion-depth` header in any OpenRouter API documentation I can locate. The plan treats this as a server-side recursion guard when it's actually just a made-up header that OpenRouter will silently ignore. The entire "server-side recursion guard" half of the defense is theater.

**WHY:** If this header doesn't exist, a panel member that calls `openrouter:fusion` again will **not** be rejected by OpenRouter — it will recurse server-side until OpenRouter's own nesting limits kick in (or you burn through your rate limit). The plan author appears to have confused a design proposal with an existing feature.

**CONCRETE FIX:** Remove the `x-openrouter-fusion-depth` header claim. Implement recursion guarding **entirely** on the Hermes side: (a) `HERMES_FUSION_DEPTH` env var set by the tool entrypoint, (b) checked in the tool entrypoint before making the HTTP call, (c) cleared (or decremented) on exit. Add a note that server-side recursion protection is an OpenRouter feature request, not a current capability. If OpenRouter *does* have a beta recursion header, cite the specific doc URL and require the implementer to verify it before merging.

---

### 2. `HERMES_FUSION_DEPTH` env var has no wiring — no code ever sets or reads it

**WHERE:** §4 (Recursion guard), §7 (Test strategy mentions it), §10 (Acceptance criteria)

**WHAT:** The plan says "the tool raises `RecursionError` when `HERMES_FUSION_DEPTH >= 1`" and that "`run_agent.py` sets it when entering a panel." But:
- `run_agent.py` is never listed as a modified file.
- No code snippet shows where the env var is set.
- No code snippet shows where the env var is read.
- Env vars set via `os.environ` within a tool function are process-global and **do** survive across calls in the same process — but only if the tool actually sets them. If the tool spawns subprocesses (common in agent frameworks), the env var is inherited. If the tool uses async tasks in the same process, it works but is a fragile global-state pattern.
- An env var is the wrong primitive for this. A thread-local or context-var is correct for async code.

**WHY:** A subagent following this plan literally will not know where to set the var, where to check it, or what primitive to use. The recursion guard acceptance criterion is unverifiable because the mechanism is unspecified.

**CONCRETE FIX:** Replace the env var with a `contextvars.ContextVar[int]` named `fusion_depth`. Specify exactly two code sites:
1. **`tools/fusion_tool.py:execute()`** — at the top: read `fusion_depth.get()`, if ≥ 1 raise `RecursionError`; set it to current + 1 via `fusion_depth.set()`, and in a `finally` block, decrement it.
2. **No change to `run_agent.py` needed** — the ContextVar is self-managing.
Remove all references to `HERMES_FUSION_DEPTH` from the plan and acceptance criteria. Replace with "ContextVar `fusion_depth` is checked and incremented in the tool entrypoint."

---

### 3. Acceptance criteria are not independently verifiable — too many are smoke-level

**WHERE:** §10

**WHAT:** Specific issues:

| Criterion | Problem |
|---|---|
| "Tool default params resolve from config.yaml fusion.*" | Which params? All 7? What does "resolve" mean — fall back? override? The implementer will write one test for one param and check the box. |
| "Recursion guard raises RecursionError when HERMES_FUSION_DEPTH ≥ 1" | See Tier-1 #2. The mechanism doesn't exist yet. |
| "All 6 unit tests pass; all 4 recorded-fixture tests pass" | The exact test count is an implementation detail that will diverge from the plan on day 1. Tie the criterion to **behaviors**, not test counts. |
| "record_fusion.py produces a valid fixture for at least one panel size, judge configuration, and reasoning effort" | "Valid fixture" is undefined. What schema? What assertion? |
| "Cost guard refuses analysis_models of size > max_panel_size unless overridden" | "Unless overridden" — overridden how? Via `force: true`? The plan says `force` maps to `tool_choice: "required"`, not to cost-guard bypass. This is a conflation of two independent flags. |
| "This plan is updated to reflect any design changes" | Not a software criterion. A process criterion that no automated check can verify. |

**WHY:** A subagent (or junior engineer) cannot walk up to this list and tick boxes unambiguously. Half the criteria require interpretation, which means half the "done" checkboxes will be rubber-stamped.

**CONCRETE FIX:** Rewrite each criterion as a deterministic assertion pattern. Example rewrite:
- "For any call where `analysis_models` is omitted and `config.yaml` has `fusion.analysis_models: [a, b, c]`, the HTTP body sent to OpenRouter contains exactly `["a", "b", "c"]` as the `analysis_models` field. A unit test asserts this with a mocked HTTP client."
- "For any call where `len(analysis_models) > config.fusion.max_panel_size` and `force` is `False`, the tool raises `CostGuardError` before making any HTTP call. Verified by unit test."
- Remove the test-count criteria entirely.

---

### 4. The `force` param conflates two unrelated semantics

**WHERE:** §3 (Tool schema — `force` description), §4 ("tool_choice: 'required' if force"), §5 ("unless the user explicitly opts in via the tool's force param"), §10 (cost guard "unless overridden")

**WHAT:** `force` is defined in §3 as mapping to `tool_choice: "required"` (meaning: make the outer model call this tool even if it doesn't want to). But §5 and §10 imply `force` also bypasses the cost guard. These are completely orthogonal concerns:
- "Make the model call the tool" = prompt-level instruction.
- "Allow expensive panel sizes" = safety override.

If `force` means both, a user who wants to override the cost guard also forces the model to call the tool (and vice versa). This is a design bug.

**WHY:** An implementer following this literally will wire `force` to both behaviors, creating a confusing UX. Users will accidentally force tool invocation when they just wanted a bigger panel, or vice versa.

**CONCRETE FIX:** Split into two parameters:
- `force: bool` — maps only to `tool_choice: "required"` (keep as-is for the tool_choice concern).
- `override_cost_guard: bool` (default `False`) — bypasses `max_panel_size` check.
Update all references in §5, §10, and the test matrix accordingly.

---

### 5. No handling of "all panel models failed" or "partial panel success"

**WHERE:** §4 (Hard failures), §3 (Tool description)

**WHAT:** The plan handles two states:
- `status: "ok"` with `analysis` → full success
- `status: "ok"` without `analysis` → judge degraded
- `status: "error"` → total failure

But what about:
- **1 of 3 panel members succeeds** — is there still an `analysis`? OpenRouter's behavior here is undocumented in this plan.
- **All panel members fail but judge still runs** — what does OpenRouter return?
- **Panel succeeds but returns 0 tokens** (empty response from a model that hit content filter) — is that a "success"?
- **Partial panel with contradictions** — does the judge see the failures as a contradiction or just ignore them?

**WHY:** The implementer will hit partial-success in real usage within the first hour. The plan provides no guidance, so they'll either (a) guess, (b) block on asking the author, or (c) ship something that silently discards partial data.

**CONCRETE FIX:** Add a §4.3 "Partial panel success" subsection. State the expected OpenRouter behavior for 0/N, 1/N, and (N-1)/N panel successes. If the behavior is unknown (likely), add it as an explicit "unknown — implementer must test and document" acceptance criterion with a fixture for each case.

---

## TIER 2: Significant (fix in this iteration)

### 6. Cost estimates in §6 are fabricated to the penny and the model pricing is wrong

**WHERE:** §6

**WHAT:** The table claims "Claude Opus 4.6 + GPT-5.4 Pro + Gemini 2.5 Pro" at "$0.06 per panel member" with "2K+4K" tokens. Issues:
- **Model names don't exist yet (it's 2025).** "Claude Opus 4.6" and "GPT-5.4 Pro" are speculative. The cost table is fiction dressed as a budget.
- **Even with current models:** Claude Opus 4 at $15/$75 per 1M tokens, 6K tokens = ~$0.45, not $0.06. GPT-4o at $2.50/$10 per 1M, 6K tokens = ~$0.07. These don't match "$0.06" uniformly.
- **"$2-3/call at panel of 8"** — even with cheap models, 8 × 6K = 48K tokens. At current frontier pricing ($15-75/1M out), that's $0.60-$3.60. The range is roughly right but the per-member number is wrong.
- The judge cost of "$0.12" for "2K in + ~6K structured-analysis out" is implausible. Structured analysis JSON with consensus, contradictions, insights, and blind spots for 3-8 model outputs will be far more than 6K tokens of input to the judge (it needs to read all panel outputs) and far more than 6K output.

**WHY:** Wrong cost numbers lead to wrong risk assessments. If someone sets `max_panel_size: 8` thinking it's "$2-3/call" but it's actually "$8-15/call", the cost guard is miscalibrated.

**CONCRETE FIX:** Replace the cost table with a **formula** and a **range**, not point estimates:
```
Cost ≈ Σ(panel_member_i cost for input_tokens + output_tokens) + judge_cost(judge_input_tokens + judge_output_tokens)
```
Add: "Judge input tokens ≈ sum of all panel output tokens + prompt tokens. Judge output tokens are unpredictable; estimate 2K-10K. Implementer must instrument actual costs in the first week and update this section."
Remove the fake model names. Reference actual current models as "example" and note that pricing changes quarterly.

---

### 7. Provider plugin (`plugins/model-providers/fusion/`) should be deferred to v0.2

**WHERE:** §2 (In scope), §9 Q5 (open question, but leans "ship the stub"), §10 (acceptance criterion)

**WHAT:** The plan ships a provider plugin that exposes `openrouter/fusion` as a selectable primary model in `hermes model`. This directly contradicts the plan's own philosophy:
- §1: "expose as a first-class tool the agent can call, with the same opt-in posture as `moa`"
- §8: "off-by-default"
- §10: "is gated by `fusion_tools` toolset"

But the provider plugin makes it a **primary model**, not a tool. A user who runs `hermes model openrouter/fusion` would route **every single message** through a 3-model panel + judge. At $0.30+/call, a 50-message conversation costs $15+. The "opt-in" philosophy is violated.

Additionally, a "stub" provider plugin that doesn't actually work as a real provider (no streaming, no proper token counting, no proper tool-call forwarding through the panel) will cause confusing failures if anyone tries to use it.

**WHY:** Shipping a broken or dangerous stub in v0.1 creates support burden and violates the stated opt-in principle. It's not in scope for the core use case (tool invocation).

**CONCRETE FIX:** Move the provider plugin to **v0.2 Out of scope** list. Remove it from §10 acceptance criteria. Add a §9 open question: "Should fusion be usable as a primary model (provider plugin) or only as a tool? The cost implications of primary-model routing are severe."

---

### 8. No response sanitization for fixtures — PII/credential leak risk

**WHERE:** §7 (Test strategy — "Fixtures are sanitized: no API keys, no real model outputs that contain PII")

**WHAT:** The plan asserts fixtures "are sanitized" but describes no sanitization mechanism. `scripts/record_fusion.py` hits the real API and writes raw responses. Who sanitizes? When? How?

- Model outputs from real prompts can contain: user-provided data echoed back, API keys in system prompts, personal names, addresses, etc.
- `record_fusion.py` writes raw JSON. There is no post-processing step, no regex scrubber, no manual review gate.
- "Never in CI" doesn't prevent a developer from committing unsanitized fixtures.

**WHY:** This is a data-leak liability. A single commit with unsanitized fixtures containing PII in a public repo is a compliance incident.

**CONCRETE FIX:** Add to §7:
1. `record_fusion.py` must write to a `fixtures/.gitignore`d staging directory.
2. A separate `scripts/sanitize_fixtures.py` scrubs: API keys (regex for `sk-`, `Bearer`), email addresses, phone numbers, and any string > 200 characters (likely user-pasted content).
3. Sanitized fixtures are written to `fixtures/openrouter-fusion-*.json`.
4. CI runs a lint check: no fixture file may contain patterns matching known secret formats.
5. Add an acceptance criterion: "sanitization script exists and passes its own test suite."

---

### 9. No timeout or retry strategy specified

**WHERE:** §4 (entire Wire protocol section)

**WHAT:** The plan mentions rate-limit errors as a pass-through but says nothing about:
- **HTTP timeouts**: A panel of 3-8 models running in parallel can take 30-120 seconds. What's the client timeout? The default `httpx` timeout is 5 seconds — way too short.
- **Retry strategy**: OpenRouter rate limits are per-model. If model A is rate-limited but B and C succeed, does the panel partial-fail? Does OpenRouter retry internally? Should Hermes retry the whole call?
- **Streaming**: Is this tool call synchronous (blocking the agent for up to 2 minutes) or streamed? The plan doesn't say.

**WHY:** Without timeout configuration, the tool will either (a) time out on every real call (5s default), or (b) the implementer will set an arbitrary timeout that's either too short or too long. Without retry guidance, rate-limit errors will surface to the outer model as raw errors with no retry strategy.

**CONCRETE FIX:** Add to §4 and §3:
- New parameter `timeout_seconds: int` (default 120) — exposed to the caller.
- Document: "OpenRouter handles per-model retries internally. Hermes does NOT retry on rate-limit; the error is surfaced to the outer model. The outer model's own retry logic handles it."
- Add a unit test for timeout behavior.
- Add an acceptance criterion: "tool respects `timeout_seconds` parameter and raises `TimeoutError` on expiry."

---

### 10. The schema allows `temperature: 0` through `2` but many models reject values > 1 or < 0

**WHERE:** §3 (Tool schema — `temperature`)

**WHAT:** `temperature` is typed as `number` with `minimum: 0, maximum: 2`. But:
- Anthropic models accept 0-1.
- OpenAI models accept 0-2.
- Google models accept 0-2 (Gemini) but some accept 0-1.
- The tool passes `temperature` to OpenRouter, which forwards to the underlying provider. A value of 1.5 sent to Claude will be rejected.

**WHY:** The implementer will get provider-specific errors that aren't handled. The schema is too permissive.

**CONCRETE FIX:** Either:
- (a) Remove the `temperature` parameter from v0.1 (simpler, avoids the problem), or
- (b) Set `maximum: 1` (safe for all providers), or
- (c) Document that values >1 may fail for some providers and the error is surfaced as-is.
Recommend (a) for v0.1 — temperature tuning is an advanced use case.

---

## TIER 3: Nice-to-have (file as follow-up)

### 11. No logging/observability for cost tracking

**WHERE:** §6 (cost model), §7 (test strategy)

**WHAT:** The plan computes cost estimates but has no mechanism to log actual costs. OpenRouter returns `usage` in its response. The tool should log `total_tokens` and estimated cost per call to a structured log file. Without this, the cost guard in §5 is a guess based on panel size, not actual token counts.

**CONCRETE FIX:** File as follow-up. Add `cost_tracker.py` that logs `{timestamp, prompt_tokens, completion_tokens, estimated_cost_usd, models, judge_model}` per fusion call. Wire to Hermes's existing logging.

---

### 12. No abort/cancel mechanism for a running fusion call

**WHERE:** §3 (Tool schema), §4 (Wire protocol)

**WHAT:** Once the tool is invoked, the agent cannot cancel it. A panel of 8 models running for 90 seconds blocks the entire agent turn. If the user sends a "stop" message, the agent can't interrupt the fusion.

**CONCRETE FIX:** File as follow-up (v0.2). Implement via asyncio task cancellation or a shared cancellation token.

---

### 13. The `reasoning_effort` parameter is typed as `["string", "null"]` with `None` in the enum, which is a JSON Schema antipattern

**WHERE:** §3 (Tool schema)

**WHAT:** `"type": ["string", "null"]` with `"enum": ["low", "medium", "high", None]` — `None` in a JSON enum is `null` in JSON, but some LLM tool-call parsers will choke on this or serialize it differently. The safer pattern is to omit the parameter when null rather than send an explicit null.

**CONCRETE FIX:** File as follow-up. Make `reasoning_effort` optional (not in `required`), and in the implementation, only include it in the OpenRouter body when the LLM provides a value.

---

### 14. `additionalProperties: false` on the tool schema may break some LLMs

**WHERE:** §3

**WHAT:** Some models (particularly older Claude and GPT variants) sometimes inject extra keys in tool calls. `additionalProperties: false` causes schema validation to reject those calls. This is a minor compatibility risk.

**CONCRETE FIX:** File as follow-up. Log warnings on schema validation failures rather than hard-rejecting, at least in v0.1.

---

### 15. Fixture naming convention is unspecified

**WHERE:** §7 ("fixtures/openrouter-fusion-*.json")

**WHAT:** What goes in the `*`? `panel3-judge-default-reasoning-high`? `panel8-judge-claude-opus`? Without a convention, fixtures accumulate with inconsistent names and it's unclear which scenario each covers.

**CONCRETE FIX:** File as follow-up. Define: `fixtures/openrouter-fusion-{panel_size}-{judge_model_slug}-{scenario}.json` where `scenario` is one of `success`, `judge_degraded`, `all_failed`, `partial_success`, `rate_limited`.

---

## Questions the Human Reviewer Should Ask Before Approving

1. **"Is `x-openrouter-fusion-depth` a real header, and if so, can you link the specific OpenRouter documentation page?"** — If the author cannot produce a URL, the entire server-side recursion guard is vapor and the plan needs a rewrite of §4.

2. **"What is the exact behavior when 1 of 3 panel models fails? Does OpenRouter return `status: 'ok'` with 2 responses and no analysis? With 2 responses and analysis? With `status: 'error'`?"** — This determines whether partial-success handling is a Tier 1 or Tier 2 issue. If OpenRouter returns an error when any panel member fails, the "judge-degradation" path is narrower than the plan assumes.

3. **"Have you actually called `openrouter:fusion` via the OpenRouter API yourself, and do you have a real response payload to share?"** — If the author has never called the API, the wire-protocol section is entirely based on documentation reading, and docs for beta features are frequently incomplete or wrong. The plan should be validated against a real response before implementation begins.

4. **"What happens to the cost guard if the user sets `force: true` — does it bypass the guard or not? And if it does, why does a tool-choice override also override a safety mechanism?"** — This exposes the `force` conflation (Tier 1 #4). The author needs to decide: these are two flags or one.

5. **"If the provider plugin ships in v0.1 and someone selects `openrouter/fusion` as their primary model via `hermes model`, what prevents every single message from costing $0.30+? Is there a 'you're about to route everything through a panel' confirmation?"** — This exposes the contradiction between "opt-in tool" and "selectable primary model" (Tier 2 #7). The answer will likely push the plugin to v0.2.