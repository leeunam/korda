"""Liga os executores do harness à etapa de construção do worker."""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import replace
from importlib.util import find_spec
from pathlib import Path

from .correcao import executar_etapa
from .documento_base import SECOES, gerar_documento_base
from .harness.agente_sdk import CorretorAgente
from .harness.cliente_chat import ClienteChatFalso, ClienteChatHttp, ClienteComOrcamento, ErroLLM, RespostaChat
from .harness.config import ConfigHarness, ErroConfiguracao
from .harness.contexto import projetar_plano
from .harness.executor_chat import ExecutorChat
from .harness.medicao import Medidor
from .harness.orquestracao import construir_e_verificar
from .harness.roteirizado import ConstrutorRoteirizado, RestauradorRoteirizado
from .harness.tipos import usd_para_centavos
from .sandbox import RAIZ_REPO

PROJETO = RAIZ_REPO / "services/execution/pipeline/projeto"


def preparar_construcao(plano):
    """Verifica a compatibilidade e o portão de rede antes de iniciar a execução."""
    modelos = plano["editable_models"]
    disponiveis = {p.relative_to(PROJETO).as_posix() for p in (PROJETO / "models").rglob("*.sql")}
    if not modelos or len(set(modelos)) != len(modelos) or set(modelos) != disponiveis:
        raise ErroConfiguracao("o plano deve autorizar os modelos exatos deste pipeline; gere e aprove a nova versão")
    config = ConfigHarness.de_ambiente()
    if config.executor == "agente_sdk" and find_spec("claude_agent_sdk") is None:
        raise ErroConfiguracao("agente_sdk exige a dependência opcional de requirements-harness.txt")
    return config


def _documento_local(publico, contexto):
    secoes = (
        publico["editable_models"], publico["rules"], publico["metrics"],
        [t["verify"] for t in publico["tasks"]], contexto["gaps"],
    )
    blocos = [f'# Especificação do plano {publico["plan_version"]}']
    for titulo, valor in zip(SECOES, secoes, strict=True):
        blocos.append(f"## {titulo}\n\n" + json.dumps(valor, ensure_ascii=False, indent=2))
    return "\n\n".join(blocos) + "\n"


def _referencia(publico):
    return {nome: (PROJETO / nome).read_text(encoding="utf-8") for nome in publico["editable_models"]}


def _executores(config, cliente, ferramentas, publico, perfis, eventos, medidor, custo_documento, orcamento_total):
    limite = publico["limits"]["max_repair_attempts_per_step"]
    if config.executor != "chat":
        referencia = _referencia(publico)
    if config.executor in ("falso", "chat"):
        if config.executor == "falso":
            chamadas = [("escrever_modelo", {"caminho": nome, "conteudo": sql}) for nome, sql in referencia.items()]
            cliente = ClienteChatFalso([RespostaChat.de_tool_calls(chamadas, tokens=(0, 0)),
                                        RespostaChat.texto("modelos escritos", tokens=(0, 0))])
        executor = ExecutorChat(config, cliente, ferramentas, publico, perfis, limite, eventos, medidor,
                                custo_anterior_centavos=custo_documento, orcamento_total_usd=orcamento_total)
        executor.nome = config.executor
        return executor, executor

    eventos.emit_event("construcao", "build_started", "Construção roteirizada dos modelos autorizados",
                       plan_version=publico["plan_version"], executor="roteirizado")
    construtor = ConstrutorRoteirizado(ferramentas, referencia)
    if config.executor == "agente_sdk":
        return construtor, CorretorAgente(config, ferramentas, publico, perfis, limite, eventos, medidor)
    return construtor, RestauradorRoteirizado(ferramentas, referencia)


def _resultado_build(ferramentas):
    resultado = ferramentas.rodar_dbt("build")
    if resultado["ok"]:
        return {"ok": True}
    diagnostico = ((resultado.get("stdout") or "") + "\n" + (resultado.get("stderr") or "")).strip()
    if resultado.get("estourou_tempo") or resultado.get("codigo") in (125, 126, 127, 137):
        codigo = "tecnico"
    elif re.search(r"(?:Failure in test|FAIL\s+\d+)\s+(?:integridade_fontes|documentos_conflitantes)\b", diagnostico):
        codigo = "dados"
    else:
        codigo = "implementacao"
    return {"ok": False, "codigo": codigo, "erro": diagnostico[-4000:] or "dbt build falhou"}


def construir_modelos(config, plano, ferramentas, eventos, revisao, verificar_ativa):
    """Constrói, testa e mede a execução. As decisões de aprovação ficam no worker."""
    publico = projetar_plano(plano)
    contexto = {nome: plano[nome] for nome in ("context_id", "context_revision", "rules", "source_profile",
                                               "evidence", "gaps")}
    revisao = Path(revisao)
    perfis = json.loads((revisao / "fontes.json").read_text(encoding="utf-8"))
    medidor = Medidor(eventos.run_id, config.executor, config.modelo if config.usa_llm else None)
    info_doc = {"origem": "api" if config.executor == "chat" else "plano",
                "custo_usd": 0.0, "tokens_entrada": 0, "tokens_saida": 0}
    limite = plano["limits"]["max_repair_attempts_per_step"]
    inicio = time.monotonic()
    resultado = None
    cliente_pago = None

    def registrar(tipo, dados):
        eventos.emit_event("modelos", tipo, dados.get("erro", tipo), max(1, dados.get("tentativas", 1)), **dados)

    def tentar():
        verificar_ativa()
        # Os testes protegidos dependem dos cinco nós. O dbt identifica modelos
        # vazios ou ausentes sem transferir o SQL pela ferramenta de leitura do chat.
        return _resultado_build(ferramentas)

    try:
        verificar_ativa()
        if config.executor == "chat":
            cliente_pago = ClienteComOrcamento(
                ClienteChatHttp(config.llm_url, config.chave_api, config.modelo), config.orcamento_execucao_usd,
                (config.preco_entrada_usd_mtok, config.preco_saida_usd_mtok), verificar_ativa,
            )
            # Ausência de uso medido impede abrir novas sessões com o mesmo orçamento.
            info_doc["custo_usd"] = None
            doc = gerar_documento_base(cliente_pago, contexto, publico,
                                       precos=(config.preco_entrada_usd_mtok, config.preco_saida_usd_mtok))
            info_doc.update(custo_usd=doc.custo_usd, tokens_entrada=doc.tokens_entrada, tokens_saida=doc.tokens_saida)
            if doc.secoes_ausentes:
                raise ValueError("documento-base sem as seções obrigatórias: " + ", ".join(doc.secoes_ausentes))
            if doc.custo_usd is None or doc.custo_usd >= config.orcamento_execucao_usd:
                raise ValueError("uso do documento-base desconhecido ou orçamento da execução esgotado")
            config_sessoes = replace(config, orcamento_execucao_usd=config.orcamento_execucao_usd - doc.custo_usd)
            texto = doc.texto
        else:
            texto = _documento_local(publico, contexto)
            config_sessoes = config
        (revisao / "documento_base.md").write_text(texto, encoding="utf-8")
        info_doc["sha256"] = hashlib.sha256(texto.encode("utf-8")).hexdigest()
        custo_documento = usd_para_centavos(info_doc["custo_usd"], config.taxa_usd_brl)
        orcamento_centavos = usd_para_centavos(config.orcamento_execucao_usd, config.taxa_usd_brl)
        eventos.emit_event("construcao", "document_ready", "Documento-base da versão aprovada",
                           plan_version=plano["plan_version"], custo_total_centavos=custo_documento,
                           orcamento_centavos=orcamento_centavos, custo_estimado=config.executor == "chat", **info_doc)
        verificar_ativa()
        construtor, corretor = _executores(config_sessoes, cliente_pago, ferramentas, publico, perfis, eventos,
                                           medidor, custo_documento, config.orcamento_execucao_usd)

        def corrigir(falha, numero):
            verificar_ativa()
            ferramentas.attempt = numero + 1
            return corretor(falha, numero)

        resultado = construir_e_verificar(construtor, corrigir, tentar, executar_etapa, registrar, limite=limite,
                                          documento_base=texto)
        if cliente_pago and (not cliente_pago.custo_completo or cliente_pago.restante_usd < 0):
            resultado.update(ok=False, codigo="orcamento_llm", erro="medição de custo incompleta ou limite excedido")
            registrar("intervention_requested", resultado)
        return resultado
    except ErroLLM:
        # O gateway pode devolver uma cópia do prompt no corpo do erro. Ela não pertence ao log.
        raise ValueError("o provedor do documento-base não concluiu a chamada autorizada") from None
    finally:
        if info_doc["custo_usd"] is None and cliente_pago and cliente_pago.custo_completo:
            # A resposta vazia ou recusada pode ter consumido tokens antes da validação do documento.
            info_doc.update(custo_usd=round(config.orcamento_execucao_usd - cliente_pago.restante_usd, 6),
                            tokens_entrada=cliente_pago.tokens_entrada, tokens_saida=cliente_pago.tokens_saida)
        resumo = medidor.resumo()
        custo_documento = usd_para_centavos(info_doc["custo_usd"], config.taxa_usd_brl)
        resumo.update(plan_version=plano["plan_version"], documento_base=info_doc,
                      orcamento_usd=config.orcamento_execucao_usd,
                      construtor="roteirizado" if config.executor == "agente_sdk" else config.executor,
                      builds=(resultado or {}).get("tentativas", 0), correcoes=(resultado or {}).get("correcoes", 0),
                      duracao_etapa_s=round(time.monotonic() - inicio, 3))
        resumo["custo_completo"] = (resumo["custo_completo"] and custo_documento is not None
                                     and (resultado or {}).get("custo_completo", True)
                                     and (cliente_pago is None or cliente_pago.custo_completo))
        resumo["tokens_entrada"] += info_doc["tokens_entrada"]
        resumo["tokens_saida"] += info_doc["tokens_saida"]
        resumo["custo_usd"] = round(resumo["custo_usd"] + (info_doc["custo_usd"] or 0), 6)
        resumo["custo_centavos"] += custo_documento or 0
        (revisao / "medicao.json").write_text(json.dumps(resumo, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        eventos.emit_event("construcao", "measurement_saved", "Medição da etapa de modelos",
                           plan_version=plano["plan_version"], custo_completo=resumo["custo_completo"],
                           custo_total_centavos=resumo["custo_centavos"] if resumo["custo_completo"] else None,
                           orcamento_centavos=usd_para_centavos(config.orcamento_execucao_usd, config.taxa_usd_brl),
                           custo_estimado=config.executor == "chat")
