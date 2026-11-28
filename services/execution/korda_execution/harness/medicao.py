"""Medição por execução (insumo da K14): tempo, tokens, tentativas e custo.

Grava `medicao.json`. Execuções com executor falso ou roteirizado são marcadas
`synthetic: true`: os números não medem um LLM real. `cobranca` diz se o custo
foi cobrado por uso (`api`) ou é nocional, dentro da cota do plano
(`assinatura`, executor `claude_cli`).
"""

from __future__ import annotations

import json
from pathlib import Path

from .tipos import ResultadoTentativa

EXECUTORES_COM_LLM = ("chat", "agente_sdk", "claude_cli")
EXECUTORES_ASSINATURA = ("claude_cli",)


class Medidor:
    def __init__(self, run_id: str, executor: str, modelo: str | None):
        self.run_id = run_id
        self.executor = executor
        self.modelo = modelo
        self.tentativas: list[ResultadoTentativa] = []
        self.documento_base: dict | None = None

    def registrar_documento_base(self, *, tokens_entrada: int, tokens_saida: int, custo_usd: float | None,
                                 custo_centavos: int | None, duracao_s: float, secoes_ausentes: list[str]) -> None:
        """A chamada de API do worker que gera o documento-base entra nos totais da execução."""
        self.documento_base = {"tokens_entrada": tokens_entrada, "tokens_saida": tokens_saida, "custo_usd": custo_usd,
                               "custo_centavos": custo_centavos, "duracao_s": duracao_s,
                               "secoes_ausentes": list(secoes_ausentes)}

    def registrar(self, resultado: ResultadoTentativa) -> None:
        self.tentativas.append(resultado)

    def resumo(self) -> dict:
        t = self.tentativas
        d = self.documento_base or {}
        return {
            "run_id": self.run_id,
            "executor": self.executor,
            "modelo": self.modelo,
            "synthetic": self.executor not in EXECUTORES_COM_LLM,
            "cobranca": ("assinatura" if self.executor in EXECUTORES_ASSINATURA
                         else "api" if self.executor in EXECUTORES_COM_LLM else None),
            "tentativas": len(t),
            "turnos": sum(r.turnos for r in t),
            "tokens_entrada": sum(r.tokens_entrada for r in t) + d.get("tokens_entrada", 0),
            "tokens_saida": sum(r.tokens_saida for r in t) + d.get("tokens_saida", 0),
            "tokens_cache_leitura": sum(r.tokens_cache_leitura for r in t),
            "custo_usd": round(sum(r.custo_usd or 0 for r in t) + (d.get("custo_usd") or 0), 6),
            "custo_centavos": sum(r.custo_centavos or 0 for r in t) + (d.get("custo_centavos") or 0),
            "custo_completo": all(r.custo_centavos is not None for r in t)
            and (not d or d["custo_centavos"] is not None),
            "duracao_s": round(sum(r.duracao_s for r in t) + d.get("duracao_s", 0), 3),
            "documento_base": self.documento_base,
            "por_tentativa": [r.como_dict() for r in t],
        }

    def gravar(self, caminho: Path) -> None:
        caminho = Path(caminho)
        caminho.parent.mkdir(parents=True, exist_ok=True)
        caminho.write_text(json.dumps(self.resumo(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
