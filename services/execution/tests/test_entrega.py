"""Pacote de entrega (K13), sem Docker: uma revisão montada à mão com dados sintéticos mínimos.

O pacote não tem página: `entrega.json` é o contrato que o front vai consumir.

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
from korda_execution.entrega import REGRAS_DOMINIO, empacotar, montar_entrega
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
        self.prata = {"prata_ctes": (b"PAR1-ctes-ficticio", 3), "prata_rateios": (b"PAR1-rateios-ficticio", 3)}
        self.eventos = [
            {"run_id": self.run_id, "step": "plano", "type": "run_started", "message": "Iniciada", "attempt": 1,
             "ts": "2026-11-27T10:00:00.000+00:00", "dados": {"executor": "falso"}},
            {"run_id": self.run_id, "step": "construcao", "type": "tool_refused", "message": "escrita fora de models/",
             "attempt": 1, "ts": "2026-11-27T10:00:05.000+00:00",
             "dados": {"origem": "hook", "caminho": "tests/chave_fiscal_unica.sql"}},
            {"run_id": self.run_id, "step": "construcao", "type": "file_written", "message": "models/prata_ctes.sql",
             "attempt": 1, "ts": "2026-11-27T10:00:09.000+00:00", "dados": {"caminho": "models/prata_ctes.sql"}},
            {"run_id": self.run_id, "step": "construcao", "type": "dbt_failed", "message": "build", "attempt": 1,
             "ts": "2026-11-27T10:00:20.000+00:00", "dados": {"codigo": 1}},
            {"run_id": self.run_id, "step": "modelos", "type": "fix_applied", "message": "corrigido", "attempt": 2,
             "ts": "2026-11-27T10:00:40.000+00:00", "dados": {"custo_centavos": 12}},
            {"run_id": self.run_id, "step": "construcao", "type": "dbt_passed", "message": "build", "attempt": 2,
             "ts": "2026-11-27T10:01:30.000+00:00", "dados": {"codigo": 0}},
        ]
        self._preparar()

    def _preparar(self, *, catalog=True, prata=True, kpis=KPIS):
        resultados = self.sandbox / "saida" / "resultados"
        models = self.sandbox / "projeto" / "models"
        target = self.sandbox / "saida" / "target"
        pasta_prata = self.sandbox / "saida" / "prata"
        for pasta in (resultados, models, target, pasta_prata):
            pasta.mkdir(parents=True, exist_ok=True)
        (resultados / "kpis.json").write_text(json.dumps({"kpis": kpis}) + "\n", encoding="utf-8")
        (resultados / "por_pedido.csv").write_text(_csv(PEDIDO, PEDIDOS), encoding="utf-8")
        (resultados / "por_viagem.csv").write_text(_csv(VIAGEM, VIAGENS), encoding="utf-8")
        for caminho, sql in self.modelos.items():
            (models / Path(caminho).name).write_text(sql, encoding="utf-8")
        for tabela, (conteudo, _linhas) in self.prata.items():
            (pasta_prata / f"{tabela}.parquet").write_bytes(conteudo)
        (pasta_prata / "linhas.json").write_text(json.dumps({t: n for t, (_c, n) in self.prata.items()}))
        (target / "manifest.json").write_text(json.dumps(_manifest_dbt(self.modelos)), encoding="utf-8")
        (target / "run_results.json").write_text(json.dumps({"results": [
            {"unique_id": "test.korda_logistica.chave_fiscal_unica", "status": "pass", "execution_time": 0.1}]}),
            encoding="utf-8")
        if catalog:
            (target / "catalog.json").write_text(json.dumps({"nodes": {"model.korda_logistica.prata_ctes": {
                "columns": {"chave_cte": {"type": "VARCHAR", "index": 1, "name": "chave_cte"},
                            "valor_centavos": {"type": "BIGINT", "index": 2, "name": "valor_centavos"}}
            }}, "sources": {}}), encoding="utf-8")
        self.revisao.mkdir(parents=True, exist_ok=True)
        manifesto = capturar(resultados, self.revisao / "resultados")
        manifesto["infra"] = capturar_infra(models, target, self.revisao / "infra",
                                            prata=pasta_prata if prata else None)
        (self.revisao / "eventos.jsonl").write_text(
            "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in self.eventos), encoding="utf-8")
        (self.revisao / "medicao.json").write_text(json.dumps({
            "executor": "falso", "synthetic": True, "tentativas": 2, "custo_usd": 0.02, "custo_centavos": 12,
            "tokens_entrada": 1000, "tokens_saida": 200, "duracao_s": 70.0}), encoding="utf-8")
        self.registro.finalizar(self.run_id, aprovado=True, manifesto=manifesto)

    def _pacote(self):
        return empacotar(self.registro, self.raiz, self.run_id)

    def _entrega(self):
        return json.loads((self._pacote() / "entrega.json").read_text(encoding="utf-8"))

    def test_estrutura_e_manifesto_do_pacote_conferem(self):
        pacote = self._pacote()
        self.assertEqual(pacote, self.revisao / "entrega")
        manifesto = json.loads((pacote / "manifesto.json").read_text(encoding="utf-8"))
        arquivos = {str(p.relative_to(pacote)) for p in pacote.rglob("*") if p.is_file()} - {"manifesto.json"}
        self.assertEqual(set(manifesto["arquivos"]), arquivos)
        for caminho, meta in manifesto["arquivos"].items():
            self.assertEqual(hashlib.sha256((pacote / caminho).read_bytes()).hexdigest(), meta["sha256"], caminho)
        self.assertEqual(manifesto["aprovado"], self.registro.consultar(self.run_id)["manifesto"])
        for esperado in ("entrega.json", "decisoes.md", "execucao.md", "dados/kpis.json", "dados/por_pedido.csv",
                         "dados/por_viagem.csv", "dados/prata/prata_ctes.parquet", "dados/prata/linhas.json",
                         "projeto_dbt/dbt_project.yml", "projeto_dbt/profiles.yml", "projeto_dbt/exportar_prata.py",
                         "projeto_dbt/regras.json", "projeto_dbt/README.md", "projeto_dbt/models/ouro_kpis.sql",
                         "projeto_dbt/tests/conservacao.sql", "docs_dbt/manifest.json"):
            self.assertIn(esperado, arquivos)
        self.assertNotIn("index.html", arquivos)  # a visualização fica no front
        regras = json.loads((pacote / "projeto_dbt/regras.json").read_text(encoding="utf-8"))
        self.assertEqual(regras, {k: r["value"] for k, r in self.plano["rules"].items()})

    def test_kpis_do_entrega_json_sao_os_do_resultado_e_a_conta_confere(self):
        entrega = self._entrega()
        self.assertEqual(entrega["entrega_version"], "0.1.0")
        self.assertTrue(entrega["sintetico"])
        self.assertEqual({k["chave"]: k["valor"] for k in entrega["kpis"]}, KPIS)
        contas = {k["chave"]: k["conta"] for k in entrega["kpis"]}
        self.assertEqual(contas["custo_frete_por_entrega"]["numerador"], "500.00")
        self.assertEqual(contas["custo_frete_por_entrega"]["denominador"], 3)
        self.assertTrue(all(c["confere"] for c in contas.values()), contas)
        for k in entrega["kpis"]:
            self.assertEqual(k["formula"], self.plano["metrics"][k["chave"]]["formula"])
            self.assertEqual(k["regras"], self.plano["metrics"][k["chave"]]["rule_keys"])

    def test_kpi_que_nao_bate_com_os_dados_aparece_como_divergente(self):
        (self.revisao / "resultados" / "kpis.json").write_text(
            json.dumps({"kpis": {**KPIS, "otif_pct": 75.0}}), encoding="utf-8")
        contas = {k["chave"]: k["conta"] for k in montar_entrega(self.plano, self.revisao)["kpis"]}
        self.assertFalse(contas["otif_pct"]["confere"])
        self.assertTrue(contas["custo_frete_por_entrega"]["confere"])

    def test_toda_regra_aparece_no_json_e_em_decisoes_com_a_evidencia(self):
        pacote = self._pacote()
        decisoes = (pacote / "decisoes.md").read_text(encoding="utf-8")
        regras = {r["chave"]: r for r in json.loads((pacote / "entrega.json").read_text(encoding="utf-8"))["regras"]}
        evidencias = {e["id"]: e for e in self.plano["evidence"]}
        self.assertEqual(set(regras), set(self.plano["rules"]))
        for chave, regra in self.plano["rules"].items():
            self.assertIn(f"`{chave}`", decisoes)
            self.assertEqual(regras[chave]["valor"], regra["value"])
            for ev in regra["evidence_ids"]:
                self.assertIn(evidencias[ev]["locator"], decisoes)
                self.assertIn(" ".join(evidencias[ev]["excerpt"].split()), " ".join(decisoes.split()))
                self.assertIn(evidencias[ev]["excerpt"], [e["excerpt"] for e in regras[chave]["evidencias"]])
        self.assertEqual(set(self.plano["rules"]) - set(REGRAS_DOMINIO), set(),
                         "a tabela de domínio cobre as regras do plano demo")
        self.assertNotIn("avaliador", decisoes.lower())

    def test_prata_diz_onde_esta_cada_tabela_com_hash_linhas_e_colunas(self):
        pacote = self._pacote()
        prata = {p["tabela"]: p for p in json.loads((pacote / "entrega.json").read_text(encoding="utf-8"))["prata"]}
        self.assertEqual(set(prata), set(self.prata))
        for tabela, (conteudo, linhas) in self.prata.items():
            item = prata[tabela]
            self.assertEqual(item["arquivo"], f"dados/prata/{tabela}.parquet")
            self.assertEqual((pacote / item["arquivo"]).read_bytes(), conteudo)
            self.assertEqual(item["sha256"], hashlib.sha256(conteudo).hexdigest())
            self.assertEqual(item["linhas"], linhas)
            self.assertEqual(item["modelo"], f"projeto_dbt/models/{tabela}.sql")
        self.assertEqual(prata["prata_ctes"]["colunas"], [{"nome": "chave_cte", "tipo": "VARCHAR"},
                                                           {"nome": "valor_centavos", "tipo": "BIGINT"}])
        self.assertEqual(prata["prata_rateios"]["depende_de"],
                         ["source.korda_logistica.sinteticas.bronze_pedidos", "model.korda_logistica.prata_ctes"])

    def test_estrutura_tecnica_tem_um_modelo_por_no_do_manifest_com_a_camada(self):
        estrutura = self._entrega()["estrutura"]
        modelos = {m["nome"]: m for m in estrutura["modelos"]}
        self.assertEqual(set(modelos), {Path(c).stem for c in self.modelos})
        for nome, modelo in modelos.items():
            self.assertEqual(modelo["camada"], nome.split("_")[0])
            self.assertEqual(modelo["arquivo"], f"projeto_dbt/models/{nome}.sql")
        self.assertEqual(estrutura["camadas"]["prata"], ["prata_ctes", "prata_rateios"])
        self.assertIn("bronze_documentos", estrutura["camadas"]["bronze"])
        testes = {t["nome"]: t for t in estrutura["testes"]}
        self.assertEqual(testes["chave_fiscal_unica"]["status"], "pass")
        ids = {m["id"] for m in estrutura["modelos"]} | {f["id"] for f in estrutura["fontes"]} | \
            {t["id"] for t in estrutura["testes"]}
        self.assertTrue(estrutura["arestas"])
        self.assertTrue(all(a in ids and b in ids for a, b in estrutura["arestas"]))

    def test_sem_insumos_opcionais_marca_indisponivel_em_vez_de_quebrar(self):
        (self.sandbox / "saida" / "target" / "catalog.json").unlink()
        self.run_id = "run-sem-catalog"
        self.revisao = self.raiz / "revisao" / self.run_id
        self.registro.iniciar(self.plano["project_id"], self.plano["plan_version"], self.run_id)
        self._preparar(catalog=False, prata=False)
        entrega = self._entrega()
        self.assertEqual(entrega["prata"], [])
        self.assertIn("prata", entrega["indisponivel"])
        self.assertIn("colunas", entrega["indisponivel"])
        self.assertTrue(all(m["colunas"] is None for m in entrega["estrutura"]["modelos"]))
        (self.revisao / "infra/target/manifest.json").unlink()
        sem_manifest = montar_entrega(self.plano, self.revisao)
        self.assertIsNone(sem_manifest["estrutura"])
        self.assertIn("estrutura", sem_manifest["indisponivel"])

    def test_execucao_e_registro_passado_com_recusa_do_hook_e_custo(self):
        execucao = (self._pacote() / "execucao.md").read_text(encoding="utf-8")
        self.assertIn("registro de uma execução passada", execucao.lower())
        self.assertIn("tests/chave_fiscal_unica.sql", execucao)
        self.assertIn("hook", execucao)
        self.assertIn("1 min 30 s", execucao)  # do primeiro ao último evento
        self.assertIn("US$ 0,02", execucao)

    def test_nenhum_caminho_do_host_nem_gabarito_nem_laudo_no_pacote(self):
        pacote = self._pacote()
        for caminho in pacote.rglob("*"):
            if caminho.is_file() and caminho.suffix != ".parquet":
                texto = caminho.read_text(encoding="utf-8")
                for proibido in (str(self.raiz), str(RAIZ_REPO), "/home/", "evaluation/golden"):
                    self.assertNotIn(proibido, texto, f"{proibido} em {caminho}")
        nomes = [p.name for p in pacote.rglob("*")]
        self.assertFalse([n for n in nomes if "golden" in n or n in ("_gerador", "avaliacao.json", "index.html")])

    def test_recusa_empacotar_revisao_alterada_depois_da_execucao(self):
        for alvo in ("infra/models/ouro_kpis.sql", "infra/prata/prata_ctes.parquet"):
            with self.subTest(alvo=alvo):
                original = (self.revisao / alvo).read_bytes()
                (self.revisao / alvo).write_bytes(b"alterado")
                with self.assertRaises(ValueError):
                    self._pacote()
                self.assertFalse((self.revisao / "entrega").exists())
                (self.revisao / alvo).write_bytes(original)

    def test_reempacotar_gera_os_mesmos_bytes(self):
        primeiro = (self._pacote() / "manifesto.json").read_bytes()
        self.assertEqual((self._pacote() / "manifesto.json").read_bytes(), primeiro)


if __name__ == "__main__":
    unittest.main()
