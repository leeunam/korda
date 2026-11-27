"""Fronteira entre o contrato da entrevista e o plano logístico."""
import copy
import json
import sys
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(RAIZ / "services/planning"))
from korda_planning import ContextoPendente, gerar_plano, preparar_contexto, validar_plano


def exemplo(versao, nome):
    return json.loads((RAIZ / f"packages/contracts/context/v{versao}/examples/{nome}.json").read_text())


def entrevista_completa():
    """Participantes e respostas explícitos são sintéticos, como os fixtures de origem."""
    doc = exemplo("0.2.0", "03_confirmed")
    legado = exemplo("0.1.0", "02_rateio_confirmado")
    topicos = {"deduplicar_cte": "frete_deduplicacao", "excluir_cancelados": "frete_cancelamento",
               "excluir_tipos_viagem": "frete_elegibilidade", "no_prazo": "otif_prazo", "completo": "otif_completude",
               "sem_data_realizada": "otif_data_ausente", "prazo_conta_sabado": "otif_sabado", "ocupacao_unidade": "ocupacao_unidade"}
    doc["required_topics"].update(dict.fromkeys(topicos.values(), "operacao"), fontes="dados")
    valores = {k: v["value"] for k, v in legado["rules"].items() if k != "rateio_cte"}
    perfil = {k: v for k, v in legado["source_profile"].items() if k != "evidence_ids"}
    modelo = copy.deepcopy(doc["claims"][0])
    for chave, valor in {**valores, **perfil}.items():
        papel, topico = ("dados", "fontes") if chave in perfil else ("operacao", topicos[chave])
        citacao = chave + " = " + json.dumps(valor, ensure_ascii=False)
        referencias = []
        for sufixo, texto in [("declaracao", citacao), ("confirmacao", "Confirmo.")]:
            entrada = chave + "-" + sufixo
            id_evidencia = "ev-" + entrada
            doc["processed_input_ids"].append(entrada)
            doc["evidence"].append({
                **doc["evidence"][0], "id": id_evidencia, "input_id": entrada, "source_id": entrada,
                "participant_id": "participante-" + papel, "participant_role": papel,
                "quote": texto, "start_offset": 7, "end_offset": 7 + len(texto),
            })
            referencias.append(id_evidencia)
        doc["claims"].append({
            **modelo, "id": "claim-" + chave, "topic": topico, "key": chave, "value": valor, "statement": citacao,
            "kind": "source" if chave in perfil else "rule",
            "source_verification": "nao_inspecionada" if chave in perfil else None,
            "confirmation": {"evidence_id": referencias[-1], "participant_id": "participante-" + papel, "role": papel},
            "evidence_ids": referencias,
        })
    return doc


class Ponte(unittest.TestCase):
    def test_quatro_revisoes_publicadas_e_papel(self):
        inicial = preparar_contexto(exemplo("0.2.0", "01_initial"))
        self.assertEqual(inicial["revision"], 0)
        self.assertIsNone(inicial["contexto_planejamento"])
        bloqueado = preparar_contexto(exemplo("0.2.0", "02_blocked"))
        self.assertEqual(bloqueado["regras"]["rateio_cte"]["status"], "a_confirmar")
        doc = exemplo("0.2.0", "03_confirmed")
        parcial = preparar_contexto(doc)
        self.assertEqual((parcial["estado"], parcial["regras"]["rateio_cte"]["value"]), ("pendente", "peso"))
        self.assertEqual(parcial["regras"]["rateio_cte"]["confirmed_by"],
                         {"name": "financeiro-sintetico", "role": "financeiro"})
        self.assertEqual(set(parcial["regras"]["rateio_cte"]["evidence_ids"]), {e["id"] for e in doc["evidence"]})
        self.assertTrue({"completo", "freight_link", "timezone"} <= {p["campo"] for p in parcial["pendencias"]})
        self.assertEqual(parcial["lacunas"], doc["gaps"])
        with self.assertRaises(ContextoPendente) as erro:
            gerar_plano(doc, dataset="01_demo")
        self.assertEqual(erro.exception.diagnostico, parcial)
        conflito = preparar_contexto(exemplo("0.2.0", "04_conflict"))
        self.assertEqual(conflito["regras"]["rateio_cte"]["status"], "em_conflito")
        self.assertIsNone(conflito["regras"]["rateio_cte"]["value"])

    def test_plano_preserva_revisao_turnos_papeis_e_identidade_da_transcricao(self):
        doc = entrevista_completa()
        ev = doc["evidence"][0]
        ev.update(kind="audio_transcript", transcription_version=2, source_id="audio-sintetico")
        copia = copy.deepcopy(doc)
        dig = preparar_contexto(doc)
        self.assertEqual(dig["estado"], "pronto")
        proj = dig["contexto_planejamento"]
        self.assertEqual(proj["context_id"], "whatsapp:" + doc["project_id"])
        self.assertEqual(proj["last_processed_turn_id"], doc["processed_input_ids"][-1])
        self.assertEqual(proj["revision"], doc["revision"])
        evid = next(e for e in proj["evidence"] if e["id"] == ev["id"])
        self.assertEqual(evid["excerpt"], ev["quote"])
        fonte = next(f for f in proj["sources"] if f["id"] == evid["source_id"])
        self.assertEqual(json.loads(fonte["locator"])["transcription_version"], 2)
        self.assertIn(dig["contexto_sha256"], fonte["version"])
        self.assertIsNone(gerar_plano(doc)["dataset"])
        plano = gerar_plano(doc, dataset="01_demo")
        self.assertEqual(plano, gerar_plano(proj, dataset="01_demo"))
        validar_plano(plano)
        self.assertEqual(doc, copia)
        # O plano continua contendo o SHA de todo o contexto original, inclusive
        # os qualificadores que não são campos nativos do plano legado.
        doc["evidence"][0]["transcription_version"] += 1
        self.assertNotEqual(plano["plan_version"], gerar_plano(doc, dataset="01_demo")["plan_version"])

    def test_alias_concorrente_e_limite_temporal_nao_vazam_ao_lote_integral(self):
        doc = entrevista_completa()
        outro = copy.deepcopy(doc["claims"][0])
        outro.update(id="outra-politica", key="rateio_cte", value="volume")
        doc["claims"].append(outro)
        dig = preparar_contexto(doc)
        self.assertEqual(dig["regras"]["rateio_cte"]["status"], "em_conflito")
        self.assertIsNone(dig["contexto_planejamento"])
        doc["claims"].pop()
        doc["claims"][0]["time_scope"] = "somente janeiro"
        dig = preparar_contexto(doc)
        self.assertIn("período", next(p["pergunta"] for p in dig["pendencias"] if p["campo"] == "rateio_cte"))

    def test_autoridade_declaracao_anterior_e_qualificador_desconhecido(self):
        doc = entrevista_completa()
        doc["claims"][0]["confirmation"]["role"] = "operacao"
        with self.assertRaises(ValueError):
            preparar_contexto(doc)
        doc = entrevista_completa()
        doc["claims"][0]["evidence_ids"] = [doc["claims"][0]["confirmation"]["evidence_id"]]
        self.assertIsNone(preparar_contexto(doc)["regras"]["rateio_cte"]["value"])
        doc = entrevista_completa()
        extra = copy.deepcopy(doc["claims"][0])
        extra.update(id="claim-adicional", key="tratamento_da_filial", value="excluir")
        doc["claims"].append(extra)
        dig = preparar_contexto(doc)
        self.assertTrue(any(p["campo"] == extra["key"] and extra["id"] in p["claim_ids"] for p in dig["pendencias"]))

    def test_chave_canonica_em_topico_alheio_nao_da_autoridade(self):
        doc = entrevista_completa()
        frete = doc["claims"][0]
        doc["gaps"] = []
        doc["required_topics"].pop("frete")
        doc["required_topics"]["objetivo"] = "operacao"
        frete.update(key="rateio_cte", topic="objetivo")
        frete["confirmation"]["role"] = "operacao"
        doc["evidence"][1]["participant_role"] = "operacao"
        dig = preparar_contexto(doc)
        self.assertIsNone(dig["regras"]["rateio_cte"]["value"])
        self.assertIn("frete_rateio", next(p["pergunta"] for p in dig["pendencias"] if p["campo"] == "rateio_cte"))
        # Mesmo no tópico correto, o papel operacional não confirma o rateio.
        frete["topic"] = "frete_rateio"
        doc["required_topics"] = {("frete_rateio" if k == "objetivo" else k): v for k, v in doc["required_topics"].items()}
        self.assertIsNone(preparar_contexto(doc)["regras"]["rateio_cte"]["confirmed_by"])

    def test_grupo_de_perfil_parcial_conserva_confirmacoes_individuais(self):
        doc = entrevista_completa()
        perfil = [c for c in doc["claims"] if c["topic"] == "fontes"]
        doc["claims"] = [c for c in doc["claims"] if c["topic"] != "fontes"]
        primeiro = perfil[0]
        primeiro.update(key="source_profile", value={"grain": "uma_entrega_por_pedido"}, kind="constraint")
        doc["claims"].append(primeiro)
        dig = preparar_contexto(doc)
        self.assertIsNone(dig["contexto_planejamento"])
        self.assertEqual(dig["vinculos"]["grain"]["confirmation"], primeiro["confirmation"])
        self.assertTrue({"timezone", "quantity_unit", "freight_link"} <= {p["campo"] for p in dig["pendencias"]})
        primeiro["value"]["regra_da_filial"] = 123
        self.assertIn("source_profile", {p["campo"] for p in preparar_contexto(doc)["pendencias"]})

    def test_lacuna_bloqueante_geral_e_inputs_pendentes(self):
        doc = entrevista_completa()
        doc["state"] = "rascunho"
        doc["pending_input_ids"] = ["nova-mensagem"]
        doc["gaps"].append({"id": "questao-externa", "topic": "filial", "key": "cobertura",
                            "question": "Quais filiais entraram no lote?", "blocking": True})
        dig = preparar_contexto(doc)
        self.assertIsNone(dig["contexto_planejamento"])
        self.assertTrue({"questao-externa", "revisao"} <= {p["campo"] for p in dig["pendencias"]})

    def test_legado_continua_com_rascunho_revisavel(self):
        doc = exemplo("0.1.0", "01_rateio_pendente")
        self.assertEqual(preparar_contexto(doc)["contexto_planejamento"], doc)
        self.assertEqual(gerar_plano(doc)["state"], "rascunho")
