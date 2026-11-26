"""O que o agente vê: a falha, a projeção do plano aprovado e os perfis das fontes.

Do plano, só cinco campos passam: plan_version, editable_models, limits, rules
e metrics[*].acceptance. Evidências, fontes, destino e fórmulas ficam de fora,
e as respostas esperadas nunca fazem parte do contexto.
"""

from __future__ import annotations

import json

CAMPOS_PLANO = ("plan_version", "editable_models", "limits", "rules", "metrics")
LIMITE_PERFIS = 12_000

SISTEMA = """Você é o executor da Korda. Um teste protegido do pipeline dbt/DuckDB falhou \
numa execução de um plano já aprovado por uma pessoa. Sua tarefa é corrigir a implementação.

Regras:
- Você só pode alterar os modelos listados em editable_models do plano, usando escrever_modelo.
- Você não pode alterar testes, fontes, definições, configuração do dbt nem as regras do plano. \
O teste que falhou está certo por definição; corrija o modelo, nunca o teste.
- Use ler_plano, ler_arquivo, inspecionar_fonte e consultar_sql para entender a causa antes de escrever.
- Depois de escrever, rode rodar_dbt com subcomando build e leia o resultado.
- Se a correção exigir mudar uma regra ou algo fora de editable_models, não escreva nada: \
explique o motivo em uma frase e pare. Uma pessoa decide o próximo passo.
- Responda em português, de forma curta."""


def _valor(regra):
    return regra["value"] if isinstance(regra, dict) and "value" in regra else regra


def projetar_plano(plano: dict) -> dict:
    ausentes = [c for c in CAMPOS_PLANO if c not in plano]
    if ausentes:
        raise ValueError(f"plano sem os campos exigidos pelo harness: {', '.join(ausentes)}")
    return {
        "plan_version": plano["plan_version"],
        "editable_models": list(plano["editable_models"]),
        "limits": dict(plano["limits"]),
        "rules": {chave: _valor(regra) for chave, regra in plano["rules"].items()},
        "metrics": {nome: {"acceptance": list(m.get("acceptance", []))} for nome, m in plano["metrics"].items()},
    }


def _json(objeto) -> str:
    return json.dumps(objeto, ensure_ascii=False, sort_keys=True, indent=1, default=str)


def montar_prompt(falha: dict, tentativa: int, limite: int, plano_publico: dict, perfis: dict) -> str:
    perfis_txt = _json(perfis)
    if len(perfis_txt) > LIMITE_PERFIS:
        perfis_txt = perfis_txt[:LIMITE_PERFIS] + "\n… (perfis cortados; use inspecionar_fonte para detalhes)"
    return (
        f"Correção: tentativa {tentativa} de {limite}.\n\n"
        f"Falha do build (código {falha.get('codigo', 'desconhecido')}):\n{falha.get('erro', '')}\n\n"
        f"Plano aprovado (projeção):\n{_json(plano_publico)}\n\n"
        f"Perfis das fontes:\n{perfis_txt}\n"
    )
