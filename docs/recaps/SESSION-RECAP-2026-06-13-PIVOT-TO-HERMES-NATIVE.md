# Session Recap — 2026-06-13 (v1 → v2 Pivot: Hermes-Native Fusion)

## Goal

Reframe the fusion tool from "thin wrapper around OpenRouter's
`openrouter:fusion` server tool" (v1) to "generalized multi-model
deliberation capability with pluggable backends" (v2), with a
`hermes-native` backend as the v0.1 default.

## Outcome

Done. v1 plan archived. v2 plan written (32 KB) with the
backend-pluggable architecture, the `hermes-native` backend as the
default, and OpenRouter as an opt-in alternate backend. Most v1 Tier
1 + Tier 2 fixes carried over because they were about correctness, not
OpenRouter-specificity.

## Why the pivot

User clarification (2026-06-13, mid-session): "I don't want to use
openrouter, I want hermes agent to have this functionality."

v1 made OpenRouter a hard dependency for the *only* shipped backend.
That was wrong on three dimensions:

1. **Architectural**: OpenRouter is one of many possible backends for
   multi-model deliberation. The tool is the product; the backend is
   interchangeable. v1 violated the open-closed principle.

2. **Economic**: the v1 hermes-native user with Anthropic + DeepSeek
   + Kimi keys was *already* paying for those models directly. Routing
   them through OpenRouter would add 5% aggregator markup on every call
   and require an additional credential. v1 imposed that cost
   unnecessarily.

3. **User scope**: the v1 plan excluded users who don't use OpenRouter
   at all (some users route everything through direct provider keys
   for billing or latency reasons). v2 includes them.

## What changed from v1 to v2

### Architecture (major)

- v1: single backend (OpenRouter pass-through)
- v2: backend ABC with two concrete backends; hermes-native default

### Tool name (deferred decision)

- v1: `openrouter_fusion` (honest about the OpenRouter dependency)
- v2: still `openrouter_fusion` in v0.1, but the prefix is now
  misleading. Renaming to `fusion` is on the v0.2 punch list
  (§9 question 1).

### Cost model (radically different)

- v1: $1.30–$2.00/call (OpenRouter aggregator rates)
- v2 hermes-native: $0.25–$1.60/call (user's existing direct provider
  rates, panel model choice drives the variance)
- v2 openrouter-fusion: same as v1

### Wire protocol (different)

- v1: single OpenRouter POST with `openrouter:fusion` server tool
- v2 hermes-native: `asyncio.gather` over Hermes's existing model
  clients (no new wire protocol)
- v2 openrouter-fusion: same as v1 (single OpenRouter POST)

### Judge strategy (new in v2)

- v1: judge = outer model (OpenRouter default) or explicit
- v2: three strategies — `outer-model` (zero cost), `auxiliary-curator`
  (Hermes's existing curator slot, typically a strong reasoner),
  `explicit-model` (override)

### Prerequisites (simplified)

- v1: §4.0 prerequisite — live-verify the OpenRouter wire protocol
  before implementation (1-2 hours blocking)
- v2: **no prerequisite**. The hermes-native backend uses Hermes's
  existing clients (already tested). The openrouter-fusion backend
  has a backend-specific implementation note (not a tool-level
  prerequisite).

## What carried over from v1

Most Tier 1 + Tier 2 fixes from v1 Pass 1 are in v2 unchanged. They
were about correctness, not OpenRouter-specificity:

- `force` parameter dropped → carried over (v2 §3)
- `ContextVar` recursion guard → carried over (v2 §4.4)
- Cost guard `max_panel_size: 8` + schema `maxItems: 16` → carried
  over (v2 §3, §5)
- File manifest in §2 → carried over, expanded (v2 §2)
- `judge_model_default` fallback → generalized to `judge_strategy`
  (v2 §3, §4.5)
- `enable_web_tools: false` → carried over to openrouter-fusion
  backend config (v2 §5)
- Documented precedence → carried over (v2 §5)
- `timeout_seconds` parameter → carried over (v2 §3)
- Specific, falsifiable acceptance criteria → carried over (v2 §10)
- §4.1 partial-failure-paths table → generalized in v2 §4.6
- Invalid JSON Schema fix → carried over (v2 §3)
- `run_agent.py` integration → carried over (v2 §8)
- Provider plugin deferred → carried over (v2 §2)
- Upstream PR deferred to v0.1.1 → carried over (v2 §8)

## What did NOT carry over

- The §4.0 "wire protocol verification" prerequisite. The hermes-native
  backend has no wire protocol to verify. The openrouter-fusion
  backend's wire verification moves to a backend-specific implementation
  note.
- v1's blanket OpenRouter dependency. v2's `hermes-native` backend is
  zero-dep.
- v1's cost assumption (OpenRouter aggregator rates as the only option).
  v2 distinguishes per-backend cost.

## New design questions for Pass 2

The v2 plan opens 5 new questions (§9) for the buildability-lens
review (Pass 2):

1. Should the v0.1 tool name be `openrouter_fusion` or `fusion`?
2. Default judge: hermes-native's curator slot, or always outer model?
3. `model.fallback_providers` chain semantics in hermes-native: per-panel-member
   or sequential?
4. Should the structured-analysis prompt be configurable per use case?
5. Web tools in panel members — both backends disabled in v0.1?

Plus 5 more granular ones for Pass 2:
6. Backend ABC granularity
7. `auxiliary_client` extension
8. Curator slot when its provider key isn't in the fallback chain
9. Empty `fallback_providers` chain behavior
10. v1 → v0.1 tool-name rename backwards compat

## Acceptance criteria status (v2)

- [x] v1 plan archived
- [x] v2 plan written (32 KB, 11 sections)
- [x] Backend-pluggable architecture specified
- [x] hermes-native default backend specified (no external deps)
- [x] openrouter-fusion opt-in backend specified
- [x] Judge strategy specified (3 strategies)
- [x] v1 Pass 1 fixes carried over
- [ ] Pass 2 cross-LLM review (buildability lens)
- [ ] Implementation
- [ ] Upstream PR to hermes-agent (v0.1.1)

## Doc updates needed

- [x] v1 plan archived with the full Pass 1 patch history preserved
- [x] v2 plan includes a CHANGELOG section explicitly mapping v1 → v2
- [x] CLAUDE.md "Today's state" reflects the pivot
- [x] AGENTS.md updated to reference v2 plan
- [x] README.md reflects backend-pluggable architecture
- [ ] CLAUDE.md re-checked when v0.1 ships

## Next step

Dispatch Pass 2 cross-LLM review of the v2 plan with the buildability
lens (Pattern 4b from the `cross-llm-review` skill). The Pass 2 brief
must include the "do NOT re-flag" list of v1 fixes that carried over.
