"""Emissão de eventos da execução (provisória).

Campos do contrato mínimo em packages/contracts/README.md: run_id, step, type, message,
attempt, ts. Os valores de `type` usados aqui são provisórios até a K01 fechar o contrato.
O destino é um JSONL local; trocar de backend (P4) muda só esta classe.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

LIMITE_MENSAGEM = 2_000


@dataclass
class EmissorEventos:
    caminho: Path
    run_id: str

    def emit_event(self, step: str, type: str, message: str, attempt: int = 1, **extra) -> dict:
        evento = {
            "run_id": self.run_id,
            "step": step,
            "type": type,
            "message": message[:LIMITE_MENSAGEM],
            "attempt": attempt,
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        }
        if extra:
            evento["dados"] = extra
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        with self.caminho.open("a", encoding="utf-8") as f:
            f.write(json.dumps(evento, ensure_ascii=False) + "\n")
        return evento

    def ler(self) -> list[dict]:
        if not self.caminho.exists():
            return []
        return [json.loads(l) for l in self.caminho.read_text(encoding="utf-8").splitlines() if l]
