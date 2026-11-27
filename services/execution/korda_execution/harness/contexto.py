"""O que o agente vê: o plano aprovado, o documento-base, os perfis e, na correção, a falha.

Do plano passam os campos necessários para construir: plan_version,
editable_models, limits, rules (valores), metrics (sem estado nem lacunas) e
tasks em ordem topológica. Evidências brutas, fontes, destino e respostas
esperadas ficam de fora.
"""

from __future__ import annotations

import json

CAMPOS_PLANO = ("plan_version", "editable_models", "limits", "rules", "metrics", "tasks")
CAMPOS_METRICA_OMITIDOS = ("state", "blocking_gaps")
LIMITE_PERFIS = 12_000
LIMITE_DOCUMENTO = 60_000

_REGRAS = """Regras:
- Você só pode criar ou alterar modelos SQL permitidos por editable_models do plano, usando escrever_modelo.
- Você não pode alterar testes, fontes, definições, macros, configuração do dbt nem as regras do plano. \
Os testes em tests/ e definicoes/ estão certos por definição: eles fixam nomes de modelos e colunas esperados.
- No pipeline 01_demo, a bronze já foi materializada pelo adaptador protegido ingerir.py. Leia \
definicoes/fontes.yml para os nomes das tabelas. A lista de colunas e tipos da entrega está em \
dbt_project.yml, na variável contrato_exportacao, e exportar.py especifica a linhagem por pedido e viagem. \
Leia tests/conservacao.sql, tests/chave_fiscal_unica.sql, tests/documentos_conflitantes.sql e tests/integridade_fontes.sql \
para conferir as relações exigidas. tests/rastreabilidade_cte.sql confere as NF-e associadas ao CT-e. \
tests/contrato_exportacao.sql valida nomes e tipos da saída. Se houver divergência de tipo, consulte \
main_dbt_test__audit.contrato_exportacao para identificar tabela, campo, esperado e encontrado. \
macros/meio_par.sql fornece o arredondamento compartilhado.
- O contrato de saída está em exportar.py (leia com ler_arquivo): as tabelas ouro_kpis, ouro_por_pedido, \
ouro_por_viagem e prata_rateios, com as colunas que ele seleciona. A exportação faz parte da verificação.
- Investigue antes de escrever: ler_plano, ler_arquivo, inspecionar_fonte e consultar_sql.
- Depois de escrever, rode rodar_dbt com subcomando build e leia o resultado.
- Se algo exigir mudar uma regra, um teste ou algo fora de editable_models, não contorne: \
explique o motivo em uma frase e pare. Uma pessoa decide o próximo passo.
- Responda em português, de forma curta."""

SISTEMA_CONSTRUCAO = f"""Você é o executor da Korda. Uma pessoa aprovou um plano de dados construído \
a partir de entrevistas com o cliente. Sua tarefa é construir o pipeline dbt/DuckDB que implementa esse plano: \
use as tabelas bronze (fontes com origem) e construa os modelos prata (tipagem, chaves, deduplicação, regras) e ouro (as métricas exatamente \
como especificadas), seguindo as tarefas do plano na ordem dada.

{_REGRAS}"""

SISTEMA = f"""Você é o executor da Korda. Um teste protegido do pipeline dbt/DuckDB falhou \
numa execução de um plano já aprovado por uma pessoa. Sua tarefa é corrigir a implementação; \
o teste que falhou está certo por definição, corrija o modelo, nunca o teste.

{_REGRAS}"""


def _valor(regra):
    return regra["value"] if isinstance(regra, dict) and "value" in regra else regra


def ordenar_tarefas(tarefas: list[dict]) -> list[dict]:
    """Ordem topológica estável (Kahn); recusa ciclo e dependência inexistente."""
    por_id = {t["id"]: t for t in tarefas}
    for t in tarefas:
        faltando = [d for d in t.get("depends_on", []) if d not in por_id]
        if faltando:
            raise ValueError(f"tarefa {t['id']!r} depende de tarefa inexistente: {', '.join(faltando)}")
    feitas: list[dict] = []
    restantes = list(tarefas)
    while restantes:
        prontas = [t for t in restantes if all(d in {f["id"] for f in feitas} for d in t.get("depends_on", []))]
        if not prontas:
            raise ValueError("as tarefas do plano têm dependência circular")
        feitas.extend(prontas)
        restantes = [t for t in restantes if t not in prontas]
    return [dict(t) for t in feitas]


def projetar_plano(plano: dict) -> dict:
    ausentes = [c for c in CAMPOS_PLANO if c not in plano]
    if ausentes:
        raise ValueError(f"plano sem os campos exigidos pelo harness: {', '.join(ausentes)}")
    return {
        "plan_version": plano["plan_version"],
        "editable_models": list(plano["editable_models"]),
        "limits": dict(plano["limits"]),
        "rules": {chave: _valor(regra) for chave, regra in plano["rules"].items()},
        "metrics": {nome: {k: v for k, v in m.items() if k not in CAMPOS_METRICA_OMITIDOS}
                    for nome, m in plano["metrics"].items()},
        "tasks": ordenar_tarefas(plano["tasks"]),
    }


def _json(objeto) -> str:
    return json.dumps(objeto, ensure_ascii=False, sort_keys=True, indent=1, default=str)


def _cortar(texto: str, limite: int, aviso: str) -> str:
    return texto if len(texto) <= limite else texto[:limite] + f"\n… ({aviso})"


def _perfis(perfis: dict) -> str:
    return _cortar(_json(perfis), LIMITE_PERFIS, "perfis cortados; use inspecionar_fonte para detalhes")


def montar_prompt_construcao(plano_publico: dict, perfis: dict, documento_base: str | None) -> str:
    documento = (_cortar(documento_base, LIMITE_DOCUMENTO, "documento-base cortado") if documento_base
                 else "(sem documento-base; use só o plano)")
    tarefas = _json([{k: t[k] for k in ("id", "depends_on", "output", "verify") if k in t}
                     for t in plano_publico["tasks"]])
    return (
        "Construa o pipeline do plano aprovado.\n\n"
        f"Tarefas, em ordem:\n{tarefas}\n\n"
        f"Documento-base da especificação:\n{documento}\n\n"
        f"Plano aprovado (projeção):\n{_json(plano_publico)}\n\n"
        f"Perfis das fontes:\n{_perfis(perfis)}\n"
    )


def montar_prompt(falha: dict, tentativa: int, limite: int, plano_publico: dict, perfis: dict,
                 documento_base: str | None = None) -> str:
    return (
        f"Correção: tentativa {tentativa} de {limite}.\n\n"
        f"Especificação aprovada: {documento_base or '(consultar plano)'}\n\n"
        f"Falha do build (código {falha.get('codigo', 'desconhecido')}):\n{falha.get('erro', '')}\n\n"
        f"Plano aprovado (projeção):\n{_json(plano_publico)}\n\n"
        f"Perfis das fontes:\n{_perfis(perfis)}\n"
    )
