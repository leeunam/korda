with rateios as (
    select chave_cte, count(*) as n, count(centavos) as partes, sum(centavos) as total
    from {{ ref('prata_rateios') }} group by chave_cte
), validos as (
    select chave_cte, count(*) as nfes, max(valor_centavos) as valor
    from {{ ref('prata_ctes') }} group by chave_cte
)
select v.chave_cte from validos v left join rateios r using (chave_cte)
where r.chave_cte is null or r.n <> v.nfes or r.partes <> r.n or v.valor <> r.total
