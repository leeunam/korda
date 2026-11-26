{# quociente inteiro arredondado para o par mais próximo, usando o resto inteiro para decidir o empate #}
{% macro meio_par(n, d) -%}
(
    floor(({{ n }}) / nullif(({{ d }}), 0))
    + case
        when 2 * (({{ n }}) % nullif(({{ d }}), 0)) > ({{ d }})
            or (2 * (({{ n }}) % nullif(({{ d }}), 0)) = ({{ d }})
                and ({{ n }}) % nullif(2 * ({{ d }}), 0) >= ({{ d }}))
        then 1 else 0 end
)
{%- endmacro %}
