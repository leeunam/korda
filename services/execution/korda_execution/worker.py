"""Executa no Docker a versão aprovada do plano da transportadora sintética."""

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

from .artefatos import capturar, manifesto_revisao
from .construcao import preparar_construcao, construir_modelos
from .harness.contexto import projetar_plano
from .lote import preparar_lote
from .pacote import montar_pacote
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
    if "ingestion" not in plano and plano["editable_models"] != [MODELO_CTE]:
        raise FalhaExecucao("a lista de modelos autorizados diverge do projeto de execução")
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


def _avaliar(resultados, plano, snapshot, regras, landing, janela, revisao, eventos):
    laudo = avaliar(resultados, plano["dataset"], fontes=snapshot, regras=regras,
                   landing=landing, janela_replay=janela)
    _escrever_json(revisao / "avaliacao.json", laudo)
    eventos.emit_event("avaliacao", "evaluation_finished", laudo["classe"],
                       aprovado=laudo["aprovado"], divergencias=laudo["divergencias"])
    if not laudo["aprovado"]:
        raise FalhaExecucao(f"avaliação externa recusou os resultados ({laudo['classe']})")


def _modelar(sandbox, plano, revisao, eventos, verificar_ativa, config):
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
    if config is None:
        resultado = _build_legado(ferramentas, eventos, plano["limits"]["max_repair_attempts_per_step"],
                                  verificar_ativa)
    else:
        resultado = construir_modelos(config, plano, ferramentas, eventos, revisao, verificar_ativa)
    if not resultado["ok"]:
        raise FalhaExecucao(resultado["erro"])
    verificar_ativa()
    exportacao = sandbox.rodar_comando(["python", "/work/projeto/exportar.py"], timeout_s=120)
    if not exportacao.ok:
        raise FalhaExecucao("exportação falhou: " + exportacao.stderr[-1000:])


def executar(registro, plano, run_id, *, raiz: Path, fontes: Path) -> dict:
    """Processa a landing N0/N1 autorizada e congela a entrega para a segunda aprovação."""
    _validar_parametros(plano, run_id)
    raiz = Path(raiz).resolve()
    regras = {chave: regra["value"] for chave, regra in plano["rules"].items()}
    registro.iniciar(plano["project_id"], plano["plan_version"], run_id)

    def verificar_ativa():
        if registro.consultar(run_id)["state"] != "executando":
            raise FalhaExecucao("a autorização desta execução foi revogada")

    revisao = raiz / "revisao" / run_id
    resultados = revisao / "resultados"
    eventos = EmissorEventos(revisao / "eventos.jsonl", run_id)
    try:
        revisao.mkdir(mode=0o700, parents=True, exist_ok=False)
        eventos.emit_event("plano", "run_started", "Iniciada a versão aprovada do plano",
                           project_id=plano["project_id"], plan_version=plano["plan_version"])
        config = preparar_construcao(plano) if "ingestion" in plano else None
        if config is None and os.environ.get("KORDA_EXECUTOR", "").strip() not in ("", "roteirizado"):
            raise FalhaExecucao("o plano v0.1 autoriza apenas a correção roteirizada do modelo CT-e")
        with tempfile.TemporaryDirectory(dir=revisao, prefix="fontes-") as temp:
            temporario = Path(temp)
            snapshot = temporario / "brutos"
            snapshot.mkdir()
            _snapshot(Path(fontes), snapshot)
            verificar_ativa()
            landing, publicas, janela = preparar_lote(plano, snapshot, temporario, revisao, eventos, verificar_ativa)
            if janela and janela[0] != janela[1]:
                _avaliar(resultados, plano, snapshot, regras, landing, janela, revisao, eventos)
                raise FalhaExecucao("a janela parcial requer uma avaliação específica para o período")
            verificar_ativa()
            sandbox = LocalDockerSandbox(run_id, PROJETO, publicas, raiz_runs=raiz / "sandbox",
                                         modelos_permitidos=tuple(plano["editable_models"]),
                                         modelos_vazios=config is not None)
            try:
                sandbox.criar()
                _modelar(sandbox, plano, revisao, eventos, verificar_ativa, config)
                sandbox.destruir(apagar_diretorio=False)
                manifesto = capturar(sandbox.dir_run / "saida/resultados", resultados)
                verificar_ativa()
                _avaliar(resultados, plano, snapshot, regras, landing, janela, revisao, eventos)
                if config is not None:
                    montar_pacote(sandbox.dir_run / "projeto", resultados, revisao, plano)
                    manifesto = manifesto_revisao(resultados)
            finally:
                sandbox.destruir()
        verificar_ativa()
        registro.finalizar(run_id, aprovado=True, manifesto=manifesto)
    except BaseException as exc:
        if registro.consultar(run_id)["state"] == "executando":
            registro.finalizar(run_id, aprovado=False)
            if revisao.is_dir():
                eventos.emit_event("execucao", "run_failed", str(exc) or type(exc).__name__)
        raise
    return registro.consultar(run_id)
