"""Mensagem, pergunta entregue e confirmação em turnos distintos, com participantes fictícios."""
import json

import pytest

from korda_context.domain import new_context
from korda_context.interview import Interviewer
from korda_context.organizer import Organizer


TOPICS = {topic: "operacao" for topic in (
    "fontes", "frete_deduplicacao", "frete_cancelamento", "frete_elegibilidade",
    "otif_prazo", "otif_completude", "otif_data_ausente", "otif_sabado", "ocupacao_unidade")}
TOPICS["frete_rateio"] = "financeiro"
PARTICIPANTS = {role: {"id": "sim-" + role, "role": role} for role in ("operacao", "financeiro")}

# Texto que um participante da empresa sintética poderia responder pelo WhatsApp.
ANSWERS = {
    "grain": ("Uma entrega por pedido.", "uma_entrega_por_pedido"),
    "quantity_unit": ("Contamos as quantidades em volumes.", "volumes"),
    "timezone": ("Usamos o horário de São Paulo.", "America/Sao_Paulo"),
    "freight_link": ("Ligamos o número do pedido da entrega ao código do pedido no ERP e a chave da nota do pedido à nota citada no CT-e.",
                     "TMS.nr_ped = ERP.cd_ped; ERP.ch_nfe = CT-e.infNFe/chave"),
    "deduplicar_cte": ("Contamos apenas uma vez por chave do CT-e.", True),
    "excluir_cancelados": ("Excluímos o CT-e cancelado.", True),
    "excluir_tipos_viagem": ("Todos os tipos de viagem entram.", []),
    "rateio_cte": ("Pelo peso expedido de cada pedido.", "peso"),
    "no_prazo": ("Entregue até o dia previsto, inclusive.", "data(dt_realizada) <= data prevista"),
    "completo": ("Quando os volumes entregues são iguais ou superiores aos volumes pedidos.", "qt_entregue >= qt_itens"),
    "sem_data_realizada": ("Conta como falha no OTIF.", "falha"),
    "prazo_conta_sabado": ("Sábado conta como dia útil.", True),
    "ocupacao_unidade": ("Comparamos o peso em quilos.", "kg"),
}


def no_model(*args):
    raise AssertionError("O fluxo de escolha explícita não precisa inferir uma resposta por LLM.")


def test_thirteen_spoken_answers_are_grounded_confirmed_and_ready_to_plan():
    interviewer, organizer = Interviewer(no_model), Organizer(no_model)
    ctx = new_context("transportadora-sintetica", TOPICS)
    for role in ("operacao", "financeiro"):
        participant = PARTICIPANTS[role]
        for _ in range(14):
            q = interviewer.choose(ctx, participant)
            if not q.capture_key:
                break
            key = q.capture_key
            text, expected = ANSWERS[key]
            assert text.rstrip(".") in q.text
            ctx = organizer.organize(ctx, "declaracao-" + key, text, participant, TOPICS, capture_key=key)
            claim = next(c for c in ctx.claims if c.key == key)
            assert claim.value == expected and claim.state == "declarada"
            challenge = interviewer.choose(ctx, participant)
            assert challenge.claim_ids == [claim.id] and challenge.capture_key is None
            assert text.rstrip(".") in challenge.text
            if role == "financeiro":
                with pytest.raises(ValueError, match="role"):
                    organizer.organize(ctx, "tentativa", "Confirmo", PARTICIPANTS["operacao"], TOPICS, challenge.claim_ids)
            ctx = organizer.organize(ctx, "confirmacao-" + key, "Confirmo", participant, TOPICS, challenge.claim_ids)
        if role == "operacao":
            assert ctx.state == "rascunho" and "financeiro" in q.text
    assert ctx.state == "pronto" and {c.key for c in ctx.claims} == ANSWERS.keys()
    evidence = {e.id: e for e in ctx.evidence}
    for c in ctx.claims:
        assert c.state == "confirmada"
        original, approval = [evidence[e] for e in c.evidence_ids]
        assert original.quote == ANSWERS[c.key][0] and original.input_id != approval.input_id
        assert approval.id == c.confirmation.evidence_id and approval.quote == "Confirmo"
        assert c.confirmation.role == TOPICS[c.topic]
        if c.topic == "fontes":
            assert c.kind == "source" and c.source_verification == "nao_inspecionada" and not c.inspected


def test_free_answer_or_uncertainty_preserves_evidence_and_does_not_assume_an_option():
    ctx = new_context("sintetica", TOPICS)
    participant = PARTICIPANTS["financeiro"]
    q = Interviewer(no_model).choose(ctx, participant)
    assert q.capture_key == "rateio_cte"
    def unknown(system, payload):
        assert json.loads(payload)["capture_key"] == "rateio_cte"
        return {"base_revision": 0}
    text = "Parece ser pelo tamanho da carga, vou confirmar com a equipe."
    ctx = Organizer(unknown).organize(ctx, "meu-relato", text, participant, TOPICS, capture_key=q.capture_key)
    assert not ctx.claims
    gap = next(g for g in ctx.gaps if g.key == "claim:rateio_cte")
    assert gap.state == "aberta" and gap.evidence_ids == [ctx.evidence[0].id]
    assert ctx.evidence[0].quote == text and Interviewer(no_model).choose(ctx, participant).capture_key == q.capture_key

    text = "Aqui o valor de cada pedido define a parte que ele paga."
    def explain(system, payload):
        data = json.loads(payload)
        assert data["current_text"] == text and data["planning_vocabulary"]["rateio_cte"]["kind"] == "rule"
        return {"base_revision": 1, "claims": [{"topic": "frete_rateio", "key": "rateio_cte", "ref": "r",
            "value": "valor", "kind": "rule", "statement": "interpretação proposta", "quote": text}]}
    ctx = Organizer(explain).organize(ctx, "relato-explicado", text, participant, TOPICS, capture_key=q.capture_key)
    assert ctx.claims[0].value == "valor" and ctx.claims[0].state == "declarada"
    assert ctx.evidence[-1].quote == text
    assert "Pelo valor da mercadoria de cada pedido" in Interviewer(no_model).choose(ctx, participant).text


def test_default_project_can_confirm_constraints_and_aggregate_with_empty_trips():
    topics = dict(TOPICS, restricoes="operacao", ocupacao_agregacao="operacao")
    ctx = new_context("sintetica", topics)
    participant = PARTICIPANTS["operacao"]
    organizer = Organizer(no_model)
    answers = {
        "agregacao_ocupacao": "Somamos a carga de todas as viagens e dividimos pela soma das capacidades, incluindo as viagens vazias",
        "restricoes_adicionais": "Não há restrição adicional para este lote",
    }
    for key, text in answers.items():
        ctx = organizer.organize(ctx, "fala-" + key, text, participant, topics, capture_key=key)
        declaration = next(c for c in ctx.claims if c.key == key)
        ctx = organizer.organize(ctx, "confirmacao-" + key, "Confirmo", participant, topics, [declaration.id])
    assert {c.key: (c.kind, c.value) for c in ctx.claims} == {
        "agregacao_ocupacao": ("rule", "soma_carga_por_viagem_dividida_pela_soma_capacidade_incluindo_vazias"),
        "restricoes_adicionais": ("constraint", "nenhuma_restricao_adicional")}
    assert ctx.state == "rascunho"


def test_previous_revision_gets_source_gaps_only_in_the_next_revision():
    ctx = new_context("sintetica", TOPICS)
    ctx.gaps = [gap for gap in ctx.gaps if gap.key == "required"]
    unchanged = ctx.model_dump(mode="json")
    ctx2 = Organizer(lambda *_: {"base_revision": 0}).organize(
        ctx, "inicio", "Boa tarde!", PARTICIPANTS["operacao"], TOPICS)
    assert ctx.model_dump(mode="json") == unchanged
    assert {gap.key for gap in ctx2.gaps if gap.topic == "fontes"} == {
        "required", "claim:grain", "claim:quantity_unit", "claim:timezone", "claim:freight_link"}
