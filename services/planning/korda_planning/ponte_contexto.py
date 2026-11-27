"""Projeção da revisão imutável da entrevista para o contrato logístico do planejador."""

import copy
import hashlib
import json
from collections import defaultdict
from functools import lru_cache

from .plano import CONTRATOS, _carregar_contrato, contrato_contexto

# São qualificadores opcionais com significado já expresso pela fórmula da demo.
COMPLEMENTARES = {
    "agregacao_ocupacao": ("ocupacao_agregacao", "rule", "soma_carga_por_viagem_dividida_pela_soma_capacidade_incluindo_vazias"),
    "restricoes_adicionais": ("restricoes", "constraint", "nenhuma_restricao_adicional"),
}

PERFIL = contrato_contexto.SCHEMA["properties"]["source_profile"]["properties"]
CAMPOS_PERFIL = tuple(chave for chave in PERFIL if chave != "evidence_ids")
REGRAS = tuple(contrato_contexto.RULE_METRICS)
CHAVES = (*REGRAS, *CAMPOS_PERFIL)


@lru_cache(maxsize=1)
def _validador_entrevista():
    # O consumidor v0.1 não exige o runtime Pydantic do backend WhatsApp.
    return _carregar_contrato("korda_context_v020", CONTRATOS / "context/v0.2.0/context.schema.json").validate


def _canonico(objeto):
    return json.dumps(objeto, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _id_revisao(documento):
    return hashlib.sha256(_canonico(documento).encode("utf-8")).hexdigest()


def _pendencia(campo, pergunta, *, claims=(), evidencias=()):
    return {
        "campo": campo, "pergunta": pergunta,
        "claim_ids": [c["id"] for c in claims],
        "evidence_ids": sorted(set(evidencias) | {e for c in claims for e in c["evidence_ids"]}),
    }


def _campos(claim):
    """Aceita nomes explícitos e o vocabulário do exemplo publicado da descoberta."""
    chave = claim["key"].strip().lower().replace(" ", "_")
    valor = claim["value"]
    if claim["kind"] in {"rule", "decision"}:
        if claim["topic"] == "frete" and chave == "rateio":
            chave = "rateio_cte"
        if chave in REGRAS:
            if chave == "rateio_cte" and valor == "peso_bruto":
                valor = "peso"
            return {chave: valor}
    if claim["kind"] in {"source", "constraint", "process", "decision"}:
        if chave in CAMPOS_PERFIL:
            return {chave: valor}
        if chave == "source_profile" and isinstance(valor, dict):
            return {k: v for k, v in valor.items() if k in CAMPOS_PERFIL}
    return {}


def _valor_compativel(chave, valor):
    if chave in CAMPOS_PERFIL:
        return valor == PERFIL[chave]["const"]
    # Reaproveita os tipos/enumerações do contrato P1 sem replicar o vocabulário.
    schema = contrato_contexto.SCHEMA["properties"]["rules"]["properties"][chave]["allOf"][1]
    return valor is not None and contrato_contexto.VALIDATOR.evolve(schema=schema).is_valid({"value": valor})


def _escolher(chave, candidatos, papeis, ordem_evidencias, topico, pergunta):
    # Os tópicos e perguntas são os mesmos usados na captura guiada da entrevista.
    claims = [c for c, _ in candidatos]
    if not claims:
        return None, _pendencia(chave, pergunta)
    if len(claims) != 1:
        return None, _pendencia(chave, "Qual afirmação vigente deve prevalecer? " + pergunta, claims=claims)
    claim, valor = candidatos[0]
    confirmacao = claim["confirmation"]
    alias_publicado = chave == "rateio_cte" and claim["topic"] == "frete" and claim["key"] == "rateio"
    papeis_permitidos = {"operacao", "dados"} if chave in CAMPOS_PERFIL else {"operacao"}
    if chave == "rateio_cte":
        papeis_permitidos = {"financeiro"}
    if not alias_publicado and claim["topic"] != topico:
        return None, _pendencia(chave, f"Confirme no tópico {topico}. " + pergunta, claims=claims)
    if (claim["state"] != "confirmada" or not confirmacao or confirmacao["role"] not in papeis_permitidos
            or papeis.get(claim["topic"]) != confirmacao["role"]):
        return None, _pendencia(chave, "Solicite confirmação explícita ao papel responsável. " + pergunta,
                                claims=claims)
    ordem_confirmacao = ordem_evidencias[confirmacao["evidence_id"]]
    if not any(ordem_evidencias[ev] < ordem_confirmacao for ev in claim["evidence_ids"]):
        return None, _pendencia(chave, "Localize a declaração e a confirmação em turnos distintos.", claims=claims)
    # Uma restrição temporal ou de unidade precisa ter representação no plano
    # antes de ser aplicada ao lote integral. Conservamos a afirmação na revisão.
    if claim["time_scope"] or (claim["unit"] and claim["unit"] != valor):
        return None, _pendencia(chave, "Esclareça a unidade ou o período de aplicação. " + pergunta, claims=claims)
    if chave in COMPLEMENTARES:
        _, tipo, esperado = COMPLEMENTARES[chave]
        compativel = claim["kind"] == tipo and valor == esperado
    else:
        compativel = _valor_compativel(chave, valor)
    if not compativel:
        return None, _pendencia(chave, "O valor declarado requer revisão do contrato da demo. " + pergunta,
                                claims=claims)
    return {
        "value": copy.deepcopy(valor), "evidence_ids": sorted(set(claim["evidence_ids"])),
        "confirmed_by": {"name": confirmacao["participant_id"], "role": confirmacao["role"]},
    }, None


def _fontes_e_evidencias(documento, digest):
    fontes, evidencias = [], []
    afirmacoes = defaultdict(list)
    for claim in documento["claims"]:
        for eid in claim["evidence_ids"]:
            afirmacoes[eid].append({
                "claim_id": claim["id"], "topic": claim["topic"], "key": claim["key"], "state": claim["state"],
                "time_scope": claim["time_scope"], "unit": claim["unit"], "source_verification": claim["source_verification"],
                "confirms": bool(claim["confirmation"] and claim["confirmation"]["evidence_id"] == eid),
            })
    for ev in documento["evidence"]:
        # Uma transcrição corrigida pode citar a mesma mídia, mas tem outro ID e
        # versão. O localizador preserva a origem e os offsets do trecho literal.
        local = {k: v for k, v in ev.items() if k not in {"id", "quote"}}
        local["claims"] = afirmacoes[ev["id"]]
        fonte = "whatsapp:" + ev["id"]
        fontes.append({"id": fonte, "kind": "entrevista", "origin": "fornecida", "scope": "empresa",
                       "version": f"whatsapp/v0.2.0:{documento['revision']}:{digest}", "locator": _canonico(local)})
        evidencias.append({"id": ev["id"], "source_id": fonte, "locator": ev["input_id"], "excerpt": ev["quote"]})
    return fontes, evidencias


def _lacunas_do_plano(documento, regras, candidatos):
    por_claim = {claim["id"]: chave for chave in regras for claim, _ in candidatos[chave]}
    lacunas = []
    for gap in documento["gaps"]:
        chaves = sorted({por_claim[cid] for cid in gap["claim_ids"] if cid in por_claim})
        for chave in chaves:
            regra = regras[chave]
            ids = list(gap["evidence_ids"])
            if gap["state"] == "respondida" and not set(ids).intersection(regra["evidence_ids"]):
                # A relação gap → claim → confirmação é explícita no contrato da entrevista.
                claim = candidatos[chave][0][0]
                ids.append(claim["confirmation"]["evidence_id"])
            # O contrato legado representa uma única regra por lacuna. Em uma
            # lacuna transversal, cada projeção conserva o ID do registro de origem.
            lacunas.append({
                "id": gap["id"] if len(chaves) == 1 else f"{gap['id']}:{chave}",
                "rule_key": chave, "state": gap["state"], "blocking": gap["blocking"],
                "affected_metrics": sorted(contrato_contexto.RULE_METRICS[chave]),
                "question": gap["question"], "responsible_role": regra["confirmed_by"]["role"],
                "evidence_ids": sorted(set(ids)),
            })
    return lacunas


def preparar_contexto(contexto):
    """Valida uma revisão e devolve sua projeção P1 ou pendências com referências de origem."""
    digest = _id_revisao(contexto)
    if contexto.get("schema_version") == "0.1.0":
        contrato_contexto.validate_context(contexto)
        gaps = copy.deepcopy(contexto["gaps"])
        return {
            "project_id": contexto["project_id"], "revision": contexto["revision"], "contexto_sha256": digest,
            "estado": "pronto" if contexto["state"] == "pronto_para_planejamento" else "pendente",
            "contexto_planejamento": copy.deepcopy(contexto), "regras": copy.deepcopy(contexto["rules"]), "lacunas": gaps,
            "pendencias": [_pendencia(g["rule_key"], g["question"], evidencias=g["evidence_ids"])
                           for g in gaps if g["blocking"] and g["state"] != "respondida"],
        }
    if contexto.get("schema_version") != "0.2.0" or contexto.get("synthetic") is not True:
        raise ValueError("a ponte exige uma revisão sintética identificada de contexto v0.1.0 ou v0.2.0")
    doc = _validador_entrevista()(contexto).model_dump(mode="json")
    from korda_context.logistics import FIELDS  # disponibilizado pelo validador oficial v0.2

    candidatos = defaultdict(list)
    pendencias = []
    for claim in doc["claims"]:
        if claim["state"] == "substituida":
            continue
        campos = _campos(claim)
        if claim["key"] in COMPLEMENTARES:
            campos[claim["key"]] = claim["value"]
        for chave, valor in campos.items():
            candidatos[chave].append((claim, valor))
        if claim["key"] == "source_profile" and (
            not campos or not isinstance(claim["value"], dict) or set(claim["value"]) - set(CAMPOS_PERFIL)
        ):
            pendencias.append(_pendencia("source_profile", "Esclareça os campos de perfil sem correspondência na demo.", claims=[claim]))
        elif not campos and claim["kind"] in {"rule", "constraint", "decision"}:
            pendencias.append(_pendencia(claim["key"], "Esclareça a qual regra ou campo do perfil esta decisão se aplica.",
                                         claims=[claim]))
    ordem_inputs = {entrada: i for i, entrada in enumerate(doc["processed_input_ids"])}
    ordem_evidencias = {e["id"]: ordem_inputs[e["input_id"]] for e in doc["evidence"]}
    regras, perfil, evidencias_perfil, vinculos = {}, {}, set(), {}
    for chave in (*CHAVES, *(k for k in COMPLEMENTARES if k in candidatos)):
        if chave in COMPLEMENTARES:
            topico = COMPLEMENTARES[chave][0]
            pergunta = "Essa condição corresponde à fórmula e aos limites aprováveis da demo?"
        else:
            topico, pergunta = FIELDS[chave].topic, FIELDS[chave].question
        item, pendencia = _escolher(chave, candidatos[chave], doc["required_topics"], ordem_evidencias, topico, pergunta)
        if pendencia:
            pendencias.append(pendencia)
        else:
            claim = candidatos[chave][0][0]
            vinculos[chave] = {"claim_id": claim["id"], "topic": claim["topic"], "evidence_ids": item["evidence_ids"],
                               "confirmation": copy.deepcopy(claim["confirmation"])}
        if chave in REGRAS:
            if item:
                regras[chave] = {"status": "confirmada", **item}
            else:
                conflito = len(candidatos[chave]) > 1 or any(c["state"] == "em_conflito" for c, _ in candidatos[chave])
                regras[chave] = {"status": "em_conflito" if conflito else "a_confirmar", "value": None,
                                 "evidence_ids": pendencia["evidence_ids"], "confirmed_by": None}
        elif item and chave in CAMPOS_PERFIL:
            perfil[chave] = item["value"]
            evidencias_perfil.update(item["evidence_ids"])
    for gap in doc["gaps"]:
        if gap["blocking"] and gap["state"] != "respondida":
            pendencias.append({"campo": gap["id"], "pergunta": gap["question"], "claim_ids": gap["claim_ids"],
                               "evidence_ids": gap["evidence_ids"]})
    if doc["state"] != "pronto" or doc["pending_input_ids"]:
        pendencias.append(_pendencia("revisao", "Quais mensagens e confirmações ainda faltam para a descoberta ficar pronta?"))
    ultimo = doc["processed_input_ids"][-1] if doc["processed_input_ids"] else None
    if doc["revision"] < 1 or not any(ev["input_id"] == ultimo for ev in doc["evidence"]):
        pendencias.append(_pendencia("ultimo_turno", "Qual evidência da entrevista documenta o último turno processado?"))
    projecao = None
    if not pendencias:
        fontes, evidencias = _fontes_e_evidencias(doc, digest)
        projecao = {
            "schema_version": "0.1.0", "project_id": doc["project_id"], "context_id": "whatsapp:" + doc["project_id"],
            "revision": doc["revision"], "synthetic": True, "state": "pronto_para_planejamento",
            "last_processed_turn_id": ultimo, "sources": fontes, "evidence": evidencias,
            "source_profile": {**perfil, "evidence_ids": sorted(evidencias_perfil)}, "rules": regras,
            "gaps": _lacunas_do_plano(doc, regras, candidatos),
        }
        contrato_contexto.validate_context(projecao)
    return {"project_id": doc["project_id"], "revision": doc["revision"], "contexto_sha256": digest,
            "estado": "pendente" if pendencias else "pronto", "contexto_planejamento": projecao,
            "regras": regras, "vinculos": vinculos, "lacunas": doc["gaps"], "pendencias": pendencias}


class ContextoPendente(ValueError):
    """A revisão é válida, mas ainda não sustenta o plano de construção."""

    def __init__(self, diagnostico):
        self.diagnostico = diagnostico
        campos = ", ".join(p["campo"] for p in diagnostico["pendencias"])
        super().__init__("confirmações ou esclarecimentos necessários para o planejamento: " + campos)
