with pedidos as (
    select sum(centavos) as custo, sum(elegivel_custo) as n_custo,
        sum(otif) as completos_no_prazo, sum(elegivel_otif) as n_otif
    from {{ ref('ouro_por_pedido') }}
), viagens as (
    select sum(peso_decimos_kg) as peso, sum(capacidade) as capacidade
    from {{ ref('ouro_por_viagem') }}
)
select {{ meio_par('custo * 100', 'n_custo') }} / 10000.0 as custo_frete_por_entrega,
    {{ meio_par('completos_no_prazo * 1000000', 'n_otif') }} / 10000.0 as otif_pct,
    {{ meio_par('peso * 100000', 'capacidade') }} / 10000.0 as ocupacao_pct
from pedidos cross join viagens
