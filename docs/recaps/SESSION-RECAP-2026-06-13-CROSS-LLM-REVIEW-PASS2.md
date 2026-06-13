# Cross-LLM Review — Pass 2 (Buildability / Subagent-Interpretation Lens)

> **Date:** 2026-06-13
> **Artifact:** `docs/plans/2026-06-13-fusion-tool-design.md` (v2, 32 KB, 705 lines)
> **Brief:** Pattern 4b from `cross-llm-review` skill — buildability lens with explicit "do NOT re-flag" list of v1 fixes that carried over to v2
> **Providers called:** 4 (DeepSeek, GLM, Kimi, Mimo)
> **Providers that completed:** 4/4 — Kimi recovered with `--temperature 1` after Pass 1's failure; Mimo recovered with `--max-tokens 12000` (was truncated at 8192)
> **Note:** v2's Mimo output was truncated at 8192 tokens in the first attempt; re-ran with 12K max-tokens. The 8.5K-token completion is complete and used in the synthesis.

## Consensus legend
- 🔴 **4/4 agree** — every provider flagged this
- 🟠 **3/4 agree** — strong consensus
- 🟡 **2/4 agree** — worth investigating
- ⚪ **1 provider only** — novel insight

---

## Tier 1 — Blockers for delegation (must fix before plan approval)

### 🔴 T1.1: Judge invocation location is contradictory between §4.2 and §4.3
**Flagged by:** DeepSeek, GLM, Mimo (Kimi implied via §4.6 failure-path table)
**Plan location:** §4.2 (Runner — step 4: "If backend didn't produce analysis, run the judge separately (hermes-native does this; openrouter-fusion does it server-side)"), §4.3 (hermes-native: "The judge runs as one of the panel members"), §6.1 (Cost model — judge receives 18K input tokens, only possible if called *after* the panel)
**Issue:** Three different stories about who runs the judge for hermes-native:
- §4.2: the *runner* runs the judge after `run_panel` returns
- §4.3: the *backend* runs the judge as one of the panel members
- §6.1: the judge is called with all panel responses concatenated, which is a second round-trip

If the backend runs the judge as a panel member, the judge sees only its OWN context window's prompt (the user's original prompt), not the other panel members' responses — so the structured analysis would be of nothing useful. If the runner runs the judge as a second round-trip after the panel completes, the judge gets all panel responses — that's the §6.1 cost model.

**Concrete fix:**
- The **runner** runs the judge, never the backend.
- Update §4.2 to make this explicit: "Step 4: Runner invokes judge model with `(user_prompt, panel_responses)` as a second round-trip. The backend's `run_panel` does NOT produce analysis for hermes-native."
- Update §4.3 to remove the "judge runs as one of the panel members" sentence.
- Add to `PanelResponse` semantics: `analysis: dict | None` and `raw_judge_output: str | None` are populated **by the runner** (after `run_panel` returns), not by the backend.
- Backend ABC stays: `run_panel(request) -> PanelResponse` where the backend only does panel fan-out. The `analysis` field is set by the runner post-call.

### 🔴 T1.2: Tool name `openrouter_fusion` contradicts v2's "OpenRouter is opt-in" thesis
**Flagged by:** Mimo, GLM (DeepSeek flagged as "implementer cannot resolve")
**Plan location:** §2 (Out of scope: "Renaming the tool" deferred to v0.2), §3 (Schema: `name: openrouter_fusion`), §9 Q1 (renaming is a question), §10 (acceptance criteria: `openrouter_fusion` tool registers)
**Issue:** The v2 plan's central thesis is "OpenRouter is opt-in, hermes-native is default." But the *tool name itself* is `openrouter_fusion`. Two consequences:
1. **The model prompt text is misleading.** When the model sees the tool description, the name `openrouter_fusion` implies OpenRouter is the primary mechanism — opposite of v2's intent.
2. **Backwards-compat argument is weak.** v0.1 has not shipped. There is no v1 to be compatible with. Keeping the v1 name to be "compatible" with a v1 that never shipped is a paper constraint.

**Concrete fix:**
- **Rename to `fusion` in v0.1.** Update §3, §10, all mentions.
- Remove the "Renaming the tool" item from the v0.2 punch list — it's done in v0.1.
- If you want a deprecation shim for any v1-era prototype usage: register `openrouter_fusion` as a one-line alias to `fusion` with a `DeprecationWarning` on first call. Cost: ~5 lines of code.

### 🟠 T1.3: `asyncio.gather` without `return_exceptions=True` breaks the partial-failure-paths contract
**Flagged by:** Kimi (most explicit), DeepSeek (concurrency section)
**Plan location:** §4.3 (hermes-native: "Fan out via asyncio.gather over the user's existing model providers"), §4.6 (Partial and total panel failure paths — requires capturing partial successes)
**Issue:** The default `asyncio.gather` raises on the first exception, losing all other results. The §4.6 table explicitly requires capturing partial successes (e.g., 2 of 3 panel members succeed, 1 times out → return 2 responses + 1 failed_models entry). Without `return_exceptions=True`, a single panel member's timeout or auth error would crash the entire call and lose the successful responses.

**Concrete fix:** Mandate in §4.3: `results = await asyncio.gather(*tasks, return_exceptions=True)`. Then iterate results: success → append to `responses`, exception → append to `failed_models` with the exception type and message. Update the §4.6 example pseudocode to use this pattern.

### 🟠 T1.4: `run_agent.py` change is in v0.1 but the upstream PR is v0.1.1 — this is a plugin repo
**Flagged by:** Kimi
**Plan location:** §8 (v0.1: "run_agent.py modification (Hermes core): add `from contextvars import ContextVar` and `_fusion_depth: ContextVar[int] = ContextVar(...)` at module level"), §10 (acceptance: "run_agent.py is modified to add the ContextVar")
**Issue:** `~/Projects/fusion` is a third-party plugin. It does not contain `run_agent.py`. The plan says the only hermes-agent core change is in `run_agent.py`, but that change is **outside this repo**. A subagent reading the plan will:
1. Look for `run_agent.py` in the fusion repo, not find it
2. Either invent a fake one in this repo (wrong) or skip the change (silently broken)
3. Discover on Day 1 that the ContextVar doesn't exist anywhere

**Concrete fix:**
- Define the ContextVar **inside the fusion plugin**: `tools/fusion/runner.py` exports `_fusion_depth: ContextVar[int] = ContextVar('fusion_depth', default=0)`. The runner manages its own set/reset.
- Remove "run_agent.py modification" from §8 v0.1 in-scope.
- Keep the upstream patch as a future improvement in v0.1.1 (the runner still works locally with the plugin's own ContextVar; the upstream change would make it a shared global so other tools could see the depth).
- Update §10: replace "run_agent.py is modified" with "the plugin defines its own `_fusion_depth: ContextVar[int]` in `tools/fusion/runner.py`."

### 🟠 T1.5: Circular import risk — `tools/fusion/runner.py` shouldn't import from `run_agent.py`
**Flagged by:** GLM
**Plan location:** §8 (v0.1: ContextVar in run_agent.py), §4.4 (Recursion guard: "lives in `run_agent.py`")
**Issue:** A third-party plugin (this repo) cannot safely import from Hermes core (`run_agent.py`). The import direction is wrong: hermes-agent would need to *discover* the plugin's ContextVar, not the plugin reach into hermes-agent. The original v1 plan's env-var approach had the same problem (the env var was a Hermes-side concept), but the ContextVar approach makes it explicit: the ContextVar should be *owned* by the plugin and discovered by hermes-agent (if at all).

**Concrete fix:** Same as T1.4 — the plugin owns its own ContextVar. The upstream PR in v0.1.1 may add a shared registry in hermes-agent for tools to publish ContextVars they need the agent loop to wrap, but that's a v0.1.1 / v0.2 problem, not v0.1.

### 🟠 T1.6: `max_tool_calls` is meaningless for hermes-native in v0.1
**Flagged by:** GLM
**Plan location:** §3 (Schema: `max_tool_calls` description says "hermes-native caps the per-panel-member iteration count")
**Issue:** v0.1 hermes-native panel members are **single completion calls** (no tool-use loop, §2 explicitly disables web tools and there's no tool-calling infrastructure in v0.1's hermes-native backend). "Per-panel-member iteration count" doesn't exist for a single completion call. A subagent implementing this will either (a) build a mini-agent loop per panel member (massive scope creep) or (b) silently ignore the parameter (misleading). The parameter exists because v1's OpenRouter backend has a real meaning for it; for hermes-native, it's dead weight.

**Concrete fix:** Update §3 `max_tool_calls` description: "Max tool-calling steps the panel/judge models can make. **Backend-specific: openrouter-fusion passes to OpenRouter's per-panel-member limit. hermes-native in v0.1 accepts but ignores this parameter** (panel members make single completion calls; no tool-calling loop). v0.2 may add tool-use loops to hermes-native panel members." Optionally: remove the parameter from the v0.1 hermes-native code path entirely and only document it in the openrouter-fusion backend config.

### 🟡 T1.7: hermes-native `check_requirements` should verify ≥2 fallback models
**Flagged by:** DeepSeek
**Plan location:** §4.1 (`check_requirements() -> True` for hermes-native)
**Issue:** Returning `True` unconditionally means the tool only fails at call time, with a potentially confusing error like "0 models available" or an empty panel. A pre-check would surface the issue with a helpful message: "fusion requires at least 2 models in `model.fallback_providers`."

**Concrete fix:** `check_requirements` for hermes-native:
```python
def check_requirements(self) -> bool:
    cfg = load_hermes_config()
    providers = cfg.get("model", {}).get("fallback_providers", [])
    if not providers:
        return False
    return len(providers) >= 2  # panel of 2 minimum
```
Tool's `check_requirements` returns True only if *some* backend reports True. The first call to an unconfigured tool shows a message like: "fusion requires at least 2 models in `model.fallback_providers`. Configure them in `config.yaml` under `model.fallback_providers`."

### 🟡 T1.8: `analysis_models=[]` auto-population rule is undefined
**Flagged by:** GLM, DeepSeek
**Plan location:** §5 (Configuration: `analysis_models: [] # empty = auto-populate from fallback chain`)
**Issue:** "Auto-populate from fallback chain" is silent on the rule. First 2? First 3? First N that support the prompt's required capabilities (which the tool can't know)?

**Concrete fix:** Add to §5: "When `analysis_models` is empty, the runner auto-populates by taking the **first 3 entries** of `model.fallback_providers`. If the chain has fewer than 2 entries, the tool refuses with a clear error (see T1.7). Users who want a specific panel override `analysis_models` explicitly per call."

---

## Tier 2 — Will cause confusion or rework if not addressed

### T2.1: Per-panel-member fallback chain semantics are undefined
**Flagged by:** Mimo, DeepSeek (Q3)
**Plan location:** §4.3 (hermes-native: "If a model in the panel fails, the fallback_providers chain activates per-panel-member")
**Issue:** Two interpretations:
- (a) Per-member fallback: Claude fails for member 1 → fall back to DeepSeek for that member (member 1 = "DeepSeek after Claude failed")
- (b) Per-member fail: Claude fails for member 1 → report in `failed_models`, panel has 2 of 3 succeed

(a) is user-friendlier but hides transient errors and may surprise the user (they asked for a Claude panel and got mostly DeepSeek). (b) is more honest.

**Concrete fix:** Add to §4.3: "v0.1 semantics: **per-member fail**, not per-member fallback. If a panel member fails (timeout, auth, rate limit), it appears in `failed_models` and the panel continues with the remaining members. Per-member fallback is v0.2 — it requires user-visible `resolved_model` tracking (the actual model that answered may differ from the requested model) and a config flag to opt in. v0.1 keeps the panel = the panel you asked for, with explicit failure surfacing."

### T2.2: `FusionConfig` construction time is ambiguous
**Flagged by:** Mimo
**Plan location:** §4.2 (Runner `__init__` takes `config: FusionConfig`), §5 (Precedence: args > config > schema)
**Issue:** If `FusionConfig` is built once at tool registration, per-call overrides (the "args" layer) need to be passed to `run()` separately. If rebuilt per call, the runner needs a config-factory function. The plan doesn't specify.

**Concrete fix:** Add to §4.2: "The runner holds a `FusionConfig` instance built once from `config.yaml fusion.*` at tool registration. Per-call overrides are passed as kwargs to `run(prompt, panel_models, **overrides)`. The runner's internal resolution merges args > config > schema."

### T2.3: Backend registry discovery mechanism is unspecified
**Flagged by:** GLM
**Plan location:** §4.1 (mentions "backend registry"), §2 (file manifest: `tools/fusion/backends/__init__.py` is a "Backend registry")
**Issue:** Is the registry a Python module that imports each backend (`from .hermes_native import HermesNativeBackend; register(HermesNativeBackend)`)? Is it discovered via Hermes's PluginManager? Is it a config-driven list (`fusion.backends: [hermes-native, openrouter-fusion]`)?

**Concrete fix:** Specify in §4.1: "Backend registration is **explicit in the runner module** at import time. New backends add themselves by calling `register_backend(MyBackend())` in their `__init__.py`. The runner enumerates registered backends by name. This avoids dependence on Hermes's PluginManager and makes the registry self-contained."

### T2.4: Recorded-fixture format for hermes-native is unspecified
**Flagged by:** DeepSeek, Kimi
**Plan location:** §7 (Recorded-fixture tests)
**Issue:** hermes-native calls multiple providers, so fixtures need to capture each panel member's response. Is it one file per call (containing all panel responses + judge output) or multiple files (one per provider)?

**Concrete fix:** Add to §7: "hermes-native fixtures are single JSON files matching the `PanelResponse` dataclass shape:
```json
{
  \"backend\": \"hermes-native\",
  \"panel_request\": {...},
  \"expected_panel_response\": {
    \"responses\": [{\"model\": \"...\", \"content\": \"...\", ...}, ...],
    \"failed_models\": [...],
    \"analysis\": {\"consensus\": [...], ...},
    \"raw_judge_output\": null
  }
}
```
Required fixtures: `success.json`, `judge-degraded.json`, `all-panel-failed.json`, `partial-panel-failed.json`."

### T2.5: Curator slot fallback when provider is unavailable
**Flagged by:** GLM
**Plan location:** §9 Q8 (asked but unanswered)
**Issue:** `judge_strategy: auxiliary-curator` requires the curator's provider to be available. If not, the tool needs a fallback rule.

**Concrete fix:** Add to §4.5: "If `judge_strategy` is `auxiliary-curator` and the curator model's provider is unavailable (no API key, provider down), fall back to `outer-model` and log a warning: `'Curator model {model} unavailable; falling back to outer model {outer_model}'`. If the outer model is also unavailable, skip the judge and return raw panel responses (the outer model can synthesize)."

### T2.6: `max_tool_calls` schema description contradicts the dead-weight finding
**Flagged by:** GLM
**Plan location:** §3 schema description for `max_tool_calls`
**Concrete fix:** Covered by T1.6.

### T2.7: `judge_strategy` default contradiction between §3 and §4.5
**Flagged by:** DeepSeek (Q12)
**Plan location:** §3 (default `"judge_strategy": "outer-model"`), §4.5 (cost-model example shows "curator slot" judge)
**Issue:** §3 says default is `outer-model`. §4.5 example shows curator slot. Which is right?

**Concrete fix:** §3 is correct (`outer-model` is the default — zero extra cost). §4.5 example is illustrative; update it to use `outer-model` for the example, or explicitly note "if `judge_strategy` is `auxiliary-curator`, the judge receives 18K + 2K tokens as in §6.1."

### T2.8: The hermes-native judge receives 18K input tokens — but where does that come from?
**Flagged by:** Mimo (implied), GLM
**Plan location:** §6.1 (Cost model row: "Judge (curator slot, typically Kimi K2.6) | 18K in + ~2K structured-analysis out")
**Issue:** 18K is the *concatenation of all panel responses*. The runner must assemble this and pass it to the judge. The plan should specify the assembly format.

**Concrete fix:** Add to §4.5: "The runner assembles the judge input as a single user message with structure: `'You have been given the following {N} responses to the same prompt:\n\n[Response 1 from {model_1}]\n{content_1}\n\n[Response 2 from {model_2}]\n{content_2}\n\n...\n\n{JUDGE_PROMPT}'`. The 18K input token count in §6.1 assumes 3 panel members × 6K average response."

### T2.9: §8 v0.1.1 upstream PR ordering
**Flagged by:** Kimi
**Plan location:** §8 (5 items: ContextVar in run_agent.py, model_tools.py entry, _DEFAULT_OFF_TOOLSETS, toolsets.py, AGENTS.md)
**Issue:** Are these atomic? Can they ship in any order?

**Concrete fix:** Add to §8: "v0.1.1 PR ordering — must be atomic, all 5 in one PR (the upstream change is a coherent unit: register the toolset, add the off-by-default gate, document it, share the ContextVar if applicable). No ordering risk if shipped together."

---

## Tier 3 — File as follow-up plan

### T3.1: Backend ABC granularity
**Flagged by:** DeepSeek
**Plan location:** §4.1
**Issue:** Should the ABC expose `resolve_judge_model(strategy) -> str` so each backend can implement its own judge resolution? Or should the runner do all judge resolution and the backend just does panel fan-out?
**Follow-up:** v0.2 — explore whether some backend (e.g., a future Anthropic batch API backend) would want bespoke judge resolution.

### T3.2: Web tools in hermes-native panel members
**Plan location:** §2 (disabled in v0.1), §5 (`enable_web_tools: false`)
**Follow-up:** v0.2 — expose as opt-in. hermes-native panel members would need to invoke Hermes's web tools in a tool-calling loop, which requires the tool-use loop infrastructure that's not in v0.1.

### T3.3: Streaming tool results
**Plan location:** §2 (deferred)
**Follow-up:** v0.2 — partial-stream panel responses as they arrive.

### T3.4: Per-call dollar cap
**Plan location:** §6.3 (deferred)
**Follow-up:** v0.2 — `max_cost_usd: 5.00` abort before fan-out based on input-size × rate estimates.

### T3.5: Observability
**Plan location:** §2 (deferred)
**Follow-up:** v0.2 — structured logging (model names, token counts, latency, estimated cost) and per-session cost counter.

---

## Questions for the human (5)

1. **Tool name: rename to `fusion` in v0.1 or keep `openrouter_fusion` for v1 compat?** v0.1 hasn't shipped — there is no v1 to be compatible with. The plan's own thesis is that OpenRouter is opt-in. The name should match. (T1.2)

2. **Judge ownership: runner does the judge (single source of truth) or each backend does it?** Three reviewers flagged the contradiction between §4.2/§4.3/§6.1. The runner doing the judge is the cleanest answer (and what §6.1's cost model assumes), but the plan's pseudocode in §4.3 says the backend does it. Pick one. (T1.1)

3. **`run_agent.py` ContextVar: own it in the plugin (tools/fusion/runner.py) or upstream-patch hermes-agent?** A third-party plugin shouldn't import from hermes-agent core. The plugin should own its own ContextVar and self-guard. (T1.4, T1.5)

4. **Per-panel-member fallback semantics for hermes-native: per-member-fail (v0.1 simple) or per-member-substitute (v0.2 honest)?** Per-member-fail is simpler and matches the §4.6 partial-failure-paths table. Per-member-substitute is more user-friendly but requires `resolved_model` tracking in the response. (T2.1)

5. **v0.1 deadline pressure?** If v0.1 needs to ship this week, T1.1 (judge location), T1.2 (tool name), T1.3 (asyncio.gather), and T1.4/T1.5 (ContextVar ownership) are non-negotiable. T1.6-T1.8 are smaller. If v0.1 is more relaxed, T2 items can be polished in this same pass.

---

## Per-model summary

| Model | Strongest at | Caught that others missed |
|-------|-------------|---------------------------|
| **DeepSeek-v4-pro** | Concurrency / asyncio safety, hermes-specific integration gaps, fixture format | T1.7 (check_requirements pre-check), T2.4 (fixture format), T2.7 (judge_strategy default contradiction) |
| **GLM-5.1** | Concrete code-level analysis, import-graph issues, dead-code detection | T1.5 (circular import risk between plugin and hermes-agent), T1.6 (`max_tool_calls` is dead weight for hermes-native), T2.3 (backend registry mechanism) |
| **Kimi-k2.6** | Buildability for a subagent (most thorough; longest output at 34K chars) | T1.3 (`asyncio.gather` without `return_exceptions=True` is a critical bug), T1.4 (this is a plugin repo, `run_agent.py` doesn't exist here), T2.9 (PR atomicity) |
| **Mimo-m2.5-pro** | Tool-name semantic analysis, hermes-native/judge separation, fallback-substitution UX | T1.2 (tool name contradicts the v2 thesis — the most user-visible bug in v2), T2.1 (per-member-fail vs per-member-substitute UX), T2.2 (FusionConfig construction time) |

---

## Recommended patch order (Tier 1 first)

1. **T1.1** — §4.2/§4.3 judge-location contradiction. ~10 min of plan edits.
2. **T1.2** — Rename tool to `fusion`. ~5 min.
3. **T1.3** — `asyncio.gather(..., return_exceptions=True)`. ~5 min + 1 unit test.
4. **T1.4 + T1.5** — Move ContextVar to `tools/fusion/runner.py`. ~10 min of plan edits + remove the "run_agent.py" AC.
5. **T1.6** — `max_tool_calls` ignored for hermes-native v0.1. ~3 min.
6. **T1.7** — hermes-native `check_requirements` ≥2 models. ~5 min.
7. **T1.8** — `analysis_models=[]` auto-population = first 3 from fallback chain. ~3 min.
8. **T2.1–T2.9** — batch edits to §4, §5, §7, §8.
9. After patches: re-run cross-LLM review with the buildability lens to confirm no new Tier 1 items. If clean, ship the implementation brief.

---

## Raw provider outputs

- `docs/recaps/REVIEW-DEEPSEEK-PASS2-2026-06-13.md` (10.3 KB, 8192 tokens)
- `docs/recaps/REVIEW-GLM-PASS2-2026-06-13.md` (13.2 KB, 8192 tokens)
- `docs/recaps/REVIEW-KIMI-PASS2-2026-06-13.md` (34.1 KB, 8192 tokens — most thorough)
- `docs/recaps/REVIEW-MIMO-PASS2-2026-06-13.md` (8.5 KB, 8467 tokens — re-ran at 12K max-tokens after first run was truncated at 8192)
