-- A aritmética do rateio usa inteiros: frete em centavos, peso em décimos de kg.
with bases as (
    select c.*, p.pedido_id, p.peso_decimos_kg,
        sum(p.peso_decimos_kg) over (partition by c.chave_cte) as peso_total
    from {{ ref('prata_ctes') }} c
    join {{ source('sinteticas', 'bronze_pedidos') }} p using (chave_nfe)
), partes as (
    select *, valor_centavos * peso_decimos_kg as numerador
    from bases
), restos as (
    select *, numerador % nullif(peso_total, 0) as resto
    from partes
), inteiras as (
    select *, cast((numerador - resto) / nullif(peso_total, 0) as bigint) as parte_inteira
    from restos
), ordenadas as (
    select *, valor_centavos - sum(parte_inteira) over (partition by chave_cte) as faltam,
        row_number() over (partition by chave_cte order by resto desc, pedido_id) as ordem
    from inteiras
)
select chave_cte, chave_nfe, pedido_id, arquivo, sha256, valor_centavos,
    parte_inteira + case when ordem <= faltam then 1 else 0 end as centavos
from ordenadas
