# Ingestão de nível 1 de referência

**Estado (23/11/2026):** rascunho da Etapa 2 da ingestão (Refs [K09](https://github.com/leeunam/korda/issues/9), [K10](https://github.com/leeunam/korda/issues/10)). Lê sistemas do cliente **simulados**, com dados sintéticos; não é conector real.

[`ingestao_n1/`](ingestao_n1/__main__.py) é uma ingestão escrita à mão que executa a [seção de ingestão do plano](../../../packages/contracts/ingestion_plan/v0.1.0/README.md) contra o [ambiente simulado](../../../infra/sistemas-simulados/README.md). Ela serve para três coisas:

1. **Plano B da demo**, enquanto o harness (K10) não existe.
2. **Base de comparação** para o código que o agente vai gerar (tempo, tentativas, resultado).
3. **Prova de que os testes de aceite são alcançáveis**: eles passam com a referência.

**Ela não fica ao alcance do agente.** Não entra na imagem da sandbox (`test_sandbox.py` confere) e só é montada, somente leitura, em `/work/codigo` quando a referência roda. O agente terá de escrever a própria ingestão a partir do plano.

## O que faz

Cada execução é uma **carga**:

| Fonte | Método do plano | Como |
| --- | --- | --- |
| ERP (Postgres) | `snapshot_completo` | `select <coluna>::text ...` de cada tabela do `locator`, ordenado pela chave; o ERP não expõe data de atualização (lacuna `lac-erp-atualizacao`) |
| TMS (API) | `incremental_campo` | páginas de 500 com `atualizado_desde` maior que a marca da carga anterior; números ficam com o texto do JSON (`parse_int=str`) |
| CT-e (pasta) | `novos_arquivos` | arquivos do padrão do `locator` ainda não processados; parser do nível 0 (`korda_ingestao.cte`) |

- **Idempotência:** sem registro novo, sem arquivo novo e com o ERP igual, nada muda (`sem_novidades`).
- **Resiliência:** novas tentativas conforme `resilience` do plano (motivos, espera e tempo limite; respeita `Retry-After`). Esgotado o limite, a saída é 1 e nada é gravado.
- **Mudança de esquema:** coluna nova, ausente ou renomeada faz a ingestão parar sem gravar nada. Ela registra `_escalonamentos/<carga>.json` (esperado, recebido, novas, ausentes) e sai com 3. Nada é corrigido em silêncio.
- **Credenciais:** só por variáveis `KORDA_*` listadas em `credentials_env`. O worker as entrega por um `--env-file` temporário (0600).

## Landing

Os caminhos são os mesmos do nível 0 (`erp/erp_pedidos.parquet`, `tms/tms_entregas.parquet`, `cte/cte.parquet`…), para a K09 não mudar. O manifesto traz `nivel: 1` e a lista de cargas.

| Item | Conteúdo |
| --- | --- |
| `erp/*.parquet` | último snapshot |
| `tms/*.parquet`, `cte/*.parquet`, `_rejeitados.parquet` | união das cargas, na ordem |
| `_cargas/<NNNN>/` | o que cada carga trouxe, mais `carga.json` (contagens, marcas, tentativas) |
| `_estado/estado.json` | marcas, arquivos processados, esquemas conhecidos e hash do snapshot do ERP |
| `_escalonamentos/` | pedidos de decisão humana |

Tudo é texto (`VARCHAR`), com linhagem `_origem` (ex.: `tms:/entregas`) ou `_arquivo` + `_xml_sha256`, e `_carga`.

**Diferenças de valor em relação ao nível 0** (são do sistema de origem, não limpeza):
- O ERP vem do banco tipado, então `ps_bruto` chega como `363.9` (no CSV exportado era `363,9`) e as datas em ISO.
- No TMS, `dt_saida` vem em ISO; `dt_realizada` mantém os formatos mistos, e vazio vira `NULL`.
- A API acrescenta `atualizado_em`.

## Como rodar

```bash
docker build -t korda-sandbox:dev infra/sandbox
docker build -t korda-simulados:dev infra/sistemas-simulados && docker pull postgres:17.6-alpine
cd services/execution
PYTHONPATH=../../infra/sistemas-simulados python3 - <<'EOF'
from pathlib import Path
from korda_simulados.controle import AmbienteSimulado
from korda_execution.ingestao_n1 import executar_ingestao
plano = Path("../../packages/contracts/ingestion_plan/v0.1.0/examples/01_demo.json")
with AmbienteSimulado("01_demo") as amb:
    print(executar_ingestao(amb.credenciais, plano, Path("../../runs/landing-n1-01"))["saida"])
    amb.avancar()
    print(executar_ingestao(amb.credenciais, plano, Path("../../runs/landing-n1-01"))["saida"])
EOF
```

## Testes de aceite

[`tests/test_ingestao_n1.py`](../tests/test_ingestao_n1.py) roda os testes do plano (`at-completude`, `at-idempotencia`, `at-incremental`, `at-resiliencia`, `at-mudanca-esquema`) contra esta referência. Mais tarde, os mesmos testes valerão para o código do agente. O avaliador lê o que o simulador serve **direto do armazenamento dele** (partições por dia e pasta de entrega), sem a API e sem o código de ingestão, e compara com a landing linha a linha.

| Cenário | Resultado (23/11/2026) |
| --- | --- |
| 01_demo: carga inicial, repetição, dia novo, dia com coluna renomeada | ok: igual ao servido; repetição sem mudança de bytes; só o dia novo; escalonado sem gravar |
| 02_variacao: 500, timeout, 429 e 500 em sequência | ok, com as novas tentativas registradas |
| 02_variacao: 500 sempre | falha sem carga parcial |
| 02_variacao: credenciais | nenhuma senha ou token aparece na landing |

Tempo de parede (inclui subir o contêiner), medido em 23/11/2026:

| Empresa | Carga inicial | Repetição | Dia novo | Pico de memória |
| --- | ---: | ---: | ---: | ---: |
| 02_variacao | ~1 s | ~0,7 s | ~0,8 s | — |
| 01_demo | 2,9 s | 1,2 s | 1,1 s | 127 MB |
| 03_reservada (só medição) | 4,6 s | 1,1 s | 1,5 s | 173 MB |

A 03_reservada passou nos 4 testes de aceite na primeira execução (`KORDA_MEDIR_03=1`), sem mudança de código e sem que seus dados fossem abertos. O plano dela é derivado genericamente do exemplo da 02 (chaves vazias, sem colunas sensíveis), porque um plano de verdade para ela exigiria olhar os dados.

## Limites

- O limite de 3 tentativas **de correção** por etapa é do ciclo do agente (K10), não desta ingestão. As tentativas aqui são novas chamadas HTTP ou de conexão.
- Uma mudança de esquema escalada não tem fluxo de retomada: depois da decisão humana, o plano muda e o estado precisa ser ajustado. Isso não está implementado.
- Atualizações do mesmo id no TMS entrariam como novas linhas (só acrescenta), mas o simulador ainda não gera atualizações.
- A landing guarda cada snapshot do ERP em `_cargas/`. Para ERPs grandes, isso precisaria de outra estratégia.
