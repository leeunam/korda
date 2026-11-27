-- Uma linha por CT-e válido e NF-e referenciada. Mantém o arquivo escolhido para rastreamento.
with documentos as (
    select * from {{ source('sinteticas', 'bronze_documentos') }}
),
validos as (
    select d.*, row_number() over (
        partition by d.chave_cte, d.chave_nfe order by d.arquivo
    ) as copia
    from documentos d
    where d.especie = 'cte' and d.cstat = '100'
      and not exists (
          select 1 from documentos ev
          where ev.especie = 'evento' and ev.tipo_evento = '110111'
            and ev.cstat = '135' and ev.chave_cte = d.chave_cte
      )
)
select chave_cte, chave_nfe, valor_centavos, arquivo, sha256, carga
from validos
where copia = 1
