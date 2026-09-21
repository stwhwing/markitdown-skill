#!/usr/bin/env python3
"""
url_to_markdown.py — Convert a web URL to Markdown, with automatic SPA
(JavaScript-rendered Single Page App) fallback.

WHY: `markitdown <url>` only performs a plain HTTP GET and converts the raw
HTML. It does NOT execute JavaScript. Pages whose content is injected
client-side (React/Vue/Next.js SPAs, often served via CDNs such as Tencent
Cloud CDN) therefore yield an empty <div id="root"> and ~0 bytes of text.

HOW THIS WRAPPER HELPS:
  1. Fetch the page with a full browser User-Agent (defeats anti-bot challenges
     like WeChat / mp.weixin.qq.com that serve an "环境异常" blank page to bare
     or library UAs), then convert the fetched HTML via markitdown.
  2. If the extracted text looks like nav/footer/UI chrome or is suspiciously
     short (likely an SPA shell / empty body), do NOT treat it as success —
     instead fall back to rendering the page with a headless
     Chromium/Chrome/Edge (`--dump-dom`, which executes JS) and feed the
     rendered DOM back to markitdown.
  3. If no browser is available, attempt to extract embedded SSR/JSON data
     (`__NEXT_DATA__`, `window.__INITIAL_STATE__`, <script type="application/json">).
  4. As a last resort, print a clear hint to use the WebFetch tool (which
     server-side renders).

LAYOUT: this file is the CLI entry point and orchestration only. The moving
parts live in sibling modules next to it:
  url_security.py   — SSRF / private-target guard
  url_fetch.py      — UA fetch, temp files, markitdown invocation, headless render
  content_detect.py — "is this real content or UI chrome?" heuristics
  spa_extract.py    — embedded-JSON flattening + WeChat article extraction
  media_detect.py   — audio/video URL detection & missing-backend warnings

Usage:
  python url_to_markdown.py "https://..." [-o page.md] [--no-browser] [--force-browser]
Run with the Python interpreter that has `markitdown` installed
(eg. WorkBuddy managed venv: ~/.workbuddy/binaries/python/envs/default/Scripts/python.exe).
"""
import argparse
import datetime
import hashlib
import json
import os
import re
import sys
import tempfile

# Make sibling modules importable no matter how the script is invoked
# (direct path, `python -m`, or imported from another directory).
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from content_detect import accept_content, is_real_content, meaningful_len      # noqa: E402
from media_detect import warn_media_backends                                    # noqa: E402
from spa_extract import (extract_embedded_json, extract_wechat_article,         # noqa: E402
                         json_to_markdown)
from url_fetch import (_make_temp_html, fetch_html, find_browser,               # noqa: E402
                       render_with_browser, run_markitdown_on_file)
from url_security import _is_blocked_target, resolve_and_check                  # noqa: E402


# ---------------------------------------------------------------------------
# output helpers (atomic write + manifest + prompt-injection boundary)
# ---------------------------------------------------------------------------
def _atomic_write_text(path, text):
    """Write `text` to `path` atomically: temp file then os.replace.

    A crash mid-write leaves no half-written file behind, and a reader never
    sees a partial document. os.replace is atomic on both POSIX and Windows.
    """
    d = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(dir=d, suffix=".md.tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def emit(md, out):
    if out:
        _atomic_write_text(out, md)
    else:
        sys.stdout.write(md)


# Active-content / prompt-injection boundaries. Web page text is UNTRUSTED DATA,
# not instructions: a hostile page could embed "ignore previous instructions …".
_SCRIPT_RE = re.compile(r"<script\b[^>]*>.*?</script>", re.I | re.S)
_STYLE_RE = re.compile(r"<style\b[^>]*>.*?</style>", re.I | re.S)
_JS_URI_RE = re.compile(r"(]\(\s*|\!\[\]?\()\s*(?:javascript|data):", re.I)


def _sanitize_markdown(md, src):
    """Strip active content and fence the payload with external-content markers.

    Best-effort, not a security boundary: drops <script>/<style> blocks,
    neutralises javascript:/data: URIs in markdown links/images, and wraps the
    whole result between explicit boundary markers so downstream consumers can
    treat it strictly as data and ignore any embedded "instructions".
    """
    body = _SCRIPT_RE.sub("", md)
    body = _STYLE_RE.sub("", body)
    body = _JS_URI_RE.sub(lambda m: m.group(1) + "sanitized-uri:", body)
    return ("--- EXTERNAL CONTENT [source: %s] ---\n%s\n"
            "--- END EXTERNAL CONTENT ---\n" % (src or "unknown", body))


def _quality_score(md):
    """Heuristic quality assessment of converted markdown (no external calls)."""
    n = meaningful_len(md)
    real = is_real_content(md)
    if n >= 800 and real:
        score = "high"
    elif n >= 200:
        score = "medium"
    else:
        score = "low"
    return {"meaningful_chars": n, "real_content": bool(real), "score": score}


def _write_manifest(path, record):
    """Append one conversion record (JSON line) to the manifest at `path`."""
    try:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as e:
        print("[manifest] could not write %s: %s" % (path, e), file=sys.stderr)


def deliver(md, url, out, manifest_path=None, sanitize=False):
    """Sanitize (opt), write atomically, and append a provenance manifest record."""
    if sanitize:
        md = _sanitize_markdown(md, url)
    emit(md, out)
    if manifest_path:
        rec = {
            "source": url,
            "output": out or "<stdout>",
            "fetched_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "md_bytes": len(md.encode("utf-8", "ignore")),
            "md_sha256": hashlib.sha256(md.encode("utf-8", "ignore")).hexdigest(),
            "quality": _quality_score(md),
        }
        _write_manifest(manifest_path, rec)


# Stable exit codes (documented in SKILL.md) so callers can branch on failure
# type without parsing stderr.
EXIT_OK = 0          # success
EXIT_USAGE = 2       # bad arguments (argparse default)
EXIT_BLOCKED = 3     # refused by the SSRF guard
EXIT_FETCH = 4       # every fetch path failed (network / proxy / DNS / anti-bot)
EXIT_CONTENT = 5     # fetched something but no meaningful content could be extracted
EXIT_OUTPUT = 6      # could not write the output file


def die(code, message, hint=None):
    print("[error] %s" % message, file=sys.stderr)
    if hint:
        print("[hint]  %s" % hint, file=sys.stderr)
    sys.exit(code)


def _ocr_hint():
    """Print a one-line upgrade suggestion for scanned / image-only sources."""
    print("[hint]  If the source is a scanned PDF or image with no selectable "
          "text, try markitdown with Azure Document Intelligence "
          "(--docintel-endpoint) or a local OCR step before converting.",
          file=sys.stderr)


def main():
    ap = argparse.ArgumentParser(description="Convert a URL to Markdown with SPA fallback")
    ap.add_argument("url")
    ap.add_argument("-o", "--output", help="Write markdown to this file (default: stdout)")
    ap.add_argument("--no-browser", action="store_true", help="Skip browser fallback")
    ap.add_argument("--force-browser", action="store_true", help="Always use browser render")
    ap.add_argument("--virtual-time-budget", type=int, default=8000,
                    help="Virtual time (ms) for SPA JS to run (default 8000)")
    ap.add_argument("--allow-internal", action="store_true",
                    help="Override the internal/loopback URL guard (trusted local dev only)")
    ap.add_argument("--strict-pin", action="store_true",
                    help="Bypass the HTTP proxy and pin DNS to the validated IP "
                         "(use only where direct egress is available)")
    ap.add_argument("--sanitize", action="store_true",
                    help="Strip <script>/<style> and javascript:/data: URIs, and wrap "
                         "output in EXTERNAL CONTENT boundary markers (treat as data)")
    ap.add_argument("--manifest", help="Append a JSON-lines provenance/quality record "
                                       "per conversion to this file")
    args = ap.parse_args()

    # SSRF guard — refuse internal/private targets before any fetch/render.
    blocked, reason = _is_blocked_target(args.url, args.allow_internal)
    if blocked:
        die(EXIT_BLOCKED, "refusing to fetch blocked target: %s" % reason,
            "Only public http/https URLs are supported. If this is a trusted "
            "local/intranet page, re-run with --allow-internal.")

    # DNS-level re-validation (best effort — see url_security.resolve_and_check
    # for its TOCTOU caveat; it complements the redirect and in-function checks).
    import urllib.parse as _up
    _host = _up.urlparse(args.url).hostname or ""
    blocked_dns, reason_dns = resolve_and_check(_host, args.allow_internal)
    if blocked_dns:
        die(EXIT_BLOCKED, "refusing to fetch target: %s" % reason_dns,
            "The hostname resolves into a private/loopback range. Use a public "
            "mirror, or --allow-internal for trusted local development.")

    warn_media_backends(args.url)

    # 1) fetch with browser UA, then convert the fetched HTML file via markitdown.
    #    Using our own UA-aware fetch (instead of markitdown's internal GET) defeats
    #    WeChat-style anti-bot challenges that would otherwise return an empty page.
    direct_md = ""
    fetch_error = None
    if not args.force_browser:
        try:
            raw = fetch_html(args.url, allow_internal=args.allow_internal,
                             strict_pin=args.strict_pin)
            # WeChat articles: extract title / account / publish time plus the
            # #js_content body directly, instead of the whole ~3 MB shell.
            wx = extract_wechat_article(raw)
            if wx:
                header_md, body_html = wx
                tmp_body = _make_temp_html("mid_wx_")
                with open(tmp_body, "w", encoding="utf-8", errors="ignore") as fh:
                    fh.write("<html><head><meta charset='utf-8'></head><body>"
                             + body_html + "</body></html>")
                res = run_markitdown_on_file(tmp_body)
                try:
                    os.unlink(tmp_body)
                except OSError:
                    pass
                wx_md = header_md + (res.stdout or "")
                if accept_content(wx_md):
                    direct_md = wx_md
            if not direct_md:
                tmp_html = _make_temp_html("mid_direct_")
                with open(tmp_html, "w", encoding="utf-8", errors="ignore") as fh:
                    fh.write(raw)
                res = run_markitdown_on_file(tmp_html)
                try:
                    os.unlink(tmp_html)
                except OSError:
                    pass
                direct_md = res.stdout or ""
        except Exception as e:  # noqa: BLE001
            fetch_error = e
            print(f"[fetch] direct fetch failed: {e}", file=sys.stderr)
            print("[hint]  Check the URL is reachable (and, if this machine uses a "
                  "proxy, that the proxy allows it). Try --force-browser, or "
                  "--strict-pin when direct egress is available.", file=sys.stderr)
        if accept_content(direct_md):
            deliver(direct_md, args.url, args.output, args.manifest, args.sanitize)
            return

    # 2) browser
    browser = None if args.no_browser else find_browser()
    fallback_md = ""
    if browser:
        html = render_with_browser(args.url, browser, args.virtual_time_budget,
                                   allow_internal=args.allow_internal)
        if html:
            res = run_markitdown_on_file(html)
            md = res.stdout or ""
            try:
                os.unlink(html)
            except OSError:
                pass
            if accept_content(md):
                deliver(md, args.url, args.output, args.manifest, args.sanitize)
                return
            fallback_md = md
            print("[spa-fallback] browser render produced little text; trying JSON extraction",
                  file=sys.stderr)

    # 3) JSON extraction — 递归平铺抽取，只保留正文类字段，从源头缩量
    js = extract_embedded_json(args.url)
    if js:
        md = json_to_markdown(js)
        if not md:
            # flatten produced nothing usable (e.g. non-JSON); keep old raw fallback
            md = f"<!-- embedded JSON extracted from SPA (flatten failed, raw fallback) -->\n\n```json\n{js}\n```\n"
        deliver(md, args.url, args.output, args.manifest, args.sanitize)
        return

    # 4) safety net: never discard content we already have (direct or browser render).
    best = direct_md if meaningful_len(direct_md) >= meaningful_len(fallback_md) else fallback_md
    if best.strip():
        if not is_real_content(best):
            print("[content-warning] extracted text looks like UI/navigation chrome or an empty "
                  "shell (no substantial body detected). The page may be JS-rendered, behind a "
                  "paywall/app reader, or anti-bot blocked. For full fidelity try the WebFetch "
                  "tool, or run with a browser installed (Chrome/Edge on Windows, chromium on "
                  "Linux).", file=sys.stderr)
            _ocr_hint()
        else:
            print("[spa-fallback] returning best-effort content (page may be a JS-rendered SPA). "
                  "For full fidelity ensure a browser (Chrome/Edge/Chromium) is installed or use "
                  "the WebFetch tool.", file=sys.stderr)
        deliver(best, args.url, args.output, args.manifest, args.sanitize)
        return

    if fetch_error is not None and not fallback_md:
        die(EXIT_FETCH, "could not fetch %s: %s" % (args.url, fetch_error),
            "Verify network/proxy/DNS, then retry; --strict-pin bypasses a proxy, "
            "--no-browser skips the renderer.")
    die(EXIT_CONTENT,
        "fetched the page but could not extract meaningful content "
        "(JS-rendered SPA, paywall/app-reader shell, or anti-bot challenge).",
        "Install a browser for the render fallback (Chrome/Edge on Windows, "
        "chromium on Linux) or use the platform's WebFetch tool.")


if __name__ == "__main__":
    main()
