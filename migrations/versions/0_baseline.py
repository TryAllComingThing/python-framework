"""Consolidated initial schema for NEW PostgreSQL installations only.

Historical revisions were intentionally squashed. Databases with old alembic_version
values require explicit migration reconciliation, not automatic upgrade.
DDL is a frozen snapshot of SQLAlchemy metadata at consolidation time.
"""
from alembic import op

revision = "0_baseline"
down_revision = None
branch_labels = None
depends_on = None


SCHEMA_DDL = (
    'CREATE TABLE sf_departments (\n\tid SERIAL NOT NULL, \n\tparent_id INTEGER, \n\tname VARCHAR(100) NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(parent_id) REFERENCES sf_departments (id)\n)',
    "CREATE TABLE sf_file_cleanup_jobs (\n\tid SERIAL NOT NULL, \n\tobject_key VARCHAR(64) NOT NULL, \n\tfile_id INTEGER, \n\treason VARCHAR(32) DEFAULT 'delete' NOT NULL, \n\tlease_token VARCHAR(64), \n\tlease_until TIMESTAMP WITH TIME ZONE, \n\tattempts INTEGER DEFAULT '0' NOT NULL, \n\tlast_error VARCHAR(255), \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (object_key)\n)",
    "CREATE TABLE sf_login_attempts (\n\tbucket VARCHAR(64) NOT NULL, \n\tfailures INTEGER DEFAULT '0' NOT NULL, \n\twindow_start TIMESTAMP WITH TIME ZONE NOT NULL, \n\tlocked_until TIMESTAMP WITH TIME ZONE, \n\tPRIMARY KEY (bucket)\n)",
    'CREATE TABLE sf_menus (\n\tid SERIAL NOT NULL, \n\tparent_id INTEGER, \n\tname VARCHAR(100) NOT NULL, \n\tpath VARCHAR(255) NOT NULL, \n\tpermission_code VARCHAR(128), \n\torder_num INTEGER DEFAULT 0 NOT NULL, \n\tactive BOOLEAN DEFAULT true NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT uq_sf_menus_path UNIQUE (path), \n\tFOREIGN KEY(parent_id) REFERENCES sf_menus (id)\n)',
    'CREATE TABLE sf_permissions (\n\tid SERIAL NOT NULL, \n\tcode VARCHAR(128) NOT NULL, \n\tPRIMARY KEY (id)\n)',
    'CREATE UNIQUE INDEX ix_sf_permissions_code ON sf_permissions (code)',
    "CREATE TABLE sf_roles (\n\tid SERIAL NOT NULL, \n\tname VARCHAR(100) NOT NULL, \n\tscope VARCHAR(32) DEFAULT 'SELF' NOT NULL, \n\tactive BOOLEAN DEFAULT 'true' NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT ck_sf_roles_scope CHECK (scope IN ('SELF', 'DEPARTMENT', 'DEPARTMENT_AND_CHILDREN', 'CUSTOM', 'ALL')), \n\tUNIQUE (name)\n)",
    'CREATE TABLE sf_role_departments (\n\trole_id INTEGER NOT NULL, \n\tdepartment_id INTEGER NOT NULL, \n\tPRIMARY KEY (role_id, department_id), \n\tFOREIGN KEY(role_id) REFERENCES sf_roles (id) ON DELETE CASCADE, \n\tFOREIGN KEY(department_id) REFERENCES sf_departments (id) ON DELETE CASCADE\n)',
    'CREATE TABLE sf_role_permissions (\n\trole_id INTEGER NOT NULL, \n\tpermission_id INTEGER NOT NULL, \n\tPRIMARY KEY (role_id, permission_id), \n\tFOREIGN KEY(role_id) REFERENCES sf_roles (id) ON DELETE CASCADE, \n\tFOREIGN KEY(permission_id) REFERENCES sf_permissions (id) ON DELETE CASCADE\n)',
    'CREATE TABLE sf_users (\n\tid SERIAL NOT NULL, \n\tusername VARCHAR(100) NOT NULL, \n\tpassword_hash VARCHAR(255) NOT NULL, \n\tactive BOOLEAN DEFAULT true NOT NULL, \n\tauth_version INTEGER DEFAULT 1 NOT NULL, \n\tdepartment_id INTEGER, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(department_id) REFERENCES sf_departments (id) ON DELETE SET NULL\n)',
    'CREATE UNIQUE INDEX ix_sf_users_username ON sf_users (username)',
    'CREATE TABLE sf_audit_events (\n\tid SERIAL NOT NULL, \n\tactor_id INTEGER, \n\taction VARCHAR(100) NOT NULL, \n\ttarget VARCHAR(255) NOT NULL, \n\trequest_id VARCHAR(64) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(actor_id) REFERENCES sf_users (id)\n)',
    'CREATE TABLE sf_file_records (\n\tid SERIAL NOT NULL, \n\towner_id INTEGER NOT NULL, \n\tobject_key VARCHAR(64) NOT NULL, \n\toriginal_name VARCHAR(255) NOT NULL, \n\tcontent_type VARCHAR(120) NOT NULL, \n\tsize BIGINT NOT NULL, \n\tsha256 VARCHAR(64) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(owner_id) REFERENCES sf_users (id) ON DELETE RESTRICT, \n\tUNIQUE (object_key)\n)',
    'CREATE INDEX ix_sf_file_records_owner_id ON sf_file_records (owner_id)',
    'CREATE TABLE sf_login_sessions (\n\tid SERIAL NOT NULL, \n\tuser_id INTEGER NOT NULL, \n\ttoken_digest VARCHAR(64) NOT NULL, \n\tcsrf_digest VARCHAR(64) NOT NULL, \n\tauth_version INTEGER NOT NULL, \n\texpires_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\trevoked_at TIMESTAMP WITH TIME ZONE, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(user_id) REFERENCES sf_users (id) ON DELETE CASCADE\n)',
    'CREATE UNIQUE INDEX ix_sf_login_sessions_token_digest ON sf_login_sessions (token_digest)',
    'CREATE INDEX ix_sf_login_sessions_user_id ON sf_login_sessions (user_id)',
    'CREATE TABLE sf_user_roles (\n\tuser_id INTEGER NOT NULL, \n\trole_id INTEGER NOT NULL, \n\tPRIMARY KEY (user_id, role_id), \n\tFOREIGN KEY(user_id) REFERENCES sf_users (id) ON DELETE CASCADE, \n\tFOREIGN KEY(role_id) REFERENCES sf_roles (id) ON DELETE CASCADE\n)',
)


def upgrade() -> None:
    for ddl in SCHEMA_DDL:
        op.execute(ddl)


def downgrade() -> None:
    op.drop_table('sf_user_roles')
    op.drop_table('sf_login_sessions')
    op.drop_table('sf_file_records')
    op.drop_table('sf_audit_events')
    op.drop_table('sf_users')
    op.drop_table('sf_role_permissions')
    op.drop_table('sf_role_departments')
    op.drop_table('sf_roles')
    op.drop_table('sf_permissions')
    op.drop_table('sf_menus')
    op.drop_table('sf_login_attempts')
    op.drop_table('sf_file_cleanup_jobs')
    op.drop_table('sf_departments')
