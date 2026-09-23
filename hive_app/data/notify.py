from typing import Protocol

import requests

REQUEST_TIMEOUT_SECONDS = 10
REAUTH_REQUIRED_MESSAGE = (
    "hive-app: Hive re-authentication required. The remembered device is no "
    "longer recognized and a live SMS 2FA code is needed to recover."
)


class ReauthNotifier(Protocol):
    def notify_reauth_required(self) -> None: ...


class NtfyReauthNotifier:
    """Posts a plain-text alert to a configured ntfy.sh topic URL when
    called -- see ADR-0018. ntfy.sh's public-topic API needs no auth/JSON,
    just the message body POSTed as plain text to the topic URL."""

    def __init__(self, topic_url: str) -> None:
        self._topic_url = topic_url

    def notify_reauth_required(self) -> None:
        response = requests.post(
            self._topic_url,
            data=REAUTH_REQUIRED_MESSAGE.encode("utf-8"),
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
