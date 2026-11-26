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
from korda_planning import gerar_plano

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
