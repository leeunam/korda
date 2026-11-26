"""Medição por execução (insumo da K14): tempo, tokens, tentativas e custo.

Grava `medicao.json`. Execuções com executor falso ou roteirizado são marcadas
`synthetic: true`: os números não medem um LLM real.
"""

from __future__ import annotations

import json
from pathlib import Path

from .tipos import ResultadoTentativa

EXECUTORES_COM_LLM = ("chat", "agente_sdk")


class Medidor:
    def __init__(self, run_id: str, executor: str, modelo: str | None):
        self.run_id = run_id
        self.executor = executor
        self.modelo = modelo
        self.tentativas: list[ResultadoTentativa] = []

    def registrar(self, resultado: ResultadoTentativa) -> None:
        self.tentativas.append(resultado)

    def resumo(self) -> dict:
        t = self.tentativas
        return {
            "run_id": self.run_id,
            "executor": self.executor,
            "modelo": self.modelo,
            "synthetic": self.executor not in EXECUTORES_COM_LLM,
            "tentativas": len(t),
            "turnos": sum(r.turnos for r in t),
            "tokens_entrada": sum(r.tokens_entrada for r in t),
            "tokens_saida": sum(r.tokens_saida for r in t),
            "tokens_cache_leitura": sum(r.tokens_cache_leitura for r in t),
            "custo_usd": round(sum(r.custo_usd or 0 for r in t), 6),
            "custo_centavos": sum(r.custo_centavos or 0 for r in t),
            "custo_completo": all(r.custo_centavos is not None for r in t),
            "duracao_s": round(sum(r.duracao_s for r in t), 3),
            "por_tentativa": [r.como_dict() for r in t],
        }

    def gravar(self, caminho: Path) -> None:
        caminho = Path(caminho)
        caminho.parent.mkdir(parents=True, exist_ok=True)
        caminho.write_text(json.dumps(self.resumo(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
