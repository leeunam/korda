"""Cliente de uma API chat/completions no formato OpenAI (ex.: gateway da Feita).

Só biblioteca padrão. A chave vai no cabeçalho Authorization e nunca aparece
em mensagens de erro nem no repr. `ClienteChatFalso` serve aos testes.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Protocol


class ErroLLM(RuntimeError):
    """Falha de comunicação com a API do LLM."""


@dataclass
class RespostaChat:
    conteudo: str
    tool_calls: list[dict]  # [{"id", "nome", "argumentos" (JSON em texto)}]
    tokens_entrada: int
    tokens_saida: int
    finish_reason: str
    uso_informado: bool
    mensagem_assistente: dict = field(default_factory=dict)

    @classmethod
    def texto(cls, conteudo: str, tokens=(100, 20)) -> "RespostaChat":
        return cls(conteudo, [], tokens[0], tokens[1], "stop", True, {"role": "assistant", "content": conteudo})

    @classmethod
    def de_tool_calls(cls, chamadas: list[tuple[str, dict]], tokens=(1000, 200)) -> "RespostaChat":
        brutas = [{"id": f"call_{i}", "type": "function",
                   "function": {"name": nome, "arguments": json.dumps(args, ensure_ascii=False)}}
                  for i, (nome, args) in enumerate(chamadas)]
        return cls._de_mensagem({"role": "assistant", "content": None, "tool_calls": brutas}, "tool_calls",
                                {"prompt_tokens": tokens[0], "completion_tokens": tokens[1]})

    @classmethod
    def _de_mensagem(cls, mensagem: dict, finish_reason: str, usage: dict | None) -> "RespostaChat":
        chamadas = [{"id": c.get("id", ""), "nome": c.get("function", {}).get("name", ""),
                     "argumentos": c.get("function", {}).get("arguments") or "{}"}
                    for c in (mensagem.get("tool_calls") or [])]
        usage = usage if isinstance(usage, dict) else None
        return cls(conteudo=mensagem.get("content") or "", tool_calls=chamadas,
                   tokens_entrada=int((usage or {}).get("prompt_tokens") or 0),
                   tokens_saida=int((usage or {}).get("completion_tokens") or 0),
                   finish_reason=finish_reason or "", uso_informado=usage is not None,
                   mensagem_assistente={k: v for k, v in mensagem.items() if k in ("role", "content", "tool_calls")})


class ClienteChat(Protocol):
    def completar(self, mensagens: list[dict], ferramentas: list[dict]) -> RespostaChat: ...


class ClienteChatHttp:
    def __init__(self, url_base: str, chave: str, modelo: str, timeout_s: float = 300):
        self.url = url_base.rstrip("/") + "/chat/completions"
        self._chave = chave
        self.modelo = modelo
        self.timeout_s = timeout_s

    def __repr__(self) -> str:
        return f"ClienteChatHttp(url={self.url!r}, modelo={self.modelo!r})"

    def completar(self, mensagens: list[dict], ferramentas: list[dict]) -> RespostaChat:
        dados = {"model": self.modelo, "messages": mensagens}
        if ferramentas:
            dados["tools"] = ferramentas
        corpo = json.dumps(dados).encode("utf-8")
        pedido = urllib.request.Request(self.url, data=corpo, method="POST", headers={
            "Authorization": f"Bearer {self._chave}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(pedido, timeout=self.timeout_s) as r:
                bruto = r.read()
        except urllib.error.HTTPError as e:
            detalhe = e.read()[:500].decode("utf-8", "replace").replace(self._chave, "***")
            raise ErroLLM(f"API do LLM respondeu HTTP {e.code}: {detalhe}") from None
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise ErroLLM(f"falha de rede ao chamar a API do LLM ({type(e).__name__})") from None
        try:
            dados = json.loads(bruto)
            escolha = dados["choices"][0]
            return RespostaChat._de_mensagem(escolha["message"], escolha.get("finish_reason", ""), dados.get("usage"))
        except (ValueError, KeyError, IndexError, TypeError, AttributeError):
            raise ErroLLM("resposta da API do LLM fora do formato chat/completions") from None


class ClienteChatFalso:
    """Devolve respostas roteirizadas em ordem; esgotado o roteiro, responde texto vazio (o agente para)."""

    def __init__(self, respostas: list[RespostaChat]):
        self.respostas = list(respostas)
        self.pedidos: list[list[dict]] = []

    def completar(self, mensagens: list[dict], ferramentas: list[dict]) -> RespostaChat:
        self.pedidos.append(json.loads(json.dumps(mensagens)))
        return self.respostas.pop(0) if self.respostas else RespostaChat.texto("")
