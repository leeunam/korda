# P2 · Planejamento

O planejador gera uma proposta revisável para os três indicadores da transportadora sintética. Cada indicador referencia suas fontes, chaves, regras, fórmula, denominador e verificações de aceite. As tarefas especificam os resultados verificáveis das camadas bronze, prata e ouro. O plano conserva os IDs e as evidências do contexto de descoberta.

## Gerar e validar

A partir da raiz do projeto, instale as dependências de contratos em um ambiente Python 3.11 ou superior e execute o exemplo sintético.

```bash
python3 -m pip install -r requirements-contracts.txt
export PYTHONPATH=services/planning
python3 -m korda_planning packages/contracts/context/v0.1.0/examples/02_rateio_confirmado.json \
  --destino painel-demo --custo-estimado-centavos 125 > /tmp/plano-korda.json
python3 -m korda_planning --validar /tmp/plano-korda.json
python3 -m unittest discover -s services/planning/tests
```

O destino e os R$ 1,25 do comando são valores fictícios de entrada. Quando omitidos, seus campos ficam nulos para revisão. O destino é um identificador lógico que a aplicação associa ao destino real. A estimativa está em centavos inteiros de real. O lote inteiro de arquivos autorizados é o período proposto da demonstração.

O contexto de rateio pendente gera um rascunho com custo bloqueado. OTIF e ocupação já podem ser revisados. A confirmação fictícia do financeiro gera outra versão que pode receber a primeira aprovação humana. O contrato documenta a identidade do plano e o limite entre a decisão de negócio e o consumo pelo worker. [Contrato P2](../../packages/contracts/plan/v0.1.0/README.md)

O par `demo-01` e `ctx-demo-01` dos exemplos P1 identifica, por convenção da demo, o lote `01_demo`. Para outro contexto, o operador indica o lote com `--dataset`. A omissão deixa o vínculo pendente. Com o lote `01_demo`, o plano autoriza `editable_models: ["models/*"]`: o harness da execução constrói todos os modelos SQL a partir do plano, e testes, definições e configuração continuam protegidos. O worker verifica se o lote e as regras são suportados antes da execução.
