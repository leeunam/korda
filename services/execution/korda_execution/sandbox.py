"""Interface `Sandbox` e implementação local com Docker (K08).

O worker (este processo, no host) controla a sandbox pelo CLI do Docker. Código gerado
roda só dentro do contêiner, que não tem rede, não tem root e só enxerga montagens
explícitas:

    /work/fontes          somente leitura  (landing zone em Parquet das fontes sintéticas)
    /work/projeto         somente leitura  (dbt_project, profiles, definicoes/, tests/)
    /work/projeto/models  escrita          (modelos que o agente pode criar)
    /work/saida           escrita          (banco DuckDB, target/ e logs/ do dbt)

Isto é isolamento de demo, não de produção: o kernel é compartilhado com o host.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

RAIZ_REPO = Path(__file__).resolve().parents[3]
IMAGEM_PADRAO = os.environ.get("KORDA_SANDBOX_IMAGE", "korda-sandbox:dev")
RAIZ_RUNS_PADRAO = RAIZ_REPO / "runs"
LIMITE_SAIDA = 20_000  # caracteres de stdout/stderr devolvidos (mantém o final, onde o dbt põe o erro)
FOLGA_TIMEOUT_HOST = 15  # segundos extras antes de o host desistir do `docker exec`

DIR_FONTES = "/work/fontes"
DIR_PROJETO = "/work/projeto"
DIR_MODELS = "/work/projeto/models"
DIR_SAIDA = "/work/saida"

_RUN_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


class ErroSandbox(RuntimeError):
    """Falha ao criar, usar ou destruir a sandbox."""


@dataclass(frozen=True)
class Limites:
    memoria: str = "2g"
    cpus: str = "1"
    pids: int = 256
    tmp: str = "256m"


@dataclass(frozen=True)
class ResultadoComando:
    codigo: int
    stdout: str
    stderr: str
    duracao_s: float
    estourou_tempo: bool

    @property
    def ok(self) -> bool:
        return self.codigo == 0 and not self.estourou_tempo


class Sandbox(Protocol):
    """Contrato mínimo usado pelo worker. A versão em nuvem deve cumprir o mesmo."""

    run_id: str

    def criar(self) -> None: ...

    def enviar_arquivos(self, arquivos: dict[str, bytes]) -> None: ...

    def rodar_comando(
        self, argv: list[str], timeout_s: int = 300, stdin: bytes | None = None
    ) -> ResultadoComando: ...

    def destruir(self) -> None: ...


def _truncar(texto: str) -> str:
    if len(texto) <= LIMITE_SAIDA:
        return texto
    return "[... saída truncada ...]\n" + texto[-LIMITE_SAIDA:]


def docker_disponivel() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        r = subprocess.run(["docker", "info"], capture_output=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return r.returncode == 0


def imagem_existe(imagem: str = IMAGEM_PADRAO) -> bool:
    r = subprocess.run(["docker", "image", "inspect", imagem], capture_output=True)
    return r.returncode == 0


def opcoes_isolamento(limites: Limites) -> list[str]:
    """Opções de `docker run` comuns à sandbox e à ingestão: sem rede, sem root, sem privilégios."""
    return [
        "--network", "none",
        "--read-only",
        "--tmpfs", f"/tmp:rw,noexec,nosuid,size={limites.tmp}",
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "--memory", limites.memoria,
        "--memory-swap", limites.memoria,
        "--cpus", limites.cpus,
        "--pids-limit", str(limites.pids),
        "--user", f"{os.getuid()}:{os.getgid()}",
    ]


def montagens_ocultas(origem: Path, destino: str, nomes: tuple[str, ...]) -> list[str]:
    """Cobre subpastas de `origem` com um tmpfs vazio, de root e sem escrita (ex.: `_gerador/`)."""
    argv: list[str] = []
    for nome in nomes:
        if (origem / nome).exists():
            argv += ["--mount", f"type=tmpfs,dst={destino}/{nome},tmpfs-size=4k,tmpfs-mode=0555"]
    return argv


@dataclass
class LocalDockerSandbox:
    """Uma execução = um diretório em runs/<run_id>/ + um contêiner."""

    run_id: str
    projeto: Path
    fontes: Path
    imagem: str = IMAGEM_PADRAO
    raiz_runs: Path = RAIZ_RUNS_PADRAO
    limites: Limites = field(default_factory=Limites)
    # Subpastas das fontes que o executor não pode ver. `_gerador/` registra onde as
    # anomalias foram plantadas: seria uma folha de respostas.
    ocultar_nas_fontes: tuple[str, ...] = ("_gerador",)
    # `fontes` deve ser uma landing zone (ver ingestao.py), com manifesto.json na raiz.
    exigir_manifesto: bool = True
    container_id: str | None = None

    def __post_init__(self) -> None:
        if not _RUN_ID.match(self.run_id):
            raise ErroSandbox(f"run_id inválido: {self.run_id!r}")
        self.projeto = Path(self.projeto).resolve()
        self.fontes = Path(self.fontes).resolve()
        self.raiz_runs = Path(self.raiz_runs).resolve()

    @property
    def dir_run(self) -> Path:
        return self.raiz_runs / self.run_id

    @property
    def nome_container(self) -> str:
        return f"korda-run-{self.run_id}"

    def criar(self) -> None:
        if self.container_id:
            raise ErroSandbox("sandbox já criada")
        if os.getuid() == 0:
            # O contêiner herda o uid do worker; como root, ele também rodaria como root.
            raise ErroSandbox("não rode o worker como root")
        if not (self.projeto / "dbt_project.yml").is_file():
            raise ErroSandbox(f"projeto dbt não encontrado em {self.projeto}")
        if not self.fontes.is_dir():
            raise ErroSandbox(f"pasta de fontes não encontrada: {self.fontes}")
        if self.exigir_manifesto and not (self.fontes / "manifesto.json").is_file():
            raise ErroSandbox(
                f"{self.fontes} não é uma landing zone (sem manifesto.json); "
                "rode a ingestão: python -m korda_execution.ingestao"
            )
        if self.dir_run.exists():
            raise ErroSandbox(f"diretório da execução já existe: {self.dir_run}")
        if not imagem_existe(self.imagem):
            raise ErroSandbox(
                f"imagem {self.imagem} não encontrada; rode: docker build -t {self.imagem} infra/sandbox"
            )

        projeto_run = self.dir_run / "projeto"
        saida_run = self.dir_run / "saida"
        shutil.copytree(self.projeto, projeto_run, symlinks=False)
        (projeto_run / "models").mkdir(exist_ok=True)
        saida_run.mkdir(parents=True)

        argv = [
            "docker", "run", "--detach",
            "--name", self.nome_container,
            "--label", f"korda.run_id={self.run_id}",
            *opcoes_isolamento(self.limites),
            "--mount", f"type=bind,src={self.fontes},dst={DIR_FONTES},readonly",
            "--mount", f"type=bind,src={projeto_run},dst={DIR_PROJETO},readonly",
            "--mount", f"type=bind,src={projeto_run / 'models'},dst={DIR_MODELS}",
            "--mount", f"type=bind,src={saida_run},dst={DIR_SAIDA}",
            *montagens_ocultas(self.fontes, DIR_FONTES, self.ocultar_nas_fontes),
        ]
        argv.append(self.imagem)
        r = subprocess.run(argv, capture_output=True, text=True)
        if r.returncode != 0:
            shutil.rmtree(self.dir_run, ignore_errors=True)
            raise ErroSandbox(f"docker run falhou: {r.stderr.strip()}")
        self.container_id = r.stdout.strip()

    def _exigir_ativa(self) -> str:
        if not self.container_id:
            raise ErroSandbox("sandbox não foi criada ou já foi destruída")
        return self.container_id

    def rodar_comando(
        self, argv: list[str], timeout_s: int = 300, stdin: bytes | None = None
    ) -> ResultadoComando:
        """Roda argv (sem shell) no contêiner. O tempo limite é imposto lá dentro com `timeout -s KILL`."""
        cid = self._exigir_ativa()
        if not argv:
            raise ErroSandbox("comando vazio")
        cmd = ["docker", "exec"]
        if stdin is not None:
            cmd.append("--interactive")
        cmd += [cid, "timeout", "-s", "KILL", str(int(timeout_s)), *argv]
        inicio = time.monotonic()
        try:
            r = subprocess.run(
                cmd, input=stdin, capture_output=True, timeout=timeout_s + FOLGA_TIMEOUT_HOST
            )
            codigo, out, err = r.returncode, r.stdout, r.stderr
        except subprocess.TimeoutExpired as e:
            codigo, out, err = 137, e.stdout or b"", (e.stderr or b"") + b"\n[host] docker exec sem resposta"
        duracao = time.monotonic() - inicio
        return ResultadoComando(
            codigo=codigo,
            stdout=_truncar(out.decode("utf-8", "replace")),
            stderr=_truncar(err.decode("utf-8", "replace")),
            duracao_s=round(duracao, 3),
            # `timeout -s KILL` faz o processo terminar com 137 (128 + SIGKILL).
            estourou_tempo=codigo == 137 and duracao >= timeout_s,
        )

    def enviar_arquivos(self, arquivos: dict[str, bytes]) -> None:
        """Grava arquivos por caminho absoluto **dentro** do contêiner.

        A escrita acontece lá dentro, então montagens somente leitura recusam o que estiver
        fora de models/ e saida/, e um symlink criado na sandbox não alcança o host.
        """
        for destino, conteudo in arquivos.items():
            r = self.rodar_comando(
                ["sh", "-c", 'mkdir -p -- "$(dirname -- "$1")" && cat > "$1"', "sh", destino],
                timeout_s=30,
                stdin=conteudo,
            )
            if not r.ok:
                raise ErroSandbox(f"escrita recusada em {destino}: {r.stderr.strip()}")

    def destruir(self, apagar_diretorio: bool = True) -> None:
        subprocess.run(["docker", "rm", "--force", self.nome_container], capture_output=True)
        self.container_id = None
        if apagar_diretorio:
            shutil.rmtree(self.dir_run, ignore_errors=True)

    def __enter__(self) -> "LocalDockerSandbox":
        self.criar()
        return self

    def __exit__(self, *exc) -> None:
        self.destruir()
