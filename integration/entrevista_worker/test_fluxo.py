"""Verifica as duas revisões do produtor e sua passagem pelo registro de aprovações."""

import os
import tempfile
import unittest
from pathlib import Path

from integration.entrevista_worker.roteiro import RESPOSTAS, ler, revisoes_em_memoria
from integration.entrevista_worker.seed import exportar
from korda_execution.aprovacoes import ErroAprovacao, Registro
from services.planning.korda_planning import ContextoPendente, gerar_plano, preparar_contexto, validar_plano


def revisar(documento):
    return gerar_plano(documento, dataset="01_demo", destino="pasta-demo", custo_estimado_centavos=0)


class TestEntrevistaPlanejamento(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        manifest = os.environ.get("KORDA_ENTREVISTA_MANIFEST")
        if manifest:
            sessao = ler(Path(manifest))
            token = os.environ["CONTEXT_PROJECT_TOKEN"]
            cls.pendente, cls.pronta = (
                exportar(sessao["url"], sessao["project_id"], sessao[k], token)
                for k in ("pending_revision", "ready_revision")
            )
        elif os.environ.get("KORDA_EXIGIR_DOCKER") == "1":
            raise RuntimeError("a integração CI exige revisões persistidas e exportadas pela API real")
        else:
            cls.pendente, cls.pronta = revisoes_em_memoria()

    def test_revisao_sem_financeiro_expoe_lacuna_e_impede_o_plano(self):
        self.assertEqual(self.pendente["state"], "rascunho")
        abertas = {g["topic"] for g in self.pendente["gaps"] if g["blocking"] and g["state"] != "respondida"}
        self.assertEqual(abertas, {"frete_rateio"})
        with self.assertRaises(ContextoPendente) as bloqueio:
            revisar(self.pendente)
        self.assertIn("rateio_cte", [p["campo"] for p in bloqueio.exception.diagnostico["pendencias"]])
        self.assertIsNone(bloqueio.exception.diagnostico["contexto_planejamento"])
        self.assertIsNone(bloqueio.exception.diagnostico["regras"]["rateio_cte"]["value"])

    def test_plano_preserva_a_evidencia_de_cada_resposta_e_confirmacao(self):
        pronta = self.pronta
        self.assertEqual((pronta["state"], pronta["schema_version"]), ("pronto", "0.2.0"))
        self.assertLess(self.pendente["revision"], pronta["revision"])
        self.assertEqual(pronta["processed_input_ids"][:len(self.pendente["processed_input_ids"])],
                         self.pendente["processed_input_ids"])
        plano = revisar(pronta)
        validar_plano(plano)
        self.assertEqual((plano["project_id"], plano["context_revision"], plano["state"]),
                         (pronta["project_id"], pronta["revision"], "aguardando_aprovacao"))
        evidencias = {e["id"]: e for e in pronta["evidence"]}
        projetadas = {e["id"]: e for e in plano["evidence"]}
        claims = {c["key"]: c for c in pronta["claims"]}
        self.assertEqual(set(claims), set(RESPOSTAS))
        self.assertEqual(preparar_contexto(pronta)["pendencias"], [])
        for chave, claim in claims.items():
            with self.subTest(chave=chave):
                assinatura = claim["confirmation"]
                papel = pronta["required_topics"][claim["topic"]]
                confirmacao = evidencias[assinatura["evidence_id"]]
                self.assertEqual(assinatura["role"], papel)
                self.assertEqual(confirmacao["participant_id"], assinatura["participant_id"])
                self.assertEqual(confirmacao["quote"], "Confirmo")
                origens = [evidencias[e] for e in claim["evidence_ids"] if e != confirmacao["id"]]
                self.assertTrue(any(e["quote"] == RESPOSTAS[chave][2] and e["source_id"] != confirmacao["source_id"]
                                    and e["participant_role"] == papel for e in origens))
                for ev in claim["evidence_ids"]:
                    self.assertEqual(projetadas[ev]["excerpt"], evidencias[ev]["quote"])
                if claim["kind"] == "rule":
                    regra = plano["rules"][chave]
                    self.assertEqual(regra["confirmed_by"]["role"], papel)
                    self.assertEqual(set(regra["evidence_ids"]), set(claim["evidence_ids"]))
                    self.assertEqual(regra["value"], claim["value"])
                else:
                    self.assertEqual(plano["source_profile"][chave], claim["value"])

    def test_versao_confirmada_ainda_exige_decisao_do_operador(self):
        plano = revisar(self.pronta)
        with tempfile.TemporaryDirectory() as tmp:
            registro = Registro(Path(tmp) / "controle")
            inscrito = registro.registrar(plano)
            self.assertEqual(inscrito["state"], "aguardando_aprovacao")
            with self.assertRaises(ErroAprovacao):
                registro.iniciar(plano["project_id"], plano["plan_version"], "ensaio-sem-aprovacao")
            aprovado = registro.decidir_plano(plano["project_id"], plano["plan_version"], "Operadora do ensaio", True)
            self.assertEqual(aprovado["state"], "plano_aprovado")
            iniciado = registro.iniciar(plano["project_id"], plano["plan_version"], "ensaio-aprovado")
            self.assertEqual(iniciado["state"], "executando")
            with self.assertRaises(ErroAprovacao):
                registro.autorizar_destino("ensaio-aprovado", plano["destination"])
