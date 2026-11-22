# Anomalias plantadas (cenário 01): rascunho

Cada anomalia é um **fato** que o gerador planta nas fontes. O tratamento correto (excluir, deduplicar, ratear, considerar incompleto) **não** está definido aqui: depende das regras aprovadas em [K02](https://github.com/leeunam/korda/issues/2) e do plano (K06). As faixas estão em `anomalias` de cada [`empresa.yaml`](../empresas/01_demo/empresa.yaml) e são suposições da equipe: CT-e duplicado 2–3%, cancelado 1–2% (sempre reemitido), CT-e com vários pedidos 5–10%, atraso 8–12%, incompleta 3–5%, sem data 2–3%, datas em formatos mistos 8–12% de `dt_realizada` e viagem acima da capacidade 1–2%. O valor efetivo é sorteado pela semente e registrado em `output/<empresa>/_gerador/contagens.json`.

| # | Anomalia | Onde aparece | KPI afetado | Como se detecta | Teste que o plano deve derivar (proposta) |
| --- | --- | --- | --- | --- | --- |
| A1 | CT-e duplicado | Mesmo `chCTe` em dois arquivos XML | Custo de frete | Contagem por chave > 1 | `unique(chave_cte)` na prata |
| A2 | CT-e cancelado | `procEventoCTe` 110111 para a chave | Custo de frete, OTIF? | Junção com eventos de cancelamento | Nenhum cancelado na prata. Regra pendente de K02 |
| A3 | Cancelado e reemitido | CT-e substituto com as mesmas NF-e | Custo de frete | Mesma `infNFe/chave` em dois CT-e, um cancelado | O frete do pedido vem só do CT-e válido. Regra pendente de K02 |
| A4 | CT-e com vários pedidos | 2+ `infNFe` no mesmo CT-e | Custo por entrega | Cardinalidade CT-e → NF-e | Soma do rateio = `vTPrest` (conservação). Critério (peso?) pendente de K02 |
| A5 | Entrega incompleta | `qt_entregue < qt_itens`, `st_ent=PARCIAL` | OTIF (completude) | Comparar ERP × TMS | Pedido incompleto não é *in full* |
| A6 | Entrega atrasada | `dt_baixa > dt_prev_ent` | OTIF (pontualidade) | Comparar datas | Atrasado não é *on time*. OTIF exige pontual **e** completo |
| A7 | Sem data realizada | `dt_baixa` vazia | OTIF | Nulos | Lacuna explícita. Regra pendente de K02 (excluir do denominador ou contar como falha?) |
| A8 | Datas em formatos mistos | `dt_baixa` em `AAAA-MM-DD HH:MM`, `DD/MM/AAAA HH:MM` e `DD/MM/AA` | OTIF | Perfil de formatos | 100% de `dt_baixa` não vazias convertidas sem perda |
| A9 | Carga acima da capacidade | Soma de `ps_bruto` da viagem > `cap_kg` | Ocupação | Comparar com o cadastro | Ocupação > 100% sinalizada, não truncada em silêncio |
| A10 | Capacidade em duas unidades | `cap_kg` e `cap_m3` | Ocupação | Dicionário | O plano declara a unidade (peso ou volume). Regra pendente de K02 |

## Caso explicável da 01_demo

Fixo, fora do sorteio e definido em `caso_explicavel` da [01](../empresas/01_demo/empresa.yaml):

- CT-e de R$ 400,00 cobrindo os pedidos 900001 (100 kg) e 900002 (300 kg); rateio por peso de R$ 100,00 + R$ 300,00. O XML chega **duplicado**.
- Pedido 900003 com CT-e de R$ 150,00 **cancelado** e reemitido com o mesmo valor; o custo do pedido é R$ 150,00.

O gabarito confere esses valores em `evaluation/golden/tests/test_golden.py`.

## Caso mínimo de referência (4 CT-e)

O exemplo de 4 linhas do contexto do Gabriel (CT-e A1 duplicado, B2, C3 cancelado e rateio por peso; R$ 237,50 ingênuo contra R$ 166,67) cobre A1, A2 e A4. Ele já é uma **fixture independente**, montada à mão em `evaluation/golden/tests/test_golden.py` ([K11](https://github.com/leeunam/korda/issues/11)), e não nasce do gerador. O valor R$ 166,67 vale **só** se K02 aprovar deduplicar, excluir o cancelado e seus pedidos, ratear por peso e usar entregas válidas no denominador.

## Independência do gabarito

O gerador sabe **quais linhas** receberam cada anomalia e pode exportar esse registro. Os valores esperados dos KPIs, porém, devem ser calculados por um avaliador separado (`evaluation/golden/`), com implementação própria, e conferidos à mão em amostras. Não reaproveitar o código do gerador nem o do pipeline.
