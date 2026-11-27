"""PostgreSQL persistence. ProjectSession owns one transaction and project lock.

Provider calls belong outside this module. ``enqueue`` must defer its job using
the supplied connection, so a webhook cannot commit without its durable work.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from hashlib import sha256
from hmac import compare_digest
import re
from typing import Callable, Iterator
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb


class NotFound(LookupError):
    pass


class StaleRevision(ValueError):
    pass


class UnknownParticipant(PermissionError):
    pass


def _id() -> str:
    return str(uuid4())


def _time(value) -> datetime:
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, (int, float)) or (isinstance(value, str) and value.isdecimal()):
        result = datetime.fromtimestamp(float(value), tz=timezone.utc)
    else:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("timestamps must include a timezone")
    return result.astimezone(timezone.utc)


class Repository:
    def __init__(self, dsn: str):
        self.dsn = dsn

    def connect(self):
        return psycopg.connect(self.dsn, row_factory=dict_row)

    @contextmanager
    def transaction(self, project_id: str) -> Iterator[ProjectSession]:
        with self.connect() as conn:
            conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (project_id,))
            session = ProjectSession(conn, project_id)
            session.project()
            yield session

    def health(self) -> bool:
        with self.connect() as conn:
            conn.execute("SELECT 1 FROM ctx_projects LIMIT 1")
        return True

    def create_project(self, project_id: str, name: str, phone_number_id: str,
                       token: str, required_topics: dict[str, str]) -> dict:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", project_id):
            raise ValueError("project_id must contain 1-80 letters, digits, underscores or hyphens")
        if not all((project_id, name, phone_number_id)) or len(token) < 24:
            raise ValueError("project identity is required and token must contain at least 24 characters")
        if not isinstance(required_topics, dict) or any(
            not isinstance(k, str) or not k or not isinstance(v, str) or not v
            for k, v in required_topics.items()
        ):
            raise ValueError("required_topics maps topic IDs to authorized roles")
        with self.connect() as conn:
            row = conn.execute(
                """INSERT INTO ctx_projects(id,name,phone_number_id,token_hash,required_topics)
                   VALUES (%s,%s,%s,%s,%s) RETURNING id,name,phone_number_id,required_topics,
                   interview_status,cutoff_sequence,current_revision,model_calls,created_at""",
                (project_id, name, phone_number_id, sha256(token.encode()).hexdigest(), Jsonb(required_topics)),
            ).fetchone()
            return row

    def get_project(self, project_id: str) -> dict:
        with self.transaction(project_id) as session:
            return session.project()

    def authenticate(self, project_id: str, token: str) -> bool:
        with self.connect() as conn:
            row = conn.execute("SELECT token_hash FROM ctx_projects WHERE id=%s", (project_id,)).fetchone()
        # Hash before comparing, including unknown projects; never store bearer tokens.
        supplied = sha256(token.encode()).hexdigest()
        return compare_digest(row["token_hash"] if row else "0" * 64, supplied) and row is not None

    def add_participant(self, project_id: str, wa_id: str, name: str, role: str | list[str]) -> dict:
        from .participants import normalize_roles
        roles = normalize_roles(role)
        if not all((wa_id, name, role)):
            raise ValueError("participant identity and role are required")
        with self.transaction(project_id) as session:
            return session.conn.execute(
                """INSERT INTO ctx_participants(id,project_id,wa_id,name,role,roles)
                   VALUES (%s,%s,%s,%s,%s,%s) RETURNING *""", (_id(), project_id, wa_id, name, roles[0], roles)
            ).fetchone()

    def get_participant(self, phone_number_id: str, wa_id: str) -> dict | None:
        with self.connect() as conn:
            return conn.execute(
                """SELECT p.* FROM ctx_participants p JOIN ctx_projects j ON j.id=p.project_id
                   WHERE j.phone_number_id=%s AND p.wa_id=%s""", (phone_number_id, wa_id)
            ).fetchone()

    def read_revision(self, project_id: str, revision: int | None = None) -> dict | None:
        # Immutable snapshots are safe to read under MVCC while a model holds the writer lock.
        with self.connect() as conn:
            row = conn.execute(
                """SELECT r.document FROM ctx_revisions r JOIN ctx_projects p ON p.id=r.project_id
                   WHERE p.id=%s AND r.revision=COALESCE(%s,p.current_revision)""", (project_id, revision)
            ).fetchone()
        return row["document"] if row else None

    def ingest(self, event: dict, enqueue: Callable[[psycopg.Connection, str], None]) -> dict:
        """Insert one registered participant's message and enqueue atomically.

        Do not take the worker's advisory lock: model/provider latency must not
        block webhook acknowledgements. Receipt order is the database sequence.
        """
        kind = event["kind"]
        if kind not in {"text", "audio"}:
            raise ValueError("unsupported message kind")
        if kind == "text" and not isinstance(event.get("text"), str):
            raise ValueError("text message requires text")
        if kind == "audio" and not event.get("media_id"):
            raise ValueError("audio message requires media_id")
        with self.connect() as conn:
            participant = conn.execute(
                """SELECT p.*,j.interview_status FROM ctx_participants p
                   JOIN ctx_projects j ON p.project_id=j.id
                   WHERE j.phone_number_id=%s AND p.wa_id=%s""",
                (event["phone_number_id"], event["wa_id"]),
            ).fetchone()
            if participant is None:
                raise UnknownParticipant("participant is not registered for this phone number")
            timestamp = _time(event["timestamp"])
            row = conn.execute(
                """INSERT INTO ctx_inbox(id,project_id,participant_id,phone_number_id,message_id,
                   sent_at,kind,original_text,media_id,mime_type)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (phone_number_id,message_id) DO NOTHING RETURNING *""",
                (_id(), participant["project_id"], participant["id"], event["phone_number_id"],
                 event["message_id"], timestamp, kind, event.get("text"), event.get("media_id"), event.get("mime_type")),
            ).fetchone()
            if row is None:
                row = conn.execute(
                    "SELECT * FROM ctx_inbox WHERE phone_number_id=%s AND message_id=%s",
                    (event["phone_number_id"], event["message_id"]),
                ).fetchone()
                return {**row, "inserted": False}
            conn.execute(
                """UPDATE ctx_participants SET last_customer_at=GREATEST(last_customer_at,%s)
                   WHERE id=%s""", (timestamp, participant["id"]),
            )
            enqueue(conn, participant["project_id"])
            return {**row, "inserted": True}

    def record_delivery(self, phone_number_id: str, message_id: str, status: str,
                        timestamp, error: str | None = None) -> bool:
        if status not in {"sent", "delivered", "read", "failed"}:
            raise ValueError("unsupported delivery status")
        with self.connect() as conn:
            project = conn.execute("SELECT id FROM ctx_projects WHERE phone_number_id=%s",
                                   (phone_number_id,)).fetchone()
            if project is None:
                return False
            row = conn.execute(
                """SELECT o.id,o.project_id,o.delivery_status FROM ctx_outbox o
                   JOIN ctx_projects j ON j.id=o.project_id
                   WHERE j.phone_number_id=%s AND o.meta_message_id=%s FOR UPDATE OF o""",
                (phone_number_id, message_id),
            ).fetchone()
            added = conn.execute(
                """INSERT INTO ctx_delivery_events(project_id,phone_number_id,message_id,outbox_id,status,event_at,error)
                   VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING id""",
                (project["id"], phone_number_id, message_id, row["id"] if row else None, status, _time(timestamp), error),
            ).fetchone()
            if added is None:
                return False
            ranks = {None: -1, "sent": 0, "failed": 1, "delivered": 2, "read": 3}
            if row is not None and ranks[status] > ranks[row["delivery_status"]]:
                conn.execute("UPDATE ctx_outbox SET delivery_status=%s,updated_at=clock_timestamp() WHERE id=%s",
                             (status, row["id"]))
            return True

    def reconcile_sending(self, project_id: str) -> int:
        """Call on restart: previously started sends have an unknown outcome."""
        with self.transaction(project_id) as session:
            return session.conn.execute(
                """UPDATE ctx_outbox SET state='uncertain',error='worker restarted during send',
                   updated_at=clock_timestamp() WHERE project_id=%s AND state='sending'""", (project_id,)
            ).rowcount

    def list_project_ids(self) -> list[str]:
        with self.connect() as conn:
            return [row["id"] for row in conn.execute("SELECT id FROM ctx_projects ORDER BY id")]


class ProjectSession:
    def __init__(self, conn: psycopg.Connection, project_id: str):
        self.conn = conn
        self.project_id = project_id

    def project(self) -> dict:
        row = self.conn.execute(
            """SELECT id,name,phone_number_id,required_topics,interview_status,cutoff_sequence,
               current_revision,model_calls,created_at FROM ctx_projects WHERE id=%s""", (self.project_id,)
        ).fetchone()
        if row is None:
            raise NotFound("project not found")
        return {**row, "status": row["interview_status"], "cutoff": row["cutoff_sequence"]}

    def participants(self) -> list[dict]:
        return self.conn.execute("SELECT * FROM ctx_participants WHERE project_id=%s ORDER BY created_at,id",
                                 (self.project_id,)).fetchall()

    def get_input(self, input_id: str) -> dict:
        row = self.conn.execute("SELECT * FROM ctx_inbox WHERE project_id=%s AND id=%s",
                                (self.project_id, input_id)).fetchone()
        if row is None:
            raise NotFound("input not found")
        return row

    def next_input(self) -> dict | None:
        # A failed earlier audio remains visible; only an explicit resolution may skip it.
        return self.conn.execute(
            """SELECT * FROM ctx_inbox WHERE project_id=%s AND status NOT IN ('processed','cancelled')
               ORDER BY received_sequence LIMIT 1""", (self.project_id,)
        ).fetchone()

    def pending_inputs(self, cutoff: int | None = None) -> list[str]:
        return [r["id"] for r in self.conn.execute(
            """SELECT id FROM ctx_inbox WHERE project_id=%s AND status NOT IN ('processed','cancelled')
               AND (%s::bigint IS NULL OR received_sequence<=%s) ORDER BY received_sequence""",
            (self.project_id, cutoff, cutoff))]

    def mark_input(self, input_id: str, status: str, *, error: str | None = None,
                   text: str | None = None, increase_attempts: bool = False) -> dict:
        if status not in {"pending", "processing", "processed", "failed"}:
            raise ValueError("use resolve_input for explicit cancellation")
        original = self.get_input(input_id)
        if original["status"] in {"processed", "cancelled"} and status != original["status"]:
            raise ValueError("resolved inputs cannot be reopened; add correction evidence")
        if increase_attempts and original["attempts"] >= 3:
            raise ValueError("input retry limit reached")
        return self.conn.execute(
            """UPDATE ctx_inbox SET status=%s,error=%s,resolved_text=COALESCE(%s,resolved_text),
               attempts=attempts+%s WHERE project_id=%s AND id=%s RETURNING *""",
            (status, error, text, int(increase_attempts), self.project_id, input_id),
        ).fetchone()

    def resolve_input(self, input_id: str, reason: str) -> dict:
        if not reason.strip():
            raise ValueError("an explicit resolution reason is required")
        row = self.get_input(input_id)
        if row["status"] == "processed":
            raise ValueError("processed evidence cannot be cancelled")
        return self.conn.execute(
            """UPDATE ctx_inbox SET status='cancelled',resolution_note=%s
               WHERE project_id=%s AND id=%s RETURNING *""", (reason, self.project_id, input_id)
        ).fetchone()

    def add_media(self, input_id: str, storage_path: str, sha256: str, mime_type: str,
                  size_bytes: int) -> dict:
        row = self.get_input(input_id)
        if row["kind"] != "audio":
            raise ValueError("only audio inputs have media")
        return self.conn.execute(
            """INSERT INTO ctx_media(id,project_id,input_id,storage_path,sha256,mime_type,size_bytes)
               VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (input_id,sha256)
               DO NOTHING RETURNING *""", (_id(), self.project_id, input_id, storage_path, sha256, mime_type, size_bytes)
        ).fetchone() or self.conn.execute(
            "SELECT * FROM ctx_media WHERE project_id=%s AND input_id=%s AND sha256=%s",
            (self.project_id, input_id, sha256),
        ).fetchone()

    def add_transcription(self, input_id: str, text: str, model: str,
                          media_id: str | None = None, segments: list | None = None,
                          correction_reason: str | None = None) -> dict:
        if not text.strip() or not model.strip():
            raise ValueError("transcription text and model are required")
        input_row = self.get_input(input_id)
        if input_row["kind"] != "audio":
            raise ValueError("only audio inputs have transcriptions")
        if media_id is not None and self.conn.execute(
            "SELECT 1 FROM ctx_media WHERE id=%s AND project_id=%s AND input_id=%s",
            (media_id, self.project_id, input_id),
        ).fetchone() is None:
            raise ValueError("media does not belong to this audio input")
        previous = self.get_transcription(input_id)
        if previous is not None and not correction_reason:
            raise ValueError("a transcription correction must record its reason")
        row = self.conn.execute(
            """INSERT INTO ctx_transcriptions(id,project_id,input_id,version,text,model,media_id,
               segments,correction_reason) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
            (_id(), self.project_id, input_id, previous["version"] + 1 if previous else 1,
             text, model, media_id, Jsonb(segments or []), correction_reason),
        ).fetchone()
        self.conn.execute("UPDATE ctx_inbox SET resolved_text=%s WHERE project_id=%s AND id=%s",
                          (text, self.project_id, input_id))
        return row

    def get_transcription(self, input_id: str) -> dict | None:
        source = self.get_input(input_id)
        if source.get("correction_of_input_id"):
            return self.conn.execute(
                "SELECT * FROM ctx_transcriptions WHERE project_id=%s AND input_id=%s AND version=%s",
                (self.project_id, source["correction_of_input_id"], source["transcription_version"])
            ).fetchone()
        return self.conn.execute(
            """SELECT * FROM ctx_transcriptions WHERE project_id=%s AND input_id=%s
               ORDER BY version DESC LIMIT 1""", (self.project_id, input_id)
        ).fetchone()

    def correct_transcript(self, input_id: str, text: str, reason: str,
                           enqueue: Callable[[psycopg.Connection, str], None]) -> dict:
        """Append a transcript version and a new derived input; keep old evidence."""
        original = self.get_input(input_id)
        if original.get("correction_of_input_id"):
            original = self.get_input(original["correction_of_input_id"])
        if original["kind"] != "audio" or not reason.strip() or not 0 < len(text.strip()) <= 16384:
            raise ValueError("audio, bounded corrected text and correction reason are required")
        transcript = self.add_transcription(original["id"], text, "operator-correction",
                                             correction_reason=reason)
        correction = self.conn.execute(
            """INSERT INTO ctx_inbox(id,project_id,participant_id,phone_number_id,message_id,
               sent_at,kind,media_id,mime_type,resolved_text,correction_of_input_id,transcription_version)
               VALUES (%s,%s,%s,%s,%s,clock_timestamp(),'audio',%s,%s,%s,%s,%s) RETURNING *""",
            (_id(), self.project_id, original["participant_id"], original["phone_number_id"],
             "transcript-correction:" + _id(), original["media_id"], original["mime_type"], text,
             original["id"], transcript["version"])
        ).fetchone()
        if original["status"] not in {"processed", "cancelled"}:
            self.resolve_input(original["id"], "transcript corrected: " + reason)
        enqueue(self.conn, self.project_id)
        return correction

    def load_context(self, revision: int | None = None) -> dict | None:
        if revision is None:
            revision = self.project()["current_revision"]
        row = self.conn.execute("SELECT document FROM ctx_revisions WHERE project_id=%s AND revision=%s",
                                (self.project_id, revision)).fetchone()
        return row["document"] if row else None

    def save_revision(self, expected_revision: int, document: dict,
                      processed_input_id: str | None = None) -> dict:
        if document.get("project_id") != self.project_id or document.get("revision") != expected_revision + 1:
            raise ValueError("document identity/revision does not match this update")
        if processed_input_id is not None:
            first = self.next_input()
            if first is None or first["id"] != processed_input_id or first["status"] == "failed":
                raise ValueError("must process the earliest unresolved input")
        changed = self.conn.execute(
            """UPDATE ctx_projects SET current_revision=current_revision+1
               WHERE id=%s AND current_revision=%s RETURNING current_revision""", (self.project_id, expected_revision)
        ).fetchone()
        if changed is None:
            raise StaleRevision("context revision changed; regenerate the proposal")
        self.conn.execute("INSERT INTO ctx_revisions(project_id,revision,document) VALUES (%s,%s,%s)",
                          (self.project_id, expected_revision + 1, Jsonb(document)))
        if processed_input_id is not None:
            self.mark_input(processed_input_id, "processed")
        return document

    def create_outbox(self, participant_id: str, revision: int, text: str,
                      question_data: dict | None = None, dedupe_key: str | None = None,
                      kind: str = "question") -> dict:
        if not text.strip() or revision > self.project()["current_revision"]:
            raise ValueError("outbox text and a committed context revision are required")
        key = dedupe_key or _id()
        return self.conn.execute(
            """INSERT INTO ctx_outbox(id,project_id,participant_id,revision,body,question_data,dedupe_key,kind)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (project_id,dedupe_key)
               DO NOTHING RETURNING *""",
            (_id(), self.project_id, participant_id, revision, text, Jsonb(question_data or {}), key, kind),
        ).fetchone() or self.conn.execute(
            "SELECT * FROM ctx_outbox WHERE project_id=%s AND dedupe_key=%s", (self.project_id, key)
        ).fetchone()

    def next_outbox(self) -> dict | None:
        row = self.conn.execute(
            """SELECT o.*,p.wa_id,p.last_customer_at FROM ctx_outbox o
               JOIN ctx_participants p ON p.id=o.participant_id AND p.project_id=o.project_id
               WHERE o.project_id=%s AND (o.state='pending' OR
                   (o.state='waiting_window' AND p.last_customer_at > clock_timestamp()-interval '24 hours'))
               ORDER BY CASE WHEN o.kind='notice' THEN 0 ELSE 1 END,o.created_at,o.id LIMIT 1""", (self.project_id,)
        ).fetchone()
        return self._with_delivery(row) if row else None

    def _with_delivery(self, row: dict) -> dict:
        if not row["meta_message_id"]:
            return row
        # Compute from append-only events: callbacks can precede the send acknowledgement.
        status = self.conn.execute(
            """SELECT status FROM ctx_delivery_events WHERE project_id=%s AND message_id=%s
               ORDER BY CASE status WHEN 'read' THEN 3 WHEN 'delivered' THEN 2
               WHEN 'failed' THEN 1 ELSE 0 END DESC LIMIT 1""",
            (self.project_id, row["meta_message_id"]),
        ).fetchone()
        return {**row, "delivery_status": status["status"] if status else row["delivery_status"]}

    def get_outbox(self, outbox_id: str) -> dict:
        row = self.conn.execute("SELECT * FROM ctx_outbox WHERE project_id=%s AND id=%s",
                                (self.project_id, outbox_id)).fetchone()
        if row is None:
            raise NotFound("outbox not found")
        return self._with_delivery(row)

    def set_outbox_state(self, outbox_id: str, state: str, *, error: str | None = None,
                         message_id: str | None = None, increase_attempts: bool = False) -> dict:
        row = self.get_outbox(outbox_id)
        transitions = {
            "pending": {"sending", "waiting_window", "cancelled", "failed"},
            "sending": {"sent", "uncertain", "pending", "failed"},
            "waiting_window": {"pending", "sending", "cancelled"},
            "sent": set(), "uncertain": set(), "failed": set(), "cancelled": set(),
        }
        if state != row["state"] and state not in transitions[row["state"]]:
            raise ValueError("invalid outbox transition; uncertain sends require operator investigation")
        if increase_attempts and row["attempts"] >= 3:
            raise ValueError("send retry limit reached")
        if state == "sent" and not (message_id or row["meta_message_id"]):
            raise ValueError("a successful send must record the Meta message ID")
        return self.conn.execute(
            """UPDATE ctx_outbox SET state=%s,error=%s,meta_message_id=COALESCE(%s,meta_message_id),
               attempts=attempts+%s,updated_at=clock_timestamp(),
               sent_at=CASE WHEN %s='sent' THEN COALESCE(sent_at,clock_timestamp()) ELSE sent_at END
               WHERE project_id=%s AND id=%s RETURNING *""",
            (state, error, message_id, int(increase_attempts), state, self.project_id, outbox_id),
        ).fetchone()

    def latest_question(self, participant_id: str) -> dict | None:
        row = self.conn.execute(
            """SELECT * FROM ctx_outbox WHERE project_id=%s AND participant_id=%s
               AND state='sent' AND kind='question' ORDER BY sent_at DESC,created_at DESC,id DESC LIMIT 1""",
            (self.project_id, participant_id),
        ).fetchone()
        return row if row is not None and row["consumed_by_input_id"] is None else None

    def consume_question(self, outbox_id: str, input_id: str) -> None:
        received = self.get_input(input_id)
        row = self.get_outbox(outbox_id)
        if row["state"] != "sent" or row["kind"] != "question":
            raise ValueError("only a sent question can be answered")
        if row["consumed_by_input_id"] not in {None, input_id}:
            raise ValueError("question already answered")
        if received["participant_id"] != row["participant_id"] or received["sent_at"] <= row["sent_at"]:
            raise ValueError("answer must come from the question recipient after the question was sent")
        self.conn.execute(
            """UPDATE ctx_outbox SET consumed_by_input_id=%s,updated_at=clock_timestamp()
               WHERE project_id=%s AND id=%s""", (input_id, self.project_id, outbox_id)
        )

    def reserve_model_call(self, limit: int) -> bool:
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
            raise ValueError("model call limit must be a positive integer")
        return self.conn.execute(
            """UPDATE ctx_projects SET model_calls=model_calls+1
               WHERE id=%s AND model_calls<%s RETURNING model_calls""", (self.project_id, limit)
        ).fetchone() is not None

    def request_question(self, participant_id: str, revision: int) -> None:
        self.conn.execute(
            """INSERT INTO ctx_question_requests(id,project_id,participant_id,revision)
               VALUES (%s,%s,%s,%s) ON CONFLICT (project_id,participant_id,revision) DO NOTHING""",
            (_id(), self.project_id, participant_id, revision))

    def next_question_request(self) -> dict | None:
        return self.conn.execute(
            """SELECT * FROM ctx_question_requests WHERE project_id=%s AND state='pending'
               ORDER BY created_at,id LIMIT 1""", (self.project_id,)).fetchone()

    def update_question_request(self, request_id: str, state: str, *, error: str | None = None,
                                increase_attempts: bool = False) -> None:
        if state not in {"pending", "generated", "failed", "cancelled"}:
            raise ValueError("invalid question request state")
        self.conn.execute(
            """UPDATE ctx_question_requests SET state=%s,error=%s,attempts=attempts+%s
               WHERE project_id=%s AND id=%s""", (state, error, int(increase_attempts), self.project_id, request_id))

    def record_model_usage(self, model: str, usage: dict, latency_ms: int) -> dict:
        if not model or not isinstance(usage, dict) or latency_ms < 0:
            raise ValueError("model, usage object and nonnegative latency are required")
        return self.conn.execute(
            """INSERT INTO ctx_model_usage(project_id,model,usage,latency_ms)
               VALUES (%s,%s,%s,%s) RETURNING *""", (self.project_id, model, Jsonb(usage), latency_ms)
        ).fetchone()

    def model_usage(self) -> list[dict]:
        return self.conn.execute("SELECT * FROM ctx_model_usage WHERE project_id=%s ORDER BY id",
                                 (self.project_id,)).fetchall()

    def set_interview_state(self, status: str, cutoff: int | None = None) -> dict:
        if status not in {"active", "paused", "closed"}:
            raise ValueError("invalid interview status")
        if status == "closed" and cutoff is None:
            cutoff = self.conn.execute(
                "SELECT COALESCE(MAX(received_sequence),0) AS n FROM ctx_inbox WHERE project_id=%s",
                (self.project_id,),
            ).fetchone()["n"]
        if status != "closed":
            cutoff = None
        self.conn.execute("UPDATE ctx_projects SET interview_status=%s,cutoff_sequence=%s WHERE id=%s",
                          (status, cutoff, self.project_id))
        return self.project()
