# Avaliação offline dos materiais de descoberta

Este diretório pertence ao avaliador. Não deve ser montado no runtime dos agentes. O [roteiro do cliente](../../data/synthetic/discovery/01_demo/personas/roteiro.json) fica separado das [entradas iniciais](../../data/synthetic/discovery/01_demo/inputs/formulario.json).

[cenarios.json](01_demo/cenarios.json) especifica cinco jornadas independentes. Cada uma parte dos seis turnos de `baseline_round_1` e acrescenta seus próprios eventos em ordem. `delivery_id` identifica o recebimento; `turn_id` identifica a fala e persiste em reenvios. O cenário de retomada exige contar oito turnos únicos após nove recebimentos, sem deduplicar por texto.

Os dois JSONs de referência são **estados manuais sintéticos**, não resultados de um serviço:

- [01_rateio_pendente.json](01_demo/01_rateio_pendente.json): após a operação, custo bloqueado e rateio nulo, apesar da ocupação em kg.
- [02_rateio_confirmado.json](01_demo/02_rateio_confirmado.json): após o financeiro, rateio por peso, mesma lacuna resolvida, revisão incrementada e histórico preservado.

Para as variantes, o catálogo define invariantes por checkpoint em vez de duplicar contextos completos. `context_file=null` indica que o aceite está nos campos do checkpoint. Nenhum desses campos é fornecido ao modelo.

[check_context.py](check_context.py) compara uma futura saída com o contrato e o checkpoint: estado, regra, lacuna, indicador afetado, último turno, citações literais, evidência financeira e preservação de identidade/histórico. Não exige IDs específicos de evidência, ordem do JSON ou formulação exata de perguntas. Na continuidade, passar `previous` com a revisão anterior. `turns` deve conter apenas as falas já entregues ao agente naquele checkpoint.

[test_fixtures.py](tests/test_fixtures.py) confere os exemplos e exercita rejeições de citação inventada, confirmação setorial, perda de histórico e caminhos indevidos. As variantes são exercitadas com contextos montados no próprio teste para testar o avaliador. Isso não mede um organizador, um simulador nem uma API já implementados. A contagem do cenário de retomada valida o roteiro; a idempotência real será testada com a API.

```bash
python3 -m pip install -r requirements-discovery.txt
python3 -m pytest evaluation/discovery/tests -q
```

Não há importação do gerador ou do gabarito de indicadores para produzir os estados. As falas seguem o recorte documentado da 01, sem fechar K01/K02 nem substituir aprovações do produto. Para ensaio e limites, consultar os [materiais de descoberta](../../data/synthetic/discovery/README.md).
