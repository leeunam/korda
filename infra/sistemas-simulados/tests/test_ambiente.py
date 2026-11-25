"""Integração (host + Docker): o ambiente simulado serve exatamente as fontes geradas.

O avaliador (este teste) lê `_gerador/contagens.json` e os arquivos brutos; os sistemas
simulados não. Precisa das imagens (`docker build -t korda-simulados:dev infra/sistemas-simulados`
e `docker pull postgres:17.6-alpine`) e das fontes geradas de 01_demo e 02_variacao.
Sem isso os testes são pulados; `KORDA_EXIGIR_DOCKER=1` transforma o pulo em falha.

Rodar a partir da raiz:
    PYTHONPATH=infra/sistemas-simulados python3 -m unittest discover -s infra/sistemas-simulados/tests
"""

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from korda_simulados.controle import IMAGEM_PG, RAIZ_REPO, AmbienteSimulado, ErroSimulado, imagens_disponiveis

SAIDA = RAIZ_REPO / "data" / "synthetic" / "output"
EXIGIR = os.environ.get("KORDA_EXIGIR_DOCKER") == "1"
_PRONTO = imagens_disponiveis()
if not _PRONTO and EXIGIR:
    raise RuntimeError("KORDA_EXIGIR_DOCKER=1, mas as imagens do ambiente simulado não estão disponíveis")

# Cliente mínimo que roda DENTRO da rede interna: pagina um recurso e devolve contagem e chaves.
CLIENTE = r'''
import json, os, sys, socket, urllib.request, urllib.error
u, t = os.environ["U"], os.environ["T"]
def get(p, token=True):
    rq = urllib.request.Request(u + p, headers={"Authorization": "Bearer " + t} if token else {})
    try:
        with urllib.request.urlopen(rq, timeout=10) as r: return r.status, json.load(r)
    except urllib.error.HTTPError as e: return e.code, json.load(e)
out = {"sem_token": get("/entregas", token=False)[0], "recursos": {}}
for rec in ("veiculos", "viagens", "entregas"):
    regs, pag = [], 1
    while pag:
        s, b = get(f"/{rec}?tamanho=500&pagina={pag}" + os.environ.get("Q", ""))
        assert s == 200, (s, b)
        regs += b["dados"]; pag = b["proxima_pagina"]
    out["recursos"][rec] = {"n": len(regs), "colunas": sorted({k for r in regs for k in r})}
try:
    socket.create_connection(("1.1.1.1", 443), timeout=3); out["internet"] = True
except OSError:
    out["internet"] = False
print(json.dumps(out))
'''


class _BaseAmbiente:
    empresa = ""

    @classmethod
    def setUpClass(cls):
        cls.bruto = SAIDA / cls.empresa
        if not (cls.bruto / "_gerador" / "contagens.json").is_file():
            if EXIGIR:
                raise RuntimeError(f"fontes de {cls.empresa} não geradas")
            raise unittest.SkipTest(f"fontes de {cls.empresa} não geradas")
        cls.contagens = json.loads((cls.bruto / "_gerador" / "contagens.json").read_text(encoding="utf-8"))
        cls.tmp = Path(tempfile.mkdtemp(prefix=f"korda-sim-{cls.empresa}-"))
        cls.amb = AmbienteSimulado(cls.empresa, raiz_runs=cls.tmp).subir()
        cls.cred = cls.amb.credenciais

    @classmethod
    def tearDownClass(cls):
        cls.amb.destruir()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def psql(self, sql, usuario="leitura"):
        c = self.cred["erp"]
        url = f"postgresql://{c['usuario']}:{c['senha']}@erp:5432/{c['banco']}"
        r = self.amb.executar_na_rede(["psql", url, "-At", "-c", sql], imagem=IMAGEM_PG)
        return r.returncode, r.stdout.decode().strip(), r.stderr.decode().strip()

    def cliente(self, consulta=""):
        r = self.amb.executar_na_rede(["python", "-c", CLIENTE],
                                      env={"U": self.cred["tms"]["url"], "T": self.cred["tms"]["token"], "Q": consulta})
        self.assertEqual(r.returncode, 0, r.stderr.decode()[-2000:])
        return json.loads(r.stdout)

    def esperado_ate(self, sistema, tabela, dia):
        return sum(n for d, n in self.amb.catalogo["contagens"][sistema][tabela].items() if d <= dia)

    def ctes_entregues(self):
        return sorted(p for p in Path(self.cred["cte"]["pasta_host"]).rglob("*.xml"))

    # Os testes rodam em ordem alfabética: test_1_* antes do avanço, test_2_* depois.

    def test_1_replay_comeca_sem_o_ultimo_dia(self):
        dias = self.amb.catalogo["dias"]
        self.assertEqual(self.amb.dia_atual, dias[-2])
        self.assertEqual(self.amb.dias_restantes, dias[-1:])
        _, n, _ = self.psql('select count(*) from "erp_pedidos"')
        self.assertEqual(int(n), self.esperado_ate("erp", "erp_pedidos", dias[-2]))
        self.assertLess(int(n), self.contagens["tabelas"]["erp_pedidos"])

    def test_1_usuario_do_erp_so_le(self):
        codigo, _, erro = self.psql('delete from "erp_clientes"')
        self.assertNotEqual(codigo, 0)
        self.assertIn("read-only", erro)
        codigo, _, erro = self.psql("create table invasao (x int)")
        self.assertNotEqual(codigo, 0)

    def test_1_api_exige_token_e_rede_nao_tem_internet(self):
        out = self.cliente()
        self.assertEqual(out["sem_token"], 401)
        self.assertFalse(out["internet"])

    def test_2_depois_do_avanco_tudo_bate_com_as_fontes(self):
        if self.amb.dias_restantes:
            self.amb.avancar()
        t = self.contagens["tabelas"]
        for tabela in ("erp_clientes", "erp_pedidos"):
            with self.subTest(tabela=tabela):
                self.assertEqual(int(self.psql(f'select count(*) from "{tabela}"')[1]), t[tabela])
        out = self.cliente()
        for rec, tabela in (("veiculos", "tms_veiculos"), ("viagens", "tms_viagens"), ("entregas", "tms_entregas")):
            with self.subTest(recurso=rec):
                self.assertEqual(out["recursos"][rec]["n"], t[tabela])
        xmls = self.ctes_entregues()
        self.assertEqual(len(xmls), self.contagens["ctes"]["xml_total"])
        # Byte a byte, inclusive duplicatas e eventos de cancelamento.
        for p in xmls[:50] + xmls[-50:]:
            self.assertEqual(p.read_bytes(), (self.bruto / "cte" / p.name).read_bytes())

    def test_2_incremental_traz_so_o_dia_novo_com_esquema_mudado(self):
        if self.amb.dias_restantes:
            self.amb.avancar()
        dias = self.amb.catalogo["dias"]
        out = self.cliente(f"&atualizado_desde={dias[-2]}T23:00:00-03:00")
        n = out["recursos"]["entregas"]["n"]
        self.assertEqual(n, self.amb.catalogo["contagens"]["tms"]["tms_entregas"].get(dias[-1], 0))
        mud = self.amb.catalogo["mudanca_esquema"]
        if n:
            self.assertIn(mud["novo_nome"], out["recursos"]["entregas"]["colunas"])
            self.assertNotIn(mud["coluna"], out["recursos"]["entregas"]["colunas"])

    def test_3_ambiente_nao_ve_gerador(self):
        cat = json.dumps(self.amb.catalogo)
        self.assertNotIn("anomalias_plantadas", cat)
        self.assertFalse(any("_gerador" in p.as_posix() for p in self.amb.dir.rglob("*")))


@unittest.skipUnless(_PRONTO, "imagens do ambiente simulado indisponíveis")
class TestAmbiente01Demo(_BaseAmbiente, unittest.TestCase):
    empresa = "01_demo"


@unittest.skipUnless(_PRONTO, "imagens do ambiente simulado indisponíveis")
class TestAmbiente02Variacao(_BaseAmbiente, unittest.TestCase):
    empresa = "02_variacao"


@unittest.skipUnless(_PRONTO, "imagens do ambiente simulado indisponíveis")
class TestGuardas(unittest.TestCase):
    def test_03_reservada_exige_permissao_explicita(self):
        with self.assertRaises(ErroSimulado):
            AmbienteSimulado("03_reservada")

    def test_destruir_remove_conteineres_rede_e_diretorio(self):
        if not (SAIDA / "02_variacao" / "cte").is_dir():
            self.skipTest("fontes de 02_variacao não geradas")
        with tempfile.TemporaryDirectory() as t:
            amb = AmbienteSimulado("02_variacao", raiz_runs=Path(t), dias_iniciais=1).subir()
            nomes = (amb.c_erp, amb.c_tms, amb.rede)
            amb.destruir()
            import subprocess
            for nome in nomes:
                self.assertNotEqual(subprocess.run(["docker", "inspect", nome], capture_output=True).returncode, 0)
            self.assertFalse(amb.dir.exists())


if __name__ == "__main__":
    unittest.main()
