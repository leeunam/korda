"""Controle do ambiente simulado do cliente pelo CLI do Docker (host, só biblioteca padrão).

Um ambiente = uma empresa + uma rede Docker interna (`--internal`, sem internet) com:

    erp   Postgres 17 com as tabelas do ERP (nomes físicos da empresa) e um usuário somente leitura
    tms   API HTTP do TMS (korda_simulados.tms_api) com token
    cte   pasta de entrega por dia em runs/sim-<id>/entrega/cte/<AAAA-MM-DD>/ (estilo SFTP)

O replay começa com N dias carregados; `avancar()` libera o dia seguinte nos três sistemas.
Credenciais são geradas na subida, ficam em runs/sim-<id>/credenciais.json (0600, fora do Git)
e nunca devem entrar no contexto de um LLM.

Uso (a partir de infra/sistemas-simulados/):
    python3 -m korda_simulados.controle subir --empresa 01_demo     # imprime o id do ambiente
    python3 -m korda_simulados.controle avancar --id <id>
    python3 -m korda_simulados.controle destruir --id <id>
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

_AQUI = Path(__file__).resolve()
# infra/sistemas-simulados/korda_simulados/controle.py -> raiz do repositório (fora dele, só importa sem usar)
RAIZ_REPO = Path(os.environ.get("KORDA_RAIZ_REPO") or (_AQUI.parents[3] if len(_AQUI.parents) > 3 else _AQUI.parent))
IMAGEM_SIM = os.environ.get("KORDA_SIM_IMAGE", "korda-simulados:dev")
IMAGEM_PG = os.environ.get("KORDA_SIM_PG_IMAGE", "postgres:17.6-alpine")
EMPRESA_RESERVADA = "03_reservada"
PORTA_TMS = 8080
USUARIO_ADMIN = "korda_admin"
USUARIO_LEITURA = "korda_leitura"
BANCO = "erp"


class ErroSimulado(RuntimeError):
    pass


def _docker(*argv: str, entrada: bytes | None = None, timeout: int = 120, checar: bool = True):
    r = subprocess.run(["docker", *argv], input=entrada, capture_output=True, timeout=timeout)
    if checar and r.returncode != 0:
        raise ErroSimulado(f"docker {argv[0]} falhou: {r.stderr.decode('utf-8', 'replace').strip()[-1500:]}")
    return r


def imagens_disponiveis() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        return all(_docker("image", "inspect", i, checar=False, timeout=20).returncode == 0
                   for i in (IMAGEM_SIM, IMAGEM_PG))
    except (OSError, subprocess.TimeoutExpired):
        return False


def _ident(nome: str) -> str:
    return '"' + nome.replace('"', '""') + '"'


@dataclass
class AmbienteSimulado:
    empresa: str
    sim_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    fontes: Path | None = None
    raiz_runs: Path = RAIZ_REPO / "runs"
    dias_iniciais: int | None = None  # padrão: todos menos o último ("chega o dia N+1")
    mudanca: str | None = "ultimo"  # dia da mudança de esquema; None desliga
    falhas: dict | None = None
    limite_rps: int = 20
    permitir_reservada: bool = False  # 03_reservada só para medição

    def __post_init__(self) -> None:
        if self.empresa == EMPRESA_RESERVADA and not self.permitir_reservada:
            raise ErroSimulado("03_reservada é só para medição: use permitir_reservada=True")
        self.fontes = Path(self.fontes or RAIZ_REPO / "data" / "synthetic" / "output" / self.empresa).resolve()
        self.empresa_yaml = RAIZ_REPO / "data" / "synthetic" / "empresas" / self.empresa / "empresa.yaml"
        self.dir = Path(self.raiz_runs).resolve() / f"sim-{self.sim_id}"
        self.rede = f"korda-sim-{self.sim_id}"
        self.c_erp = f"korda-sim-{self.sim_id}-erp"
        self.c_tms = f"korda-sim-{self.sim_id}-tms"
        self.catalogo: dict | None = None
        self.dia_atual: str | None = None
        self.credenciais: dict = {}

    # Caminhos
    @property
    def dir_preparo(self) -> Path:
        return self.dir / "preparo"

    @property
    def dir_entrega(self) -> Path:
        return self.dir / "entrega"

    @property
    def dir_estado(self) -> Path:
        return self.dir / "estado"

    # Ciclo de vida
    def subir(self) -> "AmbienteSimulado":
        if os.getuid() == 0:
            raise ErroSimulado("não rode o controle como root")
        if not (self.fontes / "cte").is_dir() or not self.empresa_yaml.is_file():
            raise ErroSimulado(f"fontes de {self.empresa} não geradas ({self.fontes})")
        if not imagens_disponiveis():
            raise ErroSimulado(f"imagens ausentes: docker build -t {IMAGEM_SIM} infra/sistemas-simulados "
                               f"&& docker pull {IMAGEM_PG}")
        if self.dir.exists():
            raise ErroSimulado(f"ambiente já existe: {self.dir}")
        for d in (self.dir_preparo, self.dir_entrega / "cte", self.dir_estado):
            d.mkdir(parents=True)
        try:
            self._preparar()
            self._gerar_credenciais()
            _docker("network", "create", "--internal", "--label", f"korda.sim={self.sim_id}", self.rede)
            self._subir_erp()
            self._subir_tms()
            dias = self.catalogo["dias"]
            n = len(dias) - 1 if self.dias_iniciais is None else self.dias_iniciais
            if not 1 <= n <= len(dias):
                raise ErroSimulado(f"dias_iniciais fora de 1..{len(dias)}: {n}")
            for dia in dias[:n]:
                self._liberar(dia)
        except BaseException:
            self.destruir()
            raise
        return self

    def _preparar(self) -> None:
        argv = [
            "run", "--rm", "--network", "none", "--read-only", "--tmpfs", "/tmp",
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--user", f"{os.getuid()}:{os.getgid()}",
            "--mount", f"type=bind,src={self.fontes},dst=/work/fontes,readonly",
            "--mount", f"type=bind,src={self.empresa_yaml},dst=/work/empresa.yaml,readonly",
            "--mount", f"type=bind,src={self.dir_preparo},dst=/work/saida",
        ]
        if (self.fontes / "_gerador").exists():  # o simulador não precisa da folha de respostas
            argv += ["--mount", "type=tmpfs,dst=/work/fontes/_gerador,tmpfs-size=4k,tmpfs-mode=0555"]
        argv += [IMAGEM_SIM, "python", "-m", "korda_simulados.preparar",
                 "--fontes", "/work/fontes", "--empresa", "/work/empresa.yaml", "--saida", "/work/saida",
                 "--mudanca", self.mudanca or "nenhuma"]
        _docker(*argv, timeout=600)
        self.catalogo = json.loads((self.dir_preparo / "catalogo.json").read_text(encoding="utf-8"))

    def _gerar_credenciais(self) -> None:
        self.credenciais = {
            "rotulo": "Credenciais falsas de um ambiente simulado. Não versionar; não enviar a um LLM.",
            "rede": self.rede,
            "erp": {"host": "erp", "porta": 5432, "banco": BANCO, "usuario": USUARIO_LEITURA,
                    "senha": secrets.token_urlsafe(18)},
            "tms": {"url": f"http://tms:{PORTA_TMS}/api/v1", "token": secrets.token_urlsafe(24)},
            "cte": {"pasta_host": str(self.dir_entrega / "cte")},
        }
        self._senha_admin = secrets.token_urlsafe(18)
        arq = self.dir / "credenciais.json"
        arq.touch(mode=0o600)
        arq.write_text(json.dumps(self.credenciais, indent=1) + "\n", encoding="utf-8")

    def _psql_admin(self, sql: str) -> str:
        r = _docker("exec", "-i", self.c_erp, "psql", "-h", "127.0.0.1", "-U", USUARIO_ADMIN, "-d", BANCO,
                    "-v", "ON_ERROR_STOP=1", "-q", "-At", "-f", "-", entrada=sql.encode("utf-8"))
        return r.stdout.decode("utf-8")

    def _subir_erp(self) -> None:
        _docker(
            "run", "--detach", "--name", self.c_erp, "--label", f"korda.sim={self.sim_id}",
            "--network", self.rede, "--network-alias", "erp",
            "--security-opt", "no-new-privileges", "--memory", "512m", "--pids-limit", "256",
            "-e", f"POSTGRES_USER={USUARIO_ADMIN}", "-e", f"POSTGRES_PASSWORD={self._senha_admin}",
            "-e", f"POSTGRES_DB={BANCO}", "-e", "PGPASSWORD=" + self._senha_admin,
            IMAGEM_PG,
        )
        # O entrypoint sobe um servidor temporário só em socket; TCP responde quando o real está pronto.
        prazo = time.monotonic() + 60
        while _docker("exec", self.c_erp, "psql", "-h", "127.0.0.1", "-U", USUARIO_ADMIN, "-d", BANCO,
                      "-c", "select 1", checar=False).returncode != 0:
            if time.monotonic() > prazo:
                raise ErroSimulado("Postgres simulado não ficou pronto em 60 s")
            time.sleep(0.5)
        ddl = []
        for tabela, info in self.catalogo["erp"].items():
            cols = ", ".join(f"{_ident(c)} {t}" for c, t in info["colunas"])
            ddl.append(f"CREATE TABLE {_ident(tabela)} ({cols}, PRIMARY KEY ({_ident(info['chave'])}));")
        senha = self.credenciais["erp"]["senha"]
        ddl += [
            f"CREATE ROLE {USUARIO_LEITURA} LOGIN PASSWORD '{senha}';",
            f"ALTER ROLE {USUARIO_LEITURA} SET default_transaction_read_only = on;",
            f"REVOKE ALL ON SCHEMA public FROM PUBLIC;",
            f"GRANT CONNECT ON DATABASE {BANCO} TO {USUARIO_LEITURA};",
            f"GRANT USAGE ON SCHEMA public TO {USUARIO_LEITURA};",
            f"GRANT SELECT ON ALL TABLES IN SCHEMA public TO {USUARIO_LEITURA};",
            f"COMMENT ON DATABASE {BANCO} IS 'ERP simulado com dados sintéticos (Korda); não é sistema real';",
        ]
        self._psql_admin("\n".join(ddl))

    def _subir_tms(self) -> None:
        self._gravar_estado(None)
        _docker(
            "run", "--detach", "--name", self.c_tms, "--label", f"korda.sim={self.sim_id}",
            "--network", self.rede, "--network-alias", "tms",
            "--read-only", "--tmpfs", "/tmp", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--memory", "512m", "--pids-limit", "256", "--user", f"{os.getuid()}:{os.getgid()}",
            "--mount", f"type=bind,src={self.dir_preparo},dst=/dados,readonly",
            "--mount", f"type=bind,src={self.dir_estado},dst=/estado,readonly",
            "-e", f"KORDA_SIM_TOKEN={self.credenciais['tms']['token']}",
            "-e", f"KORDA_SIM_LIMITE_RPS={self.limite_rps}",
            "-e", f"KORDA_SIM_FALHAS={json.dumps(self.falhas or {})}",
            IMAGEM_SIM,
        )
        prazo = time.monotonic() + 30
        verificar = f"import urllib.request; urllib.request.urlopen('http://127.0.0.1:{PORTA_TMS}/saude', timeout=2)"
        while _docker("exec", self.c_tms, "python", "-c", verificar, checar=False).returncode != 0:
            if time.monotonic() > prazo:
                raise ErroSimulado("TMS simulado não ficou pronto em 30 s")
            time.sleep(0.3)

    def _gravar_estado(self, dia: str | None) -> None:
        tmp = self.dir_estado / ".estado.json.tmp"
        tmp.write_text(json.dumps({"dia_atual": dia}), encoding="utf-8")
        os.replace(tmp, self.dir_estado / "estado.json")

    def _liberar(self, dia: str) -> None:
        base = self.dir_preparo / "dias" / dia
        for tabela, info in self.catalogo["erp"].items():
            arq = base / "erp" / f"{tabela}.csv"
            if arq.is_file():
                cols = ", ".join(_ident(c) for c, _ in info["colunas"])
                _docker("exec", "-i", self.c_erp, "psql", "-h", "127.0.0.1", "-U", USUARIO_ADMIN, "-d", BANCO,
                        "-v", "ON_ERROR_STOP=1", "-q", "-c",
                        f"\\copy {_ident(tabela)} ({cols}) FROM STDIN WITH (FORMAT csv, HEADER true)",
                        entrada=arq.read_bytes(), timeout=300)
        if (base / "cte").is_dir():
            destino = self.dir_entrega / "cte" / dia
            destino.mkdir(parents=True, exist_ok=True)
            for xml in sorted((base / "cte").iterdir()):
                shutil.copyfile(xml, destino / xml.name)
        self._gravar_estado(dia)  # por último: o TMS libera o dia depois do ERP e do CT-e
        self.dia_atual = dia

    def avancar(self) -> str:
        """Libera o próximo dia do replay nos três sistemas e devolve a data."""
        dias = self.catalogo["dias"]
        i = dias.index(self.dia_atual) + 1
        if i >= len(dias):
            raise ErroSimulado("não há mais dias no replay")
        self._liberar(dias[i])
        return dias[i]

    @property
    def dias_restantes(self) -> list[str]:
        dias = self.catalogo["dias"]
        return dias[dias.index(self.dia_atual) + 1:]

    def executar_na_rede(self, argv: list[str], imagem: str = IMAGEM_SIM, montagens: list[str] = (),
                         env: dict | None = None, timeout: int = 300) -> subprocess.CompletedProcess:
        """Roda um contêiner efêmero só na rede interna do ambiente (sem internet)."""
        cmd = ["run", "--rm", "--network", self.rede, "--read-only", "--tmpfs", "/tmp",
               "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
               "--user", f"{os.getuid()}:{os.getgid()}"]
        for m in montagens:
            cmd += ["--mount", m]
        for k, v in (env or {}).items():
            cmd += ["-e", f"{k}={v}"]
        return _docker(*cmd, imagem, *argv, timeout=timeout, checar=False)

    def destruir(self, apagar_diretorio: bool = True) -> None:
        for c in (self.c_tms, self.c_erp):
            _docker("rm", "--force", c, checar=False)
        _docker("network", "rm", self.rede, checar=False)
        if apagar_diretorio:
            shutil.rmtree(self.dir, ignore_errors=True)

    def __enter__(self) -> "AmbienteSimulado":
        return self.subir()

    def __exit__(self, *exc) -> None:
        self.destruir()


def _carregar(sim_id: str, raiz_runs: Path) -> AmbienteSimulado:
    """Reconstrói um ambiente já subido a partir do diretório (para a CLI)."""
    meta = json.loads((Path(raiz_runs) / f"sim-{sim_id}" / "ambiente.json").read_text(encoding="utf-8"))
    amb = AmbienteSimulado(meta["empresa"], sim_id=sim_id, raiz_runs=raiz_runs,
                           permitir_reservada=meta["empresa"] == EMPRESA_RESERVADA)
    amb.catalogo = json.loads((amb.dir_preparo / "catalogo.json").read_text(encoding="utf-8"))
    amb.credenciais = json.loads((amb.dir / "credenciais.json").read_text(encoding="utf-8"))
    amb.dia_atual = json.loads((amb.dir_estado / "estado.json").read_text(encoding="utf-8"))["dia_atual"]
    amb._senha_admin = meta["senha_admin"]
    return amb


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Ambiente simulado do cliente (dados sintéticos, replay).")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("subir")
    s.add_argument("--empresa", required=True)
    s.add_argument("--dias-iniciais", type=int)
    s.add_argument("--sem-mudanca", action="store_true")
    s.add_argument("--medir-reservada", action="store_true", help="permite a 03_reservada (só medição)")
    for nome in ("avancar", "destruir", "status"):
        sub.add_parser(nome).add_argument("--id", required=True)
    p.add_argument("--runs", type=Path, default=RAIZ_REPO / "runs")
    a = p.parse_args(argv)
    try:
        if a.cmd == "subir":
            amb = AmbienteSimulado(a.empresa, raiz_runs=a.runs, dias_iniciais=a.dias_iniciais,
                                   mudanca=None if a.sem_mudanca else "ultimo",
                                   permitir_reservada=a.medir_reservada).subir()
            meta = amb.dir / "ambiente.json"
            meta.touch(mode=0o600)
            meta.write_text(json.dumps({"empresa": amb.empresa, "senha_admin": amb._senha_admin}), encoding="utf-8")
            print(json.dumps({"id": amb.sim_id, "rede": amb.rede, "dia_atual": amb.dia_atual,
                              "dias_restantes": amb.dias_restantes,
                              "credenciais": str(amb.dir / "credenciais.json")}, ensure_ascii=False))
            return 0
        amb = _carregar(a.id, a.runs)
        if a.cmd == "avancar":
            print(amb.avancar())
        elif a.cmd == "status":
            print(json.dumps({"dia_atual": amb.dia_atual, "dias_restantes": amb.dias_restantes}))
        else:
            amb.destruir()
        return 0
    except ErroSimulado as e:
        print(f"erro: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
