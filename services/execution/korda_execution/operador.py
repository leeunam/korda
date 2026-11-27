"""Ponte local entre revisões da entrevista, aprovação do plano e execução na demo 01."""

import fcntl
import hashlib
import json
import math
import os
import re
import stat
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from jsonschema import ValidationError
from services.execution.pipeline.projeto.ingerir import REGRAS_SUPORTADAS, validar_regras
from services.planning import korda_planning as planejamento

from .aprovacoes import ErroAprovacao, Registro, _evento, _invalidar, _json, _resumo_run as consultar_run
from .artefatos import LIMITES, LIMITE_PACOTE, PACOTE, _diretorio, entregar
from .harness.config import ConfigHarness
from .worker import executar

ARQUIVOS = {**LIMITES, PACOTE: LIMITE_PACOTE}
MAX_CONTEXTO = 4 * 1024**2
ID_PROJETO = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
HASH = re.compile(r"[a-f0-9]{64}")
KPIS = ("custo_frete_por_entrega", "otif_pct", "ocupacao_pct")


class ErroOperador(ValueError):
    def __init__(self, status, mensagem):
        self.status = status
        super().__init__(mensagem)


def _arquivo(pasta, nome, limite):
    with _diretorio(pasta) as pai:
        fd = os.open(nome, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=pai)
        with os.fdopen(fd, "rb") as entrada:
            st = os.fstat(fd)
            if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or not 0 < st.st_size <= limite:
                raise ErroOperador(409, "O arquivo esperado está indisponível ou excede o limite.")
            dados = entrada.read(limite + 1)
            if len(dados) != st.st_size:
                raise ErroOperador(409, "O arquivo mudou durante a leitura.")
            return dados


class _SemRedirecionamento(HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


class FonteEntrevista:
    def __init__(self, *, exports=None, url=None, token=None):
        if bool(exports) == bool(url):
            raise ValueError("Configure uma fonte de entrevista, por HTTP ou diretório de exportações.")
        self.exports = Path(exports).resolve() if exports else None
        self.url = url.rstrip("/") if url else None
        self.token = token
        if self.url:
            local = urlsplit(self.url)
            if (not token or not local.hostname or local.username or local.password or local.query or local.fragment
                    or not (local.scheme == "https" or local.scheme == "http" and local.hostname in ("localhost", "127.0.0.1", "::1"))):
                raise ValueError("O serviço de entrevista exige URL HTTPS ou loopback e token de projeto.")

    def ler(self, projeto, revisao=None):
        if not ID_PROJETO.fullmatch(projeto) or revisao is not None and (type(revisao) is not int or revisao < 0):
            raise ErroOperador(400, "Identificador de projeto ou revisão inválido.")
        try:
            if self.exports is not None:
                pasta = self.exports / projeto
                if revisao is None:
                    with _diretorio(pasta) as pai:
                        valores = [int(nome[:-5]) for nome in os.listdir(pai) if re.fullmatch(r"(?:0|[1-9][0-9]{0,12})\.json", nome)]
                    if not valores:
                        raise ErroOperador(404, "Nenhuma revisão exportada para este projeto.")
                    revisao = max(valores)
                dados = _arquivo(pasta, f"{revisao}.json", MAX_CONTEXTO)
            else:
                caminho = f"/v1/projects/{projeto}/context/revisions/{'latest' if revisao is None else revisao}/export"
                req = Request(self.url + caminho, headers={"Authorization": "Bearer " + self.token, "Accept": "application/json"})
                with build_opener(ProxyHandler({}), _SemRedirecionamento).open(req, timeout=8) as resposta:
                    dados = resposta.read(MAX_CONTEXTO + 1)
                    if len(dados) > MAX_CONTEXTO:
                        raise ErroOperador(502, "Exportação de entrevista acima do limite.")
            doc = json.loads(dados)
        except HTTPError as e:
            e.close()
            raise ErroOperador(404 if e.code == 404 else 502, "Serviço de entrevista não forneceu a revisão.") from None
        except FileNotFoundError:
            raise ErroOperador(404, "Revisão de entrevista não encontrada.") from None
        except (OSError, URLError, UnicodeError, json.JSONDecodeError, RecursionError):
            raise ErroOperador(502, "Falha ao ler a exportação da entrevista.") from None
        if (not isinstance(doc, dict) or doc.get("project_id") != projeto or doc.get("synthetic") is not True or doc.get("schema_version") != "0.2.0"
                or type(doc.get("revision")) is not int or doc["revision"] < 0 or revisao is not None and doc["revision"] != revisao):
            raise ErroOperador(409, "O projeto, a revisão ou o cenário sintético da fonte diverge.")
        return doc


DDL = """
CREATE TABLE IF NOT EXISTS operador_execucoes (
    run_id TEXT PRIMARY KEY, plano_id INTEGER NOT NULL REFERENCES planos(id), anterior TEXT NOT NULL,
    situacao TEXT NOT NULL, UNIQUE(plano_id, anterior)
);
"""


class Operador:
    """Um processo operador por raiz. O registro SQLite permanece a autoridade dos dois gates."""

    def __init__(self, projeto, *, raiz, fonte, fontes, destino="painel-demo", proposta=None, executar_run=executar):
        if not ID_PROJETO.fullmatch(projeto) or not ID_PROJETO.fullmatch(destino):
            raise ValueError("Projeto ou destino local inválido.")
        self.projeto, self.fonte, self.destino = projeto, fonte, destino
        self.raiz, self.fontes = Path(raiz).resolve(), Path(fontes).resolve()
        self.proposta, self.executar_run = proposta, executar_run
        self.raiz.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.trava = (self.raiz / "operador.lock").open("a")
        try:
            fcntl.flock(self.trava, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.trava.close()
            raise ValueError("Já existe um operador usando esta raiz.") from None
        self.registro = Registro(self.raiz / "controle")
        self.mutex = threading.RLock()
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="korda-worker")
        with closing(self.registro._conectar()) as db:
            db.executescript(DDL)
        # Após reiniciar, não invoque novamente uma execução cujo resultado pode já existir.
        with self.registro._escrita() as db:
            for (run,) in db.execute("SELECT run_id FROM operador_execucoes WHERE situacao='enfileirada'").fetchall():
                linha = db.execute("SELECT state,plano_id FROM runs WHERE run_id=?", (run,)).fetchone()
                if linha and linha["state"] == "executando":
                    db.execute("UPDATE runs SET state='falhou' WHERE run_id=?", (run,))
                    _evento(db, linha["plano_id"], run, "execucao_interrompida")
                db.execute("UPDATE operador_execucoes SET situacao='falhou' WHERE run_id=?", (run,))

    def fechar(self):
        self.pool.shutdown(wait=True)
        self.trava.close()

    def _ver_fonte(self, revision):
        bruto = self.fonte.ler(self.projeto, revision)
        try:
            p = planejamento.preparar_contexto(bruto)
        except (ValueError, ValidationError, KeyError, TypeError):
            raise ErroOperador(422, "A exportação não satisfaz o contrato de planejamento.") from None
        if p["project_id"] != self.projeto or (revision is not None and p["revision"] != revision) or bruto.get("synthetic") is not True:
            raise ErroOperador(409, "A identidade da revisão recebida diverge do projeto.")
        resumo = {k: p[k] for k in ("revision", "estado", "regras", "pendencias", "lacunas")}
        resumo.update(context_id=f"whatsapp:{self.projeto}", sha256=p["contexto_sha256"])
        contexto = p.get("contexto_planejamento")
        if contexto is not None and resumo["estado"] == "pronto":
            valores = {chave: regra["value"] for chave, regra in resumo["regras"].items()}
            try:
                validar_regras(valores)
            except ValueError:
                resumo["estado"] = "pendente"
                for chave, esperado in REGRAS_SUPORTADAS.items():
                    valor = valores.get(chave)
                    if type(valor) is not type(esperado) or valor != esperado:
                        regra = resumo["regras"].get(chave, {})
                        resumo["pendencias"].append({
                            "campo": chave, "pergunta": "Implementação pendente no cenário 01 para a regra confirmada.",
                            "claim_ids": [], "evidence_ids": regra.get("evidence_ids", []),
                        })
                contexto = None
        return resumo, contexto

    def fonte_atual(self, revision=None):
        return self._ver_fonte(revision)[0]

    def importar(self, revision, digest):
        if type(revision) is not int or revision < 0 or not isinstance(digest, str) or not HASH.fullmatch(digest):
            raise ErroOperador(400, "Informe o número e o SHA-256 da revisão conferida.")
        fonte, contexto = self._ver_fonte(revision)
        if fonte["sha256"] != digest:
            raise ErroOperador(409, "O conteúdo da revisão diverge do hash conferido.")
        plano = None
        if contexto is not None and fonte["estado"] == "pronto":
            try:
                plano = planejamento.gerar_plano(contexto, dataset="01_demo", destino=self.destino, custo_estimado_centavos=0,
                                                  nivel_ingestao="n1" if self.proposta is not None else "n0",
                                                  proposta_ingestao=self.proposta)
                planejamento.validar_plano(plano)
            except (ValueError, ValidationError):
                raise ErroOperador(422, "O contexto e a ingestão configurada não produzem um plano válido.") from None
        with self.mutex:
            with self.registro._escrita() as db:
                atual = db.execute("SELECT * FROM operador_fontes WHERE projeto=?", (self.projeto,)).fetchone()
                if atual and (revision < atual["revisao"] or (revision == atual["revisao"] and digest != atual["hash"])):
                    raise ErroOperador(409, "A revisão importada seria anterior ou contraditória.")
                if plano:
                    plano_id = self.registro._registrar_validado(db, plano)["generation"]
                else:
                    plano_id = None
                    anterior = db.execute("SELECT id, decisao FROM planos WHERE project_id=? ORDER BY id DESC LIMIT 1",
                                          (self.projeto,)).fetchone()
                    if anterior and anterior["decisao"] != "contexto_substituido":
                        _invalidar(db, anterior["id"])
                        db.execute("UPDATE planos SET decisao='contexto_substituido' WHERE id=?", (anterior["id"],))
                        _evento(db, anterior["id"], None, "contexto_substituido")
                db.execute("INSERT OR REPLACE INTO operador_fontes VALUES(?,?,?,?,?)",
                           (self.projeto, revision, digest, _json(fonte), plano_id))
            return self.estado()

    def _linhas(self, db):
        fonte = db.execute("SELECT * FROM operador_fontes WHERE projeto=?", (self.projeto,)).fetchone()
        plano = run = None
        if fonte and fonte["plano_id"]:
            plano = db.execute("SELECT * FROM planos WHERE project_id=? ORDER BY id DESC LIMIT 1", (self.projeto,)).fetchone()
            if plano["id"] != fonte["plano_id"]:
                raise ErroOperador(409, "O plano ativo mudou fora do painel. Confira a revisão e importe novamente.")
            run = db.execute("SELECT * FROM operador_execucoes WHERE plano_id=? ORDER BY rowid DESC LIMIT 1",
                             (plano["id"],)).fetchone()
        return fonte, plano, run

    def _arquivo_run(self, run, nome, promovido):
        manifesto = run.get("manifesto") or {}
        info = manifesto.get("arquivos", {}).get(nome)
        if not info or nome not in ARQUIVOS:
            raise ErroOperador(404, "Arquivo não consta no manifesto desta execução.")
        pasta = (self.raiz / "entregas" / run["destination"] / run["run_id"] if promovido
                 else self.raiz / "revisao" / run["run_id"] / "resultados")
        dados = _arquivo(pasta, nome, ARQUIVOS[nome])
        if len(dados) != info["bytes"] or hashlib.sha256(dados).hexdigest() != info["sha256"]:
            raise ErroOperador(409, "Integridade do arquivo difere do manifesto congelado.")
        return dados

    def _resumo_run(self, db, fila, plano):
        try:
            run = consultar_run(db, fila["run_id"])
        except ErroAprovacao:
            run = {"run_id": fila["run_id"], "state": fila["situacao"], "plan_version": plano["plan_version"],
                   "destination": plano["destination"], "manifesto": None}
        resumo = {k: run[k] for k in ("run_id", "state", "plan_version", "destination")}
        resumo.update(kpis=None, avaliacao=None, arquivos=[])
        pasta = self.raiz / "revisao" / run["run_id"]
        try:
            laudo = None if run["state"] in {"enfileirada", "executando"} else json.loads(_arquivo(pasta, "avaliacao.json", 1024**2))
        except FileNotFoundError:
            laudo = None
        if laudo is not None:
            resumo["avaliacao"] = {k: laudo.get(k) for k in ("aprovado", "classe", "divergencias", "comparados")}
        if run["manifesto"]:
            bruto = json.loads(self._arquivo_run(run, "kpis.json", run["state"] == "promovida"))["kpis"]
            if any(k not in bruto or bruto[k] is not None and
                   (type(bruto[k]) not in (int, float) or not math.isfinite(bruto[k])) for k in KPIS):
                raise ErroOperador(409, "Indicadores fora do contrato do cenário 01.")
            resumo["kpis"] = {k: bruto[k] for k in KPIS}
        if run["state"] == "promovida":
            resumo["arquivos"] = sorted(run["manifesto"]["arquivos"])
        return resumo

    def estado(self):
        with self.mutex, closing(self.registro._conectar()) as db:
            db.execute("BEGIN")
            fonte, linha, fila = self._linhas(db)
            resumo = {"project_id": self.projeto, "source": json.loads(fonte["resumo"]) if fonte else None,
                      "plan": None, "run": None}
            if linha:
                p = json.loads(linha["plano"])
                resumo["plan"] = {k: p[k] for k in ("plan_version", "context_id", "context_revision", "destination",
                                                      "cost_estimate_brl_cents", "metrics", "rules", "gaps")}
                resumo["plan"].update(state=linha["decisao"] or p["state"], context_sha256=fonte["hash"],
                                      ingestion_level=p["ingestion"]["level"])
                if fila:
                    resumo["run"] = self._resumo_run(db, fila, p)
            return resumo

    def _efetuar_run(self, plano, run_id):
        try:
            self.executar_run(self.registro, plano, run_id, raiz=self.raiz, fontes=self.fontes,
                              cfg=ConfigHarness.de_ambiente({"KORDA_EXECUTOR": "roteirizado"}))
        except Exception:
            with self.registro._escrita() as db:
                linha = db.execute("SELECT state,plano_id FROM runs WHERE run_id=?", (run_id,)).fetchone()
                if linha and linha["state"] == "executando":
                    db.execute("UPDATE runs SET state='falhou' WHERE run_id=?", (run_id,))
                    _evento(db, linha["plano_id"], run_id, "falhou")
                db.execute("UPDATE operador_execucoes SET situacao='falhou' WHERE run_id=?", (run_id,))
        else:
            with self.registro._escrita() as db:
                db.execute("UPDATE operador_execucoes SET situacao='concluida' WHERE run_id=?", (run_id,))

    def acao(self, nome, corpo):
        if not isinstance(corpo, dict):
            raise ErroOperador(400, "Envie um objeto JSON.")
        campos = {"importar": {"revision", "context_sha256"}, "decidir-plano": {"plan_version", "aprovar", "pessoa"},
                  "executar": {"plan_version"}, "decidir-entrega": {"plan_version", "run_id", "aprovar", "pessoa"},
                  "promover": {"plan_version", "run_id"}}
        exigidos = campos.get(nome)
        if exigidos is None:
            raise ErroOperador(404, "Ação desconhecida.")
        if not exigidos <= corpo.keys() or corpo.keys() - exigidos - ({"retry_run_id"} if nome == "executar" else set()):
            raise ErroOperador(400, "Campos do pedido inválidos.")
        if nome == "importar":
            return self.importar(corpo["revision"], corpo["context_sha256"])
        if nome.startswith("decidir") and (type(corpo["aprovar"]) is not bool or not isinstance(corpo["pessoa"], str)
                                          or not 1 <= len(corpo["pessoa"].strip()) <= 150):
            raise ErroOperador(400, "A decisão exige uma pessoa identificada e aprovação booleana.")
        with self.mutex, closing(self.registro._conectar()) as db:
            _, linha, fila = self._linhas(db)
            if not linha or linha["plan_version"] != corpo["plan_version"]:
                raise ErroOperador(409, "Esta versão do plano não está ativa para a revisão importada.")
            plano = json.loads(linha["plano"])
            versao = linha["plan_version"]
            if nome == "decidir-plano":
                self.registro.decidir_plano(self.projeto, versao, corpo["pessoa"], corpo["aprovar"])
            elif nome == "executar":
                if linha["decisao"] != "plano_aprovado":
                    raise ErroOperador(409, "É necessária a primeira aprovação humana para este plano.")
                anterior = corpo.get("retry_run_id", "")
                if not isinstance(anterior, str) or anterior and not re.fullmatch(r"[a-f0-9]{32}", anterior):
                    raise ErroOperador(400, "Identificador da tentativa anterior inválido.")
                if anterior:
                    if not fila or (fila["run_id"] != anterior and fila["anterior"] != anterior):
                        raise ErroOperador(409, "A tentativa anterior mudou.")
                    if fila["run_id"] == anterior and self._resumo_run(db, fila, plano)["state"] != "falhou":
                        raise ErroOperador(409, "Apenas uma execução com falha pode ser repetida.")
                if fila is None or anterior and anterior == fila["run_id"]:
                    run_id = uuid.uuid4().hex
                    with self.registro._escrita() as tx:
                        tx.execute("INSERT INTO operador_execucoes VALUES(?,?,?,'enfileirada')", (run_id, linha["id"], anterior))
                    self.pool.submit(self._efetuar_run, plano, run_id)
            else:
                if not fila or fila["run_id"] != corpo["run_id"]:
                    raise ErroOperador(409, "A execução informada não é a do plano ativo.")
                if nome == "decidir-entrega":
                    self.registro.decidir_entrega(fila["run_id"], corpo["pessoa"], corpo["aprovar"])
                elif self.registro.consultar(fila["run_id"])["state"] != "promovida":
                    entregar(self.registro, self.raiz, fila["run_id"], plano["destination"])
            return self.estado()

    def baixar(self, run_id, nome):
        with self.mutex, closing(self.registro._conectar()) as db:
            _, _, fila = self._linhas(db)
            if not fila or fila["run_id"] != run_id or nome not in ARQUIVOS:
                raise ErroOperador(404, "Arquivo desconhecido para este projeto.")
            run = self.registro.consultar(run_id)
            if run["state"] != "promovida":
                raise ErroOperador(409, "A publicação exige aprovação humana e promoção.")
            return self._arquivo_run(run, nome, True)
