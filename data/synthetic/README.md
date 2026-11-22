# Fontes sintéticas

Área para geradores determinísticos e fixtures fictícias de ERP, TMS e CT-e.

**Status (22/11/2026):** existem a **especificação** do cenário 01 e a **calibração** com dados públicos, ambas como rascunho para [K03](https://github.com/leeunam/korda/issues/3). **O gerador e os dados ainda não existem.** A K03 depende de K01 (contratos) e K02 (regras dos indicadores), que estão abertas. Nada aqui define regra de KPI.

## Estrutura

| Caminho | Conteúdo |
| --- | --- |
| [`spec/empresa.yaml`](spec/empresa.yaml) | Fatos da transportadora fictícia: frota, volumes, frete, prazos e taxas de anomalia. Cada parâmetro tem `origem`. Também servirá à persona da entrevista simulada (P1/K04). |
| [`spec/area_atendimento.csv`](spec/area_atendimento.csv) | Sede (Campinas/SP) e os 19 municípios atendidos, com peso de demanda. |
| [`spec/dicionario.md`](spec/dicionario.md) | Esquemas "sujos" de ERP, TMS e CT-e e suas relações. |
| [`spec/anomalias.md`](spec/anomalias.md) | Problemas plantados, KPI afetado e o teste que deve nascer de cada um. |
| [`spec/cenarios.md`](spec/cenarios.md) | Cenários 01 (demo), 02 (variação) e 03 (reservado só para medir). |
| [`calibration/`](calibration/sources.json) | `sources.json` (fontes declaradas), `calibrate.py` (processo único), [`manifest.json`](calibration/manifest.json) (procedência obtida, versionada), `calibration.yaml` (só agregados) e testes. |
| [`reference/municipios/`](reference/municipios/README.md) | Coordenadas dos municípios (MIT), versionadas. |
| [`reference/cte-xsd/PL_CTe_400/`](reference/cte-xsd/PL_CTe_400/README.md) | XSD oficiais do CT-e 4.00, versionados para validação offline. |
| `../external/` | Downloads brutos (ignorados pelo Git). |

## Como rodar

Só biblioteca padrão do Python (3.11+):

```bash
python3 data/synthetic/calibration/calibrate.py            # obter -> registrar -> agregar
python3 data/synthetic/calibration/calibrate.py --offline  # sem rede, com o que já está em data/external/
python3 -m unittest discover -s data/synthetic/calibration/tests
```

O script faz três etapas:

1. **Obter:** baixa as fontes de `sources.json` para `data/external/<id>/`.
2. **Registrar:** grava `calibration/manifest.json` com URL, licença, data de obtenção, tamanho, sha256 e status de cada fonte. Também confere se as cópias em `reference/` batem com o checksum registrado.
3. **Agregar:** grava `calibration/calibration.yaml`.

A data de obtenção só muda quando o arquivo muda. Checksum divergente vira status `divergente` e precisa de revisão humana. O script termina com código 1 enquanto houver fonte pendente ou divergente; hoje a pendente é a ANTT (veja abaixo). Para uma fonte manual, coloque o arquivo em `data/external/<id>/` e rode com `--offline`.

## Fontes e licenças

**Só estatísticas, nunca linhas.** As fontes públicas calibram parâmetros (preços, distâncias, composição da frota). Nenhuma linha bruta é copiada para os dados sintéticos. O dataset Olist **não** é usado, por causa da licença CC BY-NC-SA.

| Fonte | Uso | Licença | Situação em 22/11/2026 |
| --- | --- | --- | --- |
| ANP, Anuário 2026, tabela 3.21 | Diesel médio por UF (2025: SP R$ 6,0858/l) | Creative Commons Atribuição (reconferir) | Baixada; só o agregado é versionado |
| kelvins/municipios-brasileiros | Coordenadas → distância em linha reta × fator de estrada | MIT | Versionada em `reference/` |
| Portal Nacional do CT-e (SVRS) | XSD do CT-e 4.00 para gerar e validar XMLs | Documentação pública oficial | Versionada em `reference/` |
| ANTT, RNTRC Veículos | Composição da frota por tipo e carroceria, para conferir a frota suposta | Creative Commons Atribuição (conferir) | **Pendente**: `dados.antt.gov.br` não respondeu; download manual |

Os parâmetros sem fonte (capacidades, consumo, tabela de frete, prazos, taxas de anomalia) estão marcados como `suposicao:equipe` em `empresa.yaml` e devem ser revistos com P1 e com as entrevistas.

## Regras

- Documentar semente, esquema, unidades, fuso, chaves e anomalias.
- Os dados de entrada ficam separados dos resultados esperados em `evaluation/golden/`. Gerador e gabarito não compartilham o algoritmo avaliado, e amostras do gabarito são conferidas à mão.
- Não copiar cadastros reais. CNPJs fictícios levam um dígito verificador propositalmente inválido.
- Atualizar uma fonte (checksum diferente) exige revisão humana da calibração antes de mudar `sources.json`.
