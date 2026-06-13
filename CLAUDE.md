# Fusion

> Hermes Agent extension: openrouter:fusion server tool wrapper
> Repo: https://github.com/adelvillar1/fusion.git
> **Status:** Design / pre-implementation. Drive from `docs/plans/2026-06-13-fusion-tool-design.md`.

---

## Hard rules (non-negotiable)

- **This project is a Hermes plugin, not a standalone app.** No web UI, no
  hosted DB, no API endpoints. The deploy artifact is a directory drop-in
  into `~/.hermes/`.
- **No live network calls in tests.** Record-mode against OpenRouter for
  fixture generation, but committed fixtures are sanitized. CI must run
  offline.
- **Tool stays opt-in.** Shipped in `_DEFAULT_OFF_TOOLSETS` (matches Hermes's
  `moa` gating). No user is exposed to 3-8 frontier models per call without
  explicit opt-in via `hermes tools`.
- **Cost guard.** Default panel size is 3, default judge is the outer model
  (no extra cost). Expanding to 8+ frontier models requires explicit param.
- **Plan → recap discipline.** Trivial fixes can be done directly. Anything
  ≥15 min or >2 files: warmup → plan → delegate_task (subagent-driven-dev,
  2-stage review) → recap → wrapup.
- **Cross-LLM plan review is the default for any plan >2KB.** Propose the
  review before approval, expect multi-pass with rotated angles.

---

## Branch → environment topology

```
develop ──► main
(local)     (GitHub main, installable via git+https)
```

| Branch  | Use                                                |
|---------|----------------------------------------------------|
| develop | Day-to-day work, PRs land here first              |
| main    | Installable release. Tagged with semver on merge.  |

**Release process:** develop → PR → review → squash-merge to main → tag.

---

## Where to find things

**Design contract (read first):**
- [`docs/plans/2026-06-13-fusion-tool-design.md`](docs/plans/2026-06-13-fusion-tool-design.md) —
  full design: schema, config, panel cost model, recursion guard, test
  strategy, integration points. The plan drives everything else.

**Architecture:**
- Plugin layout (when written) → `docs/architecture/plugin-layout.md`
- Cost model (panel-size → $/call estimates) → `docs/architecture/cost-model.md`
- Recursion guard design → `docs/architecture/recursion-guard.md`

**Features:**
- `openrouter_fusion` tool (when written) → `docs/features/fusion-tool.md`

**Reference:**
- OpenRouter fusion docs reference → `docs/OPENROUTER-FUSION-REFERENCE.md`
- MoA parity matrix (MoA vs fusion) → `docs/MOA-PARITY-MATRIX.md`

---

## Today's state

- Repo scaffolded 2026-06-13. No runtime code yet; only design plan + stubs.
- **Pass 1 cross-LLM review complete (2026-06-13).** 3/4 providers
  completed (DeepSeek, GLM, Mimo). Kimi failed with the documented
  temperature bug. 11 Tier 1 items found, 8 Tier 2 items found, 5 Tier 3
  follow-up plans filed. All Tier 1 + Tier 2 patches applied to the
  design plan. See `docs/recaps/SESSION-RECAP-2026-06-13-CROSS-LLM-REVIEW.md`
  for the full synthesis.
- **Major design changes from Pass 1:**
  - `force` parameter dropped (T1.1, T1.2)
  - Recursion guard switched from env-var to `ContextVar` (T1.3)
  - Cost estimate corrected from $0.30/call to $1.30–$2.00/call (T1.4)
  - Schema `maxItems` bumped to 16 so the cost guard can fire (T1.5)
  - Provider plugin deferred to v0.2 (T1.6)
  - Partial-failure paths fully enumerated in §4.1 (T1.7)
  - Wire-protocol live verification added as §4.0 prerequisite (T1.8)
- Next concrete step: **Pass 2 cross-LLM review** with the buildability
  lens (Pattern 4b), then implementation.
