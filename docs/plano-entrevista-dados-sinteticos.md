# Plano da entrevista e das fontes sintéticas da Korda

**Plano iniciado em 19/11/2026 · recorte técnico alinhado ao gerador de Gabriel em 23/11/2026**

Preparar uma conversa fictícia que permita passar da descoberta ao planejamento usando as fontes já geradas por Gabriel no PR #18. A primeira rodada usa o custo de frete por entrega para revelar uma regra ausente. O mesmo caso cobre OTIF e ocupação. Marcus conduz a descoberta e usa o gerador como referência nas ambiguidades do desenho anterior. O [contrato local v0.1.0](../packages/contracts/context/v0.1.0/README.md) registra as definições e duas revisões JSON para testar o consumo pelo planejamento.

**Materiais preparados em 23/11/2026.** O [conjunto da descoberta](../data/synthetic/discovery/README.md) contém o formulário, três páginas de pesquisa fictícias e as falas das duas rodadas. O [avaliador](../evaluation/discovery/README.md) contém estados manuais e critérios para ambiguidade, contradição, correção e retomada. São materiais verificáveis para implementar o fluxo; agentes, persistência, perfilamento e frontend continuam nas etapas seguintes.

## Arquitetura e tecnologias para o primeiro ensaio

Antes de integrar as frentes, alinhar um fluxo local entre Marcus e Gabriel. A entrevista recebe texto e preserva os trechos que sustentam cada resposta. Um leitor separado inspeciona os CSVs e XMLs sintéticos em modo somente leitura. A descoberta reúne as duas fontes de evidência, registra o que falta e encaminha um arquivo de contexto ao planejamento. Gabriel valida a entrada usando um rascunho manual do plano ou um consumidor provisório.

| Decisão | Ponto de partida sugerido |
| --- | --- |
| Execução local | Python para organizar o fluxo e ler XML. DuckDB para inspecionar os CSVs, conforme a base técnica proposta pelo projeto. |
| Entrada e estado da entrevista | Diálogo em texto. Salvar as mensagens e o estado em arquivos locais distintos dos dados de origem para testar retomada entre as rodadas. |
| Passagem para planejamento | JSON conforme o [schema v0.1.0](../packages/contracts/context/v0.1.0/context.schema.json), com revisão, evidências, perfil, regras e lacunas. Dois exemplos mostram o rateio pendente e a confirmação posterior. O consumidor de planejamento será testado na integração. |
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
| Mostre um pedido, da promessa ao recebimento. Onde cada etapa fica registrada? | O ERP guarda pedido, volumes, peso, cubagem, chave da NF-e e prazo. O TMS guarda a entrega única, volumes entregues e viagem. `nr_ped` liga ao pedido do ERP; `ch_nfe` do ERP liga ao `infNFe/chave` do CT-e. |
| Qual frete entra na conta? Uma entrega parcial conta? O que acontece se o CT-e for cancelado? | Usar `vTPrest` autorizado, deduplicado por chave e sem cancelamento homologado. A entrega incompleta entra se coberta por CT-e válido. Sem CT-e válido, sai apenas do custo. Na 01, o cancelado do caso fixo é reemitido. |
| Quando o mesmo CT-e cobre duas entregas, como vocês dividem o custo? | **Rodada 1:** o gestor diz que o caminhão lota por peso e pede confirmação ao financeiro. Registrar a lacuna de rateio como bloqueante para o frete. **Rodada 2:** o responsável fictício confirma o rateio pelo peso expedido de cada entrega. Manter os mesmos arquivos e registrar a nova evidência. |
| O que significa chegar completo e no prazo? O que acontece com uma entrega em partes? | Na 01, prazo prometido inclusivo e `qt_entregue >= qt_itens` em volumes. Sem data conta como falha. Há uma entrega por pedido, possivelmente incompleta; múltiplas entregas são sinalizadas como fora do recorte. |
| Em qual momento e unidade vocês medem a ocupação? | Na 01, somar o peso dos pedidos por viagem e dividir pela soma das capacidades em kg de todas as viagens. Preservar ocorrências acima de 100%. O gerador não contém retorno vazio nem medição por trecho. |
| Quem pode confirmar as regras e a origem dos dados? | Definir papéis fictícios de operação, financeiro e responsável pelos dados. Registrar o trecho de cada confirmação e o arquivo, registro e campo para observações das fontes. |

Na rodada 1, a conversa pode avançar e o planejador pode rascunhar o restante. O custo por entrega fica bloqueado até a confirmação da regra afetada. Prever retomada da conversa e registrar a nova evidência na rodada 2.

## Fontes já disponíveis

Usar `01_demo` como caso principal e `02_variacao` como variação de desenvolvimento. A `03_reservada` permanece para medição, com isolamento no runtime. Os formatos reais estão no [dicionário](../data/synthetic/spec/dicionario.md). Datas dos CSVs não têm offset e usam `America/Sao_Paulo`; os formatos mistos são intencionais. Valores monetários são em BRL. O perfilamento recebe somente `erp/`, `tms/` e `cte/`.

| Fonte e grão | Campos da 01 | Função |
| --- | --- | --- |
| ERP, uma linha por pedido | `cd_ped`, `dt_prev_ent`, `qt_itens`, `ps_bruto`, `vl_cubag`, `vl_merc`, `ch_nfe` | Prazo, volumes totais, base de rateio e NF-e que liga ao CT-e. |
| TMS, uma entrega por pedido | `id_ent`, `nr_ped`, `id_viag`, `qt_entregue`, `dt_baixa`, `st_ent` | Baixa única, possivelmente incompleta; vínculo ao pedido do ERP. |
| TMS, uma linha por viagem | `id_viag`, `id_veic`, `dt_saida`, `tp_viag` | Agrupa os pedidos para calcular carga e buscar capacidade. |
| TMS, uma linha por veículo | `id_veic`, `cap_kg`, `cap_m3` | Capacidade na unidade da regra confirmada. |
| CT-e, XMLs de documentos e eventos | Chave do CT-e, valor `vTPrest` e evento sintético de cancelamento ligado pela mesma chave | Valor de prestação, duplicatas físicas e situação fiscal. Usar apenas identificadores fictícios. |

**Caso principal do gerador.** CT-e de R$ 400,00 cobrindo os pedidos 900001 (100 kg) e 900002 (300 kg), recebido em duplicata. O pedido 900003 tem CT-e cancelado de R$ 150,00 e reemissão do mesmo valor. São as fontes fixas para o ensaio em duas rodadas. Atraso, volumes incompletos e datas ausentes já são plantados no restante da empresa. O exemplo anterior de quatro linhas permanece como teste independente do avaliador, separado do roteiro da 01.

**Limites.** CT-e com conteúdo divergente na mesma chave, peso ausente, reentregas e capacidade desconhecida exigem tratamento explícito antes de ampliar o cenário. Não afirmar que essas variantes já estão cobertas pelo gerador. Resultados esperados e registro de anomalias ficam fora do contexto dos agentes da descoberta e execução.

## Sequência de trabalho

1. **Base técnica disponível.** Correções da revisão do PR #18, semântica alinhada ao gerador e contrato local com dois JSONs. Schema e referências cruzadas são verificáveis sem modelos externos. O aceite conjunto de K01/K02 e a conferência humana das amostras continuam seguindo o fluxo da equipe.
2. **Implementar e rodar o ensaio da descoberta.** Preparar as falas sintéticas usando a 01, alimentar o mesmo organizador antes/durante/depois e preservar a lacuna de rateio até a segunda rodada. Usar o contrato para testar a passagem ao planejador de Gabriel.
3. **Integrar perfilamento e revisão.** Inspecionar as fontes em modo somente leitura, manter configuração e metadados do gerador fora do agente e vincular os achados a arquivos e registros. Resultados esperados continuam exclusivos do avaliador no runtime. [Contratos](../packages/contracts/README.md) · [Fontes sintéticas](../data/synthetic/README.md) · [Avaliação](../evaluation/golden/README.md)
4. **Verificar o fluxo implementado e ampliar para os três indicadores.** A inspeção deve encontrar a duplicata e o evento fiscal. A primeira rodada deve preservar o bloqueio do frete. A segunda deve preparar um plano rastreável para revisão. O avaliador confere custo por entrega e média, OTIF por pedido e ocupação por viagem. Um rateio incorreto pode preservar a média e falhar nos valores individuais. As aprovações do produto seguem o fluxo definido. [Escopo](scope.md) · [Arquitetura](architecture.md)

As issues [#1](https://github.com/leeunam/korda/issues/1), [#2](https://github.com/leeunam/korda/issues/2), [#3](https://github.com/leeunam/korda/issues/3), [#4](https://github.com/leeunam/korda/issues/4) e [#5](https://github.com/leeunam/korda/issues/5) ajudam a localizar o trabalho correspondente. O contrato local descreve o desenvolvimento da descoberta; as regras de negócio permanecem no estado de referência declarado por Gabriel em cada empresa.
