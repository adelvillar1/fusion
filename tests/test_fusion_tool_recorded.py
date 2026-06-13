"""Recorded-fixture tests for the fusion tool.

Marked xfail in v0.1 — no recorded fixtures yet. To enable:

1. Run scripts/record_fusion.py against a real backend
2. Sanitize via scripts/sanitize_fusion_fixture.py
3. Commit fixtures to tests/fixtures/
4. Remove the xfail markers in this file

Per the v2 plan §7, the required fixtures are:
- success.json — full success, both `analysis` and `responses` populated
- judge-degraded.json — panel succeeds, judge fails, no `analysis`
- all-panel-failed.json — `responses: []`, all models in `failed_models`
- partial-panel-failed.json — 1 of 3 models fails, `failed_models` populated
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent.parent / "tests" / "fixtures"


@pytest.mark.xfail(
    reason="no recorded fixtures yet — see scripts/record_fusion.py",
    strict=False,
)
def test_success_fixture_loads():
    f = FIXTURES_DIR / "success.json"
    if not f.exists():
        pytest.skip("fixture not yet recorded")
    data = json.loads(f.read_text())
    assert data["backend"] == "hermes-native"
    assert "expected_panel_response" in data
    assert data["expected_panel_response"]["analysis"] is not None
    assert len(data["expected_panel_response"]["responses"]) > 0


@pytest.mark.xfail(reason="no recorded fixtures yet", strict=False)
def test_judge_degraded_fixture_loads():
    f = FIXTURES_DIR / "judge-degraded.json"
    if not f.exists():
        pytest.skip("fixture not yet recorded")
    data = json.loads(f.read_text())
    assert data["expected_panel_response"]["analysis"] is None


@pytest.mark.xfail(reason="no recorded fixtures yet", strict=False)
def test_all_panel_failed_fixture_loads():
    f = FIXTURES_DIR / "all-panel-failed.json"
    if not f.exists():
        pytest.skip("fixture not yet recorded")
    data = json.loads(f.read_text())
    assert data["expected_panel_response"]["responses"] == []
    assert len(data["expected_panel_response"]["failed_models"]) > 0


@pytest.mark.xfail(reason="no recorded fixtures yet", strict=False)
def test_partial_panel_failed_fixture_loads():
    f = FIXTURES_DIR / "partial-panel-failed.json"
    if not f.exists():
        pytest.skip("fixture not yet recorded")
    data = json.loads(f.read_text())
    assert len(data["expected_panel_response"]["responses"]) > 0
    assert len(data["expected_panel_response"]["failed_models"]) > 0
