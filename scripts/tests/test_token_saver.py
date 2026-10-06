#!/usr/bin/env python3
"""Unit tests for token_saver.estimate_tokens (pure heuristic, no network).

Run with: python scripts/tests/test_token_saver.py
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))  # scripts/

from token_saver import estimate_tokens  # noqa: E402


def test_estimate_tokens_approx():
    # ~4 chars per token (English-ish heuristic)
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("abcde") == 1      # 5 // 4 == 1
    assert estimate_tokens("a" * 8) == 2
    assert estimate_tokens("") == 1            # never 0


def main():
    tests = [test_estimate_tokens_approx]
    failed = 0
    for test in tests:
        try:
            test()
            print("PASS %s" % test.__name__)
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print("FAIL %s: %s" % (test.__name__, exc))
    print("%d/%d passed" % (len(tests) - failed, len(tests)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
