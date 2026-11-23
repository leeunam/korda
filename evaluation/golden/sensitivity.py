"""Checagem de sensibilidade: cada correção precisa mover o KPI que ela protege.

Uso:
    .venv/bin/python evaluation/golden/sensitivity.py --all

Para cada correção aplicável, recalcula os KPIs com ela DESLIGADA (comportamento
ingênuo explícito em compute_golden.compute) e compara com o gabarito correto.
Falha (código 1) se |diferença| < tolerância do empresa.yaml. Uma correção que não
muda o resultado indica que a anomalia plantada é fraca demais para testar o agente.
Grava evaluation/golden/<empresa>/sensibilidade.json.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import compute_golden as cg  # noqa: E402

# correção -> (KPI checado, descrição do comportamento ingênuo)
CHECKS = {
    "deduplicar_cte": ("custo_frete_por_entrega", "soma os XML duplicados"),
    "excluir_cancelados": ("custo_frete_por_entrega", "soma o CT-e cancelado e o substituto"),
    "ratear": ("custo_frete_por_entrega", "cada pedido recebe o vTPrest inteiro do CT-e"),
    "completude": ("otif_pct", "ignora qt_entregue < qt_itens"),
    "pontualidade": ("otif_pct", "ignora atraso"),
    "sem_data": ("otif_pct", "trata entrega sem data pela regra oposta à da empresa"),
    "datas_mistas": ("otif_pct", "só converte o formato principal; o resto conta como falha"),
    "excluir_tipos_viagem": ("custo_frete_por_entrega", "inclui viagens de tipo excluído (ex.: TRF)"),
    "excluir_tipos_viagem/otif": ("otif_pct", "inclui viagens de tipo excluído (ex.: TRF)"),
    "unidade_ocupacao": ("ocupacao_pct", "usa a outra unidade de capacidade (kg <-> m³)"),
    "sabado": ("otif_pct", "conta o sábado como dia útil no prazo"),
}


def aplicavel(correcao: str, cfg: dict) -> bool:
    regras = cfg["regras_referencia"]
    if correcao.startswith("excluir_tipos_viagem"):
        return bool(regras["excluir_tipos_viagem"])
    if correcao == "unidade_ocupacao":
        return regras["ocupacao_unidade"] == "m3"
    if correcao == "sabado":
        return cfg["pedido"]["campo_prazo"] == "prazo_dias"
    return True


def diferenca(kpi: str, correto: float, ingenuo: float, tol: dict) -> tuple[float, float, str]:
    if kpi == "custo_frete_por_entrega":
        return abs(ingenuo - correto) / correto, tol["custo_rel"], "relativa"
    limite = tol["otif_pp"] if kpi == "otif_pct" else tol["ocupacao_pp"]
    return abs(ingenuo - correto), limite, "p.p."


def check(empresa: str, fontes_dir: Path = cg.FONTES) -> tuple[bool, dict]:
    cfg = cg.load_cfg(empresa)
    fontes = cg.load_fontes(cfg, fontes_dir / empresa)
    correto = cg.compute(cfg, fontes)["kpis"]
    resultados, ok = [], True
    for nome, (kpi, descricao) in CHECKS.items():
        if not aplicavel(nome, cfg):
            continue
        correcao = nome.split("/")[0]
        ingenuo = cg.compute(cfg, fontes, frozenset({correcao}))["kpis"]
        delta, limite, tipo = diferenca(kpi, correto[kpi], ingenuo[kpi], cfg["tolerancias"])
        passou = delta >= limite
        ok = ok and passou
        resultados.append({"correcao": correcao, "kpi": kpi, "ingenuo": descricao, "correto": correto[kpi],
                           "sem_correcao": ingenuo[kpi], "diferenca": round(delta, 6), "tolerancia": limite,
                           "tipo_diferenca": tipo, "passou": passou})
    return ok, {"empresa_id": empresa, "kpis_corretos": correto, "checagens": resultados}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--empresa")
    group.add_argument("--all", action="store_true")
    parser.add_argument("--fontes", type=Path, default=cg.FONTES)
    args = parser.parse_args(argv)
    empresas = sorted(p.name for p in cg.EMPRESAS.iterdir() if (p / "empresa.yaml").is_file()) if args.all else [args.empresa]
    falhou = False
    for empresa in empresas:
        ok, rel = check(empresa, args.fontes)
        (cg.GOLDEN / empresa).mkdir(parents=True, exist_ok=True)
        (cg.GOLDEN / empresa / "sensibilidade.json").write_text(
            json.dumps(rel, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"[{'ok' if ok else 'FALHOU'}] {empresa}")
        for c in rel["checagens"]:
            marca = "ok " if c["passou"] else "XX "
            print(f"  {marca}{c['correcao']:<22} {c['kpi']:<24} {c['correto']:>10.4f} -> {c['sem_correcao']:>10.4f}"
                  f"  Δ={c['diferenca']:.4f} ({c['tipo_diferenca']}, tol {c['tolerancia']})")
        falhou = falhou or not ok
    return 1 if falhou else 0


if __name__ == "__main__":
    sys.exit(main())
