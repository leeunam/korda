# Contexto logístico sintético v0.1.0

Contrato local de leitura P1 → P2, adotado para o desenvolvimento de Marcus em 23/11/2026. Fixa o recorte do gerador de Gabriel integrado pelo PR #18. Não há consumidor de planejamento implementado nem aceite conjunto das quatro frentes registrado. As regras de `empresa.yaml` continuam sendo propostas de K02; as confirmações nos exemplos são falas fictícias para exercitar o contrato.

## Semântica do cenário

- Uma entrega por pedido. A entrega pode estar incompleta; `qt_itens` e `qt_entregue` contam volumes. Reentregas e completude por SKU exigem outro cenário.
- Vínculo do frete: `TMS.nr_ped → ERP.cd_ped → ERP.ch_nfe → CT-e.infNFe/chave`. Duplicatas têm a mesma chave; CT-e autorizado tem `cStat=100`; cancelamento homologado tem tipo `110111` e retorno `135`.
- Frete: `vTPrest` deduplicado e sem cancelados, distribuído pelo critério confirmado. Elegibilidade exige tipo de viagem permitido e CT-e válido; entrega incompleta continua elegível. Sem CT-e válido, o pedido sai apenas do custo. O rateio usa maiores restos em centavos, com empate por ID textual. Ver [avaliador](../../../../evaluation/golden/README.md).
- OTIF: `data(dt_realizada) <= prevista` **e** `qt_entregue >= qt_itens`. Usa o prazo explícito do ERP ou emissão + dias úteis conforme a empresa; a regra de sábado e o tratamento de data ausente vêm da confirmação.
- Ocupação: soma da carga / soma da capacidade, em kg ou m³ conforme a empresa, incluindo todas as viagens. A exclusão de tipos em custo/OTIF não é aplicada à ocupação.
- Datas das fontes seguem `America/Sao_Paulo`, sem offset no texto. Os [nomes e formatos reais](../../../../data/synthetic/spec/dicionario.md) variam por empresa. A 01 usa peso/falha/kg, a 02 volume/falha/kg e exclui TRF de custo/OTIF, a 03 valor/excluir/m³ e prazo sem sábado. O ensaio de entrevista usa só a 01.

## Leitura pelo planejador

O [schema](context.schema.json) contém identidade do projeto/contexto, revisão, último turno processado, fontes, evidências, perfil, regras e lacunas. IDs persistem entre revisões. `source.origin` distingue fornecida/descoberta; `source.scope` distingue empresa/setor. Pesquisa setorial pode motivar uma pergunta, sem confirmar uma regra da empresa. Cada evidência localiza seu trecho na versão da fonte indicada.

Uma regra `a_confirmar` ou `em_conflito` tem `value=null`, autor de confirmação nulo e lacuna bloqueante vinculada. Uma regra `confirmada` tem valor, evidências e nome/papel fictícios de quem confirmou. Nenhuma regra é inferida apenas da associação entre carga e ocupação. O organizador mantém a confirmação e os IDs das evidências; a integração de autenticação dos papéis será feita na aplicação.

Estados das lacunas: `aberta`, `a_confirmar`, `respondida`, `em_conflito`. Lacuna respondida exige regra confirmada e evidência compartilhada. Um contexto com regra pendente ou lacuna bloqueante continua `rascunho`. `affected_metrics` informa o escopo bloqueado e permite rascunhar os demais indicadores. `pronto_para_planejamento` permite propor o plano; a aprovação 1 continua sendo uma decisão humana sobre uma versão desse plano.

O validador confere o vínculo entre regra e indicadores: deduplicação, cancelamento e rateio afetam custo; ausência de data, prazo, sábado e completude afetam OTIF; unidade afeta ocupação; exclusão de tipos afeta custo e OTIF. Uma lacuna de rateio não pode apontar apenas para ocupação ou OTIF.

O contrato cobre somente contexto da demo logística sintética. Plano, eventos, execução e as duas aprovações continuam fora desta versão. O runtime entrega ao executor apenas fontes autorizadas; `empresa.yaml`, `_gerador/` e `evaluation/golden/` não entram na entrevista ou na execução como respostas descobertas.

## Duas revisões reproduzíveis

1. [Rateio pendente](examples/01_rateio_pendente.json): a operação informa o uso do peso na ocupação, mas encaminha a divisão do frete ao financeiro. `rateio_cte=null` e a lacuna bloqueia o custo.
2. [Rateio confirmado](examples/02_rateio_confirmado.json): o financeiro fictício confirma o peso bruto do pedido no ERP. A revisão 2 preserva as evidências anteriores, registra a nova fala e responde à mesma lacuna.

São exemplos escritos à mão, identificados como sintéticos; não são saídas de agentes já implementados nem aprovam regras comerciais. A revisão do schema muda `schema_version`; a atualização de evidências muda `revision`. O consumidor deve rejeitar versões desconhecidas.

## Verificar

```bash
python3 -m pip install -r requirements-contracts.txt
python3 -m unittest discover -s packages/contracts/context/v0.1.0/tests
python3 packages/contracts/context/v0.1.0/validate.py packages/contracts/context/v0.1.0/examples/01_rateio_pendente.json packages/contracts/context/v0.1.0/examples/02_rateio_confirmado.json
```

O validador usa [jsonschema 4.23.0](https://python-jsonschema.readthedocs.io/en/v4.23.0/validate/) e confere referências entre IDs, pendências e fechamento de lacunas. Ele valida o formato e a coerência do exemplo; a veracidade das fontes e a autorização real do confirmador precisam ser verificadas pela aplicação e pelo revisor humano.
