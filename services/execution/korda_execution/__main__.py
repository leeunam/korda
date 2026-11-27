"""CLI do operador da demonstração logística Korda."""

import argparse
import json
import sqlite3
import subprocess
import sys
import uuid
from pathlib import Path

from jsonschema import ValidationError

from .aprovacoes import Registro
from .artefatos import entregar
from .sandbox import ErroSandbox, RAIZ_REPO
from .worker import executar


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raiz", type=Path, default=RAIZ_REPO / "runs/worker",
                        help="diretório privado de controle e resultados no host")
    sub = parser.add_subparsers(dest="comando", required=True)
    sub.add_parser("registrar", help="submeter uma versão de plano à revisão").add_argument("plano", type=Path)
    decidir = sub.add_parser("decidir-plano", help="registrar a decisão humana da primeira revisão")
    decidir.add_argument("projeto")
    decidir.add_argument("versao")
    rodar = sub.add_parser("executar", help="processar o lote sintético da versão aprovada")
    rodar.add_argument("plano", type=Path)
    rodar.add_argument("--run-id", help="identificador novo; o padrão é aleatório")
    rodar.add_argument("--fontes", type=Path, default=RAIZ_REPO / "data/synthetic/output/01_demo",
                       help="lote de origem gerado para a transportadora 01_demo")
    sub.add_parser("consultar", help="ver estado, manifesto e histórico").add_argument("run_id")
    entrega = sub.add_parser("decidir-entrega", help="registrar a decisão humana sobre a entrega avaliada")
    entrega.add_argument("run_id")
    for decisao in (decidir, entrega):
        decisao.add_argument("decisao", choices=("aprovar", "rejeitar"))
        decisao.add_argument("--pessoa", required=True, help="identificação do operador responsável pela decisão")
    promover = sub.add_parser("promover", help="materializar os arquivos no destino local autorizado")
    promover.add_argument("run_id")
    promover.add_argument("destino")
    args = parser.parse_args(argv)
    try:
        raiz = args.raiz.resolve()
        registro = Registro(raiz / "controle")
        if args.comando in ("registrar", "executar"):
            plano = json.loads(args.plano.read_text(encoding="utf-8"))
            if args.comando == "registrar":
                resultado = registro.registrar(plano)
            else:
                run_id = args.run_id or uuid.uuid4().hex
                print(f"Execução {run_id}", file=sys.stderr, flush=True)
                resultado = executar(registro, plano, run_id, raiz=raiz,
                                     fontes=args.fontes)
        elif args.comando == "decidir-plano":
            resultado = registro.decidir_plano(args.projeto, args.versao, args.pessoa, args.decisao == "aprovar")
        elif args.comando == "decidir-entrega":
            resultado = registro.decidir_entrega(args.run_id, args.pessoa, args.decisao == "aprovar")
        elif args.comando == "promover":
            resultado = {"destino": str(entregar(registro, raiz, args.run_id, args.destino))}
        else:
            resultado = registro.consultar(args.run_id)
        print(json.dumps(resultado, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, ErroSandbox, ValidationError, sqlite3.Error, subprocess.SubprocessError) as exc:
        print(f"Operação interrompida: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
