"""Construção do documento já aprovado, com verificação de dbt e exportação."""

from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path

from .correcao import executar_etapa
from .harness.cliente_chat import ClienteChatHttp, ClienteComOrcamento, cliente_offline
from .harness.config import ConfigHarness, ErroConfiguracao
from .harness.contexto import projetar_plano
from .harness.executor_chat import ExecutorChat
from .harness.medicao import Medidor
from .harness.orquestracao import construir_e_verificar
from .harness.roteirizado import ConstrutorRoteirizado, RestauradorRoteirizado
from .harness.tipos import usd_para_centavos
from .sandbox import RAIZ_REPO


PROJETO = RAIZ_REPO / "services/execution/pipeline/projeto"


class FalhaPreparo(ErroConfiguracao):
    """O executor escolhido não pode construir este plano."""


def preparar_construcao(plano, config=None, *, cliente_llm=None):
    """Falha antes de reservar o run, montar a sandbox ou fazer uma chamada de API."""
    config = config or ConfigHarness.de_ambiente()
    modelos = plano["editable_models"]
    historico = plano.get("schema_version") == "0.1.0" and modelos == ["models/*"]
    disponiveis = {p.relative_to(PROJETO).as_posix() for p in (PROJETO / "models").glob("*.sql")}
    if not historico and (not modelos or len(modelos) != len(set(modelos)) or set(modelos) != disponiveis):
        raise FalhaPreparo("o plano deve autorizar os modelos exatos deste pipeline; gere e aprove a nova versão")
    if config.executor == "chat" and (not config.permitir_llm_real or not config.chave_api):
        raise ErroConfiguracao("o executor chat exige autorização de LLM e credencial")
    if config.executor == "agente_sdk":
        raise FalhaPreparo("a construção usa a API da Feita: use KORDA_EXECUTOR=chat ou roteirizado")
    if config.executor == "falso" and not cliente_offline(cliente_llm):
        raise FalhaPreparo("KORDA_EXECUTOR=falso é só para testes: exige um cliente LLM falso")
    if config.executor in ("chat", "falso") and not (plano.get("construction") or {}).get("document", "").strip():
        raise FalhaPreparo("o plano aprovado não tem a construção: rode planejar e aprove a versão com ela")
    return config


def modelos_a_mao():
    """Modelos revisados no host, disponíveis exclusivamente no executor roteirizado."""
    return {p.relative_to(PROJETO).as_posix(): p.read_text(encoding="utf-8") for p in (PROJETO / "models").glob("*.sql")}


def classificar_falha_dbt(resultado):
    if resultado.get("estourou_tempo") or resultado.get("codigo", 1) not in (1, 2):
        return "tecnico"
    diagnostico = (resultado.get("stdout") or "") + "\n" + (resultado.get("stderr") or "")
    if re.search(r"(?:Failure in test|FAIL\s+\d+)\s+(?:integridade_fontes|documentos_conflitantes)\b", diagnostico):
        return "dados"
    return "implementacao"


def construir_modelos(config, plano, ferramentas, eventos, revisao, verificar_ativa, *, cliente_llm=None, exportar=None):
    """Constrói uma vez. Cada tentativa verifica os modelos e o contrato de exportação."""
    config = preparar_construcao(plano, config, cliente_llm=cliente_llm)
    publico = projetar_plano(plano)
    revisao = Path(revisao)
    medidor = Medidor(eventos.run_id, config.executor, config.modelo if config.usa_llm else None)
    versao = plano["plan_version"]
    limite = plano["limits"]["max_repair_attempts_per_step"]
    referencia_doc = plano.get("construction")
    texto = (referencia_doc["document"] if referencia_doc else
             "# Construção roteirizada\n\nA demo usou os modelos de referência do projeto.\n")
    info_doc = {"origem": "construction" if referencia_doc else "roteirizado",
                "synthetic": referencia_doc["synthetic"] if referencia_doc else True,
                "modelo": referencia_doc["model"] if referencia_doc else None,
                "sha256": hashlib.sha256(texto.encode()).hexdigest()}
    orcamento_centavos = usd_para_centavos(config.orcamento_execucao_usd, config.taxa_usd_brl)
    inicio = time.monotonic()
    resultado = None
    medido = None

    def registrar(tipo, dados):
        eventos.emit_event("modelos", tipo, str(dados.get("erro", tipo)), max(1, dados.get("tentativas", 1)),
                           **{k: v for k, v in dados.items() if k != "construcao"})

    def tentar():
        verificar_ativa()
        build = ferramentas.rodar_dbt("build")
        if not build["ok"]:
            diagnostico = ((build.get("stdout") or "") + "\n" + (build.get("stderr") or "")).strip()
            return {"ok": False, "codigo": classificar_falha_dbt(build), "erro": diagnostico[-4000:] or "dbt build falhou"}
        if exportar is not None:
            verificar_ativa()
            saida = exportar()
            if not saida.ok:
                return {"ok": False, "codigo": "implementacao" if saida.codigo == 1 and not saida.estourou_tempo else "tecnico",
                        "erro": "exportação (contrato de saída em exportar.py) falhou: " + saida.stderr[-1400:]}
        return {"ok": True}

    try:
        verificar_ativa()
        (revisao / "documento_base.md").write_bytes(texto.encode())
        eventos.emit_event("construcao", "document_ready", "Especificação usada nesta execução",
                           plan_version=versao, **info_doc)
        if config.executor == "roteirizado":
            referencia = modelos_a_mao()
            construtor = ConstrutorRoteirizado(ferramentas, referencia)
            corretor = RestauradorRoteirizado(ferramentas, referencia)
            eventos.emit_event("construcao", "build_started", "Construção roteirizada dos modelos autorizados",
                               plan_version=versao, executor=config.executor)
        else:
            perfis = json.loads((revisao / "fontes.json").read_text(encoding="utf-8"))
            cliente = cliente_llm if cliente_llm is not None else ClienteChatHttp(config.llm_url, config.chave_api, config.modelo)
            medido = ClienteComOrcamento(cliente, config.orcamento_execucao_usd,
                                         (config.preco_entrada_usd_mtok, config.preco_saida_usd_mtok), verificar_ativa)
            construtor = ExecutorChat(config, medido, ferramentas, publico, perfis, limite, eventos, medidor,
                                     verificar_ativa=verificar_ativa)
            construtor.nome = config.executor
            corretor = construtor

        def corrigir(falha, numero):
            verificar_ativa()
            ferramentas.attempt = numero + 1
            return corretor(falha, numero)

        resultado = construir_e_verificar(construtor, corrigir, tentar, executar_etapa, registrar, limite=limite,
                                          documento_base=texto if referencia_doc else None)
        if medido and (not medido.custo_completo or medido.restante_usd < 0):
            resultado.update(ok=False, codigo="orcamento_llm", erro="medição de custo incompleta ou limite excedido")
            registrar("intervention_requested", resultado)
        return resultado
    finally:
        resumo = medidor.resumo()
        resumo.update(plan_version=versao, documento_base=info_doc, orcamento_usd=config.orcamento_execucao_usd,
                      construtor=config.executor, builds=(resultado or {}).get("tentativas", 0),
                      correcoes=(resultado or {}).get("correcoes", 0), duracao_etapa_s=round(time.monotonic() - inicio, 3))
        resumo["custo_completo"] = (resumo["custo_completo"] and (resultado or {}).get("custo_completo", True)
                                    and (medido is None or medido.custo_completo))
        if medido:
            # Inclui a resposta contabilizada mesmo se a aprovação for revogada no meio da sessão.
            resumo["tokens_entrada"], resumo["tokens_saida"] = medido.tokens_entrada, medido.tokens_saida
            resumo["custo_usd"] = round(config.orcamento_execucao_usd - medido.restante_usd, 6)
            resumo["custo_centavos"] = max(resumo["custo_centavos"], usd_para_centavos(resumo["custo_usd"], config.taxa_usd_brl))
        (revisao / "medicao.json").write_text(json.dumps(resumo, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        eventos.emit_event("construcao", "measurement_saved", "Medição da construção e das correções",
                           plan_version=versao, custo_completo=resumo["custo_completo"],
                           custo_total_centavos=resumo["custo_centavos"] if resumo["custo_completo"] else None,
                           orcamento_centavos=orcamento_centavos, custo_estimado=config.executor == "chat")
