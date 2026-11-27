# Evidências de desenvolvimento · 27/11/2026

Base: origin/main em 2d0197015d9bcdb6ac28bb4886066e438bad4b81.
Branch: feat/entrevista-whatsapp-contexto. Responsável humano: Marcus.
Seis subagentes implementaram frentes isoladas; revisões cruzadas cobriram padrões,
aderência ao plano e casos adversariais. Revisão humana e merge continuam pendentes.

## Verificado localmente

- Python 3.12 em Linux e PostgreSQL 17 reais em contêineres isolados.
- Backend: 123 testes; consumidor/avaliador: 20 testes; contrato anterior: 8 testes.
- Migrações e criação do schema Procrastinate executadas duas vezes em banco novo.
- Agendamento Procrastinate real na mesma transação do recebimento, incluindo rollback.
- Deduplicação, retomada, áudio, falhas transitórias, envio incerto e janela de atendimento.
- Recuperação de job doing órfão sem roubar heartbeat recente; lease de worker exclusivo.
- Resolução de contradição, confirmação por papel e recusa de confirmação condicional/atrasada.
- Correções de transcrição preservam versões e exigem nova confirmação comercial.
- Corte de encerramento ignora entradas posteriores até retomada explícita.
- Leituras MVCC retornam revisão consistente sem esperar o lock de organização.
- Validação dos quatro exemplos v0.2.0; v0.1.0 e seu consumidor não foram alterados.
- Imagem de produção construída; não contém .git, fontes sintéticas ou gabaritos.
- Perfis Compose e sintaxe Bash verificados; backup/restauração ensaiados em PostgreSQL 17
  com revisão e mídia sintéticas, checksum e preservação da origem.
- scripts/check_repo.py e git diff --check.

Os testes usam provedores simulados. Não medem qualidade de transcrição, entrevista
ou raciocínio dos modelos. O controle de chamadas é persistido por projeto; custos
ausentes do gateway não são inventados. O consumidor usa limite conservador de bytes
quando não há contador exato de tokens, identificado como tal no relatório.

## Achados corrigidos

As revisões encontraram confirmação condicional, associação de fala antiga a pergunta
nova, contradições irresolvíveis, jobs órfãos bloqueando a retomada, pendências após o
corte e avaliação vazia ou com citações não recuperadas. Todos ganharam regressões.
Correção técnica de transcrição agora transmite sua origem autenticada separadamente
do texto, sem inserir palavras artificiais na fala do participante.

## Dependências externas

As contas Meta Cloud API, Deepgram e gateway ainda precisam ser configuradas pelo
responsável. Não foram executados smoke tests pagos, entrevista real, avaliação da
IA consumidora real ou medição de custo/latência real. GraphRAG não foi adotado:
não há evidência de consumidor real para justificar a comparação controlada.

A preparação no Coolify não substitui esses testes. A entrega completa do plano,
incluindo demo real e aceite humano, permanece pendente dessas dependências.
