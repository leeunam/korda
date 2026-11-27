"""Materialização da janela de ingestão aprovada e montagem pública da landing."""

import hashlib
import json
import os
import shutil
import stat
import subprocess
from contextlib import contextmanager
from importlib import import_module
from pathlib import Path

from .ingestao import ErroIngestao, ingerir
from .ingestao_n1 import ErroExecucaoIngestao, executar_ingestao

# O pacote do simulador tem hífen no nome do diretório de infraestrutura.
_controle = import_module("infra.sistemas-simulados.korda_simulados.controle")
AmbienteSimulado = _controle.AmbienteSimulado
ErroSimulado = _controle.ErroSimulado


FORMATO = "korda.landing/v0"
TABELAS = {
    "erp/erp_clientes", "erp/erp_pedidos",
    "tms/tms_veiculos", "tms/tms_viagens", "tms/tms_entregas",
    "cte/cte", "cte/cte_evento", "cte/cte_nfe", "cte/cte_carga",
}
# O leitor de referência usa métodos e nomes físicos do cenário 01.
METODOS = {
    "erp": ("postgres", "snapshot_completo", None),
    "tms": ("api_http", "incremental_campo", {"field": "atualizado_em", "comparison": "maior_que"}),
    "cte": ("pasta_entrega", "novos_arquivos", None),
}
OBJETOS = {
    "erp": {"erp_clientes": ("erp_clientes", ["cd_cli"]), "erp_pedidos": ("erp_pedidos", ["cd_ped"])},
    "tms": {"tms_veiculos": ("/veiculos", ["id_veic"]), "tms_viagens": ("/viagens", ["id_viag"]),
            "tms_entregas": ("/entregas", ["id_ent"])},
    "cte": {"cte": ("**/*.xml", []), "cte_evento": ("**/*.xml", [])},
}
CREDENCIAIS = {
    "erp": {"KORDA_ERP_HOST", "KORDA_ERP_PORTA", "KORDA_ERP_BANCO", "KORDA_ERP_USUARIO", "KORDA_ERP_SENHA"},
    "tms": {"KORDA_TMS_URL", "KORDA_TMS_TOKEN"}, "cte": set(),
}


def _validar_referencia(proposta):
    if proposta["company_id"] != "01_demo" or proposta["state"] != "pronto_para_aprovacao":
        raise ValueError("a referência N1 requer proposta pronta da empresa 01_demo")
    if sorted(f["system"] for f in proposta["sources"]) != ["cte", "erp", "tms"]:
        raise ValueError("a referência N1 exige os três sistemas da demo")
    for f in proposta["sources"]:
        sistema = f["system"]
        if (f["kind"], f["method"], f["incremental_key"]) != METODOS[sistema]:
            raise ValueError(f"método de ingestão não suportado pelo simulador de {sistema}")
        objetos = {o["name"]: (o["locator"], o["key"]) for o in f["objects"]}
        if len(objetos) != len(f["objects"]) or objetos != OBJETOS[sistema]:
            raise ValueError(f"objetos, chaves ou localizadores incompatíveis com {sistema} da 01")
        if set(f["credentials_env"]) != CREDENCIAIS[sistema] or f["on_schema_change"] != "escalar":
            raise ValueError(f"política de acesso ou mudança de esquema incompatível com {sistema}")
        if f["frequency"] != "diaria" or f["acceptable_latency"] != "PT24H":
            raise ValueError(f"a demonstração de {sistema} representa dias de replay e janela diária")
        res = f["resilience"]
        if sistema == "cte" and (res["max_retries"] or res["retry_on"] or res["backoff_seconds"]):
            raise ValueError("a leitura local de CT-e não implementa tentativas de rede")
        if sistema == "erp" and (int(res["timeout_seconds"]) != res["timeout_seconds"]
                                 or not set(res["retry_on"]) <= {"timeout", "conexao"}):
            raise ValueError("política de conexão incompatível com o ERP da referência")


@contextmanager
def _arquivo(raiz, relativo, limite):
    """Abre somente arquivo regular exclusivo em uma das pastas canônicas."""
    pasta = raiz / relativo.parent
    if raiz.is_symlink() or pasta.is_symlink():
        raise ValueError("landing contém diretório indireto")
    fd = os.open(pasta / relativo.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as entrada:
        meta = os.fstat(fd)
        if not stat.S_ISREG(meta.st_mode) or meta.st_nlink != 1 or not 0 < meta.st_size <= limite:
            raise ValueError("arquivo ou tamanho inválido na landing")
        yield entrada, meta.st_size


def _conferir_origem(manifesto, ingestao):
    # O produtor de arquivos (N0) omite "nivel". O simulador (N1) registra 1.
    nivel = manifesto.get("nivel", 0)
    esperado = 1 if ingestao["level"] == "n1" else 0
    if type(nivel) is not int or nivel != esperado:
        raise ValueError("nível do manifesto diverge da ingestão aprovada")
    if nivel == 0:
        if ("plano" in manifesto or "cargas" in manifesto or not isinstance(manifesto.get("arquivos"), list)
                or not isinstance(manifesto.get("totais"), dict)):
            raise ValueError("manifesto incompatível com arquivos exportados N0")
        return
    proposta = ingestao["proposal"]
    # O produtor N1 usa a serialização abaixo em manifesto.plano.sha256. Já o
    # proposal_sha256 do plano P2 usa JSON compacto UTF-8; os bytes são diferentes.
    digest = hashlib.sha256(json.dumps(proposta, sort_keys=True).encode("utf-8")).hexdigest()
    origem = manifesto.get("plano")
    if (not isinstance(origem, dict) or origem.get("company_id") != proposta["company_id"]
            or origem.get("schema_version") != proposta["schema_version"] or origem.get("sha256") != digest):
        raise ValueError("o manifesto N1 não corresponde à proposta de ingestão aprovada")


def _projetar(landing, publico, ingestao, parcial):
    with _arquivo(landing, Path("manifesto.json"), 16 * 1024**2) as (entrada, _):
        dados = entrada.read()
    manifesto = json.loads(dados)
    if not isinstance(manifesto, dict) or manifesto.get("formato") != FORMATO:
        raise ValueError("formato de manifesto desconhecido")
    _conferir_origem(manifesto, ingestao)
    tabelas = manifesto.get("tabelas")
    if (not isinstance(tabelas, dict) or not tabelas or not tabelas.keys() <= TABELAS
            or not parcial and tabelas.keys() != TABELAS):
        raise ValueError("conjunto inesperado de tabelas na landing")
    arquivos = {nome: f"{nome}.parquet" for nome in tabelas}
    if any(not isinstance(tabelas[nome], dict) or tabelas[nome].get("arquivo") != nome_arq
           for nome, nome_arq in arquivos.items()):
        raise ValueError("um caminho de tabela do manifesto diverge da landing")
    rejeitados = manifesto.get("rejeitados")
    if not isinstance(rejeitados, dict) or rejeitados.get("arquivo") != "_rejeitados.parquet":
        raise ValueError("tabela de registros rejeitados ausente")
    publico.mkdir(mode=0o700)
    for nome in [*arquivos.values(), "_rejeitados.parquet"]:
        rel = Path(nome)
        destino = publico / rel
        destino.parent.mkdir(exist_ok=True)
        with _arquivo(landing, rel, 128 * 1024**2) as (entrada, tamanho), destino.open("xb") as saida:
            shutil.copyfileobj(entrada, saida)
            if saida.tell() != tamanho:
                raise ValueError("tamanho da tabela mudou durante projeção")
    (publico / "manifesto.json").write_bytes(dados)
    return hashlib.sha256(dados).hexdigest()


def _carga(amb, secao, landing, eventos, verificar_ativa):
    verificar_ativa()
    resultado = executar_ingestao(amb.credenciais, secao, landing)
    if resultado["codigo"] == 3:
        eventos.emit_event("ingestao", "intervention_requested", "Ingestão interrompida para revisão da fonte.",
                           motivo="escalonamento", dia=amb.dia_atual)
        raise ValueError("a ingestão escalou uma mudança de esquema ou objeto da fonte")
    if resultado["codigo"] != 0:
        raise ValueError("a ingestão não concluiu a carga dos sistemas simulados")
    saida = resultado["saida"]
    if saida.get("resultado") == "sem_novidades" and saida.get("carga") is None:
        return {"dia": amb.dia_atual, "carga": None, "resultado": "sem_novidades"}
    numero = saida.get("carga")
    if saida.get("resultado") != "carga" or type(numero) is not int or numero < 1:
        raise ValueError("a ingestão devolveu uma identificação de carga inválida")
    return {"dia": amb.dia_atual, "carga": numero, "resultado": "carga"}


def preparar_lote(plano, snapshot, temporario, revisao, eventos, verificar_ativa):
    """Executa os leitores oficiais após a aprovação e retorna landing privada, pública e corte."""
    ingestao = plano["ingestion"] if plano["schema_version"] != "0.1.0" else {
        "level": "n0", "window": {"kind": "full_batch"}, "proposal": None, "proposal_sha256": None,
    }
    janela = ingestao["window"]
    nivel = ingestao["level"]
    landing = Path(temporario) / "landing"
    publico = Path(temporario) / "fontes-publicas"
    replay = None
    verificar_ativa()
    try:
        if nivel == "n0":
            if janela != {"kind": "full_batch"} or ingestao["proposal"] is not None:
                raise ValueError("o N0 exige um lote completo de arquivos exportados")
            ingerir(snapshot, landing)
            cargas = [{"dia": None, "carga": 1, "resultado": "carga"}]
        elif nivel == "n1":
            proposta = ingestao["proposal"]
            _validar_referencia(proposta)
            secao = Path(temporario) / "proposta-ingestao.json"
            secao.write_text(json.dumps(proposta, ensure_ascii=False), encoding="utf-8")
            with AmbienteSimulado(plano["dataset"], fontes=snapshot, raiz_runs=Path(temporario),
                                  ate_dia=janela.get("as_of"), mudanca=None) as amb:
                cargas = [_carga(amb, secao, landing, eventos, verificar_ativa)]
                if janela["kind"] == "full_batch":
                    for _ in amb.dias_restantes:
                        verificar_ativa()
                        amb.avancar()
                        cargas.append(_carga(amb, secao, landing, eventos, verificar_ativa))
                replay = (amb.dia_atual, amb.catalogo["dias"][-1])
                if janela["kind"] == "full_batch" and replay[0] != replay[1]:
                    raise ValueError("o simulador não materializou o lote inteiro")
        else:
            raise ValueError("nível de ingestão desconhecido")
        verificar_ativa()
        manifesto_sha = _projetar(landing, publico, ingestao, parcial=replay is not None and replay[0] != replay[1])
        resumo = {"nivel": nivel, "formato": FORMATO, "janela": janela, "cargas": cargas,
                  "dia_atual": replay[0] if replay else None, "ultimo_dia": replay[1] if replay else None,
                  "plan_version": plano["plan_version"], "proposal_sha256": ingestao["proposal_sha256"],
                  "landing_manifest_sha256": manifesto_sha}
        (Path(revisao) / "ingestao.json").write_text(json.dumps(resumo, ensure_ascii=False, indent=2) + "\n",
                                                    encoding="utf-8")
        return landing, publico, replay
    except (ErroIngestao, ErroExecucaoIngestao, ErroSimulado, OSError, subprocess.SubprocessError,
            json.JSONDecodeError) as erro:
        # Exceções do Docker, do driver ou de subprocessos podem conter credenciais.
        if isinstance(erro, ErroSimulado) and str(erro) == "corte de replay fora do intervalo do catálogo":
            raise ValueError("corte de replay fora do intervalo do catálogo") from None
        raise ValueError("a ingestão falhou ao preparar, carregar ou conferir o lote") from None
