"""Configuração explícita; segredos não aparecem no repr ou nos logs."""
from pathlib import Path
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator
import os


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    database_url: SecretStr
    meta_app_secret: SecretStr = SecretStr("")
    meta_verify_token: SecretStr = SecretStr("")
    meta_access_token: SecretStr = SecretStr("")
    meta_graph_version: str = ""
    deepgram_api_key: SecretStr = SecretStr("")
    llm_api_key: SecretStr = SecretStr("")
    llm_url: str = "https://api.feita.ai/gateway/v1"
    interviewer_model: str = ""
    organizer_model: str = ""
    media_dir: Path = Path("/var/lib/korda/media")
    real_providers: bool = False
    max_llm_calls_per_project: int = Field(default=120, ge=1, le=1000)
    max_output_tokens: int = Field(default=1800, ge=128, le=6000)

    @field_validator("llm_url")
    @classmethod
    def secure_gateway(cls, value: str) -> str:
        if not value.startswith("https://"):
            raise ValueError("LLM gateway requires HTTPS")
        return value.rstrip("/")

    @classmethod
    def from_env(cls) -> "Settings":
        values = {}
        for name in cls.model_fields:
            key = "CONTEXT_" + name.upper()
            if key in os.environ:
                values[name] = os.environ[key]
        return cls.model_validate(values)

    def check_providers(self) -> None:
        if not self.real_providers:
            raise ValueError("Provedores reais desativados: habilite CONTEXT_REAL_PROVIDERS explicitamente")
        for name in ("meta_app_secret", "meta_verify_token", "meta_access_token", "deepgram_api_key", "llm_api_key"):
            if not getattr(self, name).get_secret_value():
                raise ValueError(f"Configuração ausente: CONTEXT_{name.upper()}")
        for name in ("meta_graph_version", "interviewer_model", "organizer_model"):
            if not getattr(self, name):
                raise ValueError(f"Configuração ausente: CONTEXT_{name.upper()}")
