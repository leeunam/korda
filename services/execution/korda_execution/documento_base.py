"""Documento-base: a chamada de API do worker que gera a especificação para o harness.

Entrada: o contexto validado das entrevistas (contrato context v0.1.0) e a
projeção do plano aprovado. Saída: um documento markdown com as seções em
SECOES, que o harness usa como base para construir o pipeline, precedido de um
bloco JSON com a decisão do planejamento: se dá para construir e, se não, as
perguntas que voltam para a descoberta. Uma única chamada, sem ferramentas.
O que faltar no contexto vira lacuna; o modelo não pode inventar regras. O
custo é estimado pelos tokens.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from .contrato_saida import texto_contrato
from .harness.cliente_chat import ClienteChat

SECOES = ("Modelos", "Regras aplicadas", "Métricas", "Testes de aceite", "Premissas e lacunas")
CAMPOS_PERGUNTA = ("pergunta", "lacuna", "metricas_afetadas", "motivo")
MAX_PERGUNTAS = 20
_BLOCO_JSON = re.compile(r"```json\s*\n(.*?)\n\s*```", re.DOTALL)

SISTEMA_DOCUMENTO = f"""Você é o planejador técnico da Korda. Recebe o contexto validado de entrevistas \
com um cliente (evidências, regras confirmadas, perfil das fontes e lacunas) e o plano aprovado. \
Escreva, em português e em markdown, o documento-base que um engenheiro de dados (ou um agente) usará \
para construir o pipeline dbt/DuckDB em camadas bronze, prata e ouro.

Comece a resposta com um único bloco ```json com a decisão do planejamento, antes de qualquer seção:
{{"pronto_para_construir": true ou false, "perguntas": [{{"pergunta": "...", "lacuna": "...", \
"metricas_afetadas": ["..."], "motivo": "..."}}]}}
- pronto_para_construir é false só quando uma lacuna impede construir ou testar um KPI do plano. \
Lacuna que não impede fica em Premissas e lacunas, e pronto_para_construir é true.
- Com false, cada pergunta é dirigida ao cliente, curta e respondível, e diz qual lacuna fecha e \
quais métricas destrava. Elas voltam para a etapa de descoberta.
- Com true, perguntas é uma lista vazia.

Depois do bloco, use exatamente estas seções de nível 2: {", ".join(SECOES)}.
- Modelos: para cada modelo, camada, nome, grão, colunas principais, chaves e de quais fontes vem.
- Regras aplicadas: cada regra do plano, como implementá-la e a evidência que a sustenta.
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
    # None: a resposta não trouxe uma decisão válida; o worker não constrói sem ela.
    pronto_para_construir: bool | None = None
    perguntas: list[dict] = field(default_factory=list)


def _pergunta(item) -> dict | None:
    if not isinstance(item, dict) or not isinstance(item.get("pergunta"), str) or not item["pergunta"].strip():
        return None
    saida = {"pergunta": item["pergunta"].strip()[:500]}
    for campo in ("lacuna", "motivo"):
        if isinstance(item.get(campo), str):
            saida[campo] = item[campo].strip()[:500]
    metricas = item.get("metricas_afetadas")
    if isinstance(metricas, list):
        saida["metricas_afetadas"] = [m for m in metricas if isinstance(m, str)][:10]
    return saida


def _bloco_decisao(texto: str):
    """O primeiro bloco ```json cujo objeto tem `pronto_para_construir`: (match, objeto) ou (None, None).

    O prompt pede a decisão no início; blocos json de exemplo no documento são ignorados.
    """
    for bloco in _BLOCO_JSON.finditer(texto or ""):
        try:
            objeto = json.loads(bloco.group(1))
        except ValueError:
            continue
        if isinstance(objeto, dict) and "pronto_para_construir" in objeto:
            return bloco, objeto
    return None, None


def remover_bloco_decisao(texto: str) -> str:
    """O documento sem o bloco ```json da decisão, para anexar ao plano."""
    bloco, _ = _bloco_decisao(texto)
    if bloco is None:
        return (texto or "").strip() + "\n"
    return (texto[:bloco.start()] + texto[bloco.end():]).strip() + "\n"


def ler_decisao(texto: str) -> tuple[bool | None, list[dict]]:
    """Lê o bloco ```json da decisão (no início ou no fim): (pronto_para_construir, perguntas).

    Qualquer formato inesperado devolve (None, []): sem decisão, nada é construído.
    Com pronto_para_construir false, exige ao menos uma pergunta válida.
    """
    _, decisao = _bloco_decisao(texto)
    if decisao is None or type(decisao.get("pronto_para_construir")) is not bool \
            or not isinstance(decisao.get("perguntas"), list):
        return None, []
    if decisao["pronto_para_construir"]:
        return True, []
    perguntas = [_pergunta(item) for item in decisao["perguntas"][:MAX_PERGUNTAS]]
    if not perguntas or None in perguntas:
        return None, []
    return False, perguntas


def _json(objeto) -> str:
    return json.dumps(objeto, ensure_ascii=False, sort_keys=True, indent=1, default=str)


def gerar_documento_base(cliente: ClienteChat, contexto: dict, plano_publico: dict, *,
                         precos: tuple[float, float]) -> DocumentoBase:
    mensagens = [
        {"role": "system", "content": SISTEMA_DOCUMENTO},
        {"role": "user", "content": f"Contexto validado:\n{_json(contexto)}\n\nPlano aprovado (projeção):\n"
                                    f"{_json(plano_publico)}\n\n{texto_contrato()}\n"},
    ]
    resposta = cliente.completar(mensagens, [])
    texto = (resposta.conteudo or "").strip()
    if not texto:
        raise ValueError("a API devolveu um documento-base vazio")
    custo = None
    if resposta.uso_informado:
        custo = round((resposta.tokens_entrada * precos[0] + resposta.tokens_saida * precos[1]) / 1_000_000, 6)
    ausentes = [s for s in SECOES if f"## {s}" not in texto]
    pronto, perguntas = ler_decisao(texto)
    return DocumentoBase(texto, resposta.tokens_entrada, resposta.tokens_saida, custo, ausentes, pronto, perguntas)
