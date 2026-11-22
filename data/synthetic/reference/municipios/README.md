# Municípios brasileiros (referência versionada)

| Campo | Valor |
| --- | --- |
| Fonte | [kelvins/municipios-brasileiros](https://github.com/kelvins/municipios-brasileiros) |
| Commit | `503e2f70bbf1b4b7ec0b1f68b09086ccc38fe861` (10/12/2025) |
| Obtido em | 22/11/2026 |
| Licença | MIT, © 2016 Kelvin S. do Prado ([LICENSE](LICENSE)) |
| Arquivos | `municipios.csv` (código IBGE, nome, latitude, longitude, UF…) e `estados.csv` (código, sigla, nome, região) |
| sha256 | Registrado em [`../../calibration/sources.json`](../../calibration/sources.json) |

O arquivo está versionado para que a calibração e o gerador rodem offline e no CI. Ele é usado para as coordenadas da área de atendimento (distância em linha reta × fator de estrada) e para converter nomes de UF em siglas. Não modificar à mão: para atualizar, troque o commit em `sources.json`, rode `calibrate.py` e copie os arquivos de `data/external/kelvins_municipios/`.
