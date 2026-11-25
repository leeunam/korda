"""Monta a landing zone: um Parquet por tabela, `_rejeitados` e `manifesto.json`.

A landing espelha as subpastas da entrada. Cada CSV vira uma tabela com o mesmo caminho
(`erp/erp_pedidos.csv` -> `erp/erp_pedidos.parquet`). Os XML de CT-e de uma pasta viram
`cte`, `cte_nfe`, `cte_carga` e `cte_evento` nessa pasta. Outros arquivos são listados no
manifesto como `nao_suportado`, sem virar tabela.
"""

from __future__ import annotations

import hashlib
import json
import platform
import shutil
from pathlib import Path

import duckdb
from lxml import etree

from . import __version__, csv_bruto, cte, parquet

ROTULO = (
    "Dados sintéticos. Exportação de arquivos simulada (nível 0); não é conector real nem "
    "execução ao vivo. A ingestão não limpa: duplicatas, cancelados e formatos mistos chegam intactos."
)
FORMATO = "korda.landing/v0"
LINHAGEM_CSV = [("_arquivo", "VARCHAR"), ("_linha", "BIGINT")]
LINHAGEM_XML = [("_arquivo", "VARCHAR"), ("_xml_sha256", "VARCHAR")]
ESQUEMA_REJEITADOS = [
    ("_arquivo", "VARCHAR"), ("_linha", "BIGINT"), ("_xml_sha256", "VARCHAR"),
    ("motivo", "VARCHAR"), ("conteudo_bruto", "VARCHAR"),
]
TABELAS_CTE = {
    "cte": cte.COLUNAS_CTE,
    "cte_nfe": cte.COLUNAS_NFE,
    "cte_carga": cte.COLUNAS_CARGA,
    "cte_evento": cte.COLUNAS_EVENTO,
}


class ErroIngestao(RuntimeError):
    pass


def _tipo(coluna: str) -> str:
    return "BIGINT" if coluna in ("_ordem", "_linha") else "VARCHAR"


def versao_codigo() -> dict:
    h = hashlib.sha256()
    for arq in sorted(Path(__file__).parent.glob("*.py")):
        h.update(arq.name.encode())
        h.update(arq.read_bytes())
    return {
        "pacote": "korda_ingestao",
        "versao": __version__,
        "sha256_fontes": h.hexdigest(),
        "python": platform.python_version(),
        "duckdb": duckdb.__version__,
        "lxml": ".".join(map(str, etree.LXML_VERSION)),
    }


class _Tabelas:
    def __init__(self) -> None:
        self.esquemas: dict[str, list[tuple[str, str]]] = {}
        self.linhas: dict[str, list[list]] = {}
        self.origem: dict[str, str] = {}

    def criar(self, nome: str, esquema: list[tuple[str, str]], origem: str) -> None:
        if nome.lower() in {n.lower() for n in self.esquemas}:
            raise ErroIngestao(f"duas fontes geram a mesma tabela: {nome}")
        self.esquemas[nome] = esquema
        self.linhas[nome] = []
        self.origem[nome] = origem


def ingerir(entrada: Path, saida: Path) -> dict:
    entrada, saida = Path(entrada), Path(saida)
    if not entrada.is_dir():
        raise ErroIngestao(f"entrada não é pasta: {entrada}")
    saida.mkdir(parents=True, exist_ok=True)
    if any(saida.iterdir()):
        raise ErroIngestao(f"saída não está vazia: {saida}")

    tabelas = _Tabelas()
    rejeitados: list[list] = []
    arquivos: list[dict] = []
    pastas_xml: set[str] = set()

    todos = sorted(p for p in entrada.rglob("*") if p.is_file())
    for caminho in todos:
        rel = caminho.relative_to(entrada).as_posix()
        dados = caminho.read_bytes()
        info = {"arquivo": rel, "sha256": cte.sha256(dados), "bytes": len(dados)}
        sufixo = caminho.suffix.lower()

        if sufixo == ".csv":
            nome = rel[: -len(caminho.suffix)]
            info.update(tipo="csv", tabela=nome)
            try:
                lido = csv_bruto.ler_csv(dados, reservados=tuple(c for c, _ in LINHAGEM_CSV))
            except csv_bruto.ErroCsv as e:
                info.update(tabela=None, linhas=0, rejeitadas=1)
                rejeitados.append([rel, None, None, f"arquivo_recusado: {e}", None])
                arquivos.append(info)
                continue
            info.update(
                codificacao=lido.codificacao, separador=lido.separador, cabecalho=lido.cabecalho,
                colunas_originais=lido.colunas_originais, linhas=len(lido.linhas),
                rejeitadas=len(lido.rejeitados),
            )
            tabelas.criar(nome, [(c, "VARCHAR") for c in lido.colunas] + LINHAGEM_CSV, "csv")
            tabelas.linhas[nome] = [valores + [rel, linha] for linha, valores in lido.linhas]
            for r in lido.rejeitados:
                rejeitados.append([rel, r.linha, None, r.motivo, r.conteudo_bruto])

        elif sufixo == ".xml":
            pasta = caminho.parent.relative_to(entrada).as_posix()
            pasta = "" if pasta == "." else pasta + "/"
            if pasta not in pastas_xml:
                pastas_xml.add(pasta)
                for nome_t, colunas in TABELAS_CTE.items():
                    tabelas.criar(pasta + nome_t, [(c, _tipo(c)) for c in colunas] + LINHAGEM_XML, "cte")
            lido_x = cte.ler_xml(dados)
            info.update(tipo="xml")
            if lido_x.rejeitado:
                info.update(documento=None, tabela=None)
                rejeitados.append([rel, None, info["sha256"], lido_x.rejeitado, None])
            else:
                doc = "procEventoCTe" if lido_x.cte_evento else "cteProc"
                info.update(documento=doc, tabela=pasta + ("cte_evento" if lido_x.cte_evento else "cte"))
                for nome_t, colunas in TABELAS_CTE.items():
                    for linha in getattr(lido_x, nome_t):
                        tabelas.linhas[pasta + nome_t].append(
                            [linha.get(c) for c in colunas] + [rel, info["sha256"]]
                        )
        else:
            info.update(tipo="nao_suportado", tabela=None)
        arquivos.append(info)

    staging = saida / "_staging"
    con = parquet.conectar()
    descricao_tabelas: dict[str, dict] = {}
    try:
        for nome in sorted(tabelas.esquemas):
            esquema = tabelas.esquemas[nome]
            parquet.gravar(con, saida / f"{nome}.parquet", esquema, tabelas.linhas[nome], staging)
            descricao_tabelas[nome] = {
                "arquivo": f"{nome}.parquet",
                "origem": tabelas.origem[nome],
                "linhas": len(tabelas.linhas[nome]),
                "colunas": [{"nome": c, "tipo": t} for c, t in esquema],
            }
        parquet.gravar(con, saida / "_rejeitados.parquet", ESQUEMA_REJEITADOS, rejeitados, staging)
    finally:
        con.close()
        shutil.rmtree(staging, ignore_errors=True)

    tipos = [a["tipo"] for a in arquivos]
    manifesto = {
        "formato": FORMATO,
        "rotulo": ROTULO,
        "codigo": versao_codigo(),
        "totais": {
            "arquivos": len(arquivos),
            "csv": tipos.count("csv"),
            "xml": tipos.count("xml"),
            "nao_suportado": tipos.count("nao_suportado"),
            "rejeitados": len(rejeitados),
        },
        "rejeitados": {"arquivo": "_rejeitados.parquet", "linhas": len(rejeitados),
                       "colunas": [{"nome": c, "tipo": t} for c, t in ESQUEMA_REJEITADOS]},
        "tabelas": descricao_tabelas,
        "arquivos": arquivos,
    }
    (saida / "manifesto.json").write_text(
        json.dumps(manifesto, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    return manifesto
