# AGENTS.md — for AI coding assistants working on Fusion

This file is loaded automatically by coding agents (Hermes, Claude Code, etc.)
that operate in this repo. It is **additional** to the human-readable
`CLAUDE.md` — it focuses on things only the agent needs.

## Read these first (in order)

1. `CLAUDE.md` — project context, branch topology, "today's state" headline
2. `docs/plans/2026-06-13-fusion-tool-design.md` — the design contract that
   every implementation decision must trace back to
3. `docs/MOA-PARITY-MATRIX.md` — what fusion inherits from vs diverges from
   the built-in `moa` toolset

## Don't

- Don't add a new core tool without first checking whether the existing
  `moa` toolset already covers the use case. Fusion's value is **structured
  analysis**, not "another way to call multiple models."
- Don't make fusion the default. `_DEFAULT_OFF_TOOLSETS` is the right home
  for it, alongside `moa`, `homeassistant`, and `rl`. The user must opt in.
- Don't bake API keys, model names, or panel sizes into module-level
  constants. Everything configurable goes in `config.yaml` under `fusion.*`
  and the tool reads from there.
- Don't add a new env var for non-secret config. Use `config.yaml` only.
- Don't write tests that hit the live OpenRouter API. Use recorded fixtures
  in `fixtures/` (VCR-style) or `unittest.mock`.

## Do

- Trace every code change back to a section in the design plan. If the
  design doesn't cover it, update the design first, then code.
- After every non-trivial session, write a recap at
  `docs/recaps/SESSION-RECAP-YYYY-MM-DD-<slug>.md` and update
  `CLAUDE.md`'s "Today's state" bullets.
- Prefer extending `~/.hermes/hermes-agent/tools/mixture_of_agents_tool.py`
  patterns over inventing new ones. The two tools should feel like siblings.
- Mirror the Hermes plugin convention: `plugins/<category>/<name>/__init__.py`
  + `plugin.yaml`. The PluginManager auto-discovers both.

## Tool / plugin convention quick reference

From `~/.hermes/hermes-agent/AGENTS.md:786-820`:

```
plugins/model-providers/<name>/
├── __init__.py           # calls register_provider(ProviderProfile(...))
└── plugin.yaml           # name, kind: model-provider, version, description, author
```

```
tools/<tool_name>_tool.py
└── calls registry.register(name=..., toolset=..., schema=..., handler=..., check_fn=...)
```

A new toolset key must be added to `model_tools.py` in the Hermes core. For a
third-party plugin, the convention is: ship the tool in this repo's `tools/`,
and document the toolset key + check_fn in the design plan so a Hermes core
PR can register it on install.

## Reference: similar work

- `~/.hermes/hermes-agent/tools/mixture_of_agents_tool.py` (542 lines) —
  the closest sibling. Read before implementing.
- `~/.hermes/hermes-agent/plugins/model-providers/openrouter/__init__.py` —
  provider plugin shape. Mirror.
- `~/.hermes/hermes-agent/plugins/model-providers/openrouter/plugin.yaml` —
  manifest shape. Mirror.
