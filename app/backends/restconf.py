"""RESTCONF backend: read with ietf-interfaces, write with Cisco-IOS-XE-native."""

from urllib.parse import quote

from app.backends import planning
from app.backends.common import (
    APPLIED,
    cidr_from_netmask,
    error,
    found,
    loopback_number,
    map_exception,
    not_found,
    router_credentials,
    split_ipv4,
)

TIMEOUT = 10
HEADERS = {
    "Accept": "application/yang-data+json",
    "Content-Type": "application/yang-data+json",
}


def _status_url(router, interface_name):
    return (
        f"https://{router}/restconf/data/ietf-interfaces:interfaces/"
        f"interface={quote(str(interface_name), safe='')}"
    )


def _native_url(router, number):
    return (
        f"https://{router}/restconf/data/"
        f"Cisco-IOS-XE-native:native/interface/Loopback={number}"
    )


def _session():
    import requests
    import urllib3

    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    session = requests.Session()
    session.auth = router_credentials()
    session.verify = False
    session.headers.update(HEADERS)
    return session


def _real_get(url):
    with _session() as session:
        return session.get(url, timeout=TIMEOUT)


def _real_put(url, json):
    with _session() as session:
        return session.put(url, json=json, timeout=TIMEOUT)


def _auth_or_backend(status_code):
    if status_code in (401, 403):
        return error("authentication_failed")
    return error("backend_failed")


def normalize_ietf_interface(raw):
    """Normalize an ietf-interfaces:interface JSON object."""
    if isinstance(raw, list):
        raw = raw[0] if raw else None
    if not isinstance(raw, dict):
        raise ValueError("malformed interface data")

    ipv4 = None
    ipv4_block = raw.get("ietf-ip:ipv4") or {}
    addresses = ipv4_block.get("address") or []
    if addresses:
        first = addresses[0]
        if first.get("prefix-length") is not None:
            ipv4 = cidr_from_netmask(first["ip"], first["prefix-length"])
        else:
            ipv4 = cidr_from_netmask(first["ip"], first["netmask"])

    enabled = raw.get("enabled", True)

    return {
        "name": raw["name"],
        "ipv4": ipv4,
        "description": raw.get("description"),
        "admin_state": "up" if enabled else "down",
    }


def get_interface_state(
    router,
    interface_name,
    http_get=None,
):
    """Return normalized interface status using RESTCONF."""
    http_get = http_get or _real_get

    try:
        response = http_get(_status_url(router, interface_name))
    except Exception as exc:  # noqa: BLE001 - normalized below
        return map_exception(exc)

    if response.status_code == 404:
        return not_found()
    if response.status_code != 200:
        return _auth_or_backend(response.status_code)

    try:
        body = response.json()
        raw = body.get("ietf-interfaces:interface")
        return found(normalize_ietf_interface(raw))
    except Exception:  # noqa: BLE001
        return error("backend_failed")


def plan_interface(
    router,
    desired_interface,
    http_get=None,
):
    """Return create/update/no_change plan using RESTCONF status."""
    return planning.plan_interface(
        router,
        desired_interface,
        lambda r, name: get_interface_state(r, name, http_get),
    )


def build_native_payload(desired_interface):
    number = loopback_number(desired_interface["name"])
    address, mask = split_ipv4(desired_interface["ipv4"])

    loopback = {
        "name": number,
        "description": str(desired_interface["description"]),
        "ip": {
            "address": {
                "primary": {
                    "address": address,
                    "mask": mask,
                }
            }
        },
    }
    if desired_interface["admin_state"] == "down":
        loopback["shutdown"] = [None]

    return number, {"Cisco-IOS-XE-native:Loopback": loopback}


def apply_interface(
    router,
    desired_interface,
    http_put=None,
):
    """Apply complete desired interface state using RESTCONF."""
    http_put = http_put or _real_put

    try:
        number, payload = build_native_payload(desired_interface)
    except (KeyError, ValueError, TypeError):
        return error("backend_failed")

    try:
        response = http_put(_native_url(router, number), json=payload)
    except Exception as exc:  # noqa: BLE001
        return map_exception(exc)

    if response.status_code in (200, 201, 204):
        return dict(APPLIED)
    return _auth_or_backend(response.status_code)
