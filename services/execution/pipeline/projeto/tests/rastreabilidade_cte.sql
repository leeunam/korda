-- Cada vínculo produzido deve corresponder ao XML específico e a um pedido do ERP.
-- Este teste depende da prata e suas falhas podem ser corrigidas nos modelos.
select p.chave_cte, p.chave_nfe, p.arquivo
from {{ ref('prata_ctes') }} p
left join {{ source('sinteticas', 'bronze_documentos') }} d
    on d.especie = 'cte' and d.cstat = '100'
    and d.chave_cte = p.chave_cte and d.chave_nfe = p.chave_nfe
    and d.arquivo = p.arquivo and d.sha256 = p.sha256
    and d.carga is not distinct from p.carga and d.valor_centavos = p.valor_centavos
left join {{ source('sinteticas', 'bronze_pedidos') }} pedido on pedido.chave_nfe = p.chave_nfe
where d.arquivo is null or pedido.pedido_id is null
