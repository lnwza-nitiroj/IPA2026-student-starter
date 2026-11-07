"""Part 2: desired vs. current interface planning."""

MANAGED_FIELDS = ("ipv4", "description", "admin_state")


def build_plan(desired_interface, current_interface):
    """
    Compare desired interface state with normalized current state
    and return a plan according to specs/plan-spec-v1.md.
    """
    if current_interface is None:
        return {
            "status": "ok",
            "result": "planned",
            "operation": "create",
            "changes": {
                field: {"to": desired_interface.get(field)}
                for field in MANAGED_FIELDS
            },
        }

    changes = {}
    for field in MANAGED_FIELDS:
        desired = desired_interface.get(field)
        current = current_interface.get(field)
        if desired != current:
            changes[field] = {"from": current, "to": desired}

    return {
        "status": "ok",
        "result": "planned",
        "operation": "update" if changes else "no_change",
        "changes": changes,
    }
