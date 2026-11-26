"""CLI do contêiner: python -m korda_ingestao <entrada> <saida>

A última linha do stdout é um JSON com a medição (tempo e memória). A medição fica fora do
manifesto para que duas execuções sobre as mesmas fontes gerem o mesmo manifesto.
"""

from __future__ import annotations

import json
import resource
import sys
import time
from pathlib import Path

from .csv_bruto import ErroCsv
from .landing import ErroIngestao, ingerir


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2:
        print("uso: python -m korda_ingestao <entrada> <saida>", file=sys.stderr)
        return 2
    inicio = time.monotonic()
    try:
        manifesto = ingerir(Path(args[0]), Path(args[1]))
    except (ErroIngestao, ErroCsv) as e:
        print(f"ingestão recusada: {e}", file=sys.stderr)
        return 1
    uso = resource.getrusage(resource.RUSAGE_SELF)
    print(json.dumps({
        "medicao": {
            "tempo_s": round(time.monotonic() - inicio, 3),
            "cpu_s": round(uso.ru_utime + uso.ru_stime, 3),
            "memoria_max_mb": round(uso.ru_maxrss / 1024, 1),  # Linux: ru_maxrss em KiB
        },
        "totais": manifesto["totais"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
