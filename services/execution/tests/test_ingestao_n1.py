"""Testes de aceite da ingestão de nível 1 (os do plano: at-completude, at-idempotencia,
at-incremental, at-resiliencia, at-mudanca-esquema), rodados contra a ingestão de REFERÊNCIA.

O avaliador é próprio: lê o que o ambiente simulado serve direto do armazenamento dele
(partições por dia em runs/sim-<id>/preparo e a pasta de entrega), sem usar a API nem o
código de ingestão, e compara com a landing linha a linha. Quando o harness (K10) existir,
os mesmos testes valem para o código gerado pelo agente (troque `codigo`/`modulo`).

Precisa de Docker, das imagens korda-sandbox:dev, korda-simulados:dev e postgres:17.6-alpine,
e das fontes geradas de 01_demo e 02_variacao. A 03_reservada não é usada aqui.
"""

import copy
import csv
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from korda_execution.ingestao_n1 import executar_ingestao
from korda_execution.sandbox import IMAGEM_PADRAO, docker_disponivel, imagem_existe

RAIZ = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(RAIZ / "infra" / "sistemas-simulados"))
from korda_simulados.controle import AmbienteSimulado, imagens_disponiveis  # noqa: E402

PLANOS = RAIZ / "packages" / "contracts" / "ingestion_plan" / "v0.1.0" / "examples"
SAIDA = RAIZ / "data" / "synthetic" / "output"
EXIGIR = os.environ.get("KORDA_EXIGIR_DOCKER") == "1"
_PRONTO = docker_disponivel() and imagem_existe(IMAGEM_PADRAO) and imagens_disponiveis()
if not _PRONTO and EXIGIR:
    raise RuntimeError("KORDA_EXIGIR_DOCKER=1, mas Docker ou as imagens não estão disponíveis")

TABELAS_ESPERADAS = {  # mesmos caminhos da landing de nível 0
    "erp/erp_clientes", "erp/erp_pedidos", "tms/tms_veiculos", "tms/tms_viagens", "tms/tms_entregas",
    "cte/cte", "cte/cte_nfe", "cte/cte_carga", "cte/cte_evento",
}
LEITOR_LANDING = r'''
import duckdb, glob, json, os
out = {}
for f in sorted(glob.glob("/work/landing/*/*.parquet")):
    nome = os.path.relpath(f, "/work/landing")[:-8]
    cur = duckdb.sql(f"select * from read_parquet('{f}')")
    out[nome] = {"colunas": cur.columns, "linhas": [list(map(lambda v: v if v is None or isinstance(v, str) else str(v), r)) for r in cur.fetchall()]}
print(json.dumps(out))
'''


def ler_landing(landing: Path) -> dict:
    r = subprocess.run(["docker", "run", "--rm", "--network", "none", "--read-only", "--tmpfs", "/tmp",
                        "--user", f"{os.getuid()}:{os.getgid()}",
                        "--mount", f"type=bind,src={landing},dst=/work/landing,readonly",
                        IMAGEM_PADRAO, "python", "-c", LEITOR_LANDING], capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        raise AssertionError(r.stderr[-2000:])
    return json.loads(r.stdout)


def servido(amb: AmbienteSimulado) -> dict:
    """O que o ambiente serve no dia atual, lido do armazenamento do simulador."""
    cat = amb.catalogo
    dias = [d for d in cat["dias"] if d <= amb.dia_atual]
    out = {}
    for tabela, info in cat["erp"].items():
        linhas = []
        for d in dias:
            arq = amb.dir_preparo / "dias" / d / "erp" / f"{tabela}.csv"
            if arq.is_file():
                with arq.open(encoding="utf-8", newline="") as f:
                    linhas += [[v if v != "" else None for v in r] for r in list(csv.reader(f))[1:]]
        out[f"erp/{tabela}"] = {"colunas": [c for c, _ in info["colunas"]], "linhas": linhas}
    mud = cat.get("mudanca_esquema")
    for tabela, info in cat["tms"].items():
        regs = []
        for d in dias:
            arq = amb.dir_preparo / "dias" / d / "tms" / f"{tabela}.jsonl"
            if arq.is_file():
                regs += [json.loads(l, parse_int=str, parse_float=str) for l in arq.read_text(encoding="utf-8").splitlines() if l]
        cols = info["colunas"] + [cat["campo_atualizacao"]]
        if mud and mud["tabela"] == tabela and amb.dia_atual >= mud["a_partir_de"]:
            cols = [mud["novo_nome"] if c == mud["coluna"] else c for c in cols]
            regs = [{(mud["novo_nome"] if k == mud["coluna"] else k): v for k, v in r.items()} for r in regs]
        out[f"tms/{tabela}"] = {"colunas": cols, "linhas": [[r.get(c) for c in cols] for r in regs]}
    pasta = Path(amb.credenciais["cte"]["pasta_host"])
    xml = {p.relative_to(pasta).as_posix(): p.read_bytes() for p in pasta.rglob("*.xml")}
    out["cte"] = {
        "cteProc": sorted(k for k, v in xml.items() if b"<cteProc" in v),
        "procEventoCTe": sorted(k for k, v in xml.items() if b"<procEventoCTe" in v),
        "sha": Counter(hashlib.sha256(v).hexdigest() for v in xml.values()),
    }
    return out


def hash_pasta(p: Path, ignorar=("_escalonamentos",)) -> dict:
    return {a.relative_to(p).as_posix(): hashlib.sha256(a.read_bytes()).hexdigest()
            for a in sorted(p.rglob("*")) if a.is_file() and a.relative_to(p).parts[0] not in ignorar}


class _Base:
    def assertLandingIgualAoServido(self, landing: Path, amb: AmbienteSimulado):
        lan, srv = ler_landing(landing), servido(amb)
        self.assertEqual(set(lan), TABELAS_ESPERADAS)
        for nome in sorted(n for n in srv if n != "cte"):
            with self.subTest(tabela=nome):
                cols = srv[nome]["colunas"]
                self.assertEqual(lan[nome]["colunas"], cols + ["_origem", "_carga"])
                obtido = Counter(tuple(r[:len(cols)]) for r in lan[nome]["linhas"])
                esperado = Counter(tuple(r) for r in srv[nome]["linhas"])
                self.assertEqual(obtido, esperado)
        i_arq = lambda t: lan[t]["colunas"].index("_arquivo")  # noqa: E731
        self.assertEqual(sorted(r[i_arq("cte/cte")] for r in lan["cte/cte"]["linhas"]), srv["cte"]["cteProc"])
        self.assertEqual(sorted(r[i_arq("cte/cte_evento")] for r in lan["cte/cte_evento"]["linhas"]),
                         srv["cte"]["procEventoCTe"])
        shas = Counter(r[lan[t]["colunas"].index("_xml_sha256")]
                       for t in ("cte/cte", "cte/cte_evento") for r in lan[t]["linhas"])
        self.assertEqual(shas, srv["cte"]["sha"])
        return lan


def plano_de_medicao(empresa: str, destino: Path) -> Path:
    """Plano genérico para a 03_reservada, derivado do exemplo da 02 sem ler nada da 03:
    chaves vazias (ordena pela primeira coluna) e sem colunas sensíveis."""
    plano = json.loads((PLANOS / "02_variacao.json").read_text(encoding="utf-8"))
    plano.update(company_id=empresa, project_id=f"medicao-{empresa}")
    for f in plano["sources"]:
        for o in f["objects"]:
            o["key"], o["sensitive_columns"] = [], []
    destino.write_text(json.dumps(plano), encoding="utf-8")
    return destino


class _AceiteReplay(_Base):
    """Uma sequência de replay: carga inicial, repetição, dia novo e dia com mudança de esquema."""

    empresa = ""

    @classmethod
    def setUpClass(cls):
        if not (SAIDA / cls.empresa / "_gerador" / "contagens.json").is_file():
            if EXIGIR:
                raise RuntimeError(f"fontes de {cls.empresa} não geradas")
            raise unittest.SkipTest(f"fontes de {cls.empresa} não geradas")
        cls.tmp = Path(tempfile.mkdtemp(prefix=f"korda-n1-{cls.empresa}-"))
        # Dois dias para o replay: o penúltimo é o "dia novo"; o último traz a coluna renomeada.
        cls.amb = AmbienteSimulado(cls.empresa, raiz_runs=cls.tmp, dias_para_replay=2,
                                   permitir_reservada=cls.empresa == "03_reservada").subir()
        cls.landing = cls.tmp / "landing"
        cls.plano = (PLANOS / f"{cls.empresa}.json" if cls.empresa != "03_reservada"
                     else plano_de_medicao(cls.empresa, cls.tmp / "plano.json"))

    @classmethod
    def tearDownClass(cls):
        cls.amb.destruir()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def rodar(self):
        r = executar_ingestao(self.amb.credenciais, self.plano, self.landing)
        print(f"\n[{self.empresa}] {r['saida'].get('resultado')} {json.dumps(r['saida'].get('medicao'))} "
              f"parede={r['tempo_parede_s']}s tentativas={r['saida'].get('tentativas_http')}")
        return r

    def test_1_completude(self):
        r = self.rodar()
        self.assertEqual(r["situacao"], "ok", r)
        self.assertEqual(r["saida"]["carga"], 1)
        self.assertLandingIgualAoServido(self.landing, self.amb)
        manifesto = json.loads((self.landing / "manifesto.json").read_text(encoding="utf-8"))
        self.assertEqual(manifesto["nivel"], 1)
        self.assertIn("SIMULADOS", manifesto["rotulo"])
        self.assertEqual(set(manifesto["tabelas"]), TABELAS_ESPERADAS)

    def test_2_idempotencia(self):
        antes = hash_pasta(self.landing)
        r = self.rodar()
        self.assertEqual((r["situacao"], r["saida"]["resultado"]), ("ok", "sem_novidades"), r)
        self.assertEqual(hash_pasta(self.landing), antes)

    def test_3_incremental(self):
        dia = self.amb.avancar()
        r = self.rodar()
        self.assertEqual(r["situacao"], "ok", r)
        c = r["saida"]["contagens"]
        cat = self.amb.catalogo["contagens"]
        for tabela in ("tms_viagens", "tms_entregas"):
            self.assertEqual(c[f"tms/{tabela}"], cat["tms"][tabela].get(dia, 0), tabela)
        self.assertEqual(c["cte/cte"] + c["cte/cte_evento"], cat["cte"].get(dia, 0))
        self.assertLandingIgualAoServido(self.landing, self.amb)

    def test_4_mudanca_de_esquema_escala_sem_gravar(self):
        self.amb.avancar()
        antes = hash_pasta(self.landing)
        r = self.rodar()
        self.assertEqual(r["situacao"], "escalado", r)
        esc = r["saida"]["escalonamento"]
        mud = self.amb.catalogo["mudanca_esquema"]
        self.assertEqual((esc["motivo"], esc["novas"], esc["ausentes"]),
                         ("mudanca_de_esquema", [mud["novo_nome"]], [mud["coluna"]]))
        self.assertEqual(hash_pasta(self.landing), antes)  # nada corrigido em silêncio
        self.assertTrue(list((self.landing / "_escalonamentos").glob("*.json")))


@unittest.skipUnless(_PRONTO, "Docker ou imagens indisponíveis")
class TestAceite01Demo(_AceiteReplay, unittest.TestCase):
    empresa = "01_demo"


@unittest.skipUnless(_PRONTO and os.environ.get("KORDA_MEDIR_03") == "1",
                     "03_reservada só para medição: defina KORDA_MEDIR_03=1")
class TestAceite03Reservada(_AceiteReplay, unittest.TestCase):
    empresa = "03_reservada"


@unittest.skipUnless(_PRONTO, "Docker ou imagens indisponíveis")
class TestResiliencia02(_Base, unittest.TestCase):
    def setUp(self):
        if not (SAIDA / "02_variacao" / "cte").is_dir():
            self.skipTest("fontes de 02_variacao não geradas")
        self.tmp = Path(tempfile.mkdtemp(prefix="korda-n1-02-"))
        plano = json.loads((PLANOS / "02_variacao.json").read_text(encoding="utf-8"))
        tms = next(f for f in plano["sources"] if f["id"] == "tms")
        tms["resilience"].update(timeout_seconds=1, backoff_seconds=[0.2, 0.5, 1, 1, 1])
        self.plano = self.tmp / "plano.json"
        self.plano.write_text(json.dumps(plano), encoding="utf-8")

    def tearDown(self):
        self.amb.destruir()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_500_timeout_e_429_superados_dentro_do_limite(self):
        self.amb = AmbienteSimulado(
            "02_variacao", raiz_runs=self.tmp, mudanca=None, limite_rps=0,
            falhas={"sequencia": {"1": "500", "2": "timeout", "3": "429", "5": "500"}, "atraso_timeout_s": 3}).subir()
        r = executar_ingestao(self.amb.credenciais, self.plano, self.tmp / "landing")
        self.assertEqual(r["situacao"], "ok", r)
        motivos = r["saida"]["tentativas_http"]["por_motivo"]
        self.assertGreaterEqual(motivos.get("500", 0), 2)
        self.assertGreaterEqual(motivos.get("timeout", 0), 1)
        self.assertGreaterEqual(motivos.get("429", 0), 1)
        self.assertLandingIgualAoServido(self.tmp / "landing", self.amb)

    def test_tentativas_esgotadas_falham_sem_carga_parcial(self):
        self.amb = AmbienteSimulado("02_variacao", raiz_runs=self.tmp, mudanca=None, limite_rps=0,
                                    falhas={"taxa_500": 1.0}).subir()
        landing = self.tmp / "landing"
        r = executar_ingestao(self.amb.credenciais, self.plano, landing)
        self.assertEqual(r["situacao"], "falhou", r)
        self.assertIn("500", r["saida"]["erro"])
        self.assertEqual([p for p in landing.rglob("*") if p.is_file()], [])

    def test_credenciais_nao_vazam_para_a_landing(self):
        self.amb = AmbienteSimulado("02_variacao", raiz_runs=self.tmp, mudanca=None).subir()
        landing = self.tmp / "landing"
        self.assertEqual(executar_ingestao(self.amb.credenciais, self.plano, landing)["situacao"], "ok")
        segredos = [self.amb.credenciais["erp"]["senha"], self.amb.credenciais["tms"]["token"]]
        for arq in landing.rglob("*"):
            if arq.is_file():
                conteudo = arq.read_bytes()
                for s in segredos:
                    self.assertNotIn(s.encode(), conteudo, arq)


if __name__ == "__main__":
    unittest.main()
