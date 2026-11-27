import hashlib
import json
import os
import sys
import unittest
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, Mock, patch

EXECUCAO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EXECUCAO))
from korda_execution import lote
from korda_execution.eventos import EmissorEventos

RAIZ = EXECUCAO.parents[1]
EXEMPLO = RAIZ / "packages/contracts/ingestion_plan/v0.1.0/examples/01_demo.json"


def gravar_landing(pasta, *, tabelas=None):
    tabelas = lote.TABELAS if tabelas is None else tabelas
    pasta.mkdir(exist_ok=True)
    m = {"formato": lote.FORMATO, "tabelas": {}, "rejeitados": {"arquivo": "_rejeitados.parquet", "linhas": 0}}
    for tabela in tabelas:
        nome = tabela + ".parquet"
        arq = pasta / nome
        arq.parent.mkdir(exist_ok=True)
        arq.write_bytes(b"parquet sintetico " + nome.encode())
        m["tabelas"][tabela] = {"arquivo": nome}
    (pasta / "_rejeitados.parquet").write_bytes(b"parquet vazio")
    (pasta / "manifesto.json").write_text(json.dumps(m))
    for nome in ["_cargas", "_estado", "_gerador", "credenciais.json", "bruto.xml"]:
        (pasta / nome).write_text("dado privado")
    return m


class TestLote(unittest.TestCase):
    def setUp(self):
        self.recursos = ExitStack()
        self.addCleanup(self.recursos.close)
        self.base = Path(self.recursos.enter_context(TemporaryDirectory()))
        self.temp = self.base / "temporario"
        self.revisao = self.base / "revisao"
        self.temp.mkdir()
        self.revisao.mkdir()
        self.snapshot = self.base / "snapshot"
        self.snapshot.mkdir()
        self.eventos = EmissorEventos(self.revisao / "eventos.jsonl", "demo")
        self.ativa = Mock()
        self.proposta = json.loads(EXEMPLO.read_text(encoding="utf-8"))
        self.plano = {"schema_version": "0.2.0", "dataset": "01_demo", "plan_version": "b" * 64,
                      "ingestion": {"level": "n1", "window": {"kind": "full_batch"}, "proposal": self.proposta,
                                    "proposal_sha256": "a" * 64}}

    def executar(self):
        return lote.preparar_lote(self.plano, self.snapshot, self.temp, self.revisao, self.eventos, self.ativa)

    def simulado(self):
        simulador = MagicMock()
        simulador.dia_atual = "2026-09-29"
        simulador.dias_restantes = ["2026-09-30"]
        simulador.catalogo = {"dias": ["2026-09-28", "2026-09-29", "2026-09-30"]}
        simulador.credenciais = {"token": "token-de-teste-privado"}
        simulador.avancar.side_effect = lambda: setattr(simulador, "dia_atual", "2026-09-30")
        factory = self.recursos.enter_context(patch.object(lote, "AmbienteSimulado"))
        factory.return_value.__enter__.return_value = simulador
        return factory, simulador

    def test_arquivos_n0_evidencia_mesmo_manifesto_sem_areas_privadas(self):
        self.plano["ingestion"].update(level="n0", proposal=None, proposal_sha256=None)
        with patch.object(lote, "ingerir", side_effect=lambda src, dest: gravar_landing(dest)) as ingestao:
            privada, publica, replay = self.executar()
        ingestao.assert_called_once_with(self.snapshot, privada)
        self.assertIsNone(replay)
        vistos = {p.relative_to(publica).as_posix() for p in publica.rglob("*") if p.is_file()}
        self.assertEqual(vistos, {t + ".parquet" for t in lote.TABELAS} | {"manifesto.json", "_rejeitados.parquet"})
        recibo = json.loads((self.revisao / "ingestao.json").read_text())
        self.assertEqual(recibo["landing_manifest_sha256"], hashlib.sha256((publica / "manifesto.json").read_bytes()).hexdigest())
        self.assertEqual(recibo["nivel"], "n0")
        self.assertIsNone(recibo["dia_atual"])
        self.assertGreaterEqual(self.ativa.call_count, 2)

    def test_replay_n1_cargas_privadas_e_fim_do_catalogo(self):
        factory, amb = self.simulado()

        def carga(creds, secao, landing):
            self.assertEqual(creds, amb.credenciais)
            self.assertEqual(json.loads(secao.read_text()), self.proposta)
            gravar_landing(landing)
            return {"codigo": 0, "saida": {"resultado": "carga", "carga": 1 if amb.dia_atual.endswith("29") else 2},
                    "stderr": "token-de-teste-privado"}
        with patch.object(lote, "executar_ingestao", side_effect=carga) as ingestao:
            privada, publica, replay = self.executar()
        self.assertEqual(ingestao.call_count, 2)
        self.assertEqual(replay, ("2026-09-30", "2026-09-30"))
        self.assertNotEqual(privada, publica)
        factory.return_value.__exit__.assert_called_once()
        recibo = (self.revisao / "ingestao.json").read_text()
        self.assertEqual([x["carga"] for x in json.loads(recibo)["cargas"]], [1, 2])
        self.assertNotIn("token-de-teste-privado", recibo)

    def test_parcial_materializa_somente_o_corte(self):
        self.plano["ingestion"]["window"] = {"kind": "simulated_as_of", "as_of": "2026-09-29"}
        factory, amb = self.simulado()

        def carga(creds, secao, pasta):
            gravar_landing(pasta, tabelas={"erp/erp_clientes"})
            return {"codigo": 0, "saida": {"resultado": "carga", "carga": 1}}

        with patch.object(lote, "executar_ingestao", side_effect=carga):
            _, publica, replay = self.executar()
        self.assertEqual(replay, ("2026-09-29", "2026-09-30"))
        self.assertEqual(factory.call_args.kwargs["ate_dia"], "2026-09-29")
        amb.avancar.assert_not_called()
        self.assertTrue((publica / "erp/erp_clientes.parquet").exists())
        self.assertFalse((publica / "tms").exists())

    def test_escalonamento_sem_expor_erro_que_contem_credenciais(self):
        factory, amb = self.simulado()
        bruto = {"codigo": 3, "saida": {"escalonamento": {"senha": "token-de-teste-privado"}},
                 "stderr": "token-de-teste-privado"}
        with patch.object(lote, "executar_ingestao", return_value=bruto):
            with self.assertRaisesRegex(ValueError, "escalou") as falha:
                self.executar()
        self.assertNotIn("token-de-teste-privado", str(falha.exception))
        evento, = self.eventos.ler()
        self.assertEqual((evento["type"], evento["dados"]["dia"]), ("intervention_requested", "2026-09-29"))
        self.assertNotIn("token-de-teste-privado", json.dumps(evento))
        amb.avancar.assert_not_called()
        factory.return_value.__exit__.assert_called_once()
        self.assertFalse((self.temp / "fontes-publicas").exists())

    def test_proposta_incompativel_rejeitada_antes_de_subir_simulador(self):
        tms = self.proposta["sources"][1]
        for campo, valor in [
            ("kind", "postgres"), ("incremental_key", {"field": "atualizado_em", "comparison": "maior_ou_igual"}),
            ("credentials_env", ["KORDA_OUTRO"]), ("frequency", "horaria"),
            ("objects", [*tms["objects"], tms["objects"][0]]),
            ("objects", [{**o, "locator": "/desconhecido"} for o in tms["objects"]]),
        ]:
            with self.subTest(campo=campo), patch.dict(tms, {campo: valor}), patch.object(lote, "AmbienteSimulado") as env:
                with self.assertRaises(ValueError):
                    self.executar()
                env.assert_not_called()

    def test_montagem_recusa_indirecao_ou_tabela_sem_manifesto(self):
        privada = self.temp / "landing"
        m = gravar_landing(privada)
        caminho = privada / "erp/erp_pedidos.parquet"
        caminho.unlink()
        caminho.symlink_to(privada / "credenciais.json")
        with self.assertRaises((ValueError, OSError)):
            lote._projetar(privada, self.temp / "p1", False)
        caminho.unlink()
        os.link(privada / "credenciais.json", caminho)
        with self.assertRaisesRegex(ValueError, "inválido"):
            lote._projetar(privada, self.temp / "p2", False)
        m["tabelas"]["tms/tms_entregas"]["arquivo"] = "_estado"
        (privada / "manifesto.json").write_text(json.dumps(m))
        with self.assertRaisesRegex(ValueError, "diverge"):
            lote._projetar(privada, self.temp / "p3", False)

    def test_simulador_valida_intervalo_e_nao_avanca_alem_do_dia(self):
        amb = lote.AmbienteSimulado("01_demo", raiz_runs=self.temp, ate_dia="2026-09-02")
        amb.catalogo = {"dias": ["2026-09-01", "2026-09-03", "2026-09-04"]}
        amb.dia_atual = "2026-09-01"
        self.assertEqual(amb._dias_autorizados(), ["2026-09-01"])
        self.assertEqual(amb.dias_restantes, [])
        with self.assertRaisesRegex(lote.ErroSimulado, "não há mais dias"):
            amb.avancar()
        for data in ["2026-08-31", "2026-09-05", "20260902", "2026-02-30"]:
            amb.ate_dia = data
            with self.subTest(data=data), self.assertRaisesRegex(lote.ErroSimulado, "intervalo"):
                amb._dias_autorizados()
