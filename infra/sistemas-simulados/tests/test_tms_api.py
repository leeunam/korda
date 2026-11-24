"""API do TMS simulado, servida em 127.0.0.1 dentro do teste (só biblioteca padrão)."""

import json
import shutil
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from korda_simulados.tms_api import Servico, criar_handler

TOKEN = "token-falso-de-teste"
DIAS = ["2026-09-01", "2026-09-02", "2026-09-03"]


def _dados(raiz: Path) -> Path:
    raiz.mkdir(parents=True)
    cat = {
        "dias": DIAS, "campo_atualizacao": "atualizado_em",
        "tms": {"tms_entregas": {"recurso": "entregas", "colunas": ["id_ent", "dt_baixa"], "chave": "id_ent"}},
        "mudanca_esquema": {"sistema": "tms", "tabela": "tms_entregas", "coluna": "dt_baixa",
                            "novo_nome": "dt_baixa_v2", "a_partir_de": "2026-09-03"},
    }
    (raiz / "catalogo.json").write_text(json.dumps(cat))
    ident = 0
    for i, dia in enumerate(DIAS):
        pasta = raiz / "dias" / dia / "tms"
        pasta.mkdir(parents=True)
        linhas = []
        for _ in range(5 * (i + 1)):  # 5, 10, 15 registros
            ident += 1
            linhas.append(json.dumps({"id_ent": ident, "dt_baixa": None if ident == 3 else f"{dia} 08:00",
                                      "atualizado_em": f"{dia}T23:00:00-03:00"}))
        (pasta / "tms_entregas.jsonl").write_text("\n".join(linhas) + "\n")
    return raiz


class _Base(unittest.TestCase):
    def subir(self, **kw):
        self.servico = Servico(self.dados, self.estado, TOKEN, registrar_acesso=False, **kw)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), criar_handler(self.servico))
        self.httpd.daemon_threads = True
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.dados = _dados(self.tmp / "dados")
        self.estado = self.tmp / "estado.json"
        self.dia("2026-09-02")

    def tearDown(self):
        if hasattr(self, "httpd"):
            self.httpd.shutdown()
            self.httpd.server_close()
        shutil.rmtree(self.tmp)

    def dia(self, d):
        self.estado.write_text(json.dumps({"dia_atual": d}))

    def get(self, caminho, token=TOKEN, timeout=5):
        req = urllib.request.Request(self.base + caminho, headers={"Authorization": f"Bearer {token}"} if token else {})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, json.load(r), dict(r.headers)
        except urllib.error.HTTPError as e:
            return e.code, json.load(e), dict(e.headers)

    def paginas(self, consulta=""):
        regs, pagina = [], 1
        while pagina:
            s, b, _ = self.get(f"/api/v1/entregas?tamanho=4&pagina={pagina}{consulta}")
            self.assertEqual(s, 200, b)
            regs += b["dados"]
            pagina = b["proxima_pagina"]
        return regs


class TestTmsApi(_Base):
    def setUp(self):
        super().setUp()
        self.subir(limite_rps=0)

    def test_autenticacao(self):
        self.assertEqual(self.get("/api/v1/entregas", token=None)[0], 401)
        self.assertEqual(self.get("/api/v1/entregas", token="errado")[0], 401)
        self.assertEqual(self.get("/saude", token=None)[0], 200)
        self.assertEqual(self.get("/api/v1/nada")[0], 404)

    def test_paginacao_completa_estavel_e_so_dias_liberados(self):
        regs = self.paginas()
        self.assertEqual([r["id_ent"] for r in regs], list(range(1, 16)))
        self.assertIsNone(regs[2]["dt_baixa"])

    def test_incremental_exclusivo(self):
        regs = self.paginas("&atualizado_desde=2026-09-01T23:00:00-03:00")
        self.assertEqual([r["id_ent"] for r in regs], list(range(6, 16)))
        self.dia("2026-09-03")
        regs = self.paginas("&atualizado_desde=2026-09-02T23:00:00-03:00")
        self.assertEqual(len(regs), 15)

    def test_parametros_invalidos(self):
        for q in ("?pagina=0", "?tamanho=9999", "?atualizado_desde=ontem", "?atualizado_desde=2026-09-01T00:00:00"):
            with self.subTest(q=q):
                self.assertEqual(self.get("/api/v1/entregas" + q)[0], 400)

    def test_mudanca_de_esquema_so_a_partir_do_dia(self):
        self.assertIn("dt_baixa", self.paginas()[0])
        self.dia("2026-09-03")
        primeiro = self.paginas()[0]
        self.assertIn("dt_baixa_v2", primeiro)
        self.assertNotIn("dt_baixa", primeiro)

    def test_sem_dia_liberado_nao_serve_nada(self):
        self.estado.unlink()
        self.assertEqual(self.get("/api/v1/entregas")[1]["total"], 0)


class TestFalhas(_Base):
    def test_sequencia_de_500_e_timeout(self):
        self.subir(limite_rps=0, falhas={"sequencia": {"1": "500", "2": "timeout"}, "atraso_timeout_s": 2})
        self.assertEqual(self.get("/api/v1/entregas")[0], 500)
        with self.assertRaises(OSError):  # o cliente desiste antes da resposta
            self.get("/api/v1/entregas", timeout=0.5)
        self.assertEqual(self.get("/api/v1/entregas")[0], 200)

    def test_limite_de_taxa(self):
        self.subir(limite_rps=3)
        codigos = [self.get("/api/v1/entregas?tamanho=1") for _ in range(6)]
        if all(c[0] == 200 for c in codigos):  # virada de segundo no meio: tenta de novo
            time.sleep(0.1)
            codigos = [self.get("/api/v1/entregas?tamanho=1") for _ in range(6)]
        limitadas = [c for c in codigos if c[0] == 429]
        self.assertTrue(limitadas)
        self.assertEqual(limitadas[0][2].get("Retry-After"), "1")

    def test_taxa_de_falhas_deterministica_pela_semente(self):
        self.subir(limite_rps=0, falhas={"taxa_500": 0.5, "semente": 7})
        a = [self.get("/api/v1/entregas?tamanho=1")[0] for _ in range(10)]
        self.httpd.shutdown()
        self.httpd.server_close()
        self.subir(limite_rps=0, falhas={"taxa_500": 0.5, "semente": 7})
        b = [self.get("/api/v1/entregas?tamanho=1")[0] for _ in range(10)]
        self.assertEqual(a, b)
        self.assertIn(500, a)
        self.assertIn(200, a)


if __name__ == "__main__":
    unittest.main()
