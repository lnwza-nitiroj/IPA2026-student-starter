"""Part 4: route a validated request to the correct backend."""

from app.backends import ansible, netconf, netmiko_textfsm, restconf

# (method, action) -> (backend module, function name, argument kind)
ROUTES = {
    ("restconf", "status"): (restconf, "get_interface_state", "name"),
    ("restconf", "plan"): (restconf, "plan_interface", "interface"),
    ("restconf", "apply"): (restconf, "apply_interface", "interface"),
    ("netconf", "status"): (netconf, "get_interface_state", "name"),
    ("netconf", "plan"): (netconf, "plan_interface", "interface"),
    ("netconf", "apply"): (netconf, "apply_interface", "interface"),
    ("ansible", "apply"): (ansible, "apply_interface", "interface"),
    ("netmiko-textfsm", "status"): (netmiko_textfsm, "get_interface_state", "name"),
    ("netmiko-textfsm", "delete"): (netmiko_textfsm, "delete_interface", "name"),
}


def dispatch_request(data):
    route = ROUTES.get((data.get("method"), data.get("action")))
    if route is None:
        return {"status": "error", "result": "invalid_action"}

    module, function_name, argument = route
    # Look the function up at call time so it can be replaced in tests.
    backend = getattr(module, function_name)

    router = str(data["router"])
    interface = data["desired"]["interface"]

    if argument == "name":
        return backend(router, interface["name"])
    return backend(router, interface)
