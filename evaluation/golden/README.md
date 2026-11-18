# Avaliação independente

Área reservada aos casos de aceite e resultados esperados. Nenhum teste funcional foi implementado ainda.

O avaliador verifica os três indicadores com regras aprovadas e tolerâncias explícitas. Incluir cenários de erro e casos novos além da história principal da demo. Verificar resultado por pedido/viagem quando totais puderem esconder erro.

O agente de execução não pode alterar nem ler os resultados esperados. No runtime, montar essa área somente no avaliador independente e impor permissões de acesso. A publicidade do GitHub impede tratar os gabaritos como segredo; documentar essa limitação e separar a avaliação de desenvolvimento da execução do agente.

Uma falha legítima na especificação requer decisão humana e nova versão, não afrouxamento automático do teste.
