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
  2. If the extracted text is suspiciously short (likely an SPA shell),
     automatically fall back to rendering the page with a headless
     Chromium/Chrome/Edge (`--dump-dom`, which executes JS) and feed the
     rendered DOM back to markitdown.
  3. If no browser is available, attempt to extract embedded SSR/JSON data
     (`__NEXT_DATA__`, `window.__INITIAL_STATE__`, <script type="application/json">).
  4. As a last resort, print a clear hint to use the WebFetch tool (which
     server-side renders).

Usage:
  python url_to_markdown.py "https://..." [-o page.md] [--no-browser] [--force-browser]
Run with the Python interpreter that has `markitdown` installed
(e.g. WorkBuddy managed venv: ~/.workbuddy/binaries/python/envs/default/Scripts/python.exe).
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request

TEXT_THRESHOLD = 120  # meaningful chars below which we treat the page as a likely SPA shell

# Full browser UA — many sites (notably mp.weixin.qq.com / WeChat) block requests
# with a bare or library UA and serve an "环境异常" anti-bot challenge page. A
# realistic Chrome UA lets us fetch the real HTML so markitdown can extract text.
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# ---------------------------------------------------------------------------
# markitdown invocation
# ---------------------------------------------------------------------------
def markitdown_cmd():
    """Return a command prefix that runs markitdown via the current interpreter."""
    env_bin = os.environ.get("MARKITDOWN_BIN")
    if env_bin and os.path.exists(env_bin):
        return [env_bin]
    # Run as a module with the same interpreter that has markitdown installed
    return [sys.executable, "-m", "markitdown"]

def run_markitdown_on_file(html_path):
    return subprocess.run(markitdown_cmd() + [html_path], capture_output=True, text=True)

def meaningful_len(text):
    """Length of text after stripping code, links and whitespace noise."""
    t = re.sub(r"```[\s\S]*?```", " ", text)
    t = re.sub(r"`[^`]*`", " ", t)
    t = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", t)
    t = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", t)
    t = re.sub(r"\s+", "", t)
    return len(t)

# ---------------------------------------------------------------------------
# Browser detection & rendering
# ---------------------------------------------------------------------------
def find_browser():
    candidates = [
        r"C:/Program Files/Google/Chrome/Application/chrome.exe",
        r"C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
        r"C:/Program Files/Microsoft/Edge/Application/msedge.exe",
        r"C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
        "google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome", "msedge",
    ]
    for c in candidates:
        if os.path.exists(c) or shutil.which(c):
            return c
    return None

def render_with_browser(url, browser, virtual_time=8000):
    html_path = tempfile.mktemp(suffix=".html")
    try:
        with open(html_path, "w", encoding="utf-8", errors="ignore") as fh:
            subprocess.run(
                [browser, "--headless=new", "--no-sandbox", "--disable-gpu",
                 f"--virtual-time-budget={virtual_time}", "--dump-dom", url],
                stdout=fh, stderr=subprocess.DEVNULL, timeout=90, check=True,
            )
        return html_path
    except Exception as e:  # noqa: BLE001
        if os.path.exists(html_path):
            os.unlink(html_path)
        print(f"[spa-fallback] browser render failed: {e}", file=sys.stderr)
        return None

# ---------------------------------------------------------------------------
# HTML fetch (browser UA, anti-bot bypass)
# ---------------------------------------------------------------------------
def fetch_html(url, timeout=40):
    """Fetch raw HTML with a full browser UA. Returns decoded text or raises."""
    headers = {
        "User-Agent": BROWSER_UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
                  "image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    req = urllib.request.Request(url, headers=headers)
    return urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", "ignore")

# ---------------------------------------------------------------------------
# JSON / SSR extraction (no browser)
# ---------------------------------------------------------------------------
def extract_embedded_json(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": BROWSER_UA})
        raw = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "ignore")
    except Exception as e:  # noqa: BLE001
        print(f"[spa-fallback] fetch failed: {e}", file=sys.stderr)
        return None
    # Next.js / Nuxt __NEXT_DATA__
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>([\s\S]*?)</script>', raw)
    if m:
        return m.group(1).strip()
    # generic application/json blocks
    blocks = re.findall(r'<script[^>]*type="application/json"[^>]*>([\s\S]*?)</script>', raw)
    if blocks:
        return "\n\n".join(b.strip() for b in blocks)
    # window.__INITIAL_STATE__ = {...};
    m = re.search(r'window\.__INITIAL_STATE__\s*=\s*(\{[\s\S]*?\});', raw)
    if m:
        return m.group(1).strip()
    return None

# ---------------------------------------------------------------------------
# Recursive flatten of embedded JSON → compact Markdown (token-saving)
# ---------------------------------------------------------------------------
# Keys whose values are almost always framework/boilerplate, never content.
_SKIP_KEYS = {
    "css", "script", "scripts", "styles", "style", "chunks", "head",
    "webpack", "_nextI18Next", "dynamicIds", "runtimeConfig", "buildId",
    "amp", "apis", "__proto__", "prototype", "constructor",
    "staticQueryResults", "staticQueryResult", "pageContext",
}

_CJK = re.compile(r"[\u4e00-\u9fff]")


def _looks_like_content(s):
    """Heuristic: keep only prose-like strings, drop encoded/css/url noise."""
    s = s.strip()
    if not s or len(s) < 12:
        return False
    if s.startswith(("data:", "http://", "https://", "//", "blob:", "mailto:")):
        return False
    # long single-token blobs (base64 / minified) with no spaces and no CJK
    if len(s) > 200 and " " not in s and not _CJK.search(s):
        return False
    if _CJK.search(s):
        return True
    return s.count(" ") >= 2


def _recursive_collect(obj, out, max_items=400, max_list=80):
    """Walk the JSON tree, collecting content-bearing string leaves only."""
    if len(out) >= max_items:
        return
    if isinstance(obj, dict):
        for v in obj.values():
            _recursive_collect(v, out, max_items, max_list)
    elif isinstance(obj, list):
        for item in obj[:max_list]:
            _recursive_collect(item, out, max_items, max_list)
    elif isinstance(obj, str):
        if _looks_like_content(obj):
            out.append(obj.strip())


def json_to_markdown(json_str, max_chars=20000):
    """Parse embedded SSR/JSON and return compact prose Markdown.

    Replaces the old behaviour of dumping the whole __NEXT_DATA__ blob (often
    10–20 KB) inline. A recursive flatten keeps only content-bearing string
    leaves, cutting the SPA-fallback token footprint dramatically.
    """
    try:
        data = json.loads(json_str)
    except Exception:
        return None
    out = []
    _recursive_collect(data, out)
    if not out:
        return None
    text = "\n\n".join(out)
    if len(text) > max_chars:
        text = text[:max_chars] + "\n\n… (truncated)"
    return (f"<!-- content extracted from SPA embedded JSON "
            f"(recursive flatten) -->\n\n{text}\n")


# ---------------------------------------------------------------------------
# emit
# ---------------------------------------------------------------------------
def emit(md, out):
    if out:
        with open(out, "w", encoding="utf-8") as f:
            f.write(md)
    else:
        sys.stdout.write(md)

# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Convert a URL to Markdown with SPA fallback")
    ap.add_argument("url")
    ap.add_argument("-o", "--output", help="Write markdown to this file (default: stdout)")
    ap.add_argument("--no-browser", action="store_true", help="Skip browser fallback")
    ap.add_argument("--force-browser", action="store_true", help="Always use browser render")
    ap.add_argument("--virtual-time-budget", type=int, default=8000,
                    help="Virtual time (ms) for SPA JS to run (default 8000)")
    args = ap.parse_args()

    # 1) fetch with browser UA, then convert the fetched HTML file via markitdown.
    #    Using our own UA-aware fetch (instead of markitdown's internal GET) defeats
    #    WeChat-style anti-bot challenges that would otherwise return an empty page.
    direct_md = ""
    if not args.force_browser:
        try:
            raw = fetch_html(args.url)
            tmp_html = tempfile.mktemp(suffix=".html")
            with open(tmp_html, "w", encoding="utf-8", errors="ignore") as fh:
                fh.write(raw)
            res = run_markitdown_on_file(tmp_html)
            os.unlink(tmp_html)
            direct_md = res.stdout or ""
        except Exception as e:  # noqa: BLE001
            print(f"[fetch] direct fetch failed: {e}", file=sys.stderr)
        if meaningful_len(direct_md) >= TEXT_THRESHOLD:
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
            os.unlink(html)
            if meaningful_len(md) >= TEXT_THRESHOLD:
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
        print("[spa-fallback] returning best-effort content (page may be a JS-rendered SPA). "
              "For full fidelity ensure a browser (Chrome/Edge/Chromium) is installed or use the "
              "WebFetch tool.", file=sys.stderr)
        emit(best, args.output)
        return

    print("[spa-fallback] Could not extract meaningful content. The page is a JS-rendered SPA "
          "and no headless browser / embedded JSON was available. Try the WebFetch tool, or run "
          "with a browser installed (Chrome/Edge on Windows, chromium on Linux).", file=sys.stderr)
    sys.exit(2)

if __name__ == "__main__":
    main()
