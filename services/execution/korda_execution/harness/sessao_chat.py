"""Loop de ferramentas sobre uma API chat/completions.

O modelo só pede ferramentas; quem decide e executa é o nosso código:
política (a camada "hook") → despachar → FerramentasRestritas → sandbox.
Para quando o modelo responde sem pedir ferramentas, ao atingir o limite de
turnos ou o teto de gasto, ou se a API falhar (o que já foi escrito e gasto
fica registrado). O custo é ESTIMADO pelos tokens e pelo preço configurado.
"""

from __future__ import annotations

import asyncio
import json

from .cliente_chat import ClienteChat, ErroLLM
from .ferramentas_agente import ESPECIFICACOES, despachar
from .politica import PREFIXO, hook_pre_tool_use
from .tipos import FerramentasAgente, SaidaSessao


def ferramentas_openai() -> list[dict]:
    return [{"type": "function", "function": {"name": nome, "description": descricao, "parameters": schema}}
            for nome, (descricao, schema) in ESPECIFICACOES.items()]


def _custo(tokens_entrada: int, tokens_saida: int, precos: tuple[float, float]) -> float:
    return (tokens_entrada * precos[0] + tokens_saida * precos[1]) / 1_000_000


def executar_sessao(cliente: ClienteChat, sistema: str, prompt: str, ferramentas: FerramentasAgente,
                    editable_models, *, emissor, tentativa: int, max_turnos: int, teto_usd: float,
                    precos: tuple[float, float]) -> tuple[SaidaSessao, list[str]]:
    hook = hook_pre_tool_use(editable_models, emissor, obter_tentativa=lambda: tentativa)
    catalogo = ferramentas_openai()
    mensagens: list[dict] = [{"role": "system", "content": sistema}, {"role": "user", "content": prompt}]
    escritas: list[str] = []
    entrada = saida = turnos = 0
    uso_completo = True
    subtype = "error_max_turns"

    async def executar_chamada(chamada: dict) -> str:
        try:
            argumentos = json.loads(chamada["argumentos"])
            if not isinstance(argumentos, dict):
                raise ValueError
        except ValueError:
            return json.dumps({"ok": False, "erro": "argumentos da ferramenta não são um objeto JSON válido"})
        nome = PREFIXO + chamada["nome"]
        recusa = await hook({"tool_name": nome, "tool_input": argumentos}, chamada["id"], None)
        if recusa:
            motivo = recusa["hookSpecificOutput"]["permissionDecisionReason"]
            return json.dumps({"ok": False, "erro": f"recusado pela política: {motivo}"}, ensure_ascii=False)
        resultado = await despachar(chamada["nome"], argumentos, ferramentas, escritas)
        return resultado["content"][0]["text"]

    while turnos < max_turnos:
        try:
            resposta = cliente.completar(mensagens, catalogo)
        except ErroLLM:
            subtype = "error_during_execution"
            break
        turnos += 1
        entrada += resposta.tokens_entrada
        saida += resposta.tokens_saida
        uso_completo = uso_completo and resposta.uso_informado
        mensagens.append(resposta.mensagem_assistente or {"role": "assistant", "content": resposta.conteudo})
        if not resposta.tool_calls:
            subtype = "success"
            break
        for chamada in resposta.tool_calls:
            conteudo = asyncio.run(executar_chamada(chamada))
            mensagens.append({"role": "tool", "tool_call_id": chamada["id"], "content": conteudo})
        if uso_completo and _custo(entrada, saida, precos) >= teto_usd:
            subtype = "error_max_budget_usd"
            break

    custo = round(_custo(entrada, saida, precos), 6) if uso_completo else None
    return SaidaSessao(subtype=subtype, num_turns=turnos, total_cost_usd=custo,
                       usage={"input_tokens": entrada, "output_tokens": saida},
                       ferramentas_sessao=[PREFIXO + n for n in ESPECIFICACOES]), escritas
