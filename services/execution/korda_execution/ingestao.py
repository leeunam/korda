"""Ingestão de nível 0 (arquivos exportados) disparada pelo worker.

Sobe um contêiner efêmero com a imagem da sandbox e roda `python -m korda_ingestao`:

    /work/entrada   somente leitura  fontes brutas; `_gerador/` coberta por tmpfs vazio
    /work/landing   escrita          pasta temporária, renomeada para o destino no sucesso

Sem rede, sem root, sem capacidades, com limite de memória, CPU e tempo. O worker continua
só com a biblioteca padrão; duckdb e lxml ficam na imagem.

Uso (a partir de services/execution/):
    python -m korda_execution.ingestao --fontes ../../data/synthetic/output/01_demo \\
        --destino ../../data/synthetic/landing/01_demo
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

from .sandbox import IMAGEM_PADRAO, Limites, imagem_existe, montagens_ocultas, opcoes_isolamento

DIR_ENTRADA = "/work/entrada"
DIR_LANDING = "/work/landing"
TIMEOUT_PADRAO = 900
FOLGA_TIMEOUT_HOST = 15


class ErroIngestao(RuntimeError):
    """A ingestão não rodou ou terminou com erro; o destino não é criado."""


def ingerir(
    fontes: Path,
    destino: Path,
    imagem: str = IMAGEM_PADRAO,
    limites: Limites = Limites(),
    ocultar: tuple[str, ...] = ("_gerador",),
    timeout_s: int = TIMEOUT_PADRAO,
) -> dict:
    """Ingere `fontes` em `destino` (que não pode existir). Devolve manifesto e medição."""
    fontes, destino = Path(fontes).resolve(), Path(destino).resolve()
    if os.getuid() == 0:
        raise ErroIngestao("não rode o worker como root")
    if not fontes.is_dir():
        raise ErroIngestao(f"pasta de fontes não encontrada: {fontes}")
    if destino.exists():
        raise ErroIngestao(f"destino já existe: {destino}")
    if not imagem_existe(imagem):
        raise ErroIngestao(f"imagem {imagem} não encontrada; rode: docker build -t {imagem} infra/sandbox")

    id_ = uuid.uuid4().hex[:8]
    temporario = destino.parent / f".{destino.name}.tmp-{id_}"
    temporario.mkdir(parents=True)
    argv = [
        "docker", "run", "--rm",
        "--name", f"korda-ingestao-{id_}",
        *opcoes_isolamento(limites),
        "--mount", f"type=bind,src={fontes},dst={DIR_ENTRADA},readonly",
        *montagens_ocultas(fontes, DIR_ENTRADA, ocultar),
        "--mount", f"type=bind,src={temporario},dst={DIR_LANDING}",
        "--workdir", "/tmp",
        imagem,
        "timeout", "-s", "KILL", str(int(timeout_s)),
        "python", "-m", "korda_ingestao", DIR_ENTRADA, DIR_LANDING,
    ]
    inicio = time.monotonic()
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout_s + FOLGA_TIMEOUT_HOST)
    except subprocess.TimeoutExpired:
        subprocess.run(["docker", "rm", "--force", f"korda-ingestao-{id_}"], capture_output=True)
        shutil.rmtree(temporario, ignore_errors=True)
        raise ErroIngestao(f"ingestão sem resposta após {timeout_s}s") from None
    parede = round(time.monotonic() - inicio, 3)
    if r.returncode != 0:
        shutil.rmtree(temporario, ignore_errors=True)
        raise ErroIngestao(f"ingestão falhou (código {r.returncode}): {r.stderr.strip()[-2000:]}")

    temporario.rename(destino)
    manifesto = json.loads((destino / "manifesto.json").read_text(encoding="utf-8"))
    linhas = [l for l in r.stdout.splitlines() if l.strip()]
    relatorio = json.loads(linhas[-1]) if linhas else {}
    medicao = dict(relatorio.get("medicao", {}), tempo_parede_s=parede)
    return {"manifesto": manifesto, "medicao": medicao}


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingere arquivos exportados numa landing zone em Parquet.")
    parser.add_argument("--fontes", type=Path, required=True, help="pasta com erp/, tms/, cte/ ...")
    parser.add_argument("--destino", type=Path, required=True, help="pasta da landing (não pode existir)")
    parser.add_argument("--imagem", default=IMAGEM_PADRAO)
    args = parser.parse_args()
    try:
        resultado = ingerir(args.fontes, args.destino, imagem=args.imagem)
    except ErroIngestao as e:
        print(f"erro: {e}", file=sys.stderr)
        return 1
    m = resultado["manifesto"]
    for nome, t in m["tabelas"].items():
        print(f"{nome}: {t['linhas']} linhas")
    print(f"rejeitados: {m['rejeitados']['linhas']}")
    print(f"medição: {json.dumps(resultado['medicao'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
