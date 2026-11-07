"""Part 4: minimal Webex REST API client."""

import os

import requests

WEBEX_API_BASE = 'https://webexapis.com/v1'
TIMEOUT = 10


class WebexClient:
    def __init__(self, token=None, session=None):
        token = token or os.environ.get("WEBEX_BOT_TOKEN")
        if not token:
            raise PermissionError("WEBEX_BOT_TOKEN is not set")
        self._token = token
        self.session = session if session is not None else requests.Session()

    @property
    def headers(self):
        return {"Authorization": f"Bearer {self._token}"}

    def _get(self, url):
        response = self.session.get(url, headers=self.headers, timeout=TIMEOUT)
        response.raise_for_status()
        return response

    def _post(self, url, payload):
        response = self.session.post(
            url, headers=self.headers, json=payload, timeout=TIMEOUT
        )
        response.raise_for_status()
        return response

    def get_me(self):
        return self._get(f"{WEBEX_API_BASE}/people/me").json()

    def get_message(self, message_id):
        return self._get(f"{WEBEX_API_BASE}/messages/{message_id}").json()

    def download_file(self, file_url):
        return self._get(file_url).content

    def send_message(self, room_id, text):
        return self._post(
            f"{WEBEX_API_BASE}/messages", {"roomId": room_id, "text": text}
        ).json()

    # ---- webhook registration helpers (used by app/webhook_registration.py)

    def list_webhooks(self):
        return self._get(f"{WEBEX_API_BASE}/webhooks?max=100").json().get("items", [])

    def delete_webhook(self, webhook_id):
        response = self.session.delete(
            f"{WEBEX_API_BASE}/webhooks/{webhook_id}",
            headers=self.headers,
            timeout=TIMEOUT,
        )
        response.raise_for_status()

    def create_webhook(self, name, target_url, resource, event, filter_=None):
        payload = {
            "name": name,
            "targetUrl": target_url,
            "resource": resource,
            "event": event,
        }
        if filter_:
            payload["filter"] = filter_
        return self._post(f"{WEBEX_API_BASE}/webhooks", payload).json()

    def list_rooms(self):
        return self._get(f"{WEBEX_API_BASE}/rooms?max=1000").json().get("items", [])
