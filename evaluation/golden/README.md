# Avaliação independente

Gabarito dos três KPIs para as empresas sintéticas, calculado por código **separado do gerador**.

**Status (22/11/2026):** rascunho. As regras vêm de `regras_referencia` de cada `data/synthetic/empresas/<id>/empresa.yaml` e são **proposta pendente de [K02](https://github.com/leeunam/korda/issues/2)**. Quando K02 for aprovada, ajuste as regras e recalcule. Este gabarito ainda não é a validação protegida do runtime exigida em K11.

## Independência

- [`compute_golden.py`](compute_golden.py) não importa nada de `data/synthetic/generator/` e não lê `output/<id>/_gerador/`. Ele lê só as fontes que um cliente entregaria (CSV de ERP/TMS e XML de CT-e com `csv` e `ElementTree`) e, do `empresa.yaml`, apenas formato, nomes de coluna e regras.
- O mesmo agente de IA escreveu gerador e gabarito. Para reduzir o risco de erro de interpretação repetido nos dois, [`tests/test_golden.py`](tests/test_golden.py) confere à mão o exemplo de 4 linhas (R$ 166,67) e o caso explicável da 01 (R$ 100 / R$ 300 / R$ 150). **Uma pessoa ainda precisa conferir amostras da 01.**

## KPIs (regras de referência)

| KPI | Cálculo |
| --- | --- |
| Custo de frete por entrega | Σ `vTPrest` dos CT-e válidos (deduplicados por chave, sem cancelados), rateado por pedido pelo critério da empresa (peso, volume ou valor), ÷ entregas elegíveis. Elegível: viagem de tipo não excluído e pedido coberto por algum CT-e válido. |
| OTIF | Pedidos no prazo **e** completos ÷ pedidos elegíveis. Entrega sem data: falha (01, 02) ou fora do denominador (03). Prazo: data do ERP (01, 02) ou emissão + dias úteis sem sábado (03). |
| Ocupação | Σ carga ÷ Σ capacidade de todas as viagens, em kg (01, 02) ou m³ (03). Acima de 100% é sinalizado, não truncado. |

O grão atual é uma entrega por pedido, inclusive a incompleta; múltiplas entregas do mesmo pedido são rejeitadas. A completude compara volumes totais, conforme o [dicionário](../../data/synthetic/spec/dicionario.md). As regras específicas de cada empresa permanecem as de Gabriel em `regras_referencia`.

Valores de frete são calculados com `Decimal`. O rateio proporcional distribui centavos pelos maiores restos fracionários, com desempate pelo ID textual do pedido em ordem crescente. Assim, R$ 100,00 em três partes iguais resulta em R$ 33,34 / R$ 33,33 / R$ 33,33. A soma por CT-e conserva `vTPrest`; esta é uma convenção técnica de arredondamento da demo.

Em `por_viagem.csv`, `n_entregas` continua sendo a contagem operacional usada para descrever a viagem. O custo usa `n_entregas_elegiveis_custo` e o mesmo recorte do agregado: tipos permitidos e cobertura por CT-e válido. Uma viagem excluída tem custo elegível zero e média vazia. Denominadores vazios produzem `null` no JSON (campo vazio no CSV). A ocupação continua incluindo todas as viagens do cenário.

## Saídas por empresa (`<id>/`)

| Arquivo | Conteúdo |
| --- | --- |
| `kpis.json` | KPIs, regras usadas e contagens |
| `por_pedido.csv` | Custo rateado, CT-e usados, prazo, realizado, no prazo, completo, OTIF |
| `por_viagem.csv` | Carga, capacidade, ocupação, acima da capacidade, custo total e por entrega |
| `sensibilidade.json` | KPI com e sem cada correção, diferença e tolerância |
| `fontes.sha256` | Checksum de cada fonte usada; prova que o gabarito corresponde aos dados regenerados |

## Checagem de sensibilidade

[`sensitivity.py`](sensitivity.py) recalcula cada KPI com uma correção desligada e falha se a diferença ficar abaixo da tolerância do `empresa.yaml` (custo 0,5% relativo; OTIF e ocupação 0,5 p.p.). As correções são deduplicar, excluir cancelados, ratear, completude, pontualidade, entrega sem data, datas mistas, tipos de viagem excluídos (02), unidade de ocupação (03) e sábado no prazo (03). Também troca o critério proporcional do rateio, verifica a maior diferença relativa por pedido e confere conservação exata do frete válido. Isso detecta um rateio incorreto mesmo quando a média permanece igual. O CI compara todos os arquivos versionados depois de regenerar também a sensibilidade.

## Isolamento

O agente de execução não pode ler nem alterar este diretório. O repositório é público, então os gabaritos não são segredo, inclusive o da `03_reservada`. No runtime, monte esta área só no avaliador e imponha as permissões na infraestrutura. Uma falha legítima na especificação exige decisão humana e nova versão, não afrouxamento do teste.
