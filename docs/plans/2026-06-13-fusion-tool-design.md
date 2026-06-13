# Fusion Tool — Design Plan

**Date:** 2026-06-13
**Status:** Draft, awaiting cross-LLM review
**Author:** Alejandro del Villar (via Hermes)
**Repo:** `adelvillar1/fusion`

---

## 1. Problem statement

The Hermes Agent's built-in `moa` (Mixture-of-Agents) tool runs a panel of
LLMs in parallel and returns a single synthesized answer from an aggregator
model. This is good for "give me the best answer" tasks but bad for
"where do experts disagree" tasks — the synthesis step *hides* the
disagreement instead of surfacing it.

OpenRouter exposes a server-side tool `openrouter:fusion` (beta) that does
what MoA does, plus a structured-analysis pass: a judge model returns
`consensus`, `contradictions`, `partial_coverage`, `unique_insights`, and
`blind_spots` as JSON, and the calling model writes the final response from
that map. The result is auditable and the disagreements are explicit.

**Goal:** expose `openrouter:fusion` to Hermes as a first-class tool the
agent can call, with the same opt-in posture as `moa`.

---

## 2. Scope

### In scope (v0.1)

- A single tool `openrouter_fusion` (toolset key: `fusion_tools`)
- Configuration via `config.yaml` under `fusion.*`
- Default panel of 3 frontier models, default judge = the outer model
- Recursion guard (no fusion inside a fusion panel)
- Recorded-fixture test harness, offline-only CI
- A provider-plugin stub at `plugins/model-providers/fusion/` so the
  `openrouter/fusion` router alias is selectable in `hermes model`

### Out of scope (v0.1)

- Per-model `reasoning` config beyond `effort` (no `max_tokens` override)
- Caching of fusion responses (left to Hermes's existing response cache)
- UI surfaces (no dashboard component yet)
- Web-search delegation to the panel models (fusion passes web tools, but
  v0.1 doesn't surface them to the agent)
- Judge model selection across providers other than OpenRouter (any
  OpenRouter-routable model is fine; non-OpenRouter judges are v0.2)

---

## 3. Tool schema

Tool name: `openrouter_fusion`. Toolset: `fusion_tools`.

```python
{
    "name": "openrouter_fusion",
    "description": (
        "Run the user prompt through a panel of 1-8 models in parallel and "
        "have a judge model compare their responses, returning structured "
        "analysis (consensus, contradictions, unique insights, blind spots) "
        "plus the raw panel responses. Use for 'where do experts disagree' "
        "or high-stakes multi-perspective tasks."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description": "The prompt to send to the panel.",
            },
            "analysis_models": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
                "maxItems": 8,
                "description": (
                    "Panel models. Defaults to fusion.analysis_models from "
                    "config.yaml. Mix-and-match across providers — all are "
                    "routed through OpenRouter."
                ),
            },
            "judge_model": {
                "type": "string",
                "description": (
                    "Judge model. Defaults to the outer model (zero extra "
                    "cost). Set explicitly to override."
                ),
            },
            "max_tool_calls": {
                "type": "integer",
                "minimum": 1,
                "maximum": 16,
                "default": 8,
                "description": "Max tool-calling steps per panel/judge model.",
            },
            "max_completion_tokens": {
                "type": "integer",
                "description": "Max output tokens per inner call. Provider default if unset.",
            },
            "reasoning_effort": {
                "type": ["string", "null"],
                "enum": ["low", "medium", "high", None],
                "description": "Reasoning effort for panel/judge models.",
            },
            "temperature": {
                "type": "number",
                "minimum": 0,
                "maximum": 2,
                "description": "Sampling temperature. Provider default if unset.",
            },
            "force": {
                "type": "boolean",
                "default": False,
                "description": (
                    "If true, model is told to call this tool even when it "
                    "judges the task doesn't warrant it. Maps to "
                    "tool_choice='required' on the inner call."
                ),
            },
        },
        "required": ["prompt"],
        "additionalProperties": False,
    },
}
```

---

## 4. Wire protocol

The tool is a thin pass-through to OpenRouter. The inner call structure:

```
POST https://openrouter.ai/api/v1/chat/completions
Headers:
  Authorization: Bearer ${OPENROUTER_API_KEY}
  Content-Type: application/json
  x-openrouter-fusion-depth: 1   # recursion guard (read by OpenRouter, not by us)

Body:
{
  "model": "<outer_model>",
  "messages": [{"role": "user", "content": "<prompt>"}],
  "tools": [
    {
      "type": "openrouter:fusion",
      "parameters": {
        "analysis_models": [...],   # from config or args
        "model": "<judge_model>",   # from config or args
        "max_tool_calls": 8,
        "max_completion_tokens": ...,  # optional
        "reasoning": {"effort": "high"},  # optional
        "temperature": ...  # optional
      }
    }
  ],
  "tool_choice": "required" if force else "auto"
}
```

The outer model invokes the tool; the tool result is a JSON object with the
shape OpenRouter documents. We do **not** parse the analysis — we hand it
back as JSON for the outer model to consume.

### Recursion guard

`x-openrouter-fusion-depth: 1` is set on every outer call. If a sub-agent is
ever spawned from a fusion panel member, its calls would carry
`x-openrouter-fusion-depth: 2`, and OpenRouter rejects the second
recursion. We also gate locally: the tool raises `RecursionError` if
`HERMES_FUSION_DEPTH >= 1` (set by `run_agent.py` when entering a panel).

### Judge-degradation

If the panel succeeds but the judge fails, OpenRouter returns
`status: "ok"` with `responses` only and **no** `analysis` field. The tool
passes this through unchanged — the outer model is responsible for
synthesizing from `responses` only. We do not synthesize on its behalf.

### Hard failures

`status: "error"` from OpenRouter is raised as a tool error with the
`error_reason` field surfaced verbatim. The outer model sees
`{"error": "...", "reason": "rate_limited"}` and can retry or fall back.

---

## 5. Configuration

```yaml
# config.yaml
fusion:
  # Default panel. Override per-call via the tool's `analysis_models` param.
  analysis_models:
    - "anthropic/claude-opus-latest"
    - "openai/gpt-latest"
    - "google/gemini-pro-latest"
  # Default judge. Defaults to the outer model (no override) when null.
  judge_model: null
  max_tool_calls: 8
  # Hard cost guard — refuse tool calls with analysis_models > this size
  # unless the user explicitly opts in via the tool's `force` param.
  max_panel_size: 8
```

No new env vars. All behavioral config lives in `config.yaml`. The
`OPENROUTER_API_KEY` env var is the only credential, and it's already
required by the existing OpenRouter provider plugin.

---

## 6. Cost model

Rough $/call estimates at default panel size of 3 (Claude Opus 4.6 +
GPT-5.4 Pro + Gemini 2.5 Pro), prompt ~2K tokens, response ~4K tokens:

| Component    | Tokens in+out | $/call (approx) |
|--------------|---------------|-----------------|
| Panel member | 2K + 4K       | $0.06           |
| 3 members    | 18K total     | $0.18           |
| Judge (outer)| 2K in + ~6K structured-analysis out | $0.12 |
| **Total**    |               | **~$0.30/call** |

At max panel size of 8, a long-context prompt can approach **$2-3/call**.
This is the same cost profile as `moa` and the same reason both tools
are off-by-default. The cost guard in §5 caps accidental over-spend.

---

## 7. Test strategy

- **Unit tests** (`tests/test_fusion_tool.py`): pure Python, no network.
  Use `unittest.mock` to stub the OpenRouter client. Cover:
  - Schema validation (minItems, maxItems, additionalProperties: false)
  - Default param resolution (config → args precedence)
  - Recursion guard (`HERMES_FUSION_DEPTH` → `RecursionError`)
  - Force → `tool_choice: "required"` mapping
  - Judge-degradation passthrough (no synthesis)
  - Hard-failure passthrough (error reason surfaced)
  - Cost guard refusal when `analysis_models` exceeds `max_panel_size`
- **Recorded-fixture tests** (`tests/test_fusion_tool_recorded.py`):
  replay `fixtures/openrouter-fusion-*.json` through the tool. Fixtures are
  sanitized: no API keys, no real model outputs that contain PII.
- **Record-mode script** (`scripts/record_fusion.py`): standalone script
  that hits the real OpenRouter API and writes fixtures. Run manually with
  `OPENROUTER_API_KEY` set; never in CI.
- **Cross-model live test** (manual, not in CI): call the tool from a
  Hermes session with `--profile test` and verify the judge-degradation
  path and the consensus/contradictions structure.

No live network calls in CI. Matches the Hermes skill standards
(`AGENTS.md:921`).

---

## 8. Integration points

Three small changes required in `~/.hermes/hermes-agent/` once the tool is
shipped. Each is a single-line addition; the goal is to upstream a single
PR against hermes-agent with these three changes.

1. **`model_tools.py:224` (new entry next to `moa_tools`):**
   ```python
   "fusion_tools": ["openrouter_fusion"],
   ```
2. **`model_tools.py:_DEFAULT_OFF_TOOLSETS`:**
   add `"fusion_tools"` to the off-by-default set.
3. **`toolsets.py` / `AGENTS.md` toolsets table:**
   add `fusion` to the documented toolset keys (line 945 of Hermes's
   `AGENTS.md`).

For local-only use, none of the three are required: the tool is registered
through the auto-discovery `registry.register()` call in
`tools/fusion_tool.py` and is invokable as long as the toolset key
`fusion_tools` is in `enabled_toolsets`. The opt-in toggle is
`hermes tools enable fusion_tools`.

---

## 9. Open questions for review

1. **Should the tool name be `openrouter_fusion` or just `fusion`?**
   `openrouter_fusion` is more honest about the dependency but means a
   future Anthropic-direct fusion server (if one ships) would have a
   different name. Lean: `openrouter_fusion`.
2. **Should we expose `web_tools` to the panel?** OpenRouter's docs say
   panel and judge have `web_search` and `web_fetch` enabled. Surfacing
   this would require the outer agent to be willing to spend web-tool
   budget on the panel. Lean: v0.1 passes through, but we don't document
   it in the tool description; v0.2 makes it explicit + opt-out.
3. **Default panel of 3 vs MoA's 4?** The OpenRouter doc shows up to 8
   models; MoA hardcodes 4. Lean: 3 (matches the OpenRouter quality
   preset's "Quality" tier) — easy to bump to 4+ via config.
4. **Judge model = outer model by default.** The OpenRouter doc says
   default is the outer model. This is the right default for cost
   (no extra round-trip to a different model). Lean: keep this default.
5. **Provider plugin (`plugins/model-providers/fusion/`):** ship or
   skip in v0.1? The plugin would expose `openrouter/fusion` as a
   selectable model in `hermes model`, letting users use it as a
   primary model. Lean: ship the stub, mark as alpha — gives the agent
   loop a way to route through fusion natively without calling the
   tool.

---

## 10. Acceptance criteria

A PR that ships v0.1 is "done" when:

- [ ] `openrouter_fusion` tool registers and is gated by
      `fusion_tools` toolset
- [ ] Tool default params resolve from `config.yaml fusion.*`
- [ ] Recursion guard raises `RecursionError` when `HERMES_FUSION_DEPTH >= 1`
- [ ] All 6 unit tests pass; all 4 recorded-fixture tests pass
- [ ] `record_fusion.py` produces a valid fixture for at least one
      panel size, judge configuration, and reasoning effort
- [ ] Cost guard refuses `analysis_models` of size > `max_panel_size`
      unless overridden
- [ ] `plugins/model-providers/fusion/__init__.py` and `plugin.yaml`
      exist and parse without import errors
- [ ] This plan is updated to reflect any design changes made during
      implementation, with a CHANGELOG section at the bottom

---

## 11. Changelog

- **2026-06-13** — Initial draft. Pending cross-LLM review.
