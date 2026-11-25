"""Aceite semântico offline para futuras saídas do organizador; somente o avaliador importa isto."""

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


contract = load_module("discovery_context_contract", ROOT / "packages/contracts/context/v0.1.0/validate.py")


def check_context(context, checkpoint, turns, previous=None):
    contract.validate_context(context)
    if context["state"] != checkpoint["state"]:
        raise ValueError("estado do contexto diverge do aceite")
    rule = context["rules"]["rateio_cte"]
    if rule["status"] != checkpoint["status"] or rule["value"] != checkpoint["value"]:
        raise ValueError("rateio diverge do aceite")
    gaps = [g for g in context["gaps"] if g["rule_key"] == "rateio_cte"]
    if len(gaps) != 1 or gaps[0]["state"] != checkpoint["gap_state"]:
        raise ValueError("lacuna de rateio diverge do aceite")
    if gaps[0]["affected_metrics"] != ["custo_frete_por_entrega"]:
        raise ValueError("rateio deve afetar somente custo")
    if context["last_processed_turn_id"] != checkpoint["after_turn_id"]:
        raise ValueError("último turno processado incorreto")
    sources = {s["id"]: s for s in context["sources"]}
    cited_turns = set()
    for evidence in context["evidence"]:
        if sources[evidence["source_id"]]["kind"] == "entrevista":
            tid = evidence["locator"]
            if tid not in turns or evidence["excerpt"] not in turns[tid].answer:
                raise ValueError("citação não corresponde à fala sintética")
            cited_turns.add(tid)
    if not set(checkpoint["required_turn_ids"]) <= cited_turns:
        raise ValueError("evidências obrigatórias ausentes")
    if rule["status"] == "confirmada":
        if rule["confirmed_by"]["role"] != "financeiro":
            raise ValueError("rateio precisa da confirmação do financeiro")
        evidence = {e["id"]: e for e in context["evidence"]}
        confirmation = checkpoint["after_turn_id"]
        if confirmation not in {"financeiro-rateio", "financeiro-correcao"}:
            confirmation = "financeiro-rateio"
        if not any(evidence[eid]["locator"] == confirmation
                   for eid in rule["evidence_ids"]):
            raise ValueError("confirmação financeira precisa estar vinculada à regra")
    if previous is not None:
        if (context["context_id"], context["project_id"]) != (previous["context_id"], previous["project_id"]):
            raise ValueError("retomada precisa preservar identidade")
        if context["revision"] <= previous["revision"]:
            raise ValueError("revisão precisa avançar")
        old_gaps = {g["id"]: g["rule_key"] for g in previous["gaps"]}
        new_gaps = {g["id"]: g["rule_key"] for g in context["gaps"]}
        if any(new_gaps.get(gid) != key for gid, key in old_gaps.items()):
            raise ValueError("identidade das lacunas precisa ser preservada")
        old_evidence = {e["id"]: e for e in previous["evidence"]}
        new_evidence = {e["id"]: e for e in context["evidence"]}
        if any(new_evidence.get(eid) != item for eid, item in old_evidence.items()):
            raise ValueError("histórico de evidências precisa ser preservado")
        for key, value in previous["rules"].items():
            if key != "rateio_cte" and context["rules"][key] != value:
                raise ValueError("confirmação de rateio não deve alterar outras regras")
