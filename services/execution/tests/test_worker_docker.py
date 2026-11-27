"""Integração do worker com a imagem real e o lote 01_demo do gerador."""

import hashlib
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
    @classmethod
    def setUpClass(cls):
        from data.synthetic.generator.generate import generate

        temp = tempfile.TemporaryDirectory(prefix="korda-worker-docker-")
        cls.addClassCleanup(temp.cleanup)
        fontes = Path(temp.name)
        generate("01_demo", output_root=fontes)
        cls.fontes = fontes / "01_demo"

    def test_01_demo_corrige_a_duplicata_no_dbt_e_aguarda_segunda_aprovacao(self):
        from korda_execution import worker
        from korda_execution.aprovacoes import ErroAprovacao, Registro
        from korda_execution.harness.cliente_chat import ClienteChatFalso, RespostaChat
        from services.planning.korda_planning import gerar_plano

        nome_modelo = "models/prata_ctes.sql"
        modelo = REPO / "services/execution/pipeline/projeto" / nome_modelo
        original = modelo.read_text(encoding="utf-8")
        # Omite a seleção da primeira cópia do documento só no modelo deste run.
        defeituoso, substituicoes = re.subn(r"(?im)^where\s+copia\s*=\s*1\s*;?\s*\Z", "", original)
        self.assertEqual(substituicoes, 1, "A fixture precisa acompanhar o modelo de deduplicação atual")
        modelos_iniciais = {}

        class SandboxDaFixture(LocalDockerSandbox):
            defeito_injetado = False

            def criar(self):
                super().criar()
                projeto = self.dir_run / "projeto"
                modelos_iniciais.update({p.relative_to(projeto).as_posix(): p.stat().st_size
                                         for p in (projeto / "models").rglob("*.sql")})

            def rodar_comando(self, argv, timeout_s=300, stdin=None):
                if argv[0] == "dbt" and "build" in argv and not self.defeito_injetado:
                    self.defeito_injetado = True
                    self.enviar_arquivos({f"/work/projeto/{nome_modelo}": defeituoso.encode("utf-8")})
                return super().rodar_comando(argv, timeout_s, stdin)

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            contexto = REPO / "packages/contracts/context/v0.1.0/examples/02_rateio_confirmado.json"
            plano = gerar_plano(json.loads(contexto.read_text(encoding="utf-8")),
                                destino="pasta-demo", custo_estimado_centavos=0)
            registro = Registro(base / "controle")
            registro.registrar(plano)
            registro.decidir_plano(plano["project_id"], plano["plan_version"], "Pessoa fictícia (teste)", True)
            run_id = "e2e-" + uuid.uuid4().hex

            def cliente_com_correcao(construcao):
                ajuste = [("escrever_modelo", {"caminho": nome_modelo, "conteudo": original})]
                return ClienteChatFalso([*construcao, RespostaChat.de_tool_calls(ajuste, tokens=(0, 0)),
                                         RespostaChat.texto("Modelo corrigido", tokens=(0, 0))])

            with (patch.dict(os.environ, {"KORDA_EXECUTOR": "falso", "KORDA_PERMITIR_LLM_REAL": "0"}),
                  patch("korda_execution.construcao.ClienteChatFalso", side_effect=cliente_com_correcao),
                  patch.object(worker, "LocalDockerSandbox", SandboxDaFixture)):
                worker.executar(registro, plano, run_id, raiz=base, fontes=self.fontes)
            estado = registro.consultar(run_id)
            self.assertEqual(estado["state"], "aguardando_aprovacao_entrega", estado)
            self.assertEqual(estado["plan_version"], plano["plan_version"])
            with self.assertRaises(ErroAprovacao):
                registro.autorizar_destino(run_id, plano["destination"])
            self.assertFalse((base / "sandbox" / run_id).exists(), "A sandbox temporária deve ser removida")
            self.assertEqual(modelo.read_text(encoding="utf-8"), original)
            self.assertEqual(modelos_iniciais, {p: 0 for p in plano["editable_models"]})

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

            revisao = base / "revisao" / run_id
            medicao = json.loads((revisao / "medicao.json").read_text(encoding="utf-8"))
            self.assertEqual(medicao["executor"], "falso")
            self.assertTrue(medicao["synthetic"])
            self.assertEqual(medicao["correcoes"], 1)
            self.assertEqual([fase["tentativa"] for fase in medicao["por_tentativa"]], [0, 1])
            self.assertEqual(medicao["tokens_entrada"] + medicao["tokens_saida"], 0)
            self.assertTrue(medicao["custo_completo"])
            self.assertEqual(medicao["custo_centavos"], 0)
            documento = (revisao / "documento_base.md").read_bytes()
            self.assertEqual(hashlib.sha256(documento).hexdigest(), medicao["documento_base"]["sha256"])
            self.assertEqual(medicao["plan_version"], estado["plan_version"])
            primeira_falha = next(i for i, e in enumerate(eventos) if e["type"] == "dbt_failed")
            construcao = [e["dados"]["caminho"] for e in eventos[:primeira_falha] if e["type"] == "file_written"]
            correcao = [e["dados"]["caminho"] for e in eventos[primeira_falha:] if e["type"] == "file_written"]
            self.assertCountEqual(construcao, plano["editable_models"])
            self.assertEqual(correcao, [nome_modelo])

    def test_plano_legado_mantem_versao_permissao_e_promocao_dos_tres_resultados(self):
        from korda_execution import worker
        from korda_execution.aprovacoes import ErroAprovacao, Registro
        from korda_execution.artefatos import entregar

        caminho = REPO / "packages/contracts/plan/v0.1.0/examples/01_demo.json"
        plano = json.loads(caminho.read_text(encoding="utf-8"))
        self.assertEqual(plano["editable_models"], ["models/prata_ctes.sql"])
        self.assertEqual(plano["schema_version"], "0.1.0")
        run = "legado-" + uuid.uuid4().hex
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            registro = Registro(base / "controle")
            registro.registrar(plano)
            registro.decidir_plano(plano["project_id"], plano["plan_version"], "Revisor fictício legado", True)
            with (patch.dict(os.environ, {"KORDA_EXECUTOR": "roteirizado", "KORDA_PERMITIR_LLM_REAL": "0"}),
                  patch.object(worker, "construir_modelos", side_effect=AssertionError("Construção não autorizada pela v0.1"))):
                estado = worker.executar(registro, plano, run, raiz=base, fontes=self.fontes)
            self.assertEqual(estado["state"], "aguardando_aprovacao_entrega")
            self.assertEqual(estado["plan_version"], plano["plan_version"])
            esperados = {"kpis.json", "por_pedido.csv", "por_viagem.csv"}
            self.assertEqual(set(estado["manifesto"]["arquivos"]), esperados)
            laudo = json.loads((base / "revisao" / run / "avaliacao.json").read_text(encoding="utf-8"))
            self.assertTrue(laudo["aprovado"], laudo)
            with self.assertRaises(ErroAprovacao):
                entregar(registro, base, run, plano["destination"])
            registro.decidir_entrega(run, "Revisor fictício legado", True)
            pasta = entregar(registro, base, run, plano["destination"])
            self.assertEqual({p.name for p in pasta.iterdir()}, esperados)
            self.assertEqual(registro.consultar(run)["state"], "promovida")
