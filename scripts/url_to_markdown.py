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
import os
import sys

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
from url_security import _is_blocked_target                                     # noqa: E402


def emit(md, out):
    if out:
        with open(out, "w", encoding="utf-8") as f:
            f.write(md)
    else:
        sys.stdout.write(md)


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
    args = ap.parse_args()

    # SSRF guard — refuse internal/private targets before any fetch/render.
    blocked, reason = _is_blocked_target(args.url, args.allow_internal)
    if blocked:
        print("[blocked] refusing to fetch blocked target: %s" % reason, file=sys.stderr)
        sys.exit(3)

    warn_media_backends(args.url)

    # 1) fetch with browser UA, then convert the fetched HTML file via markitdown.
    #    Using our own UA-aware fetch (instead of markitdown's internal GET) defeats
    #    WeChat-style anti-bot challenges that would otherwise return an empty page.
    direct_md = ""
    if not args.force_browser:
        try:
            raw = fetch_html(args.url)
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
            print(f"[fetch] direct fetch failed: {e}", file=sys.stderr)
        if accept_content(direct_md):
            emit(direct_md, args.output)
            return

    # 2) browser
    browser = None if args.no_browser else find_browser()
    fallback_md = ""
    if browser:
        html = render_with_browser(args.url, browser, args.virtual_time_budget)
        if html:
            res = run_markitdown_on_file(html)
            md = res.stdout or ""
            try:
                os.unlink(html)
            except OSError:
                pass
            if accept_content(md):
                emit(md, args.output)
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
        emit(md, args.output)
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
        else:
            print("[spa-fallback] returning best-effort content (page may be a JS-rendered SPA). "
                  "For full fidelity ensure a browser (Chrome/Edge/Chromium) is installed or use "
                  "the WebFetch tool.", file=sys.stderr)
        emit(best, args.output)
        return

    print("[spa-fallback] Could not extract meaningful content. The page is a JS-rendered SPA "
          "and no headless browser / embedded JSON was available. Try the WebFetch tool, or run "
          "with a browser installed (Chrome/Edge on Windows, chromium on Linux).", file=sys.stderr)
    sys.exit(2)


if __name__ == "__main__":
    main()
