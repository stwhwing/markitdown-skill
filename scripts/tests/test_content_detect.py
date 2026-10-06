#!/usr/bin/env python3
"""Unit tests for content_detect heuristics (pure functions, no network).

Run with: python scripts/tests/test_content_detect.py
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))  # scripts/

from content_detect import (  # noqa: E402
    meaningful_len,
    is_real_content,
    accept_content,
)


def test_meaningful_len_strips_noise():
    assert meaningful_len("  hello world  ") == len("helloworld")
    # markdown links keep their text, inline code is stripped
    assert meaningful_len("[x](http://a) `code`") == len("x")


def test_is_real_content_rejects_empty():
    assert is_real_content("") is False
    assert is_real_content("   ") is False


def test_is_real_content_accepts_chinese_article():
    md = "\n".join(["这是真实的正文内容，描述了产品的功能与使用方法。"] * 12)
    assert is_real_content(md) is True


def test_accept_content_gate():
    # below TEXT_THRESHOLD -> not accepted
    assert accept_content("短") is False
    # clearly real body -> accepted
    long_real = "\n".join(["这是真实的正文内容，描述了产品的功能与使用方法。"] * 12)
    assert accept_content(long_real) is True


def main():
    tests = [
        test_meaningful_len_strips_noise,
        test_is_real_content_rejects_empty,
        test_is_real_content_accepts_chinese_article,
        test_accept_content_gate,
    ]
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
