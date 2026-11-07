"""Ansible backend: apply-only via cisco.ios.ios_config over network_cli."""

import json
import os
import subprocess
import tempfile
from pathlib import Path

from app.backends.common import (
    APPLIED,
    error,
    map_exception,
    require_safe_name,
    split_ipv4,
)

ANSIBLE_DIR = Path(__file__).resolve().parents[2] / "ansible"
PLAYBOOK = ANSIBLE_DIR / "apply_interface.yml"
INVENTORY = ANSIBLE_DIR / "inventory.ini"
TIMEOUT = 60

_AUTH_MARKERS = (
    "authentication failed",
    "authentication failure",
    "permission denied",
    "invalid credentials",
    "bad authentication",
)
_CONNECTION_MARKERS = (
    "unreachable",
    "timed out",
    "timeout",
    "connection refused",
    "no route to host",
    "unable to connect",
    "could not connect",
    "network is unreachable",
    "name or service not known",
    "connection reset",
)


def build_variables(router, desired_interface):
    address, netmask = split_ipv4(desired_interface["ipv4"])
    return {
        "router": str(router),
        "interface_name": desired_interface["name"],
        "description": str(desired_interface["description"]),
        "ipv4_address": address,
        "netmask": netmask,
        "shutdown": desired_interface["admin_state"] == "down",
    }


def _classify_failure(returncode, output):
    text = output.lower()
    if any(marker in text for marker in _AUTH_MARKERS):
        raise PermissionError("ansible authentication failed")
    if returncode == 4 or any(marker in text for marker in _CONNECTION_MARKERS):
        raise ConnectionError("ansible could not reach the router")
    raise RuntimeError(f"ansible-playbook failed with rc={returncode}")


def _real_run_playbook(variables):
    require_safe_name(variables["interface_name"])
    if "\n" in variables["description"] or "\r" in variables["description"]:
        raise RuntimeError("description must be a single line")

    env = dict(os.environ)
    env.setdefault("ANSIBLE_HOST_KEY_CHECKING", "False")
    env.setdefault("ANSIBLE_RETRY_FILES_ENABLED", "False")
    env.setdefault("ANSIBLE_NOCOLOR", "1")
    env.setdefault("ANSIBLE_PERSISTENT_CONNECT_TIMEOUT", "15")
    env.setdefault("ANSIBLE_PERSISTENT_COMMAND_TIMEOUT", "20")

    with tempfile.TemporaryDirectory() as tmp:
        vars_file = Path(tmp) / "vars.json"
        vars_file.write_text(json.dumps(variables), encoding="utf-8")

        command = [
            "ansible-playbook",
            "-i",
            str(INVENTORY),
            str(PLAYBOOK),
            "-e",
            f"@{vars_file}",
        ]
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=TIMEOUT,
                env=env,
                cwd=str(ANSIBLE_DIR),
            )
        except FileNotFoundError as exc:
            raise RuntimeError("ansible-playbook is not installed") from exc
        except subprocess.TimeoutExpired as exc:
            raise ConnectionError("ansible-playbook timed out") from exc

    if completed.returncode != 0:
        _classify_failure(
            completed.returncode, completed.stdout + "\n" + completed.stderr
        )


def apply_interface(
    router,
    desired_interface,
    run_playbook=None,
):
    """Apply complete desired interface state using Ansible."""
    run_playbook = run_playbook or _real_run_playbook

    try:
        variables = build_variables(router, desired_interface)
    except (KeyError, ValueError, TypeError):
        return error("backend_failed")

    try:
        run_playbook(variables)
    except Exception as exc:  # noqa: BLE001
        return map_exception(exc)

    return dict(APPLIED)
