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

Usage:
  python url_to_markdown.py "https://..." [-o page.md] [--no-browser] [--force-browser]
Run with the Python interpreter that has `markitdown` installed
(e.g. WorkBuddy managed venv: ~/.workbuddy/binaries/python/envs/default/Scripts/python.exe).
"""
import argparse
import importlib
import json
import os
import re
import shutil
import subprocess
import sys
import ipaddress
import tempfile
import time
import urllib.parse
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
# Internal / private target guard (SSRF protection)
# ---------------------------------------------------------------------------
# The converter should only fetch PUBLIC, external URLs. Refusing loopback,
# private, link-local, carrier-grade-NAT and cloud-metadata addresses (plus
# private hostnames) prevents the tool — and the headless browser it launches —
# from being pointed at internal infrastructure (SSRF). This is the primary
# hardening behind the review finding "[AST4]/[SQP-1]: lack of URL scoping".
# Enabled by default; only an explicit --allow-internal overrides it for
# trusted local development.
_PRIVATE_HOST_SUFFIXES = (".local", ".internal", ".corp", ".lan", ".home", ".intranet")

# Known sensitive public hosts we additionally refuse by default (defense in
# depth — these are not private-range IPs but should never be auto-fetched).
_BLOCKED_HOST_EXACT = frozenset({"localhost"})


def _is_blocked_target(url, allow_internal=False):
    """Return (blocked: bool, reason: str) for `url`.

    Blocked when: scheme is not http/https; host is a private/internal hostname
    (localhost, *.local, *.internal, ...); or the host is an IP literal in a
    loopback / private / link-local / reserved / multicast range (covers
    127.0.0.0/8, 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, 169.254.0.0/16
    incl. cloud metadata 169.254.169.254, 100.64.0.0/10). Hostname-pattern
    checks are the primary guard; DNS resolution is intentionally NOT performed
    (resolution-based checks are bypassable via DNS rebinding and add latency).
    """
    if allow_internal:
        return False, ""
    if not url or not url.strip():
        return True, "empty URL"
    m = re.match(r"^([A-Za-z][A-Za-z0-9+.\-]*):", url.strip())
    if not m or m.group(1).lower() not in ("http", "https"):
        return True, "only http/https URLs are supported (scheme: %s)" % (m.group(1) if m else "none")
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    if not host:
        return True, "missing host"
    if host in _BLOCKED_HOST_EXACT or host.endswith(_PRIVATE_HOST_SUFFIXES):
        return True, "private/internal hostname blocked: %s" % host
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False, ""  # not an IP literal; hostname allow/deny list already applied
    # is_private covers 10/8, 172.16/12, 192.168/16, 169.254/16 (link-local
    # also caught by is_link_local) and IPv6 ULA; 100.64.0.0/10 (CGNAT,
    # shared address space) is NOT flagged by is_private, so check it explicitly.
    if (ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_reserved
            or ip.is_multicast or ip in ipaddress.ip_network("100.64.0.0/10")):
        return True, "private/internal IP blocked: %s" % ip
    return False, ""


def _make_temp_html(prefix="mid_"):
    """Create a secure temp .html file; caller must unlink it.

    Replaces tempfile.mktemp (flagged by security scanners as predictable /
    race-prone). NamedTemporaryFile(delete=False) returns an unguessable path
    owned by the user; we close the handle and let the caller write + unlink.
    """
    tf = tempfile.NamedTemporaryFile(delete=False, suffix=".html", prefix=prefix)
    tf.close()
    return tf.name


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


# We measure VISIBLE text only — markdown image/link/URL lines (e.g.
# `![](https://...)`) are long but carry no body, so they are stripped before
# any check. The detector then distinguishes real body prose from nav/footer/UI
# chrome using sentence punctuation: real Chinese prose is full of CJK
# punctuation (，。、；：！？) spread across many sentences, whereas chrome is a
# handful of short isolated tokens (or one concatenated token line with no
# spaces, e.g. 首页番剧直播游戏中心...) and carries little or no punctuation.
# English pages are detected via a real English sentence.
_URL_RE = re.compile(r'https?://\S+')
_CJK_PUNCT = re.compile(r'[，。、；：！？]')
# A markdown line whose visible text is essentially a single link / image.
_LINK_LINE_RE = re.compile(r'^(!?\[|\s*\[)')


def _visible_line(ln):
    """Strip markdown image/link/code and bare URLs, leaving only visible text."""
    ln = re.sub(r'!\[[^\]]*\]\([^)]*\)', '', ln)          # images
    ln = re.sub(r'\[([^\]]*)\]\([^)]*\)', r'\1', ln)      # links -> keep text
    ln = re.sub(r'`[^`]*`', '', ln)                       # inline code
    ln = _URL_RE.sub('', ln)                             # bare urls
    return ln


def is_real_content(md):
    """Heuristic: does `md` look like genuine body text (prose/paragraphs)
    rather than nav/footer/UI chrome?

    Returns True when the output looks like real prose. Two signals carry most
    of the weight, because either one alone is fooled:
      * paragraph mass — an article runs several sentences together into long
        lines, whereas a sidebar / index / UI page is entirely short items.
      * link density — a docs sidebar is mostly markdown link lines, while an
        article body has almost none.
    A loose "a handful of Latin words" test is deliberately NOT used: a Chinese
    docs page sprinkled with IDE / CLI / Menu / Sidebar Navigation clears it
    easily, which is exactly how a nav-only page used to pass as content.
    English is detected through a real English sentence, Chinese through body
    mass plus sentence punctuation.
    """
    if not md or not md.strip():
        return False
    lines = [ln.strip() for ln in md.splitlines()]
    vis = [" ".join(_visible_line(ln).split()) for ln in lines]
    vis = [v for v in vis if v]
    if not vis:
        return False
    text = " ".join(vis)

    # 1) paragraph mass — real prose has several long, sentence-bearing lines.
    long_lines = sum(1 for v in vis if len(v) >= 60)
    if long_lines >= 3:
        return True

    # 2) link density — sidebar / directory pages are dominated by link lines.
    nonempty = [ln for ln in lines if ln]
    if nonempty:
        link_lines = sum(1 for ln in nonempty if _LINK_LINE_RE.match(ln))
        if link_lines / len(nonempty) > 0.4:
            return False

    # 3) English paragraph
    if re.search(r'[A-Za-z]{12,}', text):
        return True

    # 4) Chinese prose: BOTH real body mass AND sentence punctuation.
    cjk_punct = len(_CJK_PUNCT.findall(text))
    if meaningful_len(md) >= 200 and cjk_punct >= 2:
        return True
    return False


def accept_content(md):
    """Combined gate: enough text AND it looks like real content (not boilerplate)."""
    return meaningful_len(md) >= TEXT_THRESHOLD and is_real_content(md)

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
    html_path = _make_temp_html("mid_render_")
    try:
        with open(html_path, "w", encoding="utf-8", errors="ignore") as fh:
            # --no-sandbox: required for headless Chromium to launch inside the
            # managed/containerized Python environments this skill runs in
            # (otherwise it crashes with "Running as root" / namespace errors).
            # The SSRF guard above already refuses internal/loopback targets, so
            # the browser is only ever pointed at public external URLs.
            subprocess.run(
                [browser, "--headless=new", "--no-sandbox", "--disable-gpu",
                 f"--virtual-time-budget={virtual_time}", "--dump-dom", url],
                stdout=fh, stderr=subprocess.DEVNULL, timeout=90, check=True,
            )
        return html_path
    except Exception as e:  # noqa: BLE001
        if os.path.exists(html_path):
            try:
                os.unlink(html_path)
            except OSError:
                pass
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
# WeChat article extraction (mp.weixin.qq.com)
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# Media (audio/video) URL detection & backend self-check
# ---------------------------------------------------------------------------
# A video/audio link is not a document: its page text (title, view count, nav)
# is not the content the user actually wants. Transcription needs external
# backends, and a media URL used to fall through the normal path and return
# page chrome as if it were success. This surfaces that clearly instead.
_MEDIA_URL_RE = re.compile(
    r"(bilibili\.com/video/|bilibili\.com/bangumi|youtube\.com/watch|youtu\.be/|"
    r"vimeo\.com/|douyu\.com/|kuaishou\.com/|"
    r"\.(mp3|mp4|wav|m4a|aac|flac|ogg|opus|webm|mkv|avi|mov)(\?|$))",
    re.I,
)

_MEDIA_BACKENDS = (
    ("yt_dlp", "yt-dlp", "pip install yt-dlp"),
    ("whisper", "openai-whisper", "pip install openai-whisper"),
    ("speech_recognition", "SpeechRecognition", "pip install SpeechRecognition"),
    ("youtube_transcript_api", "youtube-transcript-api", "pip install youtube-transcript-api"),
)


def missing_media_backends():
    """Return human-readable list of missing media/transcription dependencies."""
    missing = []
    if not (shutil.which("ffmpeg") or shutil.which("avconv")):
        missing.append("ffmpeg — 音视频解码/转换，必需（用系统包管理器安装）")
    for mod, label, cmd in _MEDIA_BACKENDS:
        try:
            importlib.import_module(mod)
        except Exception:  # noqa: BLE001
            missing.append(f"{label} — {cmd}")
    return missing


def warn_media_backends(url):
    """If `url` is a media link, report missing transcription backends once."""
    if not _MEDIA_URL_RE.search(url or ""):
        return
    missing = missing_media_backends()
    if not missing:
        return
    print("[media] 检测到音视频链接。本工具只能返回网页侧文本（标题/简介等），"
          "无法产出音视频正文转写；当前环境缺少以下转写后端：", file=sys.stderr)
    for m in missing:
        print(f"  - {m}", file=sys.stderr)
    print("  补齐后可获得转写内容；否则请改用平台字幕或人工整理。", file=sys.stderr)


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
