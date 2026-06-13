# Fusion

> Hermes Agent extension: multi-model deliberation with structured analysis
> Repo: https://github.com/adelvillar1/fusion.git
> **Status:** Design v2, awaiting Pass 2 cross-LLM review (buildability lens)

---

## Hard rules (non-negotiable)

- **This project is a Hermes plugin, not a standalone app.** No web UI, no
  hosted DB, no API endpoints. The deploy artifact is a directory drop-in
  into `~/.hermes/`.
- **No live network calls in tests.** Record-mode for fixture generation;
  committed fixtures are sanitized. CI must run offline.
- **Tool stays opt-in.** Shipped in `_DEFAULT_OFF_TOOLSETS` (matches
  Hermes's `moa` gating). No user is exposed to a multi-model panel per
  call without explicit opt-in via `hermes tools`.
- **Cost guard.** Default panel size is 3, max is 8 (cost guard). v0.1
  has **no override** — the guard is a hard wall.
- **Plan → recap discipline.** Trivial fixes can be done directly. Anything
  ≥15 min or >2 files: warmup → plan → delegate_task (subagent-driven-dev,
  2-stage review) → recap → wrapup.
- **Cross-LLM plan review is the default for any plan >2KB.** Propose the
  review before approval, expect multi-pass with rotated angles.
- **Backend-pluggable architecture.** The tool is the product; backends
  are interchangeable. `hermes-native` is the v0.1 default (no external
  dependency). OpenRouter is an opt-in alternate backend, not a
  requirement.

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
  v2 design: backend-pluggable, hermes-native default, structured analysis.
- [`docs/plans/archive/2026-06-13-fusion-tool-design-v1-ORwrapper.md`](docs/plans/archive/2026-06-13-fusion-tool-design-v1-ORwrapper.md) —
  v1 design (superseded): OpenRouter-wrapped.

**Architecture (when written):**
- Plugin layout → `docs/architecture/plugin-layout.md`
- Backend ABC design → `docs/architecture/backends.md`
- Cost model (per-backend) → `docs/architecture/cost-model.md`
- Recursion guard design → `docs/architecture/recursion-guard.md`

**Features:**
- `openrouter_fusion` tool → `docs/features/fusion-tool.md`

**Reference:**
- MoA parity matrix → `docs/MOA-PARITY-MATRIX.md`
- OpenRouter fusion docs reference → `docs/OPENROUTER-FUSION-REFERENCE.md`

---

## Today's state

- Repo scaffolded 2026-06-13.
- **v1 plan drafted, Pass 1 cross-LLM review complete, all Tier 1 + Tier 2
  patches applied.** See
  `docs/recaps/SESSION-RECAP-2026-06-13-CROSS-LLM-REVIEW.md`.
- **v2 pivot on 2026-06-13.** User clarified: do not require OpenRouter
  as a dependency. Tool is now backend-pluggable; `hermes-native` is the
  v0.1 default using existing model slots. See
  `docs/recaps/SESSION-RECAP-2026-06-13-PIVOT-TO-HERMES-NATIVE.md`.
- **Pass 2 cross-LLM review (buildability lens) complete on 2026-06-13.**
  4/4 providers completed (DeepSeek, GLM, Kimi, Mimo). 8 Tier 1 + 9
  Tier 2 items found, all patched. See
  `docs/recaps/SESSION-RECAP-2026-06-13-CROSS-LLM-REVIEW-PASS2.md`.
- **Major design changes from Pass 2:**
  - Tool **renamed from `openrouter_fusion` to `fusion`** in v0.1 (T1.2)
  - Judge ownership fixed: **runner owns the judge**, not the backend
    (T1.1 — three-way contradiction in §4.2/§4.3/§6.1 resolved)
  - `asyncio.gather(..., return_exceptions=True)` is now mandatory in
    hermes-native (T1.3 — critical bug that would have lost responses
    on partial failure)
  - Recursion-guard ContextVar is now **plugin-owned** in
    `tools/fusion/runner.py`, not in hermes-agent's `run_agent.py`
    (T1.4 + T1.5 — this is a plugin repo, `run_agent.py` doesn't
    exist here)
  - hermes-native `check_requirements` verifies ≥2 fallback_providers
    (T1.7)
  - `analysis_models=[]` auto-population = first 3 of fallback chain
    (T1.8)
  - `max_tool_calls` ignored by hermes-native v0.1 (T1.6)
  - Per-member-FAIL semantics (not per-member-substitute) in v0.1
    (T2.1)
- Next concrete step: implementation. The plan is now consistent
  end-to-end and ready to hand to a subagent via `delegate_task`.
