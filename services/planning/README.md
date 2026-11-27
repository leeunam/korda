# P2 · Planejamento

O planejador gera uma proposta revisável para os três indicadores da transportadora sintética. Cada indicador referencia suas fontes, chaves, regras, fórmula, denominador e verificações de aceite. As tarefas especificam os resultados verificáveis das camadas bronze, prata e ouro. O plano conserva os IDs e as evidências do contexto de descoberta.

## Gerar e validar

A partir da raiz do projeto, instale as dependências de contratos em um ambiente Python 3.11 ou superior e execute o exemplo sintético.

```bash
python3 -m pip install -r requirements-contracts.txt
export PYTHONPATH=services/planning
python3 -m korda_planning packages/contracts/context/v0.1.0/examples/02_rateio_confirmado.json \
  --destino painel-demo --custo-estimado-centavos 125 > /tmp/plano-korda.json
python3 -m korda_planning --validar /tmp/plano-korda.json
python3 -m unittest discover -s services/planning/tests
```

O destino e os R$ 1,25 do comando são valores fictícios de entrada. Quando omitidos, seus campos ficam nulos para revisão. O destino é um identificador lógico que a aplicação associa ao destino real. A estimativa está em centavos inteiros de real. No modo padrão, N0, o lote cobre os arquivos exportados autorizados.

O contexto de rateio pendente gera um rascunho com custo bloqueado. OTIF e ocupação já podem ser revisados. A confirmação fictícia do financeiro gera outra versão que pode receber a primeira aprovação humana. O contrato documenta a identidade do plano e o limite entre a decisão de negócio e o consumo pelo worker. [Contrato P2](../../packages/contracts/plan/v0.2.0/README.md)

O par `demo-01` e `ctx-demo-01` dos exemplos P1 identifica, por convenção da demo, o lote `01_demo`. Para outro contexto, o operador indica o lote com `--dataset`. A omissão deixa o vínculo pendente. Na v0.2.0, a lista explícita da demo cobre os cinco modelos SQL de prata e ouro. O worker verifica se o lote e as regras são suportados antes da execução.

## Aprovar a ingestão e o período

O comando padrão gera um plano v0.2.0 para N0. Para N1, informe a proposta de acesso aos três sistemas simulados. O arquivo abaixo identifica o mesmo projeto e a mesma revisão da descoberta usados no primeiro exemplo.

```bash
export PYTHONPATH=services/planning
python3 -m korda_planning packages/contracts/context/v0.1.0/examples/02_rateio_confirmado.json \
  --nivel-ingestao n1 --proposta-ingestao packages/contracts/ingestion_plan/v0.1.0/examples/01_demo.json \
  --destino painel-demo --custo-estimado-centavos 125 > /tmp/plano-korda-n1.json
python3 -m korda_planning --validar /tmp/plano-korda-n1.json
```

Sem corte, o escopo do N1 é o lote completo. Acrescentar `--ate-dia 2026-09-29` propõe o replay até esse dia inclusive. O planejador registra a janela, a proposta de ingestão inteira e seu hash. O worker precisa verificar se a janela materializada corresponde à aprovada e se há avaliação independente que cubra o mesmo período.

A seção N1 conserva suas lacunas. Se continuar em rascunho, o plano completo também fica em rascunho. Método, frequência e latência dos exemplos continuam propostas para revisão. A descoberta permanece a origem das regras dos KPIs. Mudar a seção, o nível ou a janela altera a versão que precisa de nova aprovação humana.

O comando `planejar` da execução produz um documento de construção a partir do contexto e do plano base. A função `anexar_construcao` inclui o documento, o modelo e o marcador de dados sintéticos em `construction` e recalcula a versão que será submetida à primeira aprovação. As regras, a janela e os modelos editáveis continuam definidos pelos campos estruturados do plano. [Planejamento e execução](../execution/README.md)

Os planos v0.1.0 registrados usam a lista de modelos e o hash que a respectiva edição emitiu. A primeira edição da demo autorizava `models/prata_ctes.sql`. A edição seguinte autorizava o padrão `models/*` e admitia o documento de construção opcional. A geração atual produz a v0.2.0. Para migrar, gere e registre o novo plano e submeta-o à aprovação humana. [Contrato v0.1.0](../../packages/contracts/plan/v0.1.0/README.md)

## Contexto da entrevista por WhatsApp

Para usar uma revisão de `context/v0.2.0`, disponibilize o backend de contexto e suas dependências na mesma instalação do planejador. A exportação pelo endpoint de contexto conserva o projeto, o número da revisão e as evidências da entrevista. A leitura de contexto v0.1 continua disponível com as dependências de contratos.

```bash
python3 -m services.planning.korda_planning --diagnosticar revisao.json
python3 -m services.planning.korda_planning revisao.json \
  --dataset 01_demo --destino revisao-logistica --custo-estimado-centavos 0 > plano.json
```

O diagnóstico retorna código 0 quando a revisão atende ao planejamento e código 3 quando ainda há perguntas. `pendencias` identifica o campo, a pergunta e os IDs das afirmações e evidências relacionadas. `lacunas` conserva as lacunas da entrevista. Um tópico pode estar pronto para a descoberta enquanto faltam outros assuntos necessários aos três indicadores. O [exemplo confirmado do WhatsApp](../../packages/contracts/context/v0.2.0/examples/03_confirmed.json) confirma o rateio por peso. As oito regras restantes e o perfil logístico ainda precisam de esclarecimento. A interface Python é `preparar_contexto(revisao)`. A função `gerar_plano` também aceita a revisão original.

Os papéis da demo são financeiro para o rateio e operação para as outras oito regras. A confirmação de perfil usa o tópico `fontes` e o papel configurado nesse tópico, operação ou dados. Cada chave é aceita no tópico que a captura guiada atribuiu a ela. `vinculos` identifica a afirmação, todas as suas evidências e a evidência exata de confirmação.

O organizador registra as respostas em campos estruturados. O operador configura os tópicos e os papéis autorizados no projeto de entrevista. O planejador localiza a declaração e a confirmação explícita em turnos distintos, com participante e papel vinculados à evidência. Na entrevista da demo, as perguntas de retorno solicitam as seguintes informações.

| Assunto | Chaves estruturadas |
| --- | --- |
| Frete e elegibilidade | `deduplicar_cte`, `excluir_cancelados`, `rateio_cte`, `excluir_tipos_viagem` |
| Prazo e completude | `sem_data_realizada`, `prazo_conta_sabado`, `no_prazo`, `completo` |
| Ocupação | `ocupacao_unidade` |
| Perfil declarado | `grain`, `quantity_unit`, `timezone`, `freight_link`, individualmente ou agrupados em `source_profile` |

Os valores das regras seguem o [contrato logístico](../../packages/contracts/context/v0.1.0/context.schema.json). A expressão publicada `frete/rateio = peso_bruto` tem mapeamento explícito para `rateio_cte = peso`. Uma chave desconhecida de regra, restrição ou decisão gera uma pergunta com o vínculo da evidência. Restrições temporais ou de unidade que o plano não representa também retornam à descoberta. A descrição da fonte por uma pessoa permanece identificada como declaração.

O identificador do contexto projetado é `whatsapp:<project_id>`. A versão do plano cobre a revisão e o SHA-256 canônico da exportação integral. Os localizadores preservam a citação, o turno, o participante, o papel, a versão da transcrição e os IDs das afirmações, incluindo qual evidência registra a confirmação. Em N1, a proposta de ingestão deve apontar para esse mesmo projeto, identificador de contexto, revisão e evidências. Na entrevista, o operador associa explicitamente a empresa sintética pelo parâmetro `--dataset`.
