"""Teste de fumaça da sandbox com fontes reais do gerador sintético.

Uso (a partir de services/execution/):
    python -m korda_execution.smoke --fontes ../../data/synthetic/output/01_demo

Cria a sandbox com o projeto dbt mínimo da fixture, roda `dbt debug`, conta as linhas de
cada CSV e os XML de CT-e montados em /work/fontes e destrói tudo no fim.
"""

from __future__ import annotations

import argparse
import sys
import uuid
from pathlib import Path

from .sandbox import IMAGEM_PADRAO, LocalDockerSandbox

FIXTURE = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "projeto_minimo"

CONTAGEM = """
import glob, os, duckdb
con = duckdb.connect()
for f in sorted(glob.glob('/work/fontes/**/*.csv', recursive=True)):
    n = con.execute("select count(*) from read_csv(?, delim=';', header=true, all_varchar=true)", [f]).fetchone()[0]
    print(f"{os.path.relpath(f, '/work/fontes')}: {n} linhas")
xml = glob.glob('/work/fontes/cte/*.xml')
print(f"cte/*.xml: {len(xml)} arquivos")
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--fontes", type=Path, required=True)
    parser.add_argument("--imagem", default=IMAGEM_PADRAO)
    args = parser.parse_args()

    run_id = f"smoke-{uuid.uuid4().hex[:8]}"
    with LocalDockerSandbox(run_id, FIXTURE, args.fontes, imagem=args.imagem) as sb:
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
