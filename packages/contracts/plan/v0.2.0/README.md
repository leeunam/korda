# Plano logístico e ingestão sintética v0.2.0

A primeira aprovação vincula uma versão exata do plano à proposta de ingestão, à janela e aos modelos que a execução pode escrever. O [schema do plano](plan.schema.json) reutiliza os campos de contexto, métricas e revisão da [v0.1.0](../v0.1.0/README.md).

| Campo | Semântica |
| --- | --- |
| `ingestion.level` | `n0` para arquivos exportados, `n1` para os três sistemas simulados da demo. |
| `ingestion.window` | `{"kind":"full_batch"}` para o lote completo em ambos os níveis. N1 admite também `{"kind":"simulated_as_of","as_of":"2026-09-29"}` para o replay até a data inclusiva. |
| `ingestion.proposal` | Em N1 contém o documento integral `ingestion_plan/0.1.0`, seus métodos, objetos, testes e lacunas. Em N0 fica nulo. [Contrato da seção](../../ingestion_plan/v0.1.0/README.md) |
| `ingestion.proposal_sha256` | Hash da proposta canônica do N1. Em N0 fica nulo. |
| `plan_version` | Hash do plano completo, com o campo `plan_version` omitido. Inclui o nível, a janela, as regras, a proposta e os modelos editáveis. |
| `construction` (opcional) | Documento de construção, identificação do modelo e indicador de geração sintética. O hash da versão inclui os três campos. |
| `editable_models` | Caminhos exatos autorizados no lote `01_demo` para os modelos `prata_ctes`, `prata_rateios`, `ouro_por_pedido`, `ouro_por_viagem` e `ouro_kpis`. A lista dos outros lotes é vazia. |

Os caminhos em `metrics[*].input_files` são relativos à landing Parquet compartilhada pelos níveis N0 e N1. A etapa bronze preparada pelo host expõe as fontes ao dbt. O agente constrói os modelos SQL sobre essas relações.

Ambos os hashes usam SHA-256 em hexadecimal sobre JSON UTF-8 com chaves ordenadas recursivamente, acentos preservados e separadores sem espaços. O validador resolve os schemas localmente. Também verifica o calendário civil da data de corte e os vínculos de projeto, empresa, revisão de contexto e IDs das evidências.

O planejador aceita uma seção N1 em rascunho vinculada ao contexto e conserva esse estado no plano. Para aprovar a proposta da demo, ela precisa declarar ERP, TMS e CT-e. Uma lacuna bloqueante aberta impede aprovar a seção. As lacunas não bloqueantes e suas perguntas permanecem visíveis na proposta, inclusive quando as regras dos KPIs já foram confirmadas. O operador autoriza apenas a versão apresentada. Usar um novo período ou uma proposta alterada exige registrar o novo plano e obter nova aprovação.

Os planos v0.1.0 registrados mantêm o hash e os modelos editáveis definidos pela edição que os gerou. Na demo, o campo registrado contém o caminho exato de um modelo ou o padrão `models/*`. As verificações dos contratos de ingestão e as instruções para gerar a nova versão estão no [guia do planejador](../../../../services/planning/README.md).
