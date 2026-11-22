# Fontes sintéticas

Área para geradores determinísticos e fixtures fictícias de ERP, TMS e CT-e.

**Status (22/11/2026):** rascunho para [K03](https://github.com/leeunam/korda/issues/3). Existem três empresas fictícias, o gerador das fontes sujas (ERP/TMS em CSV e CT-e em XML validado contra o XSD), a calibração com dados públicos e o gabarito independente em [`evaluation/golden/`](../../evaluation/golden/README.md). A K03 depende de K01 (contratos) e K02 (regras dos indicadores), ainda abertas. As `regras_referencia` de cada empresa são **proposta**, não regra aprovada.

## Estrutura

| Caminho | Conteúdo |
| --- | --- |
| [`empresas/<id>/empresa.yaml`](empresas/01_demo/empresa.yaml) | Uma por empresa (01_demo, 02_variacao, 03_reservada): fatos, faixas de anomalia, formato e nomes de coluna, `regras_referencia` e tolerâncias. Cada parâmetro tem `origem`. Também servirá à persona da entrevista simulada (P1/K04). |
| `empresas/<id>/area_atendimento.csv` | Sede e municípios atendidos, com peso de demanda. |
| [`generator/`](generator/generate.py) | Gerador determinístico (`generate.py`), XML de CT-e (`cte_xml.py`), validação XSD (`validate_xsd.py`) e testes. |
| `output/<id>/` | Fontes geradas (**ignoradas pelo Git**): `erp/`, `tms/`, `cte/` e `_gerador/` (contagens e registro de anomalias, que o gabarito não lê). |
| [`spec/dicionario.md`](spec/dicionario.md) | Esquemas "sujos" de ERP, TMS e CT-e e suas relações. |
| [`spec/anomalias.md`](spec/anomalias.md) | Problemas plantados, KPI afetado e o teste que deve nascer de cada um. |
| [`spec/cenarios.md`](spec/cenarios.md) | As três empresas, uso e diferenças entre elas. |
| [`calibration/`](calibration/sources.json) | `sources.json` (fontes declaradas), `calibrate.py` (processo único), [`manifest.json`](calibration/manifest.json) (procedência obtida, versionada), `calibration.yaml` (só agregados) e testes. |
| [`reference/municipios/`](reference/municipios/README.md) | Coordenadas dos municípios (MIT), versionadas. |
| [`reference/cte-xsd/PL_CTe_400/`](reference/cte-xsd/PL_CTe_400/README.md) | XSD oficiais do CT-e 4.00, versionados para validação offline. |
| `../external/` | Downloads brutos (ignorados pelo Git). |

## Gerar as fontes e o gabarito

Requer Python 3.11+ e [`requirements-synthetic.txt`](../../requirements-synthetic.txt) (PyYAML e lxml):

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements-synthetic.txt
.venv/bin/python data/synthetic/generator/generate.py --all        # ou --empresa 01_demo
.venv/bin/python data/synthetic/generator/validate_xsd.py --all    # 100% dos XML contra o XSD
.venv/bin/python evaluation/golden/compute_golden.py --all         # gabarito independente
.venv/bin/python evaluation/golden/sensitivity.py --all            # cada correção move o KPI?
.venv/bin/python -m unittest discover -s data/synthetic/generator/tests
.venv/bin/python -m unittest discover -s evaluation/golden/tests
```

A mesma semente gera bytes idênticos; `evaluation/golden/<id>/fontes.sha256` prova a correspondência entre gabarito e fontes. Os XML são fictícios: `tpAmb=2` (homologação), CNPJs com DV inválido e assinatura só estrutural, sem valor criptográfico.

## Calibração

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

A data de obtenção só muda quando o arquivo muda. Checksum divergente vira status `divergente` e precisa de revisão humana. O script termina com código 1 enquanto houver fonte pendente ou divergente. Para uma fonte manual, coloque o arquivo em `data/external/<id>/` e rode com `--offline`.

## Fontes e licenças

**Só estatísticas, nunca linhas.** As fontes públicas calibram parâmetros (preço do diesel e distâncias). Nenhuma linha bruta é copiada para os dados sintéticos. O dataset Olist **não** é usado, por causa da licença CC BY-NC-SA.

| Fonte | Uso | Licença | Situação em 22/11/2026 |
| --- | --- | --- | --- |
| ANP, Anuário 2026, tabela 3.21 | Diesel médio por UF (2025: SP R$ 6,0858/l) | Creative Commons Atribuição (reconferir) | Baixada; só o agregado é versionado |
| kelvins/municipios-brasileiros | Coordenadas → distância em linha reta × fator de estrada | MIT | Versionada em `reference/` |
| Portal Nacional do CT-e (SVRS) | XSD do CT-e 4.00 para gerar e validar XMLs | Documentação pública oficial | Versionada em `reference/` |

Os parâmetros sem fonte (capacidades, consumo, tabela de frete, prazos, taxas de anomalia) estão marcados como `suposicao:equipe` em `empresa.yaml` e devem ser revistos com P1 e com as entrevistas.

## Regras

- Documentar semente, esquema, unidades, fuso, chaves e anomalias.
- Os dados de entrada ficam separados dos resultados esperados em `evaluation/golden/`. Gerador e gabarito não compartilham o algoritmo avaliado, e amostras do gabarito são conferidas à mão.
- Não copiar cadastros reais. CNPJs fictícios levam um dígito verificador propositalmente inválido.
- Atualizar uma fonte (checksum diferente) exige revisão humana da calibração antes de mudar `sources.json`.
