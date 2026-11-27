<!-- SINTÉTICO: documento gerado em 27/11/2026 pelo comando planejar (anthropic/claude-opus-5.5, via API da Feita) a partir do contexto fictício 02_rateio_confirmado. Exemplo de teste, não é gabarito nem regra aprovada. plan_version 6291223… -->

# Pipeline de KPIs logísticos: ctx-demo-01 (revisão 2, sintético)

## Modelos

As fontes bronze já existem e não devem ser criadas nem alteradas: `bronze_documentos`, `bronze_pedidos`, `bronze_entregas`, `bronze_viagens` e `bronze_veiculos`. Todo modelo derivado preserva o arquivo de origem e a linha (ou o sha256 do XML) para manter a rastreabilidade.

### Prata

| Modelo | Grão | Chaves | Colunas principais | Fontes |
|---|---|---|---|---|
| prata_pedidos (aux) | 1 por pedido ERP | pedido_id (= cd_ped) | chave_nfe (ch_nfe), qt_itens, peso_decimos_kg (ps_bruto × 10, inteiro), data_prevista ou prazo, arquivo_pedido, linha_pedido | bronze_pedidos |
| prata_entregas (aux) | 1 por entrega | entrega_id; pedido_id (= nr_ped) | viagem_id (id_viag), qt_entregue, data_realizada (local America/Sao_Paulo), arquivo_entrega, linha_entrega | bronze_entregas |
| prata_viagens (aux) | 1 por viagem | viagem_id | veiculo_id (id_veic), tipo_viagem, arquivo_viagem, linha_viagem | bronze_viagens |
| prata_veiculos (aux) | 1 por veículo | veiculo_id | capacidade_kg, arquivo_veiculo, linha_veiculo | bronze_veiculos |
| prata_documentos_cte (aux) | 1 por XML lido | arquivo, sha256 | chave_cte, cStat, vTPrest, tipo do documento, evento (110111), retorno do evento (135) | bronze_documentos |
| prata_ctes | 1 por (chave_cte, chave_nfe) de CT-e válido | chave_cte + chave_nfe | chave_cte, chave_nfe (infNFe/chave), valor_centavos (vTPrest em centavos), arquivo | prata_documentos_cte |
| prata_rateios | 1 por (chave_cte, pedido_id) | chave_cte + pedido_id | chave_cte, pedido_id, centavos, valor_centavos, arquivo, sha256 | prata_ctes, prata_pedidos |
| prata_chaves_invalidas (aux) | 1 por chave sem vínculo | tipo + chave | entrega sem pedido, NF-e sem pedido, viagem sem veículo, grão violado | todas as prata |

Um CT-e é válido quando tem cStat 100, está deduplicado por chave_cte e não tem evento 110111 com retorno 135. O vTPrest é convertido para centavos com aritmética decimal exata, sem ponto flutuante.

### Ouro

| Modelo | Grão | Chaves | Colunas principais | Fontes |
|---|---|---|---|---|
| ouro_por_pedido | 1 por pedido (com sua entrega) | pedido_id | todas as colunas exigidas: elegivel_custo, custo_frete_rateado, ctes, elegivel_otif, no_prazo, completo, otif, qt_itens, qt_entregue, peso_decimos_kg e as colunas de rastreio | prata_pedidos, prata_entregas, prata_viagens, prata_rateios |
| ouro_por_viagem | 1 por viagem, inclusive vazia | viagem_id | veiculo_id, tipo_viagem, n_entregas, n_entregas_elegiveis_custo, carga, capacidade, unidade='kg', ocupacao, acima_capacidade, custo_frete_total, custo_por_entrega e as colunas de rastreio | prata_viagens, prata_veiculos, ouro_por_pedido |
| ouro_kpis | 1 linha | — | custo_frete_por_entrega, otif_pct, ocupacao_pct e os numeradores e denominadores de cada um | ouro_por_pedido, ouro_por_viagem |

## Regras aplicadas

| Regra | Implementação | Evidência |
|---|---|---|
| deduplicar_cte = true | Agrupar os CT-es por chave_cte e manter uma única ocorrência, com o critério determinístico descrito em Premissas. | ev-operacao |
| excluir_cancelados = true | Remover a chave_cte que tenha evento 110111 com retorno 135, mesmo que o evento esteja em outro arquivo. Aceitar apenas cStat 100. | ev-operacao |
| rateio_cte = peso | Para cada CT-e válido, distribuir valor_centavos entre os pedidos ligados pela chave NF-e, na proporção de peso_decimos_kg (ps_bruto). Calcular a parte inteira de V·wᵢ/W e entregar os centavos restantes aos maiores restos, com desempate por pedido_id textual crescente. A soma por CT-e precisa ser exata. | ev-financeiro, ev-operacao |
| excluir_tipos_viagem = [] | Não excluir nenhum tipo. Mesmo assim, o filtro existe como parâmetro (lista vazia) aplicado a elegivel_custo, elegivel_otif e ocupação. | ev-operacao |
| no_prazo | `date(data_realizada local) <= data_prevista`, de forma inclusiva. | ev-operacao |
| prazo_conta_sabado = true | Se o prazo vier em dias, contar segunda a sábado como dias úteis. | ev-operacao |
| sem_data_realizada = falha | Uma data_realizada nula deixa no_prazo = false. O pedido continua no denominador do OTIF. | ev-operacao |
| completo | `qt_entregue >= qt_itens`, ambos em volumes. | ev-operacao, ev-fontes |
| ocupacao_unidade = kg | Carga e capacidade em kg. A capacidade entra uma vez por viagem, considerando todas as viagens. | ev-operacao |
| Vínculos | `TMS.nr_ped = ERP.cd_ped`; `ERP.ch_nfe = CT-e infNFe/chave`; `entrega.id_viag = viagem.id_viag`; `viagem.id_veic = veiculo.id_veic`. | ev-fontes |
| Fuso | Datas sem offset são interpretadas como America/Sao_Paulo. Datas com offset são convertidas para esse fuso antes de `date()`. | ev-fontes |

## Métricas

### custo_frete_por_entrega (BRL/entrega)

- **Elegibilidade:** `elegivel_custo` é verdadeiro quando o tipo de viagem está incluído e o pedido é coberto por pelo menos um CT-e válido em prata_rateios. Entregas parciais entram.
- **Numerador:** `Σ custo_frete_rateado` dos pedidos elegíveis, em que `custo_frete_rateado = Σ centavos / 100` somado sobre os CT-es do pedido.
- **Denominador:** a contagem de entregas elegíveis.
- **Fórmula:** numerador / denominador. Se o denominador for 0, o resultado é null.
- **Grão:** uma entrega por pedido. A conciliação é feita em ouro_por_pedido e em ouro_por_viagem.
- **Exclusões:** CT-es não autorizados, duplicados ou cancelados.

### otif_pct (%)

- **Elegibilidade:** `elegivel_otif` é verdadeiro para todo pedido com entrega em tipo de viagem incluído. Não depende de CT-e.
- **Componentes:** `otif = no_prazo AND completo`, e um pedido sem data realizada é contado como falha.
- **Fórmula:** `100 × count(otif ∧ elegivel_otif) / count(elegivel_otif)`. Se o denominador for 0, o resultado é null.

### ocupacao_pct (%)

- **Carga por viagem:** `Σ peso_decimos_kg / 10` das entregas da viagem. Uma viagem sem entregas tem carga 0.
- **Ocupação por viagem:** `100 × carga / capacidade`, com `acima_capacidade = ocupacao > 100`. O valor não é truncado.
- **Fórmula agregada:** `100 × Σ carga / Σ capacidade` sobre todas as viagens. A capacidade entra uma vez por viagem. Se Σ capacidade = 0, o resultado é null.

## Testes de aceite

1. **Unicidade:** `pedido_id` é único em ouro_por_pedido; `viagem_id` é único em ouro_por_viagem; `(chave_cte, pedido_id)` é único em prata_rateios; `(chave_cte, chave_nfe)` é único em prata_ctes.
2. **Bronze conciliado:** cada XML autorizado aparece em prata_documentos_cte com arquivo e sha256, e a chave documental é preservada.
3. **Deduplicação:** uma chave_cte duplicada em dois arquivos gera um único conjunto de rateios.
4. **Cancelamento:** um CT-e com evento 110111 e retorno 135 não aparece em prata_ctes. Um CT-e com cStat diferente de 100 também não.
5. **Conservação do rateio:** para cada chave_cte, `Σ centavos = valor_centavos`.
6. **Maiores restos:** em um caso com empate de resto, o centavo extra vai ao pedido_id textualmente menor.
7. **Proporção por peso:** o caso sintético com pesos conhecidos reproduz os centavos esperados por pedido.
8. **Custo por viagem:** `custo_frete_total = Σ custo_frete_rateado` das entregas elegíveis da viagem, e `custo_por_entrega = total / n_entregas_elegiveis_custo`.
9. **Custo: parcial e sem cobertura:** uma entrega parcial coberta por CT-e entra no denominador. Uma entrega sem CT-e válido fica com `elegivel_custo = false`.
10. **OTIF: no prazo e incompleto:** o pedido fica fora do numerador.
11. **OTIF: completo e atrasado:** o pedido fica fora do numerador.
12. **OTIF: limite inclusivo:** uma entrega realizada no próprio dia previsto tem `no_prazo = true`.
13. **OTIF: sem data:** um pedido sem data_realizada fica no denominador e fora do numerador.
14. **Datas:** um timestamp com offset que muda de dia ao converter para America/Sao_Paulo é avaliado pela data local.
15. **Sábado:** um prazo em dias que atravessa um sábado conta esse sábado.
16. **Tipos de viagem:** com a lista vazia, os denominadores incluem todos os tipos. Com uma lista de teste não vazia, os tipos listados saem do custo, do OTIF e da ocupação.
17. **Ocupação:** uma viagem vazia aparece com carga 0 e com capacidade no denominador. Uma viagem acima de 100% tem `acima_capacidade = true` e o valor não é truncado.
18. **Denominador vazio:** cada KPI retorna null com uma base vazia.
19. **Valores agregados:** ouro_kpis é igual ao recálculo a partir de ouro_por_pedido e ouro_por_viagem e ao avaliador independente.
20. **Chaves inválidas:** prata_chaves_invalidas lista os vínculos quebrados, e o grão de uma entrega por pedido é verificado.

## Premissas e lacunas

**Premissas** (não alteram regras aprovadas)

- **Duplicatas de CT-e:** se a mesma chave_cte aparece em mais de um arquivo, mantém-se a ocorrência de menor `arquivo` em ordem crescente. Se os sha256 divergirem, a chave é sinalizada.
- **Carga da ocupação:** usa ps_bruto do ERP (peso_decimos_kg) somado por viagem. As fontes não citam outro campo de peso carregado.
- **Peso nulo no rateio:** um CT-e cujos pedidos somam peso 0 ou nulo não é rateado. Ele é listado em prata_chaves_invalidas, sem regra inventada para distribuí-lo.
- **Dias úteis:** se o prazo vier em dias, domingos não contam e não se aplica calendário de feriados, porque nenhum foi informado.

**Lacunas** (não bloqueantes)

- **Nomes de colunas não informados:** data prevista ou prazo, tipo de viagem, capacidade do veículo, cStat e eventos no XML. Devem ser identificados no esquema bronze, sem supor valores.
- **Prazo em dias:** não há informação sobre a data-base da contagem (ex.: emissão do pedido) nem sobre o calendário de feriados. A data-base deve ser confirmada no esquema do ERP.
- **Unidade da capacidade:** não foi confirmado que a capacidade em tms_veiculos está em kg. Se estiver em outra unidade, registrar a conversão antes do agregado.
- **Caso sintético:** todo o contexto é sintético (synthetic = true). Os números esperados vêm do avaliador independente.
