"""Política de caminhos das ferramentas do agente (camada de aplicação).

É a primeira barreira, com mensagens claras para o agente. A barreira real são as montagens
somente leitura da sandbox: mesmo que esta validação falhe, o kernel recusa a escrita.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath

from .sandbox import DIR_PROJETO

_SEGMENTO = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]*$")
SUFIXOS_MODELO = (".sql",)
SUBCOMANDOS_DBT = ("build", "run", "test", "compile", "ls", "debug")
_SELECAO = re.compile(r"^[A-Za-z0-9_.:+*@/]+$")


class CaminhoRecusado(ValueError):
    """Caminho fora da política das ferramentas."""


def _normalizar(caminho: str) -> PurePosixPath:
    if not isinstance(caminho, str) or not caminho:
        raise CaminhoRecusado("caminho vazio")
    if "\\" in caminho or "\x00" in caminho:
        raise CaminhoRecusado("caminho com caractere proibido")
    if caminho.startswith("/"):
        raise CaminhoRecusado("use caminho relativo ao projeto, como models/prata/x.sql")
    # Valida a string original: PurePosixPath descartaria "." e "//" em silêncio.
    for parte in caminho.split("/"):
        if parte in ("..", ".") or not _SEGMENTO.match(parte):
            raise CaminhoRecusado(f"segmento inválido no caminho: {parte!r}")
    return PurePosixPath(caminho)


def caminho_modelo(caminho: str) -> str:
    """Valida um caminho de escrita e devolve o destino absoluto dentro da sandbox.

    Aceita só models/**/*.sql. YAML fica de fora porque poderia redefinir testes e fontes.
    """
    p = _normalizar(caminho)
    if len(p.parts) < 2 or p.parts[0] != "models":
        raise CaminhoRecusado("o agente só escreve em models/")
    if p.suffix not in SUFIXOS_MODELO:
        raise CaminhoRecusado(f"só arquivos {', '.join(SUFIXOS_MODELO)} em models/")
    return f"{DIR_PROJETO}/{p}"


def caminho_leitura(caminho: str) -> str:
    """Valida um caminho de leitura dentro do projeto dbt (models, definicoes, tests, configs)."""
    p = _normalizar(caminho)
    return f"{DIR_PROJETO}/{p}"


def argv_dbt(subcomando: str, selecao: str | None = None) -> list[str]:
    """Monta o argv do dbt a partir de uma lista branca, sem shell."""
    if subcomando not in SUBCOMANDOS_DBT:
        raise CaminhoRecusado(f"subcomando dbt não permitido: {subcomando!r}")
    argv = ["dbt", "--no-use-colors", subcomando]
    if selecao is not None:
        if subcomando == "debug":
            raise CaminhoRecusado("dbt debug não aceita seleção")
        if not _SELECAO.match(selecao) or selecao.startswith(("-", "/")):
            raise CaminhoRecusado(f"seleção inválida: {selecao!r}")
        argv += ["--select", selecao]
    return argv
