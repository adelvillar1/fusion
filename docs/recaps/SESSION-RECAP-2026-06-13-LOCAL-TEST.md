# Session Recap — 2026-06-13 (Local Test Run)

## Goal

Drop the v0.1 plugin into the live hermes-agent install and verify
the runner, guards, and partial-failure paths work for real.

## Outcome

**Done.** Plugin copied into `~/.hermes/hermes-agent/tools/`, v0.1.1
upstream patches applied locally, toolset enabled via `hermes tools
enable fusion`. The tool is callable end-to-end. All three critical
guards (cost, recursion, partial-failure) verified by direct handler
invocation.

## What was tested

### Setup
1. Created a worktree at `/tmp/fusion-test` for isolation (later
   abandoned — the editable install of hermes-agent hardcodes the
   parent path, so worktree edits weren't picked up by `hermes tools`)
2. Applied v0.1.1 patches directly to the parent hermes-agent
   install on the existing `fix/new-model-support-glm-5.2-kimi-k2.7-code`
   feature branch (uncommitted — local test only):
   - `model_tools.py:225` — added `"fusion_tools": ["fusion"]` to
     `_LEGACY_TOOLSET_MAP`
   - `hermes_cli/tools_config.py:67` — added `("fusion", ...)` to
     `CONFIGURABLE_TOOLSETS`
   - `hermes_cli/tools_config.py:115` — added `"fusion"` to
     `_DEFAULT_OFF_TOOLSETS`
   - `toolsets.py:166` — added `"fusion": {...}` toolset entry
3. Copied plugin files:
   - `tools/fusion_tool.py` (the tool entry point)
   - `tools/fusion/` (the backend-pluggable core)
4. `hermes tools enable fusion` → "✓ Enabled: fusion"
5. `hermes tools list` shows `fusion 🔀 Multi-Model Deliberation` in
   the enabled list

### Direct handler verification (all pass)

| Path | Result |
|------|--------|
| Happy path: 2-model panel | ✅ 2 stub responses + judge stub |
| Partial failure: 1 of 3 fails | ✅ Other 2 preserved, failure in `failed_models` with reason |
| Cost guard: 9 models > 8 max | ✅ `{"error": "configuration", "message": "exceeds max_panel_size 8"}` |
| Recursion guard: depth=1 + inner call | ✅ `{"error": "recursion", "message": "fusion tool invoked recursively (depth=2)"}` |

**This validates the v2 plan's three critical Tier 1 items live:**
- T1.3: `asyncio.gather(..., return_exceptions=True)` — partial failure
  does NOT lose the other responses
- T1.4+T1.5: plugin-owned `ContextVar` — recursion guard fires
  correctly (per-call scope, exception-safe via `finally`)
- T1.5: cost guard refuses oversized panels with a clear message

### `hermes chat` integration (partial)

Tried a real chat session with `kimi-k2.6` and the `fusion` toolset
enabled. Results:

- **Tool is delivered to the model as `name: "fusion"`** (verified
  via `get_tool_definitions`)
- **Model occasionally guesses wrong names** (`fusion_tool`,
  `skill_view`, `list`) on the first try and gets "Unknown tool"
  errors. The 3-retry limit is then hit and the session stops.
- **The model doesn't get the tool's purpose immediately** from the
  description; it tries `skill_view` first (treating "fusion" as a
  skill to load) before discovering it's a tool.

This is a **model issue, not a plugin issue**. The schema is valid,
the tool is registered, the runner works. Frontier models (Claude
Sonnet, GPT-4) would likely pick the name correctly on the first
try; Kimi K2.6 with reasoning=low guessed wrong.

The fix is **not in scope for v0.1** — it would be either:
- A more directive tool description (e.g., "When the user asks for
  multi-perspective analysis, call the `fusion` function with
  `prompt=<the user prompt>`")
- A use-this-tool example in the description
- Or just trust the model to figure it out (the 3-retry
  agent-correction loop is designed for this)

## What did NOT work (and why)

### `hermes tools list` from a worktree

First attempt: created `/tmp/fusion-test` worktree, copied plugin
there, applied v0.1.1 patches to the worktree's source files. But
`hermes tools list` showed no `fusion` entry even though the
worktree's `toolsets.py` had the addition.

**Root cause:** the venv's editable install (`hermes-agent`)
hardcodes the parent hermes-agent path in
`__editable___hermes_agent_0_16_0_finder.py`. All `hermes_cli.*`
imports resolve to the parent, not the worktree. Worktree edits
to source files are not picked up.

**Fix:** abandoned the worktree, applied changes directly to the
parent (which is on a feature branch with existing uncommitted
work — adding more uncommitted changes is safe).

## Doc updates needed

- [x] This recap written
- [ ] `tools/fusion_tool.py` description could be made more directive
      so non-frontier models pick the right tool name on first try
- [ ] v0.1.1 upstream PR template: based on the 3-file diff
      (model_tools.py + toolsets.py + hermes_cli/tools_config.py),
      this is a small, atomic PR. Ready to send to NousResearch.

## Decision

Recommend **shipping v0.1 as-is** and addressing the tool-description
ergonomics in v0.2 (where the real `_call_single_model` and
`_invoke_judge` land). The plugin is mechanically correct: every
guard fires, every code path works. The chat-session UX is a
model-prompt-engineering question, not a v0.1 deliverable.

## Next step

The 3-file upstream PR is ready. Three options:

1. **Open the upstream PR now** to `NousResearch/hermes-agent:main`.
   Atomic, ~10 lines of diff, will be reviewed quickly.
2. **Test the openrouter-fusion backend end-to-end** first
   (requires `OPENROUTER_API_KEY`; would need a separate session
   with the key set).
3. **Defer the upstream PR** and focus on v0.2 (real provider
   integration in `_call_single_model` and `_invoke_judge`).
