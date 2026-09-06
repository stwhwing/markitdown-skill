#!/usr/bin/env python3
"""url_fetch.py — HTML retrieval, temp-file helpers and headless rendering.

Split out of ``url_to_markdown.py``: everything concerned with *getting* the
bytes (browser UA fetch, temp HTML files, invoking markitdown, locating and
driving a headless browser) lives here. Content *judgement* lives in
``content_detect.py``; security *policy* lives in ``url_security.py``.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request

# Full browser UA — many sites (notably mp.weixin.qq.com / WeChat) block requests
# with a bare or library UA and serve an "环境异常" anti-bot challenge page. A
# realistic Chrome UA lets us fetch the real HTML so markitdown can extract text.
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


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
