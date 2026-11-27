"""Fluxo real de ingestão N0/N1 até o avaliador da 01. Nenhum provedor de IA é chamado."""

import csv
import hashlib
import json
import os
import shutil
import sys
import tempfile
import unittest
import uuid
from zipfile import ZipFile
from pathlib import Path
from unittest.mock import patch

from korda_execution.harness.cliente_chat import ClienteChatFalso, RespostaChat
from korda_execution.sandbox import IMAGEM_PADRAO, LocalDockerSandbox, docker_disponivel, imagem_existe
from services.execution.tests.test_worker import FALSO, escrever, modelos_de_referencia, planejar_com_cliente_falso

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "infra/sistemas-simulados"))
from korda_simulados.controle import imagens_disponiveis

PRONTO = docker_disponivel() and imagem_existe(IMAGEM_PADRAO) and imagens_disponiveis()
if not PRONTO and os.environ.get("KORDA_EXIGIR_DOCKER") == "1":
    raise RuntimeError("O teste do worker N1 exige Docker, as imagens da sandbox e dos simuladores e Postgres")


CONSULTAR_ENTRADAS = """
import hashlib
import json
from pathlib import Path
pasta = Path("/work/fontes")
privados = {"_estado", "_gerador", "_cargas", "credenciais.json"}
print(json.dumps({
    "manifesto_sha256": hashlib.sha256((pasta / "manifesto.json").read_bytes()).hexdigest(),
    "tabela": (pasta / "erp/erp_pedidos.parquet").is_file(),
    "csv_bruto": (pasta / "erp/erp_pedidos.csv").exists(),
    "privados": sorted(p.name for p in pasta.rglob("*") if p.name in privados),
    "gabarito": any(Path("/work").rglob("golden")),
}))
"""


def ler_json(p):
    return json.loads(p.read_text(encoding="utf-8"))


def ler_entidades(pasta, nome, chave):
    with (pasta / nome).open(encoding="utf-8", newline="") as fp:
        linhas = list(csv.DictReader(fp))
    entidades = {linha[chave]: linha for linha in linhas}
    if not linhas or len(entidades) != len(linhas):
        raise AssertionError(f"{nome} vazio ou com {chave} duplicado")
    return entidades


def negocio(linha, colunas_linhagem):
    return {k: v for k, v in linha.items() if k not in colunas_linhagem and k != "linhagem_cte"}


def fiscal(itens):
    return sorted((x["chave_cte"], x["sha256"], x["frete_centavos"], x["parcela_centavos"]) for x in itens)


def guardar_evidencia_local(pastas):
    diretorio = os.environ.get("KORDA_EVIDENCIA_LOCAL")
    if not diretorio:
        return
    destino = Path(diretorio)
    destino.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destino.parent) as tmp:
        evidencia = Path(tmp) / "evidencia"
        for nivel, resultados in pastas.items():
            saida = evidencia / nivel
            saida.mkdir(parents=True)
            shutil.copyfile(resultados / "pacote.zip", saida / "pacote.zip")
            for nome in ("avaliacao.json", "ingestao.json", "medicao.json"):
                shutil.copyfile(resultados.parent / nome, saida / nome)
        evidencia.rename(destino)


@unittest.skipUnless(PRONTO, "Docker, sandbox ou sistemas simulados indisponíveis")
class TestWorkerIngestaoDocker(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from data.synthetic.generator.generate import generate
        pasta = tempfile.TemporaryDirectory(prefix="korda-paridade-")
        cls.addClassCleanup(pasta.cleanup)
        fontes = Path(pasta.name)
        generate("01_demo", output_root=fontes)
        cls.fontes = fontes / "01_demo"
        cls.contexto = ler_json(REPO / "packages/contracts/context/v0.1.0/examples/02_rateio_confirmado.json")
        cls.proposta = ler_json(REPO / "packages/contracts/ingestion_plan/v0.1.0/examples/01_demo.json")

    def setUp(self):
        from korda_execution.aprovacoes import Registro

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        self.registro = Registro(self.base / "controle")

    def aprovar(self, nivel, janela):
        from services.planning.korda_planning import gerar_plano

        plano = gerar_plano(self.contexto, destino="pasta-demo", custo_estimado_centavos=0,
                            nivel_ingestao=nivel, janela_ingestao=janela,
                            proposta_ingestao=self.proposta if nivel == "n1" else None)
        pronto = planejar_com_cliente_falso(plano, self.contexto, self.base)
        self.assertEqual(pronto["estado"], "pronto")
        plano = ler_json(Path(pronto["pasta"]) / "plano.json")
        self.registro.registrar(plano)
        self.registro.decidir_plano(plano["project_id"], plano["plan_version"], "Revisor fictício do teste", True)
        return plano

    def test_n0_n1_mesmos_resultados_com_linhagem_propria(self):
        from korda_execution import worker
        from korda_execution.aprovacoes import ErroAprovacao
        from korda_execution.artefatos import entregar

        landing_vista = []
        teste = self

        class ObservarMontagem(LocalDockerSandbox):
            def criar(self):
                super().criar()
                # Consulta no próprio contêiner, após a montagem usada pelo worker.
                leitura = self.rodar_comando(["python", "-c", CONSULTAR_ENTRADAS])
                teste.assertTrue(leitura.ok, leitura.stderr)
                landing_vista.append(json.loads(leitura.stdout))

        pastas = {}
        for nivel in ("n0", "n1"):
            plano = self.aprovar(nivel, {"kind": "full_batch"})
            run = nivel + "-" + uuid.uuid4().hex
            cliente = ClienteChatFalso([escrever(modelos_de_referencia()), RespostaChat.texto("Concluído.", tokens=(0, 0))])
            with patch.object(worker, "LocalDockerSandbox", ObservarMontagem):
                worker.executar(self.registro, plano, run, raiz=self.base, fontes=self.fontes, cfg=FALSO, cliente_llm=cliente)
            self.assertEqual(len(cliente.pedidos), 2)
            self.assertIn(plano["construction"]["document"], cliente.pedidos[0][1]["content"])
            self.assertEqual(self.registro.consultar(run)["state"], "aguardando_aprovacao_entrega")
            revisao = self.base / "revisao" / run
            pastas[nivel] = revisao / "resultados"
            laudo = ler_json(revisao / "avaliacao.json")
            self.assertTrue(laudo["aprovado"], laudo)
            self.assertEqual(laudo["divergencias"], 0)
            medicao = ler_json(revisao / "medicao.json")
            self.assertEqual((medicao["executor"], medicao["custo_centavos"]), ("falso", 0))
            self.assertTrue(medicao["synthetic"] and medicao["custo_completo"])
            documento = (revisao / "documento_base.md").read_bytes()
            self.assertEqual(documento, plano["construction"]["document"].encode("utf-8"))
            self.assertEqual(medicao["documento_base"]["sha256"], hashlib.sha256(documento).hexdigest())
            ingestao = ler_json(revisao / "ingestao.json")
            self.assertEqual(ingestao["nivel"], nivel)
            self.assertEqual(ingestao["janela"], {"kind": "full_batch"})
            self.assertEqual(ingestao["landing_manifest_sha256"], landing_vista[-1].pop("manifesto_sha256"))
            if nivel == "n1":
                self.assertTrue(ingestao["cargas"])
                self.assertEqual(ingestao["dia_atual"], ingestao["ultimo_dia"])
                with self.assertRaises(ErroAprovacao):
                    entregar(self.registro, self.base, run, plano["destination"])
                self.registro.decidir_entrega(run, "Revisor fictício do teste", True)
                publicada = entregar(self.registro, self.base, run, plano["destination"])
                self.assertEqual(self.registro.consultar(run)["state"], "promovida")
                with ZipFile(publicada / "pacote.zip") as pacote:
                    decisoes = json.loads(pacote.read("decisoes.json"))
                    self.assertEqual(decisoes["construction_sha256"], medicao["documento_base"]["sha256"])
                    execucao = json.loads(pacote.read("execucao.json"))
                    self.assertEqual(execucao["run_id"], run)
                    self.assertEqual(execucao["plan_version"], plano["plan_version"])
                    self.assertEqual(execucao["landing_manifest_sha256"], ingestao["landing_manifest_sha256"])
                    self.assertTrue(execucao["avaliacao"]["aprovado"])
                    for nome in ("kpis.json", "por_pedido.csv", "por_viagem.csv"):
                        self.assertEqual(pacote.read(f"resultados/{nome}"), (pastas[nivel] / nome).read_bytes())
            self.assertFalse((self.base / "sandbox" / run).exists())

        self.assertEqual(landing_vista, 2 * [{"tabela": True, "csv_bruto": False, "privados": [], "gabarito": False}])
        n0, n1 = pastas["n0"], pastas["n1"]
        self.assertEqual(ler_json(n0 / "kpis.json"), ler_json(n1 / "kpis.json"))
        self.assertEqual(set(ler_json(n1 / "kpis.json")["kpis"]), {"custo_frete_por_entrega", "otif_pct", "ocupacao_pct"})
        tabelas = [
            ("por_pedido.csv", "pedido_id", {"pedido": "erp:erp_pedidos", "entrega": "tms:/entregas"}),
            ("por_viagem.csv", "viagem_id", {"viagem": "tms:/viagens", "veiculo": "tms:/veiculos"}),
        ]
        hashes = {xml.name: hashlib.sha256(xml.read_bytes()).hexdigest() for xml in (self.fontes / "cte").glob("*.xml")}
        parcelas_xml = 0
        for nome, chave, origens in tabelas:
            arquivos = ler_entidades(n0, nome, chave)
            sistemas = ler_entidades(n1, nome, chave)
            self.assertEqual(arquivos.keys(), sistemas.keys(), nome)
            linhagem = {f"{prefixo}_{entidade}" for entidade in origens for prefixo in ("arquivo", "linha", "origem", "carga")}
            for id_, a in arquivos.items():
                b = sistemas[id_]
                self.assertEqual(negocio(a, linhagem), negocio(b, linhagem), f"{nome} {id_}")
                for entidade, origem in origens.items():
                    self.assertTrue(a[f"arquivo_{entidade}"].endswith(".csv"))
                    self.assertGreater(int(a[f"linha_{entidade}"]), 0)
                    self.assertEqual((b[f"arquivo_{entidade}"], b[f"linha_{entidade}"]), ("", ""))
                    self.assertEqual(b[f"origem_{entidade}"], origem)
                    self.assertGreaterEqual(int(b[f"carga_{entidade}"]), 1)
                if nome == "por_pedido.csv":
                    linhas_n0 = json.loads(a["linhagem_cte"])
                    linhas_n1 = json.loads(b["linhagem_cte"])
                    self.assertEqual(fiscal(linhas_n0), fiscal(linhas_n1), id_)
                    for xml in linhas_n1:
                        arq = Path(xml["arquivo"])
                        self.assertIn(arq.name, hashes)
                        self.assertEqual(xml["sha256"], hashes[arq.name])
                        self.assertGreaterEqual(int(xml["carga"]), 1)
                        parcelas_xml += 1
        self.assertGreater(parcelas_xml, 0, "A 01_demo precisa exercitar o vínculo entre CT-e e rateio real")
        guardar_evidencia_local(pastas)

    def test_janela_parcial_requer_referencia_compativel(self):
        from korda_execution import worker
        from korda_execution.aprovacoes import ErroAprovacao

        plano = self.aprovar("n1", {"kind": "simulated_as_of", "as_of": "2026-09-02"})
        run = "parcial-" + uuid.uuid4().hex
        cliente = ClienteChatFalso([])
        with patch.object(worker, "LocalDockerSandbox", side_effect=AssertionError("Build para janela parcial")):
            with self.assertRaises(worker.FalhaExecucao):
                worker.executar(self.registro, plano, run, raiz=self.base, fontes=self.fontes, cfg=FALSO, cliente_llm=cliente)
        self.assertFalse(cliente.pedidos)
        estado = self.registro.consultar(run)
        self.assertEqual(estado["state"], "falhou", estado)
        self.assertIsNone(estado["manifesto"])
        revisao = self.base / "revisao" / run
        ingestao = ler_json(revisao / "ingestao.json")
        self.assertEqual(ingestao["nivel"], "n1")
        self.assertEqual(ingestao["janela"], {"kind": "simulated_as_of", "as_of": "2026-09-02"})
        self.assertEqual(ingestao["dia_atual"], "2026-09-02")
        self.assertLess(ingestao["dia_atual"], ingestao["ultimo_dia"])
        laudo = ler_json(revisao / "avaliacao.json")
        self.assertEqual((laudo["aprovado"], laudo["classe"]), (False, "regra"))
        self.assertFalse((revisao / "resultados").exists())
        self.assertFalse((self.base / "sandbox" / run).exists())
        self.assertEqual(list(self.base.rglob("credenciais.json")), [])
        with self.assertRaises(ErroAprovacao):
            self.registro.autorizar_destino(run, plano["destination"])
