# Session Recap — 2026-06-13 (Run 1)

## Goal
Decide whether OpenRouter's `openrouter:fusion` server tool could be
implemented on Hermes Agent, and if so, scaffold the project for it.

## Outcome
Yes — and Hermes already has the closest equivalent (`moa`). Fusion
adds a structured-analysis judge on top of MoA's synthesized-answer
output. New repo: `adelvillar1/fusion`, scaffolded with a design plan
under `docs/plans/2026-06-13-fusion-tool-design.md` that is ready for
cross-LLM review.

## What shipped

- `adelvillar1/fusion` repo created on GitHub
- Scaffold: README, CLAUDE.md, AGENTS.md, .gitignore
- Design plan: 11 sections covering problem, scope, schema, wire
  protocol, config, cost model, test strategy, integration points,
  open questions, acceptance criteria, changelog
- MoA parity matrix comparing fusion to Hermes's built-in `moa` tool
- OpenRouter fusion reference snapshot for offline use
- Stub tool module + provider plugin manifest
- Stub-level test suite (5 tests)
- main branch + develop branch both pushed

## What did NOT ship (intentional)

- No runtime tool implementation. Stub only.
- No real OpenRouter pass-through. The plan §3-§4 is the contract.
- No recorded fixtures. `scripts/record_fusion.py` is a TODO.
- No upstream PR against `NousResearch/hermes-agent`. The 3
  integration-point changes are documented in plan §8.

## Decisions made this session

1. **Project shape: third-party plugin in its own repo.** Not a
   fork of hermes-agent, not a subfolder of hermes-agent, not a
   standalone app. This matches the Hermes ecosystem pattern
   (example-plugins repo, optional-skills repo) and lets us ship
   independently.
2. **Sibling to MoA, not a replacement.** Both off by default;
   user picks at the call site. The matrix in
   `docs/MOA-PARITY-MATRIX.md` is the contract for when to use which.
3. **Tool name: `openrouter_fusion`.** Honest about the dependency.
   v0.2 can rename or alias if a non-OpenRouter fusion server ships.
4. **Default panel size: 3.** Matches the OpenRouter "Quality"
   preset. Override via `config.yaml fusion.analysis_models` or the
   `analysis_models` tool arg.
5. **Default judge model: outer model.** Zero extra cost. Override
   via `judge_model` tool arg.
6. **Cost guard: `max_panel_size: 8`.** Refuses accidental
   over-spend unless the user explicitly opts in.
7. **No new env vars.** All behavioral config in `config.yaml`
   under `fusion.*`. The only credential is `OPENROUTER_API_KEY`,
   already required by the existing OpenRouter plugin.

## Acceptance criteria status

- [x] Repo created and pushed
- [x] README framing it as a Hermes extension
- [x] CLAUDE.md with branch topology and "today's state"
- [x] AGENTS.md with don'ts and reference to the design plan
- [x] Design plan with all 11 sections
- [x] MoA parity matrix
- [x] OpenRouter fusion reference snapshot
- [x] Tool stub with real schema
- [x] Provider plugin stub
- [x] Stub-level test suite
- [x] main and develop branches both pushed
- [ ] Cross-LLM review of design plan
- [ ] Implementation (gated on review outcome)
- [ ] Recorded fixtures
- [ ] Upstream PR to hermes-agent

## Doc updates needed

- [x] `CLAUDE.md` "Today's state" reflects scaffold-only state
- [ ] `CLAUDE.md` should be re-checked when v0.1 ships

## Open follow-ups

1. **Cross-LLM review** of the design plan. Recommended: route the
   plan through Kimi K2.6 (reasoning angle) and Claude Sonnet
   (caller-of-tool angle). Capture review notes in
   `docs/recaps/SESSION-RECAP-2026-06-13-CROSS-LLM-REVIEW.md` when
   complete.
2. **Cost validation.** The estimates in plan §6 are back-of-envelope.
   The real test is a single $0.30 fusion call against the live
   OpenRouter API once the implementation is done. Capture actual
   costs in `docs/architecture/cost-model.md` when v0.1 ships.
3. **Provider plugin manifest fields.** I made up the
   `ProviderProfile` shape based on Hermes's openrouter plugin. The
   v0.1 implementation should pull a real `ProviderProfile` from
   `providers.base` to confirm the field names match.
4. **API key leakage in fixtures.** The plan §7 says fixtures are
   sanitized. The actual sanitization script lives in
   `scripts/record_fusion.py` (TODO) — needs to strip
   `Authorization` headers and any prompt content that contains
   user data.
