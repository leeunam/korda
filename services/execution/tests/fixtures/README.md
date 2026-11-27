# Fixtures da sandbox

**Dados sintéticos de teste.** O exemplo de 4 linhas (CT-e duplicado, cancelado e rateio por peso) é uma **proposta para K02**, não regra aprovada. Estas fixtures testam a sandbox e as ferramentas; não são gabarito e não substituem [`evaluation/golden/`](../../../../evaluation/golden/README.md).

| Caminho | Conteúdo | Montagem na sandbox |
| --- | --- | --- |
| `fontes_minimas/` | `cte.csv` e `entregas.csv` (brutos) | Ingeridos pelos testes numa landing (`cte.parquet`, `entregas.parquet`), montada em `/work/fontes`, somente leitura |
| `projeto_minimo/` | `dbt_project.yml`, `profiles.yml`, `definicoes/` (fontes e testes de esquema), `tests/` (testes singulares) | `/work/projeto`, somente leitura |
| `projeto_minimo/models/` | Vazio: é onde o agente escreve | `/work/projeto/models`, escrita |
| `planejamento/02_rateio_confirmado.md` | Documento de construção real do `planejar` (27/11/2026, contexto fictício 02), sem o bloco de decisão. Referência para testar a construção; não é gabarito | Não é montado |
| `planejamento/01_rateio_pendente.perguntas.json` | Perguntas reais do `planejar` para o contexto fictício 01 (rateio pendente) | Não é montado |
