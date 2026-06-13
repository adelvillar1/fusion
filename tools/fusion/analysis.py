"""Structured analysis Pydantic model + judge prompt.

Both backends produce a `StructuredAnalysis` JSON. The OpenRouter
backend gets the structured analysis for free (its server tool does
the judge pass). The hermes-native backend invokes the judge model
explicitly as a second round-trip using the same `JUDGE_PROMPT` and
parses the response into `StructuredAnalysis`.

The runner assembles the judge input by concatenating panel responses
into a single user message. See `tools/fusion/runner.py`.
"""

from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field, ValidationError


class Contradiction(BaseModel):
    """A point where panel models disagree."""

    topic: str
    stances: list[dict[str, str]]  # [{"model": "...", "stance": "..."}]


class PartialCoverage(BaseModel):
    """A point raised by only some panel models."""

    models: list[str]
    point: str


class UniqueInsight(BaseModel):
    """A point raised by only one panel model."""

    model: str
    insight: str


class StructuredAnalysis(BaseModel):
    """The structured output of the judge.

    `consensus` and `blind_spots` are flat lists of strings.
    `contradictions` and `unique_insights` and `partial_coverage`
    carry their own per-item structure.
    """

    consensus: list[str] = Field(default_factory=list)
    contradictions: list[Contradiction] = Field(default_factory=list)
    partial_coverage: list[PartialCoverage] = Field(default_factory=list)
    unique_insights: list[UniqueInsight] = Field(default_factory=list)
    blind_spots: list[str] = Field(default_factory=list)


JUDGE_PROMPT = """You are a meta-analyst. You have been given {N} responses
to the same prompt from different models. Compare them and produce a
structured JSON analysis.

Output ONLY this JSON shape (no other text):

{{
  "consensus": ["Points all or most responses agree on"],
  "contradictions": [{{"topic": "...", "stances": [{{"model": "...", "stance": "..."}}]}}],
  "partial_coverage": [{{"models": ["..."], "point": "Only some models raised this"}}],
  "unique_insights": [{{"model": "...", "insight": "Something only one model raised"}}],
  "blind_spots": ["Topics no response addressed"]
}}

Be honest about disagreements. Do not manufacture consensus."""


def parse_judge_output(raw: str) -> StructuredAnalysis:
    """Parse a judge's raw text output into a StructuredAnalysis.

    Tolerant of markdown-fenced JSON (e.g. ````json ... ````). Strips
    the fences and any leading/trailing prose before parsing.

    Raises:
        ValueError: if the raw output cannot be parsed into a
            StructuredAnalysis. The runner catches this and surfaces
            `raw_judge_output` to the outer model with no `analysis`.
    """
    import json
    import re

    text = raw.strip()

    # Strip markdown code fences (```json ... ``` or ``` ... ```)
    fence_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if fence_match:
        text = fence_match.group(1).strip()

    # If the model returned prose + JSON, find the first { ... } block
    if not text.startswith("{"):
        brace_start = text.find("{")
        brace_end = text.rfind("}")
        if brace_start != -1 and brace_end != -1 and brace_end > brace_start:
            text = text[brace_start : brace_end + 1]

    try:
        data: Any = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Judge output is not valid JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError(
            f"Judge output is not a JSON object (got {type(data).__name__})"
        )

    try:
        return StructuredAnalysis(**data)
    except ValidationError as exc:
        raise ValueError(
            f"Judge output does not match StructuredAnalysis schema: {exc}"
        ) from exc
