"""Pacote de entrega (K13), sem Docker: uma revisão montada à mão com dados sintéticos mínimos.

Os números do fixture são o exemplo de 4 linhas proposto para a K02 (não é regra aprovada):
A1 = R$ 300 rateado por peso entre P1 (100 kg) e P2 (200 kg), B2 = R$ 200 para P3 e P4 sem
CT-e válido. Custo = 500 / 3 entregas elegíveis.
"""

import csv
import hashlib
import io
import json
import re
import tempfile
import unittest
from pathlib import Path

from korda_execution.aprovacoes import Registro
from korda_execution.artefatos import capturar, capturar_infra
from korda_execution.entrega import REGRAS_DOMINIO, empacotar, montar_dossie
from korda_execution.sandbox import RAIZ_REPO
from korda_execution.worker import PROJETO

CONTEXTO = RAIZ_REPO / "packages/contracts/context/v0.1.0/examples/02_rateio_confirmado.json"
PEDIDO = ("pedido_id", "viagem_id", "tipo_viagem", "elegivel_custo", "custo_frete_rateado", "ctes",
          "data_prevista", "data_realizada", "elegivel_otif", "no_prazo", "completo", "otif",
          "entrega_id", "arquivo_pedido", "linha_pedido", "arquivo_entrega", "linha_entrega",
          "chave_nfe", "qt_itens", "qt_entregue", "peso_decimos_kg", "linhagem_cte")
VIAGEM = ("viagem_id", "veiculo_id", "tipo_viagem", "n_entregas", "n_entregas_elegiveis_custo",
          "carga", "capacidade", "unidade", "ocupacao", "acima_capacidade", "custo_frete_total", "custo_por_entrega",
          "arquivo_viagem", "linha_viagem", "arquivo_veiculo", "linha_veiculo")
INJECAO = "<script>alert('x')</script>"


def _linhagem(*partes):
    return json.dumps([{"chave_cte": c, "arquivo": f"cte/{c}.xml", "sha256": hashlib.sha256(c.encode()).hexdigest(),
                        "frete_centavos": f, "parcela_centavos": p} for c, f, p in partes], separators=(",", ":"))


PEDIDOS = [
    ("P1", "V1", "DIST", 1, 100.0, "A1", "2026-09-01", "2026-09-01", 1, 1, 1, 1, "E1",
     "erp/erp_pedidos.csv", 2, "tms/tms_entregas.csv", 2, "N1", 5, 5, 1000, _linhagem(("A1", 30000, 10000))),
    ("P2", "V1", "DIST", 1, 200.0, "A1", "2026-09-01", "2026-09-01", 1, 1, 1, 1, "E2",
     "erp/erp_pedidos.csv", 3, "tms/tms_entregas.csv", 3, "N2", 5, 5, 2000, _linhagem(("A1", 30000, 20000))),
    ("P3", "V2", "DIST", 1, 200.0, "B2", "2026-09-01", "2026-09-03", 1, 0, 1, 0, "E3",
     "erp/erp_pedidos.csv", 4, "tms/tms_entregas.csv", 4, "N3", 5, 5, 500, _linhagem(("B2", 20000, 20000))),
    ("P4", "V2", "DIST", 0, 0.0, "", "2026-09-01", "", 1, 0, 0, 0, "E4",
     "erp/erp_pedidos.csv", 5, "tms/tms_entregas.csv", 5, "N4", 5, 3, 800, "[]"),
]
VIAGENS = [
    ("V1", "C1", "DIST", 2, 2, 300.0, 1000, "kg", 30.0, 0, 300.0, 150.0, "tms/tms_viagens.csv", 2,
     "tms/tms_veiculos.csv", 2),
    ("V2", "C2", "DIST", 2, 1, 130.0, 1000, "kg", 13.0, 0, 200.0, 200.0, "tms/tms_viagens.csv", 3,
     "tms/tms_veiculos.csv", 3),
]
KPIS = {"custo_frete_por_entrega": 166.6667, "otif_pct": 50.0, "ocupacao_pct": 21.5}


def _csv(campos, linhas):
    saida = io.StringIO()
    escritor = csv.writer(saida, lineterminator="\n")
    escritor.writerow(campos)
    escritor.writerows(linhas)
    return saida.getvalue()


def _manifest_dbt(modelos):
    """Manifest mínimo no formato do dbt: depends_on liga fontes, modelos e testes."""
    fontes = ("bronze_documentos", "bronze_pedidos", "bronze_entregas", "bronze_viagens", "bronze_veiculos")
    dependencias = {
        "prata_ctes": ["source.korda_logistica.sinteticas.bronze_documentos"],
        "prata_rateios": ["source.korda_logistica.sinteticas.bronze_pedidos", "model.korda_logistica.prata_ctes"],
        "ouro_por_pedido": ["source.korda_logistica.sinteticas.bronze_entregas",
                            "model.korda_logistica.prata_rateios"],
        "ouro_por_viagem": ["source.korda_logistica.sinteticas.bronze_viagens",
                            "model.korda_logistica.ouro_por_pedido"],
        "ouro_kpis": ["model.korda_logistica.ouro_por_pedido", "model.korda_logistica.ouro_por_viagem"],
    }
    nos = {}
    for caminho, sql in modelos.items():
        nome = Path(caminho).stem
        nos[f"model.korda_logistica.{nome}"] = {
            "name": nome, "resource_type": "model", "original_file_path": caminho, "raw_code": sql,
            "depends_on": {"nodes": dependencias.get(nome, [])}}
    for teste in sorted((PROJETO / "tests").glob("*.sql")):
        nos[f"test.korda_logistica.{teste.stem}"] = {
            "name": teste.stem, "resource_type": "test", "original_file_path": f"tests/{teste.name}",
            "raw_code": teste.read_text(encoding="utf-8"),
            "depends_on": {"nodes": ["model.korda_logistica.prata_ctes"]}}
    return {"nodes": nos, "sources": {f"source.korda_logistica.sinteticas.{f}": {
        "name": f, "resource_type": "source", "depends_on": {"nodes": []}} for f in fontes}}


class TestEntrega(unittest.TestCase):
    def setUp(self):
        from services.planning.korda_planning import gerar_plano

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.raiz = Path(tmp.name) / "runs"
        self.run_id = "run-entrega"
        self.plano = gerar_plano(json.loads(CONTEXTO.read_text(encoding="utf-8")), destino="pasta-demo",
                                 custo_estimado_centavos=0)
        self.registro = Registro(self.raiz / "controle")
        self.registro.registrar(self.plano)
        self.registro.decidir_plano(self.plano["project_id"], self.plano["plan_version"], "Pessoa fictícia", True)
        self.registro.iniciar(self.plano["project_id"], self.plano["plan_version"], self.run_id)
        self.revisao = self.raiz / "revisao" / self.run_id
        self.sandbox = Path(tmp.name) / "sandbox"
        self.modelos = {f"models/{a.name}": a.read_text(encoding="utf-8")
                        for a in sorted((PROJETO / "models").glob("*.sql"))}
        # Conteúdo hostil vindo da sandbox: o pacote deve exibi-lo como texto.
        self.modelos["models/prata_ctes.sql"] = f"-- {INJECAO}\n" + self.modelos["models/prata_ctes.sql"]
        self.eventos = [
            {"run_id": self.run_id, "step": "plano", "type": "run_started", "message": "Iniciada", "attempt": 1,
             "ts": "2026-11-27T10:00:00.000+00:00", "dados": {"executor": "falso"}},
            {"run_id": self.run_id, "step": "construcao", "type": "tool_refused",
             "message": f"escrita fora de models/ {INJECAO}", "attempt": 1,
             "ts": "2026-11-27T10:00:05.000+00:00",
             "dados": {"origem": "hook", "caminho": "tests/chave_fiscal_unica.sql"}},
            {"run_id": self.run_id, "step": "construcao", "type": "file_written", "message": "models/prata_ctes.sql",
             "attempt": 1, "ts": "2026-11-27T10:00:09.000+00:00", "dados": {"caminho": "models/prata_ctes.sql"}},
            {"run_id": self.run_id, "step": "construcao", "type": "dbt_failed", "message": "build", "attempt": 1,
             "ts": "2026-11-27T10:00:20.000+00:00", "dados": {"codigo": 1}},
            {"run_id": self.run_id, "step": "modelos", "type": "fix_applied", "message": "corrigido", "attempt": 2,
             "ts": "2026-11-27T10:00:40.000+00:00", "dados": {"custo_centavos": 12}},
            {"run_id": self.run_id, "step": "construcao", "type": "dbt_passed", "message": "build", "attempt": 2,
             "ts": "2026-11-27T10:01:10.000+00:00", "dados": {"codigo": 0}},
            {"run_id": self.run_id, "step": "avaliacao", "type": "evaluation_finished", "message": "ok",
             "attempt": 1, "ts": "2026-11-27T10:01:30.000+00:00", "dados": {"aprovado": True, "divergencias": 0}},
        ]
        self._preparar()

    def _preparar(self, *, catalog=True, avaliacao=True, kpis=KPIS):
        resultados = self.sandbox / "saida" / "resultados"
        models = self.sandbox / "projeto" / "models"
        target = self.sandbox / "saida" / "target"
        for pasta in (resultados, models, target):
            pasta.mkdir(parents=True, exist_ok=True)
        (resultados / "kpis.json").write_text(json.dumps({"kpis": kpis}) + "\n", encoding="utf-8")
        (resultados / "por_pedido.csv").write_text(_csv(PEDIDO, PEDIDOS), encoding="utf-8")
        (resultados / "por_viagem.csv").write_text(_csv(VIAGEM, VIAGENS), encoding="utf-8")
        for caminho, sql in self.modelos.items():
            (models / Path(caminho).name).write_text(sql, encoding="utf-8")
        (target / "manifest.json").write_text(json.dumps(_manifest_dbt(self.modelos)), encoding="utf-8")
        (target / "run_results.json").write_text(json.dumps({"results": [
            {"unique_id": "test.korda_logistica.chave_fiscal_unica", "status": "pass", "execution_time": 0.1}]}),
            encoding="utf-8")
        if catalog:
            (target / "catalog.json").write_text(json.dumps({"nodes": {"model.korda_logistica.ouro_kpis": {
                "columns": {"custo_frete_por_entrega": {"type": "DOUBLE", "index": 1, "name": "custo_frete_por_entrega"}}
            }}, "sources": {}}), encoding="utf-8")
        self.revisao.mkdir(parents=True, exist_ok=True)
        manifesto = capturar(resultados, self.revisao / "resultados")
        manifesto["infra"] = capturar_infra(models, target, self.revisao / "infra")
        (self.revisao / "eventos.jsonl").write_text(
            "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in self.eventos), encoding="utf-8")
        (self.revisao / "medicao.json").write_text(json.dumps({
            "executor": "falso", "synthetic": True, "tentativas": 2, "custo_usd": 0.02, "custo_centavos": 12,
            "tokens_entrada": 1000, "tokens_saida": 200, "duracao_s": 70.0}), encoding="utf-8")
        if avaliacao:
            (self.revisao / "avaliacao.json").write_text(json.dumps({
                "aprovado": True, "classe": "ok", "empresa": "01_demo", "divergencias": 0,
                "comparados": {"kpis": 3, "por_pedido.csv": 4, "por_viagem.csv": 2}, "exemplos": []}),
                encoding="utf-8")
        self.registro.finalizar(self.run_id, aprovado=True, manifesto=manifesto)

    def _pacote(self):
        return empacotar(self.registro, self.raiz, self.run_id)

    def _textos(self, pacote):
        return {p: p.read_text(encoding="utf-8") for p in pacote.rglob("*") if p.is_file()}

    def test_estrutura_e_manifesto_do_pacote_conferem(self):
        pacote = self._pacote()
        self.assertEqual(pacote, self.revisao / "entrega")
        manifesto = json.loads((pacote / "manifesto.json").read_text(encoding="utf-8"))
        arquivos = {str(p.relative_to(pacote)) for p in pacote.rglob("*") if p.is_file()} - {"manifesto.json"}
        self.assertEqual(set(manifesto["arquivos"]), arquivos)
        for caminho, meta in manifesto["arquivos"].items():
            self.assertEqual(hashlib.sha256((pacote / caminho).read_bytes()).hexdigest(), meta["sha256"], caminho)
        self.assertEqual(manifesto["aprovado"], self.registro.consultar(self.run_id)["manifesto"])
        for esperado in ("index.html", "decisoes.md", "execucao.md", "dados/kpis.json", "dados/por_pedido.csv",
                         "dados/por_viagem.csv", "projeto_dbt/dbt_project.yml", "projeto_dbt/profiles.yml",
                         "projeto_dbt/regras.json", "projeto_dbt/README.md", "projeto_dbt/models/ouro_kpis.sql",
                         "projeto_dbt/tests/conservacao.sql", "docs_dbt/manifest.json"):
            self.assertIn(esperado, arquivos)
        self.assertEqual((pacote / "projeto_dbt/models/prata_ctes.sql").read_text(encoding="utf-8"),
                         self.modelos["models/prata_ctes.sql"])
        regras = json.loads((pacote / "projeto_dbt/regras.json").read_text(encoding="utf-8"))
        self.assertEqual(regras, {k: r["value"] for k, r in self.plano["rules"].items()})

    def test_html_tem_cada_kpi_a_faixa_sintetica_e_nao_usa_rede(self):
        html = (self._pacote() / "index.html").read_text(encoding="utf-8")
        self.assertIn("DADOS SINTÉTICOS", html)
        for valor in KPIS.values():
            self.assertIn(f"{valor:.2f}".replace(".", ","), html)
        self.assertEqual(re.findall(r"https?://", html), [])
        self.assertIsNone(re.search(r"<(?:link|img|iframe)\b|\bsrc\s*=", html, re.I))
        self.assertNotRegex(html.lower(), r"econom")  # nenhuma afirmação de economia financeira

    def test_conteudo_da_sandbox_e_dos_eventos_sai_escapado(self):
        html = (self._pacote() / "index.html").read_text(encoding="utf-8")
        self.assertNotIn(INJECAO, html)
        self.assertIn("&lt;script&gt;alert", html)

    def test_toda_regra_aparece_em_decisoes_com_a_evidencia(self):
        decisoes = (self._pacote() / "decisoes.md").read_text(encoding="utf-8")
        evidencias = {e["id"]: e for e in self.plano["evidence"]}
        for chave, regra in self.plano["rules"].items():
            self.assertIn(f"`{chave}`", decisoes)
            for ev in regra["evidence_ids"]:
                self.assertIn(evidencias[ev]["locator"], decisoes)
                self.assertIn(" ".join(evidencias[ev]["excerpt"].split()), " ".join(decisoes.split()))
        self.assertEqual(set(self.plano["rules"]) - set(REGRAS_DOMINIO), set(),
                         "a tabela de domínio cobre as regras do plano demo")

    def test_grafo_tem_um_no_por_modelo_do_manifest(self):
        html = (self._pacote() / "index.html").read_text(encoding="utf-8")
        nos = re.findall(r'data-no="(model\.[^"]+)"', html)
        self.assertEqual(sorted(set(nos)), sorted(f"model.korda_logistica.{Path(c).stem}" for c in self.modelos))
        self.assertEqual(len(nos), len(set(nos)))

    def test_execucao_e_registro_passado_com_recusa_do_hook_e_custo(self):
        execucao = (self._pacote() / "execucao.md").read_text(encoding="utf-8")
        self.assertIn("registro de uma execução passada", execucao.lower())
        self.assertIn("tests/chave_fiscal_unica.sql", execucao)
        self.assertIn("hook", execucao)
        self.assertIn("1 min 30 s", execucao)  # do primeiro ao último evento
        self.assertIn("US$ 0,02", execucao)

    def test_nenhum_caminho_do_host_nem_gabarito_no_pacote(self):
        pacote = self._pacote()
        for caminho, texto in self._textos(pacote).items():
            for proibido in (str(self.raiz), str(RAIZ_REPO), "/home/", "evaluation/golden"):
                self.assertNotIn(proibido, texto, f"{proibido} em {caminho}")
        self.assertFalse([p for p in pacote.rglob("*") if "golden" in p.name or "_gerador" in p.parts])

    def test_sem_insumos_opcionais_mostra_indisponivel_em_vez_de_quebrar(self):
        (self.sandbox / "saida" / "target" / "catalog.json").unlink()
        self.run_id = "run-sem-catalog"
        self.revisao = self.raiz / "revisao" / self.run_id
        self.registro.iniciar(self.plano["project_id"], self.plano["plan_version"], self.run_id)
        self._preparar(catalog=False, avaliacao=False)
        html = (self._pacote() / "index.html").read_text(encoding="utf-8")
        self.assertIn("não avaliado", html)
        self.assertIn("colunas indisponíveis", html)

    def test_drill_down_mostra_o_rateio_e_refaz_cada_kpi_a_partir_dos_dados(self):
        dossie = montar_dossie(self.plano, self.revisao)
        rateio = dossie["ctes"]["A1"]
        self.assertEqual(sorted(p["pedido_id"] for p in rateio["pedidos"]), ["P1", "P2"])
        self.assertEqual(sum(p["parcela_centavos"] for p in rateio["pedidos"]), rateio["frete_centavos"])
        refeitos = {k["chave"]: k["refeito"] for k in dossie["kpis"]}
        self.assertEqual(refeitos["custo_frete_por_entrega"]["numerador"], "500.00")
        self.assertEqual(refeitos["custo_frete_por_entrega"]["denominador"], 3)
        self.assertTrue(all(r["confere"] for r in refeitos.values()), refeitos)
        self.assertEqual({p["pedido_id"] for p in dossie["pedidos"]}, {"P1", "P2", "P3", "P4"})

    def test_kpi_que_nao_bate_com_os_dados_aparece_como_divergente(self):
        (self.revisao / "resultados" / "kpis.json").write_text(
            json.dumps({"kpis": {**KPIS, "otif_pct": 75.0}}), encoding="utf-8")
        refeitos = {k["chave"]: k["refeito"] for k in montar_dossie(self.plano, self.revisao)["kpis"]}
        self.assertFalse(refeitos["otif_pct"]["confere"])
        self.assertTrue(refeitos["custo_frete_por_entrega"]["confere"])

    def test_recusa_empacotar_revisao_alterada_depois_da_avaliacao(self):
        (self.revisao / "infra" / "models" / "ouro_kpis.sql").write_text("select 0", encoding="utf-8")
        with self.assertRaises(ValueError):
            self._pacote()
        self.assertFalse((self.revisao / "entrega").exists())

    def test_reempacotar_substitui_o_pacote(self):
        primeiro = (self._pacote() / "manifesto.json").read_bytes()
        self.assertEqual((self._pacote() / "manifesto.json").read_bytes(), primeiro)


if __name__ == "__main__":
    unittest.main()
