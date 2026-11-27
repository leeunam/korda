"""Leitura de CSV exportado sem interpretar valores.

Detecta codificação, separador e cabeçalho a partir do próprio arquivo. Nada é fixado para
uma empresa: os nomes de coluna saem do cabeçalho, e todos os valores ficam como texto,
exatamente como no arquivo (sem trim, sem trocar vírgula decimal, sem converter datas).
Registro com número de campos diferente do cabeçalho vai para os rejeitados, com o número
da linha física e o texto bruto.
"""

from __future__ import annotations

import codecs
import csv
import io
import re
from collections import Counter
from dataclasses import dataclass, field

SEPARADORES = (";", ",", "|", "\t")
AMOSTRA_REGISTROS = 50

# Um valor "parece dado" se for número ou data. Cabeçalho não tem esse tipo de valor.
_NUMERO = re.compile(r"^[+-]?\d+(?:[.,]\d+)*$")
_DATA = re.compile(r"^\d{1,4}[-/.]\d{1,2}[-/.]\d{1,4}(?:[ T]\d{1,2}:\d{2}(?::\d{2})?)?$")


class ErroCsv(ValueError):
    """Arquivo que não pode virar tabela (por exemplo, nomes de coluna que colidem)."""


@dataclass
class Rejeitado:
    linha: int
    motivo: str
    conteudo_bruto: str


@dataclass
class CsvLido:
    codificacao: str
    separador: str
    cabecalho: bool
    colunas: list[str]
    colunas_originais: list[str]
    linhas: list[tuple[int, list[str]]] = field(default_factory=list)  # (_linha, valores)
    rejeitados: list[Rejeitado] = field(default_factory=list)


def decodificar(dados: bytes) -> tuple[str, str]:
    """Devolve (codificação detectada, texto). UTF-8 estrito primeiro; depois cp1252 e latin-1."""
    if dados.startswith(codecs.BOM_UTF8):
        try:
            return "utf-8-sig", dados[len(codecs.BOM_UTF8):].decode("utf-8")
        except UnicodeDecodeError:
            pass
    try:
        return "utf-8", dados.decode("utf-8")
    except UnicodeDecodeError:
        pass
    try:
        return "cp1252", dados.decode("cp1252")
    except UnicodeDecodeError:
        # latin-1 decodifica qualquer byte; fica registrado no manifesto.
        return "latin-1", dados.decode("latin-1")


def _amostra(texto: str, separador: str) -> list[list[str]]:
    leitor = csv.reader(io.StringIO(texto, newline=""), delimiter=separador)
    registros: list[list[str]] = []
    try:
        for registro in leitor:
            if registro:
                registros.append(registro)
            if len(registros) >= AMOSTRA_REGISTROS:
                break
    except csv.Error:
        pass
    return registros


def detectar_separador(texto: str) -> str:
    """Separador que produz o número de campos mais constante (e maior que 1) na amostra."""
    melhor: tuple[float, int, int] | None = None
    escolhido = SEPARADORES[0]
    for prioridade, sep in enumerate(SEPARADORES):
        registros = _amostra(texto, sep)
        if not registros:
            continue
        contagem = Counter(len(r) for r in registros)
        campos, vezes = contagem.most_common(1)[0]
        constancia = vezes / len(registros)
        # Ordem: mais constante; depois mais campos; depois a ordem de SEPARADORES.
        nota = (constancia if campos > 1 else 0.0, campos, -prioridade)
        if melhor is None or nota > melhor:
            melhor, escolhido = nota, sep
    return escolhido


def parece_cabecalho(registro: list[str]) -> bool:
    """Cabeçalho: algum nome preenchido e nenhum valor com cara de número ou data."""
    preenchidos = [v.strip() for v in registro if v.strip()]
    if not preenchidos:
        return False
    return not any(_NUMERO.match(v) or _DATA.match(v) for v in preenchidos)


def _nomes_unicos(nomes: list[str]) -> list[str]:
    """DuckDB não diferencia maiúsculas em nomes de coluna; repetidos ganham sufixo __2, __3."""
    vistos: Counter = Counter()
    saida = []
    for nome in nomes:
        chave = nome.lower()
        vistos[chave] += 1
        saida.append(nome if vistos[chave] == 1 else f"{nome}__{vistos[chave]}")
    return saida


def ler_csv(dados: bytes, reservados: tuple[str, ...] = ()) -> CsvLido:
    codificacao, texto = decodificar(dados)
    separador = detectar_separador(texto)

    fisicas: list[str] = []

    def _linhas():
        for linha in io.StringIO(texto, newline=""):
            fisicas.append(linha)
            yield linha

    leitor = csv.reader(_linhas(), delimiter=separador, strict=True)
    registros: list[tuple[int, list[str] | None, str, str | None]] = []  # (linha, valores, bruto, erro)
    while True:
        inicio = len(fisicas) + 1
        try:
            registro = next(leitor)
            erro = None
        except StopIteration:
            break
        except csv.Error as e:
            registro, erro = None, f"csv_invalido: {e}"
        bruto = "".join(fisicas[inicio - 1:])
        registros.append((inicio, registro, bruto, erro))

    if not registros:
        return CsvLido(codificacao, separador, False, [], [])

    primeiro = registros[0][1]
    cabecalho = primeiro is not None and parece_cabecalho(primeiro)
    if cabecalho:
        originais = list(primeiro)
        dados_reg = registros[1:]
        # Nome vazio (ex.: separador no fim do cabeçalho) vira coluna_<posição>.
        nomes = [n if n.strip() else f"coluna_{i}" for i, n in enumerate(originais, 1)]
    else:
        largura = Counter(len(r[1]) for r in registros if r[1]).most_common(1)
        n = largura[0][0] if largura else 1
        originais = []
        nomes = [f"coluna_{i}" for i in range(1, n + 1)]
        dados_reg = registros
    colunas = _nomes_unicos(nomes)
    colisao = {c.lower() for c in colunas} & {r.lower() for r in reservados}
    if colisao:
        raise ErroCsv(f"coluna com nome reservado da linhagem: {sorted(colisao)}")

    lido = CsvLido(codificacao, separador, cabecalho, colunas, originais)
    for linha, valores, bruto, erro in dados_reg:
        if erro:
            lido.rejeitados.append(Rejeitado(linha, erro, bruto))
        elif not valores:
            lido.rejeitados.append(Rejeitado(linha, "linha_vazia", bruto))
        elif len(valores) != len(colunas):
            lido.rejeitados.append(
                Rejeitado(linha, f"campos_{len(valores)}_esperados_{len(colunas)}", bruto)
            )
        else:
            lido.linhas.append((linha, valores))
    return lido
