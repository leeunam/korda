-- O DuckDB fornece o tipo estático de cada coluna, inclusive nas relações vazias.
-- O ensaio SQLite confere o tipo de armazenamento dos valores efetivamente presentes.
{% set sqlite = target.type == 'sqlite' %}
{% set inteiros = ['TINYINT', 'SMALLINT', 'INTEGER', 'BIGINT', 'HUGEINT',
                   'UTINYINT', 'USMALLINT', 'UINTEGER', 'UBIGINT', 'UHUGEINT'] %}
{% set tipos = {'texto': ['VARCHAR', 'TEXT'], 'inteiro': inteiros,
                'numero': inteiros + ['FLOAT', 'REAL', 'DOUBLE'],
                'flag': inteiros + ['BOOLEAN'], 'data_iso': ['DATE', 'VARCHAR', 'TEXT']} %}
{% for tabela, campos in var('contrato_exportacao').items() %}
    {% set relacao = ref(tabela) %}
    {% for campo, familia in campos.items() %}
        select '{{ tabela }}' as tabela, '{{ campo }}' as campo, '{{ familia }}' as esperado, encontrado
        from (
            select upper(typeof(r.{{ campo }})) as encontrado
            {% if sqlite %}
                from {{ relacao }} as r
                where r.{{ campo }} is not null
            {% else %}
                from (select 1 as ancora) as a left join {{ relacao }} as r on false
                where true
            {% endif %}
              and not (
                upper(typeof(r.{{ campo }})) in ('{{ tipos[familia] | join("', '") }}')
                {% if familia == 'numero' %} or upper(typeof(r.{{ campo }})) like 'DECIMAL(%' {% endif %}
              )
            limit 1
        ) as falha
        {% if not loop.last %} union all {% endif %}
    {% endfor %}
    {% if not loop.last %} union all {% endif %}
{% endfor %}
