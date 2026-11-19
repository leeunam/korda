# Plano da entrevista e das fontes sintéticas da Korda

**Proposta para revisão de Marcus e Gabriel · 19/11/2026**

Preparar uma conversa fictícia e um conjunto pequeno de arquivos que permitam passar da descoberta ao planejamento. A primeira rodada usa o custo de frete por entrega para revelar uma regra ausente. A expansão do mesmo caso cobre OTIF e ocupação. Marcus conduz o rascunho de descoberta. Gabriel revisa o que o planejador precisa receber. A equipe ainda precisa confirmar quem responde pelas regras da transportadora fictícia e quem mantém as fixtures.

## Arquitetura e tecnologias para o primeiro ensaio

Antes de integrar as frentes, alinhar um fluxo local entre Marcus e Gabriel. A entrevista recebe texto e preserva os trechos que sustentam cada resposta. Um leitor separado inspeciona os CSVs e XMLs sintéticos em modo somente leitura. A descoberta reúne as duas fontes de evidência, registra o que falta e encaminha um arquivo de contexto ao planejamento. Gabriel valida a entrada usando um rascunho manual do plano ou um consumidor provisório.

| Decisão | Ponto de partida sugerido |
| --- | --- |
| Execução local | Python para organizar o fluxo e ler XML. DuckDB para inspecionar os CSVs, conforme a base técnica proposta pelo projeto. |
| Entrada e estado da entrevista | Diálogo em texto. Salvar as mensagens e o estado em arquivos locais distintos dos dados de origem para testar retomada entre as rodadas. |
| Passagem para planejamento | JSON local provisório com evidências da conversa, achados das fontes e lacunas. Vincular evidências ao trecho ou ao registro de origem. Versionar o schema compartilhado depois que Gabriel testar o consumo. |
| Integrações posteriores | dbt entra na construção dos indicadores. A escolha de modelo e harness, Tavus, interface, backend de eventos e cloud seguem em avaliação para suas respectivas etapas. |

O ensaio termina quando os dois conseguem repetir localmente o fluxo com as mesmas fontes. Sem confirmação do rateio, o contexto deve carregar a lacuna e a etapa de planejamento deve preservar o bloqueio do frete. Com a confirmação, o planejador deve conseguir preparar a regra e indicar a evidência correspondente para revisão humana. O ensaio pode usar transcrições já preparadas e um planejador manual para validar a passagem de informação. [Arquitetura de referência](architecture.md) · [Contexto](../services/context/README.md)

## O que a pesquisa mudou no desenho

- **O CT-e fornece o valor total da prestação.** No modelo 57, `vPrest/vTPrest` é o valor total da prestação. `vRec` é o valor a receber e `Comp` discrimina componentes quando informados. Usar `vTPrest` como custo de frete é uma regra proposta para a demo. A referência de NF-e em `infCteNorm/infDoc/infNFe/chave` identifica uma nota fiscal. O vínculo com pedidos e entregas internos deve vir de um registro operacional. [Portal do CT-e, MOC 4.00, Anexo I, §3](https://www.cte.fazenda.gov.br/portal/exibirArquivo.aspx?conteudo=6aFNuknaWsc%3D)
- **O cancelamento fiscal tem evidência própria.** Representar o CT-e e o evento de cancelamento aceito, tipo `110111`, como entradas distintas. O evento afeta a situação fiscal do documento. O estado do pedido e da entrega vem do ERP e do TMS. A demonstração vai ler arquivos locais sintéticos. Ao preparar XMLs, registrar a revisão do XSD usada e distinguir validação estrutural de autorização fiscal. [MOC 4.00, Visão Geral, §6.2](https://www.cte.fazenda.gov.br/portal/exibirArquivo.aspx?conteudo=0eu1YksSGXM%3D) · [Pacotes oficiais de schemas](https://www.cte.fazenda.gov.br/portal/listaConteudo.aspx?tipoConteudo=0xlG1bdBass%3D)
- **OTIF exige fechar período, prazo e unidade de análise.** A APQC publica uma medida por pedido completo e no prazo. A pesquisa da Trading Partner Alliance documenta diferenças entre prazo solicitado, prometido e agendado, além de granularidades por pedido, item ou caixa. Para o caso fictício, propor pedido elegível e recebimento de todos os itens até o prazo prometido. [APQC, medida 102357](https://www.apqc.org/resources/benchmarking/open-standards-benchmarking/measures/percentage-orders-delivered-complete) · [Pesquisa da Trading Partner Alliance e McKinsey](https://www.mckinsey.com/capabilities/operations/our-insights/defining-on-time-in-full-in-the-consumer-sector)
- **Ocupação precisa de unidade e momento de medição.** A metodologia do Eurostat separa capacidade em massa e uso de volume, com informação por trecho. Para a demo, propor ocupação em kg, medida à saída da viagem. O peso expedido usado no rateio e a capacidade da viagem representam grandezas operacionais distintas. [Eurostat, metodologia de transporte rodoviário, edição revisada de 2025](https://ec.europa.eu/eurostat/web/products-manuals-and-guidelines/w/ks-01-25-070)

## Roteiro de entrevista em duas rodadas

| Pergunta ao gestor | Resposta ou evidência a preparar |
| --- | --- |
| Que decisão você quer tomar com esses números? | Comparar quanto custa uma entrega, localizar falhas de atendimento e verificar o uso da capacidade dos veículos. |
| Mostre um pedido, da promessa ao recebimento. Onde cada etapa fica registrada? | O ERP guarda o pedido, os itens e o prazo prometido. O TMS guarda o recebimento, a quantidade aceita e a viagem. O vínculo para o CT-e consta do TMS neste cenário. |
| Qual frete entra na conta? Uma entrega parcial conta? O que acontece se o CT-e for cancelado? | Propor o valor da prestação de CT-es elegíveis e uma contagem por entrega física elegível, inclusive a parcial. Validar com o responsável como tratar uma entrega realizada cujo único CT-e foi cancelado e se há substituto. O evento fiscal e o cancelamento operacional têm origens distintas. |
| Quando o mesmo CT-e cobre duas entregas, como vocês dividem o custo? | **Rodada 1:** o gestor diz que o caminhão lota por peso e pede confirmação ao financeiro. Registrar a lacuna de rateio como bloqueante para o frete. **Rodada 2:** o responsável fictício confirma o rateio pelo peso expedido de cada entrega. Manter os mesmos arquivos e registrar a nova evidência. |
| O que significa chegar completo e no prazo? O que acontece com uma entrega em partes? | Propor prazo prometido inclusivo e quantidade aceita por item acumulada até esse prazo. Confirmar a janela do relatório, o evento de recebimento e quais pedidos cancelados saem da base. |
| Em qual momento e unidade vocês medem a ocupação? | Propor peso carregado à saída dividido pela capacidade útil daquela configuração. Registrar se retorno vazio entra e como agregar viagens com capacidades diferentes. |
| Quem pode confirmar as regras e a origem dos dados? | Definir papéis fictícios de operação, financeiro e responsável pelos dados. Registrar o trecho de cada confirmação e o arquivo, registro e campo para observações das fontes. |

Na rodada 1, a conversa pode avançar e o planejador pode rascunhar o restante. O custo por entrega fica bloqueado até a confirmação da regra afetada. Prever retomada da conversa e registrar a nova evidência na rodada 2.

## Fontes a prototipar

Os nomes e campos são propostas para o exercício. Manter IDs estáveis, horários ISO 8601 com deslocamento explícito, unidades documentadas e moeda BRL com precisão decimal.

| Fonte e grão | Campos sugeridos | Função |
| --- | --- | --- |
| ERP, uma linha por pedido | `pedido_id`, `prazo_prometido_em`, `status_pedido` | Prazo e elegibilidade operacional. |
| ERP, uma linha por item do pedido | `pedido_id`, `item_id`, `qtd_pedida`, `unidade` | Quantidade esperada do item. |
| TMS, uma linha por entrega | `entrega_id`, `pedido_id`, `viagem_id`, `chave_cte`, `recebido_em`, `status_entrega`, `peso_rateio_kg` | Evento de entrega, ligação explícita ao frete e peso registrado uma vez por entrega. Várias entregas podem apontar para a mesma chave. |
| TMS, uma linha por item recebido em cada entrega | `entrega_id`, `item_id`, `qtd_aceita`, `unidade` | Completude por item e soma de recebimentos de um pedido. |
| TMS, uma linha por viagem | `viagem_id`, `saida_em`, `capacidade_util_kg`, `peso_carregado_kg`, `tipo_viagem` | Ocupação à saída e recorte de retornos. |
| CT-e, XMLs de documentos e eventos | Chave do CT-e, valor `vTPrest` e evento sintético de cancelamento ligado pela mesma chave | Valor de prestação, duplicatas físicas e situação fiscal. Usar apenas identificadores fictícios. |

**Caso principal sugerido.** A1 tem valor de R$ 300, aparece duas vezes com conteúdo idêntico e cobre as entregas de P1 e P2, com pesos de rateio de 100 e 200 kg. B2 tem valor de R$ 200 e cobre a entrega de P3. C3 tem valor de R$ 150 e um evento de cancelamento. Vincular C3 a uma entrega prevista que não ocorreu. P1 é completo no prazo, P2 é parcial no prazo e P3 é completo em atraso. A entrega parcial de P2 entra no frete se a regra proposta for confirmada. Para ocupação, prever duas viagens com capacidades distintas, por exemplo 300 de 500 kg e 200 de 400 kg.

**Casos de verificação separados.** Incluir uma mesma chave de CT-e com conteúdo divergente, peso de rateio ausente, complemento do pedido recebido após o prazo e capacidade desconhecida. Testar cancelamento do CT-e com pedido ainda ativo para detectar acoplamento entre os indicadores. Distinguir retorno vazio conhecido de peso ausente. Registrar quais casos pertencem à demonstração e quais ficam com o avaliador.

## Sequência de trabalho

1. **Alinhar a arquitetura mínima e a passagem local.** Marcus e Gabriel combinam quem produz o contexto, onde o planejamento o recebe e como os dois verificam o fluxo. Em paralelo, Marcus prepara à mão o diálogo de duas rodadas e as tabelas do caso principal. Se houver acesso a um contato de logística, validar onde ficam o vínculo pedido–entrega–CT-e, a regra de rateio e a confirmação de recebimento. Usar dados fictícios no ensaio.
2. **Rodar o ensaio e fechar as regras.** Gabriel rascunha o plano a partir do material recebido. Marquem o que veio da entrevista, o que as fontes comprovam e o que precisa voltar como pergunta. O responsável pelo cenário revisa elegibilidade, rateio, prazo, completude e ocupação. Anotar quem mantém as fixtures e quem revisa os resultados de forma independente.
3. **Versionar o contrato e implementar o recorte.** Após revisar as duas rodadas, formalizar a passagem para o planejamento em `packages/contracts/`. Colocar o roteiro e os diálogos em `services/context/` e criar as fontes em `data/synthetic/` com configuração fixa, ordem estável e geração reproduzível. Documentar esquema, chaves, fuso, unidades e anomalias. Manter as referências de aceite em `evaluation/golden/`, acessível apenas ao avaliador no runtime. Registrar com cada resultado de referência a versão aprovada das regras. [Contratos](../packages/contracts/README.md) · [Fontes sintéticas](../data/synthetic/README.md) · [Avaliação](../evaluation/golden/README.md)
4. **Verificar o fluxo implementado e ampliar para os três indicadores.** A inspeção deve encontrar a duplicata e o evento fiscal. A primeira rodada deve preservar o bloqueio do frete. A segunda deve preparar um plano rastreável para revisão. O avaliador confere custo por entrega e média, OTIF por pedido e ocupação por viagem. Um rateio incorreto pode preservar a média e falhar nos valores individuais. As aprovações do produto seguem o fluxo definido. [Escopo](scope.md) · [Arquitetura](architecture.md)

As issues [#1](https://github.com/leeunam/korda/issues/1), [#2](https://github.com/leeunam/korda/issues/2), [#3](https://github.com/leeunam/korda/issues/3), [#4](https://github.com/leeunam/korda/issues/4) e [#5](https://github.com/leeunam/korda/issues/5) ajudam a localizar o trabalho correspondente. O desenho das fontes e as regras acima permanecem como propostas para revisão.
