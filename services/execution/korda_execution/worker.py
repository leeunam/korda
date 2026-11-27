"""Orquestra a execução da versão aprovada do plano: o harness constrói; o worker não.

O planejamento da construção acontece antes, no comando `planejar` (planejamento.py),
e entra no plano aprovado como `construction`. Aqui o worker (1) prepara a sandbox com
models/ vazio; (2) intermedeia o harness (`construir_e_verificar`) com a API da Feita, com
o loop aqui e as ferramentas na sandbox, a partir da construção aprovada; e (3) entrega o
resultado ao avaliador independente. O worker não executa nada do pipeline. O executor vem de KORDA_EXECUTOR (ver harness/config.py). O
pipeline feito à mão em pipeline/projeto/models é só o plano B (`roteirizado`) e nunca é
montado na sandbox: o roteirizado o copia pelas mesmas ferramentas do agente.
"""

from __future__ import annotations

import json
import os
import re
import stat
import tempfile
from contextlib import ExitStack
from pathlib import Path

from evaluation.worker.avaliador import avaliar
from services.planning.korda_planning import validar_plano

from . import caminhos
from .artefatos import capturar, capturar_infra
from .correcao import executar_etapa
from .eventos import EmissorEventos
from .ferramentas import FerramentasRestritas
from .harness.cliente_chat import ClienteChatHttp
from .harness.config import ConfigHarness
from .harness.contexto import projetar_plano
from .harness.executor_chat import ExecutorChat
from .harness.medicao import Medidor
from .harness.orquestracao import construir_e_verificar
from .harness.roteirizado import ConstrutorRoteirizado, CorretorRoteirizado
from .sandbox import LocalDockerSandbox, RAIZ_REPO

PROJETO = RAIZ_REPO / "services/execution/pipeline/projeto"
MODELO_CTE = "models/prata_ctes.sql"
FONTE_CSV = {
    "erp": ("erp_clientes.csv", "erp_pedidos.csv"),
    "tms": ("tms_veiculos.csv", "tms_viagens.csv", "tms_entregas.csv"),
}
ID_LOCAL = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")
# Exceções do dbt que indicam modelo a corrigir: 1 = erro em modelo ou teste, 2 = erro de
# compilação/parse (ex.: ref para um modelo que o agente ainda não escreveu).
CODIGOS_DBT_IMPLEMENTACAO = (1, 2)


class FalhaExecucao(ValueError):
    """A execução precisa de intervenção antes de produzir uma entrega."""


def _snapshot(fontes: Path, destino: Path) -> None:
    """Só o lote de arquivos autorizados entra na montagem de fontes."""
    total = 0
    modo_pasta = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    with ExitStack() as abertos:
        lote = os.open(fontes, modo_pasta)
        abertos.callback(os.close, lote)
        for pasta in (*FONTE_CSV, "cte"):
            origem = os.open(pasta, modo_pasta, dir_fd=lote)
            abertos.callback(os.close, origem)
            nomes = FONTE_CSV.get(pasta)
            if nomes is None:
                nomes = sorted(nome for nome in os.listdir(origem) if nome.endswith(".xml"))
                if not 1 <= len(nomes) <= 15_000:
                    raise FalhaExecucao("lote de CT-e vazio ou acima de 15 mil XMLs")
            (destino / pasta).mkdir()
            for nome in nomes:
                fd = os.open(nome, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=origem)
                with os.fdopen(fd, "rb") as arquivo:
                    meta = os.fstat(arquivo.fileno())
                    if not stat.S_ISREG(meta.st_mode) or meta.st_nlink != 1 or meta.st_size > 8 * 1024**2:
                        raise FalhaExecucao(f"fonte irregular ou acima de 8 MiB: {pasta}/{nome}")
                    dados = arquivo.read(meta.st_size + 1)
                    if len(dados) != meta.st_size or os.fstat(arquivo.fileno()).st_mtime_ns != meta.st_mtime_ns:
                        raise FalhaExecucao(f"fonte mudou durante a cópia: {pasta}/{nome}")
                total += len(dados)
                if total > 256 * 1024**2:
                    raise FalhaExecucao("lote de fontes acima de 256 MiB")
                (destino / pasta / nome).write_bytes(dados)


def _validar_parametros(plano: dict, run_id: str) -> None:
    validar_plano(plano)
    if plano["state"] != "aguardando_aprovacao" or plano["dataset"] != "01_demo":
        raise FalhaExecucao("o worker exige um plano completo para o lote sintético 01_demo")
    if not isinstance(run_id, str) or not ID_LOCAL.fullmatch(run_id):
        raise FalhaExecucao("run_id exige um identificador local de até 64 caracteres")
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}", plano["destination"] or ""):
        raise FalhaExecucao("defina um identificador de destino local válido antes da execução")
    if not plano["editable_models"]:
        raise FalhaExecucao("o plano não autoriza nenhum modelo; o harness não tem onde construir")
    for padrao in plano["editable_models"]:
        try:
            caminhos.padrao_modelo(padrao)
        except caminhos.CaminhoRecusado as e:
            raise FalhaExecucao(str(e)) from None
    # A mesma verificação é repetida pelo ponto de entrada protegido dentro da sandbox.
    from services.execution.pipeline.projeto.ingerir import validar_regras
    validar_regras({chave: regra["value"] for chave, regra in plano["rules"].items()})


def modelos_a_mao() -> dict[str, str]:
    """Pipeline feito à mão (plano B). Lido no host; só o executor roteirizado o usa."""
    return {f"models/{arquivo.name}": arquivo.read_text(encoding="utf-8")
            for arquivo in sorted((PROJETO / "models").glob("*.sql"))}


def classificar_falha_dbt(resultado: dict) -> str:
    """Falha de compilação ou de teste de modelo é do agente corrigir; o resto escala direto."""
    if resultado.get("estourou_tempo") or resultado.get("codigo") not in CODIGOS_DBT_IMPLEMENTACAO:
        return "tecnico"
    return "implementacao"


def _executor(cfg, ferramentas, plano_publico, perfis, limite, eventos, medidor, cliente):
    """Devolve (construtor, corretor) do executor escolhido. Todos constroem a partir do plano."""
    if cfg.executor in ("chat", "falso"):
        agente = ExecutorChat(cfg, cliente, ferramentas, plano_publico, perfis, limite, eventos, medidor)
        return agente, agente
    corretor = CorretorRoteirizado(ferramentas, MODELO_CTE,
                                   lambda: (PROJETO / MODELO_CTE).read_text(encoding="utf-8"))
    return ConstrutorRoteirizado(ferramentas, modelos_a_mao()), corretor


def _tentar(ferramentas, sandbox, verificar_ativa):
    """Build com os testes protegidos e exportação no contrato de saída que o avaliador lê."""
    def tentar():
        verificar_ativa()
        resultado = ferramentas.rodar_dbt("build")
        if not resultado["ok"]:
            diagnostico = (resultado.get("stdout", "") + "\n" + resultado.get("stderr", ""))[-16000:]
            return {"ok": False, "codigo": classificar_falha_dbt(resultado),
                    "erro": diagnostico[-1500:] or "dbt build falhou"}
        exportacao = sandbox.rodar_comando(["python", "/work/projeto/exportar.py"], timeout_s=120)
        if exportacao.ok:
            return {"ok": True}
        # Tabela ou coluna de ouro fora do contrato de saída também é do modelo.
        codigo = "implementacao" if exportacao.codigo == 1 and not exportacao.estourou_tempo else "tecnico"
        return {"ok": False, "codigo": codigo,
                "erro": "exportação (contrato de saída em exportar.py) falhou: " + exportacao.stderr[-1400:]}
    return tentar


def _documentar(sandbox, eventos, verificar_ativa):
    """Gera manifest e catalog do dbt (sem rede) para a entrega. Falhar aqui não reprova o build."""
    verificar_ativa()
    # docs generate sobrescreve run_results.json; o da entrega é o do build (status dos testes).
    resultados, guardado = "/work/saida/target/run_results.json", "/work/saida/run_results_build.json"
    sandbox.rodar_comando(["cp", resultados, guardado], timeout_s=30)
    docs = sandbox.rodar_comando(["dbt", "--no-use-colors", "docs", "generate"], timeout_s=180)
    sandbox.rodar_comando(["mv", "-f", guardado, resultados], timeout_s=30)
    if docs.ok:
        eventos.emit_event("entrega", "docs_generated", "dbt docs generate gerou manifest e catalog")
    else:
        eventos.emit_event("entrega", "docs_failed", "dbt docs generate falhou; a entrega sai sem catalog",
                           erro=(docs.stdout + "\n" + docs.stderr)[-1500:], estourou_tempo=docs.estourou_tempo)


def _empacotar(registro, raiz, run_id, eventos):
    """Pacote de entrega automático. Falhar aqui não desfaz a execução: `empacotar` pode ser rodado depois."""
    from .entrega import empacotar

    try:
        pacote = empacotar(registro, raiz, run_id)
    except (OSError, ValueError) as exc:
        eventos.emit_event("entrega", "package_failed", f"pacote de entrega não gerado: {exc}"[:500])
    else:
        eventos.emit_event("entrega", "package_built", "pacote de entrega montado",
                           pasta=str(pacote.relative_to(raiz)))


def executar(registro, plano, run_id, *, raiz: Path, fontes: Path, cfg: ConfigHarness | None = None,
             cliente_llm=None) -> dict:
    """Reserva a execução, chama o harness para construir, congela o resultado e o entrega ao avaliador.

    `cliente_llm` só existe para testes (executor `falso`, com respostas roteiradas).
    """
    # Lido antes de reservar a execução ou criar a sandbox: erro de chave ou de executor falha cedo.
    cfg = cfg or ConfigHarness.de_ambiente()
    if cfg.executor == "agente_sdk":
        # Guardado do #27 (só correção, Claude Agent SDK). A construção usa a API da Feita.
        raise FalhaExecucao("a construção usa a API da Feita: use KORDA_EXECUTOR=chat ou roteirizado")
    if cfg.executor == "falso" and cliente_llm is None:
        raise FalhaExecucao("KORDA_EXECUTOR=falso é só para testes: exige um cliente LLM falso")
    _validar_parametros(plano, run_id)
    construcao = plano.get("construction")
    if cfg.usa_llm and construcao is None:
        raise FalhaExecucao("o plano aprovado não tem a construção: rode `planejar` e aprove o plano com ela")
    if cfg.executor == "roteirizado":
        documento, texto_documento = None, ("# Documento-base\n\n**Não gerado.** O executor roteirizado (plano B) "
                                            "copia o pipeline feito à mão e não usa documento-base.\n")
    elif construcao is not None:
        documento = construcao["document"]
        aviso = "<!-- SINTÉTICO: construção gerada sem LLM real. -->\n\n" if construcao["synthetic"] else ""
        texto_documento = aviso + documento
    else:
        documento, texto_documento = None, "# Documento-base\n\n**Não gerado.** O plano não tem construção.\n"
    if cfg.executor == "chat" and cliente_llm is None:
        cliente_llm = ClienteChatHttp(cfg.llm_url, cfg.chave_api, cfg.modelo)
    raiz = Path(raiz).resolve()
    regras = {chave: regra["value"] for chave, regra in plano["rules"].items()}
    plano_publico = {**projetar_plano(plano), "project_id": plano["project_id"], "dataset": plano["dataset"]}
    limite = plano["limits"]["max_repair_attempts_per_step"]
    registro.iniciar(plano["project_id"], plano["plan_version"], run_id)

    def verificar_ativa():
        if registro.consultar(run_id)["state"] != "executando":
            raise FalhaExecucao("a autorização desta execução foi revogada")

    revisao = raiz / "revisao" / run_id
    eventos = EmissorEventos(revisao / "eventos.jsonl", run_id)
    medidor = Medidor(run_id, cfg.executor, cfg.modelo if cfg.usa_llm else None)
    try:
        revisao.mkdir(parents=True, exist_ok=False)
        eventos.emit_event("plano", "run_started", "Iniciada a versão aprovada do plano",
                           project_id=plano["project_id"], plan_version=plano["plan_version"],
                           executor=cfg.executor)
        (revisao / "documento_base.md").write_text(texto_documento, encoding="utf-8")
        with tempfile.TemporaryDirectory(dir=revisao, prefix="fontes-") as temp:
            snapshot = Path(temp)
            _snapshot(Path(fontes), snapshot)
            verificar_ativa()
            sandbox = LocalDockerSandbox(run_id, PROJETO, snapshot, raiz_runs=raiz / "sandbox",
                                         modelos_permitidos=tuple(plano["editable_models"]),
                                         exigir_manifesto=False)
            try:
                sandbox.criar()
                ferramentas = FerramentasRestritas(sandbox, eventos, plano_aprovado=plano_publico,
                                                    modelos_permitidos=frozenset(plano["editable_models"]))
                perfis = {}
                for fonte in ("erp_pedidos", "tms_entregas", "cte"):
                    perfil = ferramentas.inspecionar_fonte(fonte)
                    if not perfil["ok"]:
                        raise FalhaExecucao(f"perfil de {fonte}: {perfil.get('erro')}")
                    perfis[fonte] = perfil["perfil"]
                (revisao / "fontes.json").write_text(json.dumps(perfis, ensure_ascii=False, indent=2) + "\n",
                                                     encoding="utf-8")
                verificar_ativa()
                ingestao = sandbox.rodar_comando(["python", "/work/projeto/ingerir.py"], timeout_s=240,
                                                 stdin=json.dumps(regras).encode())
                if not ingestao.ok:
                    raise FalhaExecucao("ingestão das fontes falhou: " + ingestao.stderr[-1000:])
                construtor, corretor = _executor(cfg, ferramentas, plano_publico, perfis, limite, eventos,
                                                 medidor, cliente_llm)

                def corrigir(falha, tentativa):
                    verificar_ativa()
                    ferramentas.attempt = tentativa + 1
                    return corretor(falha, tentativa)

                def registrar(tipo, dados):
                    eventos.emit_event("modelos", tipo, str(dados.get("erro", tipo)), dados.get("tentativas", 1),
                                       **{k: v for k, v in dados.items() if k != "construcao"})

                verificar_ativa()
                resultado = construir_e_verificar(construtor, corrigir, _tentar(ferramentas, sandbox, verificar_ativa),
                                                  executar_etapa, registrar, limite=limite,
                                                  documento_base=documento)
                if not resultado["ok"]:
                    raise FalhaExecucao(f"{resultado['codigo']}: {resultado['erro']}")
                _documentar(sandbox, eventos, verificar_ativa)
                # Fechar o produtor antes de abrir arquivos para inspeção no host.
                sandbox.destruir(apagar_diretorio=False)
                manifesto = capturar(sandbox.dir_run / "saida/resultados", revisao / "resultados")
                # A infra construída pelo agente também entra no manifesto da aprovação 2.
                manifesto["infra"] = capturar_infra(sandbox.dir_run / "projeto/models",
                                                    sandbox.dir_run / "saida/target", revisao / "infra")
            finally:
                sandbox.destruir()
            laudo = avaliar(revisao / "resultados", plano["dataset"], fontes=snapshot, regras=regras)
        (revisao / "avaliacao.json").write_text(json.dumps(laudo, ensure_ascii=False, indent=2) + "\n",
                                               encoding="utf-8")
        eventos.emit_event("avaliacao", "evaluation_finished", laudo["classe"],
                           aprovado=laudo["aprovado"], divergencias=laudo["divergencias"])
        if not laudo["aprovado"]:
            raise FalhaExecucao(f"avaliação externa recusou os resultados ({laudo['classe']})")
        registro.finalizar(run_id, aprovado=True, manifesto=manifesto)
        medidor.gravar(revisao / "medicao.json")  # o pacote mostra tempo e custo desta medição
        _empacotar(registro, raiz, run_id, eventos)
    except BaseException as exc:
        # Uma falha na preparação, no build, na comparação ou uma interrupção nunca autoriza entrega.
        if registro.consultar(run_id)["state"] == "executando":
            registro.finalizar(run_id, aprovado=False)
            if revisao.is_dir():
                eventos.emit_event("execucao", "run_failed", str(exc) or type(exc).__name__)
        raise
    finally:
        if revisao.is_dir():
            medidor.gravar(revisao / "medicao.json")
    return registro.consultar(run_id)
