# Schemas XSD do CT-e 4.00 (referência versionada)

| Campo | Valor |
| --- | --- |
| Fonte | Portal Nacional do CT-e, SVRS: [Consulta Schemas](https://dfe-portal.svrs.rs.gov.br/CTE/ConsultaSchema), arquivos em `https://dfe-portal.svrs.rs.gov.br/Schemas/PRCTE/` |
| Versão | CT-e 4.00 (leiaute vigente no portal em 22/11/2026). Os arquivos foram baixados um a um, não como pacote `PL_CTe_400` zipado; o nome da pasta é só uma convenção local |
| Obtido em | 22/11/2026 |
| Licença | Documentação técnica pública oficial |
| sha256 | Registrado em [`../../../calibration/sources.json`](../../../calibration/sources.json) |

Conjunto mínimo para um CT-e rodoviário autorizado e para o evento de cancelamento:

- `procCTe_v4.00.xsd` (CT-e + protocolo) → `cte_v4.00.xsd` → `cteTiposBasico_v4.00.xsd`, `tiposGeralCTe_v4.00.xsd`, `DFeTiposBasicos_v1.00.xsd`, `xmldsig-core-schema_v1.01.xsd`
- `cteModalRodoviario_v4.00.xsd` (validado à parte, como o conteúdo de `infModal`)
- `procEventoCTe_v4.00.xsd` → `eventoCTe_v4.00.xsd` → `eventoCTeTiposBasico_v4.00.xsd`; `evCancCTe_v4.00.xsd` (detalhe do evento 110111)

Pendências:
- Conferir se as notas técnicas de 2026 (NT 2026.004 e 2026.005) mudaram algum destes arquivos depois da data de obtenção.
- A validação de XMLs ainda não está implementada. Ela fica para a branch do gerador, que vai precisar de `lxml` ou `xmlschema`.
