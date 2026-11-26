-- Uma chave fiscal repetida só pode ser deduplicada se os campos usados concordam.
with arquivos as (
    select arquivo, chave_cte, cstat, valor_centavos,
        string_agg(chave_nfe, '+' order by chave_nfe) as notas
    from {{ source('sinteticas', 'bronze_documentos') }}
    where especie = 'cte'
    group by arquivo, chave_cte, cstat, valor_centavos
)
select chave_cte from arquivos group by chave_cte
having min(cstat) <> max(cstat) or min(valor_centavos) <> max(valor_centavos) or min(notas) <> max(notas)
