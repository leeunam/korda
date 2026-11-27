# Da entrevista à entrega no painel local

O painel em `/operador` acompanha um projeto da demonstração logística. A descoberta registra as respostas e confirmações, o planejador monta a versão revisável e o worker processa a transportadora sintética `01_demo`. A pessoa responsável pode inspecionar a execução antes de liberar o pacote.

## Preparar os serviços

1. Configure e inicie o [serviço de descoberta](../services/context/README.md) com seu PostgreSQL e os participantes autorizados. No servidor do operador, configure o identificador do projeto em `KORDA_OPERADOR_PROJETO`, a URL da descoberta em `KORDA_OPERADOR_CONTEXTO_URL` e o token daquele projeto em `KORDA_OPERADOR_CONTEXTO_TOKEN`. Para reproduzir exportações imutáveis locais, configure `KORDA_OPERADOR_EXPORTS` com um diretório contendo `<projeto>/<revisão>.json` e deixe a URL da descoberta vazia.
2. No host do [worker](../services/execution/README.md), instale `requirements-worker.txt`, prepare o lote sintético e a imagem `korda-sandbox:dev`. Configure `KORDA_OPERADOR_FONTES` com o diretório da `01_demo`, `KORDA_OPERADOR_RAIZ` com um diretório privado para o registro e os resultados e `KORDA_OPERADOR_DESTINO` com o identificador da pasta de entrega. A demo pelo painel usa o executor roteirizado.
3. Gere um token aleatório para `KORDA_OPERADOR_TOKEN` e disponibilize-o somente aos processos locais do operador e do servidor Next. Inicie o operador na raiz do repositório com `python -m services.execution.korda_execution.operador_http`. O endereço padrão é `127.0.0.1:8790`.
4. No processo Next configure `KORDA_OPERADOR_URL=http://127.0.0.1:8790`. Em `apps/web`, rode `pnpm install --frozen-lockfile`, `pnpm build` e `pnpm exec next start --hostname 127.0.0.1`. Acesse [o painel local](http://127.0.0.1:3000/operador). As decisões usam a identidade declarada pelo operador desta máquina. A autenticação individual de usuários de um painel público exigiria uma integração própria.

## Conferir cada etapa

- Abra o projeto, consulte a revisão da entrevista e importe o conteúdo identificado pelo hash exibido. O operador busca a revisão na fonte configurada pelo servidor. Uma revisão com regra ausente, confirmação conflitante ou perfil incompleto mostra a pendência para a descoberta.
- Depois da resposta e da confirmação pelo papel cadastrado, consulte e importe a nova revisão. Confira as regras, a versão do plano e o destino antes de registrar a decisão. O projeto da demo precisa de um plano compatível com as regras implementadas para o lote.
- A primeira aprovação habilita o início da execução. Acompanhe o estado até o fim do build e confira os três indicadores antes da decisão de entrega. Uma falha continua visível para intervenção.
- Autorize a entrega e promova o pacote. Somente então o painel oferece os arquivos para download. O ZIP é montado na hora a partir do pacote promovido (`entrega.json`, `dados/`, `projeto_dbt/`, `docs_dbt/`, `manifesto.json`), conferido contra o manifesto aprovado, e registra a execução, a versão do plano e a revisão da entrevista.

## Reproduzir o ensaio

O [ensaio de integração](../integration/entrevista_worker/painel_real.py) abre o painel em Chromium, importa revisões de um projeto de teste em PostgreSQL, inicia o worker em Docker, percorre as duas decisões e confere o ZIP baixado. As mensagens usadas no teste são sintéticas. O ensaio exercita o webhook e o processamento da descoberta em ambiente controlado. O envio por um telefone via Meta e o uso de provedores pagos requerem um ensaio separado.
