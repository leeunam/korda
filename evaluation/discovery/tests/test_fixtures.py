"""Valida materiais e aceite offline; não demonstra um organizador já implementado."""

import copy
import importlib.util
import json
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("discovery_acceptance", ROOT / "evaluation/discovery/check_context.py")
acceptance = importlib.util.module_from_spec(spec)
spec.loader.exec_module(acceptance)
fixtures = acceptance.load_module("discovery_fixtures", ROOT / "data/synthetic/discovery/validate.py")
CASE = fixtures.CASE
EXPECTED = ROOT / "evaluation/discovery/01_demo"
SCENARIOS = fixtures.read_json(EXPECTED / "cenarios.json")


def contexts():
    return [fixtures.read_json(EXPECTED / name) for name in ("01_rateio_pendente.json", "02_rateio_confirmado.json")]


def turns():
    return {t.id: t for t in fixtures.load_fixture()[2].turns}


def checkpoint(scenario, index=-1):
    return next(s for s in SCENARIOS["scenarios"] if s["id"] == scenario)["checkpoints"][index]


def test_rodadas_tem_evidencia_literal_e_preservam_revisao():
    first, final = contexts()
    acceptance.check_context(first, checkpoint("duas_rodadas", 0), turns())
    acceptance.check_context(final, checkpoint("duas_rodadas"), turns(), first)
    for ctx in (first, final):
        sources = {s["id"]: s for s in ctx["sources"]}
        for item in ctx["evidence"]:
            source = sources[item["source_id"]]
            if source["kind"] == "pesquisa":
                page = (ROOT / source["locator"]).read_text(encoding="utf-8")
                assert item["excerpt"] in page
                assert item["locator"] in page


def test_formulario_e_catalogo_preservam_origem_e_escopo():
    form, sources, script = fixtures.load_fixture()
    assert form.synthetic and script.synthetic
    assert {(s.origin, s.scope) for s in sources} == {
        ("fornecida", "empresa"), ("descoberta", "empresa"), ("descoberta", "setor")}
    assert {p.role for p in form.participants} == {"operacao", "financeiro", "dados"}


@pytest.mark.parametrize("path", ["../personas/roteiro.json", "../../../../evaluation/golden/01_demo/kpis.json", "C:/segredo.md", "pesquisa/../../empresas/01_demo/empresa.yaml", "pesquisa\\empresa.md"])
def test_catalogo_nao_pode_apontar_para_personas_ou_gabaritos(path):
    source = fixtures.read_json(CASE / "inputs/fontes.json")[0]
    with pytest.raises(ValidationError):
        fixtures.ResearchSource.model_validate({**source, "path": path})


@pytest.mark.parametrize("change", [{"synthetic": False}, {"company_id": "03_reservada"}, {"site_url": "https://empresa-real.com"}, {"respostas_esperadas": {}}])
def test_formulario_rejeita_dados_fora_do_recorte(change):
    form = fixtures.read_json(CASE / "inputs/formulario.json")
    with pytest.raises(ValidationError):
        fixtures.Form.model_validate({**form, **change})


def test_ids_e_fontes_invalidos_falham_antes_de_rodar_ensaio(tmp_path):
    from shutil import copytree

    case = tmp_path / "case"
    copytree(CASE, case)
    path = case / "personas/roteiro.json"
    script = fixtures.read_json(path)
    script["turns"].append(script["turns"][0])
    path.write_text(json.dumps(script), encoding="utf-8")
    with pytest.raises(ValueError, match="IDs repetidos"):
        fixtures.load_fixture(case)
    path.write_text((CASE / "personas/roteiro.json").read_text(encoding="utf-8"), encoding="utf-8")
    (case / "inputs/pesquisa/empresa.md").unlink()
    with pytest.raises(ValueError, match="página ausente"):
        fixtures.load_fixture(case)


def add_turn(context, tid):
    source_id = "entrevista-rodada-1"
    if tid.startswith("financeiro"):
        source_id = "entrevista-rodada-2"
    context["evidence"].append({"id": "ev-" + tid, "source_id": source_id, "locator": tid, "excerpt": turns()[tid].answer})
    context["last_processed_turn_id"] = tid
    context["revision"] += 1


def test_resposta_vaga_nao_confirma_rateio_por_peso():
    first, final = contexts()
    add_turn(first, "operacao-ambigua")
    acceptance.check_context(first, checkpoint("resposta_ambigua"), turns())
    add_turn(final, "operacao-ambigua")
    with pytest.raises(ValueError, match="estado do contexto"):
        acceptance.check_context(final, checkpoint("resposta_ambigua"), turns())


def test_conflito_bloqueia_custo_e_correcao_preserva_ambas_as_falas():
    _, conflict = contexts()
    add_turn(conflict, "operacao-conflito")
    conflict["state"] = "rascunho"
    conflict["rules"]["rateio_cte"].update(status="em_conflito", value=None, confirmed_by=None)
    conflict["rules"]["rateio_cte"]["evidence_ids"].append("ev-operacao-conflito")
    conflict["gaps"][0].update(state="em_conflito")
    conflict["gaps"][0]["evidence_ids"].append("ev-operacao-conflito")
    acceptance.check_context(conflict, checkpoint("contradicao"), turns())
    corrected = copy.deepcopy(conflict)
    add_turn(corrected, "financeiro-correcao")
    corrected["state"] = "pronto_para_planejamento"
    corrected["rules"]["rateio_cte"].update(status="confirmada", value="peso", confirmed_by={"name": "Pessoa fictícia do financeiro", "role": "financeiro"})
    corrected["rules"]["rateio_cte"]["evidence_ids"].append("ev-financeiro-correcao")
    corrected["gaps"][0].update(state="respondida")
    corrected["gaps"][0]["evidence_ids"].append("ev-financeiro-correcao")
    acceptance.check_context(corrected, checkpoint("correcao_com_historico"), turns(), conflict)
    without_confirmation = copy.deepcopy(corrected)
    without_confirmation["rules"]["rateio_cte"]["evidence_ids"].remove("ev-financeiro-correcao")
    with pytest.raises(ValueError, match="confirmação financeira"):
        acceptance.check_context(without_confirmation, checkpoint("correcao_com_historico"), turns(), conflict)
    corrected["evidence"] = [e for e in corrected["evidence"] if e["locator"] != "operacao-conflito"]
    with pytest.raises(ValueError):
        acceptance.check_context(corrected, checkpoint("correcao_com_historico"), turns(), conflict)


def test_citacao_inventada_e_reescrita_de_historico_falham():
    first, final = contexts()
    final["evidence"][0]["excerpt"] = "Fala que não está no roteiro."
    with pytest.raises(ValueError, match="citação"):
        acceptance.check_context(final, checkpoint("duas_rodadas"), turns(), first)
    first, final = contexts()
    final["evidence"][0]["excerpt"] = final["evidence"][0]["excerpt"][:20]
    with pytest.raises(ValueError, match="histórico"):
        acceptance.check_context(final, checkpoint("duas_rodadas"), turns(), first)


def test_confirmacao_setorial_nao_substitui_financeiro():
    _, final = contexts()
    final["rules"]["rateio_cte"]["evidence_ids"] = ["ev-setor"]
    with pytest.raises(ValueError, match="referência setorial"):
        acceptance.check_context(final, checkpoint("duas_rodadas"), turns())


def test_identidade_da_lacuna_e_outras_regras_nao_mudam_na_retomada():
    first, final = contexts()
    final["gaps"][0]["id"] = "outra-lacuna"
    with pytest.raises(ValueError, match="identidade das lacunas"):
        acceptance.check_context(final, checkpoint("duas_rodadas"), turns(), first)
    first, final = contexts()
    final["rules"]["ocupacao_unidade"]["value"] = "m3"
    with pytest.raises(ValueError, match="outras regras"):
        acceptance.check_context(final, checkpoint("duas_rodadas"), turns(), first)


def test_cenarios_referenciam_falas_existentes_e_cobrem_reenvio():
    catalog = turns()
    assert {s["id"] for s in SCENARIOS["scenarios"]} == {
        "duas_rodadas", "resposta_ambigua", "contradicao", "correcao_com_historico", "retomada_e_reenvio"}
    for scenario in SCENARIOS["scenarios"]:
        ids = SCENARIOS["baseline_round_1"] + [e["turn_id"] for e in scenario["events"]]
        assert set(ids) <= catalog.keys()
        assert len({e["delivery_id"] for e in scenario["events"]}) == len(scenario["events"])
        for expected in scenario["checkpoints"]:
            assert set(expected["required_turn_ids"]) <= set(ids)
            assert expected["after_turn_id"] in ids
            if expected["context_file"]:
                assert (EXPECTED / expected["context_file"]).is_file()
        if scenario["id"] == "retomada_e_reenvio":
            assert len(set(ids)) == scenario["expected_unique_turns"] == 8
            assert len(ids) == 9
    assert catalog["operacao-rateio"].answer == catalog["operacao-rateio-repetido"].answer
    assert catalog["operacao-rateio"].id != catalog["operacao-rateio-repetido"].id


def test_inputs_iniciais_nao_incluem_roteiro_ou_resultados_esperados():
    files = {p.relative_to(CASE / "inputs").as_posix() for p in (CASE / "inputs").rglob("*") if p.is_file()}
    assert files == {"formulario.json", "fontes.json", "pesquisa/empresa.md", "pesquisa/operacao.md", "pesquisa/setor.md"}
