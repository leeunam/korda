# Operação do backend de contexto

API e worker usam a mesma imagem Python 3.12, executada como UID/GID 10001.
O banco PostgreSQL 17 e os áudios ficam em volumes privados. A imagem copia somente
o serviço de contexto, sem fontes, gabaritos, arquivos `.env` ou histórico Git.

O Compose padrão foi preparado para o proxy existente do Coolify. Nenhuma porta
do host é publicada por API, worker ou banco. Caddy existe apenas no perfil
`standalone`, para um servidor sem proxy preexistente.

## Configuração e publicação no Coolify

1. Na equipe autorizada, criar projeto `korda` e ambiente `demo`; adicionar uma
   aplicação pelo repositório Git e selecionar a branch de desenvolvimento aprovada.
2. Escolher a estratégia Docker Compose. Definir **Base Directory** como
   `/infra/context` e **Docker Compose Location** como `/compose.yml`. Assim,
   `build.context: ../..` resolve para a raiz do repositório.
3. Cadastrar as variáveis de ambiente a partir do [arquivo vazio](../../services/context/.env.example).
   Manter os segredos somente no Coolify. A imagem deve usar em `CONTEXT_IMAGE_TAG`
   o SHA do commit implantado, para permitir identificar e reconstruir a versão.
4. Configurar `CONTEXT_DB_PASSWORD` com senha aleatória sem caracteres reservados
   de URL. `CONTEXT_DATABASE_URL` deve apontar para o serviço **postgres**, porta
   5432, com o mesmo usuário, banco e senha. O usuário e banco padrão são `korda`.
   Não utilizar o endereço público do servidor para esse tráfego interno.
5. Definir `CONTEXT_BACKUP_DIR` como diretório absoluto, privado e exclusivo desta
   aplicação no servidor. O diretório é montado apenas nos serviços de backup e
   restauração. Não usar `/`, o repositório ou diretórios de outros projetos.
   Criá-lo previamente com permissão 700. O bind explícito usa
   `create_host_path: false`: um caminho inexistente deve interromper o deploy.
6. Configurar a versão da Graph API, o número de teste e credenciais da Meta,
   Deepgram, gateway e identificadores exatos dos dois modelos. A operação real
   exige `CONTEXT_REAL_PROVIDERS` habilitado explicitamente. `provider-check`
   verifica configuração; `model-smoke` realiza uma chamada sintética por modelo.
7. Atribuir domínio HTTPS somente ao serviço **api**, porta interna **8000**.
   Não habilitar o perfil `standalone` no Coolify e não publicar o banco.
8. Implantar o commit revisado. A migração inicializa o contexto e a fila antes
   da API e do worker. Conferir o término bem-sucedido de `migrate`, a saúde da
   API e os logs do worker; `/readyz` comprova acesso ao esquema do banco.

O Coolify resolve caminhos de Compose a partir da base selecionada e adiciona
o roteamento dos serviços com domínio. Os serviços de execução única definem
`restart: "no"` para não reiniciar a migração. [Documentação do Compose no Coolify](https://coolify.io/docs/applications/builds/docker-compose).

O worker recusa provedores desativados ou configuração incompleta; não substitui
o canal ou modelo real por um simulador. Saúde HTTP não comprova que uma entrevista
real ou chamadas pagas tenham passado no aceite.

### Validação do Compose antes do primeiro deploy

O Coolify 4.7.9 não aceita o operador obrigatório `${VAR:?mensagem}` na origem de
um volume. O Compose usa `${CONTEXT_BACKUP_DIR}` em bind mounts de sintaxe longa,
com tipo explícito, e mantém a exigência de valor em `environment`. Informe o
diretório privado na tela de variáveis antes de implantar. Após atualizar a branch,
recarregue a definição do Compose no Coolify.

`backup`, `backup-scheduler` e `restore` usam a imagem
`korda-context-ops:<CONTEXT_IMAGE_TAG>`, construída de `ops/Dockerfile` sobre
PostgreSQL 17. Os scripts ficam em `/ops` dentro da imagem; não dependem de manter
o checkout Git no servidor. O contexto de build contém apenas os scripts.

### Atualização de um deploy com volumes incorretos

Uma origem curta `${CONTEXT_BACKUP_DIR}:/backups` pode ter sido cadastrada pelo
Coolify como volume nomeado quando a variável ainda não estava resolvida. O Coolify
também pode preservar mapeamentos antigos para evitar movimentar dados implicitamente.
O bind de sintaxe longa elimina a inferência de tipo. A troca de mount não migra
arquivos nem autoriza apagar o volume antigo.

1. Manter os volumes do banco e da mídia, a senha e o nome do recurso existentes.
   Não executar `down -v`, prune ou exclusão de volumes.
2. Confirmar `CONTEXT_BACKUP_DIR=/data/coolify/korda-contexto/backups` no ambiente
   deste recurso e o diretório privado já criado no servidor. Não alterar a senha
   de um PostgreSQL já inicializado como parte desta correção.
3. Inspecionar o volume antigo com montagem somente leitura. Se houver backups,
   preservá-los e copiá-los para um destino separado, sem sobrescrever arquivos,
   antes de qualquer limpeza futura. A correção não remove esse volume.
4. Recarregar o Compose da branch. Conferir a definição gerada e Persistent Storage:
   `/backups` deve ser **bind**, com a origem absoluta esperada, e `/ops` não deve
   ter montagem. Se o painel ainda gerar o volume antigo, corrigir somente o
   mapeamento de `/backups`, preservando o volume Docker e seu conteúdo. Não usar
   uma ação do painel que também remova o volume físico.
5. Atualizar `CONTEXT_IMAGE_TAG` para o commit implantado e fazer novo deploy.
   Conferir em `docker inspect` o mount `/backups` com `Type=bind`, origem esperada
   e escrita no agendador (somente leitura no serviço `restore`). Conferir nos logs
   `Backup complete` e os arquivos no diretório privado do host.

Esse comportamento de preservação de mounts antigos está descrito em
[Variables in host paths](https://coolify.io/docs/applications/builds/docker-compose#variables-in-host-paths).
O erro do worker por provedores desativados é independente: manter
`CONTEXT_REAL_PROVIDERS=false` até configurar as contas e credenciais reais.

```bash
python3 -m unittest discover -s infra/context/tests
docker build -t korda-context-ops:verification infra/context/ops
CONTEXT_TEST_OPS_IMAGE=korda-context-ops:verification python3 -m unittest discover -s infra/context/tests
```

## Comandos locais e administração

Executar os comandos seguintes a partir de `infra/context`, com um arquivo de
ambiente privado preenchido. Os mesmos comandos administrativos podem ser usados
no terminal do contêiner `api` no Coolify, omitindo `docker compose exec api`.

```bash
docker compose --env-file ../../services/context/.env config --quiet
docker compose --env-file ../../services/context/.env build
docker compose --env-file ../../services/context/.env up -d
docker compose --env-file ../../services/context/.env ps
docker compose --env-file ../../services/context/.env exec api contextctl provider-check
docker compose --env-file ../../services/context/.env exec api contextctl model-smoke
```

Antes de cadastrar o projeto, disponibilizar `CONTEXT_PROJECT_TOKEN` apenas na
sessão administrativa. O token deve ter pelo menos 24 caracteres e não deve ser
passado na linha de comando. A CLI lê a variável indicada por `--token-env` e
persiste somente seu hash. Não salvar o token em um arquivo de tópicos.

```bash
docker compose --env-file ../../services/context/.env exec -e CONTEXT_PROJECT_TOKEN api \
  contextctl project-create demo --name 'Transportadora sintética' --phone-number-id '<id-meta>'
docker compose --env-file ../../services/context/.env exec api \
  contextctl participant-add demo --wa-id '<id-participante-teste>' --name 'Operação sintética' --role operacao
docker compose --env-file ../../services/context/.env exec api contextctl status demo
docker compose --env-file ../../services/context/.env exec api contextctl usage demo
```

Os identificadores entre `<...>` são substituídos pelo operador e não são valores
de exemplo utilizáveis. Cadastrar também o participante financeiro, papel
`financeiro`. Os papéis autorizados vêm do cadastro. O roteiro logístico padrão
pode ser substituído por `--topics-json`, que recebe um mapa de tópico para papel.

`pause`, `resume` e `close` recebem o ID do projeto. O fechamento registra um marco
de processamento e não concede nenhuma das aprovações do produto. `retry` agenda
o projeto, preservando o limite de tentativas. Uma entrada definitivamente falha
continua bloqueando a ordem até `resolve-input` com seu ID e `--reason` explícito.
`correct-transcript` preserva o original e cria a correção a partir de `--text-file`
e `--reason`. Investigar `uncertain` na caixa de saída antes de qualquer ação;
nunca repetir um envio apenas porque não há confirmação local.

Conferir `/healthz`, `/readyz` e as quatro operações autenticadas de leitura em
`/docs`. Configurar na Meta o callback HTTPS em `/webhooks/whatsapp` e o mesmo
token de verificação. Para o aceite real, enviar texto e áudio pelo participante
de teste, verificar retomada, confirmação pelo papel correto e evidências no
contexto. Não armazenar identificadores ou conteúdo de participantes nos commits.

## Backup diário e antes de atualização

`backup-scheduler` cria uma cópia ao iniciar e a cada 24 horas. Cada cópia reúne
`database.dump`, mídia imutável, `manifest.txt` (versão, horário e commit) e
`SHA256SUMS`. Downloads `.part` não entram. O banco é capturado antes da mídia:
arquivos referenciados por dados já confirmados existem, e arquivos posteriores
extras não alteram o snapshot do banco.

Os diretórios só aparecem como cópias concluídas depois de todos os comandos
passarem. Cópias interrompidas permanecem identificadas por `.partial-*`; não são
aceitas para restauração. Um lock impede duas cópias simultâneas. Se o processo
for interrompido, verificar que nenhum backup está ativo antes de remover apenas
o diretório vazio `.backup.lock`.

Antes de alterar a imagem, executar e guardar o ID retornado:

```bash
docker compose --env-file ../../services/context/.env --profile ops run --rm backup
```

Confirmar um backup concluído nas últimas 24 horas e espaço disponível. Copiar
as cópias para um destino privado fora deste servidor conforme a operação da
equipe. A implementação não elimina cópias antigas automaticamente nem demonstra
recuperação de perda completa do servidor sem essa cópia externa.

## Ensaio de recuperação sem sobrescrever a aplicação

Usar outro nome de projeto Compose para criar PostgreSQL e volume de mídia
isolados. O comando abaixo cria uma **nova** base `ctx_restore_*`; não executa
`DROP`, não recria base existente e não monta o volume de mídia original com escrita.

```bash
docker compose --env-file ../../services/context/.env -p korda-restore-ensaio \
  --profile ops run --rm restore --disposable-target ctx_restore_ensaio '<id-backup>'
```

Antes de repetir, escolher outro nome de projeto e de banco de ensaio. A rotina
recusa mídia de destino não vazia ou uma base que já exista. Ela verifica
checksums, caminhos do arquivo, ausência de links e a presença e hash de cada
áudio referenciado no banco restaurado. Falha deixa o destino de ensaio visível
para diagnóstico e nunca limpa dados automaticamente.

Depois do ensaio, iniciar a API da mesma imagem contra a base restaurada, com o
volume de ensaio montado em `/var/lib/korda/media`, e verificar uma exportação
autenticada. Não iniciar o worker contra essa cópia para evitar repetir efeitos
externos. Registrar o ID do backup, commit, quantidade de revisões, referências
de áudio verificadas e resultado da leitura. A promoção de uma cópia ao destino
real exige decisão do operador, preservando o destino anterior.

## Servidor independente

Somente quando não houver outro proxy nas portas 80 e 443, configurar um domínio
com DNS para o servidor e usar `--profile standalone`. O Caddy mantém certificados
nos seus próprios volumes e encaminha para `api:8000`. No Coolify esse perfil fica
desativado. [HTTPS automático do Caddy](https://caddyserver.com/docs/automatic-https).

## Evidência de verificação

O Compose deve passar em `config --quiet` nos perfis padrão, `ops` e `standalone`.
O build e os testes de backup/restauração devem usar cópias sintéticas isoladas.
Não registrar como publicação ou entrevista real apenas a validação de sintaxe,
o build da imagem ou testes com provedores simulados.

Na implementação de 27/11/2026, passaram a validação dos três perfis, a sintaxe
Bash e um ensaio local em PostgreSQL 17 com duas tabelas sintéticas, uma revisão
e uma mídia: dump, restauração em base nova e verificação do hash referenciado.
Também foram recusados o banco original como destino e um ID com travessia de
diretório. Isso não substitui a verificação da imagem integrada, do servidor ou
da exportação autenticada do contexto real.

Na correção de publicação, o teste da imagem de operações executa o agendador sem
mount de `/ops`, cria um dump em bind mount com arquivo preexistente preservado e
restaura banco e mídia em destinos sintéticos novos. Confere o hash do áudio,
recusa reutilização do destino e verifica rejeição de bind inexistente. O teste
remove somente seus próprios contêineres, rede e volumes de nomes aleatórios.
Isso não comprova o redeploy no Coolify; o mount e o primeiro backup no servidor
precisam ser conferidos após atualizar a aplicação.
