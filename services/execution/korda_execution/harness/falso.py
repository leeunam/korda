"""Cliente LLM falso e corretor falso, para testes. Não chama nenhum LLM.

O roteiro diz, por tentativa, quais ferramentas o "agente" chama. Cada chamada
passa pelo mesmo hook (politica.py) e pelo mesmo despacho (ferramentas_agente.py)
do agente real. Tokens e custo são valores sintéticos fixos.
"""

from __future__ import annotations

import asyncio
import time

from .ferramentas_agente import despachar
from .politica import hook_pre_tool_use, nome_curto
from .tipos import FerramentasAgente, ResultadoTentativa, usd_para_centavos


class ClienteLLMFalso:
    def __init__(self, roteiro: list[list[tuple[str, dict]]], tokens_por_turno=(1000, 200),
                 custo_usd_por_turno: float = 0.01):
        self.roteiro = [list(t) for t in roteiro]
        self.tokens_por_turno = tokens_por_turno
        self.custo_usd_por_turno = custo_usd_por_turno

    def proxima_tentativa(self) -> list[tuple[str, dict]]:
        return self.roteiro.pop(0) if self.roteiro else []


class CorretorFalso:
    nome = "falso"

    def __init__(self, cliente: ClienteLLMFalso, ferramentas: FerramentasAgente, editable_models, cfg,
                 medidor=None, emissor=None):
        self.cliente = cliente
        self.ferramentas = ferramentas
        self.editable_models = frozenset(editable_models)
        self.cfg = cfg
        self.medidor = medidor
        self.emissor = emissor

    def __call__(self, falha: dict, tentativa: int) -> dict:
        inicio = time.monotonic()
        chamadas = self.cliente.proxima_tentativa()
        escritas: list[str] = []
        hook = hook_pre_tool_use(self.editable_models, self.emissor, obter_tentativa=lambda: tentativa)

        async def rodar():
            for nome, entrada in chamadas:
                if await hook({"tool_name": nome, "tool_input": entrada}, None, None):
                    continue  # recusado pelo hook, como no SDK
                await despachar(nome_curto(nome), entrada, self.ferramentas, escritas)

        asyncio.run(rodar())
        turnos = max(1, len(chamadas))
        custo_usd = round(self.cliente.custo_usd_por_turno * turnos, 6)
        custo_centavos = usd_para_centavos(custo_usd, self.cfg.taxa_usd_brl)
        ok = bool(escritas)
        if self.medidor is not None:
            entrada_tok, saida_tok = self.cliente.tokens_por_turno
            self.medidor.registrar(ResultadoTentativa(
                tentativa=tentativa, corretor=self.nome, ok=ok, motivo_parada="roteiro_concluido", turnos=turnos,
                tokens_entrada=entrada_tok * turnos, tokens_saida=saida_tok * turnos, tokens_cache_leitura=0,
                custo_usd=custo_usd, custo_centavos=custo_centavos, duracao_s=round(time.monotonic() - inicio, 3),
                arquivos_escritos=escritas))
        if not ok:
            return {"ok": False, "erro": "agente falso terminou sem alteração nos modelos autorizados",
                    "custo_centavos": custo_centavos}
        return {"ok": True, "custo_centavos": custo_centavos}
