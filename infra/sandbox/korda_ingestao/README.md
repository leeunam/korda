# Ingestão de nível 0: arquivos exportados → landing zone

**Estado (23/11/2026):** rascunho para [K09](https://github.com/leeunam/korda/issues/9) e [K08](https://github.com/leeunam/korda/issues/8). Trabalha só com **dados sintéticos**, numa **exportação de arquivos simulada**: não é conector real nem execução ao vivo. A ingestão por sistemas simulados (nível 1) ainda não existe.

Transforma `data/synthetic/output/<empresa>/{erp,tms,cte}` numa landing zone em Parquet, que a sandbox monta como `/work/fontes`. O objetivo é que o DuckDB e o dbt leiam também os CT-e em XML.

## A ingestão não limpa

Ela não deduplica, não remove cancelados, não corrige datas, não renomeia colunas e não converte `"363,9"`. Toda a sujeira plantada chega intacta, e quem limpa é o agente, guiado pelo plano aprovado. Esse é o teste do produto.

- Todas as colunas dos CSV ficam como `VARCHAR`, com o nome original, sem trim. Campo vazio continua `''`.
- Duas cópias do mesmo XML geram duas linhas.
- O cancelamento (`procEventoCTe` 110111) vira uma linha em `cte_evento`. O `cteProc` original continua com `prot_cStat = 100`, como no arquivo.

## Como rodar

Pelo worker, a partir de `services/execution/`:

```bash
docker build -t korda-sandbox:dev infra/sandbox            # na raiz do repositório
python3 -m korda_execution.ingestao --fontes ../../data/synthetic/output/01_demo \
    --destino ../../data/synthetic/landing/01_demo
```

O destino não pode existir. O worker grava numa pasta temporária e só a renomeia se a ingestão terminar bem.

## Onde roda

O contêiner é efêmero e usa a mesma imagem da sandbox, que tem duckdb e lxml fixados. Ele herda as opções de isolamento da sandbox (`opcoes_isolamento` em `sandbox.py`): `--network none`, `--read-only`, `--cap-drop ALL`, `no-new-privileges`, usuário do host, 2 GB, 1 CPU e tempo limite.

| No contêiner | Origem | Acesso |
| --- | --- | --- |
| `/work/entrada` | fontes brutas; `_gerador/` coberta por tmpfs vazio | somente leitura |
| `/work/landing` | `.<destino>.tmp-<id>`, renomeada para `<destino>` no sucesso | escrita |

A barreira é a montagem, não o código: a ingestão nunca vê `_gerador/` nem `evaluation/`.

## Detecção (nada fixado por empresa)

| Item | Regra |
| --- | --- |
| Codificação | UTF-8 estrito (com BOM → `utf-8-sig`); senão `cp1252`; senão `latin-1`. |
| Separador | Entre `;` `,` `\|` e tab, o que dá número de campos mais constante e maior que 1 nos primeiros 50 registros. Respeita aspas. |
| Cabeçalho | Sim se algum nome estiver preenchido e nenhum parecer número ou data. Sem cabeçalho, as colunas viram `coluna_1..n`. Nome vazio vira `coluna_<posição>`, e nome repetido (sem diferenciar maiúsculas) ganha `__2`. Os nomes originais ficam no manifesto. |
| Linha malformada | Número de campos diferente do cabeçalho, aspas inválidas ou linha vazia: vai para `_rejeitados` com a linha física e o texto bruto. |
| Tipo de XML | Vem do elemento raiz: `cteProc` ou `procEventoCTe` (namespace do CT-e). Raiz desconhecida, estrutura inesperada ou XML malformado vão para `_rejeitados`. |

O parser de XML não resolve entidades, não carrega DTD e não acessa a rede.

## Landing zone

A landing espelha as pastas da entrada:

| Arquivo | Grão | Linhagem |
| --- | --- | --- |
| `<pasta>/<nome>.parquet` | uma linha por registro de `<pasta>/<nome>.csv` | `_arquivo`, `_linha` (linha física; o cabeçalho é a 1) |
| `<pasta>/cte.parquet` | uma linha por XML `cteProc` | `_arquivo`, `_xml_sha256` |
| `<pasta>/cte_nfe.parquet` | uma linha por `infDoc/infNFe` (`_ordem`) | idem |
| `<pasta>/cte_carga.parquet` | uma linha por `infCarga/infQ` (peso `cUnid=01`, m³ `cUnid=00`) | idem |
| `<pasta>/cte_evento.parquet` | uma linha por XML `procEventoCTe` | idem |
| `_rejeitados.parquet` | uma linha por registro ou XML recusado (sempre existe) | `_arquivo`, `_linha` ou `_xml_sha256`, `motivo`, `conteudo_bruto` |
| `manifesto.json` | um por ingestão | — |

Os campos do CT-e são fixados pelo XSD 4.00 ([`cte.py`](cte.py)), porque o layout é padrão nacional. Tag ausente vira `NULL`; tag presente e vazia vira `''`. A chave `chCTe` sai de `infCte/@Id` sem o prefixo `CTe`, e o `Id` bruto fica em `infCte_Id`.

Colunas com dado pessoal ou cadastral (CNPJ/CPF e nomes de `rem` e `dest`) aparecem como no XML. Aqui são fictícias. Com dados reais, o plano precisaria tratá-las conforme a LGPD.

### Manifesto

`manifesto.json` traz:
- o rótulo de dados sintéticos;
- `codigo`: versão, sha256 dos fontes do pacote e versões de python, duckdb e lxml;
- `totais`;
- `tabelas`: arquivo, origem, linhas e esquema;
- `rejeitados`;
- `arquivos`: caminho, sha256, bytes e tipo, mais, para CSV, codificação, separador, cabeçalho, nomes originais, linhas e rejeitadas e, para XML, o tipo de documento.

Ele alimenta a linhagem e o profiling (K05). Não tem carimbo de tempo: duas ingestões das mesmas fontes geram manifesto e Parquet **idênticos byte a byte** (testado).

A medição (tempo, CPU e pico de memória) sai na última linha do stdout do contêiner, fora do manifesto.

## Implementação

| Módulo | Papel |
| --- | --- |
| [`csv_bruto.py`](csv_bruto.py) | Detecção e leitura de CSV com o módulo `csv` da biblioteca padrão. |
| [`cte.py`](cte.py) | Parser do CT-e 4.00 e do evento (lxml). |
| [`parquet.py`](parquet.py) | Gravação: NDJSON temporário → `read_json(columns=...)` → `COPY ... (FORMAT parquet)`, com uma thread. |
| [`landing.py`](landing.py) | Percorre a entrada, monta as tabelas, `_rejeitados` e o manifesto. |
| [`__main__.py`](__main__.py) | `python -m korda_ingestao <entrada> <saida>`. |

Por que NDJSON: no duckdb 1.5.6, `executemany` gravou ~2 mil linhas/s e `unnest` de listas ~3 mil, contra ~200 mil linhas/s do NDJSON com esquema explícito, que também preserva a diferença entre `NULL` e `''`. Medido na imagem em 23/11/2026.

## Testes

```bash
# Unitários, dentro da imagem e sem rede (fixtures pequenas montadas em bytes, XML escritos à mão):
docker run --rm --network none --read-only --tmpfs /tmp --user "$(id -u):$(id -g)" \
  -v "$PWD/infra/sandbox:/src:ro" -e PYTHONPATH=/src korda-sandbox:dev \
  python -m unittest discover -s /src/tests -v

# Integração com as empresas (precisa das fontes geradas; ver data/synthetic/README.md):
cd services/execution && python3 -m unittest -v tests.test_ingestao
KORDA_MEDIR_03=1 python3 -m unittest -v tests.test_ingestao.TestIngestao03Reservada   # só medição
```

A integração usa um avaliador próprio. Ele relê os CSV com o `read_csv` do DuckDB, que é outro leitor, e compara célula a célula. Confere também as contagens de `_gerador/contagens.json`, as anomalias de `_gerador/anomalias_plantadas.csv` (duplicatas, cancelamentos, CT-e com várias NF-e, datas vazias, formatos mistos) e o determinismo. O teste pode ler `_gerador/`; a ingestão não.

## Medição (23/11/2026)

Máquina de desenvolvimento (22 CPUs, Docker 29.1.3). O contêiner fica limitado a 1 CPU e 2 GB.

| Empresa | XML | Tempo no contêiner | Tempo de parede (worker) | Pico de memória |
| --- | ---: | ---: | ---: | ---: |
| 01_demo | 3494 | 1,1–1,4 s | 1,5–2,0 s | 105 MB |
| 02_variacao | 677 | 0,2–0,3 s | 0,7–0,8 s | 75 MB |
| 03_reservada (só medição) | 8448 | 2,9–3,5 s | 3,3–3,9 s | 151 MB |

A 03_reservada passou nos 12 testes de integração na primeira execução, sem mudança de código e sem que seus dados fossem abertos para depuração.

## Limites conhecidos

- **Sem validação XSD na ingestão.** O gerador valida 100% dos XML no CI. Com XML de terceiros, o ideal é registrar o resultado do XSD por arquivo.
- **A heurística de cabeçalho pode errar** quando o cabeçalho tem nomes numéricos ou quando a primeira linha de dados parece texto. O manifesto registra a decisão (`cabecalho`) para revisão.
- Uma aspa aberta sem fechamento pode juntar várias linhas num único registro, que vai inteiro para `_rejeitados`. Ele fica registrado, mas a contagem por linha física se perde.
- Só `.csv` e `.xml` (pela extensão) viram tabela. Outros arquivos aparecem no manifesto como `nao_suportado`.
- Todo o conteúdo é carregado em memória antes de gravar. Isso é suficiente para as empresas sintéticas (pico de 151 MB na maior), mas não para exportações grandes.
