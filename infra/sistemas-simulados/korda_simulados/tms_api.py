"""API HTTP do TMS simulado (só biblioteca padrão).

    GET /saude                                  sem autenticação
    GET /api/v1/<recurso>?pagina=1&tamanho=200&atualizado_desde=<ISO 8601>
        Authorization: Bearer <token>

Recursos: `veiculos`, `viagens`, `entregas`. Serve só os registros dos dias já liberados pelo
replay (`estado.json`). Ordem estável por (`atualizado_em`, chave). `atualizado_desde` é
exclusivo (registros com `atualizado_em` maior que o valor).

Comportamentos de um sistema real, configuráveis por variável de ambiente:
- KORDA_SIM_TOKEN         token aceito (obrigatório; sem ele o servidor não sobe)
- KORDA_SIM_LIMITE_RPS    requisições por segundo antes de 429 + Retry-After (padrão 20; 0 desliga)
- KORDA_SIM_TAMANHO_MAX   tamanho máximo de página (padrão 500)
- KORDA_SIM_FALHAS        JSON: {"sequencia": {"3": "500", "5": "429", "7": "timeout"}, "taxa_500": 0.0,
                          "taxa_timeout": 0.0, "semente": 1, "atraso_timeout_s": 30}
  A sequência usa o número da requisição de dados (1, 2, ...), contando só as autenticadas.
- Mudança de esquema: do dia `a_partir_de` em diante, a coluna do catálogo sai com o novo nome.

Dados sintéticos; sistema simulado, não é conector real.
"""

from __future__ import annotations

import datetime as dt
import hmac
import json
import os
import random
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

TAMANHO_PADRAO = 200


class Servico:
    def __init__(self, dados: Path, estado: Path, token: str, limite_rps: int = 20, tamanho_max: int = 500,
                 falhas: dict | None = None, registrar_acesso: bool = True) -> None:
        if not token:
            raise ValueError("KORDA_SIM_TOKEN vazio")
        self.dados = dados
        self.estado = estado
        self.token = token
        self.limite_rps = limite_rps
        self.tamanho_max = tamanho_max
        self.falhas = falhas or {}
        self.registrar_acesso = registrar_acesso
        self.rng = random.Random(self.falhas.get("semente", 1))
        self.catalogo = json.loads((dados / "catalogo.json").read_text(encoding="utf-8"))
        self.por_recurso = {v["recurso"]: (t, v) for t, v in self.catalogo["tms"].items()}
        self.trava = threading.Lock()
        self.contador = 0
        self.janela = (0, 0)  # (segundo, requisições nesse segundo)
        self._cache: dict[tuple[str, str], list[dict]] = {}

    def dia_atual(self) -> str | None:
        try:
            return json.loads(self.estado.read_text(encoding="utf-8"))["dia_atual"]
        except (OSError, ValueError, KeyError):
            return None

    def _dia(self, tabela: str, dia: str) -> list[dict]:
        chave = (tabela, dia)
        if chave not in self._cache:
            arq = self.dados / "dias" / dia / "tms" / f"{tabela}.jsonl"
            self._cache[chave] = ([json.loads(l) for l in arq.read_text(encoding="utf-8").splitlines() if l]
                                  if arq.is_file() else [])
        return self._cache[chave]

    def registros(self, tabela: str, desde: dt.datetime | None) -> list[dict]:
        atual = self.dia_atual()
        if atual is None:
            return []
        campo = self.catalogo["campo_atualizacao"]
        chave = self.catalogo["tms"][tabela]["chave"]
        saida = []
        for dia in self.catalogo["dias"]:
            if dia > atual:
                break
            for r in self._dia(tabela, dia):
                if desde is None or dt.datetime.fromisoformat(r[campo]) > desde:
                    saida.append(r)
        # Chave numérica ordena como número; texto como texto (ids do TMS podem ser 'V01').
        saida.sort(key=lambda r: (r[campo], (0, r[chave], "") if isinstance(r[chave], int) else (1, 0, str(r[chave]))))
        mudanca = self.catalogo.get("mudanca_esquema")
        if mudanca and mudanca["tabela"] == tabela and atual >= mudanca["a_partir_de"]:
            de, para = mudanca["coluna"], mudanca["novo_nome"]
            saida = [{(para if k == de else k): v for k, v in r.items()} for r in saida]
        return saida

    def autorizado(self, cabecalho: str | None) -> bool:
        if not cabecalho or not cabecalho.startswith("Bearer "):
            return False
        return hmac.compare_digest(cabecalho[len("Bearer "):].encode(), self.token.encode())

    def proxima_requisicao(self) -> tuple[int, bool]:
        """(número da requisição de dados, estourou o limite de taxa?)"""
        with self.trava:
            self.contador += 1
            agora = int(time.monotonic())
            seg, n = self.janela
            n = n + 1 if seg == agora else 1
            self.janela = (agora, n)
            return self.contador, bool(self.limite_rps) and n > self.limite_rps

    def falha_para(self, numero: int) -> str | None:
        seq = self.falhas.get("sequencia", {})
        if str(numero) in seq:
            return seq[str(numero)]
        with self.trava:
            sorteio = self.rng.random()
        if sorteio < self.falhas.get("taxa_500", 0.0):
            return "500"
        if sorteio < self.falhas.get("taxa_500", 0.0) + self.falhas.get("taxa_timeout", 0.0):
            return "timeout"
        return None


def criar_handler(servico: Servico):
    class Handler(BaseHTTPRequestHandler):
        server_version = "korda-tms-simulado/0.1"
        protocol_version = "HTTP/1.1"

        def log_message(self, formato, *args):  # registro de acesso no stderr (docker logs)
            if servico.registrar_acesso:
                sys.stderr.write("tms-simulado %s\n" % (formato % args))

        def _json(self, codigo: int, corpo: dict, cabecalhos: dict | None = None) -> None:
            dados = json.dumps(corpo, ensure_ascii=False).encode("utf-8")
            self.send_response(codigo)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(dados)))
            for k, v in (cabecalhos or {}).items():
                self.send_header(k, v)
            self.end_headers()
            try:
                self.wfile.write(dados)
            except (BrokenPipeError, ConnectionResetError):
                pass  # o cliente desistiu (ex.: timeout simulado); não é erro do servidor

        def do_GET(self):  # noqa: N802 - nome exigido pelo http.server
            url = urlsplit(self.path)
            if url.path == "/saude":
                return self._json(200, {"ok": True, "dia_atual": servico.dia_atual()})
            partes = url.path.strip("/").split("/")
            if len(partes) != 3 or partes[:2] != ["api", "v1"] or partes[2] not in servico.por_recurso:
                return self._json(404, {"erro": "recurso desconhecido", "recursos": sorted(servico.por_recurso)})
            if not servico.autorizado(self.headers.get("Authorization")):
                return self._json(401, {"erro": "token ausente ou inválido"}, {"WWW-Authenticate": "Bearer"})
            numero, excedeu = servico.proxima_requisicao()
            if excedeu:
                return self._json(429, {"erro": "limite de requisições excedido"}, {"Retry-After": "1"})
            falha = servico.falha_para(numero)
            if falha == "429":
                return self._json(429, {"erro": "limite de requisições simulado", "requisicao": numero},
                                  {"Retry-After": "1"})
            if falha == "500":
                return self._json(500, {"erro": "falha interna simulada", "requisicao": numero})
            if falha == "timeout":
                time.sleep(float(servico.falhas.get("atraso_timeout_s", 30)))
                return self._json(504, {"erro": "tempo esgotado simulado", "requisicao": numero})

            q = parse_qs(url.query)
            try:
                pagina = int(q.get("pagina", ["1"])[0])
                tamanho = int(q.get("tamanho", [str(TAMANHO_PADRAO)])[0])
                desde_txt = q.get("atualizado_desde", [None])[0]
                desde = dt.datetime.fromisoformat(desde_txt) if desde_txt else None
                if pagina < 1 or not 1 <= tamanho <= servico.tamanho_max:
                    raise ValueError
                if desde is not None and desde.tzinfo is None:
                    raise ValueError("atualizado_desde precisa de fuso")
            except ValueError:
                return self._json(400, {"erro": "parâmetros inválidos",
                                        "esperado": f"pagina>=1, 1<=tamanho<={servico.tamanho_max}, "
                                                    "atualizado_desde ISO 8601 com fuso"})
            tabela, _ = servico.por_recurso[partes[2]]
            regs = servico.registros(tabela, desde)
            inicio = (pagina - 1) * tamanho
            fatia = regs[inicio:inicio + tamanho]
            return self._json(200, {
                "dados": fatia,
                "pagina": pagina,
                "tamanho": tamanho,
                "total": len(regs),
                "proxima_pagina": pagina + 1 if inicio + tamanho < len(regs) else None,
            })

    return Handler


def main() -> int:
    servico = Servico(
        dados=Path(os.environ.get("KORDA_SIM_DADOS", "/dados")),
        estado=Path(os.environ.get("KORDA_SIM_ESTADO", "/estado/estado.json")),
        token=os.environ.get("KORDA_SIM_TOKEN", ""),
        limite_rps=int(os.environ.get("KORDA_SIM_LIMITE_RPS", "20")),
        tamanho_max=int(os.environ.get("KORDA_SIM_TAMANHO_MAX", "500")),
        falhas=json.loads(os.environ.get("KORDA_SIM_FALHAS") or "{}"),
    )
    porta = int(os.environ.get("KORDA_SIM_PORTA", "8080"))
    httpd = ThreadingHTTPServer(("0.0.0.0", porta), criar_handler(servico))
    httpd.daemon_threads = True
    print(f"tms simulado na porta {porta}", file=sys.stderr)
    httpd.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
