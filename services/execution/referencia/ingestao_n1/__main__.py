"""python -m ingestao_n1  (dentro da sandbox, na rede interna do ambiente simulado)

Entradas: plano em $KORDA_PLANO (padrão /work/plano/ingestao.json), CT-e em
$KORDA_ENTREGA_CTE (/work/entrega/cte, somente leitura), landing em $KORDA_LANDING
(/work/landing, escrita) e credenciais em variáveis KORDA_* listadas no plano.

Cada execução é uma **carga**:
- ERP: snapshot completo (o ERP não expõe data de atualização);
- TMS: registros com `atualizado_em` maior que a marca anterior;
- CT-e: arquivos ainda não processados.
Sem novidade, nada muda (idempotência). Mudança de esquema: nada é gravado; um
escalonamento vai para `_escalonamentos/` e o código de saída é 3. Fonte que esgota as
tentativas do plano: nada é gravado e a saída é 1.

Landing (mesmos caminhos do nível 0, para a K09 não mudar):
    erp/<tabela>.parquet        último snapshot
    tms/<tabela>.parquet        união das cargas, na ordem
    cte/cte*.parquet            união das cargas, na ordem
    _rejeitados.parquet, manifesto.json
    _cargas/<NNNN>/             o que cada carga trouxe; _estado/estado.json (marcas, arquivos)
Tudo como texto (VARCHAR), com linhagem `_origem`/`_arquivo`, `_xml_sha256` e `_carga`.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import resource
import shutil
import sys
import time
from pathlib import Path

from korda_ingestao import cte as cte_xml
from korda_ingestao import parquet

from . import __version__
from .fontes import Escalar, FalhaFonte, Tentativas, ler_erp, ler_tms, novos_arquivos

ROTULO = ("Dados sintéticos de sistemas do cliente SIMULADOS (nível 1); não é conector real. "
          "A ingestão não limpa: duplicatas, cancelados e formatos mistos chegam intactos.")
TABELAS_CTE = {"cte": cte_xml.COLUNAS_CTE, "cte_nfe": cte_xml.COLUNAS_NFE,
               "cte_carga": cte_xml.COLUNAS_CARGA, "cte_evento": cte_xml.COLUNAS_EVENTO}
REJEITADOS = [("_origem", "VARCHAR"), ("_arquivo", "VARCHAR"), ("_xml_sha256", "VARCHAR"),
              ("motivo", "VARCHAR"), ("_carga", "BIGINT")]


def _tipo(c: str) -> str:
    return "BIGINT" if c in ("_carga", "_ordem") else "VARCHAR"


def _versao_codigo() -> dict:
    h = hashlib.sha256()
    for arq in sorted(Path(__file__).parent.glob("*.py")):
        h.update(arq.name.encode() + arq.read_bytes())
    return {"pacote": "ingestao_n1 (referência)", "versao": __version__, "sha256_fontes": h.hexdigest(),
            "python": platform.python_version()}


def _ler_json(p: Path, padrao):
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else padrao


def _gravar_json(p: Path, dados) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(dados, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, p)


def _hash_linhas(cols, linhas) -> str:
    return hashlib.sha256(json.dumps([cols, linhas], ensure_ascii=False).encode()).hexdigest()


def _checar_esquema(estado: dict, chave: str, colunas: list[str], fonte: str) -> None:
    anterior = estado["esquemas"].get(chave)
    if anterior is not None and anterior != colunas:
        raise Escalar("mudanca_de_esquema", {
            "fonte": fonte, "objeto": chave, "esperado": anterior, "recebido": colunas,
            "novas": [c for c in colunas if c not in anterior],
            "ausentes": [c for c in anterior if c not in colunas],
        })


def executar(plano: dict, landing: Path, entrega_cte: Path) -> dict:
    estado_arq = landing / "_estado" / "estado.json"
    estado = _ler_json(estado_arq, {"ultima_carga": 0, "marcas": {}, "arquivos_cte": [], "esquemas": {},
                                    "erp_hash": {}, "cargas": []})
    carga = estado["ultima_carga"] + 1
    tentativas = Tentativas()
    fontes = {f["system"]: f for f in plano["sources"]}
    tabelas: dict[str, tuple[list[tuple[str, str]], list[list]]] = {}
    novidades = 0
    rejeitados: list[list] = []
    novo_estado = json.loads(json.dumps(estado))

    if "erp" in fontes:
        for nome, (cols, linhas) in ler_erp(fontes["erp"], tentativas).items():
            _checar_esquema(estado, f"erp/{nome}", cols, "erp")
            novo_estado["esquemas"][f"erp/{nome}"] = cols
            h = _hash_linhas(cols, linhas)
            novidades += h != estado["erp_hash"].get(nome)
            novo_estado["erp_hash"][nome] = h
            origem = f"erp:{nome}"
            tabelas[f"erp/{nome}"] = ([(c, "VARCHAR") for c in cols] + [("_origem", "VARCHAR"), ("_carga", "BIGINT")],
                                      [l + [origem, carga] for l in linhas])

    if "tms" in fontes:
        f = fontes["tms"]
        for nome, (regs, marca) in ler_tms(f, estado["marcas"], tentativas).items():
            cols = list(estado["esquemas"].get(f"tms/{nome}") or [])
            vistas = []
            for r in regs:
                for k in r:
                    if k not in vistas:
                        vistas.append(k)
            if regs:
                if cols:
                    _checar_esquema(estado, f"tms/{nome}", vistas if set(vistas) != set(cols) else cols, "tms")
                else:
                    cols = vistas
            novo_estado["marcas"][nome] = marca
            if not cols:  # recurso ainda sem nenhum registro: a tabela nasce na primeira carga com dados
                continue
            novo_estado["esquemas"][f"tms/{nome}"] = cols
            novidades += len(regs)
            loc = next(o["locator"] for o in f["objects"] if o["name"] == nome)
            tabelas[f"tms/{nome}"] = ([(c, "VARCHAR") for c in cols] + [("_origem", "VARCHAR"), ("_carga", "BIGINT")],
                                      [[r.get(c) for c in cols] + [f"tms:{loc}", carga] for r in regs])

    if "cte" in fontes:
        padrao = fontes["cte"]["objects"][0]["locator"]
        arquivos = novos_arquivos(entrega_cte, padrao, set(estado["arquivos_cte"]))
        linhas_cte = {n: [] for n in TABELAS_CTE}
        for p in arquivos:
            rel = p.relative_to(entrega_cte).as_posix()
            dados = p.read_bytes()
            sha = cte_xml.sha256(dados)
            lido = cte_xml.ler_xml(dados)
            if lido.rejeitado:
                rejeitados.append([f"cte:{rel}", rel, sha, lido.rejeitado, carga])
            for n, cols in TABELAS_CTE.items():
                for linha in getattr(lido, n):
                    linhas_cte[n].append([linha.get(c) for c in cols] + [rel, sha, carga])
            novo_estado["arquivos_cte"].append(rel)
        novidades += len(arquivos)
        for n, cols in TABELAS_CTE.items():
            tabelas[f"cte/{n}"] = ([(c, _tipo(c)) for c in cols] +
                                   [("_arquivo", "VARCHAR"), ("_xml_sha256", "VARCHAR"), ("_carga", "BIGINT")],
                                   linhas_cte[n])

    if not novidades:
        return {"resultado": "sem_novidades", "carga": None, "tentativas_http": tentativas.__dict__}

    # 1) Gravar a carga numa pasta temporária e publicá-la com rename.
    pasta = landing / "_cargas" / f"{carga:04d}"
    tmp = landing / "_cargas" / f".{carga:04d}.tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    staging = landing / "_staging"
    con = parquet.conectar()
    try:
        for nome, (esquema, linhas) in tabelas.items():
            parquet.gravar(con, tmp / f"{nome}.parquet", esquema, linhas, staging)
        parquet.gravar(con, tmp / "_rejeitados.parquet", REJEITADOS, rejeitados, staging)
        contagens = {n: len(l) for n, (_, l) in tabelas.items()}
        _gravar_json(tmp / "carga.json", {"carga": carga, "contagens": contagens, "rejeitados": len(rejeitados),
                                          "marcas": novo_estado["marcas"], "tentativas_http": tentativas.__dict__})
        shutil.rmtree(pasta, ignore_errors=True)  # resto de uma carga que não chegou a ser registrada
        os.replace(tmp, pasta)

        # 2) Reconstruir a landing canônica a partir das cargas registradas + esta.
        cargas = [c["carga"] for c in estado["cargas"]] + [carga]
        for nome in tabelas:
            if nome.startswith("erp/"):
                fontes_t = [pasta / f"{nome}.parquet"]
            else:
                fontes_t = [landing / "_cargas" / f"{c:04d}" / f"{nome}.parquet" for c in cargas]
                fontes_t = [p for p in fontes_t if p.is_file()]
            _uniao(con, fontes_t, landing / f"{nome}.parquet")
        _uniao(con, [p for c in cargas if (p := landing / "_cargas" / f"{c:04d}" / "_rejeitados.parquet").is_file()],
               landing / "_rejeitados.parquet")
        tabelas_manifesto = {
            nome: {"arquivo": f"{nome}.parquet", "origem": nome.split("/")[0],
                   "linhas": con.execute(f"select count(*) from read_parquet({parquet.literal(str(landing / f'{nome}.parquet'))})").fetchone()[0],
                   "colunas": [{"nome": c, "tipo": t} for c, t in esquema]}
            for nome, (esquema, _) in sorted(tabelas.items())
        }
        n_rej = con.execute(f"select count(*) from read_parquet({parquet.literal(str(landing / '_rejeitados.parquet'))})").fetchone()[0]
    finally:
        con.close()
        shutil.rmtree(staging, ignore_errors=True)

    # 3) Estado por último: só agora a carga conta como registrada.
    novo_estado["ultima_carga"] = carga
    novo_estado["cargas"] = estado["cargas"] + [{"carga": carga, "contagens": contagens}]
    _gravar_json(estado_arq, novo_estado)
    _gravar_json(landing / "manifesto.json", {
        "formato": "korda.landing/v0", "nivel": 1, "rotulo": ROTULO, "codigo": _versao_codigo(),
        "plano": {"company_id": plano["company_id"], "schema_version": plano["schema_version"],
                  "sha256": hashlib.sha256(json.dumps(plano, sort_keys=True).encode()).hexdigest()},
        "cargas": novo_estado["cargas"],
        "rejeitados": {"arquivo": "_rejeitados.parquet", "linhas": n_rej},
        "tabelas": tabelas_manifesto,
    })
    return {"resultado": "carga", "carga": carga, "contagens": contagens, "tentativas_http": tentativas.__dict__}


def _uniao(con, arquivos: list[Path], destino: Path) -> None:
    lista = "[" + ", ".join(parquet.literal(str(p)) for p in arquivos) + "]"
    tmp = destino.with_name(destino.name + ".tmp")
    destino.parent.mkdir(parents=True, exist_ok=True)
    con.execute(f"COPY (SELECT * FROM read_parquet({lista})) TO {parquet.literal(str(tmp))} (FORMAT parquet)")
    os.replace(tmp, destino)


def main() -> int:
    plano_arq = Path(os.environ.get("KORDA_PLANO", "/work/plano/ingestao.json"))
    landing = Path(os.environ.get("KORDA_LANDING", "/work/landing"))
    entrega = Path(os.environ.get("KORDA_ENTREGA_CTE", "/work/entrega/cte"))
    plano = json.loads(plano_arq.read_text(encoding="utf-8"))
    if plano.get("schema_version") != "ingestion_plan/0.1.0":
        print(json.dumps({"resultado": "falhou", "erro": "versão de plano desconhecida"}))
        return 2
    inicio = time.monotonic()
    codigo = 0
    try:
        saida = executar(plano, landing, entrega)
    except Escalar as e:
        estado = _ler_json(landing / "_estado" / "estado.json", {"ultima_carga": 0})
        registro = {"motivo": e.motivo, "carga_tentada": estado["ultima_carga"] + 1, **e.detalhes,
                    "acao": "nada foi gravado; decisão humana necessária (plano: on_schema_change=escalar)"}
        _gravar_json(landing / "_escalonamentos" / f"{registro['carga_tentada']:04d}.json", registro)
        saida, codigo = {"resultado": "escalado", "escalonamento": registro}, 3
    except FalhaFonte as e:
        saida, codigo = {"resultado": "falhou", "erro": str(e)}, 1
    uso = resource.getrusage(resource.RUSAGE_SELF)
    saida["medicao"] = {"tempo_s": round(time.monotonic() - inicio, 3),
                        "memoria_max_mb": round(uso.ru_maxrss / 1024, 1)}
    print(json.dumps(saida, ensure_ascii=False))
    return codigo


if __name__ == "__main__":
    sys.exit(main())
