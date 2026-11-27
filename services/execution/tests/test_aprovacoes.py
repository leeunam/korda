import json
import sys
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier, Event

P3 = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(P3))
from korda_execution.aprovacoes import ErroAprovacao, Registro
from korda_planning import anexar_construcao, gerar_plano

EXEMPLOS = P3.parents[1] / "packages/contracts/context/v0.1.0/examples"


class TestAprovacoes(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.raiz = Path(tmp.name)
        self.reg = Registro(self.raiz)
        self.contexto = json.loads((EXEMPLOS / "02_rateio_confirmado.json").read_text(encoding="utf-8"))
        self.plano = gerar_plano(self.contexto, destino="artefato-demo", custo_estimado_centavos=0)
        self.identidade = (self.plano["project_id"], self.plano["plan_version"])
        self.reg.registrar(self.plano)
        self.manifesto = {"arquivo.csv": "sha256-de-teste"}

    def aprovar_plano(self):
        self.reg.decidir_plano(*self.identidade, "Pessoa revisora A", True)

    def preparar_resultado(self):
        self.aprovar_plano()
        self.reg.iniciar(*self.identidade, "run-um")
        self.reg.finalizar("run-um", aprovado=True, manifesto=self.manifesto)

    def test_duas_decisoes_reabertura_e_promocao(self):
        with self.assertRaises(ErroAprovacao):
            self.reg.iniciar(*self.identidade, "run-um")
        self.preparar_resultado()
        instancia = Registro(self.raiz)
        with self.assertRaises(ErroAprovacao):
            instancia.autorizar_destino("run-um", "artefato-demo")
        instancia.decidir_entrega("run-um", "Pessoa revisora B", True)
        with self.assertRaises(ErroAprovacao):
            instancia.autorizar_destino("run-um", "outro-destino")
        self.assertEqual(instancia.autorizar_destino("run-um", "artefato-demo"), self.manifesto)
        with self.assertRaisesRegex(OSError, "disco"):
            with instancia.promover("run-um", "artefato-demo"):
                raise OSError("disco")
        self.assertEqual(instancia.consultar("run-um")["state"], "entrega_autorizada")
        with instancia.promover("run-um", "artefato-demo") as manifesto:
            self.assertEqual(manifesto, self.manifesto)
        resultado = self.reg.consultar("run-um")
        self.assertEqual(resultado["state"], "promovida")
        pessoas = [ev["actor"] for ev in resultado["history"] if ev["actor"]]
        self.assertEqual(pessoas, ["Pessoa revisora A", "Pessoa revisora B"])
        self.assertTrue(all(ev["ts"].endswith("+00:00") for ev in resultado["history"]))
        with self.assertRaises(ErroAprovacao), instancia.promover("run-um", "artefato-demo"):
            self.fail("promoção repetida")

    def test_aprovacao_vincula_nivel_janela_e_proposta_de_ingestao(self):
        caminho = P3.parents[1] / "packages/contracts/ingestion_plan/v0.1.0/examples/01_demo.json"
        proposta = json.loads(caminho.read_text(encoding="utf-8"))
        self.aprovar_plano()
        janela = {"kind": "simulated_as_of", "as_of": "2026-09-29"}
        opcoes = dict(nivel_ingestao="n1", proposta_ingestao=proposta,
                      destino="artefato-demo", custo_estimado_centavos=0)
        identidade = self.identidade
        for i in range(3):
            if i == 1:
                opcoes["janela_ingestao"] = janela
            if i == 2:
                proposta["sources"][0]["frequency"] = "sob_demanda"
            novo = gerar_plano(self.contexto, **opcoes)
            self.reg.registrar(novo)
            with self.assertRaises(ErroAprovacao):
                self.reg.iniciar(*identidade, "versao-anterior")
            identidade = (novo["project_id"], novo["plan_version"])
            with self.assertRaises(ErroAprovacao):
                self.reg.iniciar(*identidade, "sem-nova-aprovacao")
            self.reg.decidir_plano(*identidade, "Pessoa revisora", True)
        self.reg.iniciar(*identidade, "corte-aprovado")
        proposta["state"] = "rascunho"
        pendente = gerar_plano(self.contexto, **opcoes)
        self.reg.registrar(pendente)
        with self.assertRaisesRegex(ErroAprovacao, "rascunho"):
            self.reg.decidir_plano(pendente["project_id"], pendente["plan_version"], "Pessoa revisora", True)
        self.assertEqual(self.reg.consultar("corte-aprovado")["state"], "invalidada")

    def test_troca_de_escopo_legado_e_documento_exige_aprovacao_da_versao(self):
        path = P3.parents[1] / "packages/contracts/plan/v0.1.0/examples/01_demo.json"
        exato = json.loads(path.read_text(encoding="utf-8"))
        self.reg.registrar(exato)
        self.reg.decidir_plano(exato["project_id"], exato["plan_version"], "Revisor do teste", True)
        self.reg.iniciar(exato["project_id"], exato["plan_version"], "cte-legado")

        amplo = {**exato, "editable_models": ["models/*"]}
        with self.assertRaises(ValueError):
            self.reg.registrar(amplo)
        self.assertEqual(self.reg.consultar("cte-legado")["state"], "executando")
        # Hash emitido pela edição do PR #30 para este contexto, destino e custo.
        amplo["plan_version"] = "e7743944485dd3ecef0f13f9d673ecd4b12c3fe7f85dce549d8bb87eb228205d"
        self.reg.registrar(amplo)
        self.assertEqual(self.reg.consultar("cte-legado")["state"], "invalidada")
        with self.assertRaises(ErroAprovacao):
            self.reg.iniciar(amplo["project_id"], amplo["plan_version"], "sem-autorizacao-ampla")
        self.reg.decidir_plano(amplo["project_id"], amplo["plan_version"], "Revisor do teste", True)
        novo = anexar_construcao(amplo, {"document": "Planejamento", "model": "falso", "synthetic": True})
        self.reg.registrar(novo)
        with self.assertRaises(ErroAprovacao):
            self.reg.iniciar(novo["project_id"], novo["plan_version"], "sem-autorizacao-documento")
        self.reg.decidir_plano(novo["project_id"], novo["plan_version"], "Revisor do teste", True)
        self.assertEqual(self.reg.iniciar(novo["project_id"], novo["plan_version"], "com-documento")["state"],
                         "executando")

    def test_alternancia_de_versao_exige_nova_aprovacao_ainda_com_mesmo_hash(self):
        self.preparar_resultado()
        self.reg.decidir_entrega("run-um", "B", True)
        outro = gerar_plano(self.contexto, destino="destino-b", custo_estimado_centavos=0)
        self.reg.registrar(outro)
        self.reg.registrar(self.plano)
        self.assertEqual(self.reg.consultar("run-um")["state"], "invalidada")
        with self.assertRaises(ErroAprovacao):
            self.reg.iniciar(*self.identidade, "run-dois")
        with self.assertRaises(ErroAprovacao):
            self.reg.autorizar_destino("run-um", "artefato-demo")
        self.aprovar_plano()
        self.reg.iniciar(*self.identidade, "run-dois")
        self.reg.registrar(self.plano)
        self.assertEqual(self.reg.consultar("run-dois")["state"], "executando")
        self.reg.decidir_plano(*self.identidade, "A", False)
        with self.assertRaises(ErroAprovacao):
            self.reg.finalizar("run-dois", aprovado=True, manifesto=self.manifesto)

    def test_rascunho_revisao_atrasada_falha_e_pendencias(self):
        antigo = json.loads((EXEMPLOS / "01_rateio_pendente.json").read_text(encoding="utf-8"))
        with self.assertRaisesRegex(ErroAprovacao, "revisão"):
            self.reg.registrar(gerar_plano(antigo))
        antigo["project_id"] = "isolado"
        rascunho = gerar_plano(antigo)
        self.reg.registrar(rascunho)
        with self.assertRaisesRegex(ErroAprovacao, "rascunho"):
            self.reg.decidir_plano("isolado", rascunho["plan_version"], "A", True)
        self.aprovar_plano()
        self.reg.iniciar(*self.identidade, "falha")
        resultado = self.reg.finalizar("falha", aprovado=False)
        self.assertEqual(resultado["state"], "falhou")
        with self.assertRaises(ErroAprovacao):
            self.reg.decidir_entrega("falha", "A", True)
        incompleto = gerar_plano(self.contexto, destino="artefato-demo")
        self.reg.registrar(incompleto)
        self.reg.decidir_plano(self.identidade[0], incompleto["plan_version"], "A", True)
        with self.assertRaisesRegex(ErroAprovacao, "estimativa"):
            self.reg.iniciar(self.identidade[0], incompleto["plan_version"], "sem-custo")

    def test_recusa_rejeicao_sem_pessoa_e_manifesto_inconsistente(self):
        with self.assertRaises(ErroAprovacao):
            self.reg.decidir_plano(*self.identidade, "  ", True)
        self.aprovar_plano()
        self.reg.iniciar(*self.identidade, "run-um")
        with self.assertRaises(ErroAprovacao):
            self.reg.finalizar("run-um", aprovado=True)
        self.assertEqual(self.reg.consultar("run-um")["state"], "executando")
        self.reg.finalizar("run-um", aprovado=True, manifesto=self.manifesto)
        self.reg.decidir_entrega("run-um", "A", True)
        self.reg.decidir_entrega("run-um", "A", False)
        with self.assertRaises(ErroAprovacao):
            self.reg.autorizar_destino("run-um", "artefato-demo")

    def test_reserva_concorrente_e_revogacao_durante_promocao(self):
        self.aprovar_plano()
        barreira = Barrier(2)

        def reservar():
            barreira.wait(timeout=5)
            try:
                self.reg.iniciar(*self.identidade, "run-um")
            except ErroAprovacao:
                return False
            return True

        with ThreadPoolExecutor(max_workers=2) as pool:
            futuros = [pool.submit(reservar) for _ in range(2)]
            self.assertEqual(sorted(f.result(timeout=5) for f in futuros), [False, True])
            self.reg.finalizar("run-um", aprovado=True, manifesto=self.manifesto)
            self.reg.decidir_entrega("run-um", "B", True)
            iniciou = Event()

            def revogar():
                iniciou.set()
                return self.reg.decidir_entrega("run-um", "B", False)

            with self.reg.promover("run-um", "artefato-demo"):
                futuro = pool.submit(revogar)
                self.assertTrue(iniciou.wait(timeout=5))
            with self.assertRaises(ErroAprovacao):
                futuro.result(timeout=5)
        self.assertEqual(self.reg.consultar("run-um")["state"], "promovida")
