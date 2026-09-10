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


def render_with_browser(url, browser, virtual_time=8000, allow_internal=False):
    # Defense-in-depth: re-verify the target INSIDE this function so the browser
    # is never launched for an internal/private URL even if an upstream guard
    # were skipped. --allow-internal (trusted local dev) still overrides.
    try:
        from url_security import _is_blocked_target
    except ImportError:  # used standalone without the package; upstream guard applies
        _is_blocked_target = None
    if _is_blocked_target is not None:
        blocked, reason = _is_blocked_target(url, allow_internal)
        if blocked:
            print("[spa-fallback] in-function SSRF re-check refused target: %s" % reason,
                  file=sys.stderr)
            return None
    html_path = _make_temp_html("mid_render_")
    # Sandbox-first strategy: keep Chromium's sandbox enabled whenever possible.
    # --no-sandbox is only used when it is actually required (running as root) or
    # when the sandboxed launch crashed with the typical namespace error seen in
    # restricted containerized environments. The SSRF guard already refuses
    # internal/loopback targets, so the browser is only pointed at public URLs.
    base = [browser, "--headless=new", "--disable-gpu",
            f"--virtual-time-budget={virtual_time}", "--dump-dom", url]
    is_root = hasattr(os, "getuid") and os.getuid() == 0
    if is_root:
        attempts = [base + ["--no-sandbox"]]
    else:
        attempts = [base, base + ["--no-sandbox"]]
    last_err = None
    try:
        for i, cmd in enumerate(attempts):
            try:
                with open(html_path, "w", encoding="utf-8", errors="ignore") as fh:
                    subprocess.run(
                        cmd, stdout=fh, stderr=subprocess.DEVNULL, timeout=90,
                        check=True,
                    )
                if i > 0:
                    print("[spa-fallback] sandboxed launch failed; retried with "
                          "--no-sandbox (browser sandbox disabled)", file=sys.stderr)
                return html_path
            except FileNotFoundError:
                raise  # browser binary missing; retrying cannot help
            except subprocess.TimeoutExpired:
                raise  # page too slow; retrying with --no-sandbox cannot help
            except subprocess.CalledProcessError as e:
                last_err = e  # typical root/namespace crash -> retry sandboxless
        raise last_err
    except Exception as e:  # noqa: BLE001
        if os.path.exists(html_path):
            try:
                os.unlink(html_path)
            except OSError:
                pass
        print(f"[spa-fallback] browser render failed: {e}", file=sys.stderr)
        return None


class ValidatingRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Re-check every redirect hop against the SSRF guard before following it.

    urllib follows 3xx automatically, which would otherwise let a public URL
    bounce the request to a loopback address, the cloud metadata endpoint,
    or other private/internal address space.
    """

    def __init__(self, allow_internal=False):
        self.allow_internal = allow_internal

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        try:
            from url_security import _is_blocked_target
        except ImportError:  # package used standalone; default urllib behaviour
            return super().redirect_request(req, fp, code, msg, headers, newurl)
        blocked, reason = _is_blocked_target(newurl, self.allow_internal)
        if blocked:
            raise urllib.error.HTTPError(
                req.full_url, code,
                "redirect target refused by SSRF guard: %s" % reason, headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def safe_urlopen(req, timeout=40, allow_internal=False):
    """urlopen with redirect-target validation (defense in depth)."""
    opener = urllib.request.build_opener(ValidatingRedirectHandler(allow_internal))
    return opener.open(req, timeout=timeout)


def fetch_html(url, timeout=40, allow_internal=False):
    """Fetch raw HTML with a full browser UA. Returns decoded text or raises."""
    headers = {
        "User-Agent": BROWSER_UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
                  "image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    req = urllib.request.Request(url, headers=headers)
    return safe_urlopen(req, timeout=timeout,
                        allow_internal=allow_internal).read().decode("utf-8", "ignore")
