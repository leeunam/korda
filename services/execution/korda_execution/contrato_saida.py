"""Contrato de saída do pipeline: nomes fixos que o plano de construção deve usar.

Lido por código, para não divergir do que é cobrado:
- os testes protegidos (`pipeline/projeto/tests/*.sql`): modelos em `ref('...')`,
  colunas que esses testes selecionam e fontes em `source(..., '...')`;
- o `exportar.py`: colunas de `ouro_kpis` (tupla `cols`), `ouro_por_pedido`
  (`PEDIDO`), `ouro_por_viagem` (`VIAGEM`) e as consultas fixas em texto
  (ex.: `select ... from prata_rateios`).
O `exportar.py` é lido com `ast`, sem importar (ele depende do duckdb).
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

PROJETO = Path(__file__).resolve().parents[1] / "pipeline/projeto"
# Qual variável do exportar.py define as colunas de cada modelo exportado.
ORIGENS_EXPORTAR = {"ouro_kpis": "cols", "ouro_por_pedido": "PEDIDO", "ouro_por_viagem": "VIAGEM"}

_REF = re.compile(r"ref\('(\w+)'\)")
_FONTE = re.compile(r"source\('\w+',\s*'(\w+)'\)")
# "select <lista> from {{ ref('m') }}" sem atravessar outro select.
_SELECT_REF = re.compile(r"select\s+((?:(?!\bselect\b).)*?)\s+from\s+\{\{\s*ref\('(\w+)'\)\s*\}\}", re.I | re.S)
_SELECT_TABELA = re.compile(r"select\s+(.*?)\s+from\s+(\w+)", re.I | re.S)
_APELIDO = re.compile(r"\bas\s+\w+", re.I)
_IDENT = re.compile(r"(?:\b\w+\.)?\b([a-z_][a-z0-9_]*)\b(?!\s*\()", re.I)
_RESERVADAS = {"distinct", "case", "when", "then", "else", "end", "and", "or", "not", "null", "is", "in"}


def _colunas(lista: str) -> list[str]:
    return [c for c in _IDENT.findall(_APELIDO.sub("", lista)) if c.lower() not in _RESERVADAS]


def _juntar(destino: dict[str, list[str]], modelo: str, colunas) -> None:
    atuais = destino.setdefault(modelo, [])
    atuais.extend(c for c in colunas if c not in atuais)


def _do_exportar(caminho: Path, modelos: dict[str, list[str]]) -> None:
    arvore = ast.parse(caminho.read_text(encoding="utf-8"))
    tuplas = {}
    for no in ast.walk(arvore):
        if isinstance(no, ast.Assign) and isinstance(no.value, ast.Tuple) \
                and all(isinstance(e, ast.Constant) and isinstance(e.value, str) for e in no.value.elts):
            for alvo in no.targets:
                if isinstance(alvo, ast.Name):
                    tuplas[alvo.id] = [e.value for e in no.value.elts]
        elif isinstance(no, ast.Constant) and isinstance(no.value, str):
            for lista, tabela in _SELECT_TABELA.findall(no.value):
                _juntar(modelos, tabela, _colunas(lista))
    for modelo, variavel in ORIGENS_EXPORTAR.items():
        if variavel not in tuplas:
            raise ValueError(f"exportar.py sem a tupla {variavel} (colunas de {modelo})")
        _juntar(modelos, modelo, tuplas[variavel])


def contrato_saida(projeto: Path = PROJETO) -> dict:
    """{"modelos": {nome: [colunas]}, "fontes": [nomes]}, em ordem de aparição."""
    modelos: dict[str, list[str]] = {}
    fontes: list[str] = []
    for teste in sorted((projeto / "tests").glob("*.sql")):
        sql = teste.read_text(encoding="utf-8")
        for modelo in _REF.findall(sql):
            modelos.setdefault(modelo, [])
        for lista, modelo in _SELECT_REF.findall(sql):
            _juntar(modelos, modelo, _colunas(lista))
        fontes.extend(f for f in _FONTE.findall(sql) if f not in fontes)
    _do_exportar(projeto / "exportar.py", modelos)
    return {"modelos": modelos, "fontes": fontes}


def texto_contrato(projeto: Path = PROJETO) -> str:
    """O contrato como texto para a mensagem do planejamento."""
    c = contrato_saida(projeto)
    linhas = ["Nomes fixos que o plano deve usar (cobrados pelos testes protegidos e pela exportação; "
              "não renomeie; pode haver modelos auxiliares além destes):",
              "Modelos obrigatórios e colunas exigidas:"]
    linhas += [f"- {modelo}: {', '.join(colunas) or '(colunas livres)'}" for modelo, colunas in c["modelos"].items()]
    linhas.append(f"Fontes bronze já carregadas (não crie nem altere): {', '.join(c['fontes'])}")
    return "\n".join(linhas)
