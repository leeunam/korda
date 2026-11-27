"""Compara os três artefatos da execução com a referência logística fora da sandbox."""

import argparse
import csv
import hashlib
import io
import json
import os
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .arquivos import _abrir_diretorio, _ler_arquivo, _sem_repeticao
from .landing import conferir_landing, conferir_linhagem, conferir_janela

GOLDEN = Path(__file__).resolve().parents[1] / "golden"
EMPRESAS = {"01_demo", "02_variacao", "03_reservada"}
LIMITE_LINHAS = 20_000
LIMITE_EXEMPLOS = 20

KPIS = ("custo_frete_por_entrega", "otif_pct", "ocupacao_pct")
TABELAS = {
    "por_pedido.csv": (
        "pedido_id", "viagem_id", "tipo_viagem", "elegivel_custo", "custo_frete_rateado",
        "ctes", "data_prevista", "data_realizada", "elegivel_otif", "no_prazo", "completo", "otif",
    ),
    "por_viagem.csv": (
        "viagem_id", "veiculo_id", "tipo_viagem", "n_entregas", "n_entregas_elegiveis_custo",
        "carga", "custo_frete_total", "capacidade", "unidade", "ocupacao",
        "acima_capacidade", "custo_por_entrega",
    ),
}
FLAGS = {"elegivel_custo", "elegivel_otif", "no_prazo", "completo", "otif", "acima_capacidade"}
NUMEROS = set(KPIS) | {"custo_frete_rateado", "n_entregas", "n_entregas_elegiveis_custo",
                        "carga", "custo_frete_total", "capacidade", "ocupacao", "custo_por_entrega"}
ACEITA_NULO = set(KPIS) | {"custo_por_entrega"}
# O gabarito publica quatro casas para KPIs e ocupação por viagem, três para a carga.
MEIA_UNIDADE = {k: Decimal("0.00005") for k in (*KPIS, "ocupacao")}
MEIA_UNIDADE["carga"] = Decimal("0.0005")
REGRAS_VARIAVEIS = ("rateio_cte", "sem_data_realizada", "ocupacao_unidade",
                    "prazo_conta_sabado", "excluir_tipos_viagem")


def _kpis(fd):
    objeto = json.loads(_ler_arquivo(fd, "kpis.json").decode("utf-8"), parse_float=Decimal,
                        object_pairs_hook=_sem_repeticao)
    campos = objeto.get("kpis") if isinstance(objeto, dict) else None
    if not isinstance(campos, dict) or not set(KPIS).issubset(campos):
        raise ValueError("kpis.json: faltam indicadores obrigatórios")
    for campo in KPIS:
        if campos[campo] is not None and type(campos[campo]) not in (Decimal, int):
            raise ValueError(f"kpis.json: {campo} exige número finito ou null")
    return objeto


def _linhas(fd, nome, colunas):
    dados = _ler_arquivo(fd, nome).decode("utf-8")
    leitor = csv.DictReader(io.StringIO(dados, newline=""), strict=True)
    cabecalho = leitor.fieldnames or []
    if len(cabecalho) != len(set(cabecalho)) or not set(colunas).issubset(cabecalho):
        raise ValueError(f"{nome}: cabeçalho duplicado ou ausente para coluna obrigatória")
    por_id = {}
    for linha in leitor:
        if None in linha or None in linha.values():
            raise ValueError(f"{nome}: largura de linha diferente do cabeçalho")
        chave = linha[colunas[0]]
        if not chave or chave in por_id:
            raise ValueError(f"{nome}: identificador ausente ou repetido")
        if len(por_id) >= LIMITE_LINHAS:
            raise ValueError(f"{nome}: limite de linhas excedido")
        por_id[chave] = linha
    return por_id


def _valor(campo, valor):
    if campo in FLAGS:
        texto = str(valor).lower()
        if texto not in ("0", "1", "false", "true"):
            raise ValueError(f"{campo}: indicador lógico inválido")
        return texto in ("1", "true")
    if campo in NUMEROS:
        if campo in ACEITA_NULO and valor in (None, ""):
            return None
        numero = Decimal(str(valor))
        if not numero.is_finite() or numero.copy_abs() > 10**16:
            raise ValueError(f"{campo}: número fora do intervalo da demonstração")
        return numero
    if campo == "ctes":
        return tuple(sorted(valor.split("+"))) if valor else ()
    return valor


def _coincide(campo, esperado, encontrado):
    a, b = _valor(campo, esperado), _valor(campo, encontrado)
    if isinstance(a, Decimal) and isinstance(b, Decimal):
        return abs(a - b) <= MEIA_UNIDADE.get(campo, 0)
    return a == b


def _diferenca(relatorio, local, campo, esperado, encontrado):
    relatorio["divergencias"] += 1
    if len(relatorio["exemplos"]) < LIMITE_EXEMPLOS:
        relatorio["exemplos"].append({
            "local": local[:100], "campo": campo,
            "esperado": None if esperado is None else str(esperado)[:120],
            "encontrado": None if encontrado is None else str(encontrado)[:120],
        })


def _empate_ocupacao(esperado, encontrado):
    # O gabarito histórico soma cargas em float. Em um meio exato ele pode publicar
    # o vizinho oposto a half-even. Aceita ambos só quando o quociente de referência prova o empate.
    carga = _valor("carga", esperado["carga"])
    capacidade = _valor("capacidade", esperado["capacidade"])
    if capacidade <= 0:
        return False
    inteiro, resto = divmod(carga * 10_000, capacidade)
    if 2 * resto != capacidade:
        return False
    vizinhos = {inteiro / 10_000, (inteiro + 1) / 10_000}
    return {_valor("ocupacao", esperado["ocupacao"]), _valor("ocupacao", encontrado)} == vizinhos


def _comparar_campos(relatorio, local, campos, esperado, encontrado):
    for campo in campos:
        if not _coincide(campo, esperado[campo], encontrado[campo]):
            if campo == "ocupacao" and _empate_ocupacao(esperado, encontrado[campo]):
                continue
            _diferenca(relatorio, local, campo, esperado[campo], encontrado[campo])


def _conferir_fontes(pasta, referencia):
    esperado = {nome: digest for digest, nome in (
        linha.split("  ", 1) for linha in (referencia / "fontes.sha256").read_text().splitlines()
    )}
    encontrados = {}
    for subpasta, sufixo in (("erp", ".csv"), ("tms", ".csv"), ("cte", ".xml")):
        with _abrir_diretorio(Path(pasta) / subpasta) as fd:
            for nome in os.listdir(fd):
                if nome.endswith(sufixo):
                    chave = f"{subpasta}/{nome}"
                    if chave not in esperado:
                        raise ValueError(f"fonte fora da referência: {chave}")
                    encontrados[chave] = hashlib.sha256(_ler_arquivo(fd, nome)).hexdigest()
                    if esperado[chave] != encontrados[chave]:
                        raise ValueError(f"conteúdo de fonte divergente: {chave}")
    if esperados_ausentes := esperado.keys() - encontrados.keys():
        raise ValueError(f"fonte ausente: {min(esperados_ausentes)}")
    return esperado


def avaliar(diretorio_resultados, empresa_id, *, fontes=None, regras=None, landing=None, janela_replay=None):
    """Retorna laudo do revisor. O chamador confiável escolhe o cenário e as fontes aprovadas."""
    relatorio = {"aprovado": False, "classe": "regra", "empresa": empresa_id,
                 "fontes_conferidas": False, "regras_conferidas": False,
                 "comparados": {}, "divergencias": 0, "exemplos": []}
    trilha = None
    try:
        if janela_replay is not None and landing is None:
            raise ValueError("janela de replay exige landing de nível 1")
        if landing is not None:
            if fontes is None or regras is None or empresa_id != "01_demo":
                raise ValueError("aceite da landing exige fontes e regras da demonstração 01_demo")
            nivel = 1 if janela_replay is not None else 0
            relatorio.update(nivel=nivel, landing_conferida=False, linhagem_conferida=False)
            if janela_replay is not None:
                if isinstance(janela_replay, (tuple, list)):
                    relatorio["janela_replay"] = list(janela_replay)
                conferir_janela(janela_replay)
        if empresa_id not in EMPRESAS:
            raise ValueError("cenário sem referência independente")
        referencia = GOLDEN / empresa_id
        with _abrir_diretorio(referencia) as fid:
            ref = _kpis(fid)
            if ref.get("empresa_id") != empresa_id:
                raise ValueError("cenário da referência incompatível")
            if regras is not None:
                if not isinstance(regras, dict):
                    raise ValueError("regras aprovadas devem ser um objeto")
                for campo in REGRAS_VARIAVEIS:
                    if (campo not in regras or type(regras[campo]) is not type(ref["regras_referencia"][campo])
                            or regras[campo] != ref["regras_referencia"][campo]):
                        raise ValueError(f"regra aprovada difere da referência em {campo}; requer revisão")
                relatorio["regras_conferidas"] = True
            tabelas = {nome: _linhas(fid, nome, campos) for nome, campos in TABELAS.items()}
        if fontes is not None:
            relatorio["classe"] = "dados"
            inventario = _conferir_fontes(fontes, referencia)
            relatorio["fontes_conferidas"] = True
            if landing is not None:
                trilha = conferir_landing(landing, fontes, inventario, nivel, janela_replay)
                relatorio["landing_conferida"] = True
        relatorio["classe"] = "implementacao"
        with _abrir_diretorio(diretorio_resultados) as fid:
            encontrado = _kpis(fid)["kpis"]
            _comparar_campos(relatorio, "kpis.json", KPIS, ref["kpis"], encontrado)
            relatorio["comparados"]["kpis"] = len(KPIS)
            for nome, campos in TABELAS.items():
                esperado = tabelas[nome]
                obtido = _linhas(fid, nome, campos)
                for chave, linha in esperado.items():
                    if chave not in obtido:
                        _diferenca(relatorio, nome, campos[0], chave, None)
                    else:
                        if trilha is not None:
                            conferir_linhagem(nome, obtido[chave], linha, trilha)
                        _comparar_campos(relatorio, f"{nome}/{chave}", campos[1:], linha, obtido[chave])
                for chave in sorted(obtido.keys() - esperado.keys()):
                    _diferenca(relatorio, nome, campos[0], None, chave)
                relatorio["comparados"][nome] = len(esperado.keys() & obtido.keys())
        if not relatorio["divergencias"]:
            if trilha is not None:
                relatorio["linhagem_conferida"] = True
            relatorio.update(aprovado=True, classe="ok")
    except (OSError, ValueError, csv.Error, RecursionError, InvalidOperation) as erro:
        relatorio["erro"] = str(erro)[:300]
    return relatorio


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--empresa", required=True, choices=sorted(EMPRESAS))
    parser.add_argument("--resultados", type=Path, required=True)
    parser.add_argument("--fontes", type=Path, help="Diretório do cenário contendo erp, tms e cte")
    parser.add_argument("--landing", type=Path, help="Landing congelada produzida pela ingestão da demo")
    parser.add_argument("--regras", type=Path, help="JSON das regras efetivamente aprovadas (chave → valor)")
    parser.add_argument("--janela-replay", nargs=2, metavar=("DIA_ATUAL", "DIA_FINAL"),
                        help="Dias ISO informados pelo controlador do simulador N1")
    args = parser.parse_args()
    regras = json.loads(args.regras.read_text(encoding="utf-8")) if args.regras else None
    laudo = avaliar(args.resultados, args.empresa, fontes=args.fontes, regras=regras,
                    landing=args.landing, janela_replay=args.janela_replay)
    print(json.dumps(laudo, ensure_ascii=False, indent=2))
    return 0 if laudo["aprovado"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
