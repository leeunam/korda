"""Leitura de CT-e 4.00. Os XML são montados à mão aqui (sem importar o gerador) e são fictícios."""

import unittest

from korda_ingestao.cte import ler_xml

NS = "http://www.portalfiscal.inf.br/cte"
CH_A = "35260911222333000192570010000000011000000001"
CH_B = "35260911222333000192570010000000021000000002"


def cte_proc(chave=CH_A, nfes=("NFE1",), infq=(("01", "PESO BRUTO", "100.0000"),), vtprest="300.00",
             cstat="100"):
    docs = "".join(f"<infNFe><chave>{n}</chave></infNFe>" for n in nfes)
    qs = "".join(f"<infQ><cUnid>{u}</cUnid><tpMed>{t}</tpMed><qCarga>{q}</qCarga></infQ>" for u, t, q in infq)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<cteProc xmlns="{NS}" versao="4.00"><CTe><infCte versao="4.00" Id="CTe{chave}">
<ide><cUF>35</cUF><nCT>1</nCT><serie>1</serie><dhEmi>2026-09-01T05:30:00-03:00</dhEmi><tpAmb>2</tpAmb>
<cMunIni>3509502</cMunIni><cMunFim>3509502</cMunFim></ide>
<emit><CNPJ>11222333000192</CNPJ><xNome>Transportadora (ficticia)</xNome></emit>
<rem><CNPJ>94463569000148</CNPJ><xNome>Rem (ficticio)</xNome></rem>
<dest><CPF>00000000000</CPF><xNome></xNome></dest>
<vPrest><vTPrest>{vtprest}</vTPrest><vRec>{vtprest}</vRec></vPrest>
<infCTeNorm><infCarga><vCarga>1000.00</vCarga>{qs}</infCarga><infDoc>{docs}</infDoc></infCTeNorm>
</infCte></CTe>
<protCTe versao="4.00"><infProt><chCTe>{chave}</chCTe><cStat>{cstat}</cStat><nProt>135</nProt></infProt></protCTe>
</cteProc>""".encode()


def proc_evento(chave=CH_A):
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<procEventoCTe xmlns="{NS}" versao="4.00"><eventoCTe versao="4.00">
<infEvento Id="ID110111{chave}001"><cOrgao>35</cOrgao><tpAmb>2</tpAmb><CNPJ>11222333000192</CNPJ>
<chCTe>{chave}</chCTe><dhEvento>2026-09-01T06:40:00-03:00</dhEvento><tpEvento>110111</tpEvento>
<nSeqEvento>1</nSeqEvento><detEvento versaoEvento="4.00"><evCancCTe><descEvento>Cancelamento</descEvento>
<nProt>135260000000011</nProt><xJust>Destinatario com endereco divergente</xJust></evCancCTe></detEvento>
</infEvento></eventoCTe>
<retEventoCTe versao="4.00"><infEvento><cStat>135</cStat><chCTe>{chave}</chCTe><tpEvento>110111</tpEvento>
<nProt>135260000900011</nProt><dhRegEvento>2026-09-01T06:40:00-03:00</dhRegEvento></infEvento></retEventoCTe>
</procEventoCTe>""".encode()


class TestCteProc(unittest.TestCase):
    def test_campos_principais_como_texto(self):
        lido = ler_xml(cte_proc())
        self.assertIsNone(lido.rejeitado)
        linha = lido.cte[0]
        self.assertEqual(linha["chCTe"], CH_A)
        self.assertEqual(linha["infCte_Id"], "CTe" + CH_A)
        self.assertEqual(linha["vTPrest"], "300.00")
        self.assertEqual(linha["prot_cStat"], "100")
        self.assertEqual(linha["tpAmb"], "2")

    def test_tag_ausente_e_none_e_tag_vazia_e_texto_vazio(self):
        linha = ler_xml(cte_proc()).cte[0]
        self.assertIsNone(linha["dest_CNPJ"])
        self.assertEqual(linha["dest_CPF"], "00000000000")
        self.assertEqual(linha["dest_xNome"], "")
        self.assertIsNone(linha["natOp"])

    def test_varias_nfe_geram_varias_linhas_em_ordem(self):
        lido = ler_xml(cte_proc(nfes=("N1", "N2", "N3")))
        self.assertEqual([(r["chCTe"], r["_ordem"], r["chave"]) for r in lido.cte_nfe],
                         [(CH_A, 1, "N1"), (CH_A, 2, "N2"), (CH_A, 3, "N3")])

    def test_infq_peso_e_volume(self):
        lido = ler_xml(cte_proc(infq=(("01", "PESO BRUTO", "363.9000"), ("00", "M3", "2.1880"))))
        self.assertEqual([(r["cUnid"], r["qCarga"]) for r in lido.cte_carga],
                         [("01", "363.9000"), ("00", "2.1880")])


class TestEvento(unittest.TestCase):
    def test_cancelamento_vai_para_cte_evento(self):
        lido = ler_xml(proc_evento())
        self.assertEqual(lido.cte, [])
        ev = lido.cte_evento[0]
        self.assertEqual((ev["chCTe"], ev["tpEvento"], ev["ret_cStat"]), (CH_A, "110111", "135"))
        self.assertEqual(ev["xJust"], "Destinatario com endereco divergente")
        self.assertEqual(ev["nProt_cte"], "135260000000011")


class TestRejeicao(unittest.TestCase):
    def test_xml_truncado(self):
        lido = ler_xml(cte_proc()[:200])
        self.assertTrue(lido.rejeitado.startswith("xml_malformado"))

    def test_raiz_desconhecida(self):
        lido = ler_xml(b"<nfeProc xmlns='http://www.portalfiscal.inf.br/nfe'/>")
        self.assertTrue(lido.rejeitado.startswith("raiz_desconhecida"))

    def test_cte_proc_sem_infcte(self):
        lido = ler_xml(f"<cteProc xmlns='{NS}'/>".encode())
        self.assertTrue(lido.rejeitado.startswith("estrutura_inesperada"))

    def test_entidade_externa_nao_e_resolvida(self):
        corpo = cte_proc().split(b"?>", 1)[1].replace(b"<nCT>1</nCT>", b"<nCT>&e;</nCT>")
        xml = b'<?xml version="1.0"?><!DOCTYPE cteProc [<!ENTITY e SYSTEM "file:///etc/passwd">]>' + corpo
        lido = ler_xml(xml)
        self.assertIsNone(lido.rejeitado)
        self.assertEqual(lido.cte[0]["nCT"], "")  # referência mantida sem expandir: nada de /etc/passwd


if __name__ == "__main__":
    unittest.main()
