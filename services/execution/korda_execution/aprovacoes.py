"""Registro local do operador. O agente e o contêiner não recebem acesso ao banco."""

import json
import re
import sqlite3
import sys
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path

# A CLI da execução também funciona a partir de services/execution.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "planning"))
from korda_planning import validar_plano


class ErroAprovacao(ValueError):
    """A operação solicitada não está autorizada no estado atual."""


DDL = """
CREATE TABLE IF NOT EXISTS planos (
    id INTEGER PRIMARY KEY,
    project_id TEXT NOT NULL,
    context_id TEXT NOT NULL,
    context_revision INTEGER NOT NULL,
    plan_version TEXT NOT NULL,
    plano TEXT NOT NULL,
    decisao TEXT
);
CREATE TABLE IF NOT EXISTS operador_fontes (
    projeto TEXT PRIMARY KEY, revisao INTEGER NOT NULL, hash TEXT NOT NULL, resumo TEXT NOT NULL, plano_id INTEGER REFERENCES planos(id)
);
CREATE INDEX IF NOT EXISTS idx_planos_projeto ON planos(project_id, id);
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    plano_id INTEGER NOT NULL REFERENCES planos(id),
    state TEXT NOT NULL,
    manifesto TEXT
);
CREATE TABLE IF NOT EXISTS auditoria (
    id INTEGER PRIMARY KEY,
    plano_id INTEGER NOT NULL REFERENCES planos(id),
    run_id TEXT REFERENCES runs(run_id),
    event TEXT NOT NULL,
    actor TEXT,
    ts TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_auditoria_plano ON auditoria(plano_id, id);
"""


def _json(objeto):
    return json.dumps(objeto, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))


def _evento(db, plano_id, run_id, evento, pessoa=None):
    instante = datetime.now(timezone.utc).isoformat()
    db.execute("INSERT INTO auditoria(plano_id,run_id,event,actor,ts) VALUES(?,?,?,?,?)",
               (plano_id, run_id, evento, pessoa, instante))


def _revisor(pessoa, aprovar):
    if not isinstance(pessoa, str) or not pessoa.strip() or type(aprovar) is not bool:
        raise ErroAprovacao("identifique a pessoa e informe uma decisão booleana")
    return pessoa.strip()


def _atual(db, project_id, versao):
    linha = db.execute("SELECT * FROM planos WHERE project_id=? ORDER BY id DESC LIMIT 1", (project_id,)).fetchone()
    if linha is None or linha["plan_version"] != versao:
        raise ErroAprovacao("versão do plano não está ativa para este projeto")
    return linha


def _resumo_plano(linha):
    plano = json.loads(linha["plano"])
    return {
        "project_id": linha["project_id"], "plan_version": linha["plan_version"], "generation": linha["id"],
        "context_revision": linha["context_revision"], "state": linha["decisao"] or plano["state"],
    }


def _invalidar(db, plano_id):
    linhas = db.execute("""
        SELECT run_id FROM runs WHERE plano_id=?
        AND state IN ('executando','aguardando_aprovacao_entrega','entrega_autorizada','entrega_rejeitada')
    """, (plano_id,)).fetchall()
    for linha in linhas:
        db.execute("UPDATE runs SET state='invalidada' WHERE run_id=?", (linha["run_id"],))
        _evento(db, plano_id, linha["run_id"], "invalidada")


def _run(db, run_id):
    linha = db.execute("""
        SELECT r.*, p.project_id, p.plan_version, p.plano, p.decisao
        FROM runs r JOIN planos p ON p.id=r.plano_id WHERE run_id=?
    """, (run_id,)).fetchone()
    if linha is None:
        raise ErroAprovacao("execução desconhecida")
    return linha


def _resumo_run(db, run_id):
    linha = _run(db, run_id)
    eventos = db.execute("""
        SELECT event, actor, ts FROM auditoria WHERE plano_id=? AND (run_id=? OR run_id IS NULL) ORDER BY id
    """, (linha["plano_id"], run_id))
    return {
        "run_id": run_id, "project_id": linha["project_id"], "plan_version": linha["plan_version"],
        "state": linha["state"], "destination": json.loads(linha["plano"])["destination"],
        "manifesto": json.loads(linha["manifesto"]) if linha["manifesto"] is not None else None,
        "history": [dict(evento) for evento in eventos],
    }


class Registro:
    def __init__(self, raiz: Path):
        raiz = Path(raiz)
        raiz.mkdir(parents=True, exist_ok=True)
        self.banco = raiz / "registro.sqlite3"
        with closing(self._conectar()) as db:
            db.executescript(DDL)

    def _conectar(self):
        db = sqlite3.connect(self.banco, timeout=30, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        return db

    @contextmanager
    def _escrita(self):
        with closing(self._conectar()) as db:
            with db:
                db.execute("BEGIN IMMEDIATE")
                yield db

    def registrar(self, plano):
        """Ativa exatamente este documento. Reenviar a versão já ativa é idempotente."""
        plano = json.loads(_json(plano))
        validar_plano(plano)
        with self._escrita() as db:
            # Uma raiz usada pelo painel tem uma revisão de entrevista congelada.
            # Uma CLI na mesma raiz deve respeitar a mesma revogação.
            vinculo = db.execute("SELECT * FROM operador_fontes WHERE projeto=?", (plano["project_id"],)).fetchone()
            if vinculo:
                origem = json.loads(vinculo["resumo"])
                referencia = f"whatsapp/v0.2.0:{vinculo['revisao']}:{vinculo['hash']}"
                if (origem["estado"] != "pronto" or plano["context_id"] != origem["context_id"]
                        or plano["context_revision"] != vinculo["revisao"] or not plano["sources"]
                        or any(f["version"] != referencia for f in plano["sources"])):
                    raise ErroAprovacao("o plano diverge da revisão de entrevista ativa neste registro")
            return self._registrar_validado(db, plano)

    def _registrar_validado(self, db, plano):
        """Usa a mesma transação para registrar o plano e, no painel, sua revisão de origem."""
        projeto = plano["project_id"]
        atual = db.execute("SELECT * FROM planos WHERE project_id=? ORDER BY id DESC LIMIT 1", (projeto,)).fetchone()
        if atual and atual["plan_version"] == plano["plan_version"] and atual["decisao"] != "contexto_substituido":
            return _resumo_plano(atual)
        maior = db.execute("SELECT MAX(context_revision) FROM planos WHERE project_id=? AND context_id=?",
                           (projeto, plano["context_id"])).fetchone()[0]
        if maior is not None and plano["context_revision"] < maior:
            raise ErroAprovacao("revisão de contexto anterior à já registrada")
        if atual:
            _invalidar(db, atual["id"])
            _evento(db, atual["id"], None, "versao_substituida")
        cursor = db.execute("""
            INSERT INTO planos(project_id,context_id,context_revision,plan_version,plano) VALUES(?,?,?,?,?)
        """, (projeto, plano["context_id"], plano["context_revision"], plano["plan_version"], _json(plano)))
        _evento(db, cursor.lastrowid, None, "plano_registrado")
        return _resumo_plano(_atual(db, projeto, plano["plan_version"]))

    def decidir_plano(self, project_id, plan_version, pessoa, aprovar: bool):
        pessoa = _revisor(pessoa, aprovar)
        with self._escrita() as db:
            linha = _atual(db, project_id, plan_version)
            if linha["decisao"] == "contexto_substituido":
                raise ErroAprovacao("a revisão de entrevista deste plano já foi substituída")
            plano = json.loads(linha["plano"])
            if aprovar and plano["state"] != "aguardando_aprovacao":
                raise ErroAprovacao("o plano ainda está em rascunho")
            decisao = "plano_aprovado" if aprovar else "plano_rejeitado"
            if not aprovar:
                _invalidar(db, linha["id"])
            db.execute("UPDATE planos SET decisao=? WHERE id=?", (decisao, linha["id"]))
            _evento(db, linha["id"], None, decisao, pessoa)
            return _resumo_plano(_atual(db, project_id, plan_version))

    def iniciar(self, project_id, plan_version, run_id):
        if not isinstance(run_id, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", run_id):
            raise ErroAprovacao("run_id inválido")
        with self._escrita() as db:
            linha = _atual(db, project_id, plan_version)
            plano = json.loads(linha["plano"])
            if linha["decisao"] != "plano_aprovado" or plano["state"] != "aguardando_aprovacao":
                raise ErroAprovacao("execução exige aprovação humana da versão ativa")
            if plano["destination"] is None or plano["cost_estimate_brl_cents"] is None:
                raise ErroAprovacao("confirme o destino e a estimativa de custo em uma nova versão do plano")
            if db.execute("SELECT 1 FROM runs WHERE run_id=?", (run_id,)).fetchone():
                raise ErroAprovacao("run_id já reservado")
            db.execute("INSERT INTO runs(run_id,plano_id,state) VALUES(?,?,'executando')", (run_id, linha["id"]))
            _evento(db, linha["id"], run_id, "executando")
            return _resumo_run(db, run_id)

    def finalizar(self, run_id, *, aprovado: bool, manifesto: dict | None = None):
        """O worker confiável informa o resultado dos testes e o inventário dos artefatos."""
        if type(aprovado) is not bool or (aprovado and (not isinstance(manifesto, dict) or not manifesto)):
            raise ErroAprovacao("execução validada exige manifesto não vazio")
        if not aprovado and manifesto is not None:
            raise ErroAprovacao("uma execução com falha não produz manifesto para promoção")
        texto = _json(manifesto) if manifesto is not None else None
        with self._escrita() as db:
            linha = _run(db, run_id)
            if linha["state"] != "executando":
                raise ErroAprovacao("execução não está ativa")
            estado = "aguardando_aprovacao_entrega" if aprovado else "falhou"
            db.execute("UPDATE runs SET state=?, manifesto=? WHERE run_id=?", (estado, texto, run_id))
            _evento(db, linha["plano_id"], run_id, estado)
            return _resumo_run(db, run_id)

    def decidir_entrega(self, run_id, pessoa, aprovar: bool):
        pessoa = _revisor(pessoa, aprovar)
        with self._escrita() as db:
            linha = _run(db, run_id)
            if linha["state"] not in {"aguardando_aprovacao_entrega", "entrega_autorizada", "entrega_rejeitada"}:
                raise ErroAprovacao("decisão de entrega exige uma execução validada na versão ativa")
            estado = "entrega_autorizada" if aprovar else "entrega_rejeitada"
            db.execute("UPDATE runs SET state=? WHERE run_id=?", (estado, run_id))
            _evento(db, linha["plano_id"], run_id, estado, pessoa)
            return _resumo_run(db, run_id)

    @staticmethod
    def _entrega(db, run_id, destino):
        linha = _run(db, run_id)
        if linha["state"] != "entrega_autorizada" or linha["decisao"] != "plano_aprovado":
            raise ErroAprovacao("entrega exige segunda aprovação para esta execução")
        if json.loads(linha["plano"])["destination"] != destino:
            raise ErroAprovacao("destino diverge da versão autorizada")
        return linha

    def autorizar_destino(self, run_id, destino):
        """Consulta pontual para revisão. A publicação deve usar promover()."""
        with closing(self._conectar()) as db:
            return json.loads(self._entrega(db, run_id, destino)["manifesto"])

    @contextmanager
    def promover(self, run_id, destino):
        """Serializa autorização, escrita externa pelo host e registro de promoção."""
        with self._escrita() as db:
            linha = self._entrega(db, run_id, destino)
            yield json.loads(linha["manifesto"])
            db.execute("UPDATE runs SET state='promovida' WHERE run_id=?", (run_id,))
            _evento(db, linha["plano_id"], run_id, "promovida")

    def plano_da_execucao(self, run_id):
        """Somente leitura: o documento exato da versão que esta execução seguiu (para a entrega)."""
        with closing(self._conectar()) as db:
            return json.loads(_run(db, run_id)["plano"])

    def consultar(self, run_id):
        with closing(self._conectar()) as db:
            db.execute("BEGIN")
            return _resumo_run(db, run_id)
