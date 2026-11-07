"""NETCONF backend: read with ietf-interfaces, write with Cisco-IOS-XE-native."""

import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape

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

PORT = 830
TIMEOUT = 10

IF_NS = "urn:ietf:params:xml:ns:yang:ietf-interfaces"
IP_NS = "urn:ietf:params:xml:ns:yang:ietf-ip"
NATIVE_NS = "http://cisco.com/ns/yang/Cisco-IOS-XE-native"


def _connect(router):
    from ncclient import manager
    from ncclient.transport.errors import AuthenticationError, SSHError

    username, password = router_credentials()
    try:
        return manager.connect(
            host=router,
            port=PORT,
            username=username,
            password=password,
            hostkey_verify=False,
            allow_agent=False,
            look_for_keys=False,
            timeout=TIMEOUT,
            device_params={"name": "iosxe"},
        )
    except AuthenticationError as exc:
        raise PermissionError(str(exc)) from exc
    except (SSHError, OSError) as exc:
        raise ConnectionError(str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - other transport failures
        raise ConnectionError(str(exc)) from exc


def _rpc(router, call):
    from ncclient.operations.rpc import RPCError
    from ncclient.transport.errors import TransportError

    with _connect(router) as session:
        try:
            return call(session)
        except RPCError as exc:
            raise RuntimeError(str(exc)) from exc
        except TransportError as exc:
            raise ConnectionError(str(exc)) from exc


def _real_get_config(router, filter_xml):
    reply = _rpc(
        router,
        lambda s: s.get_config(source="running", filter=("subtree", filter_xml)),
    )
    return reply.data_xml if hasattr(reply, "data_xml") else str(reply)


def _real_edit_config(router, config_xml):
    _rpc(router, lambda s: s.edit_config(target="running", config=config_xml))


def build_status_filter(interface_name):
    return (
        f'<interfaces xmlns="{IF_NS}">'
        "<interface>"
        f"<name>{escape(str(interface_name))}</name>"
        "</interface>"
        "</interfaces>"
    )


def _text(element):
    if element is None or element.text is None:
        return None
    return element.text.strip()


def parse_interface_xml(xml_text, interface_name):
    """Return a normalized interface dict, or None when absent."""
    if isinstance(xml_text, bytes):
        xml_text = xml_text.decode("utf-8")
    root = ET.fromstring(xml_text.strip())

    for interface in root.iter(f"{{{IF_NS}}}interface"):
        name = _text(interface.find(f"{{{IF_NS}}}name"))
        if name != str(interface_name):
            continue

        enabled = _text(interface.find(f"{{{IF_NS}}}enabled"))
        description = _text(interface.find(f"{{{IF_NS}}}description"))

        ipv4 = None
        address = interface.find(f"{{{IP_NS}}}ipv4/{{{IP_NS}}}address")
        if address is not None:
            ip = _text(address.find(f"{{{IP_NS}}}ip"))
            mask = _text(address.find(f"{{{IP_NS}}}netmask")) or _text(
                address.find(f"{{{IP_NS}}}prefix-length")
            )
            if ip and mask:
                ipv4 = cidr_from_netmask(ip, mask)

        return {
            "name": name,
            "ipv4": ipv4,
            "description": description,
            "admin_state": "down" if enabled == "false" else "up",
        }

    return None


def get_interface_state(
    router,
    interface_name,
    netconf_get_config=None,
):
    """Return normalized interface status using NETCONF."""
    netconf_get_config = netconf_get_config or _real_get_config

    try:
        xml_text = netconf_get_config(router, build_status_filter(interface_name))
    except Exception as exc:  # noqa: BLE001
        return map_exception(exc)

    try:
        interface = parse_interface_xml(xml_text, interface_name)
    except Exception:  # noqa: BLE001 - malformed backend data
        return error("backend_failed")

    if interface is None:
        return not_found()
    return found(interface)


def plan_interface(
    router,
    desired_interface,
    netconf_get_config=None,
):
    """Return create/update/no_change plan using NETCONF status."""
    return planning.plan_interface(
        router,
        desired_interface,
        lambda r, name: get_interface_state(r, name, netconf_get_config),
    )


def build_native_config(desired_interface):
    number = loopback_number(desired_interface["name"])
    address, mask = split_ipv4(desired_interface["ipv4"])
    shutdown = "<shutdown/>" if desired_interface["admin_state"] == "down" else ""

    return (
        '<config xmlns="urn:ietf:params:xml:ns:netconf:base:1.0" '
        'xmlns:nc="urn:ietf:params:xml:ns:netconf:base:1.0">'
        f'<native xmlns="{NATIVE_NS}">'
        "<interface>"
        '<Loopback nc:operation="replace">'
        f"<name>{number}</name>"
        f"<description>{escape(str(desired_interface['description']))}</description>"
        "<ip><address><primary>"
        f"<address>{address}</address>"
        f"<mask>{mask}</mask>"
        "</primary></address></ip>"
        f"{shutdown}"
        "</Loopback>"
        "</interface>"
        "</native>"
        "</config>"
    )


def apply_interface(
    router,
    desired_interface,
    netconf_edit_config=None,
):
    """Apply complete desired interface state using NETCONF."""
    netconf_edit_config = netconf_edit_config or _real_edit_config

    try:
        config_xml = build_native_config(desired_interface)
    except (KeyError, ValueError, TypeError):
        return error("backend_failed")

    try:
        netconf_edit_config(router, config_xml)
    except Exception as exc:  # noqa: BLE001
        return map_exception(exc)

    return dict(APPLIED)
