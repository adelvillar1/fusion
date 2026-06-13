# Cross-LLM Review — Pass 1 (Gap-Analysis Lens)

**Provider:** DeepSeek-v4-pro
**Model:** deepseek-v4-pro
**Latency:** 80348ms
**Tokens in/out:** 4001/8192
**Error:** none

---

## Tier 1 (blocker for plan approval — must fix before delegation)

1. **Cost estimates in §6 are unrealistic and will cause misguided decisions**
   - **What:** The "$0.30/call for 3 models, –3/call for 8" numbers are off by at least a factor of 5–10.
   - **Where:** Section 6, Cost model.
   - **Why:** If the author believes these numbers, they will set defaults and cost guards that are 5–10× too low, leading to budget overruns on real usage. A subagent implementing the guard with those assumptions might set a `max_panel_size` budget that is too permissive.
   - **Concrete fix:** Re‑estimate with current frontier model pricing (e.g., Claude 3 Opus $15/$75 per MTok, GPT-4o $5/$15, Gemini 1.5 Pro $3.5/$10.5). Mark the estimates as **speculative** and clearly note that real costs may be 5–10× higher. Reflect this in the cost guard so it doesn’t accidentally approve a panel of 8 models costing $10–15/call.

2. **Local recursion guard via `HERMES_FUSION_DEPTH` is undefined, unnecessary, and fragile**
   - **What:** The plan invents a local env‑var guard that is not needed (the server‑side depth header is sufficient) and is left with no concrete implementation.
   - **Where:** §4 “Recursion guard” paragraph and acceptance criteria bullet 4.
   - **Why:** The spec says “set by `run_agent.py` when entering a panel,” but the tool is a library call; `run_agent.py` has no mechanism to inject an env var around a tool invocation without tight, brittle coupling. The guard will not work as described, and any test that sets the env var manually will pass but the real integration will remain unguarded (or error‑prone).
   - **Concrete fix:** Remove the local `HERMES_FUSION_DEPTH` entirely. Rely solely on the `x-openrouter-fusion-depth` header sent on the outer request. The server‑side depth limit is the canonical recursion guard for `openrouter:fusion`. Delete the acceptance criterion that depends on it.

3. **Provider plugin stub in v0.1 contradicts the opt‑in, off‑by‑default posture and introduces un‑tested, dangerous surface**
   - **What:** Shipping `plugins/model-providers/fusion/` as a primary‑model provider exposes fusion outside the tool guard, bypasses the cost guard, and has zero behavioral tests.
   - **Where:** Scope §2 “In scope … provider‑plugin stub,” open question 5, acceptance criteria 8.
   - **Why:** Exposing `openrouter/fusion` as a selectable model means an agent can route *every* turn through fusion, potentially 4× the estimated cost with no warning. The plan’s philosophy is “off by default, opt‑in toolset,” but a provider plugin is an always‑available model choice that cannot be gated by the toolset toggle. It introduces a second, unchecked entrypoint with no recorded‑fixture coverage.
   - **Concrete fix:** Move the provider plugin to **v0.2**. Remove it from v0.1 scope, the acceptance criteria, and the “open questions” lean. Keep the integration points limited to the tool and three upstream hermes‑agent changes.

4. **Wire protocol header `x-openrouter-fusion-depth` may not match the real API → recursion guard is at risk of being no‑op**
   - **What:** The plan hardcodes a single‑value header `x-openrouter-fusion-depth: 1` but the actual OpenRouter Fusion API may require a JSON object in `x-openrouter-fusion` (e.g., `{"depth": 1}`).
   - **Where:** §4 “Wire protocol” (the HEADERS block).
   - **Why:** If the header format is wrong, the OpenRouter server will not recognise the depth limit, and a panel model’s tool call could successfully spawn another fusion request—causing unbounded recursion and cost. This is a critical wire‑format correctness issue.
   - **Concrete fix:** Verify the exact header format from the official OpenRouter Fusion documentation. Update the spec to match. If the format is not yet stable, explicitly note the risk and add a unit test that asserts the request header value against the known format.

## Tier 2 (significant — fix in this iteration)

5. **No test scenario for partial panel failures (some models succeed, others fail)**
   - **What:** The plan covers only “judge‑degradation” (all models succeed, judge fails) and “hard failures” (complete error). It omits the case where 2 of 3 panel models fail but the third returns a response, and the judge may still produce analysis.
   - **Where:** §7 Test strategy, missing fixture scenario.
   - **Why:** A real production tool will encounter partial failures. Without a recorded fixture for this, the tool’s passthrough might misinterpret the partial‑failure JSON and deliver a malformed result to the outer model, causing agent confusion.
   - **Concrete fix:** Add a recorded fixture (`fixtures/openrouter-fusion-partial-success.json`) that includes a mixture of `status: "ok"` models and some with `status: "error"`. Write a unit test that confirms the tool returns the raw OpenRouter JSON unchanged and does not raise an exception.

6. **`force` parameter’s cost‑guard‑override role is untested**
   - **What:** The plan states that `force` (which maps to `tool_choice: "required"`) also overrides the `max_panel_size` cost guard. Acceptance criteria 6 only mentions “refuses … unless overridden” but doesn’t tie it to `force`.
   - **Where:** §5 (config comment), acceptance criteria item 6.
   - **Why:** If `force` doesn’t actually implement the bypass in code, a user with a legitimate 9‑model panel cannot proceed. This is the only way to allow a panel larger than the guard, so the path must be exercised.
   - **Concrete fix:** Add a unit test: when `analysis_models` length > `max_panel_size` and `force=True`, the tool proceeds without an exception. Reword the acceptance criterion to “Cost guard refuses … unless `force=True` is passed.”

7. **No prescription for how the tool communicates with OpenRouter (HTTP client selection)**
   - **What:** The plan says “thin pass‑through” but never specifies which HTTP library or client to use (raw `httpx`, the existing OpenRouter provider’s session, etc.).
   - **Where:** Implicit in §4—requires an HTTP call but no implementation guidance.
   - **Why:** Without guidance, an implementer might spin up a new `httpx` client with separate retry/error/rate‑limit logic, diverging from the rest of the platform. This leads to duplicated connection pools and inconsistent error surfacing.
   - **Concrete fix:** Explicitly state: “Reuse the OpenRouter provider’s authenticated `httpx.AsyncClient` (or equivalent) that is already configured with `OPENROUTER_API_KEY`, base URL, and retry middleware. If reusing is not possible, document the required client config here.”

8. **Unclear where the tool reads its configuration (path to `config.yaml`)**
   - **What:** The config section says “Configuration via `config.yaml` under `fusion.*`” but doesn’t state whether this is the repo‑level `config.yaml` or the Hermes config directory.
   - **Where:** §5.
   - **Why:** A naive implementer might assume a local `config.yaml` in the tool’s directory, causing it to miss the user’s settings. The tool must integrate with Hermes’s configuration loading.
   - **Concrete fix:** Clarify: “The tool reads from the same `config.yaml` as the Hermes Agent (the one passed to the tool’s `__init__` via the `Config` object). The `fusion.*` keys are defined in the agent’s config spec. Add a `FusionToolConfig` pydantic model that validates those keys.”

9. **Upstream Hermes‑Agent changes listed in §8 are not in‑repo and could confuse acceptance**
   - **What:** The three integration changes in hermes‑agent (`model_tools.py` and `AGENTS.md`) are required for the tool to be used after installation, but they are not part of this PR.
   - **Where:** §8.
   - **Why:** If a reviewer thinks these must be included in the same PR, they will block until the changes are made, but the hermes‑agent repo is separate. The plan must separate the boundaries.
   - **Concrete fix:** Add a sentence: “These three changes must be made in a separate PR against the hermes‑agent repository. They are *not* required to ship the tool in this repo; they are integration steps for downstream adopters.”

10. **Default model IDs are pinned, not using OpenRouter’s quality tiers**
   - **What:** The default panel hardcodes `"anthropic/claude-opus-latest"`, `"openai/gpt-latest"`, `"google/gemini-pro-latest"`. These are convenient aliases, but OpenRouter might retire or rename them.
   - **Where:** §5.
   - **Why:** Pinned IDs could break silently when aliases are removed, requiring a config update. Using a quality preset (e.g., `"quality"`) would automatically track the best available models.
   - **Concrete fix:** Assess whether `"quality"` or `"balanced"` presets are supported inside fusion’s `analysis_models`. If so, switch the default to `["openrouter/auto"]` or a tier syntax, with a fallback list of exact IDs only if preset is not available.

## Tier 3 (nice-to-have — file as follow‑up)

11. **Web‑tools passthrough is out of scope but mentioned in passing; could confuse users**
    - Suggest adding a comment in the tool description that