"""Adaptador P1 → P2. Nenhuma construção de plano concede autorização."""

import copy
import hashlib
import importlib.util
import json
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

CONTRATOS = Path(__file__).resolve().parents[3] / "packages" / "contracts"
CAMINHO_CONTEXTO = CONTRATOS / "context/v0.1.0/context.schema.json"
CAMINHO_PLANO = CONTRATOS / "plan/v0.1.0/plan.schema.json"

# O contrato P1 é versionado em uma pasta com pontos, fora dos pacotes instaláveis.
_spec = importlib.util.spec_from_file_location("korda_context_v010", CAMINHO_CONTEXTO.with_name("validate.py"))
contrato_contexto = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(contrato_contexto)
schema = json.loads(CAMINHO_PLANO.read_text(encoding="utf-8"))
Draft202012Validator.check_schema(schema)
registry = Registry().with_resources([
    (CAMINHO_PLANO.as_uri(), Resource.from_contents(schema)),
    (CAMINHO_CONTEXTO.as_uri(), Resource.from_contents(contrato_contexto.SCHEMA)),
])
VALIDADOR = Draft202012Validator({"$ref": CAMINHO_PLANO.as_uri()}, registry=registry)
VERSAO = "0.1.0"
CAMPOS_CONTEXTO = (
    "project_id", "context_id", "synthetic", "last_processed_turn_id",
    "sources", "evidence", "source_profile", "rules", "gaps",
)

METRICAS = {
    "custo_frete_por_entrega": {
        "grain": "Uma entrega por pedido. Conciliar também por pedido e por viagem.",
        "unit": "BRL/entrega",
        "formula": "Somar o frete alocado aos pedidos elegíveis e dividir pelo número de entregas elegíveis.",
        "denominator": "Entregas em tipos de viagem incluídos e cobertas por pelo menos um CT-e válido, inclusive entregas parciais.",
        "input_files": ["erp/erp_pedidos.csv", "tms/tms_entregas.csv", "tms/tms_viagens.csv", "cte/*.xml"],
        "joins": ["TMS.nr_ped = ERP.cd_ped", "ERP.ch_nfe = CT-e.infNFe/chave", "entrega.id_viag = viagem.id_viag"],
        "acceptance": [
            "Aplicar a cada chave autorizada (cStat 100) as regras explícitas de deduplicação e cancelamento (evento 110111 com retorno 135).",
            "Distribuir vTPrest pela base de rateio confirmada. Conservar os centavos por CT-e por maiores restos e desempatar por ID textual crescente.",
            "Conferir a distribuição por pedido e a agregação elegível por viagem com o avaliador independente.",
        ],
    },
    "otif_pct": {
        "grain": "Um pedido com uma entrega.",
        "unit": "%",
        "formula": "100 × pedidos elegíveis que satisfazem simultaneamente no_prazo e completo / pedidos elegíveis.",
        "denominator": "Pedidos em tipos de viagem incluídos, aplicando a regra confirmada de data realizada ausente.",
        "input_files": ["erp/erp_pedidos.csv", "tms/tms_entregas.csv", "tms/tms_viagens.csv"],
        "joins": ["TMS.nr_ped = ERP.cd_ped", "entrega.id_viag = viagem.id_viag"],
        "acceptance": [
            "Demonstrar uma entrega no prazo e incompleta e uma entrega completa e atrasada, ambas fora do numerador.",
            "Normalizar os formatos de data e aplicar o prazo do ERP ou a contagem de dias úteis quando o prazo estiver em dias.",
            "Conferir o denominador com datas ausentes e tipos excluídos, sem depender da cobertura por CT-e.",
        ],
    },
    "ocupacao_pct": {
        "grain": "Uma capacidade por viagem, inclusive viagem vazia.",
        "unit": "%",
        "formula": "100 × soma da carga de todas as viagens / soma da capacidade dessas viagens, na mesma unidade confirmada.",
        "denominator": "Somatório das capacidades dos veículos, uma vez por viagem, incluindo todos os tipos.",
        "input_files": ["erp/erp_pedidos.csv", "tms/tms_entregas.csv", "tms/tms_viagens.csv", "tms/tms_veiculos.csv"],
        "joins": ["TMS.nr_ped = ERP.cd_ped", "entrega.id_viag = viagem.id_viag", "viagem.id_veic = veiculo.id_veic"],
        "acceptance": [
            "Usar carga e capacidade em kg ou m³ conforme ocupacao_unidade.",
            "Agregar pela capacidade de cada viagem. Preservar viagens vazias e valores acima de 100%.",
            "Conferir carga, capacidade e percentual por viagem antes do agregado.",
        ],
    },
}
TAREFAS_COMPARTILHADAS = [
    {
        "id": "bronze", "depends_on": [],
        "output": "Relações de fontes brutas de ERP, TMS e CT-e com identificação do arquivo de origem.",
        "verify": "Conciliar os arquivos autorizados com as relações ingeridas e preservar a chave documental dos XML.",
    },
    {
        "id": "prata", "depends_on": ["bronze"],
        "output": "Pedidos, entregas, viagens, veículos, documentos e eventos tipados com chaves rastreáveis.",
        "verify": "Conferir o vínculo de NF-e, datas locais, volumes e o grão de uma entrega por pedido; expor chaves inválidas.",
    },
]


def _versao(corpo):
    canonico = json.dumps(corpo, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(canonico.encode("utf-8")).hexdigest()


def _montar(contexto, destino, custo, dataset):
    plano = {chave: copy.deepcopy(contexto[chave]) for chave in CAMPOS_CONTEXTO}
    metricas = {}
    tarefas = copy.deepcopy(TAREFAS_COMPARTILHADAS)
    for nome, definicao in METRICAS.items():
        bloqueios = [g["id"] for g in contexto["gaps"]
                     if g["blocking"] and g["state"] != "respondida" and nome in g["affected_metrics"]]
        regras = [r for r, afetadas in contrato_contexto.RULE_METRICS.items() if nome in afetadas]
        metricas[nome] = {
            **copy.deepcopy(definicao), "rule_keys": regras, "blocking_gaps": bloqueios,
            "state": "bloqueada" if bloqueios else "planejada",
        }
        tarefas.append({
            "id": f"ouro_{nome}", "depends_on": ["prata"],
            "output": f"Relação de ouro com {nome} e os componentes do seu numerador e denominador.",
            "verify": f"Executar os testes de metrics.{nome}.acceptance e devolver null para denominador vazio.",
        })
    plano.update(
        schema_version=VERSAO, context_revision=contexto["revision"], context_state=contexto["state"],
        state="aguardando_aprovacao" if contexto["state"] == "pronto_para_planejamento" else "rascunho",
        metrics=metricas, tasks=tarefas, dataset=dataset,
        editable_models=["models/prata_ctes.sql"] if dataset == "01_demo" else [],
        period="Lote sintético de fontes autorizado para a execução inteira, sem recorte adicional de datas.",
        limits={"max_repair_attempts_per_step": 3}, destination=destino, cost_estimate_brl_cents=custo,
    )
    plano["plan_version"] = _versao(plano)
    return plano


def gerar_plano(contexto, *, destino=None, custo_estimado_centavos=None, dataset=None):
    """Cria uma proposta reprodutível a partir de um contexto válido, inclusive rascunho."""
    contrato_contexto.validate_context(contexto)
    if dataset is None and (contexto["project_id"], contexto["context_id"]) == ("demo-01", "ctx-demo-01"):
        dataset = "01_demo"
    plano = _montar(contexto, destino, custo_estimado_centavos, dataset)
    VALIDADOR.validate(plano)
    return plano


def validar_plano(plano):
    """Valida o schema, o vínculo das evidências, as projeções dos KPIs e a versão."""
    VALIDADOR.validate(plano)
    contexto = {chave: plano[chave] for chave in CAMPOS_CONTEXTO}
    contexto.update(schema_version=VERSAO, revision=plano["context_revision"], state=plano["context_state"])
    contrato_contexto.validate_context(contexto)
    esperado = _montar(contexto, plano["destination"], plano["cost_estimate_brl_cents"], plano["dataset"])
    if plano != esperado:
        raise ValueError("conteúdo, versão ou vínculos do plano divergentes da revisão canônica")
