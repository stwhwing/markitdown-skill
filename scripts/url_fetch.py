#!/usr/bin/env python3
"""url_fetch.py — HTML retrieval, temp-file helpers and headless rendering.

Split out of ``url_to_markdown.py``: everything concerned with *getting* the
bytes (browser UA fetch, temp HTML files, invoking markitdown, locating and
driving a headless browser) lives here. Content *judgement* lives in
``content_detect.py``; security *policy* lives in ``url_security.py``.
"""
import http.client
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
from functools import partial

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


def _validated_markitdown_bin(raw):
    """Strict-allowlist validation for the MARKITDOWN_BIN override.

    Returns the absolute path when it is safe to execute, else ``None`` (the
    caller then falls back to ``python -m markitdown``). Rejected on purpose:

    - empty / non-absolute paths (a relative name would be resolved against
      PATH and could pick up an unrelated or attacker-planted program);
    - paths that are not a regular file;
    - on POSIX only: files that are not executable, or are writable by group /
      other (a shared-writable binary can be swapped between this check and
      exec — TOCTOU tampering).

    Reading an executable location from the environment is only safe when the
    value is pinned: an unrestricted env var can otherwise redirect execution
    to an attacker-controlled program.
    """
    v = (raw or "").strip()
    if not v or not os.path.isabs(v):
        return None
    try:
        st = os.stat(v)
    except OSError:
        return None
    if not os.path.isfile(v):
        return None
    if os.name != "nt":
        # Windows has no POSIX mode bits: os.chmod cannot set X_OK and every
        # file reports 0o666, so these checks would reject all binaries there.
        if not os.access(v, os.X_OK):
            return None
        if st.st_mode & 0o022:  # group- or world-writable -> not trusted
            return None
    return v


def markitdown_cmd():
    """Return a command prefix that runs markitdown via the current interpreter.

    MARKITDOWN_BIN is honoured only after strict validation (absolute path,
    regular executable file, not group/world-writable); anything else is
    ignored and the trusted ``python -m markitdown`` module path is used.
    """
    env_bin = _validated_markitdown_bin(os.environ.get("MARKITDOWN_BIN"))
    if env_bin:
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
    # Pin the hostname to its validated address for the renderer as well, so a
    # rebinding resolver cannot send the browser to an internal address. The
    # mapping only covers this hostname (sub-resource hosts are untested by
    # design — see the documented limitation in SKILL.md).
    pin_rule = None
    try:
        from url_security import resolve_and_check
        _host = urllib.parse.urlparse(url).hostname or ""
        _blocked_dns, _reason_dns = resolve_and_check(_host, allow_internal)
        if _blocked_dns:
            print("[spa-fallback] in-function DNS re-check refused target: %s" % _reason_dns,
                  file=sys.stderr)
            return None
        _ip = _resolve_first_ipv4(_host)
        if _ip and _host and _host != _ip:
            pin_rule = "MAP %s %s" % (_host, _ip)
    except Exception:  # noqa: BLE001 - pinning is best effort, never fatal
        pin_rule = None
    html_path = _make_temp_html("mid_render_")
    # Sandbox-first strategy: keep Chromium's sandbox enabled whenever possible.
    # --no-sandbox is only used when it is actually required (running as root) or
    # when the sandboxed launch crashed with the typical namespace error seen in
    # restricted containerized environments. The SSRF guard already refuses
    # internal/loopback targets, so the browser is only pointed at public URLs.
    base = [browser, "--headless=new", "--disable-gpu",
            f"--virtual-time-budget={virtual_time}", "--dump-dom", url]
    if pin_rule:
        base.insert(1, "--host-resolver-rules=%s" % pin_rule)
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


class _PinnedHTTPConnection(http.client.HTTPConnection):
    """HTTP connection whose TCP peer is a pre-validated IP (DNS pinning).

    The ``Host`` header still comes from the original request, so virtual
    hosting keeps working; only the socket destination is pinned.
    """

    def __init__(self, *args, pinned_ip=None, **kwargs):
        self._pinned_ip = pinned_ip
        super().__init__(*args, **kwargs)

    def connect(self):
        self.sock = socket.create_connection(
            (self._pinned_ip, self.port), self.timeout, self.source_address)


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """HTTPS variant: pins the socket but keeps SNI / cert checks on the hostname."""

    def __init__(self, *args, pinned_ip=None, **kwargs):
        self._pinned_ip = pinned_ip
        super().__init__(*args, **kwargs)

    def connect(self):
        sock = socket.create_connection(
            (self._pinned_ip, self.port), self.timeout, self.source_address)
        # server_hostname must stay the ORIGINAL hostname (not the IP) so that
        # SNI and certificate verification still validate the real site.
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


def _resolve_first_ipv4(host):
    """First IPv4 address for host (None when unresolvable)."""
    try:
        for info in socket.getaddrinfo(host, None):
            ip = info[4][0]
            if ":" not in ip:
                return ip
    except Exception:
        return None
    return None


class PinnedHandler(urllib.request.HTTPHandler, urllib.request.HTTPSHandler):
    """Resolve -> validate -> PIN, re-done for every hop (redirects included).

    Pinning closes the DNS-rebinding TOCTOU window: the socket connects to the
    exact address that passed the SSRF guard instead of letting the resolver
    answer twice. Delegates everything else to the shared handler logic.
    """

    def __init__(self, allow_internal=False):
        self.allow_internal = allow_internal

    def _pin_for(self, url):
        host = urllib.parse.urlparse(url).hostname or ""
        try:
            from url_security import resolve_and_check
        except ImportError:  # standalone use; upstream guard applies
            return None
        blocked, reason = resolve_and_check(host, self.allow_internal)
        if blocked:
            raise urllib.error.URLError("refused by pin-guard: %s" % reason)
        try:
            infos = socket.getaddrinfo(host, None)
        except Exception:
            return None
        for info in infos:
            ip = info[4][0]
            if ":" in ip:  # prefer IPv4 for maximum compatibility
                continue
            return ip
        return infos[0][4][0] if infos else None

    def http_open(self, req):
        ip = self._pin_for(req.full_url)
        return self.do_open(partial(_PinnedHTTPConnection, pinned_ip=ip), req)

    def https_open(self, req):
        ip = self._pin_for(req.full_url)
        return self.do_open(partial(_PinnedHTTPSConnection, pinned_ip=ip), req)


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


def safe_urlopen(req, timeout=40, allow_internal=False, strict_pin=False):
    """urlopen with redirect-target validation and (when possible) DNS pinning.

    Proxy policy — deliberate and documented, because it decides whether pinning
    can work at all:
      * default (strict_pin=False): honour the environment/system proxy. When a
        proxy is in effect the proxy performs the connection, so pinning is
        skipped (and a one-off notice is printed); otherwise the request is
        pinned to the validated IP.
      * strict_pin=True: bypass the proxy (``ProxyHandler({})``) and always pin.
        Only use where direct egress is available.
    """
    handlers = [ValidatingRedirectHandler(allow_internal)]
    proxies = urllib.request.getproxies()
    if strict_pin:
        handlers.insert(0, urllib.request.ProxyHandler({}))
        handlers.append(PinnedHandler(allow_internal))
    elif not _proxy_applies(req.full_url, proxies):
        handlers.append(PinnedHandler(allow_internal))
    else:
        _warn_pin_skipped_once()
    opener = urllib.request.build_opener(*handlers)
    return opener.open(req, timeout=timeout)


_PIN_NOTICE_SHOWN = [False]


def _warn_pin_skipped_once():
    if not _PIN_NOTICE_SHOWN[0]:
        _PIN_NOTICE_SHOWN[0] = True
        print("[security] an HTTP proxy is in effect: DNS pinning is skipped "
              "(the proxy performs the connection). Use --strict-pin to bypass "
              "the proxy and pin anyway.", file=sys.stderr)


def _proxy_applies(url, proxies):
    try:
        return urllib.request.proxy_bypass(urllib.parse.urlparse(url).hostname or "") is False \
            and bool(proxies.get("http") or proxies.get("https"))
    except Exception:
        return bool(proxies)


def fetch_html(url, timeout=40, allow_internal=False, strict_pin=False):
    """Fetch raw HTML with a full browser UA. Returns decoded text or raises."""
    headers = {
        "User-Agent": BROWSER_UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
                  "image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    req = urllib.request.Request(url, headers=headers)
    return safe_urlopen(req, timeout=timeout, allow_internal=allow_internal,
                        strict_pin=strict_pin).read().decode("utf-8", "ignore")
