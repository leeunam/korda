# Infraestrutura

Área para o ambiente controlado de execução e publicação. Nenhuma sandbox, container, credencial ou deploy está configurado ainda.

Definir limites de CPU/memória/tempo, diretórios de leitura/escrita, política de rede, limpeza por execução e isolamento do avaliador. Escolher um destino da demo e confirmar sua compatibilidade antes da promoção.

Não expor o Docker socket ou credenciais administrativas ao agente. Toda chamada externa de voz, LLM ou eventos deve ser identificada no trajeto de dados e nos custos. A demo sintética não comprova isolamento adequado para dados de clientes.

## Sistemas simulados do cliente (nível 1)

[`sistemas-simulados/`](sistemas-simulados/README.md): ERP em Postgres, TMS por API HTTP e pasta diária de CT-e, numa rede Docker interna sem internet, com replay por dias. Servem só dados sintéticos e **não são conectores reais**.
