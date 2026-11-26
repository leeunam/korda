"""Perfis técnicos limitados às exportações sintéticas montadas em /work/fontes."""

import csv
import json
import re
import sys
from collections import Counter
from heapq import nsmallest
from itertools import islice
from pathlib import Path
from xml.parsers import expat

CSV = {
    "erp_clientes": "erp/erp_clientes.csv",
    "erp_pedidos": "erp/erp_pedidos.csv",
    "tms_veiculos": "tms/tms_veiculos.csv",
    "tms_viagens": "tms/tms_viagens.csv",
    "tms_entregas": "tms/tms_entregas.csv",
}
XML_CTE = re.compile(r"[0-9]{44}-(?:cte(?:_reenvio)?|canc-110111)\.xml")
NS_CTE = "http://www.portalfiscal.inf.br/cte"
MAX_REGISTROS = 100
MAX_XML = 24
MAX_DIRETORIO = 50_000
MAX_LINHA = 16_384
MAX_BYTES_XML = 256 * 1024


def _arquivo(raiz, nome):
    caminho = raiz / nome
    if caminho.resolve() != caminho or not caminho.is_file():
        raise ValueError("fonte autorizada ausente ou não é um arquivo regular")
    return caminho


def _linhas(handle):
    lidos = 0
    while linha := handle.readline(MAX_LINHA + 1):
        lidos += len(linha)
        if len(linha) > MAX_LINHA or lidos > 1024 * 1024:
            raise ValueError("amostra do CSV excede o limite de leitura")
        yield linha.decode("utf-8")


def _csv(arquivo):
    with arquivo.open("rb") as handle:
        linhas = _linhas(handle)
        cabecalho = next(linhas, "").lstrip("\ufeff")
        if not cabecalho:
            raise ValueError("CSV sem cabeçalho")
        dialeto = csv.Sniffer().sniff(cabecalho, delimiters=";,|\t")
        colunas = next(csv.reader([cabecalho], dialeto, strict=True))
        if (not 1 <= len(colunas) <= 64 or len(set(colunas)) != len(colunas)
                or any(not c.strip() or len(c) > 100 for c in colunas)):
            raise ValueError("cabeçalho do CSV inválido")
        registros = csv.reader(linhas, dialeto, strict=True)
        contagem = 0
        nulos = [0] * len(colunas)
        for registro in islice(registros, MAX_REGISTROS):
            if len(registro) != len(colunas):
                raise ValueError("número de colunas inconsistente na amostra")
            contagem += 1
            for i, valor in enumerate(registro):
                nulos[i] += not valor.strip()
        parcial = next(registros, None) is not None
    return {
        "formato": "csv", "colunas": colunas, "separador": dialeto.delimiter,
        "registros_analisados": contagem, "amostra_parcial": parcial,
        "nulos_na_amostra": dict(zip(colunas, nulos)),
    }


def _tipo_xml(arquivo):
    with arquivo.open("rb") as handle:
        dados = handle.read(MAX_BYTES_XML + 1)
    if len(dados) > MAX_BYTES_XML:
        raise ValueError("XML excede o limite de leitura por documento")
    raiz = None

    def elemento(nome, _atributos):
        nonlocal raiz
        if raiz is None:
            raiz = nome

    def recusar_doctype(*_):
        raise ValueError("DTD não permitida em XML fiscal")

    parser = expat.ParserCreate(namespace_separator="|")
    parser.StartElementHandler = elemento
    parser.StartDoctypeDeclHandler = recusar_doctype
    parser.Parse(dados, True)
    if raiz not in (f"{NS_CTE}|cteProc", f"{NS_CTE}|procEventoCTe"):
        raise ValueError("tipo de documento fiscal desconhecido")
    return raiz.split("|")[1]


def _cte(raiz):
    pasta = raiz / "cte"
    if pasta.resolve() != pasta or not pasta.is_dir():
        raise ValueError("pasta de CT-e ausente ou inválida")
    total = 0

    def nomes():
        nonlocal total
        for i, caminho in enumerate(pasta.iterdir(), 1):
            if i > MAX_DIRETORIO:
                raise ValueError("diretório excede o limite de documentos")
            if XML_CTE.fullmatch(caminho.name):
                total += 1
                yield caminho.name

    tipos = Counter(_tipo_xml(_arquivo(pasta, nome)) for nome in nsmallest(MAX_XML, nomes()))
    return {
        "formato": "xml", "arquivos_elegiveis": total,
        "arquivos_analisados": sum(tipos.values()), "amostra_parcial": total > MAX_XML,
        "tipos_na_amostra": dict(tipos),
    }


def inspecionar(raiz, fonte):
    if fonte == "cte":
        dados = _cte(raiz)
    elif fonte in CSV:
        dados = _csv(_arquivo(raiz, CSV[fonte]))
    else:
        raise ValueError("fonte fora do catálogo autorizado")
    return {"fonte": fonte, **dados}


if __name__ == "__main__":
    try:
        if len(sys.argv) != 2:
            raise ValueError("informe um identificador de fonte")
        print(json.dumps(inspecionar(Path("/work/fontes"), sys.argv[1]), ensure_ascii=False))
    except (ValueError, OSError, csv.Error, expat.ExpatError) as erro:
        print(json.dumps({"erro": str(erro)}, ensure_ascii=False))
        sys.exit(1)
