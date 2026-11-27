"""Adaptador PROVISÓRIO: eventos do worker → RunEvent do front (apps/web, events.schema.json).

O worker emite steps em português (`plano`, `modelos`, `construcao`), `dados`
e `attempt` até 4. O front espera steps `plan…deliver`, `data` e `attempt` de
1 a 3. Este módulo é o único ponto de contato entre os dois. O mapeamento não
resolve a divergência (K01 e P4 decidem): eventos sem tradução são contados
em `nao_mapeados` e ficam fora da exportação.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

MAPA: dict[tuple[str, str], tuple[str, str]] = {
    ("plano", "run_started"): ("plan", "task_started"),
    ("modelos", "test_failed"): ("run_dbt", "test_failed"),
    ("modelos", "test_passed"): ("run_dbt", "test_passed"),
    ("modelos", "fix_started"): ("agent", "task_started"),
    ("modelos", "fix_applied"): ("agent", "fix_applied"),
    ("construcao", "build_started"): ("agent", "task_started"),
    ("construcao", "file_written"): ("agent", "file_written"),
    # Só recusas de escrita ou do hook; ver _recusa_de_escrita.
    ("construcao", "tool_refused"): ("write_hook", "write_blocked"),
}
CAMPOS_CUSTO = ("custo_total_centavos", "orcamento_centavos", "custo_estimado")
NOTA = ("Exportado de eventos.jsonl do worker pelo adaptador provisório "
        "(services/execution/korda_execution/harness/adaptador_eventos.py); contrato pendente da K01.")


def _recusa_de_escrita(dados: dict) -> bool:
    return dados.get("ferramenta") == "escrever_modelo" or dados.get("origem") == "hook"


def traduzir(ev: dict) -> dict | None:
    chave = (ev.get("step"), ev.get("type"))
    dados = dict(ev.get("dados") or {})
    if chave not in MAPA:
        return None
    if chave == ("construcao", "tool_refused") and not _recusa_de_escrita(dados):
        return None
    step, tipo = MAPA[chave]
    if "caminho" in dados:
        dados["file"] = dados.pop("caminho")
    attempt = ev.get("attempt")
    if not (type(attempt) is int and 1 <= attempt <= 3):
        if attempt is not None:
            dados["attempt_original"] = attempt
        attempt = None
    saida = {"run_id": ev["run_id"], "step": step, "type": tipo, "message": str(ev.get("message", "")),
             "attempt": attempt, "ts": ev["ts"]}
    if dados:
        saida["data"] = dados
    return saida


def exportar_execucao(jsonl: Path, *, synthetic: bool) -> dict:
    linhas = [json.loads(l) for l in Path(jsonl).read_text(encoding="utf-8").splitlines() if l.strip()]
    if not linhas:
        raise ValueError(f"nenhum evento em {jsonl}")
    eventos, nao_mapeados = [], Counter()
    custo: dict | None = None
    for ev in linhas:
        dados = ev.get("dados") or {}
        if "custo_total_centavos" in dados:
            # Custo acumulado (estimado) mais recente: segue nos eventos seguintes para o front.
            custo = {k: dados[k] for k in CAMPOS_CUSTO if k in dados}
        traduzido = traduzir(ev)
        if traduzido is None:
            nao_mapeados[f"{ev.get('step')}/{ev.get('type')}"] += 1
            continue
        if custo:
            traduzido["data"] = {**traduzido.get("data", {}), **custo}
        eventos.append(traduzido)
    return {"run_id": linhas[0]["run_id"], "synthetic": synthetic, "note": NOTA, "custo": custo, "events": eventos,
            "nao_mapeados": dict(sorted(nao_mapeados.items()))}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Traduz eventos.jsonl do worker para o formato do front.")
    parser.add_argument("eventos", type=Path)
    parser.add_argument("--synthetic", action="store_true", help="marca a execução como sintética")
    args = parser.parse_args(argv)
    json.dump(exportar_execucao(args.eventos, synthetic=args.synthetic), sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
