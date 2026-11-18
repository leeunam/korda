# P3 · Execução

Área reservada à construção e teste; implementação pendente.

Recebe plano aprovado e fontes sintéticas. Produz modelos bronze/prata/ouro, indicadores, relatório de testes, documentação e linhagem. Proposta inicial: Python, DuckDB e dbt.

Ferramentas previstas: ler plano, perfilar fonte, escrever modelos autorizados, executar dbt, consultar dados em modo leitura, solicitar aprovação e emitir eventos. São interfaces a implementar, não ferramentas disponíveis neste diretório.

O executor não modifica fontes, testes ou gabaritos. Até três correções por etapa é o limite inicial proposto. Falha persistente, mudança de regra ou lacuna crítica devem interromper o trecho afetado. Somente a aprovação 2 permite promover a entrega para destino definido.
