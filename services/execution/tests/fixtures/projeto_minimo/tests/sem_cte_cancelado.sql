-- Nenhum CT-e cancelado chega à prata (proposta K02).
select * from {{ ref('prata_cte') }} where status = 'cancelado'
