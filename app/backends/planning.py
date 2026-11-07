from app.planner import build_plan


def plan_interface(
    router,
    desired_interface,
    get_interface_state,
):
    """Build a Part 2 plan from backend status."""
    status = get_interface_state(router, desired_interface["name"])

    if status.get("status") != "ok":
        return status

    if status.get("result") == "found":
        current = status.get("interface")
    elif status.get("result") == "not_found":
        current = None
    else:
        return {"status": "error", "result": "backend_failed"}

    return build_plan(desired_interface, current)
