# P1 · Contexto

Área reservada à descoberta; implementação pendente.

O [plano técnico atualizado em 24/11/2026](../../docs/plano-arquitetura-agentes-descoberta.md) delimita a entrega de Marcus ao backend: item 4 para API, persistência, pesquisa e entrevista por texto; item 5 para perfilamento, entrevista ao vivo e consolidação. O frontend está com outro integrante e será integrado posteriormente por contratos HTTP e sessão de mídia.

Já existem [materiais sintéticos](../../data/synthetic/discovery/README.md), [aceite offline](../../evaluation/discovery/README.md) e o [contrato de exportação](../../packages/contracts/context/v0.1.0/README.md). Eles não implementam o serviço. A primeira entrega funcional será verificável por API, cliente de terminal e testes com PostgreSQL.

Recebe conversa e acesso autorizado às fontes. Produz respostas com evidência, lacunas e perfil das fontes. Pergunta sobre decisão, processo, indicadores, exceções, responsáveis e destino. Diferencia uma declaração de uma regra confirmada.

O perfilamento de esquema, tipos, nulos e duplicatas deve ser determinístico quando possível. Lacunas críticas precisam ficar visíveis e bloquear o avanço afetado. A entrevista por texto é alternativa ao canal de voz/avatar; não pressupor integração contratada.
