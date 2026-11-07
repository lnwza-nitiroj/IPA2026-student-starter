"""Netmiko + TextFSM backend: status and delete via IOS CLI."""

import re

from app.backends.common import (
    DELETED,
    error,
    found,
    map_exception,
    not_found,
    require_safe_name,
    router_credentials,
)

TIMEOUT = 10

# IOS abbreviations used by "show interfaces description"
_ABBREVIATIONS = (
    ("lo", "Loopback"),
    ("gi", "GigabitEthernet"),
    ("te", "TenGigabitEthernet"),
    ("fa", "FastEthernet"),
    ("et", "Ethernet"),
    ("tu", "Tunnel"),
    ("vl", "Vlan"),
    ("po", "Port-channel"),
    ("se", "Serial"),
)

_ABBR_RE = re.compile(r"^([A-Za-z]+)(\d.*)$")


def normalize_interface_name(name):
    """Lo123 -> Loopback123 (full names are returned unchanged)."""
    name = str(name or "").strip()
    match = _ABBR_RE.match(name)
    if not match:
        return name
    prefix, rest = match.groups()
    for short, full in _ABBREVIATIONS:
        if prefix.lower() == short:
            return full + rest
    return name


def _same(a, b):
    return normalize_interface_name(a).lower() == normalize_interface_name(b).lower()


def _first(value):
    if isinstance(value, list):
        return value[0] if value else None
    return value


def normalize_status(interface_name, ip_info, descriptions):
    """Build a normalized interface dict from parsed TextFSM records."""
    record = next(
        (r for r in ip_info or [] if _same(r.get("interface"), interface_name)),
        None,
    )
    if record is None:
        return None

    ip = _first(record.get("ip_address"))
    prefix = _first(record.get("prefix_length"))
    ipv4 = f"{ip}/{prefix}" if ip and prefix else None

    link_status = str(record.get("link_status") or "").lower()
    admin_state = "down" if "administratively down" in link_status else "up"

    description = None
    for entry in descriptions or []:
        if _same(entry.get("port"), interface_name):
            description = (entry.get("description") or "").strip() or None
            break

    return {
        "name": normalize_interface_name(record.get("interface")) or interface_name,
        "ipv4": ipv4,
        "description": description,
        "admin_state": admin_state,
    }


# ---------------------------------------------------------------- transport

def _connect(router):
    from netmiko import ConnectHandler
    from netmiko.exceptions import (
        NetmikoAuthenticationException,
        NetmikoTimeoutException,
    )

    username, password = router_credentials()
    try:
        return ConnectHandler(
            device_type="cisco_ios",
            host=router,
            username=username,
            password=password,
            conn_timeout=TIMEOUT,
            auth_timeout=TIMEOUT,
            banner_timeout=TIMEOUT,
            fast_cli=False,
        )
    except NetmikoAuthenticationException as exc:
        raise PermissionError(str(exc)) from exc
    except (NetmikoTimeoutException, OSError) as exc:
        raise ConnectionError(str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - e.g. paramiko SSHException
        raise ConnectionError(str(exc)) from exc


def _read_status(connection, interface_name):
    """Run the two read-only commands and return parsed records."""
    require_safe_name(interface_name)

    raw = connection.send_command(f"show ip interface {interface_name}")
    if not raw.strip() or "Invalid input" in raw or "% " in raw:
        # IOS rejects "show ip interface" for an interface that does not exist
        ip_info = []
    else:
        ip_info = _parse("show ip interface", raw)

    raw_descriptions = connection.send_command("show interfaces description")
    descriptions = _parse("show interfaces description", raw_descriptions)

    return ip_info, descriptions


def _parse(command, raw):
    from ntc_templates.parse import parse_output

    try:
        records = parse_output(platform="cisco_ios", command=command, data=raw)
    except Exception as exc:  # noqa: BLE001 - TextFSM template/parse errors
        raise RuntimeError(f"TextFSM could not parse {command}: {exc}") from exc
    if not isinstance(records, list):
        raise RuntimeError(f"TextFSM could not parse {command}")
    return records


def _real_get(router, interface_name):
    connection = _connect(router)
    try:
        return _read_status(connection, interface_name)
    finally:
        connection.disconnect()


def _real_delete(router, interface_name):
    require_safe_name(interface_name)
    if not interface_name.lower().startswith("loopback"):
        raise RuntimeError("only Loopback interfaces may be deleted")

    connection = _connect(router)
    try:
        before = normalize_status(interface_name, *_read_status(connection, interface_name))
        if before is None:
            return "not_found"

        output = connection.send_config_set([f"no interface {interface_name}"])
        if "Invalid input" in output or "% " in output:
            raise RuntimeError(f"delete failed: {output}")

        after = normalize_status(interface_name, *_read_status(connection, interface_name))
        if after is not None:
            raise RuntimeError("interface still present after delete")
        return "deleted"
    finally:
        connection.disconnect()


# ------------------------------------------------------------------- public

def get_interface_state(
    router,
    interface_name,
    netmiko_get=None,
):
    """Return normalized interface status using Netmiko + TextFSM."""
    netmiko_get = netmiko_get or _real_get

    try:
        ip_info, descriptions = netmiko_get(router, interface_name)
    except Exception as exc:  # noqa: BLE001
        return map_exception(exc)

    try:
        interface = normalize_status(interface_name, ip_info, descriptions)
    except Exception:  # noqa: BLE001
        return error("backend_failed")

    if interface is None:
        return not_found()
    return found(interface)


def delete_interface(
    router,
    interface_name,
    netmiko_delete=None,
):
    """Delete an interface using Netmiko."""
    netmiko_delete = netmiko_delete or _real_delete

    try:
        outcome = netmiko_delete(router, interface_name)
    except Exception as exc:  # noqa: BLE001
        return map_exception(exc)

    if outcome == "deleted":
        return dict(DELETED)
    if outcome == "not_found":
        return not_found()
    return error("backend_failed")
