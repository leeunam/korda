"""Ingestão das fontes sintéticas 01_demo, executada dentro da sandbox."""

import csv
import hashlib
import json
import sys
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from xml.etree import ElementTree as ET

BANCO = "/work/saida/korda.duckdb"
NS = {"": "http://www.portalfiscal.inf.br/cte"}
REGRAS_SUPORTADAS = {
    "deduplicar_cte": True,
    "excluir_cancelados": True,
    "rateio_cte": "peso",
    "sem_data_realizada": "falha",
    "ocupacao_unidade": "kg",
    "prazo_conta_sabado": True,
    "excluir_tipos_viagem": [],
    "no_prazo": "data(dt_realizada) <= data prevista",
    "completo": "qt_entregue >= qt_itens",
}


def validar_regras(regras):
    if not isinstance(regras, dict) or regras.keys() != REGRAS_SUPORTADAS.keys():
        raise ValueError("as nove regras confirmadas do cenário 01_demo são obrigatórias")
    for chave, esperado in REGRAS_SUPORTADAS.items():
        if type(regras[chave]) is not type(esperado) or regras[chave] != esperado:
            raise ValueError(f"regra sem implementação no pipeline 01_demo: {chave}")


def inteiro_escalado(texto, escala):
    try:
        valor = Decimal(texto.replace(",", ".")) * escala
        if not valor.is_finite() or valor < 0 or valor != valor.to_integral_value():
            raise ValueError("valor negativo, não finito ou precisão incompatível")
        return int(valor)
    except (ValueError, InvalidOperation) as exc:
        raise ValueError(f"valor numérico inválido: {texto!r}") from exc


def data_iso(texto, formatos):
    for formato in formatos:
        try:
            return datetime.strptime(texto, formato).date().isoformat()
        except ValueError:
            continue
    raise ValueError(f"data inválida no layout 01_demo: {texto!r}")


def ler_csv(raiz, caminho, campos):
    arquivo = raiz / caminho
    if arquivo.is_symlink() or arquivo.parent.is_symlink():
        raise ValueError(f"fonte indireta recusada: {caminho}")
    with arquivo.open(encoding="utf-8-sig", newline="") as fp:
        leitor = csv.DictReader(fp, delimiter=";")
        nomes = leitor.fieldnames or []
        if len(set(nomes)) != len(nomes) or not set(campos).issubset(nomes):
            raise ValueError(f"{caminho}: cabeçalho incompatível com 01_demo")
        for linha in leitor:
            try:
                if None in linha or None in linha.values():
                    raise ValueError("largura da linha diferente do cabeçalho")
                yield caminho, leitor.line_num, [linha[c] for c in campos]
            except ValueError as exc:
                raise ValueError(f"{caminho}:{leitor.line_num}: {exc}") from exc


def gravar(conn, tabela, definicao, linhas):
    # Tabela e definição são constantes internas. Todos os valores usam parâmetros.
    conn.execute(f"create table {tabela} ({definicao})")
    batch = []
    for linha in linhas:
        batch.append(linha)
        if len(batch) == 512:
            inserir_lote(conn, tabela, batch)
            batch.clear()
    if batch:
        inserir_lote(conn, tabela, batch)


def inserir_lote(conn, tabela, lote):
    marcas = ", ".join("?" for _ in lote[0])
    conn.executemany(f"insert into {tabela} values ({marcas})", lote)


def pedidos(raiz):
    campos = ["cd_ped", "ch_nfe", "dt_prev_ent", "qt_itens", "ps_bruto"]
    for origem, linha, (pedido, nfe, prazo, itens, peso) in ler_csv(raiz, "erp/erp_pedidos.csv", campos):
        yield (origem, linha, pedido, nfe, data_iso(prazo, ["%Y-%m-%d"]),
               inteiro_escalado(itens, 1), inteiro_escalado(peso, 10))


def entregas(raiz):
    campos = ["id_ent", "nr_ped", "id_viag", "dt_baixa", "qt_entregue"]
    for origem, linha, (entrega, pedido, viagem, raw, itens) in ler_csv(raiz, "tms/tms_entregas.csv", campos):
        realizada = data_iso(raw, ["%Y-%m-%d %H:%M", "%d/%m/%Y %H:%M", "%d/%m/%y"]) if raw else None
        yield origem, linha, entrega, pedido, viagem, raw, realizada, inteiro_escalado(itens, 1)


def veiculos(raiz):
    for origem, linha, (veiculo, cap) in ler_csv(raiz, "tms/tms_veiculos.csv", ["id_veic", "cap_kg"]):
        capacidade = inteiro_escalado(cap, 1)
        if capacidade <= 0:
            raise ValueError(f"{origem}:{linha}: capacidade deve ser positiva")
        yield origem, linha, veiculo, capacidade


def campo(root, caminho):
    valor = root.findtext(caminho, namespaces=NS)
    if not valor or not valor.strip():
        raise ValueError(f"campo XML obrigatório ausente: {caminho}")
    return valor.strip()


def ler_xml(arquivo, origem):
    bruto = arquivo.read_bytes()
    digest = hashlib.sha256(bruto).hexdigest()
    root = ET.fromstring(bruto)
    if root.tag == f"{{{NS['']}}}cteProc":
        chave = campo(root, "protCTe/infProt/chCTe")
        info = root.find("CTe/infCte", NS)
        if info is None or info.get("Id") != "CTe" + chave:
            raise ValueError("protocolo não corresponde à chave do documento")
        valor = inteiro_escalado(campo(info, "vPrest/vTPrest"), 100)
        status = campo(root, "protCTe/infProt/cStat")
        nfes = [campo(nfe, "chave") for nfe in info.findall("infCTeNorm/infDoc/infNFe", NS)]
        if not nfes or len(nfes) != len(set(nfes)):
            raise ValueError("NF-e ausente ou repetida no mesmo documento")
        for nfe in nfes:
            yield origem, digest, "cte", chave, status, None, nfe, valor
    elif root.tag == f"{{{NS['']}}}procEventoCTe":
        chave = campo(root, "eventoCTe/infEvento/chCTe")
        tipo = campo(root, "eventoCTe/infEvento/tpEvento")
        if (campo(root, "retEventoCTe/infEvento/chCTe") != chave or
                campo(root, "retEventoCTe/infEvento/tpEvento") != tipo):
            raise ValueError("retorno de evento não corresponde à chave e tipo enviados")
        yield origem, digest, "evento", chave, campo(root, "retEventoCTe/infEvento/cStat"), tipo, None, None
    else:
        raise ValueError("tipo de documento XML desconhecido")


def documentos(raiz):
    pasta = raiz / "cte"
    if not pasta.is_dir() or pasta.is_symlink():
        raise ValueError("diretório cte/ ausente ou indireto")
    for arquivo in sorted(pasta.glob("*.xml")):
        if arquivo.is_symlink() or not arquivo.is_file():
            raise ValueError("arquivo XML indireto ou irregular")
        origem = f"cte/{arquivo.name}"
        try:
            yield from ler_xml(arquivo, origem)
        except (ET.ParseError, ValueError) as exc:
            raise ValueError(f"{origem}: {exc}") from exc


def ingerir(conn, raiz, regras):
    validar_regras(regras)
    conn.execute("begin")
    try:
        gravar(conn, "bronze_pedidos", "arquivo varchar, linha bigint, pedido_id varchar primary key, "
               "chave_nfe varchar not null unique, data_prevista varchar, qt_itens bigint, peso_decimos_kg bigint",
               pedidos(raiz))
        gravar(conn, "bronze_entregas", "arquivo varchar, linha bigint, entrega_id varchar primary key, "
               "pedido_id varchar not null unique, viagem_id varchar, baixa_original varchar, "
               "data_realizada varchar, qt_entregue bigint", entregas(raiz))
        campos = ["id_viag", "id_veic", "tp_viag"]
        viagens = ((origem, linha, *valores) for origem, linha, valores in ler_csv(raiz, "tms/tms_viagens.csv", campos))
        gravar(conn, "bronze_viagens", "arquivo varchar, linha bigint, viagem_id varchar primary key, "
               "veiculo_id varchar, tipo_viagem varchar", viagens)
        gravar(conn, "bronze_veiculos", "arquivo varchar, linha bigint, veiculo_id varchar primary key, "
               "capacidade_kg bigint", veiculos(raiz))
        gravar(conn, "bronze_documentos", "arquivo varchar, sha256 varchar, especie varchar, chave_cte varchar, "
               "cstat varchar, tipo_evento varchar, chave_nfe varchar, valor_centavos bigint", documentos(raiz))
        conn.commit()
    except Exception:
        conn.rollback()
        raise


if __name__ == "__main__":
    import duckdb

    with duckdb.connect(BANCO) as banco:
        ingerir(banco, Path("/work/fontes"), json.load(sys.stdin))
