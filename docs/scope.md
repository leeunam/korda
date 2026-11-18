# Escopo inicial

## Problema e público

A consultoria de dados precisa entender o negócio antes de construir. Reuniões, esclarecimentos, registro de regras e revisão podem concentrar trabalho no responsável técnico. A hipótese da Korda é reduzir esse esforço e o retrabalho sem perder a correção da entrega.

**Comprador inicial:** consultoria de dados/BI. **Usuário:** gestor do cliente, apoiado pelo consultor. **Aprovador:** consultor ou profissional com conhecimento técnico. Equipes internas de dados são uma possibilidade posterior.

## Demonstração delimitada

- Uma transportadora fictícia e fontes sintéticas de ERP, TMS e CT-e.
- Descoberta das regras, registro de evidências e bloqueio de lacunas essenciais.
- Um plano versionado com fontes, modelos, fórmulas, regras e testes revisáveis.
- Primeira aprovação humana antes de executar.
- Construção e correção limitadas em ambiente controlado.
- Indicadores, relatório de testes, modelos, documentação e linhagem.
- Segunda aprovação antes de promover a entrega para um destino definido.

| Indicador | Definição a fechar com o exemplo |
| --- | --- |
| Custo de frete por entrega | Fretes elegíveis divididos pelas entregas elegíveis; definir duplicatas, cancelamentos e rateio |
| OTIF | Parcela de pedidos elegíveis entregues no prazo **e completos**; definir denominador, prazo, completude e exceções |
| Ocupação dos veículos | Uso da capacidade na unidade acordada; definir viagem/trecho, capacidade, vazios e agregação |

O cenário logístico não define exclusividade comercial. Fontes e regras insuficientes podem produzir um diagnóstico; não autorizam inventar indicadores.

## Limites propostos

Um caso, até três fontes, três indicadores e uma versão aprovada do plano. A oferta foi discutida com até 60 minutos acumulados de entrevista por projeto; isso precisa de medição. Até três correções automáticas por etapa é a proposta inicial; depois o agente escala ao humano. Mudanças materiais exigem nova aprovação.

Não fazem parte da primeira entrega: múltiplos clientes em produção, operação contínua, qualquer conector, todos os canais completos, infraestrutura elástica ou integração universal. Não afirmar que os dados nunca saem do cliente sem verificar todo o trajeto, inclusive voz, LLM e telemetria.

## Como provar valor

Comparar o esforço humano até um plano correto e aprovado, incluindo revisão e correção. Medir também esforço do cliente, retrabalho, qualidade dos indicadores, custos e tempo total. Reduzir esforço em 50% é uma **meta a testar**, não um resultado. Correção de cálculo não é economia financeira realizada.

## Decisões abertas

1. Destino compatível da entrega e como demonstrar a promoção.
2. Contratos entre frentes e regras exatas dos três indicadores.
3. Canal principal da entrevista e alternativa funcional.
4. Donos técnicos de cada frente e revisão cruzada.
5. Limites reais de custo e evidências do experimento.

Origem: decisões de negócio da equipe e planejamento técnico consolidado. Documentos privados completos e contatos comerciais não fazem parte deste repositório público.
