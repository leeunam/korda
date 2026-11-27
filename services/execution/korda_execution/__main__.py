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
from .entrega import empacotar
from .sandbox import ErroSandbox, RAIZ_REPO
from .harness.cliente_chat import ErroLLM
from .harness.config import ErroConfiguracao
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
    planejar = sub.add_parser("planejar", help="gerar o plano de construção (1 chamada à API) antes da aprovação 1")
    planejar.add_argument("plano", type=Path, help="plano base gerado pelo korda_planning")
    planejar.add_argument("--contexto", type=Path, required=True,
                          help="contexto validado das entrevistas (contrato context v0.1.0) que originou o plano")
    planejar.add_argument("--saida", type=Path, help="onde gravar o plano com a construção, para registrar")
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
    sub.add_parser("empacotar", help="(re)montar o pacote de entrega de uma execução avaliada").add_argument("run_id")
    promover = sub.add_parser("promover", help="publicar o pacote de entrega no destino local autorizado")
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
        elif args.comando == "planejar":
            from .planejamento import planejar as gerar
            plano = json.loads(args.plano.read_text(encoding="utf-8"))
            contexto = json.loads(args.contexto.read_text(encoding="utf-8"))
            resultado = gerar(plano, contexto, raiz=raiz)
            if resultado["estado"] == "pronto" and args.saida:
                args.saida.write_text(json.dumps(resultado["plano"], ensure_ascii=False, indent=2) + "\n",
                                      encoding="utf-8")
            resumo = {k: v for k, v in resultado.items() if k != "plano"}
            if resultado["estado"] == "pronto":
                resumo["plan_version"] = resultado["plano"]["plan_version"]
            print(json.dumps(resumo, ensure_ascii=False, indent=2))
            return 0 if resultado["estado"] == "pronto" else 3
        elif args.comando == "decidir-plano":
            resultado = registro.decidir_plano(args.projeto, args.versao, args.pessoa, args.decisao == "aprovar")
        elif args.comando == "decidir-entrega":
            resultado = registro.decidir_entrega(args.run_id, args.pessoa, args.decisao == "aprovar")
        elif args.comando == "empacotar":
            resultado = {"pacote": str(empacotar(registro, raiz, args.run_id))}
        elif args.comando == "promover":
            resultado = {"destino": str(entregar(registro, raiz, args.run_id, args.destino))}
        else:
            resultado = registro.consultar(args.run_id)
        print(json.dumps(resultado, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, ErroSandbox, ValidationError, sqlite3.Error, subprocess.SubprocessError,
            ErroConfiguracao, ErroLLM) as exc:
        print(f"Operação interrompida: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
