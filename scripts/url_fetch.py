#!/usr/bin/env python3
"""url_fetch.py — HTML retrieval, temp-file helpers and headless rendering.

Split out of ``url_to_markdown.py``: everything concerned with *getting* the
bytes (browser UA fetch, temp HTML files, invoking markitdown, locating and
driving a headless browser) lives here. Content *judgement* lives in
``content_detect.py``; security *policy* lives in ``url_security.py``.
"""
import gzip
import http.client
import io
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
import zlib
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
        # Windows has no POSIX mode bits (every file reports the same mode),
        # so the executable / ownership checks below are skipped there.
        if not os.access(v, os.X_OK):
            return None
        if st.st_mode & 0o022:  # group/other write access -> not trusted
            return None
    return v


def markitdown_cmd():
    """Return a command prefix that runs markitdown via the current interpreter.

    MARKITDOWN_BIN is honoured only after strict validation (absolute path,
    regular executable file, no group/other write access); anything else is
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
        # Initialise the base-handler state before any request is opened. Without
        # it, do_open() -> h.set_debuglevel(self._debuglevel) raises
        # AttributeError: 'PinnedHandler' object has no attribute '_debuglevel'
        # (reproduced on the deployed Linux host, 2026-09-14).
        #
        # AbstractHTTPHandler.__init__ is called explicitly instead of a bare
        # super().__init__(): the MRO would reach HTTPSHandler.__init__, which
        # also builds an SSL context this handler never uses (it overrides
        # http_open/https_open and drives do_open with its own pinned connection
        # classes) — and that context would be rebuilt on every request.
        urllib.request.AbstractHTTPHandler.__init__(self)
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


# ---- response size limits (SSRF-adjacent hardening) -----------------------
# A misconfigured or hostile host could answer with an unbounded body (e.g. a
# multi-GB stream) and exhaust memory before markitdown even runs. We cap both
# the RAW bytes we buffer and the DECOMPRESSED bytes we keep.
MAX_RESPONSE_BYTES = 32 * 1024 * 1024        # 32 MiB raw body cap
MAX_DECOMPRESSED_BYTES = 64 * 1024 * 1024    # 64 MiB after decompression
MAX_REDIRECT_HOPS = 10                       # refuse redirect loops / chains


def _read_body_limited(resp, max_bytes):
    """Read ``resp`` in bounded chunks, raising if it exceeds ``max_bytes``.

    urllib's ``read()`` with no size streams the whole body into memory; this
    wrapper enforces a hard ceiling and surfaces a clear, catchable error.
    """
    chunks = []
    total = 0
    while True:
        chunk = resp.read(65536)
        if not chunk:
            break
        total += len(chunk)
        chunks.append(chunk)
        if total > max_bytes:
            raise urllib.error.URLError(
                "response body too large (>{0} bytes); refusing to buffer".format(max_bytes))
    return b"".join(chunks)


def _gzip_decompress_bounded(data, limit):
    """Streaming gzip decompress that aborts past ``limit`` bytes (no OOM)."""
    out = io.BytesIO()
    total = 0
    with gzip.GzipFile(fileobj=io.BytesIO(data)) as gz:
        while True:
            chunk = gz.read(65536)
            if not chunk:
                break
            total += len(chunk)
            if total > limit:
                raise ValueError(
                    "decompressed payload exceeds {0} bytes; refusing".format(limit))
            out.write(chunk)
    return out.getvalue()


class ValidatingRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Re-check every redirect hop against the SSRF guard before following it.

    urllib follows 3xx automatically, which would otherwise let a public URL
    bounce the request to a loopback address, the cloud metadata endpoint,
    or other private/internal address space. A per-request hop counter also
    refuses redirect loops / absurdly long chains.
    """

    def __init__(self, allow_internal=False):
        self.allow_internal = allow_internal
        self._hops = 0

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        self._hops += 1
        if self._hops > MAX_REDIRECT_HOPS:
            raise urllib.error.HTTPError(
                req.full_url, code,
                "too many redirects (>{0}); possible redirect loop".format(MAX_REDIRECT_HOPS),
                headers, fp)
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


def _decode_body(raw, content_encoding, content_type=""):
    """Undo ``Content-Encoding`` first, then decode the bytes to text.

    urllib does NOT decompress transparently (unlike ``requests``), so a response
    that arrives gzip/deflate/br-compressed would otherwise be handed straight to
    ``bytes.decode()`` — yielding silent mojibake while the tool still exits 0.
    Observed live (2026-09-15, both the Windows host and the Linux deployment):
    ``https://www.python.org/`` replies ``content-encoding: gzip`` and the
    converted Markdown came out as unreadable bytes.

    Decompressed output is bounded by MAX_DECOMPRESSED_BYTES to stop a small
    compressed body from expanding into a huge in-memory string.
    """
    enc = (content_encoding or "").strip().lower()
    try:
        if enc in ("gzip", "x-gzip"):
            raw = _gzip_decompress_bounded(raw, MAX_DECOMPRESSED_BYTES)
        elif enc == "deflate":
            try:
                raw = zlib.decompress(raw)
            except zlib.error:  # raw deflate without the zlib wrapper
                raw = zlib.decompress(raw, -zlib.MAX_WBITS)
        elif enc == "br":
            import brotli  # optional dependency
            raw = brotli.decompress(raw)
        elif enc == "zstd":
            import zstandard  # optional dependency
            raw = zstandard.ZstdDecompressor().decompress(raw)
    except Exception:  # noqa: BLE001 - unknown/corrupt encoding: use what we got
        pass
    if len(raw) > MAX_DECOMPRESSED_BYTES:
        raise ValueError(
            "decompressed payload exceeds {0} bytes; refusing".format(MAX_DECOMPRESSED_BYTES))
    match = re.search(r"charset=([\w\-]+)", content_type or "", re.I)
    for charset in ([match.group(1)] if match else []) + ["utf-8"]:
        try:
            return raw.decode(charset)
        except (LookupError, UnicodeDecodeError):
            continue
    return raw.decode("utf-8", "ignore")


def fetch_html(url, timeout=40, allow_internal=False, strict_pin=False,
               max_bytes=MAX_RESPONSE_BYTES):
    """Fetch raw HTML with a full browser UA. Returns decoded text or raises.

    `max_bytes` caps the RAW body we will buffer (a body larger than that aborts
    the fetch with a clear error instead of letting memory balloon). Decompressed
    output is additionally bounded by MAX_DECOMPRESSED_BYTES inside _decode_body.
    """
    headers = {
        "User-Agent": BROWSER_UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
                  "image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    req = urllib.request.Request(url, headers=headers)
    with safe_urlopen(req, timeout=timeout, allow_internal=allow_internal,
                      strict_pin=strict_pin) as resp:
        raw = _read_body_limited(resp, max_bytes)
        return _decode_body(raw,
                            resp.headers.get("Content-Encoding"),
                            resp.headers.get("Content-Type"))
