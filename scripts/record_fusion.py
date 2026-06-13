#!/usr/bin/env python3
"""Record-mode harness for the fusion tool.

Run manually with OPENROUTER_API_KEY (or other provider keys) set.
Writes sanitized fixtures to tests/fixtures/.

TODO (v0.1): not yet implemented. Stub prints a TODO and exits.

Usage (once implemented):
    OPENROUTER_API_KEY=sk-... python3 scripts/record_fusion.py \\
        --backend openrouter-fusion \\
        --panel "claude-opus,gpt-5,grok-3" \\
        --prompt "What is the capital of France?" \\
        --output tests/fixtures/success.json
"""

from __future__ import annotations

import sys


def main() -> int:
    print(
        "TODO: scripts/record_fusion.py is a stub in v0.1. "
        "See docs/plans/2026-06-13-fusion-tool-design.md §7 for the "
        "design; v0.2 will implement the record-mode harness against "
        "real backends.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
