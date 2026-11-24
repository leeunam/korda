# Sistemas simulados do cliente (nível 1)

**Estado (23/11/2026):** rascunho da Etapa 2 da ingestão (Refs [K09](https://github.com/leeunam/korda/issues/9), [K08](https://github.com/leeunam/korda/issues/8)). **Simulação com dados sintéticos: não são conectores nem sistemas reais.** O "dia seguinte" é um **replay**, nunca execução ao vivo (regra de [`apps/web/README.md`](../../apps/web/README.md)).

> **Escopo pendente de decisão.** [`docs/scope.md`](../../docs/scope.md) exclui da primeira entrega "qualquer conector" e "operação contínua". Este ambiente não conecta a produto real nem roda continuamente. A exceção ("sistemas do cliente simulados, com dados sintéticos, para demonstrar o planejamento e a execução da ingestão") ainda precisa ser aprovada pelo time e registrada em `scope.md`.

## O que existe

Por empresa (01_demo e 02_variacao; a 03_reservada só sob `permitir_reservada=True`, para medição), numa rede Docker `--internal`, sem internet:

| Sistema | Como aparece | Acesso da ingestão |
| --- | --- | --- |
| ERP | Postgres 17 (`erp:5432`, banco `erp`), tabelas `erp_clientes` e `erp_pedidos` com os **nomes físicos da empresa** (`cd_ped`, `NUM_PEDIDO`, `pedidoId`…) | usuário `korda_leitura`, somente leitura (`default_transaction_read_only`), senha falsa gerada na subida |
| TMS | API HTTP (`http://tms:8080/api/v1`): `veiculos`, `viagens`, `entregas` | `Authorization: Bearer <token falso>` |
| CT-e | pasta de entrega por dia, no estilo SFTP: `runs/sim-<id>/entrega/cte/<AAAA-MM-DD>/*.xml` | montagem somente leitura no contêiner da ingestão |

A SEFAZ **não** é simulada: os XML (inclusive duplicatas e eventos de cancelamento) são entregues byte a byte como o gerador os escreveu.

### Como cada sistema guarda o dado (decisões registradas)

O sistema simulado guarda o dado como um sistema real guardaria, não como a exportação CSV o escreve ([`esquema.py`](korda_simulados/esquema.py)):

- **ERP tipado:** chaves e quantidades `integer`, peso, volume e valor `numeric`, datas `date`. `"363,9"` era artefato da exportação CSV: no banco é `363.9`. As tabelas têm chave primária no id.
- **TMS em JSON:** números como número; `dt_saida` em ISO 8601. `dt_realizada` é **texto livre do TMS legado**: mantém os formatos mistos, e vazio vira `null`.
- Cada registro da API tem `atualizado_em` (metadado **simulado**: fim do dia em que o registro foi liberado, `-03:00`). As fontes geradas não têm data de atualização.

Nenhuma anomalia plantada se perde: duplicatas e cancelamentos estão nos XML, e datas mistas ou vazias estão no TMS. O ERP gerado não tem sujeira de formato.

### Replay por dias

O preparo ([`preparar.py`](korda_simulados/preparar.py)) atribui um dia a cada registro:

| Registro | Dia |
| --- | --- |
| clientes, veículos (cadastros) | primeiro dia do período |
| pedidos | `dt_emissao` |
| viagens | data de `dt_saida` |
| entregas | dia da viagem |
| CT-e | data de `dhEmi` |
| evento de cancelamento | data de `dhEvento` |

O ambiente sobe com todos os dias **menos o último** (configurável). `avancar()` libera o dia seguinte no ERP (`COPY`), na pasta de CT-e e, por último, no TMS.

**Mudança de esquema:** regra genérica, sem nada específico de empresa. A partir do último dia, o campo da data realizada de `entregas` sai como `<nome>_v2` (por exemplo, `dt_baixa_v2` ou `DATA_ENTR_v2`) em todos os registros, como numa nova versão da API. O dia e o novo nome são configuráveis (`--mudanca`, `--renomear`), e a mudança pode ser desligada.

### Comportamentos da API ([`tms_api.py`](korda_simulados/tms_api.py))

| Comportamento | Detalhe |
| --- | --- |
| Paginação | `pagina` (desde 1), `tamanho` (até 500), `total`, `proxima_pagina`; ordem estável por (`atualizado_em`, id) |
| Incremental | `atualizado_desde` (ISO 8601 com fuso; exclusivo) |
| Autenticação | 401 sem token ou com token errado |
| Limite de taxa | 429 com `Retry-After: 1` acima de `limite_rps` (padrão 20/s) |
| Falhas | `falhas={"sequencia": {"3": "500", "7": "timeout"}, "taxa_500": 0.1, "taxa_timeout": 0.05, "semente": 1, "atraso_timeout_s": 30}`; o sorteio é determinístico pela semente |
| Parâmetro inválido | 400 com o formato esperado |

## Como usar

Requer Docker (sem `docker compose`; o controle usa o CLI) e as fontes geradas ([`data/synthetic/README.md`](../../data/synthetic/README.md)).

```bash
docker build -t korda-simulados:dev infra/sistemas-simulados
docker pull postgres:17.6-alpine
cd infra/sistemas-simulados
python3 -m korda_simulados.controle subir --empresa 01_demo    # imprime id, rede e caminho das credenciais
python3 -m korda_simulados.controle avancar --id <id>          # chega o dia N+1
python3 -m korda_simulados.controle destruir --id <id>
```

Em Python: `AmbienteSimulado("01_demo").subir()`, `.avancar()`, `.executar_na_rede(argv, imagem, montagens, env)` (contêiner efêmero só na rede interna) e `.destruir()`.

O ambiente fica em `runs/sim-<id>/` (ignorado pelo Git):
- `preparo/` (catálogo e partições por dia);
- `entrega/cte/`;
- `estado/` (dia atual);
- `credenciais.json` (0600).

**As credenciais são falsas, mas seguem a regra das verdadeiras:** não vão para o Git e não entram no contexto de um LLM. Para o harness, elas devem chegar à ingestão só como variáveis de ambiente do contêiner.

## Isolamento

| Contêiner | Opções |
| --- | --- |
| preparo | `--network none`, `--read-only`, `--cap-drop ALL`, usuário do host, fontes somente leitura, `_gerador/` coberta por tmpfs vazio |
| TMS | rede interna, `--read-only`, `--cap-drop ALL`, `no-new-privileges`, usuário do host, dados somente leitura, 512 MB |
| ERP | rede interna, `no-new-privileges`, 512 MB. Não usa `--cap-drop ALL`, porque o entrypoint do Postgres precisa trocar de usuário. Não roda código do agente. |
| clientes (`executar_na_rede`) | só a rede interna, `--read-only`, `--cap-drop ALL`, usuário do host |

O host não alcança a rede interna; os testes usam contêineres efêmeros nela.

## Testes

```bash
# Unitários (preparo e API), dentro da imagem e sem rede:
docker run --rm --network none --read-only --tmpfs /tmp --user "$(id -u):$(id -g)" \
  -v "$PWD/infra/sistemas-simulados:/src:ro" -e PYTHONPATH=/src korda-simulados:dev \
  python -m unittest discover -s /src/tests -v
# Integração com 01 e 02 (na raiz; KORDA_EXIGIR_DOCKER=1 faz o pulo virar falha):
PYTHONPATH=infra/sistemas-simulados python3 -m unittest discover -s infra/sistemas-simulados/tests -v
```

A integração confere, com um avaliador próprio que lê `_gerador/contagens.json` e os XML brutos:
- o replay começa sem o último dia;
- o usuário do ERP não escreve;
- a API exige token;
- não há internet na rede;
- depois do avanço, ERP, TMS e CT-e batem com as fontes (contagens; XML byte a byte);
- o incremental traz só o dia novo, já com a coluna renomeada.

Medido em 23/11/2026: subir 01_demo ou 02_variacao leva ~4 s; os 31 testes de integração levam ~22 s.

## Limites conhecidos

- **Não é um ERP nem um TMS de verdade.** Os tipos e o `atualizado_em` são escolhas da simulação, registradas acima.
- O ERP não tem coluna de atualização: a ingestão incremental do ERP precisa de outra estratégia, decidida no plano (por chave, por data de emissão ou recarga completa). Essa lacuna é intencional e realista.
- A pasta de CT-e é uma montagem local, não um servidor SFTP. Não há protocolo, nem chaves, nem falhas de transferência.
- O Postgres roda com as capacidades padrão do Docker (veja Isolamento).
- A 03_reservada fica fora do CI e dos ajustes; só sobe com permissão explícita, para medição.
