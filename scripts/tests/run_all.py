#!/usr/bin/env python3
"""Run the skill's regression test modules (no pytest needed).

Usage:
    python scripts/tests/run_all.py
Exits non-zero if any test module fails.

Tests are imported statically (no dynamic exec) so the published package
passes static-analysis scanners that flag runtime module loading.
"""
import os
import sys

# Tests live alongside this runner; make them importable.
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from test_content_detect import main as run_content_detect
from test_token_saver import main as run_token_saver
from test_url_fetch import main as run_url_fetch

_TESTS = [
    ("test_url_fetch.py", run_url_fetch),
    ("test_token_saver.py", run_token_saver),
    ("test_content_detect.py", run_content_detect),
]


def main():
    failed = 0
    for label, fn in _TESTS:
        print("=== %s ===" % label)
        try:
            failed += (fn() or 0)
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print("FAIL %s: %s" % (label, exc))
    print("\n%d test(s) run; %d failed" % (len(_TESTS), failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
