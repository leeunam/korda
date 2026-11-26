with totais as (
    select v.viagem_id, v.veiculo_id, v.tipo_viagem, v.arquivo as arquivo_viagem, v.linha as linha_viagem,
        c.arquivo as arquivo_veiculo, c.linha as linha_veiculo, c.capacidade_kg as capacidade,
        count(p.pedido_id) as n_entregas,
        coalesce(sum(p.elegivel_custo), 0) as n_entregas_elegiveis_custo,
        coalesce(sum(p.peso_decimos_kg), 0) as peso_decimos_kg,
        coalesce(sum(p.centavos), 0) as centavos
    from {{ source('sinteticas', 'bronze_viagens') }} v
    join {{ source('sinteticas', 'bronze_veiculos') }} c on c.veiculo_id = v.veiculo_id
    left join {{ ref('ouro_por_pedido') }} p on p.viagem_id = v.viagem_id
    group by v.viagem_id, v.veiculo_id, v.tipo_viagem, v.arquivo, v.linha, c.arquivo, c.linha, c.capacidade_kg
)
select *, 'kg' as unidade, peso_decimos_kg / 10.0 as carga,
    {{ meio_par('peso_decimos_kg * 1000', 'capacidade') }} / 10000.0 as ocupacao,
    case when peso_decimos_kg > 10 * capacidade then 1 else 0 end as acima_capacidade,
    centavos / 100.0 as custo_frete_total,
    {{ meio_par('centavos', 'n_entregas_elegiveis_custo') }} / 100.0 as custo_por_entrega
from totais
