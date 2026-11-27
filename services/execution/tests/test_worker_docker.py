"""Aceites do worker sobre 01_demo, DuckDB, dbt e o exportador da imagem real."""

import hashlib
import json
import os
import re
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from korda_execution import worker
from korda_execution.aprovacoes import ErroAprovacao, Registro
from korda_execution.artefatos import entregar
from korda_execution.eventos import EmissorEventos
from korda_execution.harness.cliente_chat import ClienteChatFalso, RespostaChat
from korda_execution.sandbox import IMAGEM_PADRAO, LocalDockerSandbox, docker_disponivel, imagem_existe
from services.execution.tests.test_worker import (
    CONTEXTO, DOCUMENTO, FALSO, PROJETO, REPO, ROTEIRIZADO, escrever, modelos_de_referencia, planejar_com_cliente_falso,
)

PRONTO = docker_disponivel() and imagem_existe(IMAGEM_PADRAO)
if not PRONTO and os.environ.get("KORDA_EXIGIR_DOCKER") == "1":
    raise RuntimeError(f"KORDA_EXIGIR_DOCKER=1, mas Docker ou a imagem {IMAGEM_PADRAO} não está disponível")


def _hashes_protegidos():
    pastas = (PROJETO / "tests", PROJETO / "definicoes", PROJETO / "models")
    arquivos = [p for pasta in pastas for p in pasta.rglob("*") if p.is_file() and "__pycache__" not in p.parts]
    return {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in [*arquivos, PROJETO / "exportar.py"]}


def _sem_deduplicacao(sql):
    defeituoso, n = re.subn(r"(?im)^where\s+copia\s*=\s*1\s*;?\s*\Z", "", sql)
    if n != 1:
        raise AssertionError("A fixture precisa acompanhar o filtro de deduplicação de prata_ctes")
    return defeituoso


@unittest.skipUnless(PRONTO, f"Docker ou imagem {IMAGEM_PADRAO} indisponível")
class TestWorkerDocker(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from data.synthetic.generator.generate import generate

        temp = tempfile.TemporaryDirectory(prefix="korda-worker-docker-")
        cls.addClassCleanup(temp.cleanup)
        generate("01_demo", output_root=Path(temp.name))
        cls.fontes = Path(temp.name) / "01_demo"

    def setUp(self):
        from services.planning.korda_planning import gerar_plano

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        self.registro = Registro(self.base / "controle")
        contexto = json.loads(CONTEXTO.read_text(encoding="utf-8"))
        self.plano_base = gerar_plano(contexto, destino="pasta-demo", custo_estimado_centavos=0)
        self.contexto = contexto
        self.run_id = "demo-" + uuid.uuid4().hex
        self.revisao = self.base / "revisao" / self.run_id
        self.hashes = _hashes_protegidos()

    def aprovar(self, plano):
        self.registro.registrar(plano)
        self.registro.decidir_plano(plano["project_id"], plano["plan_version"], "Pessoa fictícia (teste)", True)

    def planejar_e_aprovar(self, plano_base=None):
        plano_base = self.plano_base if plano_base is None else plano_base
        pronto = planejar_com_cliente_falso(plano_base, self.contexto, self.base)
        self.assertEqual(pronto["estado"], "pronto")
        # Usa o plano gravado pelo planejamento, como o operador faz pela CLI.
        plano = json.loads((Path(pronto["pasta"]) / "plano.json").read_text(encoding="utf-8"))
        self.assertNotEqual(plano["plan_version"], plano_base["plan_version"])
        self.assertEqual(plano["construction"]["document"].strip(), DOCUMENTO)
        self.aprovar(plano)
        return plano

    def executar(self, plano, cfg, respostas=()):
        self.cliente = ClienteChatFalso(list(respostas)) if cfg == FALSO else None
        return worker.executar(self.registro, plano, self.run_id, raiz=self.base, fontes=self.fontes,
                               cfg=cfg, cliente_llm=self.cliente)

    def eventos(self):
        return EmissorEventos(self.revisao / "eventos.jsonl", self.run_id).ler()

    def medir(self):
        return json.loads((self.revisao / "medicao.json").read_text(encoding="utf-8"))

    def conferir_documento(self, plano):
        texto = plano["construction"]["document"]
        documento = (self.revisao / "documento_base.md").read_bytes()
        self.assertEqual(documento, texto.encode("utf-8"))
        self.assertIn(texto, self.cliente.pedidos[0][1]["content"])
        medicao = self.medir()
        self.assertEqual(medicao["documento_base"]["origem"], "construction")
        self.assertEqual(medicao["documento_base"]["sha256"], hashlib.sha256(documento).hexdigest())
        self.assertEqual(medicao["plan_version"], plano["plan_version"])
        self.assertTrue(medicao["synthetic"] and medicao["custo_completo"])

    def confere_infra(self, modelos):
        """A infra que o harness construiu sobrevive à sandbox, com hash no manifesto, e vira o pacote de entrega."""
        infra = self.revisao / "infra"
        manifesto = self.registro.consultar(self.run_id)["manifesto"]
        self.assertEqual({c for c in manifesto["infra"] if c.startswith("models/")}, set(modelos))
        for caminho, sql in modelos.items():
            self.assertEqual((infra / caminho).read_text(encoding="utf-8"), sql)
        for caminho, meta in manifesto["infra"].items():
            self.assertEqual(hashlib.sha256((infra / caminho).read_bytes()).hexdigest(), meta["sha256"], caminho)
        dbt = json.loads((infra / "target/manifest.json").read_text(encoding="utf-8"))
        nos = {n["name"] for n in dbt["nodes"].values() if n["resource_type"] == "model"}
        self.assertEqual(nos, {Path(c).stem for c in modelos})
        catalogo = json.loads((infra / "target/catalog.json").read_text(encoding="utf-8"))
        self.assertIn("model.korda_logistica.ouro_kpis", catalogo["nodes"])
        eventos = self.eventos()
        self.assertIn("docs_generated", [e["type"] for e in eventos])
        self.assertEqual(eventos[-1]["type"], "package_built")
        pacote = self.revisao / "entrega"
        entrega = json.loads((pacote / "entrega.json").read_text(encoding="utf-8"))
        kpis = json.loads((self.revisao / "resultados/kpis.json").read_text(encoding="utf-8"))["kpis"]
        self.assertEqual({k["chave"]: k["valor"] for k in entrega["kpis"]}, kpis)
        self.assertTrue(all(k["conta"]["confere"] for k in entrega["kpis"]), entrega["kpis"])
        self.assertEqual({p["tabela"] for p in entrega["prata"]}, {"prata_ctes", "prata_rateios"})
        self.assertEqual({f"models/{p.name}" for p in (pacote / "projeto_dbt/models").iterdir()}, set(modelos))
        # Prata exportada em Parquet, com hash no manifesto e contagem de linhas.
        linhas = json.loads((infra / "prata/linhas.json").read_text(encoding="utf-8"))
        self.assertEqual(set(linhas), {"prata_ctes", "prata_rateios"})
        self.assertTrue(all(n > 0 for n in linhas.values()), linhas)
        for tabela in linhas:
            self.assertEqual((infra / "prata" / f"{tabela}.parquet").read_bytes()[:4], b"PAR1")
            self.assertIn(f"prata/{tabela}.parquet", manifesto["infra"])
        # run_results é o do build (testes com status pass), não o do docs generate.
        build = json.loads((infra / "target/run_results.json").read_text(encoding="utf-8"))
        testes = {r["unique_id"]: r["status"] for r in build["results"] if r["unique_id"].startswith("test.")}
        self.assertTrue(testes)
        self.assertEqual(set(testes.values()), {"pass"})
        # Sem gabarito no fluxo (27/11/2026): a pessoa decide na aprovação 2.
        self.assertFalse((self.revisao / "avaliacao.json").exists())

    def tearDown(self):
        self.assertFalse((self.base / "sandbox" / self.run_id).exists())
        self.assertEqual(_hashes_protegidos(), self.hashes)

    def test_glob_historico_planejado_cria_modelo_novo_em_sandbox_vazia(self):
        base = json.loads((REPO / "packages/contracts/plan/v0.1.0/examples/01_demo.json").read_text(encoding="utf-8"))
        # Versão emitida pelo planejador publicado de Gabriel para o mesmo contexto,
        # destino e custo com o escopo models/*. O validador recalcula este hash.
        base.update(editable_models=["models/*"],
                    plan_version="e7743944485dd3ecef0f13f9d673ecd4b12c3fe7f85dce549d8bb87eb228205d")
        plano = self.planejar_e_aprovar(base)
        self.assertEqual(plano["editable_models"], ["models/*"])
        inicial = []

        class ObservarSandbox(LocalDockerSandbox):
            def criar(self):
                super().criar()
                inicial.append([p.relative_to(self.dir_run).as_posix() for p in
                                (self.dir_run / "projeto/models").rglob("*.sql") if p.stat().st_size > 0])

        modelos = modelos_de_referencia()
        novo = "models/conferencia_pedidos.sql"
        self.assertNotIn(novo, modelos)
        modelos[novo] = "select count(*) as pedidos from {{ ref('ouro_por_pedido') }}"
        respostas = [
            RespostaChat.de_tool_calls([("ler_arquivo", {"caminho": "exportar.py"})]),
            RespostaChat.de_tool_calls([("escrever_modelo", {"caminho": "tests/chave_fiscal_unica.sql",
                                                            "conteudo": "select 1 where false"})]),
            escrever(modelos),
            RespostaChat.texto("Pipeline escrito."),
        ]
        with patch.object(worker, "LocalDockerSandbox", ObservarSandbox):
            estado = self.executar(plano, FALSO, respostas)
        self.assertEqual(estado["state"], "aguardando_aprovacao_entrega", estado)
        self.assertEqual(inicial, [[]])
        self.conferir_documento(plano)
        self.assertEqual(len(self.cliente.pedidos), len(respostas))
        eventos = self.eventos()
        recusa = [e for e in eventos if e["type"] == "tool_refused"]
        self.assertEqual(len(recusa), 1)
        self.assertEqual(recusa[0]["dados"]["origem"], "hook")
        self.assertCountEqual([e["dados"]["caminho"] for e in eventos if e["type"] == "file_written"], modelos)
        sequencia = ["build_started", "agent_finished", "dbt_passed", "test_passed", "package_built"]
        self.assertEqual([e["type"] for e in eventos if e["type"] in sequencia + ["intervention_requested"]], sequencia)
        medicao = self.medir()
        self.assertEqual([f["tentativa"] for f in medicao["por_tentativa"]], [0])
        self.assertEqual(medicao["tokens_entrada"], sum(r.tokens_entrada for r in respostas))
        self.assertEqual(medicao["tokens_saida"], sum(r.tokens_saida for r in respostas))
        self.confere_infra(modelos)

    def test_exportador_recusa_duas_linhas_de_kpi_e_chat_corrige_so_o_agregado(self):
        plano = self.planejar_e_aprovar()
        modelos = modelos_de_referencia()
        nome = "models/ouro_kpis.sql"
        # O contrato de tipos dbt aceita este agregado. A cardinalidade é verificada por exportar.py.
        sql = modelos[nome].strip().removesuffix(";")
        errado = f"with duplicado as (\n{sql}\n) select duplicado.* from duplicado cross join (values (1), (2)) copia(n)"
        respostas = [escrever({**modelos, nome: errado}), RespostaChat.texto("Construído.", tokens=(0, 0)),
                     escrever({nome: modelos[nome]}), RespostaChat.texto("Agregado corrigido.", tokens=(0, 0))]
        estado = self.executar(plano, FALSO, respostas)
        self.assertEqual(estado["state"], "aguardando_aprovacao_entrega")
        self.conferir_documento(plano)
        eventos = self.eventos()
        fases = {"dbt_passed", "dbt_failed", "test_failed", "fix_started", "fix_applied", "test_passed", "package_built"}
        self.assertEqual([e["type"] for e in eventos if e["type"] in fases],
                         ["dbt_passed", "test_failed", "fix_started", "fix_applied", "dbt_passed", "test_passed",
                          "package_built"])
        i = next(i for i, e in enumerate(eventos) if e["type"] == "test_failed")
        self.assertEqual(eventos[i]["dados"]["codigo"], "implementacao")
        self.assertIn("agregado deve produzir exatamente uma linha", eventos[i]["dados"]["erro"])
        self.assertEqual([e["dados"]["caminho"] for e in eventos[i:] if e["type"] == "file_written"], [nome])
        self.assertEqual(self.medir()["correcoes"], 1)
        with self.assertRaises(ErroAprovacao):
            entregar(self.registro, self.base, self.run_id, plano["destination"])
        self.registro.decidir_entrega(self.run_id, "Revisor de entrega fictício", True)
        entrega = entregar(self.registro, self.base, self.run_id, plano["destination"])
        self.assertTrue((entrega / "entrega.json").is_file())
        self.assertEqual(json.loads((entrega / "manifesto.json").read_text())["run_id"], self.run_id)
        self.assertTrue((entrega / "dados/kpis.json").is_file())
        self.assertEqual(self.registro.consultar(self.run_id)["state"], "promovida")

    def test_roteirizado_repara_duplicata_real_no_primeiro_build(self):
        plano = self.plano_base
        self.aprovar(plano)
        nome = "models/prata_ctes.sql"
        ruim = _sem_deduplicacao(modelos_de_referencia()[nome])

        class DuplicataNoPrimeiroBuild(LocalDockerSandbox):
            injetado = False

            def rodar_comando(self, argv, timeout_s=300, stdin=None):
                if argv[0] == "dbt" and "build" in argv and not self.injetado:
                    self.enviar_arquivos({f"/work/projeto/{nome}": ruim.encode("utf-8")})
                    self.injetado = True
                return super().rodar_comando(argv, timeout_s, stdin)

        with patch.object(worker, "LocalDockerSandbox", DuplicataNoPrimeiroBuild):
            estado = self.executar(plano, ROTEIRIZADO)
        self.assertEqual(estado["state"], "aguardando_aprovacao_entrega")
        eventos = self.eventos()
        fases = {"dbt_failed", "test_failed", "fix_started", "fix_applied", "dbt_passed", "test_passed", "package_built"}
        self.assertEqual([e["type"] for e in eventos if e["type"] in fases], [
            "dbt_failed", "test_failed", "fix_started", "fix_applied", "dbt_passed", "test_passed", "package_built",
        ])
        por_tipo = {e["type"]: e.get("dados", {}) for e in eventos}
        self.assertEqual(por_tipo["test_failed"]["codigo"], "implementacao")
        self.assertIn("chave_fiscal_unica", por_tipo["test_failed"]["erro"])
        self.assertEqual(por_tipo["fix_applied"]["correcoes"], 1)
        self.assertEqual(por_tipo["fix_applied"]["custo_centavos"], 0)
        self.assertEqual(self.medir()["executor"], "roteirizado")
        self.confere_infra(modelos_de_referencia())

    def test_falha_persistente_para_no_limite_e_nao_avalia(self):
        plano = self.planejar_e_aprovar()
        modelos = modelos_de_referencia()
        nome = "models/prata_ctes.sql"
        ruim = {nome: _sem_deduplicacao(modelos[nome])}
        cliente = [escrever({**modelos, **ruim}), RespostaChat.texto("Construído.")]
        for _ in range(3):
            cliente.extend([escrever(ruim), RespostaChat.texto("Tentei corrigir.")])
        with self.assertRaisesRegex(worker.FalhaExecucao, "limite_atingido"):
            self.executar(plano, FALSO, cliente)
        self.assertEqual(self.registro.consultar(self.run_id)["state"], "falhou")
        eventos = self.eventos()
        tipos = [e["type"] for e in eventos]
        self.assertEqual(tipos.count("intervention_requested"), 1)
        self.assertEqual(tipos.count("fix_applied"), 3)
        self.assertEqual(tipos.count("test_failed"), 4)
        self.assertNotIn("evaluation_finished", tipos)
        self.assertFalse((self.revisao / "avaliacao.json").exists())
        self.assertEqual(self.medir()["tentativas"], 4)
        # Os SQL escritos ficam para diagnóstico, fora da entrega, e o dbt_failed traz o erro.
        self.assertEqual((self.revisao / "falha" / nome).read_text(), ruim[nome])
        preservados = [e for e in eventos if e["type"] == "models_preserved"]
        self.assertEqual(len(preservados), 1)
        self.assertIn(nome, preservados[0]["dados"]["arquivos"])
        self.assertTrue(all(e["dados"].get("diagnostico") for e in eventos if e["type"] == "dbt_failed"))

    def test_construcao_sem_modelos_escala_sem_build(self):
        plano = self.planejar_e_aprovar()
        with self.assertRaisesRegex(worker.FalhaExecucao, "construcao_falhou"):
            self.executar(plano, FALSO, [RespostaChat.texto("Não consigo construir.")])
        tipos = [e["type"] for e in self.eventos()]
        self.assertEqual(tipos.count("intervention_requested"), 1)
        self.assertFalse({"dbt_failed", "dbt_passed", "evaluation_finished"}.intersection(tipos))

    def test_legado_promove_tres_resultados_com_sua_permissao_original(self):
        plano = json.loads((REPO / "packages/contracts/plan/v0.1.0/examples/01_demo.json").read_text(encoding="utf-8"))
        self.assertEqual(plano["editable_models"], ["models/prata_ctes.sql"])
        self.aprovar(plano)
        with patch.object(worker, "construir_modelos", side_effect=AssertionError("Construção v0.2 fora da autorização")):
            estado = self.executar(plano, ROTEIRIZADO)
        self.assertEqual(estado["state"], "aguardando_aprovacao_entrega")
        self.assertEqual(estado["plan_version"], plano["plan_version"])
        esperados = {"kpis.json", "por_pedido.csv", "por_viagem.csv"}
        self.assertEqual(set(estado["manifesto"]["arquivos"]), esperados)
        self.assertFalse((self.revisao / "avaliacao.json").exists())
        with self.assertRaises(ErroAprovacao):
            entregar(self.registro, self.base, self.run_id, plano["destination"])
        self.registro.decidir_entrega(self.run_id, "Revisor fictício legado", True)
        pasta = entregar(self.registro, self.base, self.run_id, plano["destination"])
        self.assertEqual({p.name for p in (pasta / "dados").iterdir() if p.is_file()}, esperados)
        self.assertTrue((pasta / "entrega.json").is_file())
        self.assertEqual(self.registro.consultar(self.run_id)["state"], "promovida")


if __name__ == "__main__":
    unittest.main()
