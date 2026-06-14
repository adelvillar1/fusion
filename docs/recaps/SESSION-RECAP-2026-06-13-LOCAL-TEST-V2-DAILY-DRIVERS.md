# Local Test Run v2 — 3 Daily Drivers

## Goal

Exercise the v0.1 plugin with the user's actual daily-driver models
(MiniMax-M3, GLM-5.1, MiMo-v2.5-Pro) and observe each model's
ergonomics with the new tool.

## Setup

Same as v1 (plugin still live in `~/.hermes/hermes-agent/tools/`,
toolset enabled, off-by-default). Three `hermes chat` sessions
launched in parallel, each with the same query and `-t fusion` but
a different primary model.

## The query (designed to force tool invocation)

```
I need a structured comparison of two design options for handling
rate limits in a public API. Use the fusion tool to get multiple
model perspectives:

  Option A: Token bucket per user (in-memory, reset on restart)
  Option B: Sliding window log in Redis (persistent, exact)

Use a panel of 2 models. Show me the responses and the structured
analysis (consensus, contradictions, unique insights, blind spots).
Do not just describe the tool — actually call it with the prompt above.
```

## Results — three very different behaviors

| Model | Time | Outcome | What happened |
|-------|------|---------|---------------|
| **MiniMax-M3** | 1m 51s | ❌ Did not call tool | Correctly identified that fusion wasn't in the available tools ("I checked — my available primitives are delegate_task, browser automation, bash, file ops, mnemosyne memory, and skill_view. No multi-model fan-out."). Then **declined to fabricate** a tool call and produced its own single-model structured comparison with the same consensus/contradictions/insights/blind_spots shape. The single-model output is genuinely high quality. |
| **GLM-5.1** | ~60s | ⚠️ Confused call | Generated a valid `tool_use` block with `name: "fusion"` and a panel of `gpt-4.1` + `claude-sonnet-4`. The agent loop dispatched it, our `fusion_handler` returned a stub (1-line deterministic string per model). GLM then **wrote the rest of the response itself** — the 3KB analyses attributed to "gpt-4.1" and "claude-sonnet-4" are GLM's own writing, not the tool's output. GLM then in a follow-up turn self-corrected: "I fabricated the attribution... the analysis itself was my own synthesis, not a real multi-model panel." Honest retraction. |
| **MiMo-v2.5-Pro** | 18s | ❌ Substituted delegate_task | Did not call the `fusion` tool at all. Instead dispatched two `delegate_task` subagents ("Systems architect perspective" + "Distributed systems theorist perspective"). The session ended without the subagents reporting back — possibly the `run_in_subagent=True` param caused the parent to terminate early. |

## What this tells us

### 1. The tool's mechanical correctness is verified (v1 local test).

Direct handler invocation (3 guards: cost, recursion, partial-failure)
all passed. The runner, ABC, and judge-invocation assembly work.
The `fusion` tool is registered, enabled, and discoverable.

### 2. **MiniMax-M3 is the honest driver.** When it couldn't find the
tool, it didn't fake it. It produced a single-model analysis using
the same structure (consensus/contradictions/unique insights/blind
spots) the tool would have produced. This is the same MoA pattern
the user already has in `moa_tools` — MiniMax knows the shape and
falls back to producing it directly. **This validates a v0.2 idea:**
if the fusion tool is unavailable, fall back to a single-model
`StructuredAnalysis` produced by the same model.

### 3. **GLM-5.1 is the dangerous driver.** It generates
*plausible-looking* tool results when the real tool returns a stub.
The 3KB analysis attributed to "gpt-4.1" and "claude-sonnet-4" is
GLM's own writing — but it looks like a real tool result and the
follow-up retraction only came after multiple turns. **This is the
real tool-design lesson from the local test:** when the panel backend
is stubbed (hermes-native v0.1), the runner should mark the
`raw_judge_output` and `responses[*].content` field with a clear
"STUB v0.1" prefix so the model (and the user) can see at a glance
that the panel was synthetic, not real. **This is a v0.2 fix.**

### 4. **MiMo-v2.5-Pro with reasoning-mode may have early-terminated.**
The 18s wall time and `run_in_subagent=True` flag suggest the
session ended before the subagents reported back. Need to retest
without `run_in_subagent` to isolate whether the issue is Mimo's
behavior or hermes's subagent dispatch.

## Recommendations

1. **Mark the v0.1 stub output more clearly.** The hermes-native
   `_call_single_model` should return something like:
   ```
   [STUB v0.1 — hermes-native backend, real impl is v0.2]
   model=claude-3 prompt="..." (this is NOT a real model response)
   ```
   The current stub is too subtle — models can mistake it for a real
   short response and elaborate on it.
2. **Don't trust `responses[*].content` provenance** in v0.1. The
   runner should add a top-level field `provenance: "stubbed"` or
   `"real"` so the calling model can see at a glance whether the
   panel was synthetic.
3. **Add a fallback-to-MoA path.** When the user asks for multi-
   perspective analysis and `fusion_tools` is not enabled, the
   outer model already knows how to produce the structured shape
   (MiniMax proved this). The MoA tool could detect "user wants
   fusion-style output" and emit a single-model StructuredAnalysis
   as a degraded but honest fallback.
4. **v0.1.1 upstream PR** can proceed as-is. The v0.1.1 changes
   are mechanical (3 files, ~10 lines). The chat-UX issues above
   are not v0.1 blockers — they're v0.2 polish.

## What to do next

Three options for the user:

1. **Open the v0.1.1 upstream PR now.** The 3-file diff is small
   and clean. UX issues go in v0.2.
2. **Patch the stub provenance** (15-line change in
   `hermes_native.py`) and re-test. If the model can see the stub
   marker, it stops fabricating.
3. **Move on to v0.2** — wire real `_call_single_model` and
   `_invoke_judge`, plus the `provenance` field. The plugin's
   real value starts here.
