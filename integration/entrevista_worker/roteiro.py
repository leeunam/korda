"""Atores sintéticos da 01 respondem às perguntas de captura e aos desafios do produtor."""

import json
from pathlib import Path

from korda_context.domain import new_context
from korda_context.interview import Interviewer
from korda_context.logistics import FIELDS
from korda_context.organizer import Organizer
from korda_context.retrieval import export


REPO = Path(__file__).resolve().parents[2]
DATA = REPO / "data/synthetic/discovery/01_demo"
TOPICOS = {campo.topic: "operacao" for campo in FIELDS.values()}
TOPICOS.update(fontes="dados", frete_rateio="financeiro")

# Respostas da empresa 01, independentes das opções oferecidas pelo produto.
# Cada escolha é justificada por uma fala no roteiro público de participantes.
RESPOSTAS = {
    "grain": ("dados-processo", "o TMS tem uma entrega por pedido", "Uma entrega por pedido"),
    "quantity_unit": ("dados-processo", "qt_itens e qt_entregue contam volumes", "Contamos as quantidades em volumes"),
    "timezone": ("dados-processo", "em America/Sao_Paulo", "Usamos o horário de São Paulo"),
    "freight_link": ("dados-processo", "TMS.nr_ped liga ao ERP.cd_ped; ERP.ch_nfe liga ao CT-e.infNFe/chave",
                     "Ligamos o número do pedido da entrega ao código do pedido no ERP e a chave da nota do pedido à nota citada no CT-e"),
    "deduplicar_cte": ("operacao-frete", "Contamos a chave uma vez", "Contamos apenas uma vez por chave do CT-e"),
    "excluir_cancelados": ("operacao-frete", "excluímos o cancelamento homologado", "Excluímos o CT-e cancelado"),
    "excluir_tipos_viagem": ("operacao-frete", "Não excluímos tipos de viagem", "Todos os tipos de viagem entram"),
    "no_prazo": ("operacao-otif", "incluindo o próprio dia do prazo", "Entregue até o dia previsto, inclusive"),
    "completo": ("operacao-otif", "Completo exige qt_entregue >= qt_itens em volumes",
                 "Quando os volumes entregues são iguais ou superiores aos volumes pedidos"),
    "sem_data_realizada": ("operacao-otif", "Sem data realizada conta como falha", "Conta como falha no OTIF"),
    "prazo_conta_sabado": ("operacao-otif", "O prazo considera sábado", "Sábado conta como dia útil"),
    "ocupacao_unidade": ("operacao-ocupacao", "A ocupação usa kg na saída", "Comparamos o peso em quilos"),
    "rateio_cte": ("financeiro-rateio", "proporcionalmente ao peso bruto de cada pedido", "Pelo peso expedido de cada pedido"),
}


def ler(path):
    return json.loads(path.read_text(encoding="utf-8"))


def modelo_sem_fatos(_system, data):
    """Somente a saudação usa o provedor de teste; nem escolhas nem confirmações dependem dele."""
    entrada = json.loads(data)
    if entrada["current_text"] != "Olá":
        raise AssertionError("a entrevista recorreu ao provedor para interpretar uma resposta guiada")
    return {"base_revision": entrada["context"]["revision"]}


def redator_de_pergunta(_system, data):
    return {"text": json.loads(data)["selected_gap"]["question"]}


def entrevistar(enviar):
    """Cada mensagem devolve a exportação e a pergunta realmente emitida àquela pessoa."""
    turnos = {x["id"]: x for x in ler(DATA / "personas/roteiro.json")["turns"]}
    respondidas = set()
    for papel in ("dados", "operacao", "financeiro"):
        documento, pergunta = enviar(papel, "Olá")
        for _ in range(2 * len(RESPOSTAS) + 1):
            if pergunta.get("claim_ids"):
                if len(pergunta["claim_ids"]) != 1:
                    raise AssertionError("a confirmação exige um único desafio vinculado")
                texto = "Confirmo"
            elif chave := pergunta.get("capture_key"):
                turno, trecho, texto = RESPOSTAS[chave]
                if chave in respondidas or turnos[turno]["participant_id"] != papel or trecho not in turnos[turno]["answer"]:
                    raise AssertionError(f"captura sem respaldo no roteiro deste responsável: {chave}")
                respondidas.add(chave)
            else:
                break
            documento, pergunta = enviar(papel, texto)
        else:
            raise AssertionError("a entrevista não progrediu ao receber as confirmações")
        if papel == "operacao":
            pendente = documento
    if respondidas != set(RESPOSTAS):
        raise AssertionError(f"campos ausentes da entrevista: {set(RESPOSTAS) - respondidas}")
    return pendente, documento


def revisoes_em_memoria(project_id="entrevista-01"):
    """Executa organizador e entrevistador reais sem Postgres para a suíte rápida."""
    documento = new_context(project_id, TOPICOS)
    organizador = Organizer(modelo_sem_fatos)
    entrevistador = Interviewer(redator_de_pergunta)
    participantes = {p["id"]: p for p in ler(DATA / "inputs/formulario.json")["participants"]}
    perguntas = {}

    def enviar(papel, texto):
        nonlocal documento
        anterior = perguntas.get(papel, {})
        pessoa = participantes[papel]
        identificador = f"turno-{documento.revision + 1}"
        documento = organizador.organize(
            documento, identificador, texto, pessoa, TOPICOS, anterior.get("claim_ids", ()),
            capture_key=anterior.get("capture_key"), source_id="wamid." + identificador,
            input_timestamp=f"2026-09-01T12:00:{documento.revision:02d}+00:00",
        )
        pergunta = entrevistador.choose(documento, pessoa)
        perguntas[papel] = pergunta.model_dump() if pergunta else {}
        return export(documento), perguntas[papel]

    return entrevistar(enviar)
