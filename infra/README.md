# Infraestrutura

Área para o ambiente controlado de execução e publicação.

**Ambiente da demo:** a execução usa a **sandbox local em Docker** de [`sandbox/`](sandbox/Dockerfile), usada por [`services/execution/`](../services/execution/README.md). Sem rede, sem root, sistema de arquivos somente leitura com montagens explícitas, limites de memória, CPU, processos e tempo, e uma pasta por execução, destruída no fim. A promoção local exige a segunda decisão humana da execução. Sandbox em nuvem e deploy permanecem pendentes.

A sandbox local **não é isolamento de produção**: compartilha o kernel do host e serve à demo com dados sintéticos. Os limites estão descritos em [`services/execution/README.md`](../services/execution/README.md#controles-e-diagnóstico).

O avaliador lê os resultados no host depois do desligamento do contêiner. A equipe ainda precisa confirmar o destino operacional da apresentação.

Não expor o Docker socket ou credenciais administrativas ao agente. Toda chamada externa de voz, LLM ou eventos deve ser identificada no trajeto de dados e nos custos. A demo sintética não comprova isolamento adequado para dados de clientes.

## Sistemas simulados do cliente (nível 1)

[`sistemas-simulados/`](sistemas-simulados/README.md): ERP em Postgres, TMS por API HTTP e pasta diária de CT-e, numa rede Docker interna sem internet, com replay por dias. Servem só dados sintéticos e **não são conectores reais**.
