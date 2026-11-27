"""Execução da ingestão de nível 1 pelo worker: código de ingestão + plano -> landing.

Roda um contêiner efêmero com a imagem da sandbox **só na rede interna do ambiente simulado**
(sem internet), com:

    /work/codigo          somente leitura  código de ingestão (a referência hoje; o do agente depois)
    /work/plano/...json   somente leitura  seção de ingestão do plano aprovado
    /work/entrega/cte     somente leitura  pasta de entrega de CT-e
    /work/landing         escrita          landing zone (persistente entre cargas)

As credenciais chegam como variáveis de ambiente por um --env-file temporário (0600, apagado
no fim), nunca na linha de comando nem em arquivos montados. O mesmo executor servirá ao
código gerado pelo agente (K10): basta trocar `codigo` e `modulo`.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

from .sandbox import IMAGEM_PADRAO, Limites, imagem_existe, opcoes_isolamento

REFERENCIA = Path(__file__).resolve().parents[1] / "referencia"
CODIGOS = {0: "ok", 1: "falhou", 2: "uso", 3: "escalado"}


class ErroExecucaoIngestao(RuntimeError):
    pass


def variaveis_de_ambiente(credenciais: dict) -> dict[str, str]:
    """Credenciais do ambiente simulado -> variáveis KORDA_* esperadas pelo plano."""
    erp, tms = credenciais["erp"], credenciais["tms"]
    return {
        "KORDA_ERP_HOST": erp["host"], "KORDA_ERP_PORTA": str(erp["porta"]), "KORDA_ERP_BANCO": erp["banco"],
        "KORDA_ERP_USUARIO": erp["usuario"], "KORDA_ERP_SENHA": erp["senha"],
        "KORDA_TMS_URL": tms["url"], "KORDA_TMS_TOKEN": tms["token"],
    }


def executar_ingestao(
    credenciais: dict,
    plano: Path,
    landing: Path,
    codigo: Path = REFERENCIA,
    modulo: str = "ingestao_n1",
    imagem: str = IMAGEM_PADRAO,
    limites: Limites = Limites(),
    timeout_s: int = 600,
) -> dict:
    """Roda uma carga. Devolve {codigo, situacao, saida (última linha JSON), stderr, tempo_parede_s}."""
    if os.getuid() == 0:
        raise ErroExecucaoIngestao("não rode o worker como root")
    if not imagem_existe(imagem):
        raise ErroExecucaoIngestao(f"imagem {imagem} não encontrada")
    plano, landing, codigo = Path(plano).resolve(), Path(landing).resolve(), Path(codigo).resolve()
    entrega = Path(credenciais["cte"]["pasta_host"]).resolve()
    landing.mkdir(parents=True, exist_ok=True)
    nome = f"korda-ingestao-n1-{uuid.uuid4().hex[:8]}"
    with tempfile.NamedTemporaryFile("w", prefix="korda-env-", delete=False) as f:
        os.chmod(f.name, 0o600)
        for k, v in variaveis_de_ambiente(credenciais).items():
            f.write(f"{k}={v}\n")
        env_file = f.name
    argv = [
        "docker", "run", "--rm", "--name", nome,
        *opcoes_isolamento(limites, rede=credenciais["rede"]),
        "--env-file", env_file,
        "-e", "PYTHONPATH=/work/codigo:/opt/korda", "-e", "PYTHONDONTWRITEBYTECODE=1",
        "--mount", f"type=bind,src={codigo},dst=/work/codigo,readonly",
        "--mount", f"type=bind,src={plano},dst=/work/plano/ingestao.json,readonly",
        "--mount", f"type=bind,src={entrega},dst=/work/entrega/cte,readonly",
        "--mount", f"type=bind,src={landing},dst=/work/landing",
        "--workdir", "/tmp",
        imagem, "timeout", "-s", "KILL", str(int(timeout_s)), "python", "-m", modulo,
    ]
    inicio = time.monotonic()
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout_s + 15)
    except subprocess.TimeoutExpired:
        subprocess.run(["docker", "rm", "--force", nome], capture_output=True)
        raise ErroExecucaoIngestao(f"ingestão sem resposta após {timeout_s}s") from None
    finally:
        os.unlink(env_file)
    linhas = [l for l in r.stdout.splitlines() if l.strip()]
    try:
        saida = json.loads(linhas[-1]) if linhas else {}
    except ValueError:
        saida = {}
    return {"codigo": r.returncode, "situacao": CODIGOS.get(r.returncode, "erro"), "saida": saida,
            "stderr": r.stderr[-3000:], "tempo_parede_s": round(time.monotonic() - inicio, 3)}
