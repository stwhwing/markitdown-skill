#!/usr/bin/env python3
"""spa_extract.py — Recover content from JS-rendered pages without a browser.

Split out of ``url_to_markdown.py``: the two "no browser available" recovery
paths —
  1. embedded SSR/JSON extraction (__NEXT_DATA__, __INITIAL_STATE__, JSON
     script blocks), recursively flattened into compact Markdown, and
  2. WeChat article extraction (mp.weixin.qq.com), which pulls title / account
     / publish time and the #js_content body out of the ~3 MB page shell.
"""
import json
import os
import re
import sys
import time
import urllib.request

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from content_detect import meaningful_len  # noqa: E402

try:
    from url_fetch import BROWSER_UA
except Exception:  # pragma: no cover - url_fetch always present in the package
    BROWSER_UA = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )


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


# A WeChat article page is a ~3 MB shell: UI chrome ("在小说阅读器读本章" /
# "微信扫一扫" / "轻点两下取消赞"), inline scripts and empty image placeholders.
# Feeding the whole page to markitdown buries the body in chrome. The body lives
# in <div id="js_content">; title / account / publish time live in known
# markers. Extracting them directly yields cleaner, smaller Markdown than the
# full page while keeping every piece of metadata.
_WX_TITLE_RE = re.compile(r'<h1[^>]*id="activity-name"[^>]*>([\s\S]*?)</h1>')
_WX_OG_TITLE_RE = re.compile(r'<meta[^>]*property="og:title"[^>]*content="([^"]+)"')
_WX_NICK_RE = re.compile(r'var\s+nickname\s*=\s*["\']([^"\']*)["\']')
_WX_NAME_RE = re.compile(r'<[^>]*id="js_name"[^>]*>([\s\S]*?)</')
_WX_CT_RE = re.compile(r'var\s+ct\s*=\s*["\']?(\d{10})')
_WX_TIME_RE = re.compile(r'<em[^>]*id="publish_time"[^>]*>([\s\S]*?)</em>')
_WX_BODY_RE = re.compile(r'<div[^>]*id="js_content"[^>]*>([\s\S]*?)<script')


def _strip_tags(h):
    return re.sub(r"\s+", " ", re.sub(r"(?s)<[^>]+>", " ", h)).strip()


def extract_wechat_article(raw):
    """Return (header_markdown, body_html) for a WeChat article, else None.

    Only engages when the page really is a WeChat article carrying a body, so
    reader pages and non-WeChat URLs transparently use the normal path.
    """
    m = _WX_BODY_RE.search(raw)
    if not m:
        return None
    body = m.group(1)
    if meaningful_len(_strip_tags(body)) < 80:
        return None

    title = ""
    mt = _WX_TITLE_RE.search(raw)
    if mt:
        title = _strip_tags(mt.group(1))
    if not title:
        mt = _WX_OG_TITLE_RE.search(raw)
        if mt:
            title = mt.group(1).strip()

    nick = ""
    mn = _WX_NICK_RE.search(raw)
    if mn:
        nick = mn.group(1).strip()
    if not nick:
        mn = _WX_NAME_RE.search(raw)
        if mn:
            nick = _strip_tags(mn.group(1))

    when = ""
    mc = _WX_CT_RE.search(raw)
    if mc:
        try:
            when = time.strftime("%Y-%m-%d %H:%M", time.localtime(int(mc.group(1))))
        except Exception:  # noqa: BLE001
            when = ""
    if not when:
        mc = _WX_TIME_RE.search(raw)
        if mc:
            when = _strip_tags(mc.group(1))

    hdr = f"# {title}\n\n" if title else ""
    bits = [b for b in (nick, when) if b]
    if bits:
        hdr += "> " + " · ".join(bits) + "\n\n"
    if not hdr:
        return None
    return hdr, body
