-- Junções obrigatórias: um registro sem par não pode desaparecer dos denominadores.
with pedidos as (select * from {{ source('sinteticas', 'bronze_pedidos') }}),
entregas as (select * from {{ source('sinteticas', 'bronze_entregas') }}),
viagens as (select * from {{ source('sinteticas', 'bronze_viagens') }}),
veiculos as (select * from {{ source('sinteticas', 'bronze_veiculos') }}),
documentos as (select * from {{ source('sinteticas', 'bronze_documentos') }})
select coalesce(e.arquivo, e.origem) as origem, e.entrega_id as identificador from entregas e
left join pedidos p using (pedido_id) left join viagens v using (viagem_id)
where p.pedido_id is null or v.viagem_id is null or e.entrega_id = ''
union all
select coalesce(v.arquivo, v.origem), v.viagem_id from viagens v left join veiculos c using (veiculo_id)
where c.veiculo_id is null or v.viagem_id = '' or v.tipo_viagem = ''
union all
select coalesce(p.arquivo, p.origem), p.pedido_id from pedidos p left join entregas e using (pedido_id)
where e.pedido_id is null or p.pedido_id = '' or p.chave_nfe = '' or p.qt_itens <= 0
union all
select coalesce(arquivo, origem), veiculo_id from veiculos where veiculo_id = ''
union all
select d.arquivo, d.chave_nfe from documentos d
left join pedidos p on p.chave_nfe = d.chave_nfe
where d.especie = 'cte' and d.cstat = '100' and p.pedido_id is null
  and not exists (
      select 1 from documentos ev where ev.especie = 'evento' and ev.tipo_evento = '110111'
        and ev.cstat = '135' and ev.chave_cte = d.chave_cte
  )
