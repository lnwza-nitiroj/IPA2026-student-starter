"""Part 1: YAML desired-state request validation."""

import yaml

ALLOWED_ROUTERS = (
    "10.0.29.101",
    "10.0.29.102",
    "10.0.29.103",
    "10.0.29.104",
    "10.0.29.105",
)

# method -> actions supported by that method (capability matrix)
CAPABILITIES = {
    "restconf": ("status", "plan", "apply"),
    "netconf": ("status", "plan", "apply"),
    "ansible": ("apply",),
    "netmiko-textfsm": ("status", "delete"),
}

ADMIN_STATES = ("up", "down")

ACCEPTED = {"status": "ok", "result": "accepted"}


def error(result):
    return {"status": "error", "result": result}


def _missing(mapping, key):
    return key not in mapping or mapping[key] is None


def validate_request(data):
    """
    Validate one IPA2026 desired-state request.

    Return a response dictionary according to
    specs/response-spec-v1.md.
    """
    if not isinstance(data, dict):
        return error("invalid_yaml")

    # 1. version must be the YAML integer 1 (bool is a subclass of int)
    version = data.get("version")
    if type(version) is not int or version != 1:
        return error("invalid_version")

    # 2. router
    if _missing(data, "router"):
        return error("missing_router")
    if str(data["router"]) not in ALLOWED_ROUTERS:
        return error("invalid_router")

    # 3. method
    if _missing(data, "method"):
        return error("missing_method")
    method = data["method"]
    if not isinstance(method, str) or method not in CAPABILITIES:
        return error("invalid_method")

    # 4. action (must be supported by the selected method)
    if _missing(data, "action"):
        return error("missing_action")
    action = data["action"]
    if not isinstance(action, str) or action not in CAPABILITIES[method]:
        return error("invalid_action")

    # 5. desired / interface / name
    desired = data.get("desired")
    if not isinstance(desired, dict):
        return error("missing_desired")
    interface = desired.get("interface")
    if not isinstance(interface, dict):
        return error("missing_interface")
    name = interface.get("name")
    if name is None or (isinstance(name, str) and not name.strip()):
        return error("missing_interface_name")

    # 6. complete desired state for plan/apply only
    if action in ("plan", "apply"):
        if _missing(interface, "ipv4"):
            return error("missing_ipv4")
        if _missing(interface, "description"):
            return error("missing_description")
        if _missing(interface, "admin_state"):
            return error("missing_admin_state")
        if interface["admin_state"] not in ADMIN_STATES:
            return error("invalid_admin_state")

    return dict(ACCEPTED)


def load_request_file(path):
    """
    Read and parse a YAML request file.

    Return (data, None) on success or (None, error_response) when the
    file cannot be read or parsed.
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except (OSError, UnicodeDecodeError, yaml.YAMLError):
        return None, error("invalid_yaml")

    if not isinstance(data, dict):
        return None, error("invalid_yaml")

    return data, None


def process_request_file(path):
    """
    Read a YAML request file, validate it,
    and return a response dictionary.
    """
    data, failure = load_request_file(path)
    if failure is not None:
        return failure
    return validate_request(data)
