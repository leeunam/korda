"""Revisão independente da landing e da linhagem da transportadora sintética 01_demo."""

import csv
import io
import json
import os
import stat
from collections import Counter
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from .arquivos import _abrir_diretorio, _ler_arquivo, _sem_repeticao

# Layout físico publicado para 01_demo. Cada identidade refere-se a um registro do seed.
TABELAS_CSV = {
    "erp/erp_clientes": ("cd_cli", "erp:erp_clientes"),
    "erp/erp_pedidos": ("cd_ped", "erp:erp_pedidos"),
    "tms/tms_entregas": ("id_ent", "tms:/entregas"),
    "tms/tms_viagens": ("id_viag", "tms:/viagens"),
    "tms/tms_veiculos": ("id_veic", "tms:/veiculos"),
}
TABELAS_XML = {"cte/cte", "cte/cte_evento", "cte/cte_nfe", "cte/cte_carga"}
DECIMAIS = {"ps_bruto", "vl_cubag", "vl_merc", "cap_kg", "cap_m3", "km_rodado"}
LINHAGENS = {"pedido": "erp/erp_pedidos", "entrega": "tms/tms_entregas",
             "viagem": "tms/tms_viagens", "veiculo": "tms/tms_veiculos"}


def conferir_janela(janela):
    if not isinstance(janela, (tuple, list)) or len(janela) != 2:
        raise ValueError("janela de replay exige as datas atual e final do simulador")
    if any(type(d) is not str or date.fromisoformat(d).isoformat() != d for d in janela):
        raise ValueError("as datas do replay devem usar AAAA-MM-DD")
    if janela[0] != janela[1]:
        raise ValueError("o gabarito cobre apenas o lote integral; a janela informada requer referência própria")


def _json(pasta, nome):
    with _abrir_diretorio(pasta) as fd:
        objeto = json.loads(_ler_arquivo(fd, nome), object_pairs_hook=_sem_repeticao)
    if not isinstance(objeto, dict):
        raise ValueError(f"{nome}: objeto esperado")
    return objeto


def _objeto(obj, campo, tipo):
    valor = obj.get(campo)
    if type(valor) is not tipo:
        raise ValueError(f"campo inválido: {campo}")
    return valor


def _linhas_parquet(parquet, landing, tabela):
    # Nome interno fixo e descritor aberto sem seguir links. O manifesto não escolhe o arquivo.
    caminho = Path(landing) / (tabela + ".parquet")
    with _abrir_diretorio(caminho.parent) as pasta:
        opcoes = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
        with os.fdopen(os.open(caminho.name, opcoes, dir_fd=pasta), "rb") as fp:
            meta = os.fstat(fp.fileno())
            if not stat.S_ISREG(meta.st_mode) or meta.st_nlink != 1 or not 0 < meta.st_size <= 32 * 1024**2:
                raise ValueError(f"{tabela}: arquivo Parquet inválido")
            with parquet.ParquetFile(fp, thrift_string_size_limit=1024**2,
                                     thrift_container_size_limit=50_000) as arquivo:
                meta_pq = arquivo.metadata
                if (meta_pq.num_rows > 30_000 or meta_pq.num_columns > 128 or
                        any(meta_pq.row_group(i).total_byte_size > 64 * 1024**2 for i in range(meta_pq.num_row_groups))):
                    raise ValueError(f"{tabela}: dimensão fora da demonstração")
                for lote in arquivo.iter_batches(batch_size=256, use_threads=False):
                    yield from lote.to_pylist()


def _mesmo_valor_n1(coluna, bruto, obtido):
    if bruto == "":
        return obtido is None
    if not isinstance(obtido, str):
        return False
    if coluna in DECIMAIS:
        return Decimal(bruto.replace(",", ".")) == Decimal(obtido)
    if coluna == "dt_saida":
        return datetime.fromisoformat(bruto).isoformat(timespec="seconds") == obtido
    return bruto == obtido


def _fontes_csv(fontes):
    tabelas = {}
    for tabela, (pk, _) in TABELAS_CSV.items():
        caminho = Path(fontes) / (tabela + ".csv")
        with _abrir_diretorio(caminho.parent) as pasta:
            dados = _ler_arquivo(pasta, caminho.name).decode("utf-8-sig")
        leitor = csv.DictReader(io.StringIO(dados, newline=""), delimiter=";", strict=True)
        entidades = {}
        for linha in leitor:
            chave = linha[pk]
            if chave in entidades:
                raise ValueError(f"{tabela}: identidade duplicada na fonte")
            entidades[chave] = (leitor.line_num, linha)
        tabelas[tabela] = entidades
    return tabelas


def _conferir_csv(tabela, linhas, fontes, nivel, cargas, primeiro_dia):
    pk, origem = TABELAS_CSV[tabela]
    esperado = fontes[tabela]
    localizadores = {}
    for linha in linhas:
        chave = linha.get(pk)
        if chave in localizadores or chave not in esperado:
            raise ValueError(f"{tabela}: identidade duplicada ou desconhecida")
        n, raw = esperado[chave]
        if nivel == 0:
            if (linha.get("_arquivo"), linha.get("_linha")) != (tabela + ".csv", n):
                raise ValueError(f"{tabela}: arquivo ou linha diverge da exportação")
            if any(c not in linha or linha[c] != v for c, v in raw.items()):
                raise ValueError(f"{tabela}: conteúdo divergente na exportação")
            localizadores[chave] = (tabela + ".csv", str(n), "", "")
        else:
            carga = linha.get("_carga")
            if type(carga) is not int or carga not in cargas or linha.get("_origem") != origem:
                raise ValueError(f"{tabela}: origem ou carga inválida")
            if tabela.startswith("erp/") and carga != max(cargas):
                raise ValueError(f"{tabela}: registro fora do snapshot final do ERP")
            if tabela.startswith("tms/"):
                dia = primeiro_dia if tabela.endswith("veiculos") else (
                    fontes["tms/tms_viagens"][raw["id_viag"]][1]["dt_saida"][:10])
                if linha.get("atualizado_em") != dia + "T23:00:00-03:00":
                    raise ValueError(f"{tabela}: marca incremental divergente do replay")
            if any(c not in linha or not _mesmo_valor_n1(c, v, linha[c]) for c, v in raw.items()):
                raise ValueError(f"{tabela}: conteúdo da fonte simulada diverge do seed verificado")
            localizadores[chave] = ("", "", origem, str(carga))
    if localizadores.keys() != esperado.keys():
        raise ValueError(f"{tabela}: faltam entidades da fonte integral")
    return localizadores


def _xmls(fontes, inventario):
    import xml.etree.ElementTree as ET

    docs = {}
    filhos = {"cte/cte_nfe": Counter(), "cte/cte_carga": Counter()}
    ns = {"": "http://www.portalfiscal.inf.br/cte"}
    with _abrir_diretorio(Path(fontes) / "cte") as pasta:
        for caminho, sha in inventario.items():
            if not caminho.startswith("cte/"):
                continue
            nome = caminho.removeprefix("cte/")
            raiz = ET.fromstring(_ler_arquivo(pasta, nome))
            if raiz.tag == f"{{{ns['']}}}cteProc":
                info = raiz.find("CTe/infCte", ns)
                chave = raiz.findtext("protCTe/infProt/chCTe", namespaces=ns)
                valor = Decimal(info.findtext("vPrest/vTPrest", namespaces=ns)) * 100
                if valor != valor.to_integral_value():
                    raise ValueError("valor de CT-e fora de centavos inteiros")
                dia = info.findtext("ide/dhEmi", namespaces=ns)[:10]
                for i, el in enumerate(info.findall("infCTeNorm/infDoc/infNFe", ns), 1):
                    filhos["cte/cte_nfe"][(nome, i, chave, el.findtext("chave", namespaces=ns))] += 1
                for i, el in enumerate(info.findall("infCTeNorm/infCarga/infQ", ns), 1):
                    campos = tuple(el.findtext(c, namespaces=ns) for c in ("cUnid", "tpMed", "qCarga"))
                    filhos["cte/cte_carga"][(nome, i, chave, *campos)] += 1
                campos = {"chCTe": chave, "prot_chCTe": chave, "prot_cStat": raiz.findtext(
                    "protCTe/infProt/cStat", namespaces=ns), "vTPrest": info.findtext("vPrest/vTPrest", namespaces=ns)}
                docs[nome] = ("cte/cte", sha, dia, campos, int(valor))
            else:
                evento = raiz.find("eventoCTe/infEvento", ns)
                dia = evento.findtext("dhEvento", namespaces=ns)[:10]
                campos = {c: evento.findtext(c, namespaces=ns) for c in ("chCTe", "tpEvento")}
                campos["ret_cStat"] = raiz.findtext("retEventoCTe/infEvento/cStat", namespaces=ns)
                docs[nome] = ("cte/cte_evento", sha, dia, campos, None)
    return docs, filhos


def _parcelas_por_xml(documentos, vinculos, pedidos):
    """Rateio de referência em centavos pelo peso bruto de cada NF-e (01_demo)."""
    pesos = {r["ch_nfe"]: (pid, Decimal(r["ps_bruto"].replace(",", "."))) for pid, (_, r) in pedidos.items()}
    por_arquivo = {}
    for nome, _ordem, _chave, nfe in vinculos:
        if nfe not in pesos:
            raise ValueError("NF-e fiscal sem pedido de referência")
        pid, peso = pesos[nfe]
        por_arquivo.setdefault(nome, {})[pid] = peso
    saida = {}
    for nome, bases in por_arquivo.items():
        total = sum(bases.values())
        if total <= 0:
            raise ValueError("CT-e sem peso positivo para rateio")
        centavos = documentos[nome][4]
        quocientes = {pid: divmod(centavos * peso, total) for pid, peso in bases.items()}
        partes = {pid: int(q) for pid, (q, _) in quocientes.items()}
        resto = centavos - sum(partes.values())
        for pid in sorted(bases, key=lambda p: (-quocientes[p][1], p))[:resto]:
            partes[pid] += 1
        saida[nome] = partes
    return saida


def _documento(linha, docs, nivel, cargas):
    arquivo = _objeto(linha, "_arquivo", str)
    nome = arquivo.rsplit("/", 1)[-1]
    if nome not in docs:
        raise ValueError("Parquet contém XML fora da referência")
    tabela, digest, dia, campos, centavos = docs[nome]
    origem = f"{dia}/{nome}" if nivel else f"cte/{nome}"
    carga = linha.get("_carga")
    if arquivo != origem or linha.get("_xml_sha256") != digest:
        raise ValueError("caminho ou digest de XML diverge da fonte")
    if nivel and (type(carga) is not int or carga not in cargas):
        raise ValueError("identificador de carga de XML inválido")
    return nome, tabela, campos, (arquivo, digest, carga, centavos)


def _conferir_landing(ler, meta, estado, fontes, inventario, nivel, janela):
    tabelas = _objeto(meta, "tabelas", dict)
    if set(tabelas) != set(TABELAS_CSV) | TABELAS_XML:
        raise ValueError("manifesto não contém as nove tabelas da demo")
    rejeitados = _objeto(meta, "rejeitados", dict)
    if rejeitados.get("linhas") != 0 or next(iter(ler("_rejeitados")), None) is not None:
        raise ValueError("a landing contém registros rejeitados")
    cargas = set()
    if nivel == 1:
        lista = _objeto(meta, "cargas", list)
        cargas = {c.get("carga") for c in lista if isinstance(c, dict)}
        if (not lista or any(not isinstance(c, dict) or type(c.get("carga")) is not int for c in lista)
                or cargas != set(range(1, len(lista) + 1)) or lista != estado.get("cargas")):
            raise ValueError("cargas da landing divergem do estado confirmado")
        if _objeto(estado, "ultima_carga", int) != len(lista) or _objeto(meta, "plano", dict).get("company_id") != "01_demo":
            raise ValueError("empresa ou última carga inválida")
    else:
        arquivos = _objeto(meta, "arquivos", list)
        pares = {i.get("arquivo"): i.get("sha256") for i in arquivos if isinstance(i, dict)}
        if len(pares) != len(arquivos) or pares != inventario:
            raise ValueError("inventário do manifesto diverge dos hashes das fontes")
    tabelas_raw = _fontes_csv(fontes)
    docs, filhos = _xmls(fontes, inventario)
    parcelas = _parcelas_por_xml(docs, filhos["cte/cte_nfe"], tabelas_raw["erp/erp_pedidos"])
    dias = {v[1]["dt_emis"] for v in tabelas_raw["erp/erp_pedidos"].values()}
    dias.update(v[1]["dt_saida"][:10] for v in tabelas_raw["tms/tms_viagens"].values())
    dias.update(doc[2] for doc in docs.values())
    if not dias or (nivel == 1 and janela[1] != max(dias)):
        raise ValueError("dia final do replay diverge da última data observada no seed independente")
    locais = {t: _conferir_csv(t, ler(t), tabelas_raw, nivel, cargas, min(dias)) for t in TABELAS_CSV}
    xml_lidos, locais_xml, carga_xml = set(), {}, {}
    contagens = {t: len(l) for t, l in locais.items()}
    for tabela in sorted(TABELAS_XML):
        total = 0
        for linha in ler(tabela):
            total += 1
            nome, tipo, campos, local = _documento(linha, docs, nivel, cargas)
            if nivel and carga_xml.setdefault(nome, local[2]) != local[2]:
                raise ValueError("as linhas do mesmo XML apontam para cargas diferentes")
            if tabela in filhos:
                atributos = ("chave",) if tabela == "cte/cte_nfe" else ("cUnid", "tpMed", "qCarga")
                k = (nome, linha.get("_ordem"), linha.get("chCTe"), *(linha.get(c) for c in atributos))
                if filhos[tabela][k] <= 0:
                    raise ValueError(f"{tabela}: vínculo XML inesperado")
                filhos[tabela][k] -= 1
            else:
                if nome in xml_lidos or tipo != tabela or any(linha.get(c) != v for c, v in campos.items()):
                    raise ValueError(f"{tabela}: registro fiscal diverge da fonte")
                xml_lidos.add(nome)
                locais_xml[local[0]] = (campos["chCTe"], *local[1:])
        contagens[tabela] = total
    if xml_lidos != docs.keys() or any(+c for c in filhos.values()):
        raise ValueError("documentos, eventos ou vínculos XML ausentes na landing")
    for t, n in contagens.items():
        if not isinstance(tabelas[t], dict) or tabelas[t].get("arquivo") != t + ".parquet" or tabelas[t].get("linhas") != n:
            raise ValueError(f"{t}: contagem ou caminho do manifesto diverge da tabela materializada")
    if nivel:
        registrados = _objeto(estado, "arquivos_cte", list)
        if (any(type(n) is not str for n in registrados) or len(registrados) != len(locais_xml)
                or set(registrados) != locais_xml.keys()):
            raise ValueError("inventário fiscal do estado diverge da landing")
    return {"locais": locais, "xml": locais_xml, "raw": tabelas_raw, "parcelas": parcelas}


def manifesto_landing(landing):
    return _json(landing, "manifesto.json")


def conferir_landing(landing, fontes, inventario, nivel, janela, *, manifesto=None):
    meta = manifesto_landing(landing) if manifesto is None else manifesto
    if meta.get("formato") != "korda.landing/v0" or type(meta.get("nivel", 0)) is not int or meta.get("nivel", 0) != nivel:
        raise ValueError("manifesto incompatível com o nível e a janela declarados")
    estado = _json(Path(landing) / "_estado", "estado.json") if nivel else None
    try:
        import pyarrow
        import pyarrow.parquet as parquet
    except ImportError as exc:
        raise ValueError("leitor PyArrow indisponível para conferir os Parquets da landing") from exc
    try:
        return _conferir_landing(lambda t: _linhas_parquet(parquet, landing, t), meta, estado,
                                 fontes, inventario, nivel, janela)
    except pyarrow.ArrowException as exc:
        raise ValueError("Parquet inválido ou formato não suportado no revisor") from exc


def conferir_linhagem(tabela, linha, referencia, trilha):
    campos = ("pedido", "entrega") if tabela == "por_pedido.csv" else ("viagem", "veiculo")
    for campo in campos:
        chave = linha.get(campo + "_id")
        tabela_raw = LINHAGENS[campo]
        declarado = tuple(linha.get(f"{tipo}_{campo}") for tipo in ("arquivo", "linha", "origem", "carga"))
        if declarado != trilha["locais"][tabela_raw].get(chave):
            raise ValueError(f"{campo}: linhagem exportada não corresponde à entrada verificada")
    if tabela != "por_pedido.csv":
        return
    pedido = trilha["raw"]["erp/erp_pedidos"][linha["pedido_id"]][1]
    entrega = trilha["raw"]["tms/tms_entregas"][linha["entrega_id"]][1]
    if (entrega["nr_ped"] != linha["pedido_id"] or pedido["ch_nfe"] != linha.get("chave_nfe")
            or entrega["id_viag"] != linha["viagem_id"] or linha.get("qt_entregue") != entrega["qt_entregue"]
            or linha.get("qt_itens") != pedido["qt_itens"]
            or Decimal(linha.get("peso_decimos_kg") or "NaN") != Decimal(pedido["ps_bruto"].replace(",", ".")) * 10):
        raise ValueError("linhagem de pedido aponta para outra entrega, viagem ou NF-e")
    itens = json.loads(linha.get("linhagem_cte", "null"), object_pairs_hook=_sem_repeticao)
    if not isinstance(itens, list):
        raise ValueError("linhagem de CT-e ausente no pedido")
    chaves = []
    total = 0
    for item in itens:
        if not isinstance(item, dict):
            raise ValueError("vínculo de CT-e inválido")
        esperado = trilha["xml"].get(_objeto(item, "arquivo", str))
        centavos = _objeto(item, "frete_centavos", int)
        carga = item.get("carga")
        if carga is not None and type(carga) is not int:
            raise ValueError("carga de CT-e inválida")
        if esperado != (item.get("chave_cte"), item.get("sha256"), carga, centavos):
            raise ValueError("linhagem ou valor do CT-e diverge do documento independente")
        chaves.append(item["chave_cte"])
        parcela = _objeto(item, "parcela_centavos", int)
        por_pedido = trilha["parcelas"].get(item["arquivo"].rsplit("/", 1)[-1], {})
        if parcela != por_pedido.get(linha["pedido_id"]):
            raise ValueError("parcela de frete do XML diverge do rateio independente por peso")
        total += parcela
    chaves_ref = referencia["ctes"].split("+") if referencia["ctes"] else []
    if sorted(chaves) != sorted(chaves_ref) or total != Decimal(referencia["custo_frete_rateado"]) * 100:
        raise ValueError("documentos ou centavos de rateio divergem do pedido de referência")
