"""Shared helpers for Part 3 backends."""

import ipaddress
import os
import re


def ok(result, **extra):
    response = {"status": "ok", "result": result}
    response.update(extra)
    return response


def error(result):
    return {"status": "error", "result": result}


NOT_FOUND = {"status": "ok", "result": "not_found", "interface": None}
APPLIED = {"status": "ok", "result": "applied"}
DELETED = {"status": "ok", "result": "deleted"}


def not_found():
    return dict(NOT_FOUND)


def found(interface):
    return ok("found", interface=interface)


def map_exception(exc):
    """
    Map an exception to a backend error response.

    Injected fakes and our own real transports raise PermissionError,
    ConnectionError (or TimeoutError) and RuntimeError. Library-specific
    exceptions are normalized here as a final safety net.
    """
    if isinstance(exc, PermissionError):
        return error("authentication_failed")
    if isinstance(exc, (ConnectionError, TimeoutError)):
        return error("connection_failed")

    try:
        import requests

        if isinstance(
            exc,
            (requests.exceptions.ConnectionError, requests.exceptions.Timeout),
        ):
            return error("connection_failed")
    except ImportError:  # pragma: no cover
        pass

    # socket.timeout / gaierror / other OS-level network errors
    if isinstance(exc, OSError):
        return error("connection_failed")

    return error("backend_failed")


def router_credentials():
    return os.environ.get("ROUTER_USER", ""), os.environ.get("ROUTER_PASS", "")


def cidr_from_netmask(ip, netmask):
    """172.23.123.1 + 255.255.255.255 -> 172.23.123.1/32"""
    return ipaddress.IPv4Interface(f"{ip}/{netmask}").with_prefixlen


def split_ipv4(cidr):
    """172.23.123.1/32 -> ("172.23.123.1", "255.255.255.255")"""
    interface = ipaddress.IPv4Interface(str(cidr).strip())
    return str(interface.ip), str(interface.network.netmask)


_LOOPBACK_RE = re.compile(r"^loopback\s*(\d+)$", re.IGNORECASE)


def loopback_number(name):
    """Loopback123 -> 123; raise ValueError for non-Loopback names."""
    match = _LOOPBACK_RE.match(str(name).strip())
    if not match:
        raise ValueError(f"not a Loopback interface: {name!r}")
    return int(match.group(1))


_SAFE_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9/.:\-]*$")


def require_safe_name(name):
    """Reject names that could inject extra CLI commands."""
    if not isinstance(name, str) or not _SAFE_NAME_RE.match(name):
        raise RuntimeError(f"unsafe interface name: {name!r}")
    return name
