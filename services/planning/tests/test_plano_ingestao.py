import copy
import hashlib
import json
import subprocess
import sys
import unittest
from pathlib import Path

from jsonschema.exceptions import ValidationError

P2 = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(P2))
from korda_planning import anexar_construcao, gerar_plano, validar_plano

CONTRATOS = P2.parents[1] / "packages/contracts"
CONTEXTO = CONTRATOS / "context/v0.1.0/examples/02_rateio_confirmado.json"
PROPOSTA = CONTRATOS / "ingestion_plan/v0.1.0/examples/01_demo.json"


def digest(objeto):
    canonico = json.dumps(objeto, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonico.encode("utf-8")).hexdigest()


class TestPlanoIngestao(unittest.TestCase):
    def setUp(self):
        self.contexto = json.loads(CONTEXTO.read_text(encoding="utf-8"))
        self.proposta = json.loads(PROPOSTA.read_text(encoding="utf-8"))

    def gerar_n1(self, proposta=None, **kw):
        return gerar_plano(self.contexto, nivel_ingestao="n1",
                           proposta_ingestao=self.proposta if proposta is None else proposta, **kw)

    def test_proposta_completa_vinculada_ao_plano_e_corte(self):
        n0 = gerar_plano(self.contexto)
        self.assertEqual(n0["schema_version"], "0.2.0")
        self.assertEqual(n0["ingestion"], {"level": "n0", "window": {"kind": "full_batch"},
                                          "proposal": None, "proposal_sha256": None})
        completo = self.gerar_n1()
        self.assertEqual(completo["state"], "aguardando_aprovacao")
        self.assertEqual(completo["ingestion"]["proposal"], self.proposta)
        self.assertEqual(completo["ingestion"]["proposal_sha256"], digest(self.proposta))
        self.assertEqual(completo["rules"], n0["rules"])
        por_dia = self.gerar_n1(janela_ingestao={"kind": "simulated_as_of", "as_of": "2026-09-29"})
        self.assertIn("2026-09-29", por_dia["period"])
        self.assertEqual(por_dia["ingestion"]["proposal_sha256"], completo["ingestion"]["proposal_sha256"])
        self.proposta["sources"][0]["frequency"] = "sob_demanda"
        revisado = self.gerar_n1()
        self.assertEqual(completo["ingestion"]["proposal"]["sources"][0]["frequency"], "diaria")
        self.assertNotEqual(completo["ingestion"]["proposal_sha256"], revisado["ingestion"]["proposal_sha256"])
        self.assertEqual(len({p["plan_version"] for p in [n0, completo, por_dia, revisado]}), 4)
        for plano in [n0, completo, por_dia, revisado]:
            validar_plano(plano)

    def test_recusa_nivel_janela_formato_e_datas_invalidas(self):
        opcoes = [
            {"nivel_ingestao": "n2"}, {"nivel_ingestao": "n1"},
            {"nivel_ingestao": "n0", "proposta_ingestao": self.proposta},
            {"janela_ingestao": {"kind": "simulated_as_of", "as_of": "2026-02-28"}},
            {"nivel_ingestao": "n1", "proposta_ingestao": self.proposta,
             "janela_ingestao": {"kind": "simulated_as_of", "as_of": "2026-02-30"}},
            {"nivel_ingestao": "n1", "proposta_ingestao": self.proposta,
             "janela_ingestao": {"kind": "full_batch", "as_of": "2026-02-28"}},
        ]
        for i, kw in enumerate(opcoes):
            with self.subTest(i=i), self.assertRaises((ValueError, ValidationError)):
                gerar_plano(self.contexto, **kw)

    def test_rascunho_e_lacuna_bloqueante_propaga_sem_aprovar_regras(self):
        self.proposta["gaps"][0]["blocking"] = True
        with self.assertRaisesRegex(ValueError, "bloqueante"):
            self.gerar_n1()
        self.proposta["state"] = "rascunho"
        plano = self.gerar_n1()
        self.assertEqual(plano["state"], "rascunho")
        self.assertEqual(plano["rules"], self.contexto["rules"])
        validar_plano(plano)

    def test_recusa_divergencia_de_contexto_ou_evidencia(self):
        for campos in [
            {"project_id": "outro"}, {"company_id": "02_variacao"}, {"context_ref": None},
            {"context_ref": {"context_id": "ctx-demo-01", "revision": 1}},
        ]:
            with self.subTest(campos=campos), self.assertRaises(ValueError):
                self.gerar_n1({**self.proposta, **campos})
        self.proposta["sources"][1]["evidence_ids"] = ["evidencia-inexistente"]
        with self.assertRaisesRegex(ValueError, "evidência"):
            self.gerar_n1()

    def test_recusa_fontes_repetidas_e_ids_de_teste_duplicados(self):
        self.proposta["sources"][0]["system"] = "tms"
        with self.assertRaisesRegex(ValueError, "ERP, TMS e CT-e"):
            self.gerar_n1()
        self.proposta["sources"][0]["system"] = "erp"
        self.proposta["acceptance_tests"].append(copy.deepcopy(self.proposta["acceptance_tests"][0]))
        with self.assertRaisesRegex(ValueError, "IDs"):
            self.gerar_n1()

    def test_recusa_hash_da_secao_e_hash_total_divergentes(self):
        plano = self.gerar_n1()
        plano["ingestion"]["proposal"]["sources"][0]["frequency"] = "sob_demanda"
        # Mesmo recalculando o hash do documento inteiro, o da proposta tem de bater.
        plano["plan_version"] = digest({k: v for k, v in plano.items() if k != "plan_version"})
        with self.assertRaisesRegex(ValueError, "hash da proposta"):
            validar_plano(plano)
        plano["ingestion"]["proposal_sha256"] = digest(plano["ingestion"]["proposal"])
        with self.assertRaisesRegex(ValueError, "revisão canônica"):
            validar_plano(plano)

    def test_legado_preserva_exatamente_hash_e_permissao_anteriores(self):
        # Hash conferido na CLI da versão integrada no PR #21 com o exemplo original.
        esperado = "99ba267a013801900e76c39aa178362c69e90bfaaac9a2e0a39365dc876901e0"
        legado = json.loads((CONTRATOS / "plan/v0.1.0/examples/01_demo.json").read_text(encoding="utf-8"))
        self.assertEqual(legado["plan_version"], esperado)
        self.assertEqual(legado["editable_models"], ["models/prata_ctes.sql"])
        validar_plano(legado)
        legado["editable_models"].append("models/ouro_kpis.sql")
        with self.assertRaisesRegex(ValueError, "revisão canônica"):
            validar_plano(legado)
        legado["plan_version"] = digest({k: v for k, v in legado.items() if k != "plan_version"})
        with self.assertRaisesRegex(ValueError, "revisão canônica"):
            validar_plano(legado)

    def test_glob_v01_preserva_hash_antes_e_depois_de_construir(self):
        legado = json.loads((CONTRATOS / "plan/v0.1.0/examples/01_demo.json").read_text(encoding="utf-8"))
        legado["editable_models"] = ["models/*"]
        with self.assertRaisesRegex(ValueError, "revisão canônica"):
            validar_plano(legado)
        # Versões medidas com o planejador do PR #30 e o mesmo contexto, destino e custo.
        legado["plan_version"] = "e7743944485dd3ecef0f13f9d673ecd4b12c3fe7f85dce549d8bb87eb228205d"
        validar_plano(legado)
        construcao = {"document": "## Modelos\nprata_ctes", "model": "teste/falso", "synthetic": True}
        pronto = anexar_construcao(legado, construcao)
        self.assertEqual(pronto["plan_version"], "fcdf7a5659ac7c2d8bb82f748c17bd5e71896c38d8fb9fa4c6240e89969fd943")
        self.assertEqual(pronto["editable_models"], ["models/*"])
        validar_plano(pronto)
        pronto["editable_models"] = ["models/prata_ctes.sql"]
        with self.assertRaisesRegex(ValueError, "revisão canônica"):
            validar_plano(pronto)

    def test_construcao_considera_ingestao_janela_e_escopo_exato(self):
        doc = {"document": "Plano da demo", "model": "teste/falso", "synthetic": True}
        n0 = anexar_construcao(gerar_plano(self.contexto), doc)
        n1 = anexar_construcao(self.gerar_n1(), doc)
        self.assertNotEqual(n0["plan_version"], n1["plan_version"])
        validar_plano(n1)
        self.assertEqual(len(n1["editable_models"]), 5)
        for campo, valor in [("doc", "mudou"), ("window", {"kind": "simulated_as_of", "as_of": "2026-09-29"}),
                             ("editable_models", ["models/*"])]:
            adulterado = copy.deepcopy(n1)
            if campo == "doc":
                adulterado["construction"]["document"] = valor
            elif campo == "window":
                adulterado["ingestion"]["window"] = valor
            else:
                adulterado[campo] = valor
            with self.subTest(campo=campo), self.assertRaises((ValidationError, ValueError)):
                validar_plano(adulterado)

    def test_cli_escolha_explicita_limite_inclusivo(self):
        r = subprocess.run([sys.executable, "-m", "korda_planning", str(CONTEXTO), "--nivel-ingestao", "n1",
                            "--proposta-ingestao", str(PROPOSTA), "--ate-dia", "2026-09-29"],
                           cwd=P2, text=True, capture_output=True, check=True)
        plano = json.loads(r.stdout)
        validar_plano(plano)
        self.assertEqual(plano["ingestion"]["window"], {"kind": "simulated_as_of", "as_of": "2026-09-29"})
