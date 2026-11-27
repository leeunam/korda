# Entrevista WhatsApp e contexto v0.2

Backend de K04: texto e áudios transcritos pelo WhatsApp, afirmações com evidências,
lacunas, confirmações por papel cadastrado e revisões imutáveis para outras IAs.
Responsável humano: Marcus. Integração em main e aceite exigem revisão humana.

**Estrutura preparada para recuperação por relações; adoção de GraphRAG condicionada
à avaliação do consumidor de contexto.** Pesquisa externa, frontend, inspeção de fontes
e implementação de planejamento/execução ficam fora desta entrega.

## Executar e verificar

Python 3.12, PostgreSQL 17 e uv são necessários. As dependências e o lock são próprios,
preservando os ambientes existentes. Configure as variáveis CONTEXT_* no processo;
o código não carrega arquivos .env automaticamente.

```bash
cd services/context
uv sync --locked
uv run contextctl migrate
uv run uvicorn korda_context.api:create_app --factory --host 127.0.0.1 --port 8000 --no-access-log
# Outro processo, com configuração explícita dos provedores reais:
uv run python -m korda_context.worker
```

As [variáveis de exemplo](.env.example) ficam vazias. Docker Compose pode receber um
arquivo privado por --env-file. Nunca coloque credenciais no Git.

```bash
# CONTEXT_TEST_DATABASE_URL deve apontar para um PostgreSQL descartável.
uv run python -m pytest tests -q
cd ../..
uv run --project services/context python -m pytest evaluation/discovery_v02/tests -q
uv run --project services/context python -m unittest discover -s packages/contracts/context/v0.1.0/tests
python3 scripts/check_repo.py
```

Sem banco de testes, os casos PostgreSQL ficam explicitamente não executados.
Provedores simulados comprovam a mecânica, não a qualidade de modelos reais.

## Configurar a entrevista

```bash
contextctl project-create demo --name 'Transportadora sintética' --phone-number-id ID_DA_META
contextctl participant-add demo --wa-id IDENTIFICADOR_DO_PARTICIPANTE --name 'Operação fictícia' --role operacao
contextctl participant-add demo --wa-id IDENTIFICADOR_DO_FINANCEIRO --name 'Financeiro fictício' --role financeiro
contextctl status demo
contextctl pause demo
contextctl resume demo
contextctl close demo
contextctl usage demo
```

Um número identifica um participante; não limita quantas áreas ele pode representar.
Para uma pessoa responder por operação e financeiro no mesmo WhatsApp, cadastre-a
uma única vez, repetindo `--role`:

```bash
contextctl participant-add demo --wa-id IDENTIFICADOR_DO_PARTICIPANTE --name 'Responsável sintético' --role operacao --role financeiro
```

Como alternativa, mantenha dois participantes, cada um com um papel, como nos
comandos anteriores. Os papéis são autorizações explícitas do operador: o modelo
não pode adicioná-los a partir de uma fala. Cada confirmação registra o papel
exigido pelo tópico e a identidade de quem respondeu. A migração `context_0002`
preserva IDs, histórico e o papel dos cadastros existentes, convertendo-o em uma
lista com um item; não concede outra área automaticamente. `role` permanece como
primeiro papel por compatibilidade, e `roles` contém a lista de autorizações.

project-create lê um token forte de CONTEXT_PROJECT_TOKEN (ou --token-env), armazena
apenas o hash e cria a revisão inicial. Não imprime o token. Telefone ou BSUID e
demais identificadores operacionais ficam privados. Alegar um papel na conversa
não altera a autoridade cadastrada.

O roteiro padrão separa objetivo/processo/fontes/restrições das regras de deduplicação,
cancelamento, elegibilidade, rateio, prazo, completude, data ausente, sábado, unidade e
agregação. Confirmar somente o prazo não fecha OTIF. Rateio exige financeiro; os
demais tópicos padrão exigem operacao. --topics-json permite outro roteiro explícito,
sem embutir respostas esperadas.

## Canal e processamento

GET/POST /webhooks/whatsapp verificam respectivamente CONTEXT_META_VERIFY_TOKEN e
o HMAC do corpo bruto com CONTEXT_META_APP_SECRET. A entrada e seu trabalho são
persistidos na mesma transação antes do ACK. Não há chamada de modelo no webhook.

O worker baixa áudio autenticado (até 10 MiB), transcreve com Nova-3 em português,
solicita propostas ao organizador e valida citações/referências antes de gravar.
O entrevistador usa lacunas atuais; a aplicação escolhe o fato e papel a confirmar.
Uma resposta como confirmo vincula apenas o desafio enviado ao participante.
Uma fala anterior à pergunta não a confirma, mesmo recebida depois por webhook.

Configure CONTEXT_ORGANIZER_MODEL para Sonnet 5.5 e CONTEXT_INTERVIEWER_MODEL para
Haiku 5.5 usando IDs disponíveis no gateway. Não há substituição silenciosa.
contextctl provider-check verifica a presença das configurações; contextctl model-smoke
faz uma chamada sintética por modelo e pode gerar custo. CONTEXT_REAL_PROVIDERS=true
é obrigatório para iniciar o worker real.

O lease PostgreSQL permite um worker por banco, com três trabalhos concorrentes de
projetos distintos. Jobs do mesmo projeto usam um lock. Após queda, jobs órfãos são
recuperados sem roubar heartbeat recente; envios interrompidos ficam incertos.

## Leitura por IA e frontend futuro

O contrato [v0.2.0](../../packages/contracts/context/v0.2.0/README.md) coexiste com
v0.1.0. O planejador atual continua usando v0.1.0; não há conversão silenciosa.
O [OpenAPI versionado](openapi.json) descreve quatro operações GET após
/v1/projects/{project_id}/context/revisions/{revision}:

| Sufixo | Resultado |
| --- | --- |
| /summary | Objetivos, decisões, situação, índice, corte e bloqueios |
| /topics/{topic_id} | Fatos, relações, entidades, lacunas e links entre tópicos |
| /evidence/{evidence_id} | Trecho literal, origem, versão e vínculos |
| /export | Contexto completo validado |

Todas exigem Authorization: Bearer com token do projeto. latest resolve uma revisão
na resposta; consultas seguintes devem usar esse número. Fontes permanecem declaradas
e não inspecionadas. Ausência não vira resposta negativa nem dado inventado.

Fechar registra o corte de recebimento. Mensagens posteriores aguardam retomada e
não bloqueiam a revisão fechada. Contexto pronto, entrevista encerrada e as duas
aprovações do produto são estados distintos.

## Falhas e correções

Uma entrada pendente ou falha não é ultrapassada silenciosamente. Falhas transitórias
têm até três tentativas por entrada/pergunta/envio. Os estados e erros aparecem no
status; contextctl retry agenda continuação sem zerar limites.

```bash
contextctl resolve-input demo ID_DA_ENTRADA --reason 'Participante reenviou por texto'
contextctl correct-transcript demo ID_DO_AUDIO --text-file /caminho/privado/correcao.txt --reason 'Palavra transcrita incorretamente'
```

Correção técnica preserva as versões e cria nova entrada ligada ao áudio original.
Substitui apenas afirmações apoiadas naquele áudio e exige nova confirmação comercial.
Correções de negócio vêm de novas mensagens e preservam predecessores.

Fora das 24 horas de atendimento, a pergunta aguarda nova mensagem. Templates proativos
ficam fora do fluxo. Um envio incerto nunca é repetido automaticamente.

## Publicação e avaliação

Consulte a [operação no Coolify](../../infra/context/README.md) e a
[avaliação do consumidor](../../evaluation/discovery_v02/README.md).
A imagem contém somente o backend; não inclui gabaritos, .git ou dados de clientes.
Backups incluem banco e mídia; restauração é ensaiada em destino novo.

A entrevista real, a qualidade dos modelos, custo observado e necessidade de GraphRAG
dependem de configurar as contas Meta, Deepgram e gateway. Testes com provedores
simulados não permitem declarar a demo pública completa.
