"""Perguntas de captura da demonstração. Uma opção descreve uma regra possível, nunca um valor padrão."""
from dataclasses import dataclass
import unicodedata


@dataclass(frozen=True)
class Field:
    topic: str
    question: str
    choices: tuple
    claim_kind: str = "rule"
    note: str = ""

    @property
    def kind(self):
        return "source" if self.topic == "fontes" else self.claim_kind

    def ask(self):
        labels = " ou ".join(f"“{label}”" for label, _ in self.choices)
        parts = [self.question, self.note, f"Se esta for a sua prática, responda com a frase correspondente: {labels}.",
                 "Se for diferente ou não souber, explique. A informação ficará pendente para revisão."]
        return " ".join(part for part in parts if part)


FIELDS = {
    "grain": Field("fontes", "Como as entregas aparecem nos registros de cada pedido?", (
        ("Uma entrega por pedido", "uma_entrega_por_pedido"),)),
    "quantity_unit": Field("fontes", "Em que unidade vocês registram a quantidade pedida e a entregue?", (
        ("Contamos as quantidades em volumes", "volumes"),)),
    "timezone": Field("fontes", "De qual fuso horário são as datas de entrega registradas?", (
        ("Usamos o horário de São Paulo", "America/Sao_Paulo"),)),
    "freight_link": Field("fontes", "Como vocês ligam cada entrega ao pedido e depois ao documento de frete?", (
        ("Ligamos o número do pedido da entrega ao código do pedido no ERP e a chave da nota do pedido à nota citada no CT-e",
         "TMS.nr_ped = ERP.cd_ped; ERP.ch_nfe = CT-e.infNFe/chave"),),
        note="Confira os nomes nos seus arquivos. O número TMS.nr_ped corresponde a ERP.cd_ped, "
             "e ERP.ch_nfe corresponde à chave em CT-e.infNFe/chave."),
    "deduplicar_cte": Field("frete_deduplicacao", "Como vocês contam duas cópias do mesmo CT-e?", (
        ("Contamos apenas uma vez por chave do CT-e", True), ("Contamos cada cópia do CT-e", False))),
    "excluir_cancelados": Field("frete_cancelamento", "Como vocês tratam um CT-e com cancelamento autorizado no custo?", (
        ("Excluímos o CT-e cancelado", True), ("Incluímos o CT-e cancelado", False))),
    "excluir_tipos_viagem": Field("frete_elegibilidade", "Quais viagens entram no custo de frete e no OTIF?", (
        ("Todos os tipos de viagem entram", []), ("Excluímos as viagens de transferência", ["TRF"]))),
    "rateio_cte": Field("frete_rateio", "Quando um CT-e cobre mais de um pedido, como vocês dividem o frete?", (
        ("Pelo peso expedido de cada pedido", "peso"), ("Pelo volume de cada pedido", "volume"),
        ("Pelo valor da mercadoria de cada pedido", "valor"))),
    "no_prazo": Field("otif_prazo", "Até quando uma entrega conta como pontual?", (
        ("Entregue até o dia previsto, inclusive", "data(dt_realizada) <= data prevista"),)),
    "completo": Field("otif_completude", "Quando uma entrega conta como completa?", (
        ("Quando os volumes entregues são iguais ou superiores aos volumes pedidos", "qt_entregue >= qt_itens"),)),
    "sem_data_realizada": Field("otif_data_ausente", "Como uma entrega sem data realizada entra no OTIF?", (
        ("Conta como falha no OTIF", "falha"), ("Fica fora do cálculo de OTIF", "excluir"))),
    "prazo_conta_sabado": Field("otif_sabado", "Como vocês contam sábado nos prazos em dias úteis?", (
        ("Sábado conta como dia útil", True), ("Sábado não conta como dia útil", False))),
    "ocupacao_unidade": Field("ocupacao_unidade", "Em que unidade vocês comparam a carga e a capacidade do veículo?", (
        ("Comparamos o peso em quilos", "kg"), ("Comparamos o volume em metros cúbicos", "m3"))),
}


# Tópicos adicionais no projeto padrão da CLI. Dependem de declaração e confirmação próprias.
SUPPLEMENTARY = {
    "agregacao_ocupacao": Field("ocupacao_agregacao", "Como vocês calculam a ocupação da frota reunindo as viagens?", (
        ("Somamos a carga de todas as viagens e dividimos pela soma das capacidades, incluindo as viagens vazias",
         "soma_carga_por_viagem_dividida_pela_soma_capacidade_incluindo_vazias"),)),
    "restricoes_adicionais": Field("restricoes", "Existe outra restrição que o plano deve respeitar?", (
        ("Não há restrição adicional para este lote", "nenhuma_restricao_adicional"),), "constraint"),
}


def vocabulary(required_topics):
    if not enabled(required_topics):
        return {}
    return {**FIELDS, **{key: field for key, field in SUPPLEMENTARY.items() if field.topic in required_topics}}


def enabled(required_topics):
    return all(field.topic in required_topics for field in FIELDS.values())


def choice(field, text):
    def normalized(value):
        words = unicodedata.normalize("NFKD", value.casefold().strip().rstrip(".!"))
        return " ".join("".join(c for c in words if not unicodedata.combining(c)).split())

    reply = normalized(text)
    return next(((label, value) for label, value in field.choices if normalized(label) == reply), None)
