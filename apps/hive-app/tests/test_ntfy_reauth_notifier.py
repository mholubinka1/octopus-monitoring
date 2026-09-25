import pytest
import requests
import responses

from hive_app.data.notify import NtfyReauthNotifier

TOPIC_URL = "https://ntfy.sh/hive-app-reauth-alerts"


@responses.activate
def test_notify_reauth_required_posts_a_plain_text_message_to_the_ntfy_topic() -> None:
    responses.add(responses.POST, TOPIC_URL, status=200)

    NtfyReauthNotifier(TOPIC_URL).notify_reauth_required()

    assert len(responses.calls) == 1
    assert responses.calls[0].request.url == TOPIC_URL
    assert responses.calls[0].request.body is not None


@responses.activate
def test_notify_reauth_required_raises_when_ntfy_responds_with_an_error() -> None:
    responses.add(responses.POST, TOPIC_URL, status=500)

    with pytest.raises(requests.HTTPError):
        NtfyReauthNotifier(TOPIC_URL).notify_reauth_required()
