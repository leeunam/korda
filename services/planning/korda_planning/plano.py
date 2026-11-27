"""Adaptador P1 → P2. Nenhuma construção de plano concede autorização."""

import copy
import hashlib
import importlib.util
import json
from datetime import date
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

CONTRATOS = Path(__file__).resolve().parents[3] / "packages" / "contracts"
CAMINHO_CONTEXTO = CONTRATOS / "context/v0.1.0/context.schema.json"
CAMINHO_INGESTAO = CONTRATOS / "ingestion_plan/v0.1.0/ingestion_plan.schema.json"
VERSAO_CONTEXTO = "0.1.0"
VERSAO_PLANO = "0.2.0"


def _carregar_contrato(nome, caminho):
    # As pastas de contrato têm pontos no nome e não são pacotes Python.
    spec = importlib.util.spec_from_file_location(nome, caminho.with_name("validate.py"))
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


contrato_contexto = _carregar_contrato("korda_context_v010", CAMINHO_CONTEXTO)
contrato_ingestao = _carregar_contrato("korda_ingestion_v010", CAMINHO_INGESTAO)
registry = Registry().with_resources([
    (CAMINHO_CONTEXTO.as_uri(), Resource.from_contents(contrato_contexto.SCHEMA)),
    (CAMINHO_INGESTAO.as_uri(), Resource.from_contents(contrato_ingestao.SCHEMA)),
])
VALIDADORES = {}
for versao in ("0.1.0", VERSAO_PLANO):
    caminho = CONTRATOS / f"plan/v{versao}/plan.schema.json"
    schema = json.loads(caminho.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    registry = registry.with_resource(caminho.as_uri(), Resource.from_contents(schema))
    VALIDADORES[versao] = Draft202012Validator({"$ref": caminho.as_uri()}, registry=registry)

VALIDADOR = VALIDADORES["0.1.0"]  # API de validação estrutural da versão anterior
URI_INGESTAO = (CONTRATOS / "plan/v0.2.0/plan.schema.json").as_uri() + "#/properties/ingestion"
VALIDADOR_INGESTAO = Draft202012Validator({"$ref": URI_INGESTAO}, registry=registry)

MODELOS_DEMO = (
    "models/prata_ctes.sql", "models/prata_rateios.sql", "models/ouro_por_pedido.sql",
    "models/ouro_por_viagem.sql", "models/ouro_kpis.sql",
)
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


def _montar(contexto, destino, custo, dataset, ingestao=None, *, glob_legado=False):
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
    modelos = ["models/*"] if glob_legado else ["models/prata_ctes.sql"]
    plano.update(
        schema_version="0.1.0", context_revision=contexto["revision"], context_state=contexto["state"],
        state="aguardando_aprovacao" if contexto["state"] == "pronto_para_planejamento" else "rascunho",
        metrics=metricas, tasks=tarefas, dataset=dataset,
        editable_models=modelos if dataset == "01_demo" else [],
        period="Lote sintético de fontes autorizado para a execução inteira, sem recorte adicional de datas.",
        limits={"max_repair_attempts_per_step": 3}, destination=destino, cost_estimate_brl_cents=custo,
    )
    if ingestao is not None:
        # Os dois níveis materializam a mesma landing. O runtime expõe relações bronze
        # protegidas ao dbt e mantém os arquivos e as evidências das origens no host.
        for metrica in metricas.values():
            landing = []
            for arquivo in metrica["input_files"]:
                if arquivo == "cte/*.xml":
                    landing.extend(["cte/cte.parquet", "cte/cte_nfe.parquet", "cte/cte_evento.parquet"])
                else:
                    landing.append(str(Path(arquivo).with_suffix(".parquet")))
            metrica["input_files"] = landing
        tarefas[0].update(
            output="Relações bronze de ERP, TMS e CT-e carregadas pelo worker a partir da landing Parquet.",
            verify="Inspecionar fontes e conferir manifesto, chaves e linhagem de origem antes de construir a prata.",
        )
        plano["schema_version"] = VERSAO_PLANO
        plano["ingestion"] = ingestao
        plano["editable_models"] = list(MODELOS_DEMO) if dataset == "01_demo" else []
        proposta = ingestao["proposal"]
        if proposta is not None and proposta["state"] != "pronto_para_aprovacao":
            plano["state"] = "rascunho"
        janela = ingestao["window"]
        if janela["kind"] == "simulated_as_of":
            plano["period"] = f"Cargas liberadas pelo simulador até o dia {janela['as_of']}, inclusive."
    plano["plan_version"] = _versao(plano)
    return plano


def _validar_ingestao(plano):
    ingestao = plano["ingestion"]
    janela = ingestao["window"]
    if janela["kind"] == "simulated_as_of":
        # O schema exige a forma ISO e esta checagem também recusa datas inexistentes.
        date.fromisoformat(janela["as_of"])
    proposta = ingestao["proposal"]
    if proposta is None:
        return
    erros = contrato_ingestao.erros_semanticos(proposta)
    if erros:
        raise ValueError("proposta de ingestão inválida: " + "; ".join(erros))
    if proposta["project_id"] != plano["project_id"] or proposta["company_id"] != plano["dataset"]:
        raise ValueError("proposta de ingestão pertence a outro projeto ou empresa")
    if proposta["context_ref"] != {"context_id": plano["context_id"], "revision": plano["context_revision"]}:
        raise ValueError("proposta de ingestão deve referenciar a mesma revisão do contexto")
    evidencias = {e["id"] for e in plano["evidence"]}
    for fonte in proposta["sources"]:
        if not set(fonte["evidence_ids"]) <= evidencias:
            raise ValueError(f"evidência desconhecida na fonte de ingestão {fonte['id']}")
    sistemas = [f["system"] for f in proposta["sources"]]
    if proposta["state"] == "pronto_para_aprovacao" and sorted(sistemas) != ["cte", "erp", "tms"]:
        raise ValueError("a proposta da demo precisa de uma fonte de ERP, TMS e CT-e")
    testes = [teste["id"] for teste in proposta["acceptance_tests"]]
    if len(set(testes)) != len(testes):
        raise ValueError("IDs de teste repetidos na proposta de ingestão")
    if ingestao["proposal_sha256"] != _versao(proposta):
        raise ValueError("hash da proposta de ingestão divergente")


def gerar_plano(contexto, *, destino=None, custo_estimado_centavos=None, dataset=None,
                nivel_ingestao="n0", proposta_ingestao=None, janela_ingestao=None):
    """Cria uma proposta revisável v0.2 a partir do contexto e da seleção de ingestão."""
    if contexto.get("schema_version") == "0.2.0":
        from .ponte_contexto import ContextoPendente, preparar_contexto

        diagnostico = preparar_contexto(contexto)
        if diagnostico["estado"] != "pronto":
            raise ContextoPendente(diagnostico)
        contexto = diagnostico["contexto_planejamento"]
    contrato_contexto.validate_context(contexto)
    if dataset is None and (contexto["project_id"], contexto["context_id"]) == ("demo-01", "ctx-demo-01"):
        dataset = "01_demo"
    ingestao = {
        "level": nivel_ingestao,
        "window": {"kind": "full_batch"} if janela_ingestao is None else copy.deepcopy(janela_ingestao),
        "proposal": copy.deepcopy(proposta_ingestao),
        "proposal_sha256": _versao(proposta_ingestao) if proposta_ingestao is not None else None,
    }
    # Valida o formato antes de usar campos internos durante a projeção.
    VALIDADOR_INGESTAO.validate(ingestao)
    plano = _montar(contexto, destino, custo_estimado_centavos, dataset, ingestao)
    VALIDADORES[VERSAO_PLANO].validate(plano)
    _validar_ingestao(plano)
    return plano


def _com_construcao(plano, construcao):
    """Acrescenta a seção de construção e recalcula a versão sobre o plano inteiro."""
    anexado = {k: v for k, v in copy.deepcopy(plano).items() if k != "plan_version"}
    anexado["construction"] = copy.deepcopy(construcao)
    anexado["plan_version"] = _versao(anexado)
    return anexado


def anexar_construcao(plano, construcao):
    """Anexa o plano de construção gerado pelo planejamento (LLM) para a aprovação 1 cobri-lo.

    A seção entra no hash: qualquer mudança no documento muda a `plan_version`.
    """
    validar_plano(plano)
    if "construction" in plano:
        raise ValueError("o plano já tem uma seção de construção; gere outra a partir do plano base")
    anexado = _com_construcao(plano, construcao)
    validar_plano(anexado)
    return anexado


def validar_plano(plano):
    """Confere a revisão exata, inclusive documentos legados com autorização limitada."""
    versao = plano.get("schema_version") if isinstance(plano, dict) else None
    if not isinstance(versao, str) or versao not in VALIDADORES:
        raise ValueError("versão do contrato de plano desconhecida")
    VALIDADORES[versao].validate(plano)
    if versao == VERSAO_PLANO:
        _validar_ingestao(plano)
    contexto = {chave: plano[chave] for chave in CAMPOS_CONTEXTO}
    contexto.update(schema_version=VERSAO_CONTEXTO, revision=plano["context_revision"], state=plano["context_state"])
    contrato_contexto.validate_context(contexto)
    # As duas edições v0.1 publicadas emitiram escopos distintos para a demo.
    # Reconstrua exatamente a edição assinada antes de confrontar sua versão.
    glob_legado = versao == "0.1.0" and plano["editable_models"] == ["models/*"]
    esperado = _montar(contexto, plano["destination"], plano["cost_estimate_brl_cents"], plano["dataset"],
                       plano.get("ingestion"), glob_legado=glob_legado)
    if "construction" in plano:
        esperado = _com_construcao(esperado, plano["construction"])
    if plano != esperado:
        raise ValueError("conteúdo, versão ou vínculos do plano divergentes da revisão canônica")
