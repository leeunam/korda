"""Teste de fumaça do gateway chat/completions: no máximo 2 chamadas curtas.

Confirma que o gateway aceita `tools`, devolve `tool_calls` com JSON válido,
informa `usage` e aceita mensagens role=tool (necessárias ao loop do harness).
Gasta créditos: exige KORDA_EXECUTOR=chat, KORDA_PERMITIR_LLM_REAL=1 e a chave.

    set -a; . ./.env; set +a
    cd services/execution
    KORDA_EXECUTOR=chat KORDA_PERMITIR_LLM_REAL=1 python3 -m korda_execution.harness.fumaca
"""

from __future__ import annotations

import json
import sys

from .cliente_chat import ClienteChat, ClienteChatHttp, ErroLLM
from .config import ConfigHarness, ErroConfiguracao

PING = {"type": "function", "function": {
    "name": "ping", "description": "Ferramenta de teste: devolve pong.",
    "parameters": {"type": "object", "properties": {"texto": {"type": "string"}}, "required": ["texto"],
                   "additionalProperties": False}}}


def testar_gateway(cliente: ClienteChat, *, precos: tuple[float, float]) -> dict:
    mensagens = [{"role": "user", "content": "Teste técnico: chame a ferramenta ping com texto \"ok\". "
                                             "Depois do resultado, responda só: pronto."}]
    r1 = cliente.completar(mensagens, [PING])
    respostas = [r1]
    chamada = r1.tool_calls[0] if r1.tool_calls else None
    argumentos_validos = False
    aceita_tool = False
    if chamada:
        try:
            argumentos_validos = isinstance(json.loads(chamada["argumentos"]), dict)
        except ValueError:
            pass
        mensagens += [r1.mensagem_assistente,
                      {"role": "tool", "tool_call_id": chamada["id"], "content": json.dumps({"ok": True, "resposta": "pong"})}]
        r2 = cliente.completar(mensagens, [PING])
        respostas.append(r2)
        aceita_tool = True
    entrada = sum(r.tokens_entrada for r in respostas)
    saida = sum(r.tokens_saida for r in respostas)
    usage = all(r.uso_informado for r in respostas)
    resultado = {
        "chamadas": len(respostas),
        "tool_calls": bool(chamada and chamada["nome"] == "ping"),
        "argumentos_validos": argumentos_validos,
        "aceita_mensagem_tool": aceita_tool,
        "usage": usage,
        "tokens_entrada": entrada,
        "tokens_saida": saida,
        "custo_estimado_usd": round((entrada * precos[0] + saida * precos[1]) / 1e6, 6) if usage else None,
        "finish_reasons": [r.finish_reason for r in respostas],
        "resposta_final": (respostas[-1].conteudo or "")[:200],
    }
    resultado["compativel"] = all(resultado[k] for k in ("tool_calls", "argumentos_validos", "aceita_mensagem_tool"))
    return resultado


def main() -> int:
    try:
        cfg = ConfigHarness.de_ambiente()
    except ErroConfiguracao as e:
        print(f"configuração: {e}", file=sys.stderr)
        return 2
    if cfg.executor != "chat":
        print("o teste de fumaça exige KORDA_EXECUTOR=chat", file=sys.stderr)
        return 2
    cliente = ClienteChatHttp(cfg.llm_url, cfg.chave_api, cfg.modelo, timeout_s=90)
    try:
        resultado = testar_gateway(cliente, precos=(cfg.preco_entrada_usd_mtok, cfg.preco_saida_usd_mtok))
    except ErroLLM as e:
        print(json.dumps({"compativel": False, "erro": str(e), "url": cfg.llm_url, "modelo": cfg.modelo},
                         ensure_ascii=False, indent=2))
        return 1
    print(json.dumps({"url": cfg.llm_url, "modelo": cfg.modelo, **resultado}, ensure_ascii=False, indent=2))
    return 0 if resultado["compativel"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
