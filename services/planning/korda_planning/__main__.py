"""Produz plano JSON no stdout ou verifica um plano existente."""

import argparse
import json
import sys
from pathlib import Path

from jsonschema.exceptions import ValidationError

from . import gerar_plano, validar_plano


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    grupo = parser.add_mutually_exclusive_group(required=True)
    grupo.add_argument("contexto", type=Path, nargs="?")
    grupo.add_argument("--validar", type=Path, metavar="PLANO")
    parser.add_argument("--dataset", choices=["01_demo", "02_variacao", "03_reservada"], help="lote sintético associado pelo operador")
    parser.add_argument("--destino", help="identificador lógico do destino pretendido")
    parser.add_argument("--custo-estimado-centavos", type=int, help="estimativa proposta em centavos de BRL")
    args = parser.parse_args()
    if args.validar and (args.destino is not None or args.custo_estimado_centavos is not None or args.dataset is not None):
        parser.error("opções de proposta só podem ser usadas ao gerar um plano")
    try:
        documento = json.loads((args.validar or args.contexto).read_text(encoding="utf-8"))
        if args.validar:
            validar_plano(documento)
            print(f"Plano válido: {documento['plan_version']}")
        else:
            plano = gerar_plano(documento, destino=args.destino, custo_estimado_centavos=args.custo_estimado_centavos,
                               dataset=args.dataset)
            print(json.dumps(plano, ensure_ascii=False, indent=2))
    except (OSError, ValueError, ValidationError) as exc:
        print(f"Erro de planejamento: {exc.message if isinstance(exc, ValidationError) else exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
