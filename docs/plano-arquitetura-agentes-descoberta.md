# Arquitetura da descoberta da Korda

**Proposta técnica para revisão · 19/11/2026**

A descoberta começa com informações fornecidas pelo cliente, passa por pesquisa e entrevista adaptativa e termina com uma versão do contexto que expõe evidências, conflitos e lacunas. O recorte usa a transportadora fictícia com ERP, TMS e CT-e sintéticos. O último passo deste plano é disponibilizar essa versão para a frente do Gabriel. [Escopo](scope.md) · [Arquitetura de referência](architecture.md) · [Caso sintético e roteiro](plano-entrevista-dados-sinteticos.md)

**Alinhamento de 23/11/2026.** O PR #18 de Gabriel fornece as fontes de referência: uma entrega por pedido, quantidades em volumes e vínculo TMS → pedido ERP → NF-e → CT-e. Nas ambiguidades do desenho anterior, esse é o recorte adotado. O [contrato de contexto v0.1.0](../packages/contracts/context/v0.1.0/README.md) possui schema e exemplos de rateio pendente/confirmado. Os processos e integrações descritos abaixo ainda serão implementados.

## Arquitetura proposta

**Um monorepositório, uma imagem Python e quatro processos com responsabilidades e limites próprios.** O processo único do rascunho anterior simplificava o primeiro ensaio. Para este desenho, a API recebe comandos e serve o estado, o worker de pesquisa faz trabalho de duração variável, o processo de entrevista ao vivo responde com prazo curto e o worker de contexto concentra as escritas canônicas. Duas etapas usam o mesmo organizador porque dependem das mesmas regras de evidência. O modo texto roda pela API e pelo worker de contexto. Os quatro processos podem ficar no mesmo host na demo e reiniciar separadamente.

```mermaid
flowchart LR
    Form["Formulário inicial"] --> API["API e entrevista por texto"]
    API -->|"Dados fornecidos"| Inputs[("PostgreSQL · entradas e fila")]
    Inputs --> Research["Worker · agente pesquisador"]
    Research -->|"Achados e referências"| Inputs
    Media["LiveKit · voz e avatar"] <-->|"Áudio e vídeo"| Voice["Processo de entrevista ao vivo"]
    Voice --> Interviewer["Modelo entrevistador"]
    Voice --> LiveCheck["Modelo de cruzamento rápido"]
    Interviewer -->|"Pergunta e lacuna alvo"| Voice
    LiveCheck -->|"Comparações provisórias"| Voice
    Voice -->|"Turnos finais e sugestões"| API
    Inputs --> Organizer["Worker · agente de cruzamento e organização"]
    Files["ERP, TMS e CT-e sintéticos"] -->|"Perfilamento local"| Organizer
    Organizer --> Context[("PostgreSQL · contexto versionado")]
    Context -->|"Lacunas e evidências relevantes"| API
    API -->|"Visão da sessão e lacunas"| Voice
    Context --> Export["Versão do contexto para revisão"]
```

| Processo | Interface e responsabilidade |
| --- | --- |
| API | Recebe o formulário, registra entradas e turnos, cria sessões de texto/voz, consulta lacunas e disponibiliza versões do contexto. Autoriza acesso por projeto e enfileira trabalho junto da entrada persistida. |
| Pesquisa | Lê apenas as informações necessárias ao seu trabalho, usa ferramentas de pesquisa pública e entrega achados com origem. Publica entradas para o organizador. |
| Entrevista ao vivo | Recebe transcrição e eventos da sala, roda os dois modelos rápidos, registra os turnos na API e dita apenas a pergunta ou mensagem selecionada. Consulta as lacunas pelo mesmo endpoint usado pelo texto. |
| Contexto | Usa o mesmo modelo organizador antes, durante e depois da entrevista. Valida propostas, atualiza afirmações e lacunas e publica revisões em transação. Executa os jobs de perfilamento e fechamento. |

## 1. Pré-onboarding e pesquisa

1. O formulário recebe nome e domínio da empresa quando disponíveis, setor, objetivo do projeto e sistemas ou fontes já conhecidos. Cada campo vira uma entrada **fornecida**, com autor, horário e projeto. O usuário pode corrigir a entrada em uma nova revisão.
2. O **agente pesquisador** gera consultas em duas frentes. A primeira busca a própria empresa e valida a identidade com domínio, localização e outros dados públicos informados. A segunda procura a cadeia de dados provável, com referências do setor, documentação de sistemas citados, formatos como CT-e e fontes de parceiros ou fornecedores que tenham vínculo público identificável. Cada achado indica se descreve **a empresa** ou **uma prática do setor**, a URL, o trecho e a data de captura. Uma empresa ambígua continua marcada como tal. Na demo, os dados da transportadora vêm de páginas fictícias reproduzíveis. A busca pública pode complementar o caso com referências do setor.
3. O organizador recebe um lote com grupos **fornecidas** e **descobertas**. Dentro de descobertas, mantém empresa e setor distinguíveis. Relaciona sistemas, processos, entidades e indicadores, verifica o que veio de cada fonte e propõe as primeiras lacunas. Uma referência setorial sobre TMS pode justificar a pergunta “onde vocês registram a entrega?”. A identificação do sistema usado pela empresa depende de evidência sobre aquela empresa.
4. A API apresenta o briefing com evidências e lacunas priorizadas. O estado da pesquisa fica visível como em andamento, concluída ou parcial. Falha ou limite de busca preserva os achados disponíveis e permite começar a entrevista com as informações fornecidas.

| Função | Stack sugerida |
| --- | --- |
| Formulário e validação | React + TypeScript + Vite em `apps/web/`. FastAPI + Pydantic v2 para validar e persistir as entradas. [Vite](https://vite.dev/guide/) · [FastAPI e schemas](https://fastapi.tiangolo.com/tutorial/schema-extra-example/) |
| Agente pesquisador | **Claude Haiku 5.5** (`claude-haiku-5-5`), SDK `anthropic`, com tarefas e ferramentas explicitamente tipadas em Python. A aplicação controla limite de consultas, páginas, duração e orçamento do job. [Modelos Claude](https://platform.claude.com/docs/en/models/overview) · [Structured Outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs) |
| Pesquisa e extração públicas | **Tavily Search + Extract** via `httpx`. Usar Search para descobrir URLs e Extract nas selecionadas. Guardar trecho com URL, data de captura e referência à versão do conteúdo. As chamadas recebem somente termos aptos a consulta pública. Bancada de testes com resultados de busca e páginas fixados. [Tavily Search](https://docs.tavily.com/documentation/api-reference/endpoint/search) · [Tavily Extract](https://docs.tavily.com/documentation/api-reference/endpoint/extract) |

## 2. Entrevista por voz ou mensagem

A sessão começa com o briefing, a última revisão do contexto e as lacunas ordenadas. Cada sessão tem um ID da Korda. Salas de voz e retomadas por texto apontam para esse ID. A API associa cada pergunta à lacuna que motivou a escolha e distingue pergunta gerada, apresentada e, em voz, interrompida.

| Papel | Modelo e responsabilidade |
| --- | --- |
| Entrevistador | **Claude Haiku 5.5**. Com uma lista de lacunas elegíveis, o histórico recente e as sugestões disponíveis, escolhe o que perguntar, se deve esclarecer a resposta ou se a conversa pode ser encerrada. Retorna a lacuna escolhida e uma pergunta curta em português. A aplicação valida o alvo antes de falar ou mostrar a pergunta. |
| Cruzamento rápido ao vivo | **Gemini 3.1 Flash-Lite** (`gemini-3.1-flash-lite`), SDK `google-genai`. Compara a fala recente com as lacunas e evidências relacionadas. Retorna sugestões de vínculo, resposta parcial, contradição ou termo ambíguo, apontando o trecho que motivou cada sugestão. |
| Cruzamento e organização do contexto | **Claude Sonnet 5.5** (`claude-sonnet-5-5`), o mesmo modelo organizador do pré-onboarding e do pós. Recebe as respostas finais, a pergunta que as motivou e as sugestões disponíveis. Registra observações, aplica a política de evidência e publica as mudanças validadas. |

Os nomes são candidatos iniciais. Usar saídas curtas e estruturadas, validar de novo com Pydantic e registrar por execução o modelo retornado pelo provedor e a versão do prompt. Revisar a escolha com resultados do ensaio em português. [Modelos Claude](https://platform.claude.com/docs/en/models/overview) · [Claude Structured Outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs) · [Gemini 3.1 Flash-Lite](https://aistudio.google.com/docs/models/gemini-3.1-flash-lite) · [Gemini Structured Outputs](https://aistudio.google.com/docs/structured-output)

### Voz ao vivo

1. Enquanto o cliente fala, o reconhecimento envia segmentos parciais. O cruzamento rápido pode rodar em um parcial estável para adiantar a análise, com frequência limitada. Cada sugestão fica vinculada à versão do trecho. Se a frase mudar, descartar a sugestão incompatível. Só a fala final registrada pode sustentar uma mudança canônica.
2. Ao fechar o turno, o processo registra texto, autor, horários disponíveis e pergunta anterior. O cruzador usa o trecho final ou reaproveita a análise compatível. O entrevistador trabalha com a última versão e recebe o resultado do cruzamento se ele chegar dentro do orçamento do turno. Se o cruzamento atrasar, segue com uma pergunta de outro tópico elegível ou pede uma confirmação neutra. Uma indicação provisória de que a lacuna pode ter sido respondida adia aquela pergunta enquanto o organizador a revisa.
3. A API grava o turno e agenda o job do organizador na mesma transação, com uma janela breve para o cruzamento rápido registrar sua sugestão com o mesmo ID. Ao rodar, o job lê o turno final e a sugestão disponível. Se o cruzamento ou a voz falhar, o job ainda processa a fala final. Sugestões que chegam após a janela ficam no histórico do turno para revisão. O entrevistador consulta a revisão mais recente antes da próxima decisão. O atraso de um modelo fica visível nos diagnósticos.
4. A sessão usa reprodução explícita da pergunta via `session.say()`. Interrupções cancelam a fala em curso. A pergunta que o cliente ouviu fica distinguível de uma geração interrompida. O servidor usa o turno comprometido pela sessão como unidade de evidência, agrupando os segmentos de transcrição que o compõem. Na retomada, carrega o histórico persistido e as lacunas, mesmo se houver outra sala.

| Função | Stack sugerida |
| --- | --- |
| Transporte e mídia | **LiveKit Cloud** para WebRTC e **LiveKit Agents SDK em Python** em processo próprio. `@livekit/components-react` no navegador. Tokens curtos, emitidos pelo backend para uma única sala, com permissões conforme o participante. [Pipeline LiveKit](https://docs.livekit.io/agents/models/pipelines/) · [Tokens e permissões](https://docs.livekit.io/frontends/reference/tokens-grants/) |
| Transcrição e detecção de fim de turno | **Deepgram Nova-3** com `pt-BR` e resultados parciais. Usar VAD Silero e o detector de turno do LiveKit, a calibrar no roteiro em português. Vocabulário de ensaio inclui CT-e, OTIF, ERP e TMS. [Idiomas Deepgram](https://developers.deepgram.com/docs/models-languages-overview) · [Plugin Deepgram](https://docs.livekit.io/agents/models/stt/deepgram/) · [Eventos de transcrição](https://docs.livekit.io/reference/agents/events/) · [Detecção de turno](https://docs.livekit.io/agents/logic/turns/turn-detector/) |
| Síntese de voz e avatar | **Cartesia Sonic 3.5**, voz em português (`pt`) via LiveKit Inference, e **Tavus** com o plugin LiveKit em modo `echo` para renderizar a fala entregue pela Korda. **Anam** é o substituto de avatar pelo mesmo SDK. Se o vídeo falhar, a sessão pode retomar só por voz. Se o áudio falhar, a pessoa retoma por texto. [Cartesia no LiveKit](https://docs.livekit.io/agents/models/tts/cartesia/) · [Fala explícita](https://docs.livekit.io/agents/multimodality/audio/#sessionsay) · [Plugin Tavus](https://docs.livekit.io/agents/models/avatar/plugins/tavus/) · [Plugin Anam](https://docs.livekit.io/agents/models/avatar/plugins/anam/) |

### Entrevista por mensagem

O chat web usa **um agente na conversa**, o entrevistador, e envia cada resposta ao mesmo organizador em segundo plano. O cliente pode ler o histórico e responder depois. A API registra a mensagem e confirma seu recebimento imediatamente. Um job de resposta roda o entrevistador após a atualização do contexto ou, no fim do prazo de espera, com aviso de revisão pendente. A API devolve a pergunta persistida por turno, inclusive em novas consultas. A interface exibe o estado com consultas REST periódicas enquanto a sessão estiver ativa. O chat é o caminho mais simples para testar a lógica de ponta a ponta e também serve de retomada para voz.

## 3. Organização do contexto e pós-entrevista

Nesta etapa, o **mesmo organizador** é o único agente ativo. O encerramento inicia a revisão das respostas finais, fontes e sugestões registradas. O organizador também recebe o perfil determinístico dos arquivos autorizados. Quando chega uma confirmação posterior, o mesmo fluxo registra a nova evidência e recalcula os estados afetados.

- **Transcrição e correções.** A voz mantém o texto final capturado pelo processo LiveKit com identificação do turno e tempos disponíveis. Uma fala truncada ou contestada fica sinalizada para revisão. Correções entram como evidência vinculada ao registro anterior, com autoria e horário. O fechamento identifica turnos pendentes, falhas de processamento e suspeitas de incompatibilidade entre a transcrição e o contexto.
- **Perfilamento.** Um job do worker de contexto usa **DuckDB** para CSV e **`defusedxml`** para XML de CT-e. O manifesto fixa caminho autorizado, hash, formato e origem por arquivo. O job roda operações definidas em código para identificar colunas, tipos, nulos, duplicatas e cobertura de chaves. Achados sobre valores e cancelamentos ficam ligados ao arquivo, registro e campo quando disponíveis. O modelo recebe perfis e trechos necessários para a análise, com limites de tamanho. [Leitura CSV no DuckDB](https://duckdb.org/docs/stable/data/csv/overview) · [defusedxml](https://github.com/tiran/defusedxml)
- **Lacunas persistentes.** Cada lacuna tem ID, escopo afetado, prioridade, pergunta sugerida, estado, evidências relacionadas e papel que pode confirmar. Estados iniciais sugeridos **aberta**, **a confirmar**, **respondida** e **em conflito**. Uma resposta vaga ou insuficiente mantém a lacuna aberta. Uma regra de negócio completa precisa da evidência aplicável e da confirmação de um papel autorizado para ficar respondida. Um perfil pode resolver uma lacuna sobre o esquema e deixar pendente a regra de negócio que usa aquela coluna. Um conflito posterior reabre a lacuna e fica visível no histórico.
- **Versão para consumo.** O contexto fica consultável sempre. O fechamento publica uma revisão com fontes e versões, evidências, afirmações e estado, perfilamento, lacunas e último turno processado. Se houver lacuna bloqueante, a versão vai marcada como rascunho com o escopo afetado explícito. A API lista pendências para revisão humana. Se houver nova rodada de perguntas, a sessão volta ao fluxo de entrevista usando a última revisão.

## Como armazenar e recuperar o contexto

**PostgreSQL 17 com um grafo de evidências versionado em tabelas relacionais.** Entidades como o TMS e o CT-e têm IDs estáveis. Afirmações como “o TMS guarda o peso expedido” são registros separados que podem ter várias evidências. As arestas apontam quais evidências sustentam ou contradizem afirmações, quais fontes descrevem entidades e quais lacunas afetam os indicadores. Os registros carregam `project_id`. A origem de uma evidência inclui um localizador verificável, como campos do formulário, URL e trecho, sessão e turno, ou hash do arquivo e registro.

| Dados | Estrutura proposta |
| --- | --- |
| Entradas originais | `sources`, `source_versions` e `turns`. Pesquisa, formulário, conversa e arquivo mantêm o tipo de origem. Duplicatas de ingestão preservam uma única referência, com o mesmo trecho rastreável. |
| Conhecimento e relações | `entities`, `claims`, `claim_evidence` e relações de domínio tipadas. Campos consultados e integridade por chaves estrangeiras. `jsonb` para detalhes específicos de cada origem. |
| Controle da descoberta | `gaps`, vínculos às evidências e indicadores e `context_revisions`. As mudanças carregam autor ou execução do modelo e ficam vinculadas à revisão em que ocorreram. |

Para o roteiro em português, recuperar pelo ID da lacuna, entidades relacionadas, aliases e busca lexical do PostgreSQL. Para pergunta sobre frete, buscar apenas a relação pedido–entrega–CT-e, o que já foi dito sobre rateio e lacunas associadas. Acoplar `pgvector` se a busca lexical perder evidências em testes com paráfrases. Avaliar **Microsoft GraphRAG** se a recuperação precisar sintetizar um corpus maior por temas. Nesse caso, ele funciona como índice derivado e cita IDs do contexto. A edição de lacunas e a proveniência continuam no Postgres. [Busca textual PostgreSQL](https://www.postgresql.org/docs/17/textsearch.html) · [pgvector](https://github.com/pgvector/pgvector) · [Indexação e consultas GraphRAG](https://microsoft.github.io/graphrag/)

### Consistência e exemplo

- A aplicação registra entradas com chaves idempotentes por projeto, sessão e evento. IDs do cliente ou do processo de voz persistem nas tentativas de reenvio. Uma repetição da mesma frase em dois turnos continua sendo dois registros. Ao voltar de uma interrupção, a API sinaliza turnos que ainda precisem ser retomados.
- O organizador lê uma revisão, propõe mudanças com IDs de evidência e valida tipo, escopo e trecho. As alterações entram em uma transação com controle de revisão por projeto. Se outra entrada já tiver mudado a revisão usada, o job relê as evidências relevantes e refaz a proposta antes de publicar. Trabalhos podem ser reexecutados sem duplicar efeitos. O fechamento registra o conjunto de entradas efetivamente processado.
- **Exemplo.** Uma página do setor cita peso para medir ocupação. Na entrevista, o gestor diz “o caminhão lota por peso”. Essa fala sustenta uma observação sobre ocupação. O cruzador identifica que falta a regra de rateio do CT-e compartilhado, e o entrevistador pergunta como o financeiro divide o valor. O organizador mantém a lacuna de rateio aberta enquanto o financeiro precisar confirmar. Em mensagem posterior, o responsável fictício confirma “dividimos pelo peso expedido de cada entrega”. A nova revisão liga a resposta à lacuna e às fontes que contêm os pesos.

## Stack comum e forma de operar

| Camada | Proposta |
| --- | --- |
| Código e dependências | Python 3.12 com `uv` e `uv.lock`, FastAPI + Uvicorn e Pydantic v2. Postgres com `psycopg` 3 e migrações Alembic. TypeScript + Vite com lockfile do pnpm. [uv](https://docs.astral.sh/uv/concepts/projects/sync/) · [psycopg 3](https://www.psycopg.org/psycopg3/docs/) · [Alembic](https://alembic.sqlalchemy.org/en/latest/) |
| Fila e paralelismo | **Procrastinate** com duas filas no Postgres, `research` e `context`. Incluir entrada e job na mesma transação com a conexão Psycopg da API. Cada fila tem concorrência e limites próprios. Configurar recuperação de jobs interrompidos e tentativas limitadas para falhas transitórias. Expor falhas persistentes no estado do projeto, com repetição acionada de forma idempotente. [Jobs na mesma transação](https://procrastinate.readthedocs.io/en/stable/howto/production/external_connection.html) · [Referência Procrastinate](https://procrastinate.readthedocs.io/en/stable/reference.html) |
| Infra da demo | Docker Compose em uma VM Linux com a imagem Python compartilhada, Postgres em volume persistente, arquivos sintéticos montados somente para leitura e frontend estático servido por Caddy via HTTPS. LiveKit Cloud transporta a mídia. Backups do banco e restauração ensaiada antes da demo. [Docker Compose](https://docs.docker.com/compose/) · [HTTPS Caddy](https://caddyserver.com/docs/automatic-https) |
| Acesso e dados | Sessão web com cookie seguro para papéis de consultor e cliente de teste, autorização por projeto no backend e acesso de máquina restrito para os workers. O papel do organizador é o único com escrita no contexto canônico. Dados sintéticos do início ao fim. Guardar chaves no ambiente dos respectivos processos. Explicitar ao participante processamento por provedores externos e manter gravação audiovisual desabilitada por padrão. |
| Medição | Logs estruturados com correlação de projeto, sessão, turno e job. Medir latência por modelo, espera de fila, término da fala até primeiro áudio p50/p95, tokens, minutos de mídia, atraso de revisão e taxa de retomada. Logs operacionais carregam IDs e estados. Trechos de fala ficam no armazenamento restrito de evidências. |
| Testes | `pytest` para contratos, transições e integração com Postgres real via Compose. Playwright para a jornada web com respostas fixadas. Ensaio de voz separado com falas sintéticas, interrupções e troca de canal. [pytest](https://docs.pytest.org/en/stable/) · [Playwright](https://playwright.dev/docs/intro) |

**Mapa no repo.** `services/context/` receberá os módulos de API, pesquisa, entrevista e organização, com pontos de entrada próprios para os quatro processos. `apps/web/` receberá as telas da descoberta. `packages/contracts/` já contém a primeira versão local do contexto logístico; a integração com o consumidor do Gabriel ainda será testada. `infra/` receberá Compose e configurações da demo. Os nomes de tabelas e modelos deste plano continuam sendo propostas. [Contratos](../packages/contracts/README.md) · [Estrutura do repositório](../README.md)

## Ordem de implementação e aceite

1. **Persistência e pré-onboarding.** Montar a base Postgres, fila e organização. Alimentar com formulário e pesquisa fixa. Verificar que origem fornecida e descoberta continuam distinguíveis até a leitura e que uma referência setorial gera hipótese, sem preencher um fato sobre a empresa.
2. **Entrevista por texto e retomada.** Usar o mesmo organizador da pesquisa com o roteiro em duas rodadas. Aceite: primeira rodada mantém o rateio aberto, resposta posterior o resolve com citação, reenvio do mesmo turno mantém uma única entrada e frase idêntica em outro turno tem ID próprio.
3. **Voz e cruzamento em paralelo.** Rodar LiveKit com Nova-3 e Cartesia, primeiro com áudio e depois com avatar. Testar português com siglas, resposta parcial, contradição, interrupção, desconexão e retomada por texto. Meta inicial a validar no ensaio: p95 de até **3 s** entre fim da fala e início da próxima pergunta, com registro separado do atraso do cruzador e do organizador. Comparar custo e latência com e sem avatar antes de fixar o canal da demo.
4. **Consolidação final.** Adicionar perfilamento dos arquivos sintéticos e revisão exportável. Aceite: origem de cada afirmação recuperável, duplicata e cancelamento fiscal visíveis, lacuna bloqueante associada ao indicador afetado e recuperação após falha de worker sem duplicar evidência ou apagar a revisão anterior.

O primeiro alinhamento técnico entre Marcus e Gabriel é a leitura da versão do contexto e dos estados de lacuna. A disponibilidade dos provedores, a qualidade das respostas em português, os limites de custo e a meta de latência dependem do ensaio.
