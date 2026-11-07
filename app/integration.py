"""Part 4: validate a Webex request and dispatch it to a backend."""

import logging

from app.core import load_request_file, validate_request
from app.dispatcher import dispatch_request
from app.request_handler import validate_webex_envelope

log = logging.getLogger(__name__)


def process_request(mentioned_people, attachment_path, bot_person_id):
    failure = validate_webex_envelope(
        mentioned_people, attachment_path, bot_person_id
    )
    if failure is not None:
        return failure

    # Load the YAML exactly once and reuse the parsed data.
    data, failure = load_request_file(attachment_path)
    if failure is not None:
        return failure

    validation = validate_request(data)
    if validation.get("status") != "ok":
        return validation

    try:
        return dispatch_request(data)
    except Exception:  # noqa: BLE001 - never crash the bot on a backend bug
        log.exception("backend raised an unexpected exception")
        return {"status": "error", "result": "backend_failed"}
