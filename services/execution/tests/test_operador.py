"""Valida o ponto de entrada e a preparação do lote em um host sem Docker."""

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from services.planning.korda_planning import gerar_plano

from korda_execution.__main__ import main
from korda_execution.aprovacoes import ErroAprovacao, Registro
from korda_execution.worker import FONTE_CSV, PROJETO, _snapshot, executar


class TestOperador(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.raiz = Path(temp.name)
        repo = PROJETO.parents[3]
        arquivo = repo / "packages/contracts/context/v0.1.0/examples/02_rateio_confirmado.json"
        self.plano = gerar_plano(json.loads(arquivo.read_text()), destino="Demo.01", custo_estimado_centavos=0)
        self.registro = Registro(self.raiz / "controle")

    def test_cli_bloqueia_execucao_sem_decisao_e_registra_falha_de_preparo(self):
        arquivo = self.raiz / "plano.json"
        arquivo.write_text(json.dumps(self.plano))
        raiz = ["--raiz", str(self.raiz)]
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(main([*raiz, "registrar", str(arquivo)]), 0)
            self.assertEqual(main([*raiz, "executar", str(arquivo), "--run-id", "teste"]), 1)
        with self.assertRaises(ErroAprovacao):
            self.registro.consultar("teste")
        self.registro.decidir_plano("demo-01", self.plano["plan_version"], "Revisora fictícia (teste)", True)
        with patch("korda_execution.worker.LocalDockerSandbox") as sandbox, self.assertRaises(FileNotFoundError):
            executar(self.registro, self.plano, "teste", raiz=self.raiz, fontes=self.raiz / "ausente")
        sandbox.assert_not_called()
        self.assertEqual(self.registro.consultar("teste")["state"], "falhou")
        self.assertFalse((self.raiz / "entregas").exists())
        eventos = (self.raiz / "revisao/teste/eventos.jsonl").read_text().splitlines()
        self.assertEqual(json.loads(eventos[-1])["type"], "run_failed")

    def test_cli_empacotar_monta_o_pacote_da_execucao(self):
        raiz = ["--raiz", str(self.raiz)]
        saida = io.StringIO()
        with patch("korda_execution.__main__.empacotar", return_value=self.raiz / "revisao/r1/entrega") as emp, \
                redirect_stdout(saida):
            self.assertEqual(main([*raiz, "empacotar", "r1"]), 0)
        registro, raiz_usada, run_id = emp.call_args.args
        self.assertEqual((raiz_usada, run_id), (self.raiz.resolve(), "r1"))
        self.assertEqual(json.loads(saida.getvalue())["pacote"], str(self.raiz / "revisao/r1/entrega"))
        with redirect_stderr(io.StringIO()) as erro:
            self.assertEqual(main([*raiz, "empacotar", "desconhecida"]), 1)
        self.assertIn("execução desconhecida", erro.getvalue())

    def test_colisao_preserva_revisao_preexistente(self):
        self.registro.registrar(self.plano)
        self.registro.decidir_plano("demo-01", self.plano["plan_version"], "Revisora de teste", True)
        revisao = self.raiz / "revisao" / "ocupada"
        revisao.mkdir(parents=True)
        anterior = revisao / "eventos.jsonl"
        anterior.write_bytes(b"registro anterior\n")
        with self.assertRaises(FileExistsError):
            executar(self.registro, self.plano, "ocupada", raiz=self.raiz, fontes=self.raiz / "ausente")
        self.assertEqual(anterior.read_bytes(), b"registro anterior\n")
        self.assertEqual(self.registro.consultar("ocupada")["state"], "falhou")

    def test_so_arquivos_aprovados_entram_no_snapshot(self):
        origem = self.raiz / "bruto"
        for pasta, nomes in {**FONTE_CSV, "cte": ["documento.xml"]}.items():
            (origem / pasta).mkdir(parents=True)
            for nome in nomes:
                (origem / pasta / nome).write_text(nome)
        (origem / "_gerador").mkdir()
        (origem / "_gerador/contagens.json").write_text("{}")
        (origem / "erp/interno.csv").write_text("material externo ao plano")
        destino = self.raiz / "snapshot"
        destino.mkdir()
        _snapshot(origem, destino)
        arquivos = {str(p.relative_to(destino)) for p in destino.rglob("*") if p.is_file()}
        self.assertEqual(arquivos, {f"{pasta}/{nome}" for pasta, nomes in FONTE_CSV.items()
                                    for nome in nomes} | {"cte/documento.xml"})


if __name__ == "__main__":
    unittest.main()
