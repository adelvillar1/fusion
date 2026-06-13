# MoA ↔ Fusion Parity Matrix

Comparison of the existing Hermes `moa` (Mixture-of-Agents) tool with the
proposed `fusion` tool. Drives design decisions in
[`docs/plans/2026-06-13-fusion-tool-design.md`](plans/2026-06-13-fusion-tool-design.md).

| Capability                                          | MoA (Hermes built-in) | Fusion (proposed) | Notes |
|-----------------------------------------------------|-----------------------|-------------------|-------|
| Parallel reference panel                            | ✅ (4 hardcoded)      | ✅ (1-8, configurable) | Fusion per-call configurable |
| Web tools enabled in panel                          | ❌                    | ✅ (passthrough only in v0.1) | v0.2 surfaces |
| Structured analysis output                          | ❌ (synthesized string) | ✅ (consensus/contradictions/unique/blind spots) | The key differentiator |
| Customizable panel per call                         | ❌ (hardcoded)        | ✅ (`analysis_models` param) | |
| Configurable judge model                            | ❌ (hardcoded aggregator) | ✅ (`judge_model` param, defaults to outer) | |
| Judge-degradation fallback                          | ⚠️ (partial: `MIN_SUCCESSFUL_REFERENCES`) | ✅ (`responses` only, no `analysis`) | |
| `tool_choice: "required"` force-fuse                | ❌                    | ✅ (`force` param) | |
| Max-tool-call / reasoning config per inner call     | ❌                    | ✅ (`max_tool_calls`, `reasoning_effort`) | |
| Recursion protection                                | ❌                    | ✅ (`x-openrouter-fusion-depth` + `HERMES_FUSION_DEPTH`) | |
| Lives in OpenRouter pipeline                        | ❌ (extra round-trips from agent) | ✅ (server-side panel) | Fusion cheaper at scale |
| Off by default                                      | ✅                    | ✅ (proposed) | Cost guard |
| Test coverage                                       | ✅ (in Hermes test suite) | 🚧 (planned) | Implementation PR |
| Provider-plugin selectable as primary model         | ❌                    | ✅ (proposed `openrouter/fusion` alias) | |

## Use-case mapping

| Task type                                              | Use MoA | Use Fusion |
|--------------------------------------------------------|---------|------------|
| "Give me the best single answer to a hard question"    | ✅      | (overkill) |
| "Where do experts disagree on X?"                       | ❌      | ✅         |
| "Audit these competing approaches and show me the consensus" | ❌ | ✅         |
| "Generate N diverse creative candidates"                | ✅      | (works, but `analysis` is wasted) |
| "Map the decision space — what are the minority views?" | ❌     | ✅         |
| High-stakes, accuracy-critical, low-volume              | (synthesized answer is fine) | ✅ (auditable) |

## Inheritance

Fusion should reuse the MoA code where possible:

- **OpenRouter async client** → `tools/openrouter_client.get_async_client`
- **Async retry pattern** → `mixture_of_agents_tool._run_reference_model_safe`
- **Content extraction** → `agent.auxiliary_client.extract_content_or_reasoning`
- **Config defaults** → `hermes_cli/config.DEFAULT_CONFIG` shape

The two tools are siblings, not parent/child. MoA is the "best answer"
play; fusion is the "map the disagreement" play. Both off by default;
user picks at the call site.
