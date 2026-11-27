"""Pacote local de reprodução da execução v0.2, preparado após o aceite técnico."""

import fcntl
import hashlib
import json
import os
import re
import stat
import uuid
import zipfile
from contextlib import contextmanager
from pathlib import Path

from .artefatos import LIMITES, LIMITE_PACOTE, PACOTE, _diretorio


REPO = Path(__file__).resolve().parents[3]
MODELOS = ("prata_ctes", "prata_rateios", "ouro_por_pedido", "ouro_por_viagem", "ouro_kpis")
TESTES = ("chave_fiscal_unica", "conservacao", "contrato_exportacao", "documentos_conflitantes",
          "integridade_fontes", "rastreabilidade_cte")
CONFIG = ("dbt_project.yml", "profiles.yml", "definicoes/fontes.yml", "macros/meio_par.sql",
          "ingerir.py", "exportar.py")
AMBIENTE = ("Dockerfile", "requirements.txt", "consulta.py", "perfil.py",
            *("korda_ingestao/" + n + ".py" for n in ("__init__", "__main__", "csv_bruto", "cte", "landing", "parquet")))
# O SQL gerado também é um artefato público da demo. Rejeite credenciais com
# formato reconhecível sem registrar o texto suspeito em logs ou mensagens.
CREDENCIAL_SQL = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----|\b(?:sk-(?:proj-|ant-)?|gh[pousr]_)[\w-]{20,}"
    r"|\bBearer\s+[A-Za-z0-9._~+/-]{16,}"
    r"|\b(?:api[_-]?key|access[_-]?token|password|senha)\s*[:=]\s*['\"][^'\"\s]{4,}['\"]",
    re.IGNORECASE,
)
REPRODUZIR = """# Reproduzir os indicadores

Extraia este ZIP em um diretório novo. A pasta `projeto/` contém o SQL que o dbt executou e os testes protegidos. `resultados/` contém os indicadores e sua linhagem por pedido e viagem. `execucao.json` identifica a revisão do plano, a janela, o destino autorizado pelo plano e o laudo técnico. A autorização humana para entrega é registrada pelo serviço que promove a pasta.

Use Docker em Linux e a mesma landing autorizada da execução, com manifesto e tabelas Parquet. Em N0 ela vem dos arquivos exportados. Em N1 ela corresponde à janela do ERP, TMS e CT-e simulados. O operador fornece essa pasta em separado. Confira `sha256sum "$LANDING/manifesto.json"` com `landing_manifest_sha256` de `execucao.json` para identificar o manifesto original.

Para regenerar as entradas sintéticas, use o gerador `data/synthetic/generator/generate.py --empresa 01_demo` do repositório Korda. Aplique ao lote o nível e a janela registrados em `execucao.json`, usando a ingestão N0 ou o replay dos sistemas simulados N1 na versão do projeto da execução. O diretório `ambiente/korda_ingestao/` traz o leitor N0; nas entregas N1, `referencia/ingestao_n1/` traz também o leitor do simulador. Uma nova carga pode registrar outro horário e produzir um hash físico de manifesto diferente. Use os hashes dos três resultados para conferir o replay da mesma janela.

Na raiz extraída, defina `LANDING` como o caminho absoluto da landing. Comece com um diretório `saida` novo. O primeiro comando prepara o ambiente com as versões da demo. O segundo executa o tratamento dos dados sem rede.

```sh
docker build -t korda-repro:local ambiente
mkdir -m 700 saida
docker run --rm -i --network none --read-only --cap-drop ALL \\
  --security-opt no-new-privileges --user "$(id -u):$(id -g)" --tmpfs /tmp:rw,nosuid,size=256m \\
  --memory 2g --cpus 1 --pids-limit 256 \\
  -v "$PWD/projeto:/work/projeto:ro" -v "$LANDING:/work/fontes:ro" \\
  -v "$PWD/saida:/work/saida" korda-repro:local sh -ec \\
  'python /work/projeto/ingerir.py && dbt --no-use-colors build && python /work/projeto/exportar.py' < regras.json
(cd saida && sha256sum -c ../resultados.sha256)
```

Para auditar o frete, localize o pedido em `resultados/por_pedido.csv` e consulte `linhagem_cte`, com a chave do documento, hash do XML e centavos rateados. O mesmo CSV identifica o pedido e a entrega que sustentam o OTIF. `por_viagem.csv` identifica a viagem e o veículo usados para ocupação. Em N1, use também a carga da landing para localizar o registro da janela avaliada.
"""


@contextmanager
def _arquivo(pasta, nome, limite):
    relativo = Path(nome)
    if relativo.is_absolute() or ".." in relativo.parts:
        raise ValueError("caminho de arquivo inválido")
    with _diretorio(pasta / relativo.parent) as pai:
        fd = os.open(relativo.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=pai)
        try:
            st = os.fstat(fd)
            if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or not 0 < st.st_size <= limite:
                raise ValueError(f"arquivo de pacote irregular ou excede limite: {nome}")
            with os.fdopen(fd, "rb", closefd=False) as entrada:
                yield entrada
            final = os.fstat(fd)
            if (st.st_size, st.st_mtime_ns) != (final.st_size, final.st_mtime_ns):
                raise ValueError(f"arquivo de pacote mudou durante a captura: {nome}")
        finally:
            os.close(fd)


def _ler(pasta, nome, limite):
    with _arquivo(pasta, nome, limite) as f:
        dados = f.read(limite + 1)
        if len(dados) > limite:
            raise ValueError(f"arquivo excede limite de leitura: {nome}")
        return dados


def _json(valor):
    return (json.dumps(valor, ensure_ascii=False, allow_nan=False, sort_keys=True, indent=2) + "\n").encode()


def _entrada_zip(nome):
    info = zipfile.ZipInfo(nome)  # Horário fixo, independente do momento de empacotar.
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    return info


def _dbt(projeto, modelos):
    target = projeto.parent / "saida/target"
    relatorio = json.loads(_ler(target, "run_results.json", 8 * 1024**2))
    manifest = json.loads(_ler(target, "manifest.json", 16 * 1024**2))
    if not relatorio["metadata"].get("invocation_id") or (
        relatorio["metadata"]["invocation_id"] != manifest["metadata"].get("invocation_id")
    ):
        raise ValueError("relatório e manifesto dbt pertencem a builds diferentes")
    esperados = {f"model.korda_logistica.{m}": "success" for m in MODELOS}
    esperados.update({f"test.korda_logistica.{t}": "pass" for t in TESTES})
    nos = {r["unique_id"]: r["status"] for r in relatorio["results"]}
    if nos != esperados or len(nos) != len(relatorio["results"]):
        raise ValueError("o dbt não confirmou todos os modelos e testes protegidos")
    for nome, dados in modelos.items():
        node = manifest["nodes"]["model.korda_logistica." + Path(nome).stem]
        codigo = dados.decode("utf-8").replace("\r\n", "\n").strip()
        if not codigo or node["original_file_path"] != nome or node["raw_code"].strip() != codigo:
            raise ValueError(f"o SQL capturado diverge do modelo testado: {nome}")
        if CREDENCIAL_SQL.search(codigo):
            raise ValueError(f"credencial identificada no SQL; revise o modelo antes da entrega: {nome}")
    return {"versao": relatorio["metadata"]["dbt_version"], "nos": nos}


def _resumo(revisao, plano, dbt):
    laudo = json.loads(_ler(revisao, "avaliacao.json", 512 * 1024))
    controles = ("fontes_conferidas", "regras_conferidas", "landing_conferida", "linhagem_conferida")
    if (laudo.get("aprovado") is not True or laudo.get("classe") != "ok" or laudo.get("divergencias") != 0
            or any(laudo.get(c) is not True for c in controles) or laudo.get("empresa") != plano["dataset"]
            or laudo.get("nivel") != {"n0": 0, "n1": 1}[plano["ingestion"]["level"]]):
        raise ValueError("o pacote requer laudo aprovado para o cenário da execução")
    comparados = laudo["comparados"]
    if (set(comparados) != {"kpis", "por_pedido.csv", "por_viagem.csv"} or comparados["kpis"] != 3
            or any(type(n) is not int or n < 1 for n in comparados.values())):
        raise ValueError("laudo sem confronto de indicadores, pedidos e viagens")
    ingestao = json.loads(_ler(revisao, "ingestao.json", 8 * 1024**2))
    digest = ingestao["landing_manifest_sha256"]
    if not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest):
        raise ValueError("hash do manifesto da landing inválido")
    return {
        "run_id": revisao.name,
        **{k: plano[k] for k in ("schema_version", "plan_version", "project_id", "context_revision", "dataset", "destination")},
        "ingestion": {k: plano["ingestion"][k] for k in ("level", "window", "proposal_sha256")},
        "landing_manifest_sha256": digest,
        "dbt": dbt,
        "avaliacao": {k: laudo[k] for k in ("aprovado", "classe", "divergencias", "comparados", *controles)},
    }


def _preencher(arquivo, projeto, resultados, revisao, plano):
    modelos = {f"models/{nome}.sql": _ler(projeto, f"models/{nome}.sql", 256 * 1024) for nome in MODELOS}
    if set(plano["editable_models"]) != set(modelos):
        raise ValueError("modelos aprovados divergem dos modelos do pacote")
    resumo = _resumo(revisao, plano, _dbt(projeto, modelos))
    regras = {k: v["value"] for k, v in plano["rules"].items()}
    arquivo.writestr(_entrada_zip("README.md"), REPRODUZIR.encode())
    arquivo.writestr(_entrada_zip("regras.json"), _json(regras))
    arquivo.writestr(_entrada_zip("execucao.json"), _json(resumo))
    for nome, dados in sorted(modelos.items()):
        arquivo.writestr(_entrada_zip("projeto/" + nome), dados)
    for nome in (*CONFIG, *(f"tests/{t}.sql" for t in TESTES)):
        arquivo.writestr(_entrada_zip("projeto/" + nome), _ler(projeto, nome, 256 * 1024))
    for nome in AMBIENTE:
        arquivo.writestr(_entrada_zip("ambiente/" + nome), _ler(REPO / "infra/sandbox", nome, 256 * 1024))
    if plano["ingestion"]["level"] == "n1":
        for nome in ("__init__.py", "__main__.py", "fontes.py"):
            caminho = "ingestao_n1/" + nome
            arquivo.writestr(_entrada_zip("referencia/" + caminho),
                             _ler(REPO / "services/execution/referencia", caminho, 256 * 1024))
    hashes = []
    for nome, limite in LIMITES.items():
        caminho = "resultados/" + nome
        digest = hashlib.sha256()
        lidos = 0
        with _arquivo(resultados, nome, limite) as src, arquivo.open(_entrada_zip(caminho), "w") as dst:
            while bloco := src.read(128 * 1024):
                lidos += len(bloco)
                if lidos > limite:
                    raise ValueError(f"resultado excede limite: {nome}")
                dst.write(bloco)
                digest.update(bloco)
        hashes.append(f"{digest.hexdigest()}  {caminho}\n")
    arquivo.writestr(_entrada_zip("resultados.sha256"), "".join(hashes).encode())


def montar_pacote(projeto: Path, resultados: Path, revisao: Path, plano: dict) -> Path:
    """Publica o ZIP na área privada de revisão. O registro decide a promoção ao destino."""
    projeto, resultados, revisao = Path(projeto), Path(resultados), Path(revisao)
    if resultados != revisao / "resultados" or plano["schema_version"] != "0.2.0":
        raise ValueError("o pacote exige os resultados da revisão v0.2 da execução")
    temporario = ".pacote-" + uuid.uuid4().hex
    with _diretorio(resultados) as pai:
        # Leitores do manifesto e outros produtores veem apenas o inventário definitivo.
        fcntl.flock(pai, fcntl.LOCK_EX)
        fd = os.open(temporario, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600, dir_fd=pai)
        try:
            with os.fdopen(fd, "w+b") as lote:
                with zipfile.ZipFile(lote, "w", allowZip64=False) as arquivo:
                    _preencher(arquivo, projeto, resultados, revisao, plano)
                lote.flush()
                os.fsync(lote.fileno())
                if lote.tell() > LIMITE_PACOTE:
                    raise ValueError("o pacote ultrapassa o limite de promoção")
                # Publicação sem sobrescrever um pacote existente em uma revisão congelada.
                try:
                    os.link(temporario, PACOTE, src_dir_fd=pai, dst_dir_fd=pai, follow_symlinks=False)
                except FileExistsError:
                    lote.seek(0)
                    with _arquivo(resultados, PACOTE, LIMITE_PACOTE) as existente:
                        if hashlib.file_digest(lote, "sha256").digest() != hashlib.file_digest(existente, "sha256").digest():
                            raise ValueError("esta revisão já possui pacote com bytes diferentes")
        finally:
            os.unlink(temporario, dir_fd=pai)
            os.fsync(pai)
    return resultados / PACOTE
