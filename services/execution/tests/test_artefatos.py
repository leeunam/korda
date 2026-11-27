import hashlib
import json
import os
import shutil
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from korda_execution.artefatos import LIMITES, LIMITES_INFRA, capturar, capturar_infra, entregar


class RegistroTeste:
    def __init__(self, manifesto):
        self.manifesto = manifesto
        self.autorizado = True
        self.falhar_commit = False
        self.promovido = False

    @contextmanager
    def promover(self, run_id, destino):
        if not self.autorizado or (run_id, destino) != ("run-1", "demo"):
            raise ValueError("aprovação ausente")
        yield self.manifesto
        if self.falhar_commit:
            raise RuntimeError("transação interrompida")
        self.promovido = True


class TestArtefatos(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.raiz = Path(tmp.name)
        self.origem = self.raiz / "sandbox" / "resultados"
        self.origem.mkdir(parents=True)
        self.conteudo = {"kpis.json": b'{"kpis":{}}\n', "por_pedido.csv": b"id\n1\n", "por_viagem.csv": b"viagem\n2\n"}
        for nome, dados in self.conteudo.items():
            (self.origem / nome).write_bytes(dados)
        self.staging = self.raiz / "revisao" / "run-1" / "resultados"
        self.pacote = self.raiz / "revisao" / "run-1" / "entrega"
        self.final = self.raiz / "entregas" / "demo" / "run-1"

    def _aprovar(self):
        """Captura os resultados e monta um pacote mínimo com manifesto.json, como o empacotar faz."""
        manifesto = capturar(self.origem, self.staging)
        shutil.copytree(self.staging, self.pacote / "dados")
        (self.pacote / "entrega.json").write_text("{}")
        self._selar(manifesto)
        return RegistroTeste(manifesto)

    def _selar(self, aprovado):
        arquivos = {str(p.relative_to(self.pacote)): {"bytes": p.stat().st_size,
                                                      "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
                    for p in sorted(self.pacote.rglob("*")) if p.is_file() and p.name != "manifesto.json"}
        (self.pacote / "manifesto.json").write_text(json.dumps({"arquivos": arquivos, "aprovado": aprovado}))

    def test_captura_so_resultados_inteiros_e_publicacao_concorrente_coincide(self):
        (self.origem / "privado.log").write_text("interno")
        with ThreadPoolExecutor(max_workers=2) as pool:
            resultados = list(pool.map(lambda _: capturar(self.origem, self.staging), range(2)))
        esperado = {"arquivos": {
            nome: {"bytes": len(dados), "sha256": hashlib.sha256(dados).hexdigest()}
            for nome, dados in self.conteudo.items()
        }}
        self.assertEqual(resultados, [esperado, esperado])
        self.assertEqual({p.name for p in self.staging.iterdir()}, set(self.conteudo))
        (self.origem / "kpis.json").write_text("mudou")
        with self.assertRaises(ValueError):
            capturar(self.origem, self.staging)
        self.assertEqual((self.staging / "kpis.json").read_bytes(), self.conteudo["kpis.json"])

    def test_recusa_links_arquivos_especiais_e_limites_sem_publicar_parcial(self):
        ultimo = self.origem / "por_viagem.csv"
        ultimo.unlink()
        for tipo in ("symlink", "hardlink", "fifo", "grande"):
            with self.subTest(tipo=tipo):
                if tipo == "symlink":
                    ultimo.symlink_to(self.origem / "por_pedido.csv")
                elif tipo == "hardlink":
                    os.link(self.origem / "por_pedido.csv", ultimo)
                elif tipo == "fifo":
                    os.mkfifo(ultimo)
                else:
                    ultimo.write_text("a" * 64)
                with patch.dict(LIMITES, {"por_viagem.csv": 32}), self.assertRaises((ValueError, OSError)):
                    capturar(self.origem, self.staging)
                self.assertEqual(list(self.staging.parent.iterdir()), [])
                ultimo.unlink()

    def test_recusa_diretorios_indiretos_e_destino_nao_autorizado(self):
        link = self.raiz / "atalho"
        link.symlink_to(self.origem.parent, target_is_directory=True)
        with self.assertRaises(OSError):
            capturar(link / "resultados", self.staging)
        registro = self._aprovar()
        registro.autorizado = False
        with self.assertRaises(ValueError):
            entregar(registro, self.raiz, "run-1", "demo")
        self.assertFalse((self.raiz / "entregas").exists())
        registro.autorizado = True
        with self.assertRaises(ValueError):
            entregar(registro, self.raiz, "run-1", "../outro")
        (self.raiz / "entregas").symlink_to(self.origem, target_is_directory=True)
        with self.assertRaises(OSError):
            entregar(registro, self.raiz, "run-1", "demo")
        self.assertFalse((self.origem / "demo").exists())

    def test_erro_na_janela_entre_rename_e_commit_e_retomavel(self):
        registro = self._aprovar()
        registro.falhar_commit = True
        with self.assertRaises(RuntimeError):
            entregar(registro, self.raiz, "run-1", "demo")
        self.assertTrue(self.final.is_dir())
        inode = self.final.stat().st_ino
        self.assertFalse(registro.promovido)
        registro.falhar_commit = False
        self.assertEqual(entregar(registro, self.raiz, "run-1", "demo"), self.final)
        self.assertTrue(registro.promovido)
        self.assertEqual(self.final.stat().st_ino, inode)

    def test_promove_o_pacote_inteiro(self):
        registro = self._aprovar()
        self.assertEqual(entregar(registro, self.raiz, "run-1", "demo"), self.final)
        self.assertEqual({str(p.relative_to(self.final)) for p in self.final.rglob("*") if p.is_file()},
                         {"dados/kpis.json", "dados/por_pedido.csv", "dados/por_viagem.csv", "entrega.json",
                          "manifesto.json"})

    def test_divergencia_de_manifesto_conteudo_ou_inventario_bloqueia_promocao(self):
        registro = self._aprovar()
        manifesto = registro.manifesto
        registro.manifesto = {"arquivos": {"invalido": {}}}
        with self.assertRaises(ValueError):
            entregar(registro, self.raiz, "run-1", "demo")
        registro.manifesto = manifesto
        # Dado alterado no pacote, mesmo com o manifesto.json do pacote refeito.
        (self.pacote / "dados" / "kpis.json").write_text("alterado")
        self._selar(manifesto)
        with self.assertRaises(ValueError):
            entregar(registro, self.raiz, "run-1", "demo")
        (self.pacote / "dados" / "kpis.json").write_bytes(self.conteudo["kpis.json"])
        self._selar(manifesto)
        # Arquivo extra fora do manifesto.json do pacote.
        (self.pacote / "extra.log").write_text("extra")
        with self.assertRaises(ValueError):
            entregar(registro, self.raiz, "run-1", "demo")
        (self.pacote / "extra.log").unlink()
        # entrega.json alterado depois de selado.
        (self.pacote / "entrega.json").write_text('{"alterado": true}')
        with self.assertRaises(ValueError):
            entregar(registro, self.raiz, "run-1", "demo")
        self._selar(manifesto)
        self.assertFalse(self.final.exists())
        self.final.mkdir(parents=True, exist_ok=True)
        (self.final / "preexistente").write_text("preservar")
        with self.assertRaises(ValueError):
            entregar(registro, self.raiz, "run-1", "demo")
        self.assertFalse(registro.promovido)
        self.assertEqual({p.name for p in self.final.iterdir()}, {"preexistente"})

    def test_modelo_do_pacote_tem_que_bater_com_a_infra_aprovada(self):
        registro = self._aprovar()
        modelo = b"select 1\n"
        registro.manifesto = {**registro.manifesto, "infra": {
            "models/ouro_kpis.sql": {"bytes": len(modelo), "sha256": hashlib.sha256(modelo).hexdigest()},
            "target/manifest.json": {"bytes": 2, "sha256": hashlib.sha256(b"{}").hexdigest()},
            "target/run_results.json": {"bytes": 2, "sha256": hashlib.sha256(b"{}").hexdigest()}}}
        (self.pacote / "projeto_dbt" / "models").mkdir(parents=True)
        (self.pacote / "docs_dbt").mkdir()
        (self.pacote / "docs_dbt" / "manifest.json").write_text("{}")
        (self.pacote / "docs_dbt" / "run_results.json").write_text("{}")
        (self.pacote / "projeto_dbt" / "models" / "ouro_kpis.sql").write_text("select 0\n")
        self._selar(registro.manifesto)
        with self.assertRaises(ValueError):
            entregar(registro, self.raiz, "run-1", "demo")
        (self.pacote / "projeto_dbt" / "models" / "ouro_kpis.sql").write_bytes(modelo)
        self._selar(registro.manifesto)
        self.assertEqual(entregar(registro, self.raiz, "run-1", "demo"), self.final)


class TestCapturaInfra(unittest.TestCase):
    """Modelos e target do dbt vêm da sandbox (não confiável) e são congelados com hash."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.raiz = Path(tmp.name)
        self.models = self.raiz / "sandbox" / "projeto" / "models"
        self.target = self.raiz / "sandbox" / "saida" / "target"
        (self.models / "prata").mkdir(parents=True)
        self.target.mkdir(parents=True)
        (self.models / "ouro_kpis.sql").write_text("select 1 as x\n")
        (self.models / "prata" / "prata_ctes.sql").write_text("select 2 as y\n")
        for nome in ("manifest.json", "catalog.json", "run_results.json"):
            (self.target / nome).write_text('{"nome": "%s"}' % nome)
        # O dbt deixa outras saídas no target; elas não entram na entrega.
        (self.target / "graph.gpickle").write_bytes(b"\x00")
        (self.target / "compiled").mkdir()
        self.destino = self.raiz / "revisao" / "run-1" / "infra"

    def _sha(self, caminho):
        return hashlib.sha256(caminho.read_bytes()).hexdigest()

    def test_captura_modelos_e_tres_jsons_do_target_com_hash(self):
        infra = capturar_infra(self.models, self.target, self.destino)
        self.assertEqual(set(infra), {"models/ouro_kpis.sql", "models/prata/prata_ctes.sql",
                                      "target/manifest.json", "target/catalog.json", "target/run_results.json"})
        for rel, meta in infra.items():
            self.assertEqual(meta["sha256"], self._sha(self.destino / rel), rel)
            self.assertEqual(meta["bytes"], (self.destino / rel).stat().st_size)
        self.assertFalse((self.destino / "target" / "graph.gpickle").exists())

    def test_catalog_e_opcional_mas_manifest_e_modelos_nao(self):
        (self.target / "catalog.json").unlink()
        self.assertNotIn("target/catalog.json", capturar_infra(self.models, self.target, self.destino))
        (self.target / "manifest.json").unlink()
        with self.assertRaises((ValueError, OSError)):
            capturar_infra(self.models, self.target, self.raiz / "outro")
        self.assertFalse((self.raiz / "outro").exists())

    def test_recusa_link_arquivo_fora_do_contrato_e_tamanho(self):
        alvo = self.models / "prata" / "extra.sql"
        casos = {
            "symlink": lambda: alvo.symlink_to(self.models / "ouro_kpis.sql"),
            "hardlink": lambda: os.link(self.models / "ouro_kpis.sql", alvo),
            "yaml": lambda: (self.models / "testes.yml").write_text("version: 2\n"),
            "grande": lambda: alvo.write_text("a" * 64),
        }
        for tipo, criar in casos.items():
            with self.subTest(tipo=tipo):
                criar()
                with patch("korda_execution.artefatos.LIMITE_MODELO", 32), self.assertRaises((ValueError, OSError)):
                    capturar_infra(self.models, self.target, self.destino)
                self.assertFalse(self.destino.exists())
                (self.models / "testes.yml").unlink(missing_ok=True)
                alvo.unlink(missing_ok=True)

    def _prata(self):
        prata = self.raiz / "sandbox" / "saida" / "prata"
        prata.mkdir()
        (prata / "prata_ctes.parquet").write_bytes(b"PAR1-ctes")
        (prata / "prata_rateios.parquet").write_bytes(b"PAR1-rateios")
        (prata / "linhas.json").write_text('{"prata_ctes": 3, "prata_rateios": 4}')
        return prata

    def test_captura_tabelas_prata_exportadas(self):
        prata = self._prata()
        infra = capturar_infra(self.models, self.target, self.destino, prata=prata)
        for rel in ("prata/prata_ctes.parquet", "prata/prata_rateios.parquet", "prata/linhas.json"):
            self.assertEqual(infra[rel]["sha256"], self._sha(self.destino / rel), rel)

    def test_recusa_prata_fora_do_padrao(self):
        prata = self._prata()
        casos = {
            "nome": lambda: (prata / "Outra Tabela.parquet").write_bytes(b"x"),
            "extensao": lambda: (prata / "prata_x.csv").write_text("a"),
            "subpasta": lambda: (prata / "sub").mkdir(),
            "symlink": lambda: (prata / "prata_y.parquet").symlink_to(prata / "prata_ctes.parquet"),
        }
        for tipo, criar in casos.items():
            with self.subTest(tipo=tipo):
                criar()
                with self.assertRaises((ValueError, OSError)):
                    capturar_infra(self.models, self.target, self.destino, prata=prata)
                self.assertFalse(self.destino.exists())
                for extra in ("Outra Tabela.parquet", "prata_x.csv", "prata_y.parquet"):
                    (prata / extra).unlink(missing_ok=True)
                if (prata / "sub").exists():
                    (prata / "sub").rmdir()

    def test_recusa_target_irregular(self):
        (self.target / "manifest.json").unlink()
        (self.target / "manifest.json").symlink_to(self.target / "catalog.json")
        with self.assertRaises((ValueError, OSError)):
            capturar_infra(self.models, self.target, self.destino)
        self.assertFalse(self.destino.exists())
        self.assertIn("target/manifest.json", LIMITES_INFRA)


if __name__ == "__main__":
    unittest.main()
