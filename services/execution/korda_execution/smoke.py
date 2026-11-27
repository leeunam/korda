"""Teste de fumaça da ingestão e da sandbox com fontes reais do gerador sintético.

Uso (a partir de services/execution/):
    python -m korda_execution.smoke --fontes ../../data/synthetic/output/01_demo
    python -m korda_execution.smoke --landing ../../data/synthetic/landing/01_demo   # landing pronta

Com --fontes, ingere as fontes brutas numa landing temporária (runs/<run_id>-landing). Depois
cria a sandbox sobre a landing com o projeto dbt mínimo da fixture, roda `dbt debug`, conta as
linhas de cada tabela Parquet montada em /work/fontes e destrói tudo no fim.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import uuid
from pathlib import Path

from .ingestao import ErroIngestao, ingerir
from .sandbox import IMAGEM_PADRAO, RAIZ_RUNS_PADRAO, LocalDockerSandbox

FIXTURE = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "projeto_minimo"

CONTAGEM = """
import glob, os, duckdb
con = duckdb.connect()
for f in sorted(glob.glob('/work/fontes/**/*.parquet', recursive=True)):
    n = con.execute("select count(*) from read_parquet(?)", [f]).fetchone()[0]
    print(f"{os.path.relpath(f, '/work/fontes')}: {n} linhas")
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    origem = parser.add_mutually_exclusive_group(required=True)
    origem.add_argument("--fontes", type=Path, help="fontes brutas (erp/, tms/, cte/)")
    origem.add_argument("--landing", type=Path, help="landing zone já ingerida")
    parser.add_argument("--imagem", default=IMAGEM_PADRAO)
    args = parser.parse_args()

    run_id = f"smoke-{uuid.uuid4().hex[:8]}"
    landing = args.landing
    temporaria = None
    if args.fontes:
        temporaria = landing = RAIZ_RUNS_PADRAO / f"{run_id}-landing"
        try:
            r = ingerir(args.fontes, landing, imagem=args.imagem)
        except ErroIngestao as e:
            print(f"ingestão: FALHOU ({e})", file=sys.stderr)
            return 1
        print(f"ingestão: ok {json.dumps(r['medicao'])}; rejeitados: {r['manifesto']['rejeitados']['linhas']}")
    try:
        with LocalDockerSandbox(run_id, FIXTURE, landing, imagem=args.imagem) as sb:
            print(f"sandbox {sb.nome_container} criada")
            # --connection: a imagem não tem git (dbt deps exigiria rede, que a sandbox não tem).
            debug = sb.rodar_comando(["dbt", "--no-use-colors", "debug", "--connection"], timeout_s=120)
            print(f"dbt debug: {'ok' if debug.ok else 'FALHOU'} ({debug.duracao_s}s)")
            if not debug.ok:
                print(debug.stdout[-3000:], debug.stderr[-2000:], sep="\n")
                return 1
            contagem = sb.rodar_comando(["python", "-c", CONTAGEM], timeout_s=120)
            print(contagem.stdout, end="")
            if not contagem.ok:
                print(contagem.stderr, file=sys.stderr)
                return 1
        print("sandbox destruída")
    finally:
        if temporaria is not None:
            shutil.rmtree(temporaria, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
