"""Projeta a landing Parquet oficial nos cinco modelos bronze da transportadora 01_demo."""

from collections import defaultdict
import re
import json
import sys
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path, PurePosixPath

BANCO = "/work/saida/korda.duckdb"
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
    except (AttributeError, ValueError, InvalidOperation) as exc:
        raise ValueError(f"valor numérico inválido: {texto!r}") from exc


def data_iso(texto, formatos):
    for formato in formatos:
        try:
            return datetime.strptime(texto, formato).date().isoformat()
        except (TypeError, ValueError):
            continue
    raise ValueError(f"data inválida no layout 01_demo: {texto!r}")


CAMPOS = {
    "erp/erp_pedidos": ("cd_ped", "ch_nfe", "dt_prev_ent", "qt_itens", "ps_bruto"),
    "tms/tms_entregas": ("id_ent", "nr_ped", "id_viag", "dt_baixa", "qt_entregue"),
    "tms/tms_viagens": ("id_viag", "id_veic", "tp_viag"),
    "tms/tms_veiculos": ("id_veic", "cap_kg"),
    "cte/cte": ("chCTe", "infCte_Id", "prot_chCTe", "prot_cStat", "vTPrest"),
    "cte/cte_nfe": ("chCTe", "chave"),
    "cte/cte_evento": ("chCTe", "ret_chCTe", "tpEvento", "ret_tpEvento", "ret_cStat"),
}


def arquivo_landing(raiz, nome):
    caminho = raiz / nome
    if caminho.resolve() != caminho or not caminho.is_file():
        raise ValueError(f"arquivo obrigatório da landing ausente ou indireto: {nome}")
    return caminho


def ler_parquet(arquivo, colunas):
    import duckdb

    with duckdb.connect(config={"threads": 1}) as leitor:
        # As colunas são constantes deste módulo; o caminho entra como parâmetro.
        selecao = ", ".join(f'"{c}"' for c in colunas) if colunas else "1"
        cursor = leitor.execute(f"select {selecao} from read_parquet(?)", [str(arquivo)])
        while lote := cursor.fetchmany(1024):
            yield from lote


class Landing:
    def __init__(self, raiz):
        self.raiz = raiz.absolute()
        manifesto = json.loads(arquivo_landing(self.raiz, "manifesto.json").read_text(encoding="utf-8"))
        self.nivel = manifesto.get("nivel", 0)
        if (manifesto.get("formato") != "korda.landing/v0" or type(self.nivel) is not int
                or self.nivel not in (0, 1)):
            raise ValueError("formato ou nível de landing não suportado")
        if self.nivel == 1 and manifesto.get("plano", {}).get("company_id") != "01_demo":
            raise ValueError("layout do plano de ingestão incompatível com 01_demo")
        self.tabelas = manifesto["tabelas"]
        rej = manifesto["rejeitados"]
        if (rej["arquivo"] != "_rejeitados.parquet" or rej["linhas"] != 0
                or next(ler_parquet(arquivo_landing(self.raiz, "_rejeitados.parquet"), ()), None) is not None):
            raise ValueError("landing contém rejeições de ingestão; revisar dados antes de calcular")

    def ler(self, nome):
        if nome not in self.tabelas or self.tabelas[nome]["arquivo"] != nome + ".parquet":
            raise ValueError(f"tabela canônica ausente ou renomeada no manifesto: {nome}")
        if nome.startswith("cte/"):
            meta = ("_arquivo", "_xml_sha256", "_carga") if self.nivel else ("_arquivo", "_xml_sha256")
        else:
            meta = ("_origem", "_carga") if self.nivel else ("_arquivo", "_linha")
        caminho = arquivo_landing(self.raiz, nome + ".parquet")
        total = 0
        for valores in ler_parquet(caminho, meta + CAMPOS[nome]):
            total += 1
            yield valores[:len(meta)], valores[len(meta):]
        if total != self.tabelas[nome]["linhas"]:
            raise ValueError(f"{nome}: número de linhas diverge do manifesto")

    def registros(self, nome):
        origens = {"erp/erp_pedidos": "erp:erp_pedidos", "tms/tms_entregas": "tms:/entregas",
                   "tms/tms_viagens": "tms:/viagens", "tms/tms_veiculos": "tms:/veiculos"}
        esperado = origens[nome] if self.nivel else nome + ".csv"
        minima = 1 if self.nivel else 2
        for (origem, posicao), dados in self.ler(nome):
            if origem != esperado or type(posicao) is not int or posicao < minima:
                raise ValueError(f"{nome}: linhagem de registro inválida")
            if self.nivel:
                yield (None, None, origem, posicao), dados
            else:
                yield (origem, posicao, None, None), dados


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


def pedidos(landing):
    for origem, (pedido, nfe, prazo, itens, peso) in landing.registros("erp/erp_pedidos"):
        yield (*origem, pedido, nfe, data_iso(prazo, ["%Y-%m-%d"]),
               inteiro_escalado(itens, 1), inteiro_escalado(peso, 10))


def entregas(landing):
    for origem, (entrega, pedido, viagem, raw, itens) in landing.registros("tms/tms_entregas"):
        realizada = data_iso(raw, ["%Y-%m-%d %H:%M", "%d/%m/%Y %H:%M", "%d/%m/%y"]) if raw else None
        yield *origem, entrega, pedido, viagem, raw, realizada, inteiro_escalado(itens, 1)


def veiculos(landing):
    for origem, (veiculo, cap) in landing.registros("tms/tms_veiculos"):
        capacidade = inteiro_escalado(cap, 1)
        if capacidade <= 0:
            raise ValueError("capacidade deve ser positiva")
        yield *origem, veiculo, capacidade


def documentos(landing):
    # Vincular os filhos a sua cópia física evita cruzar duas NF-e com ambos os reenvios do mesmo CT-e.
    notas = defaultdict(set)
    for origem, (chave, nfe) in landing.ler("cte/cte_nfe"):
        identificador = (*origem, chave)
        if not nfe or nfe in notas[identificador]:
            raise ValueError(f"{origem[0]}: NF-e ausente ou repetida no mesmo documento")
        notas[identificador].add(nfe)
    for origem, (chave, inf_id, protocolo, status, valor) in landing.ler("cte/cte"):
        if not chave or not status or inf_id != "CTe" + chave or protocolo != chave:
            raise ValueError(f"{origem[0]}: protocolo inconsistente com documento")
        nfes = notas.pop((*origem, chave), None)
        if not nfes:
            raise ValueError(f"{origem[0]}: CT-e sem NF-e correspondente")
        arquivo, digest, carga = origem_xml(origem)
        for nfe in sorted(nfes):
            yield arquivo, digest, carga, "cte", chave, status, None, nfe, inteiro_escalado(valor, 100)
    if notas:
        raise ValueError("landing contém NF-e sem documento fiscal correspondente")
    for origem, (chave, retorno, tipo, ret_tipo, status) in landing.ler("cte/cte_evento"):
        if not chave or not tipo or not status or chave != retorno or tipo != ret_tipo:
            raise ValueError(f"{origem[0]}: retorno de evento não corresponde à chave ou tipo")
        arquivo, digest, carga = origem_xml(origem)
        yield arquivo, digest, carga, "evento", chave, status, tipo, None, None


def origem_xml(origem):
    arquivo, digest, *cargas = origem
    if (not isinstance(arquivo, str) or not arquivo or PurePosixPath(arquivo).is_absolute()
            or ".." in PurePosixPath(arquivo).parts or not isinstance(digest, str)
            or not re.fullmatch(r"[a-f0-9]{64}", digest)):
        raise ValueError("linhagem XML incompleta na landing")
    if cargas and (type(cargas[0]) is not int or cargas[0] < 1):
        raise ValueError("carga de XML inválida na landing")
    return arquivo, digest, cargas[0] if cargas else None


def ingerir(conn, raiz, regras):
    validar_regras(regras)
    landing = Landing(raiz)
    origem = "arquivo varchar, linha bigint, origem varchar, carga bigint, "
    conn.execute("begin")
    try:
        gravar(conn, "bronze_pedidos", origem + "pedido_id varchar primary key, "
               "chave_nfe varchar not null unique, data_prevista varchar, qt_itens bigint, peso_decimos_kg bigint",
               pedidos(landing))
        gravar(conn, "bronze_entregas", origem + "entrega_id varchar primary key, "
               "pedido_id varchar not null unique, viagem_id varchar, baixa_original varchar, "
               "data_realizada varchar, qt_entregue bigint", entregas(landing))
        viagens = ((*meta, *valores) for meta, valores in landing.registros("tms/tms_viagens"))
        gravar(conn, "bronze_viagens", origem + "viagem_id varchar primary key, "
               "veiculo_id varchar, tipo_viagem varchar", viagens)
        gravar(conn, "bronze_veiculos", origem + "veiculo_id varchar primary key, "
               "capacidade_kg bigint", veiculos(landing))
        gravar(conn, "bronze_documentos", "arquivo varchar, sha256 varchar, carga bigint, especie varchar, chave_cte varchar, "
               "cstat varchar, tipo_evento varchar, chave_nfe varchar, valor_centavos bigint", documentos(landing))
        conn.commit()
    except Exception:
        conn.rollback()
        raise


if __name__ == "__main__":
    import duckdb

    with duckdb.connect(BANCO) as banco:
        ingerir(banco, Path("/work/fontes"), json.load(sys.stdin))
