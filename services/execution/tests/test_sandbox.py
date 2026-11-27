"""Integração com Docker: a sandbox recusa de verdade o que a política proíbe.

Precisa da imagem: docker build -t korda-sandbox:dev infra/sandbox
Sem Docker ou sem a imagem, os testes são pulados (e isso aparece no resumo do unittest).
Defina KORDA_EXIGIR_DOCKER=1 para transformar o pulo em falha (usado no CI).
"""

import hashlib
import os
import shutil
import subprocess
import tempfile
import unittest
import uuid
from pathlib import Path

from korda_execution.eventos import EmissorEventos
from korda_execution.ferramentas import FerramentasRestritas
from korda_execution.ingestao import ingerir
from korda_execution.sandbox import (
    IMAGEM_PADRAO,
    ErroSandbox,
    LocalDockerSandbox,
    docker_disponivel,
    imagem_existe,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"
PROJETO = FIXTURES / "projeto_minimo"
FONTES = FIXTURES / "fontes_minimas"

MODELO_CORRETO = """
select distinct chave_cte, cast(valor as double) as valor, status
from {{ source('fixture', 'cte') }}
where status <> 'cancelado'
"""
# Ingênuo: mantém a duplicata de A1 e o cancelado C3.
MODELO_INGENUO = """
select chave_cte, cast(valor as double) as valor, status
from {{ source('fixture', 'cte') }}
"""

_PRONTO = docker_disponivel() and imagem_existe(IMAGEM_PADRAO)
if not _PRONTO and os.environ.get("KORDA_EXIGIR_DOCKER") == "1":
    raise RuntimeError(f"KORDA_EXIGIR_DOCKER=1, mas Docker ou a imagem {IMAGEM_PADRAO} não está disponível")


@unittest.skipUnless(_PRONTO, f"Docker ou imagem {IMAGEM_PADRAO} indisponível")
class TestSandboxLocal(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Uma ingestão para a classe: fontes brutas (com uma _gerador/ falsa) -> landing em Parquet.
        cls.tmp_classe = Path(tempfile.mkdtemp(prefix="korda-test-landing-"))
        brutas = cls.tmp_classe / "brutas"
        shutil.copytree(FONTES, brutas)
        (brutas / "_gerador").mkdir()
        (brutas / "_gerador" / "anomalias_plantadas.csv").write_text("segredo\n")
        cls.landing = cls.tmp_classe / "landing"
        ingerir(brutas, cls.landing)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp_classe, ignore_errors=True)

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="korda-test-"))
        # Landing copiada para o tmp, com outra _gerador/ falsa para testar a ocultação na sandbox.
        self.fontes = self.tmp / "fontes"
        shutil.copytree(self.landing, self.fontes)
        (self.fontes / "_gerador").mkdir()
        (self.fontes / "_gerador" / "anomalias_plantadas.csv").write_text("segredo\n")
        self.run_id = f"teste-{uuid.uuid4().hex[:8]}"
        self.sb = LocalDockerSandbox(self.run_id, PROJETO, self.fontes, raiz_runs=self.tmp / "runs")
        self.sb.criar()
        self.eventos = EmissorEventos(self.tmp / "eventos.jsonl", self.run_id)
        self.ferramentas = FerramentasRestritas(self.sb, self.eventos)

    def tearDown(self):
        self.sb.destruir()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def rodar(self, *argv, timeout_s=20):
        return self.sb.rodar_comando(list(argv), timeout_s=timeout_s)

    # Caminho feliz

    def test_modelo_correto_passa_no_dbt_build(self):
        r = self.ferramentas.escrever_modelo("models/prata/prata_cte.sql", MODELO_CORRETO)
        self.assertTrue(r["ok"], r)
        r = self.ferramentas.rodar_dbt("build")
        self.assertTrue(r["ok"], r["stdout"][-2000:])
        # 1 modelo + 3 testes (unique, not_null, sem_cte_cancelado).
        self.assertIn("PASS=4 WARN=0 ERROR=0", r["stdout"])

        consulta = self.ferramentas.consultar_sql("select chave_cte from prata_cte order by 1")
        self.assertTrue(consulta["ok"], consulta)
        self.assertEqual(consulta["linhas"], [["A1"], ["B2"]])

        tipos = [e["type"] for e in self.eventos.ler()]
        self.assertEqual(tipos, ["file_written", "dbt_passed", "query_finished"])
        for e in self.eventos.ler():
            self.assertEqual(set(e) - {"dados"}, {"run_id", "step", "type", "message", "attempt", "ts"})

    def test_modelo_ingenuo_falha_nos_testes_protegidos(self):
        self.ferramentas.escrever_modelo("models/prata/prata_cte.sql", MODELO_INGENUO)
        r = self.ferramentas.rodar_dbt("build")
        self.assertFalse(r["ok"])
        self.assertIn("unique_prata_cte_chave_cte", r["stdout"])
        self.assertIn("sem_cte_cancelado", r["stdout"])
        self.assertEqual(self.eventos.ler()[-1]["type"], "dbt_failed")

    # Escrita indevida recusada pelo kernel, não só pela política

    def test_escrita_fora_de_models_e_recusada_pelo_sistema_de_arquivos(self):
        alvos = [
            "/work/fontes/cte.parquet",
            "/work/fontes/manifesto.json",
            "/work/fontes/novo.csv",
            "/work/projeto/tests/sem_cte_cancelado.sql",
            "/work/projeto/definicoes/testes.yml",
            "/work/projeto/dbt_project.yml",
            "/work/projeto/profiles.yml",
            "/opt/korda/consulta.py",
            "/novo_arquivo",
        ]
        for alvo in alvos:
            with self.subTest(alvo=alvo):
                r = self.rodar("sh", "-c", 'echo invadido >> "$1"', "sh", alvo)
                self.assertNotEqual(r.codigo, 0)
                self.assertRegex(r.stderr, "Read-only file system|Permission denied")
        self.assertEqual((FONTES / "cte.csv").read_text().count("invadido"), 0)
        self.assertEqual((self.fontes / "cte.parquet").read_bytes(), (self.landing / "cte.parquet").read_bytes())

    def test_enviar_arquivos_recusa_area_somente_leitura(self):
        with self.assertRaises(ErroSandbox):
            self.sb.enviar_arquivos({"/work/projeto/tests/novo.sql": b"select 1"})

    def test_symlink_em_models_nao_permite_escrever_nos_testes(self):
        r = self.rodar("ln", "-s", "/work/projeto/tests/sem_cte_cancelado.sql", "/work/projeto/models/atalho.sql")
        self.assertTrue(r.ok, r.stderr)
        r = self.ferramentas.escrever_modelo("models/atalho.sql", "select 1")
        self.assertFalse(r["ok"])
        original = (PROJETO / "tests" / "sem_cte_cancelado.sql").read_text()
        copia = (self.sb.dir_run / "projeto" / "tests" / "sem_cte_cancelado.sql").read_text()
        self.assertEqual(copia, original)

    def test_politica_recusa_antes_de_chegar_na_sandbox(self):
        r = self.ferramentas.escrever_modelo("tests/sem_cte_cancelado.sql", "select 1")
        self.assertFalse(r["ok"])
        self.assertEqual(self.eventos.ler()[-1]["type"], "tool_refused")
        r = self.ferramentas.rodar_dbt("deps")
        self.assertFalse(r["ok"])

    def test_consulta_nao_escreve_nem_le_arquivos(self):
        self.ferramentas.escrever_modelo("models/prata/prata_cte.sql", MODELO_CORRETO)
        self.assertTrue(self.ferramentas.rodar_dbt("run")["ok"])
        perigosas = [
            "copy (select 1) to '/work/projeto/models/x.sql'",
            "copy (select 1) to '/work/saida/x.csv'",
            "select * from read_parquet('/work/fontes/cte.parquet')",
            "create table t as select 1",
            "set enable_external_access = true",
            "attach '/work/saida/outro.duckdb'",
        ]
        for sql in perigosas:
            with self.subTest(sql=sql):
                self.assertFalse(self.ferramentas.consultar_sql(sql)["ok"])
        self.assertFalse((self.sb.dir_run / "projeto" / "models" / "x.sql").exists())
        self.assertFalse((self.sb.dir_run / "saida" / "x.csv").exists())

    # Isolamento do ambiente

    def test_sem_rede(self):
        r = self.rodar(
            "python", "-c",
            "import socket; socket.create_connection(('1.1.1.1', 443), timeout=3)",
        )
        self.assertNotEqual(r.codigo, 0)

    def test_sem_root_e_sem_gabarito_ou_registro_de_anomalias(self):
        self.assertNotEqual(self.rodar("id", "-u").stdout.strip(), "0")
        r = self.rodar("find", "/work", "/opt", "-maxdepth", "4")
        self.assertTrue(r.ok, r.stderr)
        self.assertNotIn("evaluation", r.stdout)
        self.assertNotIn("golden", r.stdout)
        self.assertNotIn("anomalias_plantadas", r.stdout)
        self.assertNotIn("ingestao_n1", r.stdout)  # a ingestão de referência não fica ao alcance do agente
        self.assertEqual(self.rodar("ls", "-A", "/work/fontes/_gerador").stdout.strip(), "")
        # A ingestão também não viu _gerador/: nenhuma tabela nem arquivo do manifesto vem de lá.
        self.assertFalse(any("_gerador" in p.as_posix() for p in self.landing.rglob("*")))
        manifesto = (self.landing / "manifesto.json").read_text(encoding="utf-8")
        self.assertNotIn("_gerador", manifesto)

    def test_tempo_limite_mata_o_processo(self):
        r = self.rodar("sleep", "30", timeout_s=2)
        self.assertTrue(r.estourou_tempo)
        self.assertLess(r.duracao_s, 15)

    def test_destruir_remove_contenedor_e_diretorio(self):
        nome = self.sb.nome_container
        self.sb.destruir()
        r = subprocess.run(["docker", "inspect", nome], capture_output=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse(self.sb.dir_run.exists())
        with self.assertRaises(ErroSandbox):
            self.rodar("true")


@unittest.skipUnless(_PRONTO, f"Docker ou imagem {IMAGEM_PADRAO} indisponível")
class TestCriacao(unittest.TestCase):
    def test_run_id_invalido(self):
        for run_id in ("../x", "A", "", "a" * 65, "a b"):
            with self.subTest(run_id=run_id), self.assertRaises(ErroSandbox):
                LocalDockerSandbox(run_id, PROJETO, FONTES)

    def test_imagem_inexistente(self):
        with tempfile.TemporaryDirectory() as t:
            sb = LocalDockerSandbox("teste-img", PROJETO, FONTES, imagem="korda-nao-existe:0", raiz_runs=Path(t),
                                    exigir_manifesto=False)
            with self.assertRaises(ErroSandbox):
                sb.criar()
            self.assertFalse(sb.dir_run.exists())

    def test_fontes_brutas_sem_manifesto_sao_recusadas(self):
        with tempfile.TemporaryDirectory() as t:
            sb = LocalDockerSandbox("teste-bruto", PROJETO, FONTES, raiz_runs=Path(t))
            with self.assertRaisesRegex(ErroSandbox, "landing"):
                sb.criar()
            self.assertFalse(sb.dir_run.exists())


if __name__ == "__main__":
    unittest.main()


PROJETO_DEMO = Path(__file__).resolve().parents[1] / "pipeline/projeto"


@unittest.skipUnless(_PRONTO, f"Docker ou imagem {IMAGEM_PADRAO} indisponível")
class TestSandboxDeConstrucao(unittest.TestCase):
    """Sandbox do worker: o harness constrói em models/ vazio; testes e configuração são do kernel."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="korda-test-construcao-"))
        (self.tmp / "fontes").mkdir()
        self.sb = LocalDockerSandbox(f"construcao-{uuid.uuid4().hex[:8]}", PROJETO_DEMO, self.tmp / "fontes",
                                     raiz_runs=self.tmp / "runs", modelos_permitidos=("models/*",),
                                     exigir_manifesto=False)
        self.sb.criar()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.addCleanup(self.sb.destruir)

    def test_models_comeca_vazio_e_o_pipeline_a_mao_nao_e_montado(self):
        r = self.sb.rodar_comando(["ls", "-A", "/work/projeto/models"], timeout_s=20)
        self.assertTrue(r.ok, r.stderr)
        self.assertEqual(r.stdout.strip(), "")
        self.sb.enviar_arquivos({"/work/projeto/models/ouro_kpis.sql": b"select 1"})
        self.assertEqual((self.sb.dir_run / "projeto/models/ouro_kpis.sql").read_text(), "select 1")

    def test_escrita_direta_em_tests_e_recusada_pelo_kernel(self):
        alvo = PROJETO_DEMO / "tests/chave_fiscal_unica.sql"
        copia = self.sb.dir_run / "projeto/tests/chave_fiscal_unica.sql"
        antes = {c: hashlib.sha256(c.read_bytes()).hexdigest() for c in (alvo, copia)}
        for destino in ("/work/projeto/tests/chave_fiscal_unica.sql", "/work/projeto/definicoes/fontes.yml",
                        "/work/projeto/dbt_project.yml", "/work/projeto/profiles.yml", "/work/projeto/ingerir.py"):
            with self.subTest(destino=destino):
                r = self.sb.rodar_comando(["sh", "-c", 'echo invadido >> "$1"', "sh", destino], timeout_s=20)
                self.assertNotEqual(r.codigo, 0)
                self.assertIn("Read-only file system", r.stderr)
        self.assertEqual({c: hashlib.sha256(c.read_bytes()).hexdigest() for c in (alvo, copia)}, antes)

    def test_ferramentas_recusam_teste_e_fonte_e_o_kernel_tambem(self):
        (self.tmp / "fontes" / "cte.csv").write_text("original\n")
        eventos = EmissorEventos(self.tmp / "eventos.jsonl", self.sb.run_id)
        ferramentas = FerramentasRestritas(self.sb, eventos, plano_aprovado={"plan_version": "x"},
                                           modelos_permitidos=frozenset(["models/*"]))
        for caminho in ("tests/chave_fiscal_unica.sql", "../fontes/cte.csv", "definicoes/fontes.yml"):
            with self.subTest(caminho=caminho):
                self.assertFalse(ferramentas.escrever_modelo(caminho, "select 1")["ok"])
        self.assertEqual({e["type"] for e in eventos.ler()}, {"tool_refused"})
        r = self.sb.rodar_comando(["sh", "-c", 'echo invadido >> "$1"', "sh", "/work/fontes/cte.csv"], timeout_s=20)
        self.assertIn("Read-only file system", r.stderr)
        self.assertEqual((self.tmp / "fontes" / "cte.csv").read_text(), "original\n")

    def test_sem_rede(self):
        r = self.sb.rodar_comando(["python", "-c", "import socket; socket.create_connection(('1.1.1.1', 53), 3)"],
                                  timeout_s=20)
        self.assertNotEqual(r.codigo, 0)
