-- Junções obrigatórias: um registro sem par não pode desaparecer dos denominadores.
with pedidos as (select * from {{ source('sinteticas', 'bronze_pedidos') }}),
entregas as (select * from {{ source('sinteticas', 'bronze_entregas') }}),
viagens as (select * from {{ source('sinteticas', 'bronze_viagens') }}),
veiculos as (select * from {{ source('sinteticas', 'bronze_veiculos') }})
select e.arquivo as origem, e.entrega_id as identificador from entregas e
left join pedidos p using (pedido_id) left join viagens v using (viagem_id)
where p.pedido_id is null or v.viagem_id is null or e.entrega_id = ''
union all
select v.arquivo, v.viagem_id from viagens v left join veiculos c using (veiculo_id)
where c.veiculo_id is null or v.viagem_id = '' or v.tipo_viagem = ''
union all
select p.arquivo, p.pedido_id from pedidos p left join entregas e using (pedido_id)
where e.pedido_id is null or p.pedido_id = '' or p.chave_nfe = '' or p.qt_itens <= 0
union all
select arquivo, veiculo_id from veiculos where veiculo_id = ''
union all
select c.arquivo, c.chave_nfe from {{ ref('prata_ctes') }} c
left join pedidos p using (chave_nfe) where p.pedido_id is null
