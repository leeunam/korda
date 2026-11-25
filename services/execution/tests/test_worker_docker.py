"""Integração do worker com a imagem real e o lote 01_demo do gerador."""

import json
import os
import re
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from korda_execution.eventos import EmissorEventos
from korda_execution.sandbox import IMAGEM_PADRAO, LocalDockerSandbox, docker_disponivel, imagem_existe

REPO = Path(__file__).resolve().parents[3]
_PRONTO = docker_disponivel() and imagem_existe(IMAGEM_PADRAO)
if not _PRONTO and os.environ.get("KORDA_EXIGIR_DOCKER") == "1":
    raise RuntimeError(f"KORDA_EXIGIR_DOCKER=1, mas Docker ou a imagem {IMAGEM_PADRAO} não está disponível")


@unittest.skipUnless(_PRONTO, f"Docker ou imagem {IMAGEM_PADRAO} indisponível")
class TestWorkerDocker(unittest.TestCase):
    def test_01_demo_corrige_a_duplicata_no_dbt_e_aguarda_segunda_aprovacao(self):
        from data.synthetic.generator.generate import generate
        from korda_execution import worker
        from korda_execution.aprovacoes import ErroAprovacao, Registro
        from services.planning.korda_planning import gerar_plano

        modelo = worker.PROJETO / worker.MODELO_CTE
        original = modelo.read_text(encoding="utf-8")
        # Omite a seleção da primeira cópia do documento só no modelo deste run.
        defeituoso, substituicoes = re.subn(r"(?im)^where\s+copia\s*=\s*1\s*;?\s*\Z", "", original)
        self.assertEqual(substituicoes, 1, "A fixture precisa acompanhar o modelo de deduplicação atual")

        class SandboxDaFixture(LocalDockerSandbox):
            def criar(self):
                super().criar()
                self.enviar_arquivos({f"/work/projeto/{worker.MODELO_CTE}": defeituoso.encode("utf-8")})

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            generate("01_demo", output_root=base / "fontes")
            contexto = REPO / "packages/contracts/context/v0.1.0/examples/02_rateio_confirmado.json"
            plano = gerar_plano(json.loads(contexto.read_text(encoding="utf-8")),
                                destino="pasta-demo", custo_estimado_centavos=0)
            registro = Registro(base / "controle")
            registro.registrar(plano)
            registro.decidir_plano(plano["project_id"], plano["plan_version"], "Pessoa fictícia (teste)", True)
            run_id = "e2e-" + uuid.uuid4().hex
            with patch.object(worker, "LocalDockerSandbox", SandboxDaFixture):
                worker.executar(registro, plano, run_id, raiz=base, fontes=base / "fontes/01_demo")
            estado = registro.consultar(run_id)
            self.assertEqual(estado["state"], "aguardando_aprovacao_entrega", estado)
            self.assertEqual(estado["plan_version"], plano["plan_version"])
            with self.assertRaises(ErroAprovacao):
                registro.autorizar_destino(run_id, plano["destination"])
            self.assertFalse((base / "sandbox" / run_id).exists(), "A sandbox temporária deve ser removida")
            self.assertEqual(modelo.read_text(encoding="utf-8"), original)

            eventos = EmissorEventos(base / "revisao" / run_id / "eventos.jsonl", run_id).ler()
            sequencia = {"dbt_failed", "test_failed", "fix_started", "fix_applied", "dbt_passed",
                         "test_passed", "evaluation_finished"}
            self.assertEqual([e["type"] for e in eventos if e["type"] in sequencia], [
                "dbt_failed", "test_failed", "fix_started", "fix_applied",
                "dbt_passed", "test_passed", "evaluation_finished",
            ])
            por_tipo = {e["type"]: e for e in eventos}
            self.assertEqual(por_tipo["test_failed"]["dados"]["codigo"], "implementacao")
            self.assertEqual(por_tipo["dbt_passed"]["attempt"], 2)
            self.assertEqual(por_tipo["fix_applied"]["dados"]["correcoes"], 1)
            self.assertEqual(por_tipo["fix_applied"]["dados"]["custo_centavos"], 0)
            self.assertTrue(por_tipo["evaluation_finished"]["dados"]["aprovado"])
