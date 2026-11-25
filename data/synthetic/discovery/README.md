# Materiais sintéticos para o ensaio da descoberta

**Item 3 do planejamento de Marcus · 23/11/2026.** O conjunto prepara pesquisa e entrevista para o futuro organizador. As falas e os estados esperados foram escritos para teste; nenhum agente, frontend, pesquisa externa ou sessão de voz foi executado nesta etapa. Marcus responde por este recorte. A integração da descoberta continua em [K04](https://github.com/leeunam/korda/issues/4) e [K05](https://github.com/leeunam/korda/issues/5).

## Conteúdo e acesso

| Caminho | Conteúdo | Quem recebe no ensaio |
| --- | --- | --- |
| [01_demo/inputs/formulario.json](01_demo/inputs/formulario.json) | Empresa, objetivo, sistemas declarados e três participantes fictícios | API e pesquisador, como informação fornecida |
| [01_demo/inputs/fontes.json](01_demo/inputs/fontes.json) e `inputs/pesquisa/` | Três páginas locais, com versão, URL fictícia, data, origem fornecida/descoberta e escopo empresa/setor | Pesquisador e organizador; a descoberta da página é simulada |
| [01_demo/personas/roteiro.json](01_demo/personas/roteiro.json) | Onze falas: seis da primeira rodada, confirmação financeira e quatro falas para variantes | Condutor humano ou simulador do cliente, separado do agente entrevistador |
| [evaluation/discovery/](../../../evaluation/discovery/README.md) | Dois estados JSON manuais, cinco cenários, verificações semânticas e testes | Apenas o avaliador |

As páginas `.example` são cópias fictícias locais. Não tentar buscá-las na internet. A referência setorial apresenta alternativas de medição e perguntas; não confirma fatos ou regras da empresa. Antes da entrevista, os dados fornecidos não fecham o grão, as chaves, os significados das colunas nem a regra de rateio.

O roteiro não é um prompt a ser entregue inteiro ao entrevistador. O condutor entrega somente a resposta correspondente à pergunta feita, com ID de turno, sessão e participante. `question_example` mostra uma formulação possível para o ensaio humano; o aceite não exige essa frase. Uma variante começa novamente a partir da primeira rodada, sem misturar falas de outras variantes.

## Ensaio principal em duas rodadas

1. Entregar o formulário e as páginas locais. Separar o que foi fornecido do que foi descoberto; registrar como hipótese qualquer relação ainda não confirmada.
2. Na primeira rodada, percorrer os seis IDs de `baseline_round_1` do [catálogo do avaliador](../../../evaluation/discovery/01_demo/cenarios.json). Eles cobrem decisão, processo, fontes, responsáveis, exceções e os três indicadores.
3. A ocupação em kg fica confirmada no cenário. O rateio permanece nulo e com lacuna para o financeiro, bloqueando somente custo. A frase sobre lotação por peso não fecha essa regra.
4. Retomar o mesmo projeto em outra sessão e entregar `financeiro-rateio`. A nova revisão confirma peso, mantém a identidade da lacuna e todas as evidências anteriores. O estado pronto permite propor um plano; não equivale à aprovação humana do plano.

Os participantes e suas confirmações são fictícios. O perfil nos JSONs é uma descrição manual sustentada pela fala de `dados-processo`; não é resultado de um profiler. A verificação dos CSVs/XMLs e a autenticação dos participantes serão implementadas nas etapas seguintes.

## Variantes e critérios observáveis

| Cenário | Resultado a exigir da aplicação quando ela existir |
| --- | --- |
| Resposta ambígua | “Tamanho da carga” não vira peso, volume ou valor; pedir esclarecimento e manter o custo bloqueado |
| Contradição | Preservar as falas do financeiro e da operação; manter valor nulo, conflito explícito e custo bloqueado até nova confirmação |
| Correção com histórico | Registrar a reconfirmação pelo financeiro, resolver a mesma lacuna e preservar a declaração divergente |
| Retomada e reenvio | O reenvio do mesmo ID não duplica o turno. Uma nova fala idêntica, com outro ID, continua sendo outro turno. Ao final são oito turnos únicos para nove recebimentos |

O conjunto usa somente `01_demo`, coerente com o contrato e as regras de referência do Gabriel. Os [arquivos da 02](../empresas/02_variacao/empresa.yaml) continuam disponíveis como variação de desenvolvimento, com volume e transferências; este roteiro da 01 não deve ser aplicado à 02. A 03 permanece reservada para medição e não ganha roteiro ou resultados de entrevista neste conjunto. As regras das empresas continuam propostas pendentes de K02.

## Validar localmente

Python 3.11+; a aplicação futura usará a versão prevista no plano. As dependências desta etapa são Pydantic para entradas tipadas, pytest para os cenários e o jsonschema já adotado no contrato:

```bash
python3 -m pip install -r requirements-discovery.txt
python3 data/synthetic/discovery/validate.py
python3 -m pytest evaluation/discovery/tests -q
python3 scripts/check_repo.py
```

Versões fixadas em [requirements-discovery.txt](../../../requirements-discovery.txt): [Pydantic 2.12.4](https://pypi.org/project/pydantic/2.12.4/) e [pytest 8.4.2](https://pypi.org/project/pytest/8.4.2/). Não há chamadas a provedores, banco, frontend ou LLM para validar estes materiais.

## Preparar o ambiente futuro

O runtime inicial recebe apenas `01_demo/inputs/`. O simulador fica em outro processo e expõe uma fala de cada vez. Quando o perfilamento for implementado, montar separadamente somente `data/synthetic/output/01_demo/erp`, `tms` e `cte`, em modo somente leitura. Não montar o repositório inteiro, `empresas/`, `_gerador/`, personas futuras ou `evaluation/` nos agentes da descoberta ou execução. A separação de diretórios e as verificações deste conjunto não impõem isolamento por si só.

As verificações demonstram coerência dos materiais e detectam respostas incompatíveis com o aceite. A qualidade do entrevistador, persistência real, idempotência da API, perfilamento, papéis autenticados e isolamento precisam de testes da aplicação nas etapas 4 e 5.
