import copy
import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from jsonschema.exceptions import ValidationError

P2 = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(P2))
from korda_planning import anexar_construcao, gerar_plano, validar_plano
from korda_planning.plano import VALIDADOR

EXEMPLOS = P2.parents[1] / "packages/contracts/context/v0.1.0/examples"


def exemplo(arquivo):
    return json.loads((EXEMPLOS / arquivo).read_text(encoding="utf-8"))


class TestPlano(unittest.TestCase):
    def setUp(self):
        self.pendente = exemplo("01_rateio_pendente.json")
        self.confirmado = exemplo("02_rateio_confirmado.json")

    def test_rateio_pendente_bloqueia_apenas_custo_no_rascunho(self):
        plano = gerar_plano(self.pendente)
        self.assertEqual(plano["state"], "rascunho")
        self.assertEqual(plano["metrics"]["custo_frete_por_entrega"]["blocking_gaps"], ["gap-rateio"])
        self.assertEqual(plano["metrics"]["custo_frete_por_entrega"]["state"], "bloqueada")
        self.assertIsNone(plano["rules"]["rateio_cte"]["value"])
        self.assertEqual(plano["metrics"]["otif_pct"]["blocking_gaps"], [])
        self.assertEqual(plano["metrics"]["ocupacao_pct"]["state"], "planejada")
        self.assertIsNone(plano["cost_estimate_brl_cents"])
        self.assertIsNone(plano["destination"])
        validar_plano(plano)

    def test_confirmacao_preserva_origem_unidades_e_controle_humano(self):
        plano = gerar_plano(self.confirmado, destino="painel-demo", custo_estimado_centavos=125)
        self.assertEqual(plano["state"], "aguardando_aprovacao")
        self.assertEqual(plano["rules"]["rateio_cte"]["confirmed_by"]["role"], "financeiro")
        metricas = plano["metrics"]
        self.assertIn("rateio_cte", metricas["custo_frete_por_entrega"]["rule_keys"])
        self.assertIn("cte/cte_evento.parquet", metricas["custo_frete_por_entrega"]["input_files"])
        self.assertEqual(set(metricas["otif_pct"]["rule_keys"]),
                         {"no_prazo", "completo", "sem_data_realizada", "prazo_conta_sabado", "excluir_tipos_viagem"})
        self.assertEqual(metricas["ocupacao_pct"]["rule_keys"], ["ocupacao_unidade"])
        self.assertIn("tms/tms_veiculos.parquet", metricas["ocupacao_pct"]["input_files"])
        validar_plano(plano)
        feitos = set()
        for tarefa in plano["tasks"]:
            self.assertTrue(set(tarefa["depends_on"]) <= feitos)
            self.assertTrue(tarefa["output"] and tarefa["verify"])
            feitos.add(tarefa["id"])

    def test_conflito_e_versoes_desconhecidas(self):
        self.pendente["rules"]["rateio_cte"]["status"] = "em_conflito"
        self.pendente["gaps"][0]["state"] = "em_conflito"
        self.assertEqual(gerar_plano(self.pendente)["metrics"]["custo_frete_por_entrega"]["state"], "bloqueada")
        self.pendente["state"] = "pronto_para_planejamento"
        with self.assertRaisesRegex(ValueError, "rascunho"):
            gerar_plano(self.pendente)
        self.confirmado["schema_version"] = "99"
        with self.assertRaises(ValidationError):
            gerar_plano(self.confirmado)

    def test_versao_deterministica_inclui_regras_destino_e_estimativa(self):
        antes = gerar_plano(self.confirmado)
        self.assertEqual(antes, gerar_plano(json.loads(json.dumps(self.confirmado, sort_keys=True))))
        mudancas = [gerar_plano(self.confirmado, destino="outro"), gerar_plano(self.confirmado, custo_estimado_centavos=0)]
        self.confirmado["rules"]["rateio_cte"]["value"] = "valor"
        mudancas.append(gerar_plano(self.confirmado))
        self.assertEqual(antes["rules"]["rateio_cte"]["value"], "peso")
        versoes = {p["plan_version"] for p in [antes, *mudancas]}
        self.assertEqual(len(versoes), 4)
        for campo, novo in [("state", "aprovado"), ("plan_version", "a" * 64), ("destination", "outro")]:
            alterado = copy.deepcopy(antes)
            alterado[campo] = novo
            with self.subTest(campo=campo), self.assertRaises((ValueError, ValidationError)):
                validar_plano(alterado)
        self.assertEqual(antes["state"], "aguardando_aprovacao")

    def test_recusa_origem_desconhecida_e_estimativa_invalida(self):
        with self.assertRaises(ValidationError):
            gerar_plano(self.confirmado, custo_estimado_centavos=-1)
        with self.assertRaises(ValidationError):
            gerar_plano(self.confirmado, destino="../relatorios")
        with self.assertRaises(ValidationError):
            gerar_plano(self.confirmado, destino="demo\n")
        self.confirmado["rules"]["ocupacao_unidade"]["evidence_ids"] = ["sem-evidencia"]
        with self.assertRaisesRegex(ValueError, "evidência desconhecida"):
            gerar_plano(self.confirmado)

    def test_dataset_vinculado_sem_inferir_empresa_desconhecida(self):
        plano = gerar_plano(self.confirmado)
        self.assertEqual(plano["dataset"], "01_demo")
        self.assertEqual(set(plano["editable_models"]), {
            "models/prata_ctes.sql", "models/prata_rateios.sql", "models/ouro_por_pedido.sql",
            "models/ouro_por_viagem.sql", "models/ouro_kpis.sql",
        })
        self.confirmado["project_id"] = "outro"
        pendente = gerar_plano(self.confirmado)
        self.assertIsNone(pendente["dataset"])
        self.assertEqual(pendente["editable_models"], [])
        variante = gerar_plano(self.confirmado, dataset="02_variacao")
        self.assertNotEqual(variante["plan_version"], pendente["plan_version"])
        validar_plano(variante)

    def test_schema_v01_aceita_caminho_ou_padrao_somente_em_models(self):
        arquivo = P2.parents[1] / "packages/contracts/plan/v0.1.0/examples/01_demo.json"
        plano = json.loads(arquivo.read_text(encoding="utf-8"))
        validar_plano(plano)
        for valor in (["models/prata_ctes.sql"], ["models/*"], ["models/prata/*.sql"]):
            with self.subTest(valor=valor):
                VALIDADOR.validate({**plano, "editable_models": valor})
        for valor in (["tests/*"], ["*"], ["models/**"], ["models/../tests/x.sql"], ["models/x.yml"], ["models/"]):
            with self.subTest(valor=valor), self.assertRaises(ValidationError):
                VALIDADOR.validate({**plano, "editable_models": valor})

    def test_construcao_entra_no_hash_da_aprovacao(self):
        base = gerar_plano(self.confirmado, destino="demo", custo_estimado_centavos=0)
        construcao = {"document": "## Modelos\nprata_ctes", "model": "teste/falso", "synthetic": True}
        plano = anexar_construcao(base, construcao)
        self.assertNotIn("construction", base)
        self.assertEqual(plano["construction"], construcao)
        self.assertNotEqual(plano["plan_version"], base["plan_version"])
        validar_plano(plano)
        validar_plano(base)
        adulterado = copy.deepcopy(plano)
        adulterado["construction"]["document"] += "\nregra nova"
        with self.assertRaisesRegex(ValueError, "divergentes"):
            validar_plano(adulterado)
        with self.assertRaisesRegex(ValueError, "já tem"):
            anexar_construcao(plano, construcao)
        with self.assertRaises(ValidationError):
            anexar_construcao(base, {"document": "", "model": "m", "synthetic": True})
        with self.assertRaises(ValidationError):
            anexar_construcao(base, {**construcao, "extra": 1})

    def test_cli_exercita_geracao_e_validacao(self):
        cmd = [sys.executable, "-m", "korda_planning"]
        resultado = subprocess.run(cmd + [str(EXEMPLOS / "02_rateio_confirmado.json"), "--destino", "demo"],
                                   cwd=P2, capture_output=True, text=True, check=True)
        with TemporaryDirectory() as tmp:
            arquivo = Path(tmp) / "plano.json"
            arquivo.write_text(resultado.stdout, encoding="utf-8")
            checagem = subprocess.run(cmd + ["--validar", str(arquivo)], cwd=P2, capture_output=True, text=True)
            self.assertEqual(checagem.returncode, 0, checagem.stderr)
            self.assertIn(json.loads(resultado.stdout)["plan_version"], checagem.stdout)
            arquivo.write_text("{}", encoding="utf-8")
            invalido = subprocess.run(cmd + ["--validar", str(arquivo)], cwd=P2, capture_output=True, text=True)
            self.assertNotEqual(invalido.returncode, 0)
