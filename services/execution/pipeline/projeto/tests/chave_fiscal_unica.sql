select chave_cte, chave_nfe from {{ ref('prata_ctes') }}
group by chave_cte, chave_nfe having count(*) > 1
