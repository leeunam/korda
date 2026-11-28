"""Contrato de saída do pipeline: nomes fixos que o plano de construção deve usar.

Lido por código, para não divergir do que é cobrado:
- os testes protegidos (`pipeline/projeto/tests/*.sql`): modelos em `ref('...')`,
  colunas que esses testes selecionam, colunas usadas pelo apelido do modelo (ex.: `p.sha256`
  numa junção) e fontes em `source(..., '...')`;
- `vars.contrato_exportacao` do `dbt_project.yml`: colunas, na ordem, que o `exportar.py`
  e o teste `contrato_exportacao` exigem de cada modelo exportado.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

PROJETO = Path(__file__).resolve().parents[1] / "pipeline/projeto"
_REF = re.compile(r"ref\('(\w+)'\)")
_FONTE = re.compile(r"source\('\w+',\s*'(\w+)'\)")
# "select <lista> from {{ ref('m') }}" sem atravessar outro select.
_SELECT_REF = re.compile(r"select\s+((?:(?!\bselect\b).)*?)\s+from\s+\{\{\s*ref\('(\w+)'\)\s*\}\}", re.I | re.S)
# "{{ ref('m') }} p" ou "{{ ref('m') }} as p": o apelido p do modelo m.
_REF_APELIDO = re.compile(r"\{\{\s*ref\('(\w+)'\)\s*\}\}\s+(?:as\s+)?(?!(?:left|right|inner|full|join|where|group|order|on|using)\b)([a-z_]\w*)", re.I)
_APELIDO = re.compile(r"\bas\s+\w+", re.I)
_IDENT = re.compile(r"(?:\b\w+\.)?\b([a-z_][a-z0-9_]*)\b(?!\s*\()", re.I)
_RESERVADAS = {"distinct", "case", "when", "then", "else", "end", "and", "or", "not", "null", "is", "in"}


def _colunas(lista: str) -> list[str]:
    return [c for c in _IDENT.findall(_APELIDO.sub("", lista)) if c.lower() not in _RESERVADAS]


def _juntar(destino: dict[str, list[str]], modelo: str, colunas) -> None:
    atuais = destino.setdefault(modelo, [])
    atuais.extend(c for c in colunas if c not in atuais)


def _do_dbt_project(caminho: Path, modelos: dict[str, list[str]]) -> None:
    projeto = yaml.safe_load(caminho.read_text(encoding="utf-8")) or {}
    contrato = (projeto.get("vars") or {}).get("contrato_exportacao")
    if not isinstance(contrato, dict) or not contrato:
        raise ValueError("dbt_project.yml sem vars.contrato_exportacao (colunas exigidas pelo exportar.py)")
    for modelo, colunas in contrato.items():
        _juntar(modelos, modelo, list(colunas))


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
        for modelo, apelido in _REF_APELIDO.findall(sql):
            _juntar(modelos, modelo, re.findall(rf"\b{re.escape(apelido)}\.([a-z_]\w*)", sql, re.I))
        fontes.extend(f for f in _FONTE.findall(sql) if f not in fontes)
    _do_dbt_project(projeto / "dbt_project.yml", modelos)
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
