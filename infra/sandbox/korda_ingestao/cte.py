"""Leitura de XML do CT-e 4.00 (layout nacional, XSD do Portal Nacional do CT-e).

O layout é padrão nacional, então os campos são fixados pelo XSD. O tipo de documento vem
do elemento raiz, não do nome do arquivo:

- `cteProc` (CT-e + protocolo): uma linha em `cte`, uma por `infNFe` em `cte_nfe` e uma por
  `infQ` em `cte_carga`;
- `procEventoCTe` (evento + retorno): uma linha em `cte_evento`. O cancelamento (110111)
  chega assim, num XML separado; o `cteProc` original continua com cStat 100.

Nada é deduplicado nem filtrado: duas cópias do mesmo XML geram duas linhas. Valores ficam
como texto. Tag ausente vira None (NULL); tag presente e vazia vira ''.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from lxml import etree

NS = "http://www.portalfiscal.inf.br/cte"
_N = {"c": NS}

# Parser seguro: sem entidades externas, sem DTD, sem rede, sem árvores gigantes.
_PARSER = etree.XMLParser(
    resolve_entities=False, no_network=True, load_dtd=False, dtd_validation=False, huge_tree=False
)

COLUNAS_CTE = [
    "infCte_Id", "chCTe", "versao", "cUF", "cCT", "CFOP", "natOp", "mod", "serie", "nCT", "dhEmi",
    "tpAmb", "tpCTe", "tpServ", "modal", "cMunIni", "xMunIni", "UFIni", "cMunFim", "xMunFim", "UFFim",
    "emit_CNPJ", "emit_xNome", "rem_CNPJ", "rem_CPF", "rem_xNome", "dest_CNPJ", "dest_CPF",
    "dest_xNome", "vTPrest", "vRec", "vCarga", "proPred", "rntrc",
    "prot_chCTe", "prot_cStat", "prot_xMotivo", "prot_nProt", "prot_dhRecbto",
]
COLUNAS_NFE = ["chCTe", "_ordem", "chave"]
COLUNAS_CARGA = ["chCTe", "_ordem", "cUnid", "tpMed", "qCarga"]
COLUNAS_EVENTO = [
    "infEvento_Id", "chCTe", "cOrgao", "tpAmb", "CNPJ", "tpEvento", "nSeqEvento", "dhEvento",
    "descEvento", "nProt_cte", "xJust",
    "ret_chCTe", "ret_cStat", "ret_xMotivo", "ret_tpEvento", "ret_nProt", "ret_dhRegEvento",
]


@dataclass
class CteLido:
    cte: list[dict] = field(default_factory=list)
    cte_nfe: list[dict] = field(default_factory=list)
    cte_carga: list[dict] = field(default_factory=list)
    cte_evento: list[dict] = field(default_factory=list)
    rejeitado: str | None = None  # motivo, se o XML não virou linha


def _t(el, caminho: str) -> str | None:
    if el is None:
        return None
    achado = el.find(caminho, _N)
    if achado is None:
        return None
    return achado.text if achado.text is not None else ""


def _cte_proc(raiz) -> CteLido:
    inf = raiz.find("c:CTe/c:infCte", _N)
    if inf is None:
        return CteLido(rejeitado="estrutura_inesperada: cteProc sem CTe/infCte")
    id_ = inf.get("Id")
    ch = id_[3:] if id_ and id_.startswith("CTe") else None
    ide = inf.find("c:ide", _N)
    prot = raiz.find("c:protCTe/c:infProt", _N)
    norm = inf.find("c:infCTeNorm", _N)
    linha = {
        "infCte_Id": id_, "chCTe": ch, "versao": inf.get("versao"),
        **{k: _t(ide, f"c:{k}") for k in (
            "cUF", "cCT", "CFOP", "natOp", "mod", "serie", "nCT", "dhEmi", "tpAmb", "tpCTe", "tpServ",
            "modal", "cMunIni", "xMunIni", "UFIni", "cMunFim", "xMunFim", "UFFim")},
        "emit_CNPJ": _t(inf, "c:emit/c:CNPJ"), "emit_xNome": _t(inf, "c:emit/c:xNome"),
        "rem_CNPJ": _t(inf, "c:rem/c:CNPJ"), "rem_CPF": _t(inf, "c:rem/c:CPF"),
        "rem_xNome": _t(inf, "c:rem/c:xNome"),
        "dest_CNPJ": _t(inf, "c:dest/c:CNPJ"), "dest_CPF": _t(inf, "c:dest/c:CPF"),
        "dest_xNome": _t(inf, "c:dest/c:xNome"),
        "vTPrest": _t(inf, "c:vPrest/c:vTPrest"), "vRec": _t(inf, "c:vPrest/c:vRec"),
        "vCarga": _t(norm, "c:infCarga/c:vCarga"), "proPred": _t(norm, "c:infCarga/c:proPred"),
        "rntrc": _t(norm, "c:infModal/c:rodo/c:RNTRC"),
        "prot_chCTe": _t(prot, "c:chCTe"), "prot_cStat": _t(prot, "c:cStat"),
        "prot_xMotivo": _t(prot, "c:xMotivo"), "prot_nProt": _t(prot, "c:nProt"),
        "prot_dhRecbto": _t(prot, "c:dhRecbto"),
    }
    lido = CteLido(cte=[linha])
    if norm is not None:
        for i, nfe in enumerate(norm.findall("c:infDoc/c:infNFe", _N), 1):
            lido.cte_nfe.append({"chCTe": ch, "_ordem": i, "chave": _t(nfe, "c:chave")})
        for i, q in enumerate(norm.findall("c:infCarga/c:infQ", _N), 1):
            lido.cte_carga.append({"chCTe": ch, "_ordem": i, "cUnid": _t(q, "c:cUnid"),
                                   "tpMed": _t(q, "c:tpMed"), "qCarga": _t(q, "c:qCarga")})
    return lido


def _proc_evento(raiz) -> CteLido:
    inf = raiz.find("c:eventoCTe/c:infEvento", _N)
    if inf is None:
        return CteLido(rejeitado="estrutura_inesperada: procEventoCTe sem eventoCTe/infEvento")
    det = inf.find("c:detEvento", _N)
    # O conteúdo de detEvento depende do tipo de evento; no cancelamento é evCancCTe.
    corpo = det[0] if det is not None and len(det) else None
    ret = raiz.find("c:retEventoCTe/c:infEvento", _N)
    linha = {
        "infEvento_Id": inf.get("Id"),
        **{k: _t(inf, f"c:{k}") for k in ("chCTe", "cOrgao", "tpAmb", "CNPJ", "tpEvento", "nSeqEvento",
                                          "dhEvento")},
        "descEvento": _t(corpo, "c:descEvento"), "nProt_cte": _t(corpo, "c:nProt"),
        "xJust": _t(corpo, "c:xJust"),
        "ret_chCTe": _t(ret, "c:chCTe"), "ret_cStat": _t(ret, "c:cStat"), "ret_xMotivo": _t(ret, "c:xMotivo"),
        "ret_tpEvento": _t(ret, "c:tpEvento"), "ret_nProt": _t(ret, "c:nProt"),
        "ret_dhRegEvento": _t(ret, "c:dhRegEvento"),
    }
    return CteLido(cte_evento=[linha])


def ler_xml(dados: bytes) -> CteLido:
    try:
        raiz = etree.fromstring(dados, parser=_PARSER)
    except etree.XMLSyntaxError as e:
        return CteLido(rejeitado=f"xml_malformado: {e}")
    tag = etree.QName(raiz)
    if tag.namespace == NS and tag.localname == "cteProc":
        return _cte_proc(raiz)
    if tag.namespace == NS and tag.localname == "procEventoCTe":
        return _proc_evento(raiz)
    return CteLido(rejeitado=f"raiz_desconhecida: {raiz.tag}")


def sha256(dados: bytes) -> str:
    return hashlib.sha256(dados).hexdigest()
