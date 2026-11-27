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
            "rules": {"rateio_cte": {"value": "peso", "status": "confirmada", "evidence_ids": ["privado"],
                                     "confirmed_by": {"name": "DADO-PRIVADO", "role": "financeiro"}}},
            "evidence": [{"id": "privado", "excerpt": "DADO-PRIVADO"}],
            "construction": {"document": "DADO-PRIVADO", "model": "exemplo", "synthetic": True},
            "editable_models": self.modelos,
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
        self.medicao = {"run_id": "run-1", "plan_version": self.plano["plan_version"], "executor": "falso",
                        "synthetic": True, "custo_completo": True, "custo_usd": 0, "custo_centavos": 0,
                        "tentativas": 2, "builds": 3, "correcoes": 1, "por_tentativa": [
                            {"tentativa": 0, "ok": False, "tokens_entrada": 300, "motivo_parada": "DADO-PRIVADO"},
                            {"tentativa": 1, "ok": True, "custo_centavos": 0, "arquivos_escritos": ["DADO-PRIVADO"]}]}
        (self.revisao / "medicao.json").write_text(json.dumps(self.medicao))
        evento = {"run_id": "run-1", "step": "modelos", "type": "test_failed", "attempt": 1,
                  "ts": "2026-11-27T13:00:00+00:00", "message": "DADO-PRIVADO", "dados": {"segredo": "DADO-PRIVADO"}}
        (self.revisao / "eventos.jsonl").write_text("\n".join(json.dumps(obj) for obj in [
            evento, {**evento, "type": "TIPO-DADO-PRIVADO"},
            {**evento, "type": "evaluation_finished", "step": "avaliacao", "attempt": 2}]) + "\n")
        (self.revisao / "credenciais.json").write_text("DADO-PRIVADO")
        self.target = self.projeto.parent / "saida/target"
        self.target.mkdir(parents=True)
        nodes = [f"model.korda_logistica.{m}" for m in MODELOS]
        fontes = ["source.korda_logistica.sinteticas.bronze_" + n for n in
                  ("pedidos", "entregas", "viagens", "veiculos", "documentos")]
        nos = {f"model.korda_logistica.{m}": {"original_file_path": p, "raw_code": (self.projeto / p).read_text(),
                                              "depends_on": {"nodes": [fontes[0]]}}
               for m, p in zip(MODELOS, self.modelos)}
        docs = self.projeto.parent / "saida/docs"
        docs.mkdir()
        tabela = {"columns": {"VALOR": {"name": "valor", "type": "DECIMAL(10,2)", "index": 1,
                                        "comment": "<script>DADO-PRIVADO</script>"}}, "stats": {"observacao": "DADO-PRIVADO"}}
        (docs / "catalog.json").write_text(json.dumps({"nodes": dict.fromkeys(nodes, tabela),
                                                      "sources": dict.fromkeys(fontes, tabela)}))
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
            self.assertIn("projeto/tests/rastreabilidade_cte.sql", pacote.namelist())
            self.assertIn(b"dbt --no-use-colors build", pacote.read("README.md"))
            self.assertEqual(json.loads(pacote.read("execucao.json"))["avaliacao"]["comparados"], self.laudo["comparados"])
            docs = pacote.read("docs/index.html")
            self.assertIn(b'<a href="#bronze_pedidos">bronze_pedidos</a>', docs)
            self.assertIn(b"<td>valor</td><td>DECIMAL(10,2)</td>", docs)
            self.assertNotIn(b"<script", docs)
            decisoes = json.loads(pacote.read("decisoes.json"))
            self.assertEqual(decisoes["construction_sha256"], hashlib.sha256(b"DADO-PRIVADO").hexdigest())
            self.assertEqual(decisoes["regras"]["rateio_cte"], {
                "evidencias": ["/evidence/0"], "papel_confirmador": "financeiro", "valor": "peso", "estado": "confirmada"})
            medicao = json.loads(pacote.read("medicao.json"))
            self.assertEqual((medicao["tentativas"], medicao["correcoes"], medicao["custo_centavos"]), (2, 1, 0))
            self.assertEqual(medicao["por_tentativa"], [
                {"tentativa": 0, "ok": False, "tokens_entrada": 300},
                {"tentativa": 1, "ok": True, "custo_centavos": 0}])
            eventos = [json.loads(linha) for linha in pacote.read("eventos.jsonl").splitlines()]
            self.assertEqual([e["type"] for e in eventos], ["test_failed", "evaluation_finished"])
            self.assertEqual(set(eventos[0]), {"step", "type", "attempt", "ts"})
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

    def test_gasto_desconhecido_e_distinto_de_zero_e_outro_run_nao_empresta_medida(self):
        self.medicao.update(custo_completo=False, custo_usd=0.0, custo_centavos=0)
        self.medicao["por_tentativa"][0]["custo_centavos"] = None
        (self.revisao / "medicao.json").write_text(json.dumps(self.medicao))
        with ZipFile(self.montar()) as pacote:
            medicao = json.loads(pacote.read("medicao.json"))
            self.assertFalse(medicao["custo_completo"])
            self.assertIsNone(medicao["custo_usd"])
            self.assertIsNone(medicao["custo_centavos"])
            self.assertIsNone(medicao["por_tentativa"][0]["custo_centavos"])
            self.assertEqual(medicao["por_tentativa"][1]["custo_centavos"], 0)
        (self.resultados / "pacote.zip").unlink()
        self.medicao["run_id"] = "outro"
        (self.revisao / "medicao.json").write_text(json.dumps(self.medicao))
        with self.assertRaisesRegex(ValueError, "medição não corresponde"):
            self.montar()
        self.assertFalse((self.resultados / "pacote.zip").exists())

    def test_catalogo_nao_pode_injetar_conteudo_ativo_no_documento(self):
        caminho = self.projeto.parent / "saida/docs/catalog.json"
        catalogo = json.loads(caminho.read_text())
        catalogo["nodes"]["model.korda_logistica.ouro_kpis"]["columns"]["VALOR"]["name"] = "<script>"
        caminho.write_text(json.dumps(catalogo))
        with self.assertRaisesRegex(ValueError, "coluna"):
            self.montar()
        self.assertFalse((self.resultados / "pacote.zip").exists())


if __name__ == "__main__":
    unittest.main()
