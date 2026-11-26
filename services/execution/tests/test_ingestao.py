"""Integração: ingestão das empresas sintéticas, comparada com as fontes por um avaliador próprio.

O avaliador (este teste) pode ler `_gerador/` e `empresa.yaml`; a ingestão não pode. As
contagens vêm de `_gerador/contagens.json` e as anomalias plantadas de
`_gerador/anomalias_plantadas.csv`. Os CSV brutos são relidos pelo `read_csv` do DuckDB, um
leitor diferente do usado pela ingestão, com o separador declarado em `empresa.yaml`.

Requisitos: Docker, a imagem da sandbox e as fontes geradas
(`python3 data/synthetic/generator/generate.py --all`).
- Sem Docker ou sem fontes, os testes são pulados; `KORDA_EXIGIR_DOCKER=1` transforma isso em falha.
- A 03_reservada só roda com `KORDA_MEDIR_03=1` (só para medição, no fim de cada etapa).
"""

import csv
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from korda_execution.ingestao import ErroIngestao, ingerir
from korda_execution.sandbox import IMAGEM_PADRAO, docker_disponivel, imagem_existe

try:
    import yaml
except ImportError:  # PyYAML vem de requirements-synthetic.txt
    yaml = None

RAIZ = Path(__file__).resolve().parents[3]
SAIDA_GERADOR = RAIZ / "data" / "synthetic" / "output"
EMPRESAS = RAIZ / "data" / "synthetic" / "empresas"
EXIGIR = os.environ.get("KORDA_EXIGIR_DOCKER") == "1"

_PRONTO = docker_disponivel() and imagem_existe(IMAGEM_PADRAO) and yaml is not None
if not _PRONTO and EXIGIR:
    raise RuntimeError("KORDA_EXIGIR_DOCKER=1, mas Docker, a imagem ou o PyYAML não estão disponíveis")

# Consultas feitas dentro da imagem (duckdb não está no worker). Parâmetros em argv[1].
AVALIADOR = r'''
import duckdb, json, sys
p = json.loads(sys.argv[1])
con = duckdb.connect()
L, B = "/work/landing/", "/work/bruto/"
def q(sql): return con.execute(sql).fetchall()
out = {"csv": {}}
for t in p["csv"]:
    pq = f"read_parquet('{L}{t}.parquet')"
    bruto = (f"read_csv('{B}{t}.csv', delim='{p['sep']}', header=true, all_varchar=true, "
             f"nullstr='\x01', allow_quoted_nulls=false)")
    cols_l = [r[0] for r in q(f"select column_name from (describe select * from {pq})")]
    cols_b = [r[0] for r in q(f"select column_name from (describe select * from {bruto})")]
    dados = ", ".join('"' + c + '"' for c in cols_b)
    out["csv"][t] = {
        "colunas_landing": cols_l, "colunas_bruto": cols_b,
        "linhas_landing": q(f"select count(*) from {pq}")[0][0],
        "linhas_bruto": q(f"select count(*) from {bruto}")[0][0],
        "so_landing": q(f"select count(*) from (select {dados} from {pq} except all select * from {bruto})")[0][0],
        "so_bruto": q(f"select count(*) from (select * from {bruto} except all select {dados} from {pq})")[0][0],
        "linhagem_ok": q(f"select bool_and(_linha = n + 1) and bool_and(_arquivo = '{t}.csv') from "
                         f"(select _linha, _arquivo, row_number() over (order by _linha) as n from {pq})")[0][0],
    }
cte = f"read_parquet('{L}cte/cte.parquet')"
nfe = f"read_parquet('{L}cte/cte_nfe.parquet')"
ev = f"read_parquet('{L}cte/cte_evento.parquet')"
out["cte_linhas"] = q(f"select count(*) from {cte}")[0][0]
out["cte_chaves"] = q(f"select count(distinct chCTe) from {cte}")[0][0]
out["cte_duplicadas"] = sorted(r[0] for r in q(f"select chCTe from {cte} group by 1 having count(*) > 1"))
out["evento_chaves"] = sorted(r[0] for r in q(f"select chCTe from {ev} where tpEvento = '110111'"))
out["evento_linhas"] = q(f"select count(*) from {ev}")[0][0]
out["cte_status_dos_cancelados"] = sorted({r[0] for r in q(
    f"select prot_cStat from {cte} where chCTe in (select chCTe from {ev})")})
out["multi_nfe"] = sorted(r[0] for r in q(f"select chCTe from {nfe} group by 1 having count(distinct chave) > 1"))
e = p["entregas"]
out["sem_data"] = sorted(r[0] for r in q(
    f"select \"{e['pedido_id']}\" from read_parquet('{L}tms/tms_entregas.parquet') where \"{e['dt_realizada']}\" = ''"))
out["datas"] = dict(q(f"select \"{e['id']}\", \"{e['dt_realizada']}\" from read_parquet('{L}tms/tms_entregas.parquet')"))
out["rejeitados"] = q(f"select count(*) from read_parquet('{L}_rejeitados.parquet')")[0][0]
print(json.dumps(out))
'''


def _strftime_para_regex(fmt: str) -> str:
    partes = {"%d": r"\d{2}", "%m": r"\d{2}", "%H": r"\d{2}", "%M": r"\d{2}", "%y": r"\d{2}", "%Y": r"\d{4}"}
    saida, i = "", 0
    while i < len(fmt):
        if fmt[i:i + 2] in partes:
            saida += partes[fmt[i:i + 2]]
            i += 2
        else:
            saida += re.escape(fmt[i])
            i += 1
    return f"^{saida}$"


def avaliar(landing: Path, bruto: Path, params: dict) -> dict:
    argv = [
        "docker", "run", "--rm", "--network", "none", "--read-only", "--tmpfs", "/tmp",
        "--user", f"{os.getuid()}:{os.getgid()}",
        "--mount", f"type=bind,src={landing},dst=/work/landing,readonly",
        "--mount", f"type=bind,src={bruto},dst=/work/bruto,readonly",
        IMAGEM_PADRAO, "python", "-c", AVALIADOR, json.dumps(params),
    ]
    r = subprocess.run(argv, capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        raise AssertionError(f"avaliador falhou: {r.stderr[-2000:]}")
    return json.loads(r.stdout)


def _conteudo(landing: Path) -> dict[str, bytes]:
    return {p.relative_to(landing).as_posix(): p.read_bytes() for p in sorted(landing.rglob("*")) if p.is_file()}


class _BaseEmpresa:
    empresa = ""

    @classmethod
    def setUpClass(cls):
        cls.bruto = SAIDA_GERADOR / cls.empresa
        if not (cls.bruto / "_gerador" / "contagens.json").is_file():
            msg = f"fontes de {cls.empresa} não geradas; rode data/synthetic/generator/generate.py"
            if EXIGIR:
                raise RuntimeError(msg)
            raise unittest.SkipTest(msg)
        cls.cfg = yaml.safe_load((EMPRESAS / cls.empresa / "empresa.yaml").read_text(encoding="utf-8"))
        cls.contagens = json.loads((cls.bruto / "_gerador" / "contagens.json").read_text(encoding="utf-8"))
        with (cls.bruto / "_gerador" / "anomalias_plantadas.csv").open(encoding="utf-8", newline="") as f:
            cls.anomalias = list(csv.DictReader(f))
        cls.tmp = Path(tempfile.mkdtemp(prefix=f"korda-ingestao-{cls.empresa}-"))
        cls.landing = cls.tmp / "landing"
        cls.resultado = ingerir(cls.bruto, cls.landing)
        cls.manifesto = cls.resultado["manifesto"]
        print(f"\n[{cls.empresa}] medição da ingestão: {json.dumps(cls.resultado['medicao'])}")
        col = cls.cfg["colunas"]["tms_entregas"]
        cls.aval = avaliar(cls.landing, cls.bruto, {
            "sep": cls.cfg["formato"]["csv"]["separador"],
            "csv": [t for t, d in cls.manifesto["tabelas"].items() if d["origem"] == "csv"],
            "entregas": {k: col[k] for k in ("id", "pedido_id", "dt_realizada")},
        })

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def ids(self, tipo):
        return sorted(a["id"] for a in self.anomalias if a["tipo"] == tipo)

    # Completude e fidelidade

    def test_csv_iguais_ao_bruto_celula_a_celula(self):
        tabelas = self.contagens["tabelas"]
        self.assertEqual(set(self.aval["csv"]), {f"{n.split('_')[0]}/{n}" for n in tabelas})
        for t, r in self.aval["csv"].items():
            with self.subTest(tabela=t):
                nome = t.split("/")[-1]
                self.assertEqual(r["linhas_landing"], tabelas[nome])
                self.assertEqual(r["linhas_bruto"], tabelas[nome])
                self.assertEqual(r["colunas_landing"], r["colunas_bruto"] + ["_arquivo", "_linha"])
                self.assertEqual((r["so_landing"], r["so_bruto"]), (0, 0))
                self.assertTrue(r["linhagem_ok"])

    def test_nomes_de_coluna_da_empresa_preservados(self):
        col = self.cfg["colunas"]
        for tabela, mapa in col.items():
            with self.subTest(tabela=tabela):
                pasta = tabela.split("_")[0]
                presentes = self.aval["csv"][f"{pasta}/{tabela}"]["colunas_bruto"]
                self.assertTrue(set(presentes) <= set(mapa.values()), presentes)

    def test_manifesto_registra_deteccao(self):
        sep = self.cfg["formato"]["csv"]["separador"]
        for a in self.manifesto["arquivos"]:
            if a["tipo"] == "csv":
                with self.subTest(arquivo=a["arquivo"]):
                    self.assertEqual((a["separador"], a["codificacao"], a["cabecalho"]), (sep, "utf-8", True))
        self.assertEqual(self.manifesto["totais"]["nao_suportado"], 0)
        self.assertEqual(self.aval["rejeitados"], 0)
        self.assertIn("sintéticos", self.manifesto["rotulo"])

    def test_cte_contagens(self):
        c = self.contagens["ctes"]
        self.assertEqual(self.aval["cte_linhas"], c["xml_cte"] + c["xml_cte_duplicado"])
        self.assertEqual(self.aval["cte_chaves"], c["emitidos"])
        self.assertEqual(self.aval["evento_linhas"], c["xml_evento_cancelamento"])
        self.assertEqual(self.manifesto["totais"]["xml"], c["xml_total"])

    # Anomalias plantadas chegam intactas

    def test_duplicatas_continuam_duplicadas(self):
        self.assertEqual(self.aval["cte_duplicadas"], self.ids("cte_duplicado"))

    def test_cancelamentos_preservados_como_evento(self):
        self.assertEqual(self.aval["evento_chaves"], self.ids("cte_cancelado"))
        # A ingestão não aplica o cancelamento: o cteProc original continua cStat 100.
        self.assertEqual(self.aval["cte_status_dos_cancelados"], ["100"])

    def test_cte_com_varios_pedidos(self):
        # O registro anota a chave original; a reemissão de um cancelado leva as mesmas NF-e.
        multi = set(self.ids("cte_multi_pedido"))
        reemitidos = {a["detalhe"].split()[-1] for a in self.anomalias
                      if a["tipo"] == "cte_cancelado" and a["id"] in multi}
        self.assertEqual(self.aval["multi_nfe"], sorted(multi | reemitidos))

    def test_entregas_sem_data_continuam_vazias(self):
        # Esperado: pedidos com data vazia no bruto, relido aqui com o módulo csv. Inclui a
        # anomalia plantada e, na 02, as entregas TRANSFERIDO das viagens TRF (fato dos dados).
        col = self.cfg["colunas"]["tms_entregas"]
        sep = self.cfg["formato"]["csv"]["separador"]
        with (self.bruto / "tms" / "tms_entregas.csv").open(encoding="utf-8", newline="") as f:
            vazias = sorted(r[col["pedido_id"]] for r in csv.DictReader(f, delimiter=sep)
                            if r[col["dt_realizada"]] == "")
        self.assertEqual(self.aval["sem_data"], vazias)
        self.assertTrue(set(self.ids("entrega_sem_data")) <= set(vazias))

    def test_datas_em_formatos_mistos_chegam_como_no_bruto(self):
        mistos = [a for a in self.anomalias if a["tipo"] == "data_formato_misto"]
        self.assertTrue(mistos)
        for a in mistos:
            with self.subTest(entrega=a["id"]):
                self.assertRegex(self.aval["datas"][a["id"]], _strftime_para_regex(a["detalhe"]))

    # Isolamento e reprodutibilidade

    def test_ingestao_nao_ve_gerador(self):
        self.assertFalse(any("_gerador" in a["arquivo"] for a in self.manifesto["arquivos"]))

    def test_duas_execucoes_geram_o_mesmo_conteudo(self):
        outra = self.tmp / "landing2"
        ingerir(self.bruto, outra)
        self.assertEqual(_conteudo(self.landing), _conteudo(outra))

    def test_destino_existente_e_recusado(self):
        with self.assertRaises(ErroIngestao):
            ingerir(self.bruto, self.landing)


@unittest.skipUnless(_PRONTO, f"Docker, imagem {IMAGEM_PADRAO} ou PyYAML indisponível")
class TestIngestao01Demo(_BaseEmpresa, unittest.TestCase):
    empresa = "01_demo"


@unittest.skipUnless(_PRONTO, f"Docker, imagem {IMAGEM_PADRAO} ou PyYAML indisponível")
class TestIngestao02Variacao(_BaseEmpresa, unittest.TestCase):
    empresa = "02_variacao"


@unittest.skipUnless(_PRONTO and os.environ.get("KORDA_MEDIR_03") == "1",
                     "03_reservada só para medição: defina KORDA_MEDIR_03=1")
class TestIngestao03Reservada(_BaseEmpresa, unittest.TestCase):
    empresa = "03_reservada"


if __name__ == "__main__":
    unittest.main()
