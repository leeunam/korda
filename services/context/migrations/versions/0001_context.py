"""Persistent interview inbox, immutable context and transactional outbox.

Revision ID: context_0001
"""

from alembic import op

revision = "context_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
CREATE TABLE ctx_projects (
    id text PRIMARY KEY,
    name text NOT NULL,
    phone_number_id text NOT NULL UNIQUE,
    token_hash text NOT NULL,
    required_topics jsonb NOT NULL DEFAULT '{}',
    interview_status text NOT NULL DEFAULT 'active' CHECK (interview_status IN ('active','paused','closed')),
    cutoff_sequence bigint,
    current_revision integer NOT NULL DEFAULT 0 CHECK (current_revision >= 0),
    model_calls integer NOT NULL DEFAULT 0 CHECK (model_calls >= 0),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE ctx_participants (
    id text PRIMARY KEY,
    project_id text NOT NULL REFERENCES ctx_projects(id),
    wa_id text NOT NULL,
    name text NOT NULL,
    role text NOT NULL,
    last_customer_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (project_id,wa_id),
    UNIQUE (project_id,id)
);
CREATE TABLE ctx_inbox (
    id text PRIMARY KEY,
    project_id text NOT NULL REFERENCES ctx_projects(id),
    participant_id text NOT NULL,
    phone_number_id text NOT NULL,
    message_id text NOT NULL,
    received_sequence bigserial UNIQUE,
    sent_at timestamptz NOT NULL,
    received_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    kind text NOT NULL CHECK (kind IN ('text','audio')),
    original_text text,
    resolved_text text,
    media_id text,
    mime_type text,
    correction_of_input_id text,
    transcription_version integer,
    status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','processing','processed','failed','cancelled')),
    attempts integer NOT NULL DEFAULT 0 CHECK (attempts BETWEEN 0 AND 3),
    error text,
    resolution_note text,
    UNIQUE (phone_number_id,message_id),
    UNIQUE (project_id,id),
    FOREIGN KEY (project_id,participant_id) REFERENCES ctx_participants(project_id,id),
    FOREIGN KEY (project_id,correction_of_input_id) REFERENCES ctx_inbox(project_id,id),
    CHECK ((kind='text' AND original_text IS NOT NULL) OR (kind='audio' AND media_id IS NOT NULL))
);
CREATE INDEX ctx_inbox_project_sequence ON ctx_inbox(project_id,received_sequence);
CREATE TABLE ctx_media (
    id text PRIMARY KEY,
    project_id text NOT NULL,
    input_id text NOT NULL,
    storage_path text NOT NULL,
    sha256 text NOT NULL CHECK (length(sha256)=64),
    mime_type text NOT NULL,
    size_bytes bigint NOT NULL CHECK (size_bytes BETWEEN 1 AND 10485760),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    FOREIGN KEY (project_id,input_id) REFERENCES ctx_inbox(project_id,id),
    UNIQUE (input_id,sha256)
);
CREATE TABLE ctx_transcriptions (
    id text PRIMARY KEY,
    project_id text NOT NULL,
    input_id text NOT NULL,
    version integer NOT NULL CHECK (version > 0),
    text text NOT NULL,
    model text NOT NULL,
    media_id text REFERENCES ctx_media(id),
    segments jsonb NOT NULL DEFAULT '[]',
    correction_reason text,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    FOREIGN KEY (project_id,input_id) REFERENCES ctx_inbox(project_id,id),
    UNIQUE (input_id,version)
);
CREATE TABLE ctx_revisions (
    project_id text NOT NULL REFERENCES ctx_projects(id),
    revision integer NOT NULL CHECK (revision > 0),
    document jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (project_id,revision)
);
CREATE TABLE ctx_outbox (
    id text PRIMARY KEY,
    project_id text NOT NULL REFERENCES ctx_projects(id),
    participant_id text NOT NULL,
    revision integer NOT NULL CHECK (revision >= 0),
    body text NOT NULL,
    question_data jsonb NOT NULL DEFAULT '{}',
    kind text NOT NULL DEFAULT 'question',
    dedupe_key text NOT NULL,
    state text NOT NULL DEFAULT 'pending' CHECK (state IN ('pending','sending','sent','uncertain','failed','waiting_window','cancelled')),
    attempts integer NOT NULL DEFAULT 0 CHECK (attempts BETWEEN 0 AND 3),
    meta_message_id text,
    delivery_status text,
    error text,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    sent_at timestamptz,
    consumed_by_input_id text,
    FOREIGN KEY (project_id,participant_id) REFERENCES ctx_participants(project_id,id),
    FOREIGN KEY (project_id,consumed_by_input_id) REFERENCES ctx_inbox(project_id,id),
    UNIQUE (project_id,dedupe_key),
    UNIQUE (project_id,meta_message_id),
    UNIQUE (project_id,id)
);
CREATE INDEX ctx_outbox_pending ON ctx_outbox(project_id,created_at);
CREATE INDEX ctx_outbox_meta ON ctx_outbox(meta_message_id) WHERE meta_message_id IS NOT NULL;
CREATE TABLE ctx_delivery_events (
    id bigserial PRIMARY KEY,
    project_id text NOT NULL,
    phone_number_id text NOT NULL,
    message_id text NOT NULL,
    outbox_id text,
    status text NOT NULL CHECK (status IN ('sent','delivered','read','failed')),
    event_at timestamptz NOT NULL,
    error text,
    received_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    FOREIGN KEY (project_id,outbox_id) REFERENCES ctx_outbox(project_id,id),
    UNIQUE (phone_number_id,message_id,status,event_at)
);
CREATE TABLE ctx_model_usage (
    id bigserial PRIMARY KEY,
    project_id text NOT NULL REFERENCES ctx_projects(id),
    model text NOT NULL,
    usage jsonb NOT NULL,
    latency_ms integer NOT NULL CHECK (latency_ms >= 0),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE ctx_question_requests (
    id text PRIMARY KEY,
    project_id text NOT NULL REFERENCES ctx_projects(id),
    participant_id text NOT NULL,
    revision integer NOT NULL,
    state text NOT NULL DEFAULT 'pending' CHECK (state IN ('pending','generated','failed','cancelled')),
    attempts integer NOT NULL DEFAULT 0 CHECK (attempts BETWEEN 0 AND 3),
    error text,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    FOREIGN KEY (project_id,participant_id) REFERENCES ctx_participants(project_id,id),
    UNIQUE (project_id,participant_id,revision)
);
CREATE FUNCTION ctx_reject_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'context history is append-only';
END $$;
CREATE TRIGGER ctx_revisions_immutable BEFORE UPDATE OR DELETE ON ctx_revisions
    FOR EACH ROW EXECUTE FUNCTION ctx_reject_mutation();
CREATE TRIGGER ctx_transcriptions_immutable BEFORE UPDATE OR DELETE ON ctx_transcriptions
    FOR EACH ROW EXECUTE FUNCTION ctx_reject_mutation();
CREATE TRIGGER ctx_media_immutable BEFORE UPDATE OR DELETE ON ctx_media
    FOR EACH ROW EXECUTE FUNCTION ctx_reject_mutation();
CREATE TRIGGER ctx_delivery_events_immutable BEFORE UPDATE OR DELETE ON ctx_delivery_events
    FOR EACH ROW EXECUTE FUNCTION ctx_reject_mutation();
CREATE TRIGGER ctx_model_usage_immutable BEFORE UPDATE OR DELETE ON ctx_model_usage
    FOR EACH ROW EXECUTE FUNCTION ctx_reject_mutation();
CREATE FUNCTION ctx_preserve_inbox_original() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF (NEW.project_id,NEW.participant_id,NEW.phone_number_id,NEW.message_id,NEW.received_sequence,
        NEW.sent_at,NEW.received_at,NEW.kind,NEW.original_text,NEW.media_id,NEW.mime_type,
        NEW.correction_of_input_id,NEW.transcription_version)
       IS DISTINCT FROM
       (OLD.project_id,OLD.participant_id,OLD.phone_number_id,OLD.message_id,OLD.received_sequence,
        OLD.sent_at,OLD.received_at,OLD.kind,OLD.original_text,OLD.media_id,OLD.mime_type,
        OLD.correction_of_input_id,OLD.transcription_version) THEN
        RAISE EXCEPTION 'original inbox evidence is immutable';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER ctx_inbox_original_immutable BEFORE UPDATE ON ctx_inbox
    FOR EACH ROW EXECUTE FUNCTION ctx_preserve_inbox_original();
CREATE TRIGGER ctx_inbox_delete_immutable BEFORE DELETE ON ctx_inbox
    FOR EACH ROW EXECUTE FUNCTION ctx_reject_mutation();
""")


def downgrade():
    raise RuntimeError("Context history cannot be dropped by downgrade; restore a verified backup instead")

