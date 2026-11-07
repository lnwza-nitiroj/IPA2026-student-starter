"""Keep the bot's Webex webhook pointed at the current public HTTPS URL.

The public URL comes from either:
  * PUBLIC_URL (a fixed https://... base URL), or
  * TUNNEL_METRICS_URL, the metrics endpoint of a cloudflared Quick Tunnel
    (``GET <metrics>/quicktunnel`` returns ``{"hostname": "..."}``).

One ``messages/created`` webhook filtered with ``mentionedPeople=me``
delivers mentions from every room the bot is in (IPA2026 and
IPA2026 Exam Room). Old registrations of this bot are replaced, so a new
tunnel URL never leaves stale or duplicate webhooks behind.

Run once by hand:  python -m app.webhook_registration https://example.trycloudflare.com
"""

import logging
import os
import sys
import threading

import requests

from app.webex_client import WebexClient

log = logging.getLogger(__name__)

WEBHOOK_NAME = "ipa2026-student-bot"
POLL_SECONDS = 30


def target_url_for(base_url):
    return base_url.rstrip("/") + "/webhook"


def register(client, base_url):
    """Replace this bot's webhooks with one pointing at base_url/webhook."""
    target = target_url_for(base_url)
    for hook in client.list_webhooks():
        client.delete_webhook(hook["id"])
        log.info("deleted old webhook %s -> %s", hook.get("id"), hook.get("targetUrl"))
    hook = client.create_webhook(
        WEBHOOK_NAME, target, "messages", "created", "mentionedPeople=me"
    )
    log.info("registered webhook %s -> %s (status=%s)", hook.get("id"), target, hook.get("status"))
    return hook


def quick_tunnel_url(metrics_url):
    response = requests.get(metrics_url.rstrip("/") + "/quicktunnel", timeout=5)
    response.raise_for_status()
    hostname = (response.json() or {}).get("hostname")
    return f"https://{hostname}" if hostname else None


def current_public_url():
    public = os.environ.get("PUBLIC_URL", "").strip()
    if public:
        return public
    metrics = os.environ.get("TUNNEL_METRICS_URL", "").strip()
    if metrics:
        return quick_tunnel_url(metrics)
    return None


def watch(client, stop_event=None):
    """Register on start, then re-register whenever the public URL changes."""
    stop_event = stop_event or threading.Event()
    registered = None
    while not stop_event.is_set():
        try:
            url = current_public_url()
            if url and url != registered:
                register(client, url)
                registered = url
        except Exception as exc:  # noqa: BLE001 - keep retrying
            log.warning("webhook registration not updated yet: %s", exc)
        stop_event.wait(POLL_SECONDS if registered else 5)


def start_background(client):
    if not (os.environ.get("PUBLIC_URL") or os.environ.get("TUNNEL_METRICS_URL")):
        log.info("PUBLIC_URL/TUNNEL_METRICS_URL not set; skipping webhook registration")
        return None
    thread = threading.Thread(target=watch, args=(client,), daemon=True)
    thread.start()
    return thread


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    argv = sys.argv[1:] if argv is None else argv
    base_url = argv[0] if argv else current_public_url()
    if not base_url:
        print("usage: python -m app.webhook_registration https://<public-host>", file=sys.stderr)
        return 2
    client = WebexClient()
    register(client, base_url)
    for hook in client.list_webhooks():
        print(f"{hook.get('status')}\t{hook.get('targetUrl')}\t{hook.get('filter')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
