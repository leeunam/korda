"""Sistemas simulados do cliente para a ingestão de nível 1.

**Simulação com dados sintéticos.** Não são conectores nem sistemas reais: um ERP em Postgres,
um TMS por API HTTP e uma pasta de entrega diária de CT-e, servindo os mesmos dados de
`data/synthetic/output/<empresa>`. O "dia seguinte" é um replay, nunca execução ao vivo.

Módulos:
- `esquema`: tipos de cada tabela no sistema simulado e o dia de cada registro;
- `preparar`: particiona as fontes por dia (roda na imagem, precisa de PyYAML);
- `tms_api`: servidor HTTP do TMS (roda na imagem, só biblioteca padrão);
- `controle`: sobe, avança e destrói o ambiente pelo CLI do Docker (host, só biblioteca padrão).
"""

__version__ = "0.1.0"
ROTULO = "Sistema simulado com dados sintéticos; não é conector real. O avanço de dias é replay, não execução ao vivo."
