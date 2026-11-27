"""Ensaio do painel contra a API de descoberta, o operador e o worker em Docker."""

from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import secrets
import signal
import socket
import subprocess
import sys
import tempfile
import time
from urllib.error import URLError
from urllib.request import urlopen
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "apps/web"
sys.path.insert(0, str(ROOT))
from data.synthetic.generator.generate import generate


@contextmanager
def servidor(argv, cwd, env):
    processo = subprocess.Popen(argv, cwd=cwd, env=env, start_new_session=True)
    try:
        yield processo
    finally:
        if processo.poll() is None:
            os.killpg(processo.pid, signal.SIGTERM)
            try:
                processo.wait(timeout=8)
            except subprocess.TimeoutExpired:
                os.killpg(processo.pid, signal.SIGKILL)
                processo.wait()


def aguardar(processo, porta, rota=None):
    for _ in range(120):
        if processo.poll() is not None:
            raise RuntimeError(f"Serviço da porta {porta} terminou com código {processo.returncode}")
        try:
            if rota:
                with urlopen(f"http://127.0.0.1:{porta}{rota}", timeout=2) as resposta:
                    if resposta.status == 200:
                        return
            else:
                with socket.create_connection(("127.0.0.1", porta), timeout=1):
                    return
        except (OSError, URLError):
            pass
        time.sleep(0.5)
    raise RuntimeError(f"Serviço da porta {porta} não ficou disponível")


def main():
    manifesto = Path(os.environ["KORDA_ENTREVISTA_MANIFEST"]).resolve()
    revisoes = json.loads(manifesto.read_text())
    contexto_url = os.environ.get("KORDA_ENTREVISTA_URL", "http://127.0.0.1:8091")
    porta_operador, porta_web = 8790, 3100
    with tempfile.TemporaryDirectory(prefix="korda-painel-") as temp:
        raiz = Path(temp)
        generate("01_demo", output_root=raiz / "fontes")
        operador_url = f"http://127.0.0.1:{porta_operador}"
        web_url = f"http://127.0.0.1:{porta_web}"
        token = secrets.token_urlsafe(36)
        # Só o operador recebe o token da descoberta; o navegador fala com o próprio painel.
        ambiente = {k: v for k, v in os.environ.items() if not k.startswith(("CONTEXT_", "KORDA_"))}
        operador = {**ambiente, "KORDA_OPERADOR_TOKEN": token, "KORDA_OPERADOR_PROJETO": revisoes["project_id"],
                    "KORDA_OPERADOR_CONTEXTO_URL": contexto_url, "KORDA_OPERADOR_CONTEXTO_TOKEN": os.environ["CONTEXT_PROJECT_TOKEN"],
                    "KORDA_OPERADOR_RAIZ": str(raiz / "operador"), "KORDA_OPERADOR_FONTES": str(raiz / "fontes/01_demo"),
                    "KORDA_OPERADOR_DESTINO": "entrega-ensaio", "KORDA_EXECUTOR": "roteirizado"}
        painel = {**ambiente, "KORDA_OPERADOR_URL": operador_url, "KORDA_OPERADOR_TOKEN": token,
                  "NEXT_TELEMETRY_DISABLED": "1"}
        with servidor([sys.executable, "-m", "services.execution.korda_execution.operador_http"], ROOT, operador) as backend:
            aguardar(backend, porta_operador)
            with servidor(["pnpm", "exec", "next", "start", "--hostname", "127.0.0.1", "--port", str(porta_web)],
                          WEB, painel) as web:
                aguardar(web, porta_web, "/operador")
                subprocess.run(["node", str(Path(__file__).with_name("painel-real.mjs")), web_url,
                                str(manifesto), str(raiz)], env=ambiente, check=True, timeout=540)
        observado = json.loads((raiz / "observado.json").read_text())
        with ZipFile(raiz / "pacote.zip") as pacote:
            # Pacote de entrega do entrega.py: entrega.json é o contrato para o front.
            entrega = json.loads(pacote.read("entrega.json"))
            execucao = entrega["execucao"]
            assert execucao["run_id"] == observado["run_id"]
            assert execucao["plan_version"] == observado["plan_version"]
            assert execucao["context_revision"] == revisoes["ready_revision"]
            rateio = next(r for r in entrega["regras"] if r["chave"] == "rateio_cte")
            assert rateio["papel"] == "financeiro"
            assert rateio["evidencias"]
            selado = json.loads(pacote.read("manifesto.json"))
            assert selado["run_id"] == observado["run_id"]
            for nome in ("dados/kpis.json", "dados/por_pedido.csv", "dados/por_viagem.csv",
                         "decisoes.md", "docs_dbt/manifest.json", "projeto_dbt/models/ouro_kpis.sql"):
                assert pacote.getinfo(nome).file_size > 0, nome
        print("Painel, duas decisões e pacote da execução verificados.")


if __name__ == "__main__":
    main()
