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

O destino e os R$ 1,25 do comando são valores fictícios de entrada. Quando omitidos, seus campos ficam nulos para revisão. O destino é um identificador lógico que a aplicação associa ao destino real. A estimativa está em centavos inteiros de real. No modo padrão, N0, o lote cobre os arquivos exportados autorizados.

O contexto de rateio pendente gera um rascunho com custo bloqueado. OTIF e ocupação já podem ser revisados. A confirmação fictícia do financeiro gera outra versão que pode receber a primeira aprovação humana. O contrato documenta a identidade do plano e o limite entre a decisão de negócio e o consumo pelo worker. [Contrato P2](../../packages/contracts/plan/v0.2.0/README.md)

O par `demo-01` e `ctx-demo-01` dos exemplos P1 identifica, por convenção da demo, o lote `01_demo`. Para outro contexto, o operador indica o lote com `--dataset`. A omissão deixa o vínculo pendente. Na v0.2.0, a lista explícita da demo cobre os cinco modelos SQL de prata e ouro. O worker verifica se o lote e as regras são suportados antes da execução.

## Aprovar a ingestão e o período

O comando padrão gera um plano v0.2.0 para N0. Para N1, informe a proposta de acesso aos três sistemas simulados. O arquivo abaixo identifica o mesmo projeto e a mesma revisão da descoberta usados no primeiro exemplo.

```bash
export PYTHONPATH=services/planning
python3 -m korda_planning packages/contracts/context/v0.1.0/examples/02_rateio_confirmado.json \
  --nivel-ingestao n1 --proposta-ingestao packages/contracts/ingestion_plan/v0.1.0/examples/01_demo.json \
  --destino painel-demo --custo-estimado-centavos 125 > /tmp/plano-korda-n1.json
python3 -m korda_planning --validar /tmp/plano-korda-n1.json
```

Sem corte, o escopo do N1 é o lote completo. Acrescentar `--ate-dia 2026-09-29` propõe o replay até esse dia inclusive. O planejador registra a janela, a proposta de ingestão inteira e seu hash. O worker precisa verificar se a janela materializada corresponde à aprovada e se há avaliação independente que cubra o mesmo período.

A seção N1 conserva suas lacunas. Se continuar em rascunho, o plano completo também fica em rascunho. Método, frequência e latência dos exemplos continuam propostas para revisão. A descoberta permanece a origem das regras dos KPIs. Mudar a seção, o nível ou a janela altera a versão que precisa de nova aprovação humana.

Os [planos v0.1.0](../../packages/contracts/plan/v0.1.0/README.md) existentes mantêm sua versão e a permissão original de editar `models/prata_ctes.sql`. Para passar do plano antigo ao novo fluxo, gere um plano v0.2.0, registre-o e submeta a nova versão à aprovação.
