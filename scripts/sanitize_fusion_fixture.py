#!/usr/bin/env python3
"""Sanitize recorded fusion fixtures.

Strips Authorization headers, PII, and other sensitive content from
recorded fixtures before they are committed to tests/fixtures/.

TODO (v0.1): not yet implemented. Stub prints a TODO and exits.

Usage (once implemented):
    python3 scripts/sanitize_fusion_fixture.py \\
        --input tests/fixtures/raw/success-raw.json \\
        --output tests/fixtures/success.json
"""

from __future__ import annotations

import sys


def main() -> int:
    print(
        "TODO: scripts/sanitize_fusion_fixture.py is a stub in v0.1. "
        "v0.2 will strip Authorization headers, redact common PII "
        "patterns (emails, phone numbers, names), and write the "
        "sanitized fixture.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
