"""Montagem de XML de CT-e 4.00 (cteProc) e de evento de cancelamento (procEventoCTe).

Todos os documentos são FICTÍCIOS:
- tpAmb=2 (homologação), CNPJs com DV inválido e nomes inventados;
- a assinatura (ds:Signature) é estruturalmente válida para o XSD, mas não tem
  valor criptográfico: DigestValue/SignatureValue/X509Certificate são bytes
  derivados da chave, não de um certificado.
"""

from __future__ import annotations

import base64
import hashlib
from decimal import Decimal

from lxml import etree

NS = "http://www.portalfiscal.inf.br/cte"
DS = "http://www.w3.org/2000/09/xmldsig#"
VERSAO = "4.00"


def _e(parent, tag, text=None, ns=NS, **attrs):
    el = etree.SubElement(parent, f"{{{ns}}}{tag}", **attrs)
    if text is not None:
        el.text = str(text)
    return el


def dv_mod11(digits: str) -> int:
    """Dígito verificador módulo 11 (pesos 2..9 da direita para a esquerda), como na chave de acesso."""
    total, weight = 0, 2
    for ch in reversed(digits):
        total += int(ch) * weight
        weight = 2 if weight == 9 else weight + 1
    rest = total % 11
    return 0 if rest in (0, 1) else 11 - rest


def chave_acesso(cuf: str, aamm: str, cnpj: str, mod: str, serie: int, numero: int, tp_emis: int, codigo: int) -> str:
    base = f"{cuf}{aamm}{cnpj}{mod}{serie:03d}{numero:09d}{tp_emis}{codigo:08d}"
    assert len(base) == 43, base
    return base + str(dv_mod11(base))


def _fake_b64(seed: str, size: int) -> str:
    raw = b""
    counter = 0
    while len(raw) < size:
        raw += hashlib.sha256(f"{seed}:{counter}".encode()).digest()
        counter += 1
    return base64.b64encode(raw[:size]).decode()


def _signature(parent, ref_id: str) -> None:
    sig = _e(parent, "Signature", ns=DS)
    info = _e(sig, "SignedInfo", ns=DS)
    _e(info, "CanonicalizationMethod", ns=DS, Algorithm="http://www.w3.org/TR/2001/REC-xml-c14n-20010315")
    _e(info, "SignatureMethod", ns=DS, Algorithm="http://www.w3.org/2000/09/xmldsig#rsa-sha1")
    ref = _e(info, "Reference", ns=DS, URI=f"#{ref_id}")
    transforms = _e(ref, "Transforms", ns=DS)
    _e(transforms, "Transform", ns=DS, Algorithm="http://www.w3.org/2000/09/xmldsig#enveloped-signature")
    _e(transforms, "Transform", ns=DS, Algorithm="http://www.w3.org/TR/2001/REC-xml-c14n-20010315")
    _e(ref, "DigestMethod", ns=DS, Algorithm="http://www.w3.org/2000/09/xmldsig#sha1")
    _e(ref, "DigestValue", _fake_b64("digest" + ref_id, 20), ns=DS)
    _e(sig, "SignatureValue", _fake_b64("sig" + ref_id, 256), ns=DS)
    key = _e(sig, "KeyInfo", ns=DS)
    x509 = _e(key, "X509Data", ns=DS)
    _e(x509, "X509Certificate", _fake_b64("cert-ficticio", 600), ns=DS)


def _money(value: Decimal) -> str:
    return f"{value:.2f}"


def _endereco(parent, tag: str, pessoa: dict) -> None:
    end = _e(parent, tag)
    _e(end, "xLgr", pessoa["logradouro"])
    _e(end, "nro", pessoa["numero"])
    _e(end, "xBairro", pessoa["bairro"])
    _e(end, "cMun", pessoa["cod_mun"])
    _e(end, "xMun", pessoa["municipio"])
    _e(end, "CEP", pessoa["cep"])
    _e(end, "UF", pessoa["uf"])


def cte_proc(cte: dict, emit: dict, rem: dict, dest: dict, sede: dict) -> bytes:
    """cteProc com um CT-e normal rodoviário autorizado (cStat 100)."""
    proc = etree.Element(f"{{{NS}}}cteProc", nsmap={None: NS}, versao=VERSAO)
    root = _e(proc, "CTe")
    inf = _e(root, "infCte", versao=VERSAO, Id=f"CTe{cte['chave']}")

    ide = _e(inf, "ide")
    _e(ide, "cUF", cte["chave"][:2])
    _e(ide, "cCT", cte["chave"][35:43])
    interestadual = sede["uf"] != dest["uf"]
    _e(ide, "CFOP", "6353" if interestadual else "5353")
    _e(ide, "natOp", "PRESTACAO DE SERVICO DE TRANSPORTE")
    _e(ide, "mod", "57")
    _e(ide, "serie", cte["serie"])
    _e(ide, "nCT", cte["numero"])
    _e(ide, "dhEmi", cte["dh_emissao"])
    _e(ide, "tpImp", "1")
    _e(ide, "tpEmis", "1")
    _e(ide, "cDV", cte["chave"][-1])
    _e(ide, "tpAmb", "2")
    _e(ide, "tpCTe", "0")
    _e(ide, "procEmi", "0")
    _e(ide, "verProc", "korda-sintetico-0.2")
    _e(ide, "cMunEnv", sede["cod_mun"])
    _e(ide, "xMunEnv", sede["municipio"])
    _e(ide, "UFEnv", sede["uf"])
    _e(ide, "modal", "01")
    _e(ide, "tpServ", "0")
    _e(ide, "cMunIni", sede["cod_mun"])
    _e(ide, "xMunIni", sede["municipio"])
    _e(ide, "UFIni", sede["uf"])
    _e(ide, "cMunFim", dest["cod_mun"])
    _e(ide, "xMunFim", dest["municipio"])
    _e(ide, "UFFim", dest["uf"])
    _e(ide, "retira", "1")
    _e(ide, "indIEToma", "1")
    toma = _e(ide, "toma3")
    _e(toma, "toma", "0")

    em = _e(inf, "emit")
    _e(em, "CNPJ", emit["cnpj"])
    _e(em, "IE", emit["ie"])
    _e(em, "xNome", "CTE EMITIDO EM AMBIENTE DE HOMOLOGACAO - SEM VALOR FISCAL")
    _endereco(em, "enderEmit", emit)
    _e(em, "CRT", "3")

    for tag, pessoa, ender in (("rem", rem, "enderReme"), ("dest", dest, "enderDest")):
        p = _e(inf, tag)
        _e(p, "CNPJ", pessoa["cnpj"])
        _e(p, "IE", pessoa["ie"])
        _e(p, "xNome", pessoa["nome"])
        _endereco(p, ender, pessoa)

    vprest = _e(inf, "vPrest")
    _e(vprest, "vTPrest", _money(cte["vTPrest"]))
    _e(vprest, "vRec", _money(cte["vTPrest"]))

    imp = _e(inf, "imp")
    icms = _e(imp, "ICMS")
    icms00 = _e(icms, "ICMS00")
    _e(icms00, "CST", "00")
    _e(icms00, "vBC", _money(cte["vTPrest"]))
    _e(icms00, "pICMS", "12.00")
    _e(icms00, "vICMS", _money((cte["vTPrest"] * Decimal("0.12")).quantize(Decimal("0.01"))))

    norm = _e(inf, "infCTeNorm")
    carga = _e(norm, "infCarga")
    _e(carga, "vCarga", _money(cte["valor_carga"]))
    _e(carga, "proPred", "MERCADORIAS DIVERSAS")
    q = _e(carga, "infQ")
    _e(q, "cUnid", "01")
    _e(q, "tpMed", "PESO BRUTO")
    _e(q, "qCarga", f"{cte['peso_kg']:.4f}")
    q = _e(carga, "infQ")
    _e(q, "cUnid", "00")
    _e(q, "tpMed", "M3")
    _e(q, "qCarga", f"{cte['volume_m3']:.4f}")
    doc = _e(norm, "infDoc")
    for chave_nfe in cte["chaves_nfe"]:
        nfe = _e(doc, "infNFe")
        _e(nfe, "chave", chave_nfe)
    modal = _e(norm, "infModal", versaoModal=VERSAO)
    rodo = _e(modal, "rodo")
    _e(rodo, "RNTRC", emit["rntrc"])

    _e(root, "infCTeSupl").append(_qr(cte["chave"]))
    _signature(root, f"CTe{cte['chave']}")

    prot = _e(proc, "protCTe", versao=VERSAO)
    infprot = _e(prot, "infProt")
    _e(infprot, "tpAmb", "2")
    _e(infprot, "verAplic", "SVRS-SINTETICO")
    _e(infprot, "chCTe", cte["chave"])
    _e(infprot, "dhRecbto", cte["dh_emissao"])
    _e(infprot, "nProt", cte["protocolo"])
    _e(infprot, "digVal", _fake_b64("digest" + "CTe" + cte["chave"], 20))
    _e(infprot, "cStat", "100")
    _e(infprot, "xMotivo", "Autorizado o uso do CT-e")
    return etree.tostring(proc, xml_declaration=True, encoding="UTF-8", pretty_print=True)


def _qr(chave: str):
    el = etree.Element(f"{{{NS}}}qrCodCTe")
    el.text = f"https://dfe-portal.svrs.rs.gov.br/cte/qrCode?chCTe={chave}&tpAmb=2"
    return el


def proc_evento_cancelamento(chave: str, cnpj_emit: str, protocolo_cte: str, protocolo_evento: str,
                             dh_evento: str, justificativa: str) -> bytes:
    """procEventoCTe com cancelamento (110111) homologado (cStat 135)."""
    proc = etree.Element(f"{{{NS}}}procEventoCTe", nsmap={None: NS}, versao=VERSAO)
    evento = _e(proc, "eventoCTe", versao=VERSAO)
    ev_id = f"ID110111{chave}001"
    inf = _e(evento, "infEvento", Id=ev_id)
    _e(inf, "cOrgao", chave[:2])
    _e(inf, "tpAmb", "2")
    _e(inf, "CNPJ", cnpj_emit)
    _e(inf, "chCTe", chave)
    _e(inf, "dhEvento", dh_evento)
    _e(inf, "tpEvento", "110111")
    _e(inf, "nSeqEvento", "1")
    det = _e(inf, "detEvento", versaoEvento=VERSAO)
    canc = _e(det, "evCancCTe")
    _e(canc, "descEvento", "Cancelamento")
    _e(canc, "nProt", protocolo_cte)
    _e(canc, "xJust", justificativa)
    _signature(evento, ev_id)

    ret = _e(proc, "retEventoCTe", versao=VERSAO)
    rinf = _e(ret, "infEvento")
    _e(rinf, "tpAmb", "2")
    _e(rinf, "verAplic", "SVRS-SINTETICO")
    _e(rinf, "cOrgao", chave[:2])
    _e(rinf, "cStat", "135")
    _e(rinf, "xMotivo", "Evento registrado e vinculado a CT-e")
    _e(rinf, "chCTe", chave)
    _e(rinf, "tpEvento", "110111")
    _e(rinf, "xEvento", "Cancelamento")
    _e(rinf, "nSeqEvento", "1")
    _e(rinf, "dhRegEvento", dh_evento)
    _e(rinf, "nProt", protocolo_evento)
    return etree.tostring(proc, xml_declaration=True, encoding="UTF-8", pretty_print=True)
