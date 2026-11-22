# Cenários sintéticos

O mesmo gerador parametrizado produz os três cenários. Só o **01** está especificado nesta etapa.

| Cenário | Uso | Pode ser usado para ajustar agente/prompts? | Estado |
| --- | --- | --- | --- |
| 01 · demo | Demonstração e desenvolvimento | Sim | Especificado em [`empresa.yaml`](empresa.yaml) (rascunho) |
| 02 · variação | Desenvolvimento, com outra regra de rateio, outros nomes de coluna e uma informação faltando | Sim | A especificar |
| 03 · reservado | **Só medição** (número honesto do pitch, K14) | **Não**: não abrir durante o desenvolvimento do agente | A especificar, com semente e parâmetros guardados fora do alcance do executor |

O cenário 03 só serve para medir se nunca foi usado para ajustar o agente. Quem preparar o 03 não deve compartilhar suas saídas com quem ajusta o planejamento ou a execução.
