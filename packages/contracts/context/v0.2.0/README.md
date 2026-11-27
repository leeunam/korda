# Contexto de entrevista v0.2.0

Contrato da entrevista por WhatsApp com texto e áudio transcrito. Esta versão é independente do [contrato anterior](../v0.1.0/README.md); não altera seus consumidores. Conteúdo e participantes dos exemplos são sintéticos e não confirmam regras comerciais.

O [schema](context.schema.json) é gerado a partir dos modelos de domínio do backend. O [validador](validate.py) verifica formato, referências, prontidão e, opcionalmente, continuidade com uma revisão anterior. A aplicação valida ainda citações contra o texto recebido e autoridade contra o cadastro do participante. Um JSON isolado não prova a veracidade das falas nem autentica quem as fez.

## Semântica

- Identificadores são gerados pela aplicação e persistem entre revisões. Novas mensagens não reescrevem evidências anteriores; correções criam uma afirmação sucessora.
- Afirmações distinguem `declarada`, `confirmada`, `em_conflito` e `substituida`. Informações ausentes são lacunas; não se preenchem valores por inferência.
- O papel autorizado vem de `required_topics`, definido pelo operador. Cada tópico obrigatório exige afirmações confirmadas e ausência de bloqueios antes de o contexto ficar `pronto`.
- Confirmação exige uma resposta explícita a um desafio anterior, ligado ao participante cadastrado. O modelo não pode se atribuir autoridade nem confirmar uma nova afirmação no mesmo turno.
- Um participante pode ter vários papéis autorizados no cadastro, com um único número WhatsApp. `participant_role` na evidência e `role` na confirmação registram o papel exercido naquele tópico, escolhido pelo backend dentre os papéis cadastrados. Dois participantes com papéis separados também são permitidos; o formato do contrato permanece o mesmo.
- Fontes mencionadas continuam `source_verification=nao_inspecionada` e `inspected=false`.
- Evidências localizam trechos literais, mensagem, participante, horário original e versão da transcrição. Uma transcrição é evidência derivada do áudio.
- Encerrar a entrevista não concede aprovação de plano nem autorização de entrega. `interview_status` e `state` são independentes.

## Recuperação e exemplos

**Estrutura preparada para recuperação por relações; adoção de GraphRAG condicionada à avaliação do consumidor de contexto.** Entidades e relações possuem IDs e evidências; resumo e tópicos permitem localizar relações e recuperar evidências sem enviar todo o histórico. Toda leitura está vinculada à mesma revisão. PostgreSQL mantém a fonte de verdade; um eventual índice derivado será reconstruível.

Exemplos: [inicial](examples/01_initial.json), [bloqueado](examples/02_blocked.json), [confirmado](examples/03_confirmed.json) e [conflito](examples/04_conflict.json). São construídos pelo organizador com propostas sintéticas, sem chamadas de modelo. Não medem qualidade de extração de uma IA real.

No ambiente Python do backend, a partir da raiz:

```powershell
python packages/contracts/context/v0.2.0/validate.py packages/contracts/context/v0.2.0/examples/01_initial.json packages/contracts/context/v0.2.0/examples/02_blocked.json packages/contracts/context/v0.2.0/examples/03_confirmed.json packages/contracts/context/v0.2.0/examples/04_conflict.json
python packages/contracts/context/v0.2.0/validate.py --previous packages/contracts/context/v0.2.0/examples/02_blocked.json packages/contracts/context/v0.2.0/examples/03_confirmed.json
```
