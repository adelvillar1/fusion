# Cross-LLM Review — Pass 2 (Buildability / Subagent-Interpretation Lens)

**Provider:** DeepSeek-v4-pro
**Model:** deepseek-v4-pro
**Latency:** 80870ms
**Tokens in/out:** 10323/8192
**Error:** none

**Artifact:** `docs/plans/2026-06-13-fusion-tool-design.md` (v2, 32 KB, 705 lines)

**Brief:** Pattern 4b from `cross-llm-review` skill — buildability lens with explicit
"do NOT re-flag" list of v1 fixes that carried over to v2.

---

TIER 1 (blocker – must fix before the plan can be given to a subagent)
----------------------------------------------------------------------------

1. **Leaky abstraction in `FusionBackend` ABC – judge responsibility**
   - **Where:** §4.1 (`PanelResponse` fields “Backends fill ONE of: …”), §4.2 step 4, §4.3.
   - **What’s wrong:** The ABC’s `run_panel` returns a `PanelResponse` that *may* contain a structured analysis. For `hermes-native` the plan says the **runner** invokes the judge separately, but §4.3 adds a confusing line: “The judge runs as one of the panel members – either the explicit judge_model or a designated slot.” This contradicts §4.2 and would lead a subagent to either (a) run the judge inside `HermesNativeBackend.run_panel()`, causing double‑judge or wrong semantics, or (b) think the backend must always produce an analysis.
   - **Concrete fix:** Add an explicit boolean `static` attribute `backend_runs_judge: bool` on the ABC (default `True`; `HermesNativeBackend` sets `False`). The runner checks this flag – if `False` it always runs the judge; if `True` it uses the backend’s analysis as‑is. Remove the misleading sentence from §4.3. Document clearly that `HermesNativeBackend.run_panel()` always returns `analysis=None`.

2. **Model‑calling interface is unspecified (hermes‑native backend)**
   - **Where:** §4.3, §8.2 (“expose a `panel_call()` helper”), §9 T3.
   - **What’s wrong:** The hermes‑native backend must call individual models with provider fallback (the `model.fallback_providers` chain). The plan assumes “existing model clients” can do this with a simple `asyncio.gather`, but it never defines the exact function the backend (and later the runner, for the judge) must call. Without that signature – including how model IDs are mapped to providers and how fallbacks are triggered – the implementation is undefined.
   - **Concrete fix:** Define a minimal async call‑model function that the backend and runner will depend on, e.g. `async def call_single_model(model_id: str, messages: list, **kwargs) -> tuple[Optional[str], Optional[dict]]`. State where this lives (likely extended from `auxiliary_client.py`). Confirm that it already exists in the codebase or that creating it is trivial and documented.

3. **Concurrency safety – 8‑way `asyncio.gather` on shared client pools**
   - **Where:** §4.3 (“Fan out via asyncio.gather”), §9 T7.
   - **What’s wrong:** The hermes‑native backend may issue up to 8 concurrent model calls through Hermes’s existing per‑provider HTTP clients. Those clients may have limited connection pools, per‑key rate limits, or token‑bucket throttles that would be exhausted by a sudden burst. A subagent who naïvely gathers 8 calls could hit connection errors or 429s that look like transient failures, leading to flaky behaviour.
   - **Concrete fix:** Either (a) verify that all provider clients are safe for 8 simultaneous connections and add an assertion note in the plan, or (b) introduce a `asyncio.BoundedSemaphore` (value configurable, default 4) around the provider calls, catching `asyncio.TimeoutError` and per‑provider retry logic. At minimum, document the risk as a known limitation.

4. **`analysis_models` auto‑population rule is missing**
   - **Where:** §5 (`analysis_models: []` – “auto‑populate from fallback chain”), §9 Q10.
   - **What’s wrong:** When the user omits `analysis_models` (or the config is empty), the tool must build a panel. The plan says only “pull 2‑3 models from `model.fallback_providers`.” It doesn’t answer: how many? First N? Distinct or can they repeat? Which models from a chain that might be ordered by priority? A subagent will guess, leading to unpredictable panel composition.
   - **Concrete fix:** Specify the rule exactly, e.g.: “Take the first 3 unique model identifiers from the ordered `model.fallback_providers` list (skipping duplicates). If fewer than 2 are available, refuse with a clear error. The primary model of the fallback chain becomes the first panel member.” Add this to §5.

5. **Runner’s access to the judge model client is undefined**
   - **Where:** §4.2 step 4 (“run the judge separately”), §8.2 (*auxiliary_client extension*).
   - **What’s wrong:** The runner (in `tools/fusion/runner.py`) needs to invoke a judge model using the same infrastructure that the hermes‑native backend uses. The plan says the backend uses a `panel_call()` helper, but the runner must also call a single model for judging. How does the runner obtain the callable? Without a clear injection point (constructor argument, global import, or context), the runner is unimplementable.
   - **Concrete fix:** Add a `call_model: Callable[..., Awaitable]` parameter to the `FusionRunner` constructor. The tool’s entry point (the registered `openrouter_fusion` function) obtains this callable from Hermes’s auxiliary client plumbing and passes it to both the runner and the backend.

TIER 2 (will cause confusion or rework if not addressed)
--------------------------------------------------------

6. **Per‑panel‑member fallback and model uniqueness**
   - **Where:** §9 Q3 (“fallback chain – apply it per panel member”), §9 Q6.
   - **Concern:** If Claude fails for panel member 1 and the fallback tries DeepSeek, the panel might end up with two DeepSeek instances (or worse, the whole panel could collapse to a single model after cascading fallbacks). The plan hasn’t decided whether to enforce model diversity during fallback.
   - **Fix:** Decide and document: “After fallback, if the resulting model ID already exists in the panel, skip that fallback step and mark the member as failed. The panel must consist of distinct model identifiers.” This preserves the “different perspectives” goal.

7. **Judge‑strategy fallback when curator’s provider is unavailable**
   - **Where:** §3 (judge_strategy `auxiliary-curator`), §9 Q4, §9 Q8.
   - **Concern:** If the user selected `auxiliary-curator` but has not configured the curator slot, or the curator model’s provider keys are missing, the plan gives no clear fallback. The subagent would likely raise an error, degrading the experience.
   - **Fix:** Define a two‑step fallback: try curator → if not configured or authentication fails, fall back to `outer-model` (the model that invoked the tool). If that also fails, skip the structured analysis and return raw responses. Document this order in §4.2 or §5.

8. **Empty `fallback_providers` error experience**
   - **Where:** §9 Q9.
   - **Concern:** When the auto‑population would yield an empty list, the plan says “the tool would refuse.” No error message or exception type is specified – the subagent might raise a generic `ValueError` that the outer model cannot interpret.
   - **Fix:** Define a dedicated `FusionConfigurationError` with a clear, user‑visible message (“Cannot create a panel: no models found in `model.fallback_providers`. Please configure at least 2 model providers.”). Mention this in §5.

9. **Recursion‑guard placement – mismatch between §8.1 and §4.4**
   - **Where:** §8.1 (“Wrap the tool dispatcher call in set/reset”) vs §4.4 (“runner increments on entry, resets in finally”).
   - **Concern:** A subagent reading §8.1 would try to modify the generic tool dispatcher inside `run_agent.py`, wrapping *every* tool call. That’s wrong and fragile. The real guard must be inside the fusion runner itself.
   - **Fix:** Rewrite §8.1: “`run_agent.py` *only* defines the `_fusion_depth` ContextVar (module‑level). The fusion runner (`tools/fusion/runner.py`) imports it and manages the increment/reset around its execution. No dispatcher wrapping is needed.”

10. **`max_tool_calls` semantics for hermes‑native**
    - **Where:** §3 schema (`max_tool_calls` description), §2 out of scope (web‑search disabled).
    - **Concern:** The parameter says “Max tool‑calling steps the panel/judge models can make.” However, the hermes‑native backend’s panel members are plain LLM calls without tool access. A subagent might try to instrument tool‑use iteration when it’s unnecessary, or pass the parameter to the model call where it is ignored, causing warnings.
    - **Fix:** Add a note: “For `hermes-native`, `max_tool_calls` is ignored (panel members have no tool calling; v0.1 disables web tools). The parameter is forwarded to the `openrouter-fusion` backend only.” Or remove it from the shared schema and attach it to the backend config.

11. **Configurable judge prompt – config key missing**
    - **Where:** §9 Q4, §4.5 fixed prompt.
    - **Concern:** The plan says v0.1 ships a default prompt + a config override, but never states the config key (e.g., `fusion.judge_prompt` or `fusion.judge_prompt_file`). The subagent would have to invent a key, risking inconsistency with future additions.
    - **Fix:** Add a configurable prompt variable `fusion.judge_prompt_override` (string) in §5. If empty, use the hard‑coded default. Document that it will be evaluated as an f‑string with `{N}` replaced.

12. **`check_requirements` for hermes‑native**
    - **Where:** §4.1, §5, §9 Q9.
    - **Concern:** `HermesNativeBackend.check_requirements()` currently always returns `True`, but if the user has no providers configured the tool will fail later with a potentially confusing error. A pre‑check would give a better error early.
    - **Fix:** Change the implementation to return `False` (or raise) if `model.fallback_providers` is empty or yields fewer than 2 usable models. Ensure the tool catches this and reports a helpful message.

13. **Fixture format for runner tests**
    - **Where:** §7 (recorded fixtures), `tests/fixtures/fusion-*.json`.
    - **Concern:** The fixtures must reflect the `PanelResponse` shape (with `responses`, `failed_models`, `analysis`, etc.), but the plan doesn’t specify the exact JSON schema. A subagent might store raw provider responses that don’t map cleanly.
    - **Fix:** Provide a sample fixture structure in an appendix or the test docstring, matching the `PanelResponse` dataclass fields. Example:
      ```json
      {
        "responses": [{"model": "...", "content": "..."}],
        "failed_models": [...],
        "analysis": { "consensus": [...], ... }
      }
      ```

14. **Tool name decision – implementer cannot resolve it**
    - **Where:** §3 (tool name), §9 Q1, §9 Q10.
    - **Concern