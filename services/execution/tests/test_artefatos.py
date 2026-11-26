import hashlib
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from korda_execution.artefatos import LIMITES, capturar, entregar


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
        self.final = self.raiz / "entregas" / "demo" / "run-1"

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
        registro = RegistroTeste(capturar(self.origem, self.staging))
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
        registro = RegistroTeste(capturar(self.origem, self.staging))
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

    def test_divergencia_de_manifesto_conteudo_ou_inventario_bloqueia_promocao(self):
        manifesto = capturar(self.origem, self.staging)
        registro = RegistroTeste({"arquivos": {"invalido": {}}})
        with self.assertRaises(ValueError):
            entregar(registro, self.raiz, "run-1", "demo")
        registro.manifesto = manifesto
        (self.staging / "kpis.json").write_text("alterado")
        with self.assertRaises(ValueError):
            entregar(registro, self.raiz, "run-1", "demo")
        (self.staging / "kpis.json").write_bytes(self.conteudo["kpis.json"])
        (self.staging / "extra.log").write_text("extra")
        with self.assertRaises(ValueError):
            entregar(registro, self.raiz, "run-1", "demo")
        self.assertFalse(self.final.exists())
        (self.staging / "extra.log").unlink()
        self.final.mkdir(parents=True, exist_ok=True)
        (self.final / "preexistente").write_text("preservar")
        with self.assertRaises(ValueError):
            entregar(registro, self.raiz, "run-1", "demo")
        self.assertFalse(registro.promovido)
        self.assertEqual({p.name for p in self.final.iterdir()}, {"preexistente"})


if __name__ == "__main__":
    unittest.main()
