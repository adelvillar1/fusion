# OpenRouter Fusion — Reference

Snapshot of OpenRouter's [`openrouter:fusion`](https://openrouter.ai/docs/guides/features/server-tools/fusion)
server tool docs, captured 2026-06-13. **Source of truth lives at the URL
above; this file is a quick reference, not a substitute.**

## What it does

Beta server tool. Multi-model deliberation: a panel of 1-8 models run in
parallel, a judge model compares their responses and returns structured
analysis (consensus / contradictions / partial coverage / unique insights /
blind spots) plus the raw panel responses.

## Wire protocol

```http
POST https://openrouter.ai/api/v1/chat/completions
Authorization: Bearer ${OPENROUTER_API_KEY}
Content-Type: application/json

{
  "model": "<outer_model>",
  "messages": [{"role": "user", "content": "..."}],
  "tools": [
    {
      "type": "openrouter:fusion",
      "parameters": {
        "analysis_models": ["m1", "m2", "m3"],
        "model": "<judge_model>",
        "max_tool_calls": 8,
        "max_completion_tokens": null,
        "reasoning": {"effort": "high"},
        "temperature": null
      }
    }
  ],
  "tool_choice": "auto" | "required"
}
```

## Recursion guard

`x-openrouter-fusion-depth` header. OpenRouter rejects a second fusion
call inside an existing one.

## Invocation conditions

Model auto-invokes fusion when:

- Research questions
- Multi-domain critique
- "Compare and contrast" prompts
- High-stakes accuracy-critical queries

Simple tactical prompts don't trigger it. Force with `tool_choice: "required"`.

## Response shape

```json
{
  "status": "ok",
  "analysis": {
    "consensus": ["..."],
    "contradictions": [{"topic": "...", "stances": [{"model": "...", "stance": "..."}]}],
    "partial_coverage": [{"models": ["..."], "point": "..."}],
    "unique_insights": [{"model": "...", "insight": "..."}],
    "blind_spots": ["..."]
  },
  "responses": [{"model": "...", "content": "..."}]
}
```

## Failure modes

| `status` | `error_reason`            | Meaning                                    |
|----------|---------------------------|--------------------------------------------|
| ok       | (omitted)                 | Success                                    |
| ok       | (omitted)                 | Partial success: panel + judge-degraded (no `analysis` field) |
| error    | `all_panels_failed`       | Every panel model errored                  |
| error    | `insufficient_credits`    | At least one failure due to credits        |
| error    | `rate_limited`            | At least one failure due to rate limits    |
| error    | `fusion_invocation_capped`| Second fusion call in same turn rejected   |
| error    | `unexpected_error`        | Unexpected interruption                    |
