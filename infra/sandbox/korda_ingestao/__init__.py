"""Ingestão de arquivos exportados (nível 0) para uma landing zone em Parquet.

Roda dentro do contêiner da sandbox, sem rede, com as fontes brutas montadas somente
leitura. **Não limpa nada**: não deduplica, não filtra cancelados, não converte datas nem
decimais e não renomeia colunas. Cada valor chega como texto, com linhagem até o arquivo
de origem. Limpar é trabalho do agente, guiado pelo plano aprovado.

Os dados processados na demo são sintéticos (exportação simulada), não vêm de conector real.
"""

__version__ = "0.1.0"
