# Korda · Undefined

**Da conversa ao dado confiável.** A Korda ajuda consultorias de dados a transformar as necessidades dos clientes em planos aprovados e entregas testadas, com menos alinhamento manual e retrabalho.

Projeto da equipe **Undefined** para o **Hack Brasil 2026**.

## O que vamos construir

1. **Entender:** conversar com o cliente, inspecionar fontes e esclarecer lacunas.
2. **Planejar:** definir indicadores, regras e testes; o consultor aprova o plano.
3. **Construir e testar:** executar em ambiente controlado, com correções limitadas.
4. **Entregar:** apresentar os resultados e pedir autorização para a entrega final.

A primeira demonstração usa uma transportadora fictícia, dados sintéticos de ERP, TMS e CT-e e três indicadores: **custo de frete por entrega, OTIF e ocupação dos veículos**.

## Estado atual

A demo logística tem fontes sintéticas, contrato de descoberta, planejador versionado e um worker local para os três indicadores. O operador revisa o plano, executa o lote e autoriza a promoção dos resultados avaliados. A descoberta ao vivo, a interface e a demonstração pública ainda dependem de integração. [Guia do worker](services/execution/README.md) · [Plano das 17 issues](docs/plano-integracao-worker.md)

- **Demo pública:** pendente.
- **Vídeo de até 3 minutos:** pendente.
- **Trilha:** Logística & automação proposta; confirmar no painel do evento.

## Equipe

**Leunam Sousa** ([@leeunam](https://github.com/leeunam)), **José**, **Marcus** ([@m4rcusml](https://github.com/m4rcusml)) e **Gabriel** ([@Gabriel-smm](https://github.com/Gabriel-smm)).

## Estrutura

| Caminho | Responsabilidade |
| --- | --- |
| `apps/web/` | Interface, revisão e acompanhamento |
| `services/context/` | Conversa, evidências e lacunas |
| `services/planning/` | Regras, plano e primeira aprovação |
| `services/execution/` | Execução, testes e entrega autorizada |
| `packages/contracts/` | Contratos compartilhados entre frentes |
| `data/synthetic/` | Fontes fictícias reproduzíveis: 3 empresas, gerador ERP/TMS/CT-e e calibração (rascunho para K03); [detalhes](data/synthetic/README.md) |
| `evaluation/golden/` | Avaliação independente com respostas conhecidas |
| `infra/` | Ambiente de execução e publicação |
| `docs/` | Escopo, arquitetura, fluxo de trabalho e evento |

## Começar

Abra o [Kanban da equipe](https://github.com/users/leeunam/projects/3/views/1) (acesso restrito aos integrantes) ou as [17 issues públicas](https://github.com/leeunam/korda/issues). Consulte a [ordem das tarefas](docs/backlog.md) e o [fluxo de trabalho](docs/workflow.md).

Leia o [escopo](docs/scope.md), a [arquitetura](docs/architecture.md) e o [guia de contribuição](CONTRIBUTING.md). Agentes de IA devem ler [AGENTS.md](AGENTS.md).

Para verificar a estrutura local, com Python 3.11 ou superior:

```bash
python3 scripts/check_repo.py
```

O comando verifica a estrutura e os links. Os testes de cálculo, aprovações, permissões e entrega estão no [guia de execução](services/execution/README.md).

## Licença

[MIT](LICENSE) · Copyright © 2026 Undefined.
