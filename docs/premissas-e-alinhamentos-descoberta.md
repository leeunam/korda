# Premissas, responsabilidades e alinhamentos da descoberta

**Registro para revisão de Gabriel no PR #20 · 24/11/2026**

Esta análise separa as escolhas da frente de Marcus, as premissas materializadas no trabalho de Gabriel e os alinhamentos adotados na preparação da descoberta. Baseia-se no planejamento de Marcus, no código e na documentação do PR #18 e nas instruções de Marcus para preservar esse recorte. Não registra um novo aceite de Gabriel nem aprovação das regras de negócio.

## Responsabilidades usadas no planejamento

| Frente | Responsabilidade considerada | Situação |
| --- | --- | --- |
| Marcus | Backend da descoberta: pesquisa, entrevista, evidências, lacunas, perfilamento e contexto versionado | Contrato e materiais de ensaio preparados; backend ainda será implementado |
| Gabriel | Planejamento e execução, consumindo o contexto produzido pela descoberta | Divisão usada no planejamento; a integração P1 → P2 ainda precisa ser validada conjuntamente |
| Outro integrante | Frontend e experiência visual | Marcus informou que já está em desenvolvimento; integração posterior, sem atribuir aqui um nome não confirmado |

O trabalho concretamente analisado de Gabriel é o gerador de fontes sintéticas e seu avaliador, integrados pelo [PR #18](https://github.com/leeunam/korda/pull/18). A atribuição de uma frente não comprova implementação de todos os seus serviços.

## Escolhas e premissas da frente de Marcus

- Pesquisador e entrevistador alimentam o mesmo organizador, que trabalha antes, durante e depois da entrevista.
- No modo ao vivo, entrevistador e cruzador rápido são componentes distintos. No texto, há um agente de conversa e o organizador em segundo plano.
- O organizador será o único escritor do contexto canônico; pesquisadores fornecem achados e entrevistadores produzem perguntas.
- O armazenamento proposto usa PostgreSQL com evidências e relações versionadas em tabelas. GraphRAG ou busca vetorial não são requisitos da primeira implementação.
- Python, FastAPI, Pydantic, PostgreSQL, Procrastinate e Docker Compose são a stack proposta desta frente. Modelos, provedores de pesquisa e componentes de voz/avatar são candidatos sujeitos a ensaio, sem aceite de Gabriel registrado neste documento.
- O [contexto v0.1.0](../packages/contracts/context/v0.1.0/README.md) é uma proposta local P1 → P2. O estado interno anterior ao perfilamento admite desconhecidos; não deve inventar campos para satisfazer o contrato de exportação.
- O ensaio usa duas rodadas: operação deixa o rateio pendente; financeiro o confirma depois. As confirmações e os participantes são fictícios, não aprovadores comerciais reais.
- O [item 3](../data/synthetic/discovery/README.md) acrescenta variantes de ambiguidade, contradição, correção e retomada, com entradas, persona e respostas esperadas separadas.
- A revisão técnica introduziu conservação de centavos no rateio, desempate estável, custo por viagem com elegibilidade consistente e rejeição de múltiplas entregas por pedido no avaliador. São convenções técnicas documentadas, sem ampliar o cenário para reentregas.
- O escopo atual concentra-se no backend. OpenAPI, exemplos de respostas e autenticação coordenada prepararão a integração posterior com o frontend da equipe.

Referência do desenho e dos itens restantes: [plano técnico da descoberta](plano-arquitetura-agentes-descoberta.md). Essas escolhas não significam que os serviços ou integrações já funcionem.

## Premissas materializadas no trabalho de Gabriel

O gerador e o avaliador estabelecem este recorte para o caso sintético:

- Três fontes: ERP, TMS e XML de CT-e; três indicadores: custo de frete por entrega, OTIF e ocupação.
- Uma entrega por pedido, que pode estar incompleta. Quantidades representam volumes; não há completude por SKU ou acúmulo de reentregas.
- Relação entre fontes: `TMS.nr_ped → ERP.cd_ped → ERP.ch_nfe → CT-e.infNFe/chave`.
- Custo baseado em `vTPrest`, com deduplicação por chave, tratamento de cancelamento e entregas elegíveis cobertas por CT-e válido.
- OTIF exige prazo e completude. Ocupação considera soma da carga sobre soma da capacidade de todas as viagens, preservando ocorrências acima de 100%.
- Empresas 01 e 02 servem ao desenvolvimento; a 03 permanece reservada para medição, sem ajuste de agentes ou prompts a partir de seus resultados.

| Empresa | Rateio de referência | Entrega sem data no OTIF | Ocupação | Particularidade |
| --- | --- | --- | --- | --- |
| `01_demo` | Peso | Falha | kg | Caso principal, sem exclusão de tipos de viagem |
| `02_variacao` | Volume | Falha | kg | Exclui TRF de custo e OTIF; a entrevista não deve antecipar esse fato |
| `03_reservada` | Valor | Excluída | m³ | Prazo em dias úteis sem sábado; somente medição |

Fontes: [cenários](../data/synthetic/spec/cenarios.md), [dicionário](../data/synthetic/spec/dicionario.md) e [avaliação independente](../evaluation/golden/README.md).

As regras nos arquivos `empresa.yaml` continuam com `status: proposta_pendente_k02`. Parâmetros como frota, demanda, preços e taxas de anomalias incluem valores marcados como `suposicao:equipe`. Gabriel os materializou no gerador; essa marcação não permite atribuí-los como decisões pessoais definitivas dele ou como fatos comerciais validados. A presença de calibração pública também não valida todas as suposições do cenário.

## Alinhamentos explícitos entre Marcus e a assistência de desenvolvimento

Estes pontos foram adotados por orientação de Marcus. A lista não deve ser interpretada como ata de aprovação bilateral Marcus–Gabriel:

1. Preservar o comportamento do trabalho de Gabriel e, nas ambiguidades, adotar seu recorte.
2. Preparar a descoberta sobre as fontes já existentes, mantendo regras específicas de cada empresa.
3. Distinguir informação fornecida de descoberta e evidência da empresa de referência setorial.
4. Manter informação ausente como ausente; uma prática setorial não confirma regra da empresa.
5. Não inferir rateio financeiro por peso a partir de uma fala sobre ocupação por peso.
6. Manter lacunas e indicadores afetados explícitos, permitindo que a entrevista peça esclarecimentos.
7. Preservar histórico, identidade de lacunas e evidências quando houver correção ou nova rodada.
8. Separar entradas dos agentes, falas futuras do cliente simulado e resultados esperados do avaliador. O isolamento real deve ser imposto pela infraestrutura.
9. Focar o desenvolvimento de Marcus no backend e integrar a interface posteriormente.

A compatibilidade técnica com o gerador está documentada. O merge do PR #18, os testes e as falas sintéticas não substituem o aceite conjunto dos contratos nem as duas aprovações do produto.

## Pontos que ainda precisam de alinhamento com Gabriel e a equipe

| Ponto aberto | Decisão ou evidência necessária |
| --- | --- |
| Contrato P1 → P2 | Gabriel conferir campos, estados, versões e exemplos do contexto v0.1.0; registrar alterações necessárias ou aceite |
| Bloqueio parcial | Confirmar como o planejador rascunha indicadores sem lacunas e impede avançar no indicador bloqueado |
| Consumo e atualização | Definir como selecionar uma revisão e tratar confirmações posteriores, conflitos e mudanças no contexto |
| Integração verificável | Demonstrar o consumo das revisões pendente e confirmada pelo planejador ou por um consumidor provisório |
| Regras e tolerâncias | Registrar revisão humana de K02 e amostras independentes; as referências atuais continuam propostas |
| Stack e operação compartilhadas | Alinhar dependências que afetem outras frentes, autenticação e autorização por projeto/papel |
| Fronteira com o frontend | Coordenar identidade dos participantes, operações e estados da API com o responsável pela interface antes da integração |

Não foi encontrado nos registros consultados aceite explícito de Gabriel para o contrato local, toda a stack proposta ou a integração do planejador. O [README do contrato](../packages/contracts/context/v0.1.0/README.md) também registra a ausência de aceite conjunto. Essa constatação limita-se às evidências consultadas; uma decisão externa pode ser incorporada quando for registrada.

Este documento torna as premissas revisáveis no [PR #20](https://github.com/leeunam/korda/pull/20). Não fecha K01/K02, não altera contratos ou regras e não concede aprovações em nome dos integrantes.
