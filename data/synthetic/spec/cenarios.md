# Cenários sintéticos (empresas)

O mesmo gerador ([`../generator/`](../generator/generate.py)) produz as três empresas. Cada uma tem sua própria [`empresa.yaml`](../empresas/01_demo/empresa.yaml) e semente fixa. Os dados gerados ficam em `data/synthetic/output/<empresa>/`, ignorado pelo Git e reproduzível.

| Empresa | Uso | Pode ajustar agente/prompts/playbook? | O que muda |
| --- | --- | --- | --- |
| [01_demo](../empresas/01_demo/empresa.yaml) | Vídeo e ajuste | Sim | Campinas/SP, 30 dias, 10 veículos (VUC/TOCO/TRUCK), ~15 entregas por viagem, rateio por peso, colunas do conjunto A, **caso explicável** |
| [02_variacao](../empresas/02_variacao/empresa.yaml) | Ajuste | Sim | Ribeirão Preto/SP, 15 dias, 5 veículos, **rateio por volume**, colunas do conjunto B, CSV com `,`, **fato fora da entrevista** (viagens de transferência `TRF`) |
| [03_reservada](../empresas/03_reservada/empresa.yaml) | **Só medição** | **Não** ([README](../empresas/03_reservada/README.md)) | Curitiba/PR, 45 dias, 20 veículos, rateio por valor, ocupação em m³, entrega sem data fora do denominador, prazo em dias úteis **sem sábado**, colunas do conjunto C, CSV com `\|` |

As regras de cada empresa (`regras_referencia`) são uma **proposta pendente de K02**. Elas definem o gabarito em [`evaluation/golden/`](../../../evaluation/golden/README.md).
