# Infraestrutura

Área para o ambiente controlado de execução e publicação.

**Estado (23/11/2026):** existe uma **sandbox local em Docker** para a execução (rascunho da K08): [`sandbox/`](sandbox/Dockerfile), usada por [`services/execution/`](../services/execution/README.md). Sem rede, sem root, sistema de arquivos somente leitura com montagens explícitas, limites de memória, CPU, processos e tempo, e uma pasta por execução, destruída no fim. **Ainda não existem** sandbox em nuvem, credenciais, deploy nem destino de promoção.

A sandbox local **não é isolamento de produção**: compartilha o kernel do host e serve à demo com dados sintéticos. Os limites estão descritos em [`services/execution/README.md`](../services/execution/README.md#limites-conhecidos).

Pendente: escolher a sandbox em nuvem e o destino da demo, confirmar a compatibilidade antes da promoção e isolar o avaliador em processo próprio.

Não expor o Docker socket ou credenciais administrativas ao agente. Toda chamada externa de voz, LLM ou eventos deve ser identificada no trajeto de dados e nos custos. A demo sintética não comprova isolamento adequado para dados de clientes.
