"""Loop de ferramentas sobre uma API chat/completions.

O modelo só pede ferramentas; quem decide e executa é o nosso código:
política (a camada "hook") → despachar → FerramentasRestritas → sandbox.
Para quando o modelo responde sem pedir ferramentas, ao atingir o limite de
turnos ou o teto de gasto, ou se a API falhar (o que já foi escrito e gasto
fica registrado). O custo é ESTIMADO pelos tokens e pelo preço configurado.

O histórico inteiro é reenviado a cada turno, então o custo de entrada cresce
como uma soma triangular. Para conter isso, as saídas de ferramenta dos últimos
`MANTER_TURNOS` turnos seguem íntegras; as anteriores viram uma linha, e o SQL
de escritas antigas sai dos argumentos (o agente pode reler o modelo). Conta
turnos, não saídas: no ensaio-01 o agente fazia várias consultas por turno e,
contando saídas, o esquema da bronze sumia no turno seguinte e era consultado
de novo. Se o agente passar `TURNOS_ATE_ESCREVER` turnos sem escrever, recebe
um lembrete para escrever e validar com o build. Ver o simulador em
`tests/harness/simulador_custo.py`.
"""

from __future__ import annotations

import asyncio
import json
import re

from .cliente_chat import ClienteChat, ErroLLM
from .ferramentas_agente import ESPECIFICACOES, despachar
from .politica import PREFIXO, hook_pre_tool_use
from .tipos import FerramentasAgente, SaidaSessao

MANTER_TURNOS = 3
TURNOS_ATE_ESCREVER = 8
LEMBRETE_ESCREVER = ("Você já usou {n} turnos sem escrever nenhum modelo. Pare de investigar: escreva agora os "
                     "modelos com escrever_modelo e use rodar_dbt build para descobrir o que falta.")
_RESUMO_DBT = re.compile(r"Done\. PASS=.*|Completed with .*")


def ferramentas_openai() -> list[dict]:
    return [{"type": "function", "function": {"name": nome, "description": descricao, "parameters": schema}}
            for nome, (descricao, schema) in ESPECIFICACOES.items()]


def _custo(tokens_entrada: int, tokens_saida: int, precos: tuple[float, float]) -> float:
    return (tokens_entrada * precos[0] + tokens_saida * precos[1]) / 1_000_000


def _resumir_saida(nome: str, argumentos: dict, conteudo: str) -> str:
    try:
        corpo = json.loads(conteudo)
    except ValueError:
        corpo = {}
    alvo = argumentos.get("caminho") or argumentos.get("fonte") or argumentos.get("subcomando") or ""
    if argumentos.get("selecao"):
        alvo += f" --select {argumentos['selecao']}"
    estado = "ok" if corpo.get("ok") else "erro"
    extra = ""
    if nome == "rodar_dbt":
        achados = _RESUMO_DBT.findall(corpo.get("saida") or "")
        extra = f"; {achados[-1]}" if achados else ""
    elif not corpo.get("ok") and corpo.get("erro"):
        extra = f"; {str(corpo['erro'])[:160]}"
    return (f"[saída antiga resumida: {nome} {alvo}".rstrip() + f", {estado}, {len(conteudo)} caracteres{extra}. "
            "Chame a ferramenta de novo se precisar do conteúdo.]")


def compactar_historico(mensagens: list[dict], manter_turnos: int = MANTER_TURNOS) -> None:
    """Resume, no lugar, as saídas de ferramenta anteriores aos `manter_turnos` últimos turnos e o SQL das
    escritas correspondentes. Mensagens já resumidas ficam iguais nos turnos seguintes (prefixo estável)."""
    # Cada saída pertence à mensagem do assistente imediatamente anterior (ids podem se repetir entre turnos).
    pares: list[tuple[int, dict, dict]] = []
    atuais: dict[str, dict] = {}
    turno = 0
    for m in mensagens:
        if m.get("role") == "assistant":
            turno += 1
            atuais = {c.get("id", ""): c for c in (m.get("tool_calls") or [])}
        elif m.get("role") == "tool":
            pares.append((turno, m, atuais.get(m.get("tool_call_id", ""), {})))
    for t, m, chamada in pares:
        if t > turno - manter_turnos:
            continue
        if m["content"].startswith("[saída antiga resumida"):
            continue
        funcao = chamada.get("function", {})
        try:
            argumentos = json.loads(funcao.get("arguments") or "{}")
        except ValueError:
            argumentos = {}
        argumentos = argumentos if isinstance(argumentos, dict) else {}
        m["content"] = _resumir_saida(funcao.get("name", "?"), argumentos, m["content"])
        if funcao.get("name") == "escrever_modelo" and isinstance(argumentos.get("conteudo"), str):
            n = len(argumentos["conteudo"])
            argumentos["conteudo"] = f"[{n} caracteres de SQL omitidos; use ler_arquivo para ver a versão atual]"
            funcao["arguments"] = json.dumps(argumentos, ensure_ascii=False)


def executar_sessao(cliente: ClienteChat, sistema: str, prompt: str, ferramentas: FerramentasAgente,
                    editable_models, *, emissor, tentativa: int, max_turnos: int, teto_usd: float,
                    precos: tuple[float, float], verificar_ativa=None, manter_turnos: int | None = MANTER_TURNOS,
                    turnos_ate_escrever: int | None = TURNOS_ATE_ESCREVER) -> tuple[SaidaSessao, list[str]]:
    hook = hook_pre_tool_use(editable_models, emissor, obter_tentativa=lambda: tentativa)
    catalogo = ferramentas_openai()
    mensagens: list[dict] = [{"role": "system", "content": sistema}, {"role": "user", "content": prompt}]
    escritas: list[str] = []
    entrada = saida = turnos = 0
    uso_completo = True
    subtype = "error_max_turns"
    erro_api = None
    por_turno: list[list[int]] = []
    lembrou = False

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
        if manter_turnos is not None:
            compactar_historico(mensagens, manter_turnos)
        try:
            resposta = cliente.completar(mensagens, catalogo)
        except ErroLLM as e:
            subtype = "error_during_execution"
            erro_api = str(e)[:300]
            break
        turnos += 1
        por_turno.append([resposta.tokens_entrada, resposta.tokens_saida])
        entrada += resposta.tokens_entrada
        saida += resposta.tokens_saida
        uso_completo = uso_completo and resposta.uso_informado
        if not uso_completo:
            subtype = "uso_desconhecido"
            break
        mensagens.append(resposta.mensagem_assistente or {"role": "assistant", "content": resposta.conteudo})
        if not resposta.tool_calls:
            subtype = "success"
            break
        for chamada in resposta.tool_calls:
            if verificar_ativa is not None:
                verificar_ativa()
            conteudo = asyncio.run(executar_chamada(chamada))
            mensagens.append({"role": "tool", "tool_call_id": chamada["id"], "content": conteudo})
        if uso_completo and _custo(entrada, saida, precos) >= teto_usd:
            subtype = "error_max_budget_usd"
            break
        if turnos_ate_escrever is not None and not lembrou and not escritas and turnos >= turnos_ate_escrever:
            mensagens.append({"role": "user", "content": LEMBRETE_ESCREVER.format(n=turnos)})
            lembrou = True

    custo = round(_custo(entrada, saida, precos), 6) if uso_completo else None
    return SaidaSessao(subtype=subtype, num_turns=turnos, total_cost_usd=custo,
                       usage={"input_tokens": entrada, "output_tokens": saida},
                       ferramentas_sessao=[PREFIXO + n for n in ESPECIFICACOES], erro=erro_api,
                       tokens_por_turno=por_turno), escritas
