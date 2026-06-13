# Fusion — Hermes Agent Extension

Multi-model deliberation as a Hermes Agent tool. Wraps OpenRouter's
`openrouter:fusion` server tool so the calling agent can spin up a panel of
models, have a judge compare their responses, and receive structured analysis
(consensus / contradictions / unique insights / blind spots) instead of a
single synthesized answer.

**Companion to** the built-in `moa` (Mixture-of-Agents) tool — fusion returns
*structure*, MoA returns *a single best answer*. Pick at the call site.

## Status

**Stage:** Design / pre-implementation. Pass 1 cross-LLM review complete;
all Tier 1 and Tier 2 patches applied. See
[`docs/recaps/SESSION-RECAP-2026-06-13-CROSS-LLM-REVIEW.md`](docs/recaps/SESSION-RECAP-2026-06-13-CROSS-LLM-REVIEW.md).

Next: Pass 2 review (buildability lens) → implementation.

## Layout

```
fusion/
├── tools/                              # Tool module(s) for the agent
│   └── fusion_tool.py                  # openrouter_fusion tool (stub)
├── tests/                              # pytest, stdlib + unittest.mock only
├── fixtures/                           # Recorded OpenRouter responses (VCR-style)
├── docs/
│   ├── plans/                          # Pre-work contracts
│   ├── recaps/                         # Post-work journals
│   ├── architecture/                   # Topical deep dives
│   └── features/                       # Per-feature deep dives
└── scripts/                            # One-off scripts (record-mode against live API)
```

The `plugins/model-providers/fusion/` provider plugin is **deferred to
v0.2** per Pass 1 review (T1.6 — unguarded cost-explosion path if a user
selects `openrouter/fusion` as their primary model).

## Install (when shipped)

Drop the `tools/` module into `~/.hermes/tools/` (or the user-level tool
path). Restart the agent. The `fusion_tools` toolset becomes available
behind a feature flag (off by default, same gating as `moa`).

Note: the upstream PR against hermes-agent (`model_tools.py` /
`toolsets.py` / `AGENTS.md` additions) is **deferred to v0.1.1** per
Pass 1 review (T2.8). The tool works locally without it; the upstream
changes just make it discoverable in `hermes tools`.

## Why a separate repo?

Hermes Agent is a narrow waist (per its `AGENTS.md` "Footprint Ladder" rule).
Every core tool ships on every API call, so additions are paid for every turn.
This extension is heavy — it has a tool module, a test harness with recorded
fixtures, and a docs tree — and it costs real money on each call ($1.30–$2.00
at the default 3-model panel, $15–$30 at max panel + long context). Shipping
it as a third-party plugin in its own repo lets us version it independently
of Hermes core, gate adoption behind `hermes tools`, and let the user opt in
per-platform.
