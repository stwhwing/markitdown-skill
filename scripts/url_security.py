#!/usr/bin/env python3
"""url_security.py — Internal / private target guard (SSRF protection).

Split out of ``url_to_markdown.py`` so the security-critical guard lives in a
small, self-contained unit that is easy to review and test in isolation.

The converter should only fetch PUBLIC, external URLs. Refusing loopback,
private, link-local, carrier-grade-NAT and cloud-metadata addresses (plus
private hostnames) prevents the tool — and the headless browser it launches —
from being pointed at internal infrastructure (SSRF). This is the primary
hardening behind the review finding "[AST4]/[SQP-1]: lack of URL scoping".
Enabled by default; only an explicit --allow-internal overrides it for
trusted local development.
"""
import ipaddress
import re
import urllib.parse

# Private/internal hostname suffixes that are always refused.
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
