"""Executa no Docker a versão aprovada do plano: o harness constrói; o worker orquestra.

O planejamento da construção acontece antes, no comando `planejar` (planejamento.py), e entra
no plano aprovado como `construction`. Aqui o worker (1) leva o lote autorizado à landing e à
bronze; (2) intermedeia o harness (`construcao.construir_modelos`) com a API da Feita, com o
loop aqui e as ferramentas na sandbox; e (3) guarda a infra e os resultados com hash e monta o
pacote de entrega (`entrega.py`) para a aprovação 2. Não há comparação com gabarito no fluxo:
o avaliador independente (evaluation/worker) é só ferramenta offline de medição (decisão de
27/11/2026). O pipeline feito à mão em pipeline/projeto/models é só o plano B (`roteirizado`).
"""

from __future__ import annotations

import json
import os
import re
import stat
import tempfile
from contextlib import ExitStack
from pathlib import Path

from services.planning.korda_planning import validar_plano

from . import caminhos
from .artefatos import capturar, capturar_infra
from .construcao import (
    FalhaPreparo,
    classificar_falha_dbt as classificar_falha_dbt,
    construir_modelos,
    modelos_a_mao as modelos_a_mao,
    preparar_construcao,
)
from .harness.config import ConfigHarness
from .harness.contexto import projetar_plano
from .lote import preparar_lote
from .correcao import executar_etapa
from .eventos import EmissorEventos
from .ferramentas import FONTES, FerramentasRestritas
from .sandbox import LocalDockerSandbox, RAIZ_REPO

PROJETO = RAIZ_REPO / "services/execution/pipeline/projeto"
MODELO_CTE = "models/prata_ctes.sql"
FONTE_CSV = {
    "erp": ("erp_clientes.csv", "erp_pedidos.csv"),
    "tms": ("tms_veiculos.csv", "tms_viagens.csv", "tms_entregas.csv"),
}
ID_LOCAL = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")


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
        raise FalhaExecucao("nenhum modelo autorizado no plano")
    for padrao in plano["editable_models"]:
        try:
            caminhos.padrao_modelo(padrao)
        except caminhos.CaminhoRecusado as exc:
            raise FalhaExecucao(str(exc)) from None
    # A mesma verificação é repetida pelo ponto de entrada protegido dentro da sandbox.
    from services.execution.pipeline.projeto.ingerir import validar_regras
    validar_regras({chave: regra["value"] for chave, regra in plano["rules"].items()})


def _build_legado(ferramentas, eventos, limite, verificar_ativa):
    def tentar():
        verificar_ativa()
        resultado = ferramentas.rodar_dbt("build")
        if resultado["ok"]:
            return {"ok": True}
        diagnostico = (resultado.get("stdout", "") + "\n" + resultado.get("stderr", ""))[-16000:]
        # Somente uma falha no teste protegido de unicidade permite a correção de CT-e.
        falha_duplicata = re.search(r"(?:Failure in test|FAIL\s+\d+)\s+chave_fiscal_unica\b",
                                    diagnostico, re.IGNORECASE)
        codigo = "implementacao" if falha_duplicata and not resultado.get("estourou_tempo") else "tecnico"
        return {"ok": False, "codigo": codigo, "erro": diagnostico[-1500:] or "dbt build falhou"}

    def corrigir(_falha, tentativa):
        verificar_ativa()
        ferramentas.attempt = tentativa + 1
        correto = (PROJETO / MODELO_CTE).read_text(encoding="utf-8")
        atual = ferramentas.ler_arquivo(MODELO_CTE)
        if not atual["ok"] or atual["conteudo"] == correto:
            return {"ok": False, "erro": "modelo indisponível ou já corresponde à versão revisada",
                    "custo_centavos": 0}
        alteracao = ferramentas.escrever_modelo(MODELO_CTE, correto)
        return {**alteracao, "custo_centavos": 0}

    def registrar(tipo, dados):
        eventos.emit_event("modelos", tipo, dados.get("erro", tipo), dados["tentativas"], **dados)

    return executar_etapa(tentar, corrigir, registrar, limite=limite)


def _escrever_json(caminho, dados):
    caminho.write_text(json.dumps(dados, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


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


def _modelar(sandbox, plano, revisao, eventos, verificar_ativa, config, cliente_llm):
    publico = projetar_plano(plano)
    publico.update({k: plano[k] for k in ("project_id", "dataset")})
    ferramentas = FerramentasRestritas(sandbox, eventos, plano_aprovado=publico,
                                       modelos_permitidos=frozenset(plano["editable_models"]))
    regras = ferramentas.ler_plano()["plano"]["rules"]
    perfis = {}
    for fonte in sorted(FONTES):
        verificar_ativa()
        perfil = ferramentas.inspecionar_fonte(fonte)
        if not perfil["ok"]:
            raise FalhaExecucao(f"perfil de {fonte}: {perfil.get('erro')}")
        perfis[fonte] = perfil["perfil"]
    _escrever_json(revisao / "fontes.json", perfis)
    verificar_ativa()
    bronze = sandbox.rodar_comando(["python", "/work/projeto/ingerir.py"], timeout_s=240,
                                   stdin=json.dumps(regras).encode())
    if not bronze.ok:
        raise FalhaExecucao("projeção da landing em bronze falhou: " + bronze.stderr[-1000:])

    def exportar():
        """Contrato de saída (exportar.py) e, se ele passar, a prata em Parquet para a entrega."""
        verificar_ativa()
        saida = sandbox.rodar_comando(["python", "/work/projeto/exportar.py"], timeout_s=120)
        if saida.ok:
            saida = sandbox.rodar_comando(["python", "/work/projeto/exportar_prata.py"], timeout_s=120)
        return saida

    if config is None:
        resultado = _build_legado(ferramentas, eventos, plano["limits"]["max_repair_attempts_per_step"],
                                  verificar_ativa)
        if resultado["ok"]:
            exportacao = exportar()
            if not exportacao.ok:
                raise FalhaExecucao("exportação falhou: " + exportacao.stderr[-1000:])
    else:
        resultado = construir_modelos(config, plano, ferramentas, eventos, revisao, verificar_ativa,
                                      cliente_llm=cliente_llm, exportar=exportar)
    if not resultado["ok"]:
        raise FalhaExecucao(f"{resultado['codigo']}: {resultado['erro']}")


LIMITE_MODELO_FALHA = 256 * 1024


def _preservar_modelos(sandbox, plano, revisao, eventos) -> None:
    """Numa falha, guarda para diagnóstico os SQL autorizados que o agente escreveu (não vão para a entrega).

    Só arquivos regulares (sem links), com teto de tamanho, e só os caminhos exatos de editable_models.
    """
    try:
        sandbox.destruir(apagar_diretorio=False)
        guardados = []
        for relativo in plano["editable_models"]:
            if "*" in relativo:
                continue
            origem = sandbox.dir_run / "projeto" / relativo
            try:
                info = os.lstat(origem)
            except OSError:
                continue
            if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= LIMITE_MODELO_FALHA:
                continue
            destino = revisao / "falha" / relativo
            destino.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            destino.write_bytes(origem.read_bytes())
            guardados.append(relativo)
        if guardados:
            eventos.emit_event("construcao", "models_preserved", "Modelos escritos guardados para diagnóstico da falha",
                               arquivos=guardados, destino="falha/models")
    except Exception:
        pass  # diagnóstico é melhor esforço; a falha original segue


def executar(registro, plano, run_id, *, raiz: Path, fontes: Path, cfg: ConfigHarness | None = None,
             cliente_llm=None) -> dict:
    """Processa a landing autorizada, chama o harness para construir, congela o resultado e monta a entrega.

    `cliente_llm` só existe para testes (executor `falso`, com respostas roteiradas).
    """
    cfg = cfg or ConfigHarness.de_ambiente()
    _validar_parametros(plano, run_id)
    legado = (plano["schema_version"] == "0.1.0" and plano["editable_models"] == [MODELO_CTE])
    if legado:
        if cfg.executor != "roteirizado":
            raise FalhaExecucao("esta versão do plano autoriza apenas a correção roteirizada do modelo CT-e")
        config = None
    else:
        try:
            config = preparar_construcao(plano, cfg, cliente_llm=cliente_llm)
        except FalhaPreparo as exc:
            raise FalhaExecucao(str(exc)) from None
    raiz = Path(raiz).resolve()
    registro.iniciar(plano["project_id"], plano["plan_version"], run_id)

    def verificar_ativa():
        if registro.consultar(run_id)["state"] != "executando":
            raise FalhaExecucao("a autorização desta execução foi revogada")

    revisao = raiz / "revisao" / run_id
    resultados = revisao / "resultados"
    eventos = EmissorEventos(revisao / "eventos.jsonl", run_id)
    revisao_criada = False
    try:
        revisao.mkdir(mode=0o700, parents=True, exist_ok=False)
        revisao_criada = True
        eventos.emit_event("plano", "run_started", "Iniciada a versão aprovada do plano",
                           project_id=plano["project_id"], plan_version=plano["plan_version"],
                           executor=cfg.executor)
        with tempfile.TemporaryDirectory(dir=revisao, prefix="fontes-") as temp:
            temporario = Path(temp)
            snapshot = temporario / "brutos"
            snapshot.mkdir()
            _snapshot(Path(fontes), snapshot)
            verificar_ativa()
            _landing, publicas, janela = preparar_lote(plano, snapshot, temporario, revisao, eventos, verificar_ativa)
            if janela and janela[0] != janela[1]:
                raise FalhaExecucao("a janela parcial requer uma avaliação específica para o período")
            verificar_ativa()
            sandbox = LocalDockerSandbox(run_id, PROJETO, publicas, raiz_runs=raiz / "sandbox",
                                         modelos_permitidos=tuple(plano["editable_models"]),
                                         modelos_vazios=config is not None)
            try:
                sandbox.criar()
                _modelar(sandbox, plano, revisao, eventos, verificar_ativa, config, cliente_llm)
                _documentar(sandbox, eventos, verificar_ativa)
                # Fechar o produtor antes de abrir arquivos para inspeção no host.
                sandbox.destruir(apagar_diretorio=False)
                manifesto = capturar(sandbox.dir_run / "saida/resultados", resultados)
                # A infra construída pelo agente também entra no manifesto da aprovação 2.
                manifesto["infra"] = capturar_infra(sandbox.dir_run / "projeto/models",
                                                    sandbox.dir_run / "saida/target", revisao / "infra",
                                                    prata=sandbox.dir_run / "saida/prata")
            except BaseException:
                _preservar_modelos(sandbox, plano, revisao, eventos)
                raise
            finally:
                sandbox.destruir()
        # Pronto para a aprovação 2: build com os testes protegidos e o contrato de saída passaram.
        # Não há comparação com gabarito no fluxo (decisão de 27/11/2026): a pessoa decide.
        verificar_ativa()
        registro.finalizar(run_id, aprovado=True, manifesto=manifesto)
        _empacotar(registro, raiz, run_id, eventos)
    except BaseException as exc:
        if registro.consultar(run_id)["state"] == "executando":
            registro.finalizar(run_id, aprovado=False)
            if revisao_criada:
                eventos.emit_event("execucao", "run_failed", str(exc) or type(exc).__name__)
        raise
    return registro.consultar(run_id)
