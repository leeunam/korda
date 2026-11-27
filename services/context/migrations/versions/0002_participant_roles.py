"""Allow several enrolled areas per phone, preserving identities and history.

Revision ID: context_0002
"""
from alembic import op

revision = "context_0002"
down_revision = "context_0001"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
ALTER TABLE ctx_participants ADD COLUMN roles text[];
UPDATE ctx_participants SET roles=ARRAY[role];
ALTER TABLE ctx_participants ALTER COLUMN roles SET NOT NULL;
ALTER TABLE ctx_participants ADD CONSTRAINT ctx_participants_roles_valid CHECK (
    cardinality(roles)>0 AND array_position(roles,NULL) IS NULL
    AND '' != ALL(roles) AND role=roles[1]
);
""")


def downgrade():
    raise RuntimeError("Removing participant roles would lose authority assignments; restore a verified backup instead")
