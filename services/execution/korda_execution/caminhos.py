"""Política de caminhos das ferramentas do agente (camada de aplicação).

É a primeira barreira, com mensagens claras para o agente. A barreira real são as montagens
somente leitura da sandbox: mesmo que esta validação falhe, o kernel recusa a escrita.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from fnmatch import fnmatchcase
from pathlib import PurePosixPath

DIR_PROJETO = "/work/projeto"
_SEGMENTO = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]*$")
SUFIXOS_MODELO = (".sql",)
SUBCOMANDOS_DBT = ("build", "run", "test", "compile", "ls", "debug")
_SELECAO = re.compile(r"^[A-Za-z0-9_.:+*@/]+$")
# Caminho exato (`models/prata_ctes.sql`) ou padrão simples (`models/*`, `models/prata/*.sql`).
# Só `*` no último segmento: nada de `**`, `?`, `[...]` nem padrão fora de models/.
_PADRAO_MODELO = re.compile(
    r"^models/(?:[A-Za-z0-9_][A-Za-z0-9_.-]*/)*(?:[A-Za-z0-9_][A-Za-z0-9_.-]*\.sql|\*|\*\.sql)$")


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
        if parte in ("..", ".") or not _SEGMENTO.fullmatch(parte):
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


def padrao_modelo(padrao: str) -> str:
    """Valida uma entrada de `editable_models` do plano (caminho exato ou padrão) e a devolve."""
    if not isinstance(padrao, str) or not _PADRAO_MODELO.fullmatch(padrao):
        raise CaminhoRecusado(f"editable_models aceita models/<arquivo>.sql ou um padrão como models/*: {padrao!r}")
    return padrao


def modelo_autorizado(caminho: str, padroes: Iterable[str]) -> bool:
    """`caminho` (já validado por `caminho_modelo`) casa com algum caminho ou padrão autorizado.

    `*` do fnmatch também atravessa `/`, então `models/*` cobre subpastas de models/;
    `caminho_modelo` já garante que o caminho fica em models/ e termina em .sql.
    """
    return any(caminho == padrao or fnmatchcase(caminho, padrao) for padrao in padroes)


def caminho_leitura(caminho: str) -> str:
    """Valida um caminho de leitura dentro do projeto dbt (models, definicoes, tests, configs)."""
    p = _normalizar(caminho)
    return f"{DIR_PROJETO}/{p}"


def argv_dbt(subcomando: str, selecao: str | None = None) -> list[str]:
    """Monta o argv do dbt a partir de uma lista branca, sem shell."""
    if subcomando not in SUBCOMANDOS_DBT:
        raise CaminhoRecusado(f"subcomando dbt não permitido: {subcomando!r}")
    argv = ["dbt", "--no-use-colors", subcomando]
    if subcomando == "debug":
        # A imagem local tem adaptador e banco, mas não inclui git nem usa pacotes remotos.
        argv.append("--connection")
    if selecao is not None:
        if subcomando == "debug":
            raise CaminhoRecusado("dbt debug não aceita seleção")
        if not isinstance(selecao, str) or not _SELECAO.fullmatch(selecao) or selecao.startswith(("-", "/")):
            raise CaminhoRecusado(f"seleção inválida: {selecao!r}")
        argv += ["--select", selecao]
    return argv
