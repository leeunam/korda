"""Ingestão de nível 1 de REFERÊNCIA: sistemas do cliente (simulados) -> landing zone.

Escrita à mão como plano B e como base de comparação para o código que o agente (harness da
K10) vai gerar. **Não é montada na sandbox do agente**: fica fora da imagem e só é montada
quando a referência roda. Lê o plano de ingestão (contrato `ingestion_plan/0.1.0`) e recebe
credenciais apenas por variáveis de ambiente.

Fontes simuladas com dados sintéticos; não é conector real.
"""

__version__ = "0.1.0"
