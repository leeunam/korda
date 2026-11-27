"""API privada de operação. Inicie na raiz com python -m services.execution.korda_execution.operador_http."""

import hmac
import json
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .aprovacoes import ErroAprovacao
from .operador import ARQUIVOS, MAX_CONTEXTO, ErroOperador, FonteEntrevista, Operador, _arquivo

MAX_PEDIDO = 16 * 1024
TIPOS = {"csv": "text/csv; charset=utf-8", "json": "application/json", "zip": "application/zip"}


def _objeto(pares):
    objeto = dict(pares)
    if len(objeto) != len(pares):
        raise ValueError("campo repetido")
    return objeto


class Handler(BaseHTTPRequestHandler):
    server_version = "Korda"
    sys_version = ""

    def setup(self):
        self.request.settimeout(12)
        super().setup()

    def log_message(self, *args):
        # O caminho e os cabeçalhos podem conter identificadores da entrevista.
        pass

    def _json(self, status, objeto):
        saida = json.dumps(objeto, ensure_ascii=False, allow_nan=False).encode()
        self._enviar(status, saida, "application/json; charset=utf-8")

    def _enviar(self, status, dados, tipo, nome=None):
        self.send_response(status)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(dados)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if nome:
            self.send_header("Content-Disposition", f'attachment; filename="{nome}"')
        self.end_headers()
        self.wfile.write(dados)

    def _corpo(self):
        tamanhos = self.headers.get_all("Content-Length") or []
        if (self.headers.get("Transfer-Encoding") or len(tamanhos) != 1
                or not re.fullmatch(r"[0-9]{1,8}", tamanhos[0])):
            raise ErroOperador(400, "Informe o tamanho do pedido JSON.")
        if self.headers.get_content_type() != "application/json":
            raise ErroOperador(415, "Envie o pedido como application/json.")
        tamanho = int(tamanhos[0])
        if tamanho > MAX_PEDIDO:
            raise ErroOperador(413, "Pedido acima do limite.")
        try:
            corpo = self.rfile.read(tamanho)
            if len(corpo) != tamanho:
                raise ValueError("pedido incompleto")
            return json.loads(corpo.decode("utf-8"), object_pairs_hook=_objeto)
        except (ValueError, RecursionError):
            raise ErroOperador(400, "Pedido JSON inválido.") from None

    def _atender(self):
        try:
            credenciais = self.headers.get_all("Authorization") or []
            if len(credenciais) != 1 or not hmac.compare_digest(
                credenciais[0].encode(), b"Bearer " + self.server.token
            ):
                raise ErroOperador(401, "Credencial do operador inválida.")
            op = self.server.operador
            url = urlsplit(self.path)
            partes = url.path.split("/")
            if (url.scheme or url.netloc or url.fragment or partes[:4] != ["", "v1", "projetos", op.projeto]
                    or (url.query and partes[4:] != ["fonte"])):
                raise ErroOperador(404, "Recurso desconhecido.")
            rota = partes[4:]
            if self.command == "GET":
                if not rota:
                    return self._json(200, op.estado())
                if rota == ["fonte"]:
                    revisao = None
                    if url.query:
                        q = parse_qs(url.query, keep_blank_values=True)
                        if set(q) != {"revision"} or len(q["revision"]) != 1 or not re.fullmatch(r"(?:0|[1-9][0-9]{0,12})", q["revision"][0]):
                            raise ErroOperador(400, "Informe uma revisão numérica.")
                        revisao = int(q["revision"][0])
                    return self._json(200, op.fonte_atual(revisao))
                if len(rota) == 4 and rota[0] == "runs" and rota[2] == "arquivos" and rota[3] in ARQUIVOS:
                    nome = rota[3]
                    dados = op.baixar(rota[1], nome)
                    return self._enviar(200, dados, TIPOS[nome.split(".")[-1]], nome)
            elif len(rota) == 1 and not url.query:
                return self._json(200, op.acao(rota[0], self._corpo()))
            raise ErroOperador(404, "Recurso desconhecido.")
        except ErroOperador as erro:
            self._json(erro.status, {"error": str(erro)})
        except ErroAprovacao as erro:
            self._json(409, {"error": str(erro)})
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            self.close_connection = True
        except (ValueError, OSError):
            self._json(409, {"error": "Falha de validação ou integridade ao processar a operação."})
        except Exception:
            self._json(500, {"error": "Não foi possível concluir a operação no servidor local."})

    do_GET = _atender
    do_POST = _atender


def main():
    env = os.environ
    repo = Path(__file__).resolve().parents[3]
    token = env.get("KORDA_OPERADOR_TOKEN", "")
    if not re.fullmatch(r"[!-~]{32,512}", token):
        raise SystemExit("Configure KORDA_OPERADOR_TOKEN com ao menos 32 caracteres ASCII visíveis.")
    porta = int(env.get("KORDA_OPERADOR_PORTA", "8790"))
    if not 1 <= porta <= 65535:
        raise SystemExit("Porta do operador fora do intervalo permitido.")
    projeto = env.get("KORDA_OPERADOR_PROJETO", "")
    if not projeto:
        raise SystemExit("Configure KORDA_OPERADOR_PROJETO com o identificador da entrevista.")
    fonte = FonteEntrevista(exports=env.get("KORDA_OPERADOR_EXPORTS"), url=env.get("KORDA_OPERADOR_CONTEXTO_URL"),
                            token=env.get("KORDA_OPERADOR_CONTEXTO_TOKEN"))
    proposta = None
    if arquivo := env.get("KORDA_OPERADOR_PROPOSTA_N1"):
        caminho = Path(arquivo)
        proposta = json.loads(_arquivo(caminho.parent, caminho.name, MAX_CONTEXTO))
    op = Operador(projeto, raiz=env.get("KORDA_OPERADOR_RAIZ", repo / "runs/operador"),
                  fontes=env.get("KORDA_OPERADOR_FONTES", repo / "data/synthetic/output/01_demo"),
                  destino=env.get("KORDA_OPERADOR_DESTINO", "painel-demo"), fonte=fonte, proposta=proposta)
    try:
        with ThreadingHTTPServer(("127.0.0.1", porta), Handler) as servidor:
            servidor.operador, servidor.token = op, token.encode()
            try:
                servidor.serve_forever()
            except KeyboardInterrupt:
                pass
    finally:
        op.fechar()


if __name__ == "__main__":
    main()
