"""WhatsApp transport and prerecorded transcription; retries belong to the worker."""

from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta
import hashlib
import hmac
import math
import os
from pathlib import Path
import re
import tempfile
from typing import Any
from urllib.parse import urlsplit

import httpx


MAX_AUDIO_BYTES = 10 * 1024 * 1024
_AUDIO_EXTENSIONS = {
    "audio/aac": ".aac", "audio/mp4": ".m4a", "audio/mpeg": ".mp3",
    "audio/amr": ".amr", "audio/ogg": ".ogg", "audio/opus": ".opus",
    "audio/wav": ".wav", "audio/x-wav": ".wav",
}
_DELIVERY_STATUSES = {"sent", "delivered", "read", "failed", "deleted"}


class ChannelError(Exception):
    """Safe error code, without provider response bodies or credentials."""


class TransientChannelError(ChannelError):
    """A retry is safe, subject to the worker's attempt limit."""


class PermanentChannelError(ChannelError):
    """Invalid input or a rejection that needs operator/participant action."""


class AmbiguousSendError(ChannelError):
    """The provider may have accepted the send; do not retry automatically."""


def verify_signature(raw: bytes, header: str | None, secret: str) -> bool:
    if not secret or not isinstance(header, str) or not re.fullmatch(r"sha256=[0-9a-f]{64}", header):
        return False
    expected = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header)


def _required_string(value: Any, name: str, limit: int = 512, *, multiline: bool = False) -> str:
    if not isinstance(value, str) or not value or len(value) > limit or any(ord(c) < 32 and not (multiline and c in "\r\n\t") for c in value):
        raise PermanentChannelError(f"invalid_{name}")
    return value


def _object(value: Any, name: str) -> dict:
    if not isinstance(value, dict):
        raise PermanentChannelError(f"invalid_{name}")
    return value


def _array(value: Any, name: str) -> list:
    if not isinstance(value, list):
        raise PermanentChannelError(f"invalid_{name}")
    return value


def _timestamp(value: Any) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int)) or not re.fullmatch(r"[0-9]{1,12}", str(value)):
        raise PermanentChannelError("invalid_timestamp")
    try:
        return datetime.fromtimestamp(int(value), UTC).isoformat()
    except (ValueError, OverflowError, OSError) as exc:
        raise PermanentChannelError("invalid_timestamp") from exc


def _mime(value: Any) -> str:
    mime = _required_string(value, "audio_mime", 128).split(";", 1)[0].strip().lower()
    if mime not in _AUDIO_EXTENSIONS:
        raise PermanentChannelError("unsupported_audio_mime")
    return mime


def normalize_webhook(payload: dict) -> dict[str, list[dict]]:
    """Separate supported input, delivery callbacks, and unsupported notifications.

    Malformed supported events reject the batch, so acknowledging cannot lose them.
    New/unsupported message types are acknowledged separately, never turned into facts.
    """
    payload = _object(payload, "webhook")
    if payload.get("object") != "whatsapp_business_account":
        raise PermanentChannelError("invalid_webhook_object")
    result: dict[str, list[dict]] = {"messages": [], "statuses": [], "unsupported": []}
    for entry in _array(payload.get("entry"), "entries"):
        for change in _array(_object(entry, "entry").get("changes"), "changes"):
            change = _object(change, "change")
            if change.get("field") != "messages":
                result["unsupported"].append({"reason": "unsupported_change"})
                continue
            value = _object(change.get("value"), "value")
            messages = _array(value.get("messages", []), "messages")
            statuses = _array(value.get("statuses", []), "statuses")
            if not messages and not statuses:
                continue
            phone_id = _required_string(_object(value.get("metadata"), "metadata").get("phone_number_id"), "phone_number_id")
            for message in messages:
                message = _object(message, "message")
                kind = message.get("type")
                if kind not in {"text", "audio"}:
                    result["unsupported"].append({"phone_number_id": phone_id, "message_id": message.get("id"), "reason": "unsupported_message", "kind": str(kind)[:64]})
                    continue
                # BSUID is needed when Meta omits the phone number for a username user.
                wa_id = message.get("from") or message.get("from_user_id")
                event = {
                    "phone_number_id": phone_id,
                    "message_id": _required_string(message.get("id"), "message_id"),
                    "wa_id": _required_string(wa_id, "wa_id", 256),
                    "timestamp": _timestamp(message.get("timestamp")),
                    "kind": kind, "text": None, "media_id": None, "mime_type": None,
                }
                body = _object(message.get(kind), kind)
                if kind == "text":
                    event["text"] = _required_string(body.get("body"), "text", 16384, multiline=True)
                else:
                    event["media_id"] = _required_string(body.get("id"), "media_id")
                    event["mime_type"] = _mime(body.get("mime_type"))
                result["messages"].append(event)
            for status in statuses:
                status = _object(status, "status")
                if status.get("status") not in _DELIVERY_STATUSES:
                    result["unsupported"].append({"phone_number_id": phone_id, "message_id": status.get("id"), "reason": "unsupported_status"})
                    continue
                result["statuses"].append({
                    "phone_number_id": phone_id,
                    "message_id": _required_string(status.get("id"), "message_id"),
                    "recipient_id": _required_string(status.get("recipient_id") or status.get("recipient_user_id"), "recipient_id", 256),
                    "status": status["status"], "timestamp": _timestamp(status.get("timestamp")),
                })
    return result


def within_service_window(last_message_at: datetime | str | None, now: datetime | None = None) -> bool:
    if last_message_at is None:
        return False
    if isinstance(last_message_at, str):
        last_message_at = datetime.fromisoformat(last_message_at.replace("Z", "+00:00"))
    now = now or datetime.now(UTC)
    if last_message_at.tzinfo is None or now.tzinfo is None:
        raise ValueError("service_window_requires_timezone")
    return timedelta(0) <= now - last_message_at < timedelta(hours=24)


def _json(response: httpx.Response, provider: str) -> dict:
    try:
        return _object(response.json(), f"{provider}_response")
    except ValueError as exc:
        raise PermanentChannelError(f"invalid_{provider}_response") from exc


def _raise_status(response: httpx.Response, provider: str, *, send: bool = False) -> None:
    status = response.status_code
    if 200 <= status < 300:
        return
    code = f"{provider}_http_{status}"
    if send and (status >= 500 or status == 408):
        raise AmbiguousSendError(code)
    if status == 429 or status >= 500 or status in {408, 425}:
        raise TransientChannelError(code)
    raise PermanentChannelError(code)


def _has_audio_header(prefix: bytes, mime: str) -> bool:
    if mime in {"audio/ogg", "audio/opus"}:
        return prefix.startswith(b"OggS")
    if mime in {"audio/wav", "audio/x-wav"}:
        return prefix.startswith(b"RIFF") and prefix[8:12] == b"WAVE"
    if mime == "audio/mp4":
        return prefix[4:8] == b"ftyp"
    if mime == "audio/amr":
        return prefix.startswith((b"#!AMR\n", b"#!AMR-WB\n"))
    if mime == "audio/aac":
        return len(prefix) >= 2 and prefix[0] == 255 and prefix[1] & 0xF6 == 0xF0
    if mime == "audio/mpeg":
        return prefix.startswith(b"ID3") or (len(prefix) >= 2 and prefix[0] == 255 and prefix[1] & 0xE0 == 0xE0)
    return False


class MetaCloudClient:
    def __init__(self, token: str, graph_version: str, client: httpx.Client | None = None, *, api_base: str = "https://graph.facebook.com", max_audio_bytes: int = MAX_AUDIO_BYTES):
        self.token = _required_string(token, "meta_token", 8192)
        if not re.fullmatch(r"v[0-9]+\.[0-9]+", graph_version):
            raise ValueError("graph_version_must_be_explicit")
        if api_base.rstrip("/") != "https://graph.facebook.com":
            raise ValueError("invalid_meta_api_base")
        if not 0 < max_audio_bytes <= MAX_AUDIO_BYTES:
            raise ValueError("invalid_audio_limit")
        self.base = f"{api_base.rstrip('/')}/{graph_version}"
        self.max_audio_bytes = max_audio_bytes
        self._owned_client = client is None
        self.client = client or httpx.Client()
        self.timeout = httpx.Timeout(30, connect=10)

    def close(self) -> None:
        if self._owned_client:
            self.client.close()

    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    @staticmethod
    def _numeric_id(value: str, name: str) -> str:
        if not isinstance(value, str) or not re.fullmatch(r"[0-9]{1,64}", value):
            raise PermanentChannelError(f"invalid_{name}")
        return value

    def send_text(self, phone_number_id: str, wa_id: str, text: str) -> str:
        phone_number_id = self._numeric_id(phone_number_id, "phone_number_id")
        wa_id = _required_string(wa_id, "wa_id", 256)
        text = _required_string(text, "text", 4096, multiline=True)
        if re.fullmatch(r"[A-Z]{2}\.(?:ENT\.)?[A-Za-z0-9]{1,128}", wa_id):
            destination = {"recipient": wa_id}
        elif re.fullmatch(r"\+?[0-9]{1,20}", wa_id):
            destination = {"to": wa_id}
        else:
            raise PermanentChannelError("invalid_wa_id")
        try:
            response = self.client.post(f"{self.base}/{phone_number_id}/messages", headers=self._headers,
                json={"messaging_product": "whatsapp", "recipient_type": "individual", **destination, "type": "text", "text": {"preview_url": False, "body": text}},
                timeout=self.timeout, follow_redirects=False)
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout) as exc:
            raise TransientChannelError("meta_connection_failed") from exc
        except httpx.RequestError as exc:
            raise AmbiguousSendError("meta_send_outcome_unknown") from exc
        _raise_status(response, "meta", send=True)
        try:
            return _required_string(_json(response, "meta")["messages"][0]["id"], "message_id")
        except (KeyError, IndexError, TypeError, PermanentChannelError) as exc:
            # Even a malformed success body may represent an accepted message.
            raise AmbiguousSendError("meta_send_missing_receipt") from exc

    def _metadata(self, phone_number_id: str, media_id: str) -> dict:
        try:
            response = self.client.get(f"{self.base}/{media_id}", headers=self._headers,
                params={"phone_number_id": phone_number_id}, timeout=self.timeout, follow_redirects=False)
        except httpx.RequestError as exc:
            raise TransientChannelError("meta_media_connection_failed") from exc
        _raise_status(response, "meta")
        data = _json(response, "meta")
        if "id" in data and data["id"] != media_id:
            raise PermanentChannelError("media_identity_mismatch")
        data["mime_type"] = _mime(data.get("mime_type"))
        url = _required_string(data.get("url"), "media_url", 16384)
        try:
            parts = urlsplit(url)
            allowed_port = parts.port in {None, 443}
        except ValueError as exc:
            raise PermanentChannelError("unsafe_media_url") from exc
        host = (parts.hostname or "").lower()
        if parts.scheme != "https" or not (host in {"graph.facebook.com", "lookaside.fbsbx.com"} or host.endswith(".fbsbx.com")) or not allowed_port or parts.username or parts.password or parts.fragment:
            raise PermanentChannelError("unsafe_media_url")
        if "file_size" in data:
            size = data["file_size"]
            if isinstance(size, bool) or not isinstance(size, int) or size <= 0 or size > self.max_audio_bytes:
                raise PermanentChannelError("audio_size_exceeded_or_invalid")
        return data

    def download_audio(self, phone_number_id: str, media_id: str, storage_dir: Path) -> dict:
        phone_number_id = self._numeric_id(phone_number_id, "phone_number_id")
        media_id = self._numeric_id(media_id, "media_id")
        storage_dir = Path(storage_dir)
        storage_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        for refresh in range(2):
            metadata = self._metadata(phone_number_id, media_id)
            try:
                with self.client.stream("GET", metadata["url"], headers=self._headers, timeout=self.timeout, follow_redirects=False) as response:
                    if response.status_code in {403, 404} and refresh == 0:
                        continue
                    _raise_status(response, "meta")
                    content_length = response.headers.get("content-length")
                    if content_length is not None:
                        try:
                            declared_size = int(content_length)
                        except ValueError as exc:
                            raise PermanentChannelError("invalid_audio_content_length") from exc
                        if not 0 < declared_size <= self.max_audio_bytes:
                            raise PermanentChannelError("audio_size_exceeded_or_invalid")
                    content_type = response.headers.get("content-type", "application/octet-stream").split(";", 1)[0].strip().lower()
                    if content_type not in {metadata["mime_type"], "application/octet-stream"}:
                        raise PermanentChannelError("audio_mime_mismatch")
                    return self._store_audio(response, metadata, media_id, storage_dir)
            except httpx.RequestError as exc:
                raise TransientChannelError("meta_media_connection_failed") from exc
        raise PermanentChannelError("expired_media_url")

    def _store_audio(self, response: httpx.Response, metadata: dict, media_id: str, storage_dir: Path) -> dict:
        temp_path: Path | None = None
        digest = hashlib.sha256()
        size = 0
        prefix = bytearray()
        try:
            with tempfile.NamedTemporaryFile(dir=storage_dir, prefix="audio-", suffix=".part", delete=False) as handle:
                temp_path = Path(handle.name)
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > self.max_audio_bytes:
                        raise PermanentChannelError("audio_size_exceeded_or_invalid")
                    prefix.extend(chunk[:max(0, 16 - len(prefix))])
                    digest.update(chunk)
                    handle.write(chunk)
            if not size or not _has_audio_header(bytes(prefix), metadata["mime_type"]):
                raise PermanentChannelError("invalid_audio_format")
            if metadata.get("sha256"):
                expected = metadata["sha256"]
                try:
                    expected_bytes = bytes.fromhex(expected) if re.fullmatch(r"[0-9a-fA-F]{64}", expected) else base64.b64decode(expected, validate=True)
                except (ValueError, TypeError) as exc:
                    raise PermanentChannelError("invalid_audio_checksum") from exc
                if not hmac.compare_digest(digest.digest(), expected_bytes):
                    raise PermanentChannelError("audio_checksum_mismatch")
            if "file_size" in metadata and size != metadata["file_size"]:
                raise PermanentChannelError("audio_size_mismatch")
            path = storage_dir / (digest.hexdigest() + _AUDIO_EXTENSIONS[metadata["mime_type"]])
            os.replace(temp_path, path)
            temp_path = None
            return {"sha256": digest.hexdigest(), "path": str(path.resolve()), "mime_type": metadata["mime_type"], "size_bytes": size, "media_id": media_id}
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)


class DeepgramClient:
    def __init__(self, api_key: str, client: httpx.Client | None = None):
        self.api_key = _required_string(api_key, "deepgram_key", 8192)
        self._owned_client = client is None
        self.client = client or httpx.Client()

    def close(self) -> None:
        if self._owned_client:
            self.client.close()

    def transcribe(self, path: Path, mime_type: str) -> dict:
        mime_type = _mime(mime_type)
        path = Path(path)
        if not 0 < path.stat().st_size <= MAX_AUDIO_BYTES:
            raise PermanentChannelError("audio_size_exceeded_or_invalid")
        with path.open("rb") as handle:
            content = handle.read(MAX_AUDIO_BYTES + 1)
        if len(content) > MAX_AUDIO_BYTES or not _has_audio_header(content[:16], mime_type):
            raise PermanentChannelError("invalid_audio_format")
        try:
            response = self.client.post("https://api.deepgram.com/v1/listen", params={"model": "nova-3", "language": "pt", "smart_format": "true"},
                headers={"Authorization": f"Token {self.api_key}", "Content-Type": mime_type}, content=content,
                timeout=httpx.Timeout(120, connect=10, write=30), follow_redirects=False)
        except httpx.RequestError as exc:
            raise TransientChannelError("deepgram_connection_failed") from exc
        _raise_status(response, "deepgram")
        data = _json(response, "deepgram")
        try:
            alternative = _object(data["results"]["channels"][0]["alternatives"][0], "transcription")
            text = _required_string(alternative["transcript"], "transcript", 200000, multiline=True)
            if not text.strip():
                raise PermanentChannelError("audio_no_speech")
            words = _array(alternative.get("words", []), "transcript_words")
            for word in words:
                word = _object(word, "transcript_word")
                _required_string(word.get("word"), "transcript_word", 1024)
                start, end = word.get("start"), word.get("end")
                if any(isinstance(v, bool) or not isinstance(v, (float, int)) or not math.isfinite(v) for v in (start, end)) or not 0 <= start <= end:
                    raise PermanentChannelError("invalid_transcript_timestamps")
            metadata = _object(data.get("metadata", {}), "transcript_metadata")
            model_info = _object(metadata.get("model_info", {}), "transcript_models")
            versions = [info.get("version") for info in model_info.values() if isinstance(info, dict) and isinstance(info.get("version"), str)]
            return {"text": text, "words": words, "model": "nova-3", "model_version": versions[0] if versions else None, "request_id": metadata.get("request_id"), "duration": metadata.get("duration")}
        except (KeyError, IndexError, TypeError) as exc:
            raise PermanentChannelError("invalid_deepgram_response") from exc
