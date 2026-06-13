# Fusion — Hermes Agent Extension

Multi-model deliberation as a Hermes Agent capability. A panel of LLMs
runs in parallel; a judge model produces a structured analysis
(consensus / contradictions / unique insights / blind spots) plus the
raw panel responses. The caller can accept the structured map as the
answer (auditable) or synthesize a final response (best-answer-with-evidence).

**Backend-pluggable.** The `hermes-native` backend (default) uses
Hermes's existing model slots to fan out locally — no external
dependency, no extra credentials. The `openrouter-fusion` backend
(opt-in) passes through to OpenRouter's `openrouter:fusion` server tool
for users who already pay for it.

**Companion to** the built-in `moa` (Mixture-of-Agents) tool — fusion
returns *structure*, MoA returns *a single best answer*. Pick at the
call site.

## Status

**Stage:** Design v2, awaiting Pass 2 cross-LLM review.

See [`docs/plans/2026-06-13-fusion-tool-design.md`](docs/plans/2026-06-13-fusion-tool-design.md)
for the design contract. See
[`docs/recaps/SESSION-RECAP-2026-06-13-CROSS-LLM-REVIEW.md`](docs/recaps/SESSION-RECAP-2026-06-13-CROSS-LLM-REVIEW.md)
for the Pass 1 review synthesis. See
[`docs/recaps/SESSION-RECAP-2026-06-13-PIVOT-TO-HERMES-NATIVE.md`](docs/recaps/SESSION-RECAP-2026-06-13-PIVOT-TO-HERMES-NATIVE.md)
for the v1 → v2 pivot rationale.

Next: Pass 2 review (buildability lens) → implementation.

## Layout

```
fusion/
├── tools/
│   ├── fusion_tool.py            # openrouter_fusion tool (registry.register)
│   └── fusion/                   # Backend-pluggable core
│       ├── __init__.py
│       ├── analysis.py           # Shared StructuredAnalysis Pydantic model + judge prompt
│       ├── runner.py             # Async fan-out + judge orchestration (backend-agnostic)
│       └── backends/
│           ├── __init__.py       # Backend registry
│           ├── base.py           # FusionBackend ABC
│           ├── hermes_native.py  # v0.1 default — uses model.fallback_providers chain
│           └── openrouter_fusion.py  # opt-in — OpenRouter server tool pass-through
├── tests/                        # pytest, stdlib + unittest.mock only
├── fixtures/                     # Recorded backend responses (sanitized)
├── docs/
│   ├── plans/                    # Pre-work contracts
│   │   └── archive/              # Superseded plans (v1 OpenRouter wrapper)
│   ├── recaps/                   # Post-work journals
│   ├── architecture/             # Topical deep dives
│   └── features/                 # Per-feature deep dives
└── scripts/                      # One-off scripts (record-mode against live backends)
```

## Install (when shipped)

Drop the `tools/` directory into `~/.hermes/tools/`. Restart the agent.
The `fusion_tools` toolset becomes available behind a feature flag
(off by default, same gating as `moa`).

Note: the upstream PR against hermes-agent (`model_tools.py` /
`toolsets.py` / `AGENTS.md` additions) is **deferred to v0.1.1**. The
tool works locally without it.

## Why a separate repo?

Hermes Agent is a narrow waist (per its `AGENTS.md` "Footprint Ladder"
rule). Every core tool ships on every API call, so additions are paid
for every turn. This extension is heavy — a backend-pluggable core, two
backend implementations, a test harness with recorded fixtures, and a
docs tree — and it costs real money on each call (~$0.25–$1.60 with
the hermes-native backend depending on panel model choice, $1.30–$2.00
with the OpenRouter backend at default panel size).

Shipping it as a third-party plugin in its own repo lets us version it
independently of Hermes core, gate adoption behind `hermes tools`, and
let the user opt in per-platform.
