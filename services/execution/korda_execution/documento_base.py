"""Documento-base: a chamada de API do worker que gera a especificação para o harness.

Entrada: o contexto validado das entrevistas (contrato context v0.1.0) e a
projeção do plano aprovado. Saída: um documento markdown com as seções em
SECOES, que o harness usa como base para construir o pipeline. Uma única
chamada, sem ferramentas. O que faltar no contexto vira lacuna; o modelo não
pode inventar regras. O custo é estimado pelos tokens.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from .harness.cliente_chat import ClienteChat

SECOES = ("Modelos", "Regras aplicadas", "Métricas", "Testes de aceite", "Premissas e lacunas")

SISTEMA_DOCUMENTO = f"""Você é o planejador técnico da Korda. Recebe o contexto validado de entrevistas \
com um cliente (evidências, regras confirmadas, perfil das fontes e lacunas) e o plano aprovado. \
Escreva, em português e em markdown, o documento-base que um engenheiro de dados (ou um agente) usará \
para construir o pipeline dbt/DuckDB em camadas bronze, prata e ouro.

Use exatamente estas seções de nível 2: {", ".join(SECOES)}.
- Modelos: para cada modelo, camada, nome sugerido, grão, colunas principais, chaves e de quais fontes vem.
- Regras aplicadas: cada regra do plano, como implementá-la e a evidência que a sustenta (fonte e trecho).
- Métricas: fórmula exata, grão, filtros, exclusões e denominador, como no plano.
- Testes de aceite: um teste verificável por decisão (unicidade, conservação do rateio, exclusões, valor da métrica).
- Premissas e lacunas: o que foi assumido e o que falta.

Não invente regras, números ou fontes. Se uma informação não estiver no contexto ou no plano, \
registre-a como lacuna em vez de supor. Não mude regras aprovadas."""


@dataclass
class DocumentoBase:
    texto: str
    tokens_entrada: int
    tokens_saida: int
    custo_usd: float | None
    secoes_ausentes: list[str] = field(default_factory=list)


def _json(objeto) -> str:
    return json.dumps(objeto, ensure_ascii=False, sort_keys=True, indent=1, default=str)


def gerar_documento_base(cliente: ClienteChat, contexto: dict, plano_publico: dict, *,
                         precos: tuple[float, float]) -> DocumentoBase:
    mensagens = [
        {"role": "system", "content": SISTEMA_DOCUMENTO},
        {"role": "user", "content": f"Contexto validado:\n{_json(contexto)}\n\nPlano aprovado (projeção):\n{_json(plano_publico)}\n"},
    ]
    resposta = cliente.completar(mensagens, [])
    texto = (resposta.conteudo or "").strip()
    if not texto:
        raise ValueError("a API devolveu um documento-base vazio")
    custo = None
    if resposta.uso_informado:
        custo = round((resposta.tokens_entrada * precos[0] + resposta.tokens_saida * precos[1]) / 1_000_000, 6)
    ausentes = [s for s in SECOES if f"## {s}" not in texto]
    return DocumentoBase(texto, resposta.tokens_entrada, resposta.tokens_saida, custo, ausentes)
