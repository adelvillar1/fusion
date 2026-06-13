# AGENTS.md — for AI coding assistants working on Fusion

This file is loaded automatically by coding agents (Hermes, Claude Code, etc.)
that operate in this repo. It is **additional** to the human-readable
`CLAUDE.md` — it focuses on things only the agent needs.

## Read these first (in order)

1. `CLAUDE.md` — project context, branch topology, "today's state" headline
2. `docs/plans/2026-06-13-fusion-tool-design.md` — the v2 design contract
   (backend-pluggable, hermes-native default)
3. `docs/plans/archive/2026-06-13-fusion-tool-design-v1-ORwrapper.md` —
   the v1 plan, useful as historical context for what was tried and why
4. `docs/MOA-PARITY-MATRIX.md` — what fusion inherits from vs diverges
   from the built-in `moa` toolset
5. `docs/OPENROUTER-FUSION-REFERENCE.md` — snapshot of OpenRouter docs
   (only relevant if you're working on the `openrouter-fusion` backend)

## Don't

- Don't add OpenRouter as a hard dependency. The `hermes-native` backend
  is the v0.1 default and must work with `OPENROUTER_API_KEY` unset.
- Don't bake API keys, model names, or panel sizes into module-level
  constants. Everything configurable goes in `config.yaml` under
  `fusion.*` and the tool reads from there.
- Don't add a new env var for non-secret config. Use `config.yaml` only.
- Don't add a new core tool to Hermes without first checking whether the
  existing `moa` toolset already covers the use case. Fusion's value is
  **structured analysis**, not "another way to call multiple models."
- Don't write tests that hit live APIs. Use recorded fixtures or
  `unittest.mock`.
- Don't ship the v0.1 plan with the `force` parameter. Drop it. The
  agent's tool call IS the user's intent.

## Do

- Trace every code change back to a section in the v2 design plan. If
  the design doesn't cover it, update the design first, then code.
- After every non-trivial session, write a recap at
  `docs/recaps/SESSION-RECAP-YYYY-MM-DD-<slug>.md` and update
  `CLAUDE.md`'s "Today's state" bullets.
- Mirror the Hermes tool convention: `tools/<tool_name>_tool.py` calls
  `registry.register(name=..., toolset=..., schema=..., handler=...,
  check_fn=...)`. The toolset key for v0.1 is `fusion_tools`.
- For the backend package, follow the ABC pattern: a base class with
  abstract methods, concrete implementations register themselves.
  New backends add themselves to the registry without touching the
  runner.

## Reference: similar work in Hermes

- `~/.hermes/hermes-agent/tools/mixture_of_agents_tool.py` (542 lines) —
  the closest sibling. Read before implementing. The `hermes-native`
  backend in v2 should reuse its `asyncio.gather` pattern and
  `_run_reference_model_safe` retry logic.
- `~/.hermes/hermes-agent/agent/auxiliary_client.py` — the canonical
  path for "call a single model with the right plumbing." The
  `hermes-native` backend fans out via this client. May need
  extension to expose `asyncio.gather` over a list of model IDs.
- `~/.hermes/hermes-agent/model_tools.py:_DEFAULT_OFF_TOOLSETS` —
  where `fusion_tools` must be added (v0.1.1, not v0.1).
- `~/.hermes/hermes-agent/cron/scheduler.py:~line 90-100` — the recent
  PR #14xxx (Norbert's $4.63 moa run) is the precedent for off-by-default
  cost defense.
