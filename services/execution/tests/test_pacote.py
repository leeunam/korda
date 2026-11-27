import hashlib
import json
import shutil
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from zipfile import ZipFile

from korda_execution.artefatos import entregar, manifesto_revisao
from korda_execution.pacote import MODELOS, REPO, TESTES, montar_pacote
from tests.test_artefatos import RegistroTeste


class TestPacote(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.raiz = Path(tmp.name)
        self.revisao = self.raiz / "revisao/run-1"
        self.resultados = self.revisao / "resultados"
        self.resultados.mkdir(parents=True)
        self.dados = {"kpis.json": b'{"kpis":{}}', "por_viagem.csv": b"viagem\n2\n", "por_pedido.csv": b"pedido\n1\n"}
        for nome, dados in self.dados.items():
            (self.resultados / nome).write_bytes(dados)
        self.projeto = self.raiz / "run/projeto"
        shutil.copytree(REPO / "services/execution/pipeline/projeto", self.projeto)
        self.modelo = self.projeto / "models/prata_ctes.sql"
        self.modelo.write_text("-- alterado pelo executor antes da construção\n" + self.modelo.read_text())
        self.modelos = [f"models/{m}.sql" for m in MODELOS]
        self.plano = {
            "schema_version": "0.2.0", "plan_version": "b" * 64, "dataset": "01_demo",
            "project_id": "demo-01", "destination": "demo", "context_revision": 2,
            "rules": {"rateio_cte": {"value": "peso"}}, "editable_models": self.modelos,
            "ingestion": {"level": "n1", "window": {"kind": "full_batch"}, "proposal_sha256": "d" * 64,
                          "proposal": {"observacoes": "DADO-PRIVADO"}},
        }
        self.laudo = {"aprovado": True, "classe": "ok", "empresa": "01_demo", "divergencias": 0, "nivel": 1,
                      "fontes_conferidas": True, "regras_conferidas": True, "landing_conferida": True,
                      "linhagem_conferida": True,
                      "comparados": {"kpis": 3, "por_pedido.csv": 1, "por_viagem.csv": 1},
                      "exemplos": [{"esperado": "DADO-PRIVADO"}]}
        (self.revisao / "avaliacao.json").write_text(json.dumps(self.laudo))
        (self.revisao / "ingestao.json").write_text(json.dumps({"landing_manifest_sha256": "e" * 64}))
        (self.revisao / "credenciais.json").write_text("DADO-PRIVADO")
        self.target = self.projeto.parent / "saida/target"
        self.target.mkdir(parents=True)
        nos = {f"model.korda_logistica.{m}": {"original_file_path": p, "raw_code": (self.projeto / p).read_text()}
               for m, p in zip(MODELOS, self.modelos)}
        metadata = {"invocation_id": "run-teste", "dbt_version": "1.11.16"}
        (self.target / "manifest.json").write_text(json.dumps({"nodes": nos, "metadata": metadata}))
        resultados = [{"unique_id": n, "status": "success", "message": "DADO-PRIVADO"} for n in nos]
        resultados += [{"unique_id": f"test.korda_logistica.{t}", "status": "pass"} for t in TESTES]
        (self.target / "run_results.json").write_text(json.dumps({"results": resultados, "metadata": metadata}))

    def montar(self):
        return montar_pacote(self.projeto, self.resultados, self.revisao, self.plano)

    def test_pacote_contem_sql_testado_resultados_validacao_e_reproducao(self):
        (self.projeto / "models/modelo_nao_aprovado.sql").write_text("DADO-PRIVADO")
        with ThreadPoolExecutor(max_workers=2) as pool:
            primeira_captura, caminho = pool.map(lambda _: self.montar(), range(2))
        self.assertEqual(primeira_captura, caminho)
        primeira = caminho.read_bytes()
        self.assertEqual(self.montar().read_bytes(), primeira)
        with ZipFile(caminho) as pacote:
            self.assertIsNone(pacote.testzip())
            self.assertEqual(pacote.read("projeto/models/prata_ctes.sql"), self.modelo.read_bytes())
            self.assertIn("referencia/ingestao_n1/fontes.py", pacote.namelist())
            self.assertIn("projeto/tests/conservacao.sql", pacote.namelist())
            self.assertIn(b"dbt --no-use-colors build", pacote.read("README.md"))
            self.assertEqual(json.loads(pacote.read("execucao.json"))["avaliacao"]["comparados"], self.laudo["comparados"])
            for nome, dados in self.dados.items():
                self.assertEqual(pacote.read("resultados/" + nome), dados)
                self.assertIn(hashlib.sha256(dados).hexdigest().encode(), pacote.read("resultados.sha256"))
            for nome in pacote.namelist():
                self.assertNotIn(b"DADO-PRIVADO", pacote.read(nome), nome)
        self.plano["ingestion"].update(level="n0", proposal_sha256=None)
        (self.revisao / "avaliacao.json").write_text(json.dumps({**self.laudo, "nivel": 0}))
        caminho.unlink()
        with ZipFile(self.montar()) as pacote:
            self.assertFalse(any(nome.startswith("referencia/") for nome in pacote.namelist()))

    def test_promocao_exige_aprovacao_e_integridade_tambem_para_o_zip(self):
        pacote = self.montar()
        manifesto = manifesto_revisao(self.resultados)
        self.assertEqual(set(manifesto["arquivos"]), {*self.dados, "pacote.zip"})
        registro = RegistroTeste(manifesto)
        registro.autorizado = False
        with self.assertRaises(ValueError):
            entregar(registro, self.raiz, "run-1", "demo")
        registro.autorizado = True
        dados = pacote.read_bytes()
        pacote.write_bytes(dados + b"alterado")
        with self.assertRaisesRegex(ValueError, "integridade"):
            entregar(registro, self.raiz, "run-1", "demo")
        self.assertFalse((self.raiz / "entregas/demo/run-1").exists())
        pacote.write_bytes(dados)
        publicada = entregar(registro, self.raiz, "run-1", "demo")
        self.assertEqual((publicada / "pacote.zip").read_bytes(), dados)

    def test_recusa_modelo_parcial_ou_modificado_apos_build(self):
        self.modelo.write_text("SELECT 1")
        with self.assertRaisesRegex(ValueError, "SQL capturado"):
            self.montar()
        self.plano["editable_models"].pop()
        with self.assertRaisesRegex(ValueError, "modelos aprovados"):
            self.montar()
        self.assertEqual({p.name for p in self.resultados.iterdir()}, set(self.dados))

    def test_sem_laudo_ou_teste_dbt_aprovado_nao_sela_pacote(self):
        (self.revisao / "avaliacao.json").write_text(json.dumps({**self.laudo, "aprovado": False}))
        with self.assertRaisesRegex(ValueError, "laudo"):
            self.montar()
        arquivo = self.target / "run_results.json"
        dbt = json.loads(arquivo.read_text())
        dbt["results"][-1]["status"] = "fail"
        arquivo.write_text(json.dumps(dbt))
        with self.assertRaisesRegex(ValueError, "dbt"):
            self.montar()
        self.assertFalse((self.resultados / "pacote.zip").exists())

    def test_captura_recusa_arquivo_indireto_ou_excessivo_sem_zip_parcial(self):
        self.modelo.unlink()
        self.modelo.symlink_to(self.revisao / "credenciais.json")
        with self.assertRaises(OSError):
            self.montar()
        self.modelo.unlink()
        self.modelo.write_bytes(b"x" * (256 * 1024 + 1))
        with self.assertRaisesRegex(ValueError, "limite"):
            self.montar()
        self.assertEqual({p.name for p in self.resultados.iterdir()}, set(self.dados))

    def test_credencial_em_sql_mesmo_testado_bloqueia_entrega(self):
        modelo = "-- api_key = 'valor-ficticio-para-teste'\n" + self.modelo.read_text()
        self.modelo.write_text(modelo)
        arquivo = self.target / "manifest.json"
        meta = json.loads(arquivo.read_text())
        meta["nodes"]["model.korda_logistica.prata_ctes"]["raw_code"] = modelo
        arquivo.write_text(json.dumps(meta))
        with self.assertRaisesRegex(ValueError, "credencial identificada") as erro:
            self.montar()
        self.assertNotIn("valor-ficticio-para-teste", str(erro.exception))
        self.assertFalse((self.resultados / "pacote.zip").exists())


if __name__ == "__main__":
    unittest.main()
