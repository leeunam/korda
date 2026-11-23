# Dicionário das fontes sintéticas (cenário 01): rascunho

**Status:** rascunho para [K03](https://github.com/leeunam/korda/issues/3). Os nomes e tipos podem mudar quando os contratos de K01 forem fechados.

Os nomes abaixo são os **lógicos** e o **conjunto A** (01_demo). Cada empresa define nomes físicos próprios em `colunas` do seu `empresa.yaml`: conjunto B na 02 (`NUM_PEDIDO`, `DATA_ENTR`…) e conjunto C na 03 (`pedidoId`, `dtEntregaReal`…). O formato também muda por empresa: separador, decimal e formatos de data em `formato`.

As fontes imitam a exportação de um cliente real. Os nomes de coluna são curtos e pouco claros, os sistemas guardam formatos diferentes e as chaves não têm o mesmo nome entre eles. Entender isso é tarefa do perfilamento (P1/K05) e do plano (P2/K06).

Convenções da exportação: CSV em UTF-8, separador `;` e vírgula decimal (ERP e TMS). Datas seguem o fuso `America/Sao_Paulo`, sem offset no texto. O CT-e chega como um XML por documento.

## ERP

### `erp_clientes.csv`
| Coluna | Tipo | Descrição |
| --- | --- | --- |
| `cd_cli` | inteiro | Código interno do cliente (chave). |
| `ds_razao` | texto | Razão social fictícia. |
| `nr_cnpj` | texto (14) | CNPJ fictício, com DV propositalmente inválido. |
| `cd_mun_ibge` | inteiro | Município (de `empresas/<id>/area_atendimento.csv`). |
| `fl_ativo` | `S`/`N` | Cadastro ativo. |

### `erp_pedidos.csv`
| Coluna | Tipo | Descrição |
| --- | --- | --- |
| `cd_ped` | inteiro | Número do pedido (chave). |
| `cd_cli` | inteiro | → `erp_clientes.cd_cli`. |
| `dt_emis` | data `AAAA-MM-DD` | Emissão do pedido. |
| `dt_prev_ent` | data `AAAA-MM-DD` | Data prometida ao cliente. |
| `qt_itens` | inteiro | Quantidade de volumes pedida. |
| `ps_bruto` | decimal (kg) | Peso bruto. |
| `vl_merc` | decimal (R$) | Valor da mercadoria. |
| `vl_cubag` | decimal (m³) | Volume (cubagem). |
| `qt_dias_prz` | inteiro | Prazo em dias úteis. Só na 03 (`prazoDU`), que não traz `dt_prev_ent`. |
| `ch_nfe` | texto (44) | Chave da NF-e do pedido. É o elo com o CT-e (`infNFe/chave`). |

## TMS

### `tms_veiculos.csv`
| Coluna | Tipo | Descrição |
| --- | --- | --- |
| `id_veic` | texto | Código interno (chave). |
| `placa` | texto | Placa fictícia no padrão Mercosul. |
| `tp_veic` | texto | `VUC`, `TOCO`, `TRUCK`. |
| `cap_kg` | inteiro | Capacidade de peso. |
| `cap_m3` | decimal | Capacidade de volume. |

### `tms_viagens.csv`
| Coluna | Tipo | Descrição |
| --- | --- | --- |
| `id_viag` | inteiro | Viagem (chave). |
| `id_veic` | texto | → `tms_veiculos.id_veic`. |
| `dt_saida` | data e hora | Saída da sede. |
| `km_rodado` | decimal | Hodômetro da viagem. |
| `tp_viag` | texto | `DIST` (distribuição). Na 02 também `TRF` (transferência para a filial; fato fora da entrevista). |

### `tms_entregas.csv`
| Coluna | Tipo | Descrição |
| --- | --- | --- |
| `id_ent` | inteiro | Entrega (chave). |
| `id_viag` | inteiro | → `tms_viagens.id_viag`. |
| `nr_ped` | inteiro | → `erp_pedidos.cd_ped` (nome diferente de propósito). |
| `seq_parada` | inteiro | Ordem na rota. |
| `qt_entregue` | inteiro | Volumes entregues. |
| `dt_baixa` | texto | Data e hora da entrega realizada. **Formatos mistos** e às vezes vazia (ver anomalias). |
| `st_ent` | texto | `ENTREGUE`, `PARCIAL`; na 02, `TRANSFERIDO` para viagens `TRF`. |

## CT-e (`cte/*.xml`)

XML do **CT-e 4.00, modal rodoviário**, no formato `cteProc` (CT-e + protocolo). Deve ser validado contra os XSD em [`../reference/cte-xsd/PL_CTe_400/`](../reference/cte-xsd/PL_CTe_400/README.md). Cancelamentos chegam como `procEventoCTe` (evento `110111`).

| Caminho (simplificado) | Uso na demo |
| --- | --- |
| `infCte/@Id` = `CTe` + chave de 44 dígitos | Chave do CT-e (`chCTe`). Duplicatas repetem a chave. |
| `ide/nCT`, `ide/serie`, `ide/dhEmi` | Número, série e emissão. |
| `ide/cMunIni`, `ide/cMunFim` | Origem (sede) e destino (IBGE). |
| `emit/CNPJ` | Transportadora fictícia. |
| `rem`, `dest` | Remetente e destinatário fictícios. |
| `vPrest/vTPrest` | **Valor total do frete.** Base do custo de frete. |
| `infCTeNorm/infCarga/vCarga`, `infQ` (peso) | Valor e peso da carga. |
| `infCTeNorm/infDoc/infNFe/chave` (1..n) | NF-e transportadas, que levam a `erp_pedidos.ch_nfe`. Mais de uma NF-e no mesmo CT-e exige rateio. |
| `protCTe/infProt/cStat` | `100` = autorizado. |
| `procEventoCTe` com `tpEvento=110111` | Cancelamento homologado da chave. |

`Signature` é exigida pelo XSD. O gerador vai produzir uma assinatura **estruturalmente válida e sem valor criptográfico**, e isso será documentado.

## Relações

```text
erp_clientes 1─n erp_pedidos ─(ch_nfe = infNFe/chave)─ n─1 CT-e
erp_pedidos  1─n tms_entregas (cd_ped = nr_ped)
tms_viagens  1─n tms_entregas ; tms_veiculos 1─n tms_viagens
```
