# Seção de ingestão do plano v0.1.0 (proposta)

**Estado (23/11/2026):** proposta da Etapa 2 da ingestão. Refs [K01](https://github.com/leeunam/korda/issues/1) e [K06](https://github.com/leeunam/korda/issues/6). O plano completo ainda não tem contrato; esta é só a seção que diz **como cada fonte do cliente entra na landing zone**. Não houve revisão conjunta das quatro frentes. Os exemplos são **sintéticos e escritos à mão**, não saídas de um planejador.

Segue a convenção do contrato de contexto (`packages/contracts/context/v0.1.0`, na branch do Marcus): chaves em inglês, enumerações em português, `synthetic: true` e ids estáveis. As evidências (`evidence_ids`) referenciam a revisão do contexto indicada em `context_ref`.

## Por fonte

| Campo | Significado |
| --- | --- |
| `system`, `kind` | `erp`/`tms`/`cte`; `postgres`, `api_http`, `pasta_entrega` ou `arquivos_exportados` (nível 0) |
| `method` | `snapshot_completo`, `incremental_campo` (exige `incremental_key`) ou `novos_arquivos` |
| `frequency`, `acceptable_latency` | frequência da carga e latência aceitável (duração ISO 8601) |
| `credentials_env` | **nomes** de variáveis de ambiente (`KORDA_*`). O valor nunca entra no plano, no Git ou no contexto de um LLM |
| `objects[]` | tabela ou recurso: chave, volume esperado por dia (`evidencia`, `perfil_das_fontes` ou `suposicao`), colunas sensíveis (LGPD) e tratamento |
| `resilience` | tentativas, espera entre elas, em que falhas tentar de novo e tempo limite por chamada |
| `on_schema_change` | sempre `escalar`: mudança de esquema para a carga e pede decisão humana |
| `evidence_ids`, `gap_ids` | de onde vem cada decisão; o que a entrevista não cobre vira **lacuna**, não suposição |

O plano também traz `gaps[]` (pergunta, bloqueante ou não, estado e papel responsável), `acceptance_tests[]` (completude, idempotência, incremental, resiliência e mudança de esquema, por fonte) e `limits.max_correction_attempts` (no máximo 3).

## Regras do validador ([`validate.py`](validate.py))

Além do [schema](ingestion_plan.schema.json):
- toda fonte tem evidência ou lacuna;
- volume `suposicao` exige uma lacuna aberta na mesma fonte;
- `incremental_key` só existe com `incremental_campo`, e é obrigatória nesse caso;
- `postgres` e `api_http` exigem `credentials_env`; pastas e arquivos não recebem credencial;
- testes de aceite obrigatórios:
  - completude e idempotência para todas as fontes;
  - incremental para fontes incrementais;
  - mudança de esquema e resiliência para fontes com rede;
- lacuna bloqueante aberta impede `pronto_para_aprovacao`;
- referências e ids precisam existir e ser únicos.

## Exemplos

- [`01_demo.json`](examples/01_demo.json): referencia `ctx-demo-01` revisão 2 (evidência `ev-fontes`, sistemas declarados no formulário).
  - ERP por snapshot diário (o ERP não expõe data de atualização: lacuna `lac-erp-atualizacao`);
  - TMS incremental por `atualizado_em`;
  - CT-e por novos arquivos.
  - Volumes por dia vêm do perfil das fontes da 01.
  - Estado `pronto_para_aprovacao`, porque as lacunas não são bloqueantes.
- [`02_variacao.json`](examples/02_variacao.json): sem contexto (`context_ref: null`). Cada fonte se apoia só em lacunas, inclusive `lac-tms-viagens-trf`: as viagens TRF existem no TMS e não apareceram na entrevista. Estado `rascunho`.

Não há exemplo da 03_reservada, que é só para medição.

## Verificar

```bash
python3 -m pip install -r requirements-contracts.txt
python3 -m unittest discover -s packages/contracts/ingestion_plan/v0.1.0/tests
python3 packages/contracts/ingestion_plan/v0.1.0/validate.py packages/contracts/ingestion_plan/v0.1.0/examples/*.json
```

## Pendências

- Encaixar esta seção no contrato do plano completo (K01/K06) e no ciclo de aprovação 1 (K07).
- A evidência `ev-fontes` só confirma quais sistemas existem. Método, frequência e latência ainda são lacunas abertas nos exemplos.
- O contrato de contexto fixa `freight_link` com os nomes de coluna da 01. Para a 02 e a 03, o vínculo entre fontes precisa ser descrito por empresa; isso fica para alinhar com o Marcus.
