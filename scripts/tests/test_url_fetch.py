#!/usr/bin/env python3
"""Regression tests for url_fetch.py — runnable with plain Python (no pytest needed).

Pins down the 2026-09-14 regression in which ``PinnedHandler.__init__`` did not
initialise the base handler, so every pinned request failed with::

    AttributeError: 'PinnedHandler' object has no attribute '_debuglevel'

(``do_open()`` reads ``self._debuglevel``; it is set by
``urllib.request.AbstractHTTPHandler.__init__``.)

Usage:
    python scripts/tests/test_url_fetch.py     # exits non-zero on failure
"""
import gzip
import os
import sys
import urllib.request
import zlib

_HERE = os.path.dirname(os.path.abspath(__file__))
_SCRIPTS = os.path.dirname(_HERE)
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

from url_fetch import PinnedHandler, _decode_body  # noqa: E402


class _StopHere(Exception):
    """Sentinel: do_open() got past the ``self._debuglevel`` access."""


class _FakeHTTPConnection:
    """Stands in for http.client.HTTPConnection so do_open() can be driven offline."""

    def __init__(self, host, timeout=None, **kwargs):
        self.host = host

    def set_debuglevel(self, level):
        self.debuglevel = level

    def request(self, *args, **kwargs):
        pass

    def getresponse(self):
        raise _StopHere("reached the connection layer")

    def close(self):
        """do_open() closes the connection on the way out of its error path."""


def test_pinned_handler_has_debuglevel():
    """Base-handler state must exist immediately after construction."""
    handler = PinnedHandler()
    assert hasattr(handler, "_debuglevel"), (
        "PinnedHandler must initialise AbstractHTTPHandler state; "
        "do_open() reads self._debuglevel"
    )
    assert handler.allow_internal is False


def test_pinned_handler_do_open_reaches_connection():
    """do_open() must not raise AttributeError (the regression being pinned down)."""
    handler = PinnedHandler()
    request = urllib.request.Request("http://example.com/")
    request.timeout = 30  # built_opener().open(..., timeout=) sets this in real use;
    #                      do_open() reads req.timeout *before* self._debuglevel,
    #                      so it must be present for this test to reach the bug
    try:
        handler.do_open(_FakeHTTPConnection, request)
    except AttributeError as exc:  # the bug itself
        raise AssertionError("do_open() raised AttributeError: %s" % exc)
    except Exception:  # any other error => execution passed the _debuglevel access
        return
    raise AssertionError("do_open() unexpectedly returned without contacting anything")


def test_decode_body_undoes_gzip():
    """gzip must be decompressed, not decoded as raw bytes (silent mojibake).

    Regression: https://www.python.org/ answers `content-encoding: gzip`; without
    decompression the converted Markdown was unreadable yet the tool exited 0.
    """
    html = "<html><body><p>hello 世界</p></body></html>"
    assert _decode_body(gzip.compress(html.encode("utf-8")),
                        "gzip", "text/html; charset=utf-8") == html


def test_decode_body_undoes_deflate_and_passes_plain_through():
    html = "<html><body>plain</body></html>"
    encoded = html.encode("utf-8")
    assert _decode_body(encoded, None, "text/html") == html
    assert _decode_body(encoded, "", "text/html") == html
    assert _decode_body(zlib.compress(encoded), "deflate", "text/html") == html
    # raw deflate (no zlib wrapper) must work too
    compressor = zlib.compressobj(wbits=-zlib.MAX_WBITS)
    raw_deflate = compressor.compress(encoded) + compressor.flush()
    assert _decode_body(raw_deflate, "deflate", "text/html") == html


def test_decode_body_honours_declared_charset():
    html = "<html><body>中文</body></html>"
    assert _decode_body(html.encode("gb18030"), None, "text/html; charset=gb18030") == html


def main():
    tests = [
        test_pinned_handler_has_debuglevel,
        test_pinned_handler_do_open_reaches_connection,
        test_decode_body_undoes_gzip,
        test_decode_body_undoes_deflate_and_passes_plain_through,
        test_decode_body_honours_declared_charset,
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
