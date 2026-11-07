"""Part 4 student implementation."""

import json

import logging

import os

from collections import deque

from concurrent.futures import ThreadPoolExecutor

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from pathlib import Path

from tempfile import TemporaryDirectory

from threading import Lock

from urllib.parse import urlsplit

from app.integration import process_request

from app.webex_client import WEBEX_API_BASE, WebexClient

log = logging.getLogger("app.webhook_server")

MAX_BODY = 1_000_000


def _error(result):
    return {"status": "error", "result": result}


class WebexEventHandler:
    def __init__(self, client, bot_person_id, processor=None):
        self.client = client
        self.bot_person_id = bot_person_id
        self.processor = processor or process_request

    def handle_event(self, event):
        if not isinstance(event, dict):
            return None
        if event.get("resource") != "messages" or event.get("event") != "created":
            return None
        data = event.get("data")
        if not isinstance(data, dict):
            return None
        message_id = data.get("id")
        if not isinstance(message_id, str) or not message_id:
            return None

        # Skip our own messages before calling the API when possible.
        if data.get("personId") == self.bot_person_id:
            return None

        message = self.client.get_message(message_id)
        if not isinstance(message, dict):
            return None
        if message.get("personId") == self.bot_person_id:
            return None

        room_id = message.get("roomId")
        if not room_id:
            return None

        mentioned_people = message.get("mentionedPeople") or []
        files = message.get("files") or []

        if len(files) > 1:
            result = _error("multiple_attachments")
        elif len(files) == 1:
            result = self._process_attachment(mentioned_people, files[0])
        else:
            result = self._run_processor(mentioned_people, None)

        self.client.send_message(room_id, json.dumps(result))
        return result

    def _process_attachment(self, mentioned_people, file_url):
        content = self.client.download_file(file_url)
        with TemporaryDirectory(prefix="ipa2026-") as tmp:
            path = Path(tmp) / "request.yaml"
            path.write_bytes(content)
            return self._run_processor(mentioned_people, path)
        # TemporaryDirectory removes the file even if processing failed.

    def _run_processor(self, mentioned_people, path):
        try:
            result = self.processor(mentioned_people, path, self.bot_person_id)
        except Exception:  # noqa: BLE001
            log.exception("processor failed")
            return _error("backend_failed")
        if not isinstance(result, dict):
            return _error("backend_failed")
        return result


def make_http_handler(submit_event):
    class WebhookHTTPHandler(BaseHTTPRequestHandler):
        server_version = "IPA2026Webhook/1.0"

        def _send_json(self, status_code, payload):
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _path(self):
            return urlsplit(self.path).path

        def do_GET(self):  # noqa: N802
            if self._path() == "/health":
                self._send_json(200, {"status": "ok", "result": "healthy"})
            else:
                self._send_json(404, _error("not_found"))

        def do_POST(self):  # noqa: N802
            if self._path() != "/webhook":
                self._send_json(404, _error("not_found"))
                return

            try:
                length = int(self.headers.get("Content-Length", ""))
            except ValueError:
                length = -1
            if length < 1 or length > MAX_BODY:
                self.close_connection = True
                self._send_json(400, _error("invalid_event"))
                return

            raw = self.rfile.read(length)
            try:
                event = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                event = None
            if not isinstance(event, dict):
                self._send_json(400, _error("invalid_event"))
                return

            try:
                submit_event(event)
            except Exception:  # noqa: BLE001
                log.exception("could not submit event")
            self._send_json(200, {"status": "ok", "result": "accepted"})

        def log_message(self, format, *args):  # noqa: A002
            log.debug("%s - %s", self.address_string(), format % args)

    return WebhookHTTPHandler


def main():
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    host = os.environ.get("WEBHOOK_HOST", "0.0.0.0")
    port = int(os.environ.get("WEBHOOK_PORT", "8000"))

    client = WebexClient()
    me = client.get_me()
    bot_person_id = me["id"]
    log.info("bot %s (%s) using %s", me.get("displayName"), bot_person_id, WEBEX_API_BASE)

    handler = WebexEventHandler(client, bot_person_id)
    # One worker: requests are processed sequentially so router changes
    # never overlap; the HTTP acknowledgement does not wait for them.
    executor = ThreadPoolExecutor(max_workers=1)
    seen = deque(maxlen=500)
    seen_lock = Lock()

    def already_seen(event):
        # Webex may redeliver an event; never process one message twice.
        data = event.get("data") if isinstance(event, dict) else None
        message_id = data.get("id") if isinstance(data, dict) else None
        if not message_id:
            return False
        with seen_lock:
            if message_id in seen:
                return True
            seen.append(message_id)
            return False

    def run(event):
        try:
            result = handler.handle_event(event)
            if result is not None:
                log.info("replied %s", json.dumps(result))
        except Exception:  # noqa: BLE001
            log.exception("event handling failed")

    def submit_event(event):
        if not already_seen(event):
            executor.submit(run, event)

    from app.webhook_registration import start_background

    start_background(client)

    server = ThreadingHTTPServer((host, port), make_http_handler(submit_event))
    log.info("listening on %s:%s", host, port)
    try:
        server.serve_forever()
    finally:
        server.server_close()
        executor.shutdown(wait=False)


if __name__ == "__main__":
    main()
