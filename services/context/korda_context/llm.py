"""Cliente JSON do gateway, sem executar ferramentas ou seguir instruções do cliente."""
from datetime import datetime, timezone
import json
import time
import httpx


class ModelError(RuntimeError):
    pass


class TransientModelError(ModelError):
    pass


class JsonModel:
    def __init__(self, *, api_key: str, base_url: str, model: str,
                 max_tokens: int = 1800, client: httpx.Client | None = None):
        if not model:
            raise ValueError("Identificador do modelo deve ser explícito")
        self.client = client or httpx.Client(timeout=90, follow_redirects=False)
        self.api_key, self.base_url, self.model = api_key, base_url.rstrip("/"), model
        self.max_tokens = max_tokens
        self.last_usage: dict = {}

    def __call__(self, system: str, data: str) -> dict:
        self.last_usage = {}
        started = time.monotonic()
        try:
            response = self.client.post(self.base_url + "/chat/completions",
                headers={"Authorization": "Bearer " + self.api_key},
                json={"model": self.model, "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": data}],
                    "max_tokens": self.max_tokens, "temperature": 0,
                    "response_format": {"type": "json_object"}})
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise TransientModelError("Gateway indisponível") from exc
        if response.status_code == 429 or response.status_code >= 500:
            raise TransientModelError(f"Gateway temporariamente indisponível ({response.status_code})")
        if response.status_code >= 400:
            raise ModelError(f"Gateway rejeitou chamada ({response.status_code}); verifique configuração/modelo")
        try:
            body = response.json()
            choice = body["choices"][0]
            if choice.get("finish_reason") == "length":
                raise ModelError("Resposta do modelo incompleta")
            result = json.loads(choice["message"]["content"])
            if not isinstance(result, dict):
                raise ValueError("Expected JSON object")
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise ModelError("Gateway não retornou objeto JSON válido") from exc
        self.last_usage = {"model": self.model, "usage": body.get("usage", {}),
                           "latency_ms": round((time.monotonic() - started) * 1000),
                           "timestamp": datetime.now(timezone.utc).isoformat()}
        return result
