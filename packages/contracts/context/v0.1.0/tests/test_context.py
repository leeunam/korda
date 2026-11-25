"""Exemplos da passagem P1/P2 e estados que não podem avançar ao planejamento."""

import json
import sys
import unittest
from pathlib import Path

from jsonschema import ValidationError

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
from validate import validate_context  # noqa: E402


def example(name="01_rateio_pendente.json"):
    return json.loads((HERE / "examples" / name).read_text(encoding="utf-8"))


class ContextContractTest(unittest.TestCase):
    def test_duas_rodadas_preservam_a_lacuna_ate_o_financeiro_confirmar(self):
        first, final = example(), example("02_rateio_confirmado.json")
        validate_context(first)
        validate_context(final)
        self.assertEqual(first["rules"]["rateio_cte"]["value"], None)
        self.assertEqual(first["state"], "rascunho")
        self.assertEqual(final["rules"]["rateio_cte"]["value"], "peso")
        self.assertEqual(final["gaps"][0]["state"], "respondida")
        self.assertEqual(final["context_id"], first["context_id"])
        self.assertGreater(final["revision"], first["revision"])
        self.assertEqual(final["evidence"][:len(first["evidence"])], first["evidence"])

    def test_lacuna_bloqueante_impede_contexto_pronto(self):
        context = example()
        context["state"] = "pronto_para_planejamento"
        with self.assertRaises(ValueError):
            validate_context(context)

    def test_nao_pode_apagar_ou_fechar_lacuna_sem_confirmacao(self):
        for action in ("apagar", "fechar"):
            with self.subTest(action=action):
                context = example()
                if action == "apagar":
                    context["gaps"] = []
                else:
                    context["gaps"][0]["state"] = "respondida"
                with self.assertRaises(ValueError):
                    validate_context(context)

    def test_rejeita_evidencia_inexistente(self):
        context = example()
        context["rules"]["rateio_cte"]["evidence_ids"] = ["inexistente"]
        with self.assertRaisesRegex(ValueError, "evidência desconhecida"):
            validate_context(context)

    def test_rejeita_ids_repetidos(self):
        context = example()
        context["evidence"].append(context["evidence"][0].copy())
        with self.assertRaisesRegex(ValueError, "IDs repetidos"):
            validate_context(context)

    def test_lacuna_bloqueia_os_indicadores_da_regra(self):
        for key, metrics in (("rateio_cte", ["otif_pct"]),
                             ("excluir_tipos_viagem", ["custo_frete_por_entrega"])):
            with self.subTest(key=key):
                context = example("02_rateio_confirmado.json")
                context["gaps"][0].update(rule_key=key, affected_metrics=metrics)
                with self.assertRaisesRegex(ValueError, "indicadores da lacuna"):
                    validate_context(context)

    def test_pratica_setorial_nao_confirma_regra_da_empresa(self):
        context = example("02_rateio_confirmado.json")
        context["sources"][2].update(kind="pesquisa", origin="descoberta", scope="setor")
        context["rules"]["rateio_cte"]["evidence_ids"] = ["ev-financeiro"]
        context["last_processed_turn_id"] = "turno-1"
        with self.assertRaisesRegex(ValueError, "referência setorial"):
            validate_context(context)

    def test_confirmacao_exige_autor_e_criterio_valido(self):
        for key, value in (("confirmed_by", None), ("value", "ocupacao")):
            with self.subTest(key=key):
                context = example("02_rateio_confirmado.json")
                context["rules"]["rateio_cte"][key] = value
                with self.assertRaises(ValidationError):
                    validate_context(context)


if __name__ == "__main__":
    unittest.main()
