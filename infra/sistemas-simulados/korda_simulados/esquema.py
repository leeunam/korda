"""Esquema lógico dos sistemas simulados.

Os nomes físicos das colunas vêm de `colunas` em `empresa.yaml` (o cliente conhece o próprio
sistema). Os tipos abaixo dizem como cada sistema **guarda** o dado, não como a exportação
CSV o escreve:

- ERP (Postgres): chaves, quantidades e valores tipados, como num ERP comum. `"363,9"` é um
  artefato da exportação CSV e vira `363.9` no banco.
- TMS (API JSON): números como número e `dt_saida` como data e hora ISO. `dt_realizada` é
  texto livre no TMS legado: mantém os formatos mistos, e vazio vira `null`.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

# tipo lógico -> tipo no Postgres
ERP = {
    "erp_clientes": {
        "id": "integer", "razao": "text", "cnpj": "text", "municipio_ibge": "integer", "ativo": "text",
    },
    "erp_pedidos": {
        "id": "integer", "cliente_id": "integer", "dt_emissao": "date", "dt_prevista": "date",
        "prazo_dias": "integer", "qt_itens": "integer", "peso_kg": "numeric", "volume_m3": "numeric",
        "valor_mercadoria": "numeric", "chave_nfe": "text",
    },
}
# tipo lógico -> representação no JSON da API
TMS = {
    "tms_veiculos": {"id": "texto", "placa": "texto", "tipo": "texto", "cap_kg": "numero", "cap_m3": "numero"},
    "tms_viagens": {"id": "inteiro", "veiculo_id": "texto", "dt_saida": "data_hora", "km": "numero", "tipo": "texto"},
    "tms_entregas": {
        "id": "inteiro", "viagem_id": "inteiro", "pedido_id": "inteiro", "seq": "inteiro",
        "qt_entregue": "inteiro", "dt_realizada": "texto_livre", "status": "texto",
    },
}
CHAVE = "id"
# Recurso da API para cada tabela do TMS.
RECURSOS = {"tms_veiculos": "veiculos", "tms_viagens": "viagens", "tms_entregas": "entregas"}
# Campo de metadado da API simulada (não existe na exportação CSV).
CAMPO_ATUALIZACAO = "atualizado_em"


class ErroEsquema(ValueError):
    pass


def numero(texto: str, decimal: str) -> Decimal:
    valor = texto.strip()
    if decimal != ".":
        valor = valor.replace(decimal, ".")
    try:
        return Decimal(valor)
    except Exception as e:  # noqa: BLE001 - qualquer falha de parse é erro do simulador
        raise ErroEsquema(f"número inválido: {texto!r}") from e


def data(texto: str, formato: str) -> dt.date:
    try:
        return dt.datetime.strptime(texto.strip(), formato).date()
    except ValueError as e:
        raise ErroEsquema(f"data inválida: {texto!r} (formato {formato})") from e


def data_hora(texto: str, formato: str) -> dt.datetime:
    try:
        return dt.datetime.strptime(texto.strip(), formato)
    except ValueError as e:
        raise ErroEsquema(f"data e hora inválida: {texto!r} (formato {formato})") from e


def valor_erp(tipo: str, texto: str, fmt: dict) -> str:
    """Valor para o COPY do Postgres (CSV): ISO para datas, ponto decimal, vazio = NULL."""
    if texto == "":
        return ""
    if tipo == "numeric":
        return str(numero(texto, fmt["csv"]["decimal"]))
    if tipo == "integer":
        return str(int(texto))
    if tipo == "date":
        return data(texto, fmt["data"]).isoformat()
    return texto


def valor_tms(tipo: str, texto: str, fmt: dict):
    if tipo == "texto_livre":
        return texto if texto != "" else None
    if texto == "":
        return None
    if tipo == "inteiro":
        return int(texto)
    if tipo == "numero":
        n = numero(texto, fmt["csv"]["decimal"])
        return int(n) if n == n.to_integral_value() and "." not in str(n) else float(n)
    if tipo == "data_hora":
        return data_hora(texto, fmt["data_hora_tms"]).isoformat(timespec="seconds")
    return texto
