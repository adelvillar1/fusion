# Cross-LLM Review — Pass 2 (Buildability / Subagent-Interpretation Lens)

**Provider:** Kimi-k2.6
**Model:** kimi-k2.6
**Latency:** 49767ms
**Tokens in/out:** 9263/8192
**Error:** none

**Artifact:** `docs/plans/2026-06-13-fusion-tool-design.md` (v2, 32 KB, 705 lines)

**Brief:** Pattern 4b from `cross-llm-review` skill — buildability lens with explicit
"do NOT re-flag" list of v1 fixes that carried over to v2.

---

The user wants a second-pass review of a design plan for a backend-pluggable fusion tool in Hermes Agent. The context is that this plan will be handed to a subagent for implementation. I need to find specific, actionable issues that a subagent would misinterpret, focusing on buildability, hidden ordering dependencies, interface vs implementation gaps, concurrency/async pitfalls, and Hermes-specific tool dispatch/ContextVar integration.

I must NOT re-flag items already carried over from v1. I need to focus on new issues in v2.

Let me carefully analyze the plan section by section with the lens of: "What would a subagent building this literally get wrong?"

Key areas to scrutinize:

1. Backend ABC granularity (§4.1):
   - The ABC has `run_panel` taking `judge_model: str` as resolved by the runner. But for OpenRouter backend, the judge runs server-side. So the runner resolves a judge model string that the OpenRouter backend might ignore entirely. The ABC says `judge_model` is required, but the OpenRouter backend doesn't use it. A subagent might wonder "why am I passing a judge_model to OpenRouter if it doesn't use it?" This is a leaky abstraction.
   - Also, `check_requirements` is a method, but there's no mention of whether it's async or sync. It should be sync since it's just checking env vars, but a subagent might make it async unnecessarily.
   - The ABC `name` is a class attribute, but there's no `__init__` or registry mechanism shown. The subagent might not know how to instantiate or register backends.
   - `PanelResponse` has `analysis: dict | None` and `raw_judge_output: str | None`. The subagent will need to know which to use. The runner needs to handle both. But for OpenRouter, `analysis` is populated by the server. For hermes-native, the runner populates it after calling the judge. Wait, §4.2 says: "If backend didn't produce analysis, run the judge separately". So for hermes-native, `run_panel` returns `responses` and maybe empty `analysis`, then runner invokes judge. But §4.3 says "The judge runs as one of the panel members". That's contradictory. §4.2 says runner runs judge separately, §4.3 says judge runs as one of the panel members. This is ambiguous.

2. auxiliary_client extension (§8):
   - The plan says `auxiliary_client.py` may need a `panel_call()` helper. But it doesn't actually read the file. As an AI reviewer, I don't have the actual file content either, but I can infer from the context. The plan says "The exact location is decided during implementation." This is too vague for a subagent. They need to know: does `auxiliary_client` expose async `call_model(model_id, prompt, ...)`? If so, `panel_call` is just `asyncio.gather(*[call_model(...) for ...])`. The subagent might incorrectly try to modify core Hermes code when they can just use the existing client in a loop.
   - Actually, looking at the plan, it says "The hermes-native backend uses the same model clients Hermes already uses (auxiliary_client.py, the per-provider async clients in plugins/model-providers/*/, the model.fallback_providers chain)." This implies the backend should use existing clients. But then it says "auxiliary_client.py extension... may not be a true core change — could be a new module under tools/fusion/." This is a decision deferred to implementation. For a subagent, this is a blocker: they don't know if they need to modify core files.

3. Recursion guard wiring in run_agent.py (§4.4, §8):
   - The plan says: "add `from contextvars import ContextVar` and `_fusion_depth: ContextVar[int] = ContextVar('fusion_depth', default=0)` at module level. Wrap the tool dispatcher call in set/reset."
   - This is extremely vague. A subagent needs to know: where exactly in `run_agent.py`? Is it `run_agent.py` in the Hermes repo? The plan mentions `run_agent.py` modification as the only core change. But a subagent can't literally find "the tool dispatcher call" without knowing the function name. The plan should specify the exact function, e.g., `dispatch_tool` or `handle_function_call`. If it's async, the ContextVar scope should be set in the async function that calls the tool. But if `run_agent.py` is a sync entry point, wrapping an async call might not work correctly with ContextVars because async tasks might inherit context differently.
   - Also, "Wrap the tool dispatcher call in set/reset" — if the tool dispatcher is a single call that handles all tools, setting the ContextVar for all tools means every tool call increments the depth? No, the plan says "Per-call scope: two independent fusion calls in the same conversation session both succeed." Wait, the ContextVar is named `_fusion_depth` but if it's set at the tool dispatcher level, every tool call would see it? No, the plan says "Raises RecursionError if >= 1." If it's set per fusion call, the runner increments it. But §4.4 says "A request-scoped contextvars.ContextVar[int] named _fusion_depth lives in run_agent.py. The runner increments on entry, resets in finally." Wait, the runner increments it? But the runner is inside the tool implementation. If the ContextVar is in `run_agent.py`, the runner (in `tools/fusion/`) would need to import it. That's fine. But if the runner is called via the tool dispatcher, the ContextVar is already set? Actually, §4.4 says "The runner increments on entry, resets in finally." So the runner does the set/reset, not `run_agent.py`. But §8 says "Wrap the tool dispatcher call in set/reset." This is contradictory. A subagent would be confused: who sets the ContextVar?
   - Also, if the runner increments it, and the tool name is `openrouter_fusion`, what happens if a subagent calls the same tool recursively via the LLM? The runner increments to 1, then if the LLM calls fusion again inside the same request context, it would increment to 2? But the guard says >= 1. So if the outer agent is running a fusion tool, and inside that tool, the LLM (via the tool) calls another tool? No, the panel members are model calls, not tool calls. But the judge model might call a tool? The plan says "max_tool_calls: Max tool-calling steps the panel/judge models can make." So panel models can make tool calls. If a panel model calls the fusion tool again, that's recursion. The ContextVar would catch it because it's in the same execution context? Actually, if the panel model is called via `auxiliary_client`, does it run in the same asyncio Task? If it's a separate task spawned by `asyncio.gather`, it might inherit the context if `contextvars.copy_context()` is used or if asyncio preserves context. Python's `asyncio.create_task` copies context by default in 3.11+. So if a panel model calls the fusion tool, it would see the same ContextVar value? Then it would increment and hit >=1. Wait, but the runner sets it in the outer tool call. If the panel member is a separate task with copied context, it copies the ContextVar state. Then when the panel member's LLM calls the fusion tool again, the runner in that sub-task would see the ContextVar already at 1 (from the copy), and increment to 2? Or does it see it as 0 because it was set in the parent task's context? Actually, ContextVars are task-local. When `create_task` copies the context, it copies the current value. So if the parent set it to 1 before creating the task, the child sees 1. But in this design, the runner sets the ContextVar after being called by the tool dispatcher. The panel members are created by the backend via `asyncio.gather` inside the runner. If the runner sets the ContextVar to 1 before calling `gather`, the tasks created by `gather` will copy the context where `_fusion_depth` is 1. Then if any panel member LLM calls the fusion tool again, the runner will see `_fusion_depth` as 1 (inherited), increment to 2, and not raise? Wait, the plan says "Raises RecursionError if >= 1." If the runner increments on entry, then if it's already 1, it becomes 2. But the check is `>= 1` before increment? Or after? The plan says "increments on entry, resets in finally. Raises RecursionError if >= 1." This is ambiguous. Does it mean: if current value >= 1, raise? Or if after incrementing >= 1? If it's "raise if >= 1" before increment, then the first call (0) passes, increments to 1. A recursive call from a panel member would see 1 (copied) and raise. That works. But if the runner is the one that increments, and the parent runner is still running (hasn't reset), the child sees 1 and raises. Good. But wait: if the runner is in the tool implementation, and the tool dispatcher in `run_agent.py` calls the tool, the tool runs. Inside, `gather` creates tasks. Those tasks copy the context. If the parent tool set the ContextVar to 1, the child tasks have it as 1. If a child task calls the fusion tool again, the runner sees 1 and raises. This is correct. But what if `run_agent.py` also wraps the tool dispatcher call and sets it? Then the runner would see it already set? No, the plan is contradictory here.

4. Curator slot when its provider isn't in fallback_providers (§9 Q8):
   - The plan identifies this as an open question but doesn't answer it. A subagent will hit this and make a wrong choice. For buildability, this needs a decision.

5. Empty fallback_providers (§9 Q9):
   - Also an open question with no default answer.

6. Per-panel-member fallback chain semantics (§9 Q3):
   - The plan says "Per-panel-member fallback (i.e., if Claude fails for panel member 1, fall back to DeepSeek for that member) is the cleanest answer." But the `analysis_models` parameter is a list of strings. If the user specifies `["claude-3-opus", "deepseek-chat"]`, and Claude fails, does it fall back to the next in `fallback_providers`? Or does the panel member use the fallback chain configured in Hermes? The plan says "The hermes-native backend uses the user's existing model clients... the fallback_providers chain activates per-panel-member." But `analysis_models` are explicit. If `fallback_providers` is `["claude", "deepseek", "kimi"]` and the user asks for `["claude", "kimi"]`, does panel member 2 (kimi) fall back to... what? The fallback chain is global. If a specific model fails, does the backend try the next model in the fallback chain? Or does it try the next item in `analysis_models`? The plan says "panel members" but `fallback_providers` is a list of fallback options for the *primary* model, not necessarily the panel. This is a major misinterpretation risk. A subagent might think: "I need to call model X, and if it fails, call model Y from fallback_providers." But `fallback_providers` is for when the *outer* model fails, and it might not make sense to use it per-panel-member if the user explicitly chose specific models for comparison. Also, if the fallback chain is `["claude", "deepseek"]` and the panel is `["claude", "deepseek"]`, and claude fails, falling back to deepseek for the first panel member means you have two deepseek calls. Is that intended? The plan says "the panel is '3 model attempts' not '3 specific models or nothing.'" This is a design choice that needs to be explicit. But it's ambiguous whether `analysis_models` overrides or combines with fallback.

7. Concurrency / asyncio safety (§4.3):
   - "Fan out via asyncio.gather over the user's existing model providers." Panel of 8 means 8 concurrent calls. Hermes's `auxiliary_client` or provider clients might have connection pool limits. If all panel members use the same provider (e.g., OpenAI), 8 concurrent requests to OpenAI might hit the client's connection pool limit (e.g., httpx limits). The plan doesn't mention a semaphore. A subagent might write `asyncio.gather(*[call_client(...) for _ in range(8)])` and deadlock or exhaust the pool.
   - Also, timeouts: the backend has `timeout_seconds`, but if 8 calls each take 120s, the `asyncio.wait_for` on the gather is needed. But if one panel member hangs, `gather` won't cancel others unless wrapped carefully. The plan mentions `TimeoutError` but not cancellation semantics.

8. Structured analysis prompt (§4.5, §9 Q4):
   - v0.1 ships a fixed prompt. But §9 Q4 says "Should the structured-analysis prompt be configurable? Yes." But then v0.1 scope says nothing about configurable prompts. This is a contradiction. If Q4 says "v0.1 ships a default prompt + a config override", but §2 In Scope doesn't list "configurable judge prompt". The acceptance criteria don't mention it. A subagent might add it (scope creep) or miss it (if they think Q4 is answered). Actually, looking closely, §9 Q4 says: "v0.1 ships a default prompt + a config override." But the In Scope section doesn't explicitly mention this. However, §5 config doesn't show a prompt override. So this is a hole: Q4 claims it's in v0.1, but the config schema and scope don't include it.

9. FusionBackend.check_requirements (§4.1, item 9 in prompt):
   - `hermes-native` returns True. But if `fallback_providers` is empty or has 1 model, the panel can't run. Should `check_requirements` verify this? The runner does the cost guard and default populating. But `check_requirements` is called before running? The plan doesn't say when. A subagent might not call it.

10. analysis_models default behavior (§5):
    - "Default: pull 2-3 models from model.fallback_providers if unset." How? First 3? Random? The config says `analysis_models: []` means auto-populate. But the exact rule is not specified. A subagent might pull all, or the first N, or skip the primary model.

11. Backend registry discovery (§4.2):
    - "Backend registry" in `tools/fusion/backends/__init__.py`. Is this a simple dict? Does it use Hermes's PluginManager? The plan doesn't show the registry code. A subagent might build a separate registry that conflicts with Hermes's plugin system.

12. judge_strategy default (§3, §5):
    - §3 schema says default is `"outer-model"`. §5 config says `judge_strategy: "outer-model"`. §4.5 example says "The judge can be the auxiliary.curator slot". But §3 description for `judge_strategy` says default is outer-model. This seems consistent. But wait, in §9 Q12, the prompt asks: "Which is the default?" Looking back, §3 says default is `"outer-model"`. The schema default is `"outer-model"`. So that's consistent. But what about `judge_model_default: "kimi-k2.6"` in config? That's for when `judge_strategy` is `explicit-model`? No, §5 says `judge_model_default: "kimi-k2.6"` is a fallback if outer-model isn't routable. But the schema doesn't mention this fallback. The subagent needs to know: when is outer-model not routable? If the outer model is a provider plugin that doesn't support the judge prompt? Or if it fails? This is not defined.

13. Recorded fixtures for hermes-native (§7):
    - The plan says fixtures are `fusion-*.json` for hermes-native. But how is a fixture structured? The hermes-native backend involves multiple async calls to different providers. A fixture would need to record the request/response for each panel member and the judge. The plan doesn't specify the fixture format. A subagent will invent a format that may not match the test harness.

14. Tool name decision (§9 T1):
    - The plan says "kept name for v1 history; renames in v0.2" in scope, but §9 Q1 recommendation is "rename to fusion in v0.1." This is a direct contradiction in the plan. §2 says: "Renaming the tool. The openrouter_fusion name stays for v0.1... v0.2 renames to fusion." §9 Q1 says: "Recommendation: rename to fusion in v0.1." This is a Tier 1 blocker because the subagent won't know what name to implement, and tests/registration will fail.

15. §8 v0.1.1 upstream PR scope:
    - The plan lists 3 items (model_tools.py, DEFAULT_OFF_TOOLSETS, toolsets.py/AGENTS.md). Are they order-dependent? Probably not, but the subagent needs to know if they need to patch core files in this repo or in the upstream hermes-agent repo. The plan says "v0.1.1: upstream PR". So for v0.1, they should NOT touch upstream files. But the acceptance criteria §10 says "run_agent.py is modified to add the ContextVar" — that's a core change in this repo? Or upstream? The plan says "v0.1 (in this repo, shipped with the tool)" for integration point 1, but then says "upstream PR to hermes-agent — deferred to v0.1.1". So `run_agent.py` modification is happening in this repo? But `run_agent.py` is part of hermes-agent core. If this repo is `adelvillar1/fusion`, it might be a plugin repo that doesn't contain `run_agent.py`. The subagent will be confused about where to make the change.

Now, let me structure the findings.

TIER 1 (blockers):
- Tool name contradiction: §2 says keep `openrouter_fusion`, §9 Q1 says rename to `fusion`. Subagent can't implement both.
- ContextVar wiring contradiction: §4.4 says runner increments, §8 says `run_agent.py` wraps tool dispatcher. Subagent won't know which file to modify.
- Judge orchestration contradiction: §4.2 says runner runs judge separately if backend didn't produce analysis. §4.3 says "The judge runs as one of the panel members". This implies hermes-native includes judge in panel. But §4.2 says runner does it. Which is it?
- Backend ABC contract leak: `run_panel` receives `judge_model` but OpenRouter backend ignores it. Subagent will pass it unnecessarily and might not understand why.
- `analysis_models` default auto-populate rule missing: §5 says "pull 2-3 models from fallback_providers" but doesn't specify the selection rule (first N, random, skip primary?). Subagent will guess.
- Configurable judge prompt claim vs scope: §9 Q4 says v0.1 ships default + config override, but §5 config schema and §2 In Scope don't include it. Subagent will either omit it (violating Q4) or add it (scope creep).
- Missing fixture schema for hermes-native: §7 lists fixture files but doesn't define the JSON structure for multi-call recordings. Subagent will invent incompatible format.
- Empty fallback_providers / curator-not-in-fallback unresolved: §9 Q8/Q9 are open questions with no default. Subagent must pick; wrong pick breaks tool.
- `run_agent.py` modification ownership: §8 says it's the only core change for v0.1, but §2 says upstream PR deferred to v0.1.1. If this repo is a plugin, `run_agent.py` isn't here. Subagent will be blocked.

TIER 2 (confusion/rework):
- `check_requirements` call site missing: §4.1 defines it but never says when runner calls it.
- Per-panel-member fallback semantics ambiguous: §9 Q3 says per-panel-member fallback is "cleanest" but doesn't define the interaction between explicit `analysis_models` and the global `fallback_providers` chain. Subagent may apply fallback to every panel member, causing model duplication.
- Concurrency guard missing: No mention of semaphore or connection pool limits for 8 concurrent model calls. Subagent might ignore it and hit `httpx` pool exhaustion.
- `judge_model_default` fallback logic undefined: §5 mentions it as fallback if outer-model isn't routable, but no logic for "not routable" is defined. Subagent won't know when to trigger it.
- Backend registry mechanism undefined: §4.2 mentions "backend registry" but doesn't show how backends discover/register. Subagent might hardcode a dict instead of using Hermes's PluginManager.
- `auxiliary_client` extension location undefined: §8 says "may not be a true core change — could be a new module under tools/fusion/". Subagent needs a decision.
- `max_tool_calls` semantics: §3 says "Max tool-calling steps the panel/judge models can make. Backend-specific interpretation; hermes-native caps the per-panel-member iteration count". Does this mean each panel member can call tools up to `max_tool_calls`? That's a lot of tool calls. Subagent might not implement tool-call chaining in panel members at all (which is fine, but plan says it's in scope).
- Timeout/cancellation: `asyncio.gather` with timeout. If timeout hits, does the backend cancel pending panel calls? Plan doesn't specify cancellation semantics.

TIER 3 (follow-up):
- Prompt configurability for different analysis lenses (legal, code, etc.) — file for v0.2.
- Per-call dollar cap (`max_cost_usd`) — already deferred to v0.2.
- Streaming tool results — already deferred.
- Observability/metrics — already deferred.
- Anthropic batch API backend — already deferred.

Wait, I need to be careful. The prompt says "Do NOT re-flag the already-patched items." So I should not list things like "force parameter dropped" etc. I need to find new bugs.

Let me re-read the plan carefully to spot more subtle issues.

Section 3: Tool schema.
- `analysis_models` has `minItems: 2`, `maxItems: 16`. But the default panel might be pulled from `fallback_providers` which could have only 1 item. If the user has only 1 fallback provider, the schema requires minItems 2, but the auto-populate might produce only 1. The subagent won't know whether to reject or duplicate.
- `judge_model` is in the schema but has no `default`. If `judge_strategy` is not `explicit-model`, this parameter is absent. The schema doesn't mark it as required. That's fine.
- `additionalProperties: False`. Good.
- `max_tool_calls` default 8. But for hermes-native, if panel members can call tools, and there are 8 panel members, that's 8*8 = 64 potential tool calls. The plan says "hermes-native caps the per-panel-member iteration count". But does the outer runner or the backend enforce this? Unclear.

Section 4.3: Hermes-native backend.
- "Each panel member gets the prompt + outer model context; we call the provider directly using Hermes's existing client infrastructure (see auxiliary_client.py)." What is "outer model context"? The entire conversation history? The plan doesn't specify how much context is passed to panel members. If the prompt is just a string, the panel members might be stateless. But if the user asks "where do experts disagree about my previous message", the panel needs conversation history. Does the tool pass the full message history or just the prompt? The schema only has `prompt: string`. This is a huge omission: the panel members are given a bare string with no conversation context. The subagent might pass only the prompt, losing all context. Or they might pass the entire conversation history but the schema doesn't have a parameter for it. Actually, in tool use, the LLM typically passes the relevant context in the prompt. But for a multi-turn conversation, the prompt might need to include history. The tool just takes `prompt`. That's probably fine as the LLM constructs the prompt. But "outer model context" is mentioned in §4.3 without definition. A subagent might think they need to pass the conversation state to the backend.

Section 4.5: Judge layer.
- "Both backends use this prompt and parse into StructuredAnalysis." But OpenRouter backend does it server-side. The subagent doesn't control the prompt for OpenRouter. So the plan's claim that both backends use this prompt is false. The OpenRouter backend gets whatever OpenRouter's server tool returns. This is a misstatement.

Section 4.6: Partial failure.
- "Backend credit exhaustion: Backend raises mid-fan-out. RuntimeError. No retry." If the backend raises mid-fan-out (e.g., after 3 of 8 panel calls succeeded), what happens to the 3 successful responses? `asyncio.gather` will raise the first exception and discard other results unless `return_exceptions=True` is used. The plan says "Backend raises mid-fan-out" but the table says `RuntimeError`. No retry. But the 3 successful responses are lost. The subagent should use `return_exceptions=True` to capture partial results. The plan doesn't specify this implementation detail, but it's critical for the "Partial and total panel failure paths" to work. If the backend uses `gather` without `return_exceptions=True`, partial failure data is lost. This is a subtle async pitfall.

Section 5: Configuration.
- `fusion.analysis_models: []` means auto-populate. But what if the user sets `analysis_models: ["claude-3-opus"]` (1 item)? Schema says minItems 2. Tool call will fail schema validation. But config-level validation isn't mentioned. The subagent might not validate config at startup.
- `judge_model_default: "kimi-k2.6"` — what if the user doesn't have a Kimi key? The config references a specific model. The subagent might not know how to resolve this string to a provider. Is it a model alias in Hermes? Probably, but not stated.

Section 6: Cost model.
- The cost table is for "default panel size of 3". But `max_panel_size` is 8. The cost guard is `max_panel_size`. The subagent needs to know the relationship between default panel size (2-3) and max_panel_size (8). The plan says "Default: pull 2-3 models from model.fallback_providers". Is 2-3 a hardcoded default or a recommendation? The config doesn't specify. The subagent needs an explicit rule: e.g., "min(3, len(fallback_providers))".

Section 7: Test strategy.
- "tests/test_fusion_tool_recorded.py: 4 recorded-fixture tests". But the plan lists 4 scenarios. However, for hermes-native, a fixture needs to mock multiple provider responses. The test strategy says "replay sanitized tests/fixtures/fusion-*.json through the runner." But the runner calls the backend, which calls auxiliary_client. The fixture needs to intercept those calls. Without a defined fixture schema, the subagent can't build the replay mechanism.

Section 8: Integration points.
- "auxiliary_client.py extension: expose a panel_call() helper... The exact location is decided during implementation." This is too vague. Subagent needs to know: should I modify auxiliary_client.py in the core hermes-agent repo (which is deferred to v0.1.1)? Or can I implement it locally in `tools/fusion/client.py`? The plan says "May not be a true core change — could be a new module under tools/fusion/." So the subagent should implement it locally. But then the plan references `auxiliary_client.py` as the canonical path. This is a decision that needs to be made in the plan.

Section 9: Open questions.
- Q6: "Should the ABC also expose resolve_judge_model(strategy) -> str so each backend can implement its own judge resolution?" This is a good question. The plan doesn't answer it. If the runner resolves the judge, then OpenRouter doesn't need `judge_model`. But the ABC passes it anyway. If the subagent implements `resolve_judge_model` in the runner, they need to know how to handle the "outer-model" strategy: they need the outer model ID. The `run_panel` signature has `outer_model: str`, which helps. But what about `auxiliary-curator`? The runner needs to look up the curator slot. The plan doesn't specify how to access the curator slot configuration from the tool code. The subagent needs to know: is the curator slot available in the context? Or is it in `config.yaml` under `auxiliary.curator`? The plan doesn't specify the config path.
- Q7: "Should the hermes-native backend use the existing auxiliary_client or a new client?" Another unanswered question. Subagent blocked.

Section 10: Acceptance criteria.
- "run_agent.py is modified to add the ContextVar" — but if this is an upstream change deferred to v0.1.1, this acceptance criterion is in the wrong version. Or if it's done in this repo, the subagent needs the file to be present. If this repo doesn't contain `run_agent.py`, the subagent cannot fulfill this.

Now, let me formulate the output. I need to be strict, no flattery, with specific section references and concrete fixes.

TIER 1:
1. Tool name contradiction: §2 vs §9 Q1.
2. ContextVar wiring ambiguity: §4.4 vs §8.
3. Judge orchestration contradiction: §4.2 vs §4.3.
4. Missing auto-populate selection rule for analysis_models: §5.
5. Open questions Q8/Q9 unresolved (empty fallback, curator provider): §9.
6. Missing fixture schema for hermes-native recordings: §7.
7. `run_agent.py` core change in v0.1 vs upstream PR deferred to v0.1.1: §8, §10.
8. Backend ABC `judge_model` parameter is ignored by OpenRouter backend: §4.1, §4.2.
9. `return_exceptions=True` missing in `asyncio.gather` for partial failure: §4.3, §4.6.
10. Configurable judge prompt claim without config schema: §9 Q4 vs §5.

TIER 2:
1. `check_requirements` call site undefined.
2. Per-panel-member fallback semantics undefined.
3. Concurrency / connection pool limits.
4. `judge_model_default` fallback logic undefined.
5. Backend registry mechanism undefined.
6. `auxiliary_client` extension location undefined.
7. Cancellation semantics on timeout.
8. `outer_model` context passed to panel members undefined.

Wait, I should narrow down to the strongest, most actionable ones. The prompt asks for "specific, actionable issues with section references and concrete fixes."

Let me pick the best ones.

TIER 1 (must fix before delegation):

1. **Tool name contradiction — §2 vs §9 Q1.**
   - WHAT: §2 says "The openrouter_fusion name stays for v0.1"; §9 Q1 says "Recommendation: rename to fusion in v0.1." Subagent will implement the wrong registration string and acceptance criteria will fail.
   - CONCRETE FIX: Pick one in the plan. If v0.1 ships both, state that explicitly in §2 and §3. If v0.1 ships only `fusion`, update §2 and §10 AC. Recommended: register `fusion` as primary and `openrouter_fusion` as a thin deprecation shim that logs a warning and delegates to `fusion` with backend forced to `openrouter-fusion`.

2. **ContextVar wiring is contradictory — §4.4 vs §8.**
   - WHAT: §4.4 says "The runner increments on entry, resets in finally." §8 says "Wrap the tool dispatcher call in set/reset." Subagent will modify both files, causing double-counting or import errors.
   - CONCRETE FIX: Consolidate on runner-side only. The runner owns `_fusion_depth`. `run_agent.py` does NOT touch it. Remove §8 bullet 1 entirely. The runner lives in `tools/fusion/runner.py` and imports a `ContextVar` defined in `tools/fusion/context.py` (or `tools/fusion/__init__.py`). Add a code snippet: `token = _FUSION_DEPTH.set(_FUSION_DEPTH.get() + 1)` wrapped in `try...finally: _FUSION_DEPTH.reset(token)`.

3. **Judge orchestration model is contradictory — §4.2 vs §4.3.**
   - WHAT: §4.2 says runner invokes judge separately after backend returns. §4.3 says "The judge runs as one of the panel members" inside the backend. Subagent cannot implement both.
   - CONCRETE FIX: Pick one. Recommended: the backend does ONLY panel fan-out; the runner always invokes the judge separately for hermes-native. Update §4.3: remove "The judge runs as one of the panel members" and instead state: "The backend returns `responses` only; the runner always invokes the judge via `auxiliary_client` for hermes-native." Update §4.2 step 4: "For hermes-native, always run the judge via the runner. For openrouter-fusion, the backend populates `analysis` server-side and the runner skips step 4."

4. **Backend ABC `judge_model` parameter is a leaky abstraction — §4.1.**
   - WHAT: `run_panel` takes `judge_model: str`, but the OpenRouter backend ignores it (server-side judge). Subagent will waste time trying to pass it to OpenRouter or will be confused why it's required.
   - CONCRETE FIX: Move judge resolution OUT of the ABC. `run_panel` should only accept `PanelRequest`. The runner resolves the judge model and either (a) passes it to the backend via a separate `run_judge` method if the backend declares `supports_server_side_judge == False`, or (b) skips it. Alternatively, split the ABC: `run_panel(request) -> PanelResponse` and `has_server_side_judge() -> bool`. If `False`, runner calls `run_judge(request, judge_model) -> PanelResponse` separately.

5. **`analysis_models` auto-populate rule is undefined — §5.**
   - WHAT: "pull 2-3 models from model.fallback_providers" is not a rule. First 3? Random? Skip primary? Subagent will guess.
   - CONCRETE FIX: Add explicit rule to §5: "If `analysis_models` is empty, auto-populate with `min(3, len(fallback_providers))` models, taking the first N entries from `model.fallback_providers` (or all if fewer than 3). If `len(fallback_providers) < 2`, refuse with a clear error."

6. **Open questions Q8 and Q9 are unresolved but block implementation — §9.**
   - WHAT: Curator-not-in-fallback and empty fallback chain have no defaults.
   - CONCRETE FIX: Answer them in the plan:
     - Q8: If curator slot provider is not configured, fall back to `judge_model_default`; if that also fails, fall back to `outer-model`.
     - Q9: If `fallback_providers` has < 2 models, refuse with `ValueError: fallback_providers must contain at least 2 models for auto-populate. User can override via analysis_models.`

7. **Hermes-native fixture schema is undefined — §7.**
   - WHAT: §7 lists fixture files but doesn't specify the JSON structure for multi-call recordings.
   - CONCRETE FIX: Add a §7.1 "Fixture schema" subsection showing:
     ```json
     {
       "panel_calls": [
         {"model": "claude-3-opus", "request": {"prompt": "..."}, "response": {"content": "...", "usage": {...}}, "status": "ok"}
       ],
       "judge_call": {"model": "kimi-k2.6", "request": {...}, "response": {...}},
       "expected_panel_response": {...}
     }
     ```

8. **`run_agent.py` change is scoped to v0.1 but upstream PR is deferred to v0.1.1 — §8.**
   - WHAT: §8 says "run_agent.py modification (Hermes core)" is in v0.1, but bullet 3 says upstream PR is v0.1.1. If this repo is a plugin, `run_agent.py` isn't present. Subagent will search in vain.
   - CONCRETE FIX: Clarify in §8: "If `run_agent.py` is not in this repo (plugin mode), the ContextVar must be defined in `tools/fusion/runner.py` and the runner will guard itself. A patch for `run_agent.py` is prepared in `patches/v0.1.1/run_agent_contextvar.patch` for the upstream PR." Remove the AC in §10 that says "run_agent.py is modified" or change it to "run_agent.py patch is prepared and verified against hermes-agent main."

9. **`asyncio.gather` without `return_exceptions=True` breaks partial failure — §4.3, §4.6.**
   - WHAT: If one panel member raises (timeout, auth error), `gather` raises immediately and successful responses are lost. The partial failure table in §4.6 requires capturing partial successes.
   - CONCRETE FIX: Mandate in §4.3: "Use `asyncio.gather(..., return_exceptions=True)` so per-panel