"""Synthetic transport cases; no live provider calls or real participant data."""

from datetime import UTC, datetime, timedelta
import hashlib
import hmac
import json
from pathlib import Path
import sys

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from korda_context.channel import (
    AmbiguousSendError, DeepgramClient, MetaCloudClient, PermanentChannelError,
    TransientChannelError, normalize_webhook, verify_signature, within_service_window,
)


def webhook(messages=None, statuses=None):
    return {"object": "whatsapp_business_account", "entry": [{"changes": [{"field": "messages", "value": {
        "metadata": {"phone_number_id": "123"}, "messages": messages or [], "statuses": statuses or [],
    }}]}]}


def message(message_id="wamid.synthetic", **extra):
    return {"id": message_id, "from": "5500000000000", "timestamp": "1795737600", "type": "text", "text": {"body": "O rateio está pendente."}, **extra}


def meta(handler, **kwargs):
    return MetaCloudClient("synthetic-token", "v99.0", httpx.Client(transport=httpx.MockTransport(handler)), **kwargs)


def test_signature_uses_original_bytes_and_requires_secret():
    body = b'{"entry": []}'
    signature = "sha256=" + hmac.new(b"synthetic", body, hashlib.sha256).hexdigest()
    assert verify_signature(body, signature, "synthetic")
    assert not verify_signature(b'{"entry":[]}', signature, "synthetic")
    assert not verify_signature(body, signature, "")
    assert not verify_signature(body, "sha256=0", "synthetic")
    assert not verify_signature(body, None, "synthetic")


def test_batch_keeps_messages_and_delivery_events_separate():
    first = webhook([message(), message("wamid.audio", type="audio", audio={"id": "456", "mime_type": "audio/ogg; codecs=opus"})], [{
        "id": "wamid.out", "status": "read", "timestamp": "1795737601", "recipient_id": "5500000000000",
    }])
    second = webhook([message("wamid.next", type="image")])
    first["entry"].extend(second["entry"])
    result = normalize_webhook(first)
    assert [e["kind"] for e in result["messages"]] == ["text", "audio"]
    assert result["messages"][1]["mime_type"] == "audio/ogg"
    assert result["messages"][1]["text"] is None
    assert result["statuses"][0]["message_id"] == "wamid.out"
    assert result["unsupported"][0]["message_id"] == "wamid.next"
    assert result["messages"][0]["timestamp"].endswith("+00:00")


def test_username_identity_without_phone_is_preserved():
    event = message(from_user_id="US.123456789")
    del event["from"]
    assert normalize_webhook(webhook([event]))["messages"][0]["wa_id"] == "US.123456789"


def test_multiline_input_and_outbound_text_remain_intact():
    body = "Usamos ERP.\nO rateio está pendente."
    assert normalize_webhook(webhook([message(text={"body": body})]))["messages"][0]["text"] == body
    def handler(request):
        payload = json.loads(request.content)
        assert payload["to"] == "5500000000000"
        assert "recipient" not in payload
        assert payload["text"]["body"] == body
        return httpx.Response(200, json={"messages": [{"id": "wamid.out"}]})
    assert meta(handler).send_text("123", "5500000000000", body) == "wamid.out"


@pytest.mark.parametrize("payload", [{}, {"object": "whatsapp_business_account", "entry": "wrong"}, webhook([message(timestamp="nan")]), webhook([message(text={})])])
def test_malformed_supported_input_is_not_acknowledged_as_empty(payload):
    with pytest.raises(PermanentChannelError):
        normalize_webhook(payload)


def test_out_of_order_callbacks_retain_original_times_for_repository():
    result = normalize_webhook(webhook(statuses=[
        {"id": "wamid.out", "status": "read", "timestamp": "1795737602", "recipient_id": "5500000000000"},
        {"id": "wamid.out", "status": "sent", "timestamp": "1795737600", "recipient_id": "5500000000000"},
    ]))
    assert [e["status"] for e in result["statuses"]] == ["read", "sent"]
    assert result["statuses"][1]["timestamp"] < result["statuses"][0]["timestamp"]
    assert result["messages"] == []


def test_window_is_per_participant_and_excludes_exact_24_hours():
    now = datetime(2026, 11, 27, tzinfo=UTC)
    assert within_service_window((now - timedelta(hours=23)).isoformat(), now)
    assert not within_service_window(now - timedelta(hours=24), now)
    assert not within_service_window(now + timedelta(seconds=1), now)
    assert not within_service_window(None, now)
    with pytest.raises(ValueError):
        within_service_window(datetime(2026, 11, 27), now)


def test_send_text_scopes_recipient_and_uses_returned_receipt():
    def handler(request):
        assert request.url.path == "/v99.0/123/messages"
        assert request.headers["authorization"] == "Bearer synthetic-token"
        payload = json.loads(request.content)
        assert payload["recipient"] == "US.123456789"
        assert "to" not in payload
        assert payload["text"] == {"preview_url": False, "body": "Qual é a regra?"}
        return httpx.Response(200, json={"messages": [{"id": "wamid.out"}]})
    assert meta(handler).send_text("123", "US.123456789", "Qual é a regra?") == "wamid.out"


@pytest.mark.parametrize("failure,expected", [
    (httpx.ConnectTimeout, TransientChannelError), (httpx.ReadTimeout, AmbiguousSendError),
    (httpx.WriteError, AmbiguousSendError), (httpx.RemoteProtocolError, AmbiguousSendError),
])
def test_only_proven_unsent_transport_failure_can_be_retried(failure, expected):
    calls = []
    def handler(request):
        calls.append(request)
        raise failure("synthetic failure", request=request)
    with pytest.raises(expected):
        meta(handler).send_text("123", "5500000000000", "Pergunta")
    assert len(calls) == 1


@pytest.mark.parametrize("response,expected", [
    (httpx.Response(429), TransientChannelError), (httpx.Response(400), PermanentChannelError),
    (httpx.Response(503), AmbiguousSendError), (httpx.Response(408), AmbiguousSendError),
    (httpx.Response(200, json={}), AmbiguousSendError),
])
def test_send_provider_rejections_and_missing_receipt(response, expected):
    with pytest.raises(expected):
        meta(lambda _: response).send_text("123", "5500000000000", "Pergunta")


def test_requires_explicit_version_and_rejects_oversized_outbound_without_request():
    with pytest.raises(ValueError):
        MetaCloudClient("synthetic", "")
    calls = []
    with pytest.raises(PermanentChannelError):
        meta(lambda request: calls.append(request)).send_text("123", "5500000000000", "x" * 4097)
    assert not calls


def audio_transport(audio, *, url="https://lookaside.fbsbx.com/audio", extra_metadata=None, response_headers=None):
    def handler(request):
        if request.url.host == "graph.facebook.com":
            assert request.url.params["phone_number_id"] == "123"
            return httpx.Response(200, json={"id": "456", "url": url, "mime_type": "audio/ogg", "sha256": hashlib.sha256(audio).hexdigest(), **(extra_metadata or {})})
        assert request.headers["authorization"] == "Bearer synthetic-token"
        return httpx.Response(200, content=audio, headers=response_headers or {"content-type": "audio/ogg"})
    return handler


def test_media_is_authenticated_verified_and_stored_by_hash(tmp_path):
    audio = b"OggS" + b"synthetic-data" * 8
    result = meta(audio_transport(audio, extra_metadata={"file_size": len(audio)})).download_audio("123", "456", tmp_path)
    assert Path(result["path"]).read_bytes() == audio
    assert Path(result["path"]).name == hashlib.sha256(audio).hexdigest() + ".ogg"
    assert result["size_bytes"] == len(audio)
    assert not list(tmp_path.glob("*.part"))


@pytest.mark.parametrize("url", ["http://lookaside.fbsbx.com/file", "https://127.0.0.1/file", "https://lookaside.fbsbx.com.attacker.example/file", "https://lookaside.fbsbx.com@attacker.example/file", "https://lookaside.fbsbx.com:8000/file"])
def test_media_url_cannot_redirect_bearer_credentials_to_arbitrary_hosts(tmp_path, url):
    requests = []
    handler = audio_transport(b"OggS", url=url)
    def capture(request):
        requests.append(request)
        return handler(request)
    with pytest.raises(PermanentChannelError, match="unsafe_media_url"):
        meta(capture).download_audio("123", "456", tmp_path)
    assert len(requests) == 1


def test_media_redirect_is_not_followed(tmp_path):
    requests = []
    def handler(request):
        requests.append(request)
        if request.url.host == "graph.facebook.com":
            return httpx.Response(200, json={"url": "https://lookaside.fbsbx.com/audio", "mime_type": "audio/ogg"})
        return httpx.Response(302, headers={"location": "https://attacker.example/audio"})
    with pytest.raises(PermanentChannelError):
        meta(handler).download_audio("123", "456", tmp_path)
    assert len(requests) == 2


def test_expired_media_url_is_refreshed_once(tmp_path):
    metadata_calls = 0
    downloads = 0
    def handler(request):
        nonlocal metadata_calls, downloads
        if request.url.host == "graph.facebook.com":
            metadata_calls += 1
            return httpx.Response(200, json={"url": f"https://lookaside.fbsbx.com/audio?attempt={metadata_calls}", "mime_type": "audio/ogg"})
        downloads += 1
        if downloads == 1:
            return httpx.Response(404)
        return httpx.Response(200, content=b"OggS-synthetic")
    assert meta(handler).download_audio("123", "456", tmp_path)["mime_type"] == "audio/ogg"
    assert metadata_calls == downloads == 2


def test_expired_media_does_not_loop_forever(tmp_path):
    requests = []
    def handler(request):
        requests.append(request)
        if request.url.host == "graph.facebook.com":
            return httpx.Response(200, json={"url": "https://lookaside.fbsbx.com/audio", "mime_type": "audio/ogg"})
        return httpx.Response(404)
    with pytest.raises(PermanentChannelError):
        meta(handler).download_audio("123", "456", tmp_path)
    assert len(requests) == 4


@pytest.mark.parametrize("headers", [{"content-length": "100000"}, {"content-length": "invalid"}])
def test_declared_size_rejected_before_file_creation(tmp_path, headers):
    with pytest.raises(PermanentChannelError):
        meta(audio_transport(b"OggSdata", response_headers=headers), max_audio_bytes=16).download_audio("123", "456", tmp_path)
    assert not list(tmp_path.iterdir())


def test_actual_stream_size_is_checked_even_when_header_lies(tmp_path):
    class Chunks(httpx.SyncByteStream):
        def __iter__(self):
            yield b"OggS1234"
            yield b"123456789"
    def handler(request):
        if request.url.host == "graph.facebook.com":
            return httpx.Response(200, json={"url": "https://lookaside.fbsbx.com/audio", "mime_type": "audio/ogg"})
        return httpx.Response(200, stream=Chunks(), headers={"content-length": "8"})
    with pytest.raises(PermanentChannelError, match="audio_size"):
        meta(handler, max_audio_bytes=16).download_audio("123", "456", tmp_path)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("audio,metadata", [(b"not-audio", {}), (b"OggSdata", {"sha256": "0" * 64}), (b"OggSdata", {"file_size": 9})])
def test_corrupt_media_never_leaves_a_committed_file(tmp_path, audio, metadata):
    with pytest.raises(PermanentChannelError):
        meta(audio_transport(audio, extra_metadata=metadata)).download_audio("123", "456", tmp_path)
    assert not list(tmp_path.iterdir())


def test_media_id_is_not_a_filesystem_or_url_path(tmp_path):
    with pytest.raises(PermanentChannelError, match="invalid_media_id"):
        meta(lambda _: pytest.fail("request must not occur")).download_audio("123", "../secret", tmp_path)


def test_transcription_uploads_local_bytes_and_keeps_provider_version_and_times(tmp_path):
    path = tmp_path / "synthetic.ogg"
    path.write_bytes(b"OggSsynthetic")
    def handler(request):
        assert request.url.host == "api.deepgram.com"
        assert request.url.params["model"] == "nova-3"
        assert request.url.params["language"] == "pt"
        assert request.headers["content-type"] == "audio/ogg"
        assert request.headers["authorization"] == "Token synthetic-key"
        assert request.content == path.read_bytes()
        return httpx.Response(200, json={"metadata": {"request_id": "synthetic-request", "duration": 1.5, "model_info": {"model-id": {"version": "synthetic-v1", "arch": "nova-3"}}}, "results": {"channels": [{"alternatives": [{"transcript": "Confirmo o peso.", "words": [{"word": "confirmo", "start": 0.1, "end": 0.5, "confidence": 0.99}]}]}]}})
    result = DeepgramClient("synthetic-key", httpx.Client(transport=httpx.MockTransport(handler))).transcribe(path, "audio/ogg; codecs=opus")
    assert result["text"] == "Confirmo o peso."
    assert result["model_version"] == "synthetic-v1"
    assert result["words"][0]["start"] == 0.1


def test_transcription_failure_is_not_an_empty_answer(tmp_path):
    path = tmp_path / "synthetic.ogg"
    path.write_bytes(b"OggSsynthetic")
    def handler(request):
        raise httpx.ReadTimeout("synthetic", request=request)
    with pytest.raises(TransientChannelError):
        DeepgramClient("synthetic", httpx.Client(transport=httpx.MockTransport(handler))).transcribe(path, "audio/ogg")
    empty = {"results": {"channels": [{"alternatives": [{"transcript": "", "words": []}]}]}}
    with pytest.raises(PermanentChannelError):
        DeepgramClient("synthetic", httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=empty)))).transcribe(path, "audio/ogg")
