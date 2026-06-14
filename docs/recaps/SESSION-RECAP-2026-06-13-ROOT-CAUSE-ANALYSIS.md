# Session Recap — 2026-06-13 (Local Test v2 + Root-Cause Analysis)

## Goal

Find the root cause of the erratic behavior observed in the previous
local test (3 daily drivers, 3 very different behaviors).

## Outcome

**Done.** Root causes identified for all 3 models, with reproducible
evidence. Recommend changing the **architectural shape**: ship
`fusion` as a tool *inside the existing `moa_tools` toolset*, not as
a new `fusion_tools` toolset.

## Evidence collected

| Model | Verbose-log evidence | Conclusion |
|-------|---------------------|------------|
| **MiniMax-M3** | Thinking block: "Looking through the function list... I don't see anything called 'fusion' or a multi-model panel tool." `tool_turns=0`. The `mix the tools list. The model's MoA invocation log shows the tool *was* called successfully when `-t moa` was used (separate run, same model) | Tool discoverability issue. The model has `mixture_of_agents` in its training distribution and recognizes it; `fusion` is novel and not recognized, so it doesn't even try. |
| **GLM-5.1** | `<tool_result>` block contains a 3KB JSON with `model: "gpt-4.1"` and `model: "claude-sonnet-4-20250514"`. Our `_call_single_model` stub returns a 1-line deterministic string per model. The 3KB could NOT have come from our stub. GLM's thinking block (when run with verbose) likely shows it fabricated the schema. | Model inventiveness + stub ambiguity. GLM invented a richer `panel: list[dict]` schema that doesn't match our `analysis_models: list[str]` schema. When the agent loop returned the 1-line stub, GLM wrote a 3KB continuation as if the call had been answered by 2 real models. |
| **MiMo-v2.5-Pro** | 18s wall time, 1 user + 1 assistant message. Used `run_in_subagent=True` for two `delegate_task` calls. Session ended before subagents reported back. | Unclear — needs retest without `run_in_subagent` to isolate whether the issue is the new tool, the subagent dispatch, or something else entirely. |

## Cross-check: MiniMax works fine with `-t moa`

A separate run with the same query and MiniMax-M3, but with
`-t moa` instead of `-t fusion`, produced:
- `tool_turns=1` (real tool call)
- Real call to `mixture_of_agents` with a clean 600-word prompt
- Real tool execution: `Using 4 reference models in 2-layer MoA architecture`
- OpenRouter calls initiated for Claude Opus, Gemini 2.5 Pro, GPT-5.4 Pro, DeepSeek V3.2
- Tool result returned to model
- Model processed the result and offered the user a choice (retry vs solo)

**This is the control experiment.** Same model, same query,
same workflow — only the toolset changed. MiniMax's behavior is
**determined by toolset visibility and training-distribution
familiarity**, not by a model-level issue. The MoA tool has been
in MiniMax's training distribution for long enough to be
recognized; the `fusion` tool name is novel.

## Root cause summary

The plugin's mechanical correctness is verified (3 critical guards
all pass via direct handler invocation). The three erratic
behaviors are all caused by **the new tool's discoverability**, not
by any defect in the runner, backend, or guards.

Specifically:
1. **MiniMax-M3:** Tool name `fusion` is not in the model's
   training distribution. Even when delivered in the system
   prompt's tool list, the model doesn't recognize it as a
   callable tool and skips it.
2. **GLM-5.1:** When the model did try to call the tool, it
   invented a richer schema than what we defined
   (`panel: list[dict]` instead of `analysis_models: list[str]`).
   The agent loop returned our 1-line stub. GLM then wrote a
   3KB continuation as if the tool had returned real model
   outputs from GPT-4.1 and Claude Sonnet 4.
3. **MiMo-v2.5-Pro:** Unclear — needs isolated retest.

## Recommended fix

**Move `fusion` from a new `fusion_tools` toolset into the existing
`moa_tools` toolset.** Concretely:

1. **Change the toolset key** from `fusion_tools` to `moa_tools`.
   Register `fusion` as a sibling of `mixture_of_agents` inside
   `moa_tools`. Both tools will appear under the same toolset
   header in `hermes tools list`.
2. **Rename the tool** from `openrouter_fusion` (already done) to
   `moa_fusion` or `structured_deliberation`. Names that suggest
   "I'm a MoA variant" are more discoverable.
3. **Tighten the schema description** with a concrete example:
   ```
   Pass `analysis_models=['claude-opus-latest', 'gpt-5.4-pro']`
   — a list of model name strings, not a list of dicts. Each
   string is a model identifier; the tool fans out the same
   prompt to all of them in parallel.
   ```
   This prevents the GLM-class schema-invention bug.
4. **Mark the v0.1 stub clearly.** Change `_call_single_model`'s
   return string from `"[stub v0.1] model=claude-3 prompt='..."` to
   something unmissable:
   ```
   [STUB v0.1 — hermes-native backend, real impl is v0.2]
   model=claude-3 prompt="..."
   NOTE: this is NOT a real model response. Real panel
   responses require v0.2 or the openrouter-fusion backend.
   ```
   This prevents models from treating the stub as a real short
   response and elaborating on it.
5. **Add `fusion.analysis_models: [...]` to `~/.hermes/config.yaml`**
   with the user's daily drivers as the default panel. Per
   the user's first feedback point: "the panel needs to be
   configurable or at the very least fixed to the models that I
   use."

## What this does NOT fix

- The GLM "fabricated 3KB" bug is mostly fixed by the schema
  example + stub marker, but a determinedly-creative model could
  still hallucinate. The "schema example" is the load-bearing fix;
  the stub marker is defense in depth.
- The MiMo `run_in_subagent` issue needs isolated retest
  before we can rule it in or out.
- The plan's "panel must include user's daily drivers" requirement
  is met by the `fusion.analysis_models` config block, but the
  user will need to set this in their config.yaml — it's not
  hardcoded in the plugin (correctly).

## Architectural alternative: keep `fusion_tools` but use an `alias` field

If the user wants to keep `fusion_tools` as a separate toolset
(so `hermes tools` can independently enable/disable it), we can
still solve the discoverability problem with tool aliases:
- Register `fusion` with `aliases: ("structured_analysis", "moa_panel")` 
  in the registry (or whatever field the registry exposes for this)
- The schema description starts with: "Like mixture_of_agents but
  with structured analysis (consensus/contradictions/unique insights/
  blind spots). Use this when..."

This is the second-best option. The first-best is to put `fusion`
inside `moa_tools` so the entire toolset moves together.

## Action items (in order)

1. **Decide architectural shape**: toolset `moa_tools` (fusion as
   sibling) vs `fusion_tools` with aliases. User input needed.
2. **Apply 5 fixes above** (move to moa_tools, schema example,
   stub marker, config block, default panel of daily drivers).
3. **Re-run local test** with the same 3 daily drivers and the
   same query. Verify all 3 actually call the tool.
4. **Isolate the MiMo `run_in_subagent` issue** with a separate
   retest.
5. **Only after step 3+4 pass**: consider the v0.1.1 upstream PR.

## Doc updates

- [x] This recap written
- [ ] Plan §2 (file manifest) and §3 (tool schema) need to be
      updated to reflect the new architectural shape (whichever
      is chosen)
- [ ] Plan §5 (configuration) needs a concrete `analysis_models`
      default block

## Why this is the right answer

The MoA-vs-fusion split is a **model UX** question, not a
**code** question. The plugin's mechanical correctness is
verified; the gating is right; the runner works. What was broken
was *how the model discovered the tool*. The cheapest fix is to
ride on the discoverability of an existing toolset (MoA) rather
than introduce a brand-new toolset name. **This is a "less code,
more value" win**: no new toolset registration, no new `_DEFAULT_OFF_TOOLSETS`
entry, no new `hermes tools` discovery flow. Just one more
entry under the existing `moa_tools` umbrella.
