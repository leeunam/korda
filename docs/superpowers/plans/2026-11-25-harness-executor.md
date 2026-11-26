# Harness do executor (P3) — plano de implementação

> **Status:** plano aprovado em 25/11/2026; Fase A em execução. Nada aqui descreve capacidade pronta antes do commit correspondente.
>
> **Para agentes:** SUB-SKILL OBRIGATÓRIA: use superpowers:subagent-driven-development (recomendado) ou superpowers:executing-plans para executar tarefa a tarefa. Passos usam checkbox (`- [ ]`).
>

## Escopo desta execução (pedido do Gabriel, 25/11)

Executar **só a Fase A (Tarefas 0–9)**, que não depende do #21 do leeunam. As Tarefas 10–15 ficam para depois do merge. Modo: **Native** (implementação nesta sessão, TDD por tarefa, um commit por tarefa na `feat/10-harness-executor`, worktree `../korda-harness` a partir de `origin/main`). Sem push, sem PR, sem chamada a LLM. No fim: resumo com branch, commits, testes executados e o que ficou para depois do merge.

Ajustes desde a primeira versão do plano:
- O corpo do #21 diz que o ensaio de ponta a ponta já exercita a falha de unicidade e a correção. Antes da Tarefa 11, reaproveitar o mecanismo dele em vez de criar `--plantar-falha-duplicata`.
- Conflitos do #21 (simulação de merge): `sandbox.py` (`exigir_manifesto` × cópia direta das fontes; montagem por arquivo ausente na `main`; `rede` configurável), `Dockerfile`, `ci.yml` e `services/execution/README.md`. Nada disso afeta a Fase A.
- Se `pip install claude-agent-sdk` não for possível no ambiente, os testes que dependem do pacote pulam com mensagem, e a fixação da versão fica registrada como pendência.

**Objetivo:** substituir o `corrigir` roteirizado do worker (#21) por um agente real (Claude Agent SDK) atrás de uma interface `Corretor`. O roteirizado fica como plano B, atrás de uma flag. Tentativas, custo e medição ficam registrados (K08, K10 e parte de modelos da K09).

**Arquitetura:** código novo em `services/execution/korda_execution/harness/`, sem tocar em `worker.py` nem em `sandbox.py` até o merge do #21. O harness roda no host (worker), mas o agente só alcança a sandbox pelas seis ferramentas de `FerramentasRestritas`, expostas como servidor MCP em processo. As ferramentas embutidas do SDK ficam desligadas. Um hook `PreToolUse` recusa qualquer escrita fora de `editable_models`. A barreira real continua sendo a montagem somente leitura da sandbox, com só os arquivos de `editable_models` graváveis e `--network none`.

**Tecnologia:** Python ≥ 3.11, `claude-agent-sdk` (versão fixada na Tarefa 0), `unittest` (padrão do repositório), Docker local (`korda-sandbox:dev`), DuckDB/dbt na imagem.

**Especificação:** o pedido do Gabriel nesta sessão (25/11/2026); as issues #8 (K08), #9 (K09) e #10 (K10); [docs/architecture.md](../../architecture.md); o PR #21 (`feat/worker-planejamento`); o contrato `packages/contracts/plan/v0.1.0/` (no #21).

---

## Contexto

A partir de 25/11, Gabriel cuida só do harness e da construção (K08, K10 e modelos da K09). O worker do leeunam (#21, draft, ainda com conflitos) já tem o ciclo limitado `executar_etapa` (`correcao.py` (no #21)), as ferramentas restritas, a sandbox Docker e o avaliador independente. O único ponto em que o LLM entra é o `corrigir(falha, tentativa) -> {ok, erro, custo_centavos}` dentro de `_build` (`worker.py:94-103` no #21), que hoje copia o SQL correto do repositório. O código congela em **28/11/2026**.

### O que a leitura confirmou (com fonte)

| Fato | Onde | Efeito no desenho |
|---|---|---|
| `corrigir` recebe `tentativa` de 1 a 3; `ok: False` escala **na hora**, sem nova tentativa | `correcao.py:60-80` (#21) | O agente devolve `ok: True` quando escreveu algo; quem julga é o rebuild. Se não escreveu nada, devolve `ok: False` com o motivo. |
| `custo_centavos` precisa ser `int ≥ 0`; senão vira `correcao_invalida` | `correcao.py:69-76` | Custo desconhecido é escalado; não inventamos zero. |
| Só a falha do teste `chave_fiscal_unica` vira `codigo="implementacao"`; o resto escala sem chamar o corretor | `worker.py:89-91` | O agente hoje só é chamado para deduplicação de CT-e. Ampliar isso é decisão do leeunam (pergunta L3). |
| `limite` vai de 0 a 3 e vem de `plano.limits.max_repair_attempts_per_step` (`const: 3`) | `correcao.py:22`, `plan.schema.json` | Sem limite próprio no harness; usamos o do plano. |
| A sandbox monta o projeto em modo somente leitura e só os arquivos de `modelos_permitidos` graváveis, com `--network none`, `--read-only` e `--cap-drop ALL` | `sandbox.py:186-213` (#21) | O hook é a terceira camada; a primeira é o kernel. |
| `caminhos.caminho_modelo` aceita só `models/**/*.sql` (YAML recusado) | `caminhos.py:37-47` (na main) | O hook reaproveita essa função. |
| O projeto é copiado como está e o `prata_ctes.sql` do repositório já é o correto, então o build passa e `corrigir` **nunca roda** no fluxo normal | `sandbox.py:183`, `worker.py:97` | O aceite da duplicata exige plantar um modelo ingênuo antes do build (Tarefa 11). |
| Na main, `FerramentasRestritas` **não** tem `ler_plano` nem `inspecionar_fonte`; só o #21 tem | `ferramentas.py` (main) vs #21 | Antes do merge, o harness depende de um `Protocol` próprio, sem importar a classe concreta. |
| `EmissorEventos` grava `dados`, steps em pt (`plano`, `modelos`, `construcao`) e `attempt` até 4; o schema (= front) usa `data`, steps `plan…deliver` e `attempt` de 1 a 3 | `eventos.py` (#21), `packages/contracts/events.schema.json` (main) | Adaptador de eventos isolado (Tarefa 9); não resolvemos a divergência. |
| Pipeline aceita só as 9 regras fixas da 01 | `ingerir.py:validar_regras` (#21) | 02 e 03 exigem parametrizar o pipeline (Tarefas 14 e 15, prioridade baixa). |
| Agent SDK (doc atual): `ClaudeAgentOptions(tools, allowed_tools, disallowed_tools, permission_mode, max_turns, max_budget_usd, hooks, mcp_servers, setting_sources, cwd, env, model)`; `@tool` + `create_sdk_mcp_server`; nome `mcp__<chave>__<ferramenta>`; `HookMatcher` + `permissionDecision: "deny"` também para MCP; `ResultMessage.total_cost_usd/usage/num_turns/subtype` (`error_max_turns`, `error_max_budget_usd`); o pacote Python traz o CLI | code.claude.com/docs/en/agent-sdk/{python,hooks} | Confirma a recomendação. **Não confirmado:** que `tools=[]` desliga todas as embutidas; que `env` é mesclado ao ambiente herdado (a doc diz que sim). Ver mitigações. |

### Decisões tomadas nesta sessão

| Decisão | Motivo | Alternativas descartadas | O que a faria mudar |
|---|---|---|---|
| **Agent SDK + mitigações** (decisão do Gabriel) | Harness pronto, hooks e limites embutidos; alinhado ao §7.3 e ao pitch | Loop próprio na Messages API: mais seguro (nada roda no host), mas exige escrever e manter o loop | Se, na 1ª execução real, a sessão listar qualquer ferramenta fora de `mcp__korda__*`, o corretor aborta e trocamos para a Messages API atrás do mesmo `Corretor` |
| Modelo padrão `claude-opus-5-5` (`KORDA_MODELO`) | Decisão do Gabriel; mais capaz | Sonnet 5.5 ou Haiku 5.5 | Custo medido acima do orçamento |
| Orçamento de **US$ 3,00 por execução** (`KORDA_ORCAMENTO_EXECUCAO_USD`); por tentativa, `min(restante, 3,00/3) × 0,9` | Decisão do Gabriel; o SDK avisa que a estimativa pode passar do teto, então deixamos 10% de folga | Teto único por execução | Medição da K14 |
| `custo_centavos` em **BRL**: `ceil(usd × KORDA_TAXA_USD_BRL × 100)`; taxa padrão **6,00** (`suposicao:equipe`, conservadora); o USD bruto vai para a medição | Casa com `cost_estimate_brl_cents` do plano | Centavos de dólar | Time fixar outra taxa |
| `max_turns` por tentativa = **12** (`KORDA_MAX_TURNOS_TENTATIVA`) | Ler falha, ler modelo, consultar, escrever e rodar o dbt cabem em cerca de 6 a 8 turnos; 12 dá folga sem laço longo | Sem limite | Medição |
| **Portão duplo** para LLM real: `KORDA_CORRETOR=agente` **e** `KORDA_PERMITIR_LLM_REAL=1` **e** `ANTHROPIC_API_KEY` não vazia | A chave não é do Gabriel; nenhum teste ou comando pode gastar crédito por acidente | Só a chave | — |
| Padrão `KORDA_CORRETOR=roteirizado` | O roteirizado garante a demo | Agente como padrão | Depois do aceite real |
| Mitigações do SDK: `tools=[]`; `disallowed_tools` com todas as embutidas (Bash, Read, Write, Edit, MultiEdit, Glob, Grep, WebFetch, WebSearch, Agent, Task, NotebookEdit, TodoWrite); `allowed_tools` só com as 6 `mcp__korda__*`; `permission_mode="dontAsk"`; hook `PreToolUse` sem matcher, que nega tudo fora de `mcp__korda__*`; `cwd` numa pasta temporária vazia; `setting_sources=[]`; o worker roda o SDK com ambiente mínimo; e um verificador de sessão que aborta se o `SystemMessage` de init listar ferramenta não-korda | As embutidas rodariam **no host**, onde estão o repositório e o `evaluation/golden/` | — | — |

### Suposições (não verificadas, marcadas)

- S1. O #21 entra na main sem mudar a assinatura de `corrigir`, `FerramentasRestritas` (6 métodos), `EmissorEventos.emit_event` e o plano v0.1.0. A tabela "O que quebra" lista o impacto de cada mudança.
- S2. `enviar_arquivos` escreve no arquivo montado sem trocar o inode. Se trocasse, a montagem por arquivo perderia a ligação. Verificar no teste Docker da Tarefa 11 (escrever e ler de volta pela sandbox).
- S3. O SDK permite inspecionar a lista de ferramentas da sessão (`SystemMessage` subtype `init`) antes da primeira chamada à API. Se não permitir, o verificador roda no primeiro turno e aborta do mesmo jeito.
- S4. A taxa de 6,00 BRL/USD é `suposicao:equipe`.

---

## Restrições globais

- Nenhuma chamada real a LLM antes da **Tarefa 12**. Testes usam `ClienteLLMFalso`. Testes reais ficam com `@unittest.skipUnless(os.environ.get("KORDA_PERMITIR_LLM_REAL") == "1", ...)`.
- `ANTHROPIC_API_KEY` fica vazia no `.env.example`. O código lê do ambiente e falha com mensagem clara se ela faltar. A chave nunca vai para a sandbox, os eventos, a medição, os logs ou o `repr`.
- A sandbox roda com `--network none` no build e na correção (já é o padrão do #21). O harness não abre rede para a sandbox.
- O executor não escreve em `tests/`, `definicoes/`, fontes, `dbt_project.yml`, `profiles.yml` nem em `evaluation/golden/`. A imposição vem da montagem somente leitura; o hook é camada extra.
- Até o merge do #21: não editar `worker.py`, `sandbox.py`, `correcao.py` nem `ferramentas.py`.
- Do plano, usar só `editable_models`, `limits`, `rules`, `metrics[*].acceptance` e `plan_version`.
- Commits em pt, Conventional Commits, `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Rodar `python3 scripts/check_repo.py` antes de cada commit. Push, PR e merge só com permissão.
- Cada tarefa atualiza, na mesma branch, a documentação que afeta (coluna "Docs" em cada tarefa). Nada simulado aparece como pronto.

## Pontos de foco na revisão

1. **Ferramenta embutida vazando para o agente** (Read/Bash no host): espera-se que a tentativa aborte antes de qualquer chamada. Teste na Tarefa 7 (`test_sessao_com_ferramenta_embutida_aborta`).
2. **Chave ausente, vazia ou só com espaços** com `KORDA_CORRETOR=agente`: espera-se erro claro citando `ANTHROPIC_API_KEY` e `.env.example`, sem traceback do SDK. Teste na Tarefa 1.
3. **Orçamento esgotado no meio da execução** (2ª tentativa gastou o resto): espera-se que a 3ª devolva `ok: False, erro="orçamento de LLM esgotado"` e `custo_centavos: 0`, sem chamar a sessão, e que a etapa escale. Teste na Tarefa 7.
4. **Agente termina sem escrever nada** (desiste ou atinge `max_turns`): espera-se `ok: False` com o motivo, escalação imediata e custo registrado. Teste na Tarefa 7.
5. **Caminho disfarçado** (`models/../tests/x.sql`, `models/prata_ctes.sql/`, `MODELS/prata_ctes.sql`, `models/prata_ctes.yml`): espera-se recusa no hook e nas ferramentas e evento `tool_refused`. Teste na Tarefa 4.

---

## Estrutura de arquivos

```
services/execution/korda_execution/harness/
  __init__.py            # exporta Corretor, fabricar_corretor
  README.md              # o que é agente, o que é simulado, variáveis, como rodar
  config.py              # ConfigHarness.de_ambiente()  (T1)
  tipos.py               # Protocol Corretor, Protocol FerramentasAgente, ResultadoTentativa, usd_para_centavos (T2)
  politica.py            # avaliar_chamada, hook_pre_tool_use (T4)
  ferramentas_agente.py  # ESPECIFICACOES, despachar (T5)
  contexto.py            # projetar_plano, SISTEMA, montar_prompt (T6)
  falso.py               # ClienteLLMFalso, CorretorFalso (T3)
  roteirizado.py         # CorretorRoteirizado (T3)
  agente_sdk.py          # construir_opcoes, CorretorAgente (T7) — único arquivo que importa claude_agent_sdk
  medicao.py             # Medidor (T8)
  adaptador_eventos.py   # traduzir, exportar_execucao, CLI (T9)
  fabrica.py             # fabricar_corretor(config, ...) (T10)
services/execution/tests/harness/
  __init__.py, fakes.py (FerramentasFalsas), test_*.py por módulo
requirements-harness.txt  # claude-agent-sdk==<fixada>
.env.example              # novas variáveis, chave vazia
```

---

## Fase A — antes do merge do #21 (só `harness/`)

### Tarefa 0: Branch, worktree e cópia do plano

**Motivo:** o diretório atual (`feat/6-planejador`) tem arquivos não rastreados de outras branches (`sistemas-simulados`, ingestões, `ci.yml` modificado). Trabalhar nele arrastaria esse material.

- [ ] `git fetch origin && git worktree add ../korda-harness -b feat/10-harness-executor origin/main`
- [ ] Copiar este plano para `docs/superpowers/plans/2026-11-25-harness-executor.md`.
- [ ] `pip index versions claude-agent-sdk`: escolher a versão mais recente com **pelo menos duas semanas** de publicação e fixá-la em `requirements-harness.txt`. Instalar não gasta crédito.
- [ ] `python3 scripts/check_repo.py` → passa.
- [ ] Commit: `docs(harness): adiciona plano de implementação do harness` (`Refs #10`).

Docs: o próprio plano. Chave real: não. Depende de: nada.

### Tarefa 1: Configuração e portão da chave

**Objetivo:** um único lugar que lê o ambiente e decide qual corretor pode rodar. **Motivo:** garantir que nenhum caminho de código chame o LLM sem os três sinais.

**Arquivos:** criar `harness/config.py`, `tests/harness/test_config.py`; modificar `.env.example`; criar `harness/README.md` (seção "Variáveis").

**Interfaces produzidas:**
- `class ErroConfiguracao(ValueError)`
- `@dataclass(frozen=True) class ConfigHarness: corretor: Literal["roteirizado","agente","falso"]; modelo: str; orcamento_execucao_usd: float; max_turnos_tentativa: int; taxa_usd_brl: float; permitir_llm_real: bool; chave_api: str | None = field(repr=False)`
- `ConfigHarness.de_ambiente(env: Mapping[str,str] = os.environ) -> ConfigHarness`

Padrões: `KORDA_CORRETOR=roteirizado`, `KORDA_MODELO=claude-opus-5-5`, `KORDA_ORCAMENTO_EXECUCAO_USD=3.00`, `KORDA_MAX_TURNOS_TENTATIVA=12`, `KORDA_TAXA_USD_BRL=6.00`, `KORDA_PERMITIR_LLM_REAL=` (vazio).

- [ ] Testes (devem falhar primeiro):
  - `test_padrao_e_roteirizado_sem_chave`: `de_ambiente({})` → `corretor == "roteirizado"`, sem erro.
  - `test_agente_sem_chave_falha_com_mensagem`: `{"KORDA_CORRETOR":"agente","KORDA_PERMITIR_LLM_REAL":"1"}` e também `ANTHROPIC_API_KEY="  "` → `ErroConfiguracao` cuja mensagem contém `"ANTHROPIC_API_KEY"` e `".env.example"`.
  - `test_agente_sem_permissao_explicita_falha`: chave presente, sem `KORDA_PERMITIR_LLM_REAL=1` → `ErroConfiguracao` contendo `"KORDA_PERMITIR_LLM_REAL"`.
  - `test_chave_nao_aparece_no_repr`: `"sk-teste" not in repr(cfg)`.
  - `test_valores_invalidos`: orçamento ≤ 0, turnos < 1, taxa ≤ 0 e corretor desconhecido → `ErroConfiguracao`.
- [ ] Rodar `python -m unittest services.execution.tests.harness.test_config -v` → FAIL (módulo inexistente).
- [ ] Implementar `config.py`.
- [ ] Rodar de novo → PASS. `.env.example`: acrescentar as seis variáveis com `ANTHROPIC_API_KEY=` vazia e um comentário: "chave fornecida pelo responsável; nunca commitar".
- [ ] Commit: `feat(harness): adiciona configuração e portão da chave do LLM`.

Docs: `.env.example`, `harness/README.md`. Chave real: não. Depende de: nada.

### Tarefa 2: Tipos estreitos (`Corretor`, `FerramentasAgente`, custo)

**Objetivo:** fixar os únicos contratos de que o harness depende. **Motivo:** isolar o #21, que pode mudar.

**Arquivos:** `harness/tipos.py`, `tests/harness/test_tipos.py`, `tests/harness/fakes.py`.

**Interfaces produzidas:**
- `class Corretor(Protocol): def __call__(self, falha: dict, tentativa: int) -> dict: ...` (retorno: `{"ok": bool, "erro"?: str, "custo_centavos": int | None}`)
- `class FerramentasAgente(Protocol)`: `ler_plano() -> dict`, `inspecionar_fonte(fonte: str) -> dict`, `ler_arquivo(caminho: str) -> dict`, `escrever_modelo(caminho: str, conteudo: str) -> dict`, `rodar_dbt(subcomando: str, selecao: str | None = None) -> dict`, `consultar_sql(sql: str) -> dict` (assinaturas idênticas às do #21)
- `@dataclass class ResultadoTentativa: tentativa: int; corretor: str; ok: bool; motivo_parada: str; turnos: int; tokens_entrada: int; tokens_saida: int; tokens_cache_leitura: int; custo_usd: float | None; custo_centavos: int | None; duracao_s: float; arquivos_escritos: list[str]`
- `usd_para_centavos(usd: float | None, taxa: float) -> int | None` (`ceil(usd*taxa*100)`; `None` → `None`)
- `tests/harness/fakes.py: FerramentasFalsas(modelos: dict[str,str], editable_models, resultados_dbt: list[dict])`: implementa o Protocol em memória e registra as chamadas.

- [ ] Testes: `usd_para_centavos(0.0123, 6.0) == 8`; `usd_para_centavos(None, 6.0) is None`; `usd_para_centavos(0, 6.0) == 0`; `isinstance(FerramentasFalsas(...), FerramentasAgente)` com `runtime_checkable`.
- [ ] FAIL → implementar → PASS → commit `feat(harness): define interfaces Corretor e FerramentasAgente`.

Docs: `harness/README.md` (seção "Contratos de que dependemos"). Chave real: não. Depende de: #21 só pelas assinaturas (S1).

### Tarefa 3: Corretores falso e roteirizado

**Objetivo:** as duas implementações sem LLM. **Motivo:** o falso testa o ciclo; o roteirizado é o plano B da demo.

**Arquivos:** `harness/falso.py`, `harness/roteirizado.py`, testes.

**Interfaces produzidas:**
- `ClienteLLMFalso(roteiro: list[list[tuple[str, dict]]], tokens_por_turno=(1000, 200), custo_usd_por_turno=0.01)`: cada tentativa consome um item do roteiro (lista de chamadas `(nome_ferramenta, entrada)`). Esgotado o roteiro, a tentativa termina sem chamadas.
- `CorretorFalso(cliente, ferramentas: FerramentasAgente, editable_models, cfg, medidor=None, emissor=None)`: cada chamada passa por `politica.avaliar_chamada` e por `ferramentas_agente.despachar` (Tarefas 4 e 5), **o mesmo caminho do agente real**. Retorno: `ok = bool(arquivos_escritos)`.
- `CorretorRoteirizado(ferramentas, modelo: str, conteudo_correto: Callable[[], str])`: reproduz o `corrigir` atual (`worker.py:94-103`), com `custo_centavos=0`.

Ordem de implementação: as Tarefas 4 e 5 vêm antes da parte do `CorretorFalso` que as usa. Esta tarefa fecha depois da 5.

- [ ] Testes do roteirizado: o modelo difere → escreve e `ok: True`; o modelo é igual → `ok: False`, `"já corresponde"`; a leitura falha → `ok: False`; `custo_centavos == 0` sempre.
- [ ] Testes do falso: roteiro com `escrever_modelo("models/prata_ctes.sql", ...)` → `ok: True` e `custo_centavos == usd_para_centavos(0.01*turnos, taxa)`; roteiro vazio → `ok: False, erro` contendo `"sem alteração"`; roteiro com `escrever_modelo("tests/chave_fiscal_unica.sql", ...)` → recusado, `ok: False`, `FerramentasFalsas.chamadas` sem escrita.
- [ ] FAIL → implementar → PASS → commit `feat(harness): adiciona corretores falso e roteirizado`.

Docs: `harness/README.md` (tabela "agente × roteirizado × falso", dizendo que o falso e o roteirizado **não** usam LLM). Chave real: não.

### Tarefa 4: Política e hook `PreToolUse`

**Objetivo:** uma decisão pura de permitir ou negar, usada pelo hook do SDK e pelo cliente falso. **Motivo:** testar a política sem o SDK.

**Arquivos:** `harness/politica.py`, `tests/harness/test_politica.py`.

**Interfaces produzidas:**
- `PREFIXO = "mcp__korda__"`; `FERRAMENTAS = ("ler_plano","inspecionar_fonte","ler_arquivo","escrever_modelo","rodar_dbt","consultar_sql")`
- `@dataclass(frozen=True) class Decisao: permitir: bool; motivo: str`
- `avaliar_chamada(nome: str, entrada: dict, editable_models: frozenset[str]) -> Decisao`. Regras: o nome tem de ser `PREFIXO + uma de FERRAMENTAS`; para `escrever_modelo`, `caminhos.caminho_modelo(entrada["caminho"])` (da main) não pode levantar erro **e** `entrada["caminho"] in editable_models` (igualdade exata).
- `hook_pre_tool_use(editable_models, emissor: EmissorEventos | None) -> Callable[[dict, str | None, Any], Awaitable[dict]]`: devolve `{}` para permitir; para negar, `{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": motivo}}` e emite `tool_refused` com `dados.origem="hook"`. Lê `input_data["tool_name"]` e `input_data["tool_input"]`.

- [ ] Testes (com o 5º ponto de foco):
  - permitido: `mcp__korda__escrever_modelo {"caminho":"models/prata_ctes.sql"}`; `mcp__korda__rodar_dbt {"subcomando":"build"}`.
  - negado: `Bash`, `Read`, `Write`, `Edit`, `mcp__outro__x`; `escrever_modelo` com `tests/chave_fiscal_unica.sql`, `definicoes/fontes.yml`, `models/ouro_kpis.sql` (fora de `editable_models`), `models/../tests/x.sql`, `models/prata_ctes.sql/`, `MODELS/prata_ctes.sql`, `models/prata_ctes.yml`, `/work/projeto/models/prata_ctes.sql`.
  - o hook (via `asyncio.run`) devolve exatamente o dict de recusa e emite 1 evento `tool_refused` num `EmissorEventos` temporário.
- [ ] FAIL → implementar → PASS → commit `feat(harness): adiciona política de ferramentas e hook PreToolUse`.

Docs: `harness/README.md` (seção "Camadas de proteção": kernel → `caminhos`/`FerramentasRestritas` → hook, nessa ordem de autoridade). Chave real: não.

### Tarefa 5: Ferramentas expostas ao agente

**Objetivo:** descrever e despachar as seis ferramentas sobre `FerramentasAgente`. **Motivo:** o mesmo código serve o SDK (via `@tool`) e o falso.

**Arquivos:** `harness/ferramentas_agente.py`, teste.

**Interfaces produzidas:**
- `ESPECIFICACOES: dict[str, tuple[str, dict]]`: nome curto → (descrição em pt, schema JSON com `additionalProperties: false`).
- `async def despachar(nome_curto: str, entrada: dict, ferramentas: FerramentasAgente, registro_escritas: list[str]) -> dict` → `{"content":[{"type":"text","text": json.dumps(resultado, ensure_ascii=False)}], "is_error": not resultado["ok"]}`. Saídas de `rodar_dbt` são cortadas para os **últimos 8.000** caracteres de `stdout + stderr`. Uma escrita aceita entra em `registro_escritas`.

- [ ] Testes com `FerramentasFalsas`: cada ferramenta chega ao método certo; o corte do dbt se mantém; erro vira `is_error: True`; entrada fora do schema (ex.: `caminho` ausente) → `is_error: True` sem chamar a ferramenta.
- [ ] FAIL → implementar → PASS → commit `feat(harness): expõe ferramentas restritas ao agente`.

Docs: `harness/README.md` (lista das ferramentas). Chave real: não.

### Tarefa 6: Contexto e prompt

**Objetivo:** o que o agente vê: a falha, a projeção do plano e os perfis. **Motivo:** depender só dos cinco campos do plano e nunca vazar o gabarito.

**Arquivos:** `harness/contexto.py`, teste.

**Interfaces produzidas:**
- `CAMPOS_PLANO = ("plan_version","editable_models","limits","rules","metrics")`
- `projetar_plano(plano: dict) -> dict`: copia esses campos e, em `metrics`, mantém **só** `acceptance` de cada métrica. Aceita `rules` como `{chave: valor}` (projeção do worker) ou `{chave: {"value":…}}` (contrato) e normaliza para valor.
- `SISTEMA: str` (fixo, estável para cache): papel; só pode escrever em `editable_models`; não pode alterar testes, fontes ou regras; termina escrevendo o modelo e rodando `rodar_dbt("build")`; se não houver correção possível, explica e para sem escrever.
- `montar_prompt(falha: dict, tentativa: int, limite: int, plano_publico: dict, perfis: dict) -> str`: tentativa N de `limite`, o `erro` da falha (já cortado em 1.500 pelo worker), a projeção do plano em JSON ordenado e os perfis.

- [ ] Testes: a projeção descarta `evidence`, `sources`, `destination`, `metrics.*.formula`; o prompt contém `"models/prata_ctes.sql"`, o erro e `"tentativa 2 de 3"`; o prompt **não** contém `"evaluation"`, `"golden"` nem o valor de `ANTHROPIC_API_KEY` do ambiente de teste; a mesma entrada dá o mesmo texto.
- [ ] FAIL → implementar → PASS → commit `feat(harness): monta contexto do agente a partir do plano aprovado`.

Docs: `harness/README.md` (seção "O que o agente vê"). Chave real: não. **Depende do dono da K06:** só dos cinco campos.

### Tarefa 7: `CorretorAgente` com o Agent SDK

**Objetivo:** a implementação real, isolada num arquivo. **Motivo:** trocar de harness (Messages API, Devin, OpenHands) mexe só aqui.

**Arquivos:** `harness/agente_sdk.py`, `tests/harness/test_agente_sdk.py`.

**Interfaces produzidas:**
- `EMBUTIDAS: tuple[str, ...]` (lista das mitigações)
- `construir_opcoes(cfg: ConfigHarness, servidor_mcp, hook, cwd_vazio: Path, max_budget_usd: float) -> ClaudeAgentOptions` com `tools=[]`, `disallowed_tools=list(EMBUTIDAS)`, `allowed_tools=[PREFIXO+n for n in FERRAMENTAS]`, `permission_mode="dontAsk"`, `max_turns=cfg.max_turnos_tentativa`, `max_budget_usd`, `model=cfg.modelo`, `setting_sources=[]`, `cwd=cwd_vazio`, `system_prompt=SISTEMA`, `mcp_servers={"korda": servidor_mcp}`, `hooks={"PreToolUse":[HookMatcher(matcher=None, hooks=[hook])]}`.
- `@dataclass class SaidaSessao: subtype: str; num_turns: int; total_cost_usd: float | None; usage: dict; ferramentas_sessao: list[str]`
- `class ErroSegurancaHarness(RuntimeError)`
- `CorretorAgente(cfg, ferramentas: FerramentasAgente, plano_publico, perfis, limite, emissor, medidor, rodar_sessao: Callable[[str, ClaudeAgentOptions], SaidaSessao] | None = None)`. O `rodar_sessao` padrão usa `claude_agent_sdk.query` dentro de `asyncio.run`: coleta o `SystemMessage` de init (lista de ferramentas) e **levanta `ErroSegurancaHarness` se houver nome fora de `PREFIXO`**, depois o `ResultMessage`.
- Regras de `__call__(falha, tentativa)`:
  1. `restante = cfg.orcamento_execucao_usd - gasto_acumulado`; se `restante <= 0` → `{"ok": False, "erro": "orçamento de LLM esgotado", "custo_centavos": 0}` sem abrir sessão.
  2. `max_budget_usd = min(restante, cfg.orcamento_execucao_usd/3) * 0.9`.
  3. Abrir a sessão; somar `total_cost_usd` ao gasto. Se for `None` → `custo_centavos: None` (o ciclo escala como `correcao_invalida`, sem inventar zero).
  4. `ok = bool(arquivos_escritos) and subtype != "error_during_execution"`. Sem escrita → `erro = f"agente terminou sem alteração ({subtype})"`.
  5. Registrar um `ResultadoTentativa` no medidor e emitir `agent_finished` (step `construcao`) com turnos, tokens, `custo_usd` e `subtype`.
- `claude_agent_sdk` é importado **dentro** das funções; o módulo carrega sem o pacote instalado.

- [ ] Testes (todos com `rodar_sessao` falso; nenhum abre o CLI):
  - `test_opcoes_desligam_embutidas` (pula se o SDK não estiver instalado): `opcoes.tools == []`, `"Bash" in opcoes.disallowed_tools`, `all(t.startswith("mcp__korda__") for t in opcoes.allowed_tools)`, `opcoes.setting_sources == []`, `"ANTHROPIC_API_KEY" not in str(opcoes.system_prompt)`.
  - `test_sessao_com_ferramenta_embutida_aborta`: o `rodar_sessao` falso levanta `ErroSegurancaHarness` → `__call__` repassa a exceção (o ciclo registra `correcao_interrompida`).
  - `test_orcamento_esgotado_nao_abre_sessao`: duas sessões a US$ 1,40 → a 3ª chamada devolve o erro de orçamento e o falso não é chamado.
  - `test_sem_escrita_devolve_ok_false`: `subtype="error_max_turns"`, sem escrita → `ok False`, erro contém `error_max_turns`, custo em centavos > 0.
  - `test_custo_desconhecido`: `total_cost_usd=None` → `custo_centavos is None`.
  - `test_real_duplicata` com `skipUnless(KORDA_PERMITIR_LLM_REAL=="1")`: só esqueleto, quem roda é a Tarefa 12.
- [ ] FAIL → implementar → PASS (com e sem `requirements-harness.txt` instalado) → commit `feat(harness): adiciona CorretorAgente sobre o Claude Agent SDK`.

Docs: `harness/README.md` (mitigações, limites de turnos e orçamento, como trocar de harness). Chave real: **não** (testes com sessão falsa).

### Tarefa 8: Medição

**Objetivo:** tempo, tokens, tentativas e custo por execução (insumo da K14).

**Arquivos:** `harness/medicao.py`, teste.

**Interfaces produzidas:** `Medidor(run_id, corretor, modelo)`; `.registrar(r: ResultadoTentativa)`; `.resumo() -> dict` (`tentativas`, `turnos`, `tokens_entrada`, `tokens_saida`, `tokens_cache_leitura`, `custo_usd`, `custo_centavos`, `custo_completo: bool`, `duracao_s`, `por_tentativa: list`); `.gravar(caminho: Path)`, que grava `medicao.json` com `"synthetic": true` quando o corretor ≠ agente.

- [ ] Testes: soma de duas tentativas; `custo_completo=False` se alguma tiver custo `None`; JSON sem a chave; `synthetic` correto.
- [ ] FAIL → implementar → PASS → commit `feat(harness): registra medição por execução`.

Docs: `harness/README.md` (formato do `medicao.json`). Chave real: não.

### Tarefa 9: Adaptador de eventos para o front

**Objetivo:** uma camada fina que traduz o JSONL do worker para o `RunEvent` do front (`apps/web/src/lib/events.ts`). **Motivo:** o backend de eventos e o front podem mudar; este é o único ponto de contato. **Não resolve a divergência:** o mapeamento é provisório e listado no README.

**Arquivos:** `harness/adaptador_eventos.py`, teste.

**Interfaces produzidas:**
- `MAPA: dict[tuple[str, str], tuple[str, str]]` (step, type do worker → step, type do front). Provisório:

  | worker | front |
  |---|---|
  | `plano/run_started` | `plan/task_started` |
  | `modelos/test_failed` | `run_dbt/test_failed` |
  | `modelos/test_passed` | `run_dbt/test_passed` |
  | `modelos/fix_started` | `agent/task_started` |
  | `modelos/fix_applied` | `agent/fix_applied` |
  | `construcao/file_written` | `agent/file_written` (`data.file = dados.caminho`) |
  | `construcao/tool_refused` com ferramenta `escrever_modelo` ou `origem=hook` | `write_hook/write_blocked` |
  | demais (`intervention_requested`, `evaluation_finished`, `run_failed`, `agent_finished`, `dbt_*`, `query_*`) | **não mapeados** → `None` |
- `traduzir(ev: dict) -> dict | None`: troca `dados` por `data`; se `attempt` ∉ 1..3 → `attempt: None` e `data.attempt_original`.
- `exportar_execucao(jsonl: Path, *, synthetic: bool) -> dict` → `{"run_id","synthetic","note","events":[...],"nao_mapeados":{tipo: n}}` (mesmo formato de `seed-run.json`).
- CLI: `python -m services.execution.korda_execution.harness.adaptador_eventos <eventos.jsonl> [--synthetic]`.

- [ ] Testes: cada linha da tabela; um evento traduzido valida contra `packages/contracts/events.schema.json` (jsonschema, como em `packages/contracts/context/v0.1.0/validate.py`); `attempt=4` → `None`; não mapeados são contados e não exportados.
- [ ] FAIL → implementar → PASS → commit `feat(harness): adiciona adaptador provisório de eventos para o front`.

Docs: `harness/README.md` (tabela + "provisório, pendente da K01 e do José"); `packages/contracts/README.md` (uma linha apontando o adaptador). Chave real: não. **Depende do José e da K01.**

---

## Fase B — depois do merge do #21

> Se o #21 não entrar até **27/11 às 12h**, fazer as Tarefas 10 e 11 numa branch criada a partir de `origin/feat/worker-planejamento`, com o leeunam avisado, para não perder a demo. Não reescrever a branch dele.

### Tarefa 10: Ligar o `Corretor` ao worker

**Objetivo:** o worker escolhe o corretor por configuração. **Motivo:** é a única mudança no `worker.py`.

**Arquivos:** criar `harness/fabrica.py`; modificar `korda_execution/worker.py` (`_build` e o trecho em que monta `ferramentas`/`perfis`); modificar `services/execution/README.md`.

**Interfaces:**
- `fabricar_corretor(cfg, *, ferramentas, plano_publico, perfis, limite, emissor, medidor, projeto: Path, modelo: str) -> Corretor`
- `_build(ferramentas, eventos, limite, verificar_ativa, corretor: Corretor)`. O `corrigir` interno vira `verificar_ativa(); ferramentas.attempt = tentativa + 1; return corretor(falha, tentativa)`.
- `executar(...)` lê `ConfigHarness.de_ambiente()` **antes** de criar a sandbox (erro de chave falha cedo) e grava `revisao/<run>/medicao.json`.

- [ ] Testes: `test_worker_docker` existente com `KORDA_CORRETOR=roteirizado` → mesmo resultado de antes; `KORDA_CORRETOR=agente` sem chave → `ErroConfiguracao` antes do `docker run`.
- [ ] Rodar `python -m unittest discover -s services/execution/tests` → PASS (testes Docker pulam sem a imagem).
- [ ] Commit `feat(execution): escolhe o corretor por configuração no worker`.

Docs: `services/execution/README.md`, linha "Correção" (agente × roteirizado, variável `KORDA_CORRETOR`, o que é simulado). Chave real: não. **Depende do #21.**

### Tarefa 11: Aceites da K08 e da K10 sem LLM (Docker + cliente falso)

**Objetivo:** dois dos três aceites, com evidência. **Motivo:** não gastar crédito no que dá para provar sem LLM.

**Arquivos:** `services/execution/tests/test_aceite_harness.py`; `services/execution/pipeline/cenarios/prata_ctes_sem_dedup.sql` (modelo ingênuo **sintético**, fora de `projeto/`, não montado na sandbox); `worker.py`: opção `--plantar-falha-duplicata`, que, depois de `sandbox.criar()`, chama `ferramentas.escrever_modelo(MODELO_CTE, ingenuo)` e emite `scenario_planted` (step `modelos`), deixando claro que é cenário de demo.

- [ ] `test_falha_sem_solucao_atinge_limite` (Docker, cliente falso): falha plantada e roteiro com 3 tentativas que escrevem SQL ainda sem dedup → `resultado["codigo"] == "limite_atingido"`, `correcoes == 3`, 1 evento `intervention_requested`, `custo_centavos` = soma das 3, `medicao.json` com 3 tentativas, avaliação **não** executada.
- [ ] `test_escrita_em_teste_ou_fonte_recusada` (Docker, cliente falso): o roteiro tenta `escrever_modelo("tests/chave_fiscal_unica.sql")` e `("definicoes/fontes.yml")` → recusado pelo hook (evento `origem=hook`). Com o hook desligado no teste, a recusa vem de `FerramentasRestritas`. E uma escrita direta via `sandbox.rodar_comando(["sh","-c","echo x > /work/projeto/tests/chave_fiscal_unica.sql"])` → código ≠ 0 com "Read-only file system" (o kernel). Conferir que o hash do arquivo no host não mudou.
- [ ] `test_correcao_falsa_corrige_duplicata` (Docker, cliente falso, roteiro que escreve o SQL correto): build passa na 2ª rodada e `avaliar` aprova. Confirma a S2.
- [ ] Commit `test(execution): prova limite, recusa de escrita e correção com cliente falso`.

Docs: `services/execution/README.md` (cenário plantado é demo); `harness/README.md` (como reproduzir os aceites). Chave real: não. **Depende do #21 e da imagem `korda-sandbox:dev`.**

### Tarefa 12: ⚠️ PRIMEIRO PASSO QUE EXIGE A CHAVE REAL — aceite "a duplicata falha e o agente corrige"

**Objetivo:** um único ensaio real no `01_demo`. **Pré-requisitos:** Gabriel fornece a chave (que não é a pessoal dele) e autoriza **nesta hora** ("pode rodar"). Tarefas 0–11 verdes.

- [ ] Gabriel exporta `ANTHROPIC_API_KEY`, `KORDA_CORRETOR=agente`, `KORDA_PERMITIR_LLM_REAL=1` no shell dele (fora do Git).
- [ ] Rodar o worker em `01_demo` com `--plantar-falha-duplicata` e `--run-id aceite-agente-001`.
- [ ] Verificar: o 1º evento do agente mostra `ferramentas_sessao` só com `mcp__korda__*` (senão parar); `test_failed` → `fix_applied` → `test_passed`; `avaliacao.json` aprovado; `medicao.json` com custo ≤ US$ 3; nenhum arquivo fora de `models/prata_ctes.sql` alterado (hash dos `tests/` e `definicoes/`).
- [ ] Guardar `eventos.jsonl`, `medicao.json` e o export do adaptador como evidência no PR (sem a chave).
- [ ] Se falhar: **não** repetir em laço. Registrar e decidir com o Gabriel antes de outra execução paga.

Docs: `harness/README.md` (resultado medido, marcado como ensaio único e sintético). Chave real: **SIM**.

### Tarefa 13: Fechamento da documentação e rascunho do PR

- [ ] `grep -rn "roteirizad\|corrigir\|KORDA_" services/ docs/ packages/` → nenhuma referência desatualizada.
- [ ] `services/execution/README.md`: o que é agente, o que é simulado ou roteirizado, as variáveis e o portão duplo.
- [ ] `python3 scripts/check_repo.py` e todos os `unittest discover` → PASS.
- [ ] Rascunho do PR conforme `.github/pull_request_template.md`, título `feat(execution): harness do executor com limite e custo (#10)`. Entregar ao Gabriel; **não abrir**.

---

## Fase C — prioridade baixa (cortar primeiro)

### Tarefa 14: K09 — pipeline lê regras do plano (cenário 02)

**Objetivo:** `ingerir.py` e os modelos aceitam as variações de `rules` (`rateio_cte` ∈ {peso, volume, valor}, `ocupacao_unidade` ∈ {kg, m3}, `prazo_conta_sabado`, `excluir_tipos_viagem` como TRF, `sem_data_realizada`) por `vars` do dbt, sem SQL por cenário. **Arquivos:** `services/execution/pipeline/projeto/ingerir.py` (`REGRAS_SUPORTADAS` → conjunto de valores aceitos), os modelos `prata_rateios.sql` e `ouro_*.sql`, `pipeline/tests/test_pipeline.py`. **Teste:** `02_variacao` bate com `evaluation/golden/02_variacao/kpis.json` **pelo avaliador independente** (nunca lendo o golden no pipeline). **Depende de:** leeunam (dono do pipeline), K06 (valores de `rules`) e K02. Docs: `pipeline/README.md`. Chave real: não.

### Tarefa 15: Medição no cenário 03 (K14)

Rodar uma vez `03_reservada` com o corretor configurado, **sem ajustar nada depois**, e registrar `medicao.json` + o laudo. Se for com o agente, exige a chave e autorização própria. Docs: `evaluation/README` ou `docs/` conforme a K14.

---

## O que quebra se um ponto estreito mudar

| Ponto | Se mudar… | Onde ajustar |
|---|---|---|
| Assinatura `corrigir(falha, tentativa) -> {ok, erro, custo_centavos}` | `Corretor` e os três corretores | `tipos.py`, `fabrica.py` (1 lugar) |
| `codigo="implementacao"` só para `chave_fiscal_unica` | O agente passa a ser chamado em outras falhas: nada quebra, mas o prompt pode precisar de contexto | `contexto.py` |
| Métodos de `FerramentasRestritas` (nomes, retorno `{ok, …}`) | `FerramentasAgente` e `despachar` | `tipos.py`, `ferramentas_agente.py` |
| `EmissorEventos.emit_event(step, type, message, attempt, **extra)` | Hook, `agent_finished` e adaptador | `politica.py`, `agente_sdk.py`, `adaptador_eventos.py` |
| Plano: `editable_models`, `limits`, `rules`, `metrics[*].acceptance`, `plan_version` | Projeção e política | `contexto.py`, `politica.py` |
| Montagem por arquivo / `enviar_arquivos` (S2) | Escrita do agente some ou cai no kernel | `sandbox.py` (leeunam) |
| Política de rede configurável na ingestão | Nada no harness, desde que o build e a correção continuem com `none` | Verificar no teste da Tarefa 11 |
| Ingestão escolhida (`korda_ingestao` × `ingerir.py`) | Só a Tarefa 14 | `pipeline/` |
| Harness (Devin, OpenHands, Messages API) | Só `agente_sdk.py` | Novo `Corretor` |
| Backend de eventos e front | Só `adaptador_eventos.py` | — |
| Sandbox em nuvem | Nada, se implementar o `Protocol Sandbox` | Fora do escopo |

## Perguntas abertas

**Para o leeunam (#21):**
- L1. A assinatura de `corrigir` e os 6 métodos de `FerramentasRestritas` ficam como estão depois de resolver os conflitos?
- L2. Política de rede: no build e na correção continua `--network none` fixo, mesmo que a ingestão fique configurável?
- L3. Só `chave_fiscal_unica` vira `implementacao`? Ampliar a classificação (ex.: falha de conservação do rateio) é dele ou do harness?
- L4. Posso acrescentar ao `worker.py` a opção `--plantar-falha-duplicata` (cenário de demo) e o parâmetro `corretor` em `_build`?
- L5. `enviar_arquivos` preserva o inode do arquivo montado (S2)?
- L6. Qual ingestão fica (`korda_ingestao` × `ingerir.py`)? Afeta só a Tarefa 14.
- L7. Previsão de merge do #21? (Cria o plano B de 27/11.)

**Para o José (P4):**
- J1. O mapeamento provisório da Tarefa 9 serve? Como representar `intervention_requested` (escalonamento) e `evaluation_finished` no grafo?
- J2. `attempt` 4 (o rebuild depois da 3ª correção) vira `null` ou o schema passa a aceitar 4?
- J3. O front pode carregar um JSON exportado pelo adaptador no lugar de `seed-run.json` enquanto não há backend?
- J4. Quem fecha `events.schema.json` na K01, e a promoção (aprovação 2) entra lá?

**Para o dono da K06:** o plano continuará trazendo `rules` com os valores da Tarefa 14 e `metrics[*].acceptance` em texto?

## Calendário até 28/11 (sugestão)

| Dia | Meta |
|---|---|
| Qua 25/11 | Tarefas 0–4 |
| Qui 26/11 | Tarefas 5–9 (Fase A completa, sem chave) |
| Sex 27/11 | Manhã: Tarefas 10–11 (depois do merge, ou plano B às 12h). Tarde: **Tarefa 12, com a chave e autorização** |
| Sáb 28/11 | Tarefa 13 + congelamento. Tarefas 14–15 só se sobrar tempo |

**Ordem de corte se faltar tempo:** (1) Tarefas 14 e 15 (02 e 03); (2) Tarefa 8 (medição; os eventos já carregam o custo); (3) Tarefa 9 (o front segue com o seed sintético); (4) Tarefa 12 (sem ela, a demo usa `KORDA_CORRETOR=roteirizado`, documentado como roteirizado). O roteirizado garante a demo.

## Verificação ponta a ponta

1. `python3 scripts/check_repo.py`
2. `python -m unittest discover -s services/execution/tests -v` (harness + worker; o Docker pula sem a imagem)
3. `docker build -t korda-sandbox:dev infra/sandbox` e repetir 2 → aceites da Tarefa 11 com cliente falso
4. `python -m services.execution.korda_execution.harness.adaptador_eventos runs/worker/revisao/<run>/eventos.jsonl --synthetic` → JSON válido contra `events.schema.json`
5. Só com autorização: Tarefa 12

## Revisão de 25/11/2026 (tarde): o harness constrói; o worker orquestra

**Decisões do Gabriel:**
1. A chave disponível é do gateway da Feita (`https://api.feita.ai/gateway/v1/chat/completions`, formato OpenAI). O Agent SDK não fala esse formato. O executor principal passa a ser `chat`: loop próprio de ferramentas, só com a biblioteca padrão. O `agente_sdk` fica guardado.
2. **O harness constrói o pipeline inteiro (bronze, prata e ouro) a partir do plano**, e corrige até 3 vezes. O pipeline feito à mão do #21 vira o executor `roteirizado` (plano B), fora do alcance do agente.
3. **O worker só orquestra:** (a) uma chamada de API gera o documento-base a partir do contexto das entrevistas e do plano; (b) prepara a sandbox; (c) chama `construir_e_verificar`; (d) avaliador, aprovação 2 e entrega.
4. Orçamento de US$ 8 por execução: construção até 60%; correções dividem o restante. Custo estimado por tokens, porque a Feita cobra em créditos. O custo vai para o front em `data` dos eventos.

**Já implementado (sem LLM, sem #21):** `config.py` (executores e variáveis), `cliente_chat.py`, `sessao_chat.py`, `executor_chat.py`, `ConstrutorRoteirizado`, contexto de construção (tarefas em ordem topológica e métricas completas), `editable_models` com padrão `models/*`, `documento_base.py`, `orquestracao.py` e o custo no adaptador.

**Nova Fase B (depois do merge do #21), substitui as Tarefas 10–12:**

| # | Passo | Arquivos | Chave real? |
|---|---|---|---|
| B-a | ✅ Feito em 25/11 com autorização: o gateway devolve `tool_calls`, aceita `role: tool` e informa `usage`; cerca de US$ 0,005. Exigiu `User-Agent` próprio (Cloudflare 1010) | `harness/fumaca.py` | Sim (usada) |
| B-b | Worker: trocar o build do pipeline à mão por `gerar_documento_base` + `construir_e_verificar`; `KORDA_EXECUTOR` escolhe o executor; gravar `documento_base.md` e `medicao.json` em `revisao/<run>/` | `worker.py` (#21) | Não |
| B-c | Sandbox: projeto começa com `models/` vazio e gravável; `tests/`, `definicoes/`, macros e configuração só leitura; o pipeline à mão nunca é montado (só copiado pelo `roteirizado`) | `sandbox.py`, `worker.py` (#21) | Não |
| B-d | Contrato do plano: `editable_models` aceitar `models/*` (hoje é `const` de `models/prata_ctes.sql`); worker deixa de exigir a lista fixa; toda falha de teste ou compilação nos modelos vira `implementacao` | `plan.schema.json`, `worker.py` (#21; K01/K06) | Não |
| B-e | Aceites sem LLM (Docker + `ClienteChatFalso`): construção falsa escreve o pipeline e o avaliador aprova; falha sem solução chega ao limite; escrita em teste ou fonte recusada pela política e pelo kernel | testes (#21) | Não |
| B-f | Ensaio real no `01_demo` com `KORDA_EXECUTOR=chat`: documento-base, construção, correções, avaliador; anotar o saldo de créditos antes e depois | — | **Sim** |
| B-g | Pacote de entrega (proposta, K13): projeto dbt, resultados, `dbt docs`, `decisoes.md`, `execucao.md` (o que o agente fez e quanto custou), manifesto | promoção (#21) | Não |

**Mudança pedida ao leeunam (#21):**
- O worker deixa de rodar o pipeline à mão como caminho principal. Ele chama `gerar_documento_base` e depois `construir_e_verificar(construtor, corretor, tentar, executar_etapa, registrar, limite=…, documento_base=…)`.
- A sandbox começa com `models/` vazio.
- O pipeline à mão vira o executor `roteirizado`.
- A classificação `implementacao` passa a cobrir qualquer falha de teste ou compilação de modelo, não só `chave_fiscal_unica`.
- `editable_models` passa a aceitar padrão.
- Perguntas:
  1. O documento-base passa pela aprovação 1, junto com o plano?
  2. Quem mantém o `plano.py` por template, já que ele substitui a K06 por enquanto?
