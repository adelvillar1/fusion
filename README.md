# Fusion — Hermes Agent Extension

Multi-model deliberation as a Hermes Agent tool. Wraps OpenRouter's
`openrouter:fusion` server tool so the calling agent can spin up a panel of
models, have a judge compare their responses, and receive structured analysis
(consensus / contradictions / unique insights / blind spots) instead of a
single synthesized answer.

**Companion to** the built-in `moa` (Mixture-of-Agents) tool — fusion returns
*structure*, MoA returns *a single best answer*. Pick at the call site.

## Status

**Stage:** Design / pre-implementation. The plan in
[`docs/plans/2026-06-13-fusion-tool-design.md`](docs/plans/2026-06-13-fusion-tool-design.md)
is the contract that drives the build. No runtime code yet — only stubs and
fixtures.

## Layout

```
fusion/
├── tools/                              # Tool module(s) for the agent
│   └── fusion_tool.py                  # openrouter_fusion tool (stub)
├── plugins/
│   └── model-providers/
│       └── fusion/                     # ProviderProfile for /fusion router alias
│           ├── __init__.py
│           └── plugin.yaml
├── tests/                              # pytest, stdlib + unittest.mock only
├── fixtures/                           # Recorded OpenRouter responses (VCR-style)
├── docs/
│   ├── plans/                          # Pre-work contracts
│   ├── recaps/                         # Post-work journals
│   ├── architecture/                   # Topical deep dives
│   └── features/                       # Per-feature deep dives
└── scripts/                            # One-off scripts (record-mode against live API)
```

## Install (when shipped)

Drop the `tools/` module and the `plugins/model-providers/fusion/` directory
into `~/.hermes/` (or the user-level plugin path). Restart the agent; the
`fusion` toolset becomes available behind a feature flag (off by default, same
gating as `moa`).

## Why a separate repo?

Hermes Agent is a narrow waist (per its `AGENTS.md` "Footprint Ladder" rule).
Every core tool ships on every API call, so additions are paid for every turn.
This extension is heavy — it has a provider plugin, a tool module, a test
harness with recorded fixtures, and a docs tree — and it costs real money on
each call (3-8 frontier models per fusion). Shipping it as a third-party
plugin in its own repo lets us version it independently of Hermes core, gate
adoption behind `hermes tools`, and let the user opt in per-platform.
