# Fixtures da sandbox

**Dados sintéticos de teste.** O exemplo de 4 linhas (CT-e duplicado, cancelado e rateio por peso) é uma **proposta para K02**, não regra aprovada. Estas fixtures testam a sandbox e as ferramentas; não são gabarito e não substituem [`evaluation/golden/`](../../../../evaluation/golden/README.md).

| Caminho | Conteúdo | Montagem na sandbox |
| --- | --- | --- |
| `fontes_minimas/` | `cte.csv` e `entregas.csv` (brutos) | Ingeridos pelos testes numa landing (`cte.parquet`, `entregas.parquet`), montada em `/work/fontes`, somente leitura |
| `projeto_minimo/` | `dbt_project.yml`, `profiles.yml`, `definicoes/` (fontes e testes de esquema), `tests/` (testes singulares) | `/work/projeto`, somente leitura |
| `projeto_minimo/models/` | Vazio: é onde o agente escreve | `/work/projeto/models`, escrita |
