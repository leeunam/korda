"""Descrição e despacho das seis ferramentas que o agente enxerga.

O mesmo `despachar` serve o Claude Agent SDK (via `@tool`) e o cliente falso,
então os testes com o falso exercitam o caminho do agente real. A política
(quem pode escrever onde) fica em `politica.py`; aqui só se valida o formato
da entrada antes de chamar `FerramentasAgente`.
"""

from __future__ import annotations

import json
import re

from .tipos import FerramentasAgente

LIMITE_SAIDA_DBT = 8_000
# Linhas de progresso sem diagnóstico: cabeçalho do dbt e START/OK/PASS de cada nó.
_RUIDO_DBT = re.compile(
    r"^\S*\s*(?:Running with dbt=|Registered adapter:|Found \d+ |Concurrency: |Unable to do partial parsing|"
    r"\d+ of \d+ START |\d+ of \d+ (?:OK|PASS) )")


def enxugar_saida_dbt(saida: str) -> str:
    """Tira o progresso de nós que passaram; erros, falhas, avisos e o resumo `PASS=… ERROR=…` ficam."""
    linhas = [l for l in saida.splitlines() if not _RUIDO_DBT.match(l.strip())]
    texto = re.sub(r"\n{3,}", "\n\n", "\n".join(linhas)).strip()
    return texto[-LIMITE_SAIDA_DBT:]


def _schema(propriedades: dict, obrigatorias: list[str]) -> dict:
    return {"type": "object", "properties": propriedades, "required": obrigatorias, "additionalProperties": False}


_TEXTO = {"type": "string"}

ESPECIFICACOES: dict[str, tuple[str, dict]] = {
    "ler_plano": ("Lê a projeção do plano aprovado: modelos editáveis, limites, regras e critérios de aceite.",
                  _schema({}, [])),
    "inspecionar_fonte": ("Perfil de uma fonte autorizada (erp_clientes, erp_pedidos, tms_veiculos, tms_viagens, "
                          "tms_entregas ou cte): colunas, tipos e amostra limitada.",
                          _schema({"fonte": _TEXTO}, ["fonte"])),
    "ler_arquivo": ("Lê um arquivo do projeto dbt por caminho relativo (ex.: models/prata_ctes.sql, "
                    "tests/chave_fiscal_unica.sql). Somente leitura.",
                    _schema({"caminho": _TEXTO}, ["caminho"])),
    "escrever_modelo": ("Substitui o conteúdo SQL de um modelo autorizado pelo plano (editable_models). "
                        "Testes, fontes e configuração não podem ser alterados.",
                        _schema({"caminho": _TEXTO, "conteudo": _TEXTO}, ["caminho", "conteudo"])),
    "rodar_dbt": ("Roda o dbt na sandbox (build, run, test, compile, ls ou debug), com seleção opcional.",
                  _schema({"subcomando": _TEXTO, "selecao": _TEXTO}, ["subcomando"])),
    "consultar_sql": ("Consulta SQL somente leitura no DuckDB da execução, com resultado limitado.",
                      _schema({"sql": _TEXTO}, ["sql"])),
}


def _erro_formato(nome: str, entrada) -> str | None:
    if nome not in ESPECIFICACOES:
        return f"ferramenta desconhecida: {nome!r}"
    if not isinstance(entrada, dict):
        return "a entrada deve ser um objeto"
    schema = ESPECIFICACOES[nome][1]
    extras = set(entrada) - set(schema["properties"])
    if extras:
        return f"campos não aceitos: {', '.join(sorted(extras))}"
    for campo in schema["required"]:
        if campo not in entrada:
            return f"campo obrigatório ausente: {campo}"
    for campo, valor in entrada.items():
        if not isinstance(valor, str):
            return f"o campo {campo} deve ser texto"
    return None


def _resultado(resultado: dict) -> dict:
    ok = bool(resultado.get("ok"))
    return {"content": [{"type": "text", "text": json.dumps(resultado, ensure_ascii=False, default=str)}],
            "is_error": not ok}


async def despachar(nome_curto: str, entrada: dict, ferramentas: FerramentasAgente, registro_escritas: list[str]) -> dict:
    erro = _erro_formato(nome_curto, entrada)
    if erro:
        return _resultado({"ok": False, "erro": erro})
    if nome_curto == "ler_plano":
        return _resultado(ferramentas.ler_plano())
    if nome_curto == "inspecionar_fonte":
        return _resultado(ferramentas.inspecionar_fonte(entrada["fonte"]))
    if nome_curto == "ler_arquivo":
        return _resultado(ferramentas.ler_arquivo(entrada["caminho"]))
    if nome_curto == "escrever_modelo":
        resultado = ferramentas.escrever_modelo(entrada["caminho"], entrada["conteudo"])
        if resultado.get("ok"):
            registro_escritas.append(entrada["caminho"])
        return _resultado(resultado)
    if nome_curto == "rodar_dbt":
        r = ferramentas.rodar_dbt(entrada["subcomando"], entrada.get("selecao"))
        saida = ((r.get("stdout") or "") + "\n" + (r.get("stderr") or "")).strip()
        return _resultado({k: r.get(k) for k in ("ok", "codigo", "estourou_tempo", "duracao_s", "erro") if k in r}
                          | {"saida": enxugar_saida_dbt(saida)})
    return _resultado(ferramentas.consultar_sql(entrada["sql"]))
