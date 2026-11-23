"""Valida o formato e as referências do contexto sintético; não aprova regras de negócio."""

import argparse
import json
from pathlib import Path

from jsonschema import Draft202012Validator

HERE = Path(__file__).resolve().parent
SCHEMA = json.loads((HERE / "context.schema.json").read_text(encoding="utf-8"))
Draft202012Validator.check_schema(SCHEMA)
VALIDATOR = Draft202012Validator(SCHEMA)
RULE_METRICS = {
    "deduplicar_cte": {"custo_frete_por_entrega"},
    "excluir_cancelados": {"custo_frete_por_entrega"},
    "rateio_cte": {"custo_frete_por_entrega"},
    "sem_data_realizada": {"otif_pct"},
    "prazo_conta_sabado": {"otif_pct"},
    "no_prazo": {"otif_pct"},
    "completo": {"otif_pct"},
    "ocupacao_unidade": {"ocupacao_pct"},
    "excluir_tipos_viagem": {"custo_frete_por_entrega", "otif_pct"},
}


def _index(rows, name):
    result = {row["id"]: row for row in rows}
    if len(result) != len(rows):
        raise ValueError(f"IDs repetidos em {name}")
    return result


def validate_context(context):
    VALIDATOR.validate(context)
    sources = _index(context["sources"], "sources")
    evidence = _index(context["evidence"], "evidence")
    _index(context["gaps"], "gaps")
    for item in evidence.values():
        if item["source_id"] not in sources:
            raise ValueError(f"fonte desconhecida: {item['source_id']}")
    links = [context["source_profile"], *context["rules"].values(), *context["gaps"]]
    for item in links:
        for eid in item["evidence_ids"]:
            if eid not in evidence:
                raise ValueError(f"evidência desconhecida: {eid}")
    if not any(e["locator"] == context["last_processed_turn_id"]
               and sources[e["source_id"]]["kind"] == "entrevista" for e in evidence.values()):
        raise ValueError("último turno processado precisa de evidência da entrevista")

    for key, rule in context["rules"].items():
        if rule["status"] == "confirmada":
            if not any(sources[evidence[eid]["source_id"]]["scope"] == "empresa" for eid in rule["evidence_ids"]):
                raise ValueError(f"referência setorial não confirma regra da empresa: {key}")
        elif not any(g["rule_key"] == key and g["state"] != "respondida" and g["blocking"]
                     for g in context["gaps"]):
            raise ValueError(f"regra pendente precisa de lacuna bloqueante: {key}")
    for gap in context["gaps"]:
        if set(gap["affected_metrics"]) != RULE_METRICS[gap["rule_key"]]:
            raise ValueError(f"indicadores da lacuna não correspondem à regra: {gap['id']}")
        rule = context["rules"][gap["rule_key"]]
        if gap["state"] == "respondida" and (rule["status"] != "confirmada"
                or not set(gap["evidence_ids"]) & set(rule["evidence_ids"])):
            raise ValueError(f"lacuna respondida exige regra confirmada e evidência vinculada: {gap['id']}")
    blocked = any(g["blocking"] and g["state"] != "respondida" for g in context["gaps"])
    pending = any(r["status"] != "confirmada" for r in context["rules"].values())
    if context["state"] == "pronto_para_planejamento" and (blocked or pending):
        raise ValueError("contexto bloqueado deve continuar como rascunho")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", type=Path, nargs="+")
    args = parser.parse_args()
    for path in args.files:
        validate_context(json.loads(path.read_text(encoding="utf-8")))
        print(f"[ok] {path.name}")


if __name__ == "__main__":
    main()
