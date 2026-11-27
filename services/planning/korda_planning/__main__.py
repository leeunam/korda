"""Produz plano JSON no stdout ou verifica um plano existente."""

import argparse
import json
import sys
from pathlib import Path

from jsonschema.exceptions import ValidationError

from . import ContextoPendente, gerar_plano, preparar_contexto, validar_plano


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    grupo = parser.add_mutually_exclusive_group(required=True)
    grupo.add_argument("contexto", type=Path, nargs="?")
    grupo.add_argument("--validar", type=Path, metavar="PLANO")
    grupo.add_argument("--diagnosticar", type=Path, metavar="CONTEXTO",
                       help="exibe regras, evidências e perguntas para uma revisão da entrevista")
    parser.add_argument("--dataset", choices=["01_demo", "02_variacao", "03_reservada"], help="lote sintético associado pelo operador")
    parser.add_argument("--nivel-ingestao", choices=["n0", "n1"], help="n0 para arquivos ou n1 para o simulador")
    parser.add_argument("--proposta-ingestao", type=Path, help="documento JSON ingestion_plan/0.1.0 para n1")
    parser.add_argument("--ate-dia", help="data final inclusiva do replay n1, AAAA-MM-DD; o padrão é lote completo")
    parser.add_argument("--destino", help="identificador lógico do destino pretendido")
    parser.add_argument("--custo-estimado-centavos", type=int, help="estimativa proposta em centavos de BRL")
    args = parser.parse_args()
    opcoes_proposta = (args.destino, args.custo_estimado_centavos, args.dataset, args.nivel_ingestao,
                       args.proposta_ingestao, args.ate_dia)
    if (args.validar or args.diagnosticar) and any(opcao is not None for opcao in opcoes_proposta):
        parser.error("opções de proposta só podem ser usadas ao gerar um plano")
    try:
        documento = json.loads((args.validar or args.diagnosticar or args.contexto).read_text(encoding="utf-8"))
        if args.diagnosticar:
            diagnostico = preparar_contexto(documento)
            print(json.dumps(diagnostico, ensure_ascii=False, indent=2))
            return 0 if diagnostico["estado"] == "pronto" else 3
        if args.validar:
            validar_plano(documento)
            print(f"Plano válido: {documento['plan_version']}")
        else:
            proposta = None
            if args.proposta_ingestao is not None:
                proposta = json.loads(args.proposta_ingestao.read_text(encoding="utf-8"))
            janela = {"kind": "simulated_as_of", "as_of": args.ate_dia} if args.ate_dia is not None else None
            plano = gerar_plano(
                documento, destino=args.destino, custo_estimado_centavos=args.custo_estimado_centavos,
                dataset=args.dataset, nivel_ingestao=args.nivel_ingestao or "n0",
                proposta_ingestao=proposta, janela_ingestao=janela,
            )
            print(json.dumps(plano, ensure_ascii=False, indent=2))
    except ContextoPendente as exc:
        print(json.dumps(exc.diagnostico, ensure_ascii=False, indent=2), file=sys.stderr)
        return 3
    except (OSError, ValueError, ValidationError) as exc:
        print(f"Erro de planejamento: {exc.message if isinstance(exc, ValidationError) else exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
