with frete as (
    select pedido_id, sum(centavos) as centavos,
        string_agg(chave_cte, '+' order by chave_cte) as ctes
    from {{ ref('prata_rateios') }}
    group by pedido_id
), avaliados as (
    select p.pedido_id, e.entrega_id, v.viagem_id, v.tipo_viagem,
        p.arquivo as arquivo_pedido, p.linha as linha_pedido,
        e.arquivo as arquivo_entrega, e.linha as linha_entrega,
        p.origem as origem_pedido, p.carga as carga_pedido, e.origem as origem_entrega, e.carga as carga_entrega,
        p.chave_nfe, p.qt_itens, e.qt_entregue, p.peso_decimos_kg,
        case when f.pedido_id is null then 0 else 1 end as elegivel_custo,
        coalesce(f.centavos, 0) as centavos, coalesce(f.ctes, '') as ctes,
        p.data_prevista, e.data_realizada, 1 as elegivel_otif,
        case when e.data_realizada <= p.data_prevista then 1 else 0 end as no_prazo,
        case when e.qt_entregue >= p.qt_itens then 1 else 0 end as completo
    from {{ source('sinteticas', 'bronze_entregas') }} e
    join {{ source('sinteticas', 'bronze_pedidos') }} p using (pedido_id)
    join {{ source('sinteticas', 'bronze_viagens') }} v using (viagem_id)
    left join frete f using (pedido_id)
)
select *, centavos / 100.0 as custo_frete_rateado, no_prazo * completo as otif
from avaliados
