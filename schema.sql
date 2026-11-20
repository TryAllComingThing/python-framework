BEGIN;

CREATE TABLE alembic_version (
    version_num VARCHAR(32) NOT NULL, 
    CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
);

-- Running upgrade  -> 0_baseline

CREATE TABLE sf_departments (
    id SERIAL NOT NULL, 
    parent_id INTEGER, 
    name VARCHAR(100) NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(parent_id) REFERENCES sf_departments (id)
);

CREATE TABLE sf_file_cleanup_jobs (
    id SERIAL NOT NULL, 
    object_key VARCHAR(64) NOT NULL, 
    file_id INTEGER, 
    reason VARCHAR(32) DEFAULT 'delete' NOT NULL, 
    lease_token VARCHAR(64), 
    lease_until TIMESTAMP WITH TIME ZONE, 
    attempts INTEGER DEFAULT '0' NOT NULL, 
    last_error VARCHAR(255), 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    UNIQUE (object_key)
);

CREATE TABLE sf_login_attempts (
    bucket VARCHAR(64) NOT NULL, 
    failures INTEGER DEFAULT '0' NOT NULL, 
    window_start TIMESTAMP WITH TIME ZONE NOT NULL, 
    locked_until TIMESTAMP WITH TIME ZONE, 
    PRIMARY KEY (bucket)
);

CREATE TABLE sf_menus (
    id SERIAL NOT NULL, 
    parent_id INTEGER, 
    name VARCHAR(100) NOT NULL, 
    path VARCHAR(255) NOT NULL, 
    permission_code VARCHAR(128), 
    order_num INTEGER DEFAULT 0 NOT NULL, 
    active BOOLEAN DEFAULT true NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT uq_sf_menus_path UNIQUE (path), 
    FOREIGN KEY(parent_id) REFERENCES sf_menus (id)
);

CREATE TABLE sf_permissions (
    id SERIAL NOT NULL, 
    code VARCHAR(128) NOT NULL, 
    PRIMARY KEY (id)
);

CREATE UNIQUE INDEX ix_sf_permissions_code ON sf_permissions (code);

CREATE TABLE sf_roles (
    id SERIAL NOT NULL, 
    name VARCHAR(100) NOT NULL, 
    scope VARCHAR(32) DEFAULT 'SELF' NOT NULL, 
    active BOOLEAN DEFAULT 'true' NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT ck_sf_roles_scope CHECK (scope IN ('SELF', 'DEPARTMENT', 'DEPARTMENT_AND_CHILDREN', 'CUSTOM', 'ALL')), 
    UNIQUE (name)
);

CREATE TABLE sf_role_departments (
    role_id INTEGER NOT NULL, 
    department_id INTEGER NOT NULL, 
    PRIMARY KEY (role_id, department_id), 
    FOREIGN KEY(role_id) REFERENCES sf_roles (id) ON DELETE CASCADE, 
    FOREIGN KEY(department_id) REFERENCES sf_departments (id) ON DELETE CASCADE
);

CREATE TABLE sf_role_permissions (
    role_id INTEGER NOT NULL, 
    permission_id INTEGER NOT NULL, 
    PRIMARY KEY (role_id, permission_id), 
    FOREIGN KEY(role_id) REFERENCES sf_roles (id) ON DELETE CASCADE, 
    FOREIGN KEY(permission_id) REFERENCES sf_permissions (id) ON DELETE CASCADE
);

CREATE TABLE sf_users (
    id SERIAL NOT NULL, 
    username VARCHAR(100) NOT NULL, 
    password_hash VARCHAR(255) NOT NULL, 
    active BOOLEAN DEFAULT true NOT NULL, 
    auth_version INTEGER DEFAULT 1 NOT NULL, 
    department_id INTEGER, 
    PRIMARY KEY (id), 
    FOREIGN KEY(department_id) REFERENCES sf_departments (id) ON DELETE SET NULL
);

CREATE UNIQUE INDEX ix_sf_users_username ON sf_users (username);

CREATE TABLE sf_audit_events (
    id SERIAL NOT NULL, 
    actor_id INTEGER, 
    action VARCHAR(100) NOT NULL, 
    target VARCHAR(255) NOT NULL, 
    request_id VARCHAR(64) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(actor_id) REFERENCES sf_users (id)
);

CREATE TABLE sf_file_records (
    id SERIAL NOT NULL, 
    owner_id INTEGER NOT NULL, 
    object_key VARCHAR(64) NOT NULL, 
    original_name VARCHAR(255) NOT NULL, 
    content_type VARCHAR(120) NOT NULL, 
    size BIGINT NOT NULL, 
    sha256 VARCHAR(64) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(owner_id) REFERENCES sf_users (id) ON DELETE RESTRICT, 
    UNIQUE (object_key)
);

CREATE INDEX ix_sf_file_records_owner_id ON sf_file_records (owner_id);

CREATE TABLE sf_login_sessions (
    id SERIAL NOT NULL, 
    user_id INTEGER NOT NULL, 
    token_digest VARCHAR(64) NOT NULL, 
    csrf_digest VARCHAR(64) NOT NULL, 
    auth_version INTEGER NOT NULL, 
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    revoked_at TIMESTAMP WITH TIME ZONE, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(user_id) REFERENCES sf_users (id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX ix_sf_login_sessions_token_digest ON sf_login_sessions (token_digest);

CREATE INDEX ix_sf_login_sessions_user_id ON sf_login_sessions (user_id);

CREATE TABLE sf_user_roles (
    user_id INTEGER NOT NULL, 
    role_id INTEGER NOT NULL, 
    PRIMARY KEY (user_id, role_id), 
    FOREIGN KEY(user_id) REFERENCES sf_users (id) ON DELETE CASCADE, 
    FOREIGN KEY(role_id) REFERENCES sf_roles (id) ON DELETE CASCADE
);

INSERT INTO alembic_version (version_num) VALUES ('0_baseline') RETURNING alembic_version.version_num;

-- Running upgrade 0_baseline -> 1_quality_remediation

ALTER TABLE sf_file_records ADD CONSTRAINT ck_sf_file_records_size_positive CHECK (size > 0);

ALTER TABLE sf_file_records ADD CONSTRAINT ck_sf_file_records_sha256 CHECK (sha256 ~ '^[0-9a-f]{64}$');

ALTER TABLE sf_file_cleanup_jobs ADD CONSTRAINT ck_sf_file_cleanup_jobs_attempts CHECK (attempts >= 0);

ALTER TABLE sf_login_attempts ADD CONSTRAINT ck_sf_login_attempts_failures CHECK (failures >= 0);

CREATE INDEX ix_sf_file_cleanup_jobs_lease_created ON sf_file_cleanup_jobs (lease_until, created_at);

CREATE INDEX ix_sf_file_cleanup_jobs_created ON sf_file_cleanup_jobs (created_at);

CREATE INDEX ix_sf_audit_events_created_at ON sf_audit_events (created_at);

CREATE INDEX ix_sf_audit_events_actor_id ON sf_audit_events (actor_id);

CREATE INDEX ix_sf_audit_events_request_id ON sf_audit_events (request_id);

CREATE INDEX ix_sf_login_sessions_expires_at ON sf_login_sessions (expires_at);

CREATE INDEX ix_sf_login_sessions_revoked_at ON sf_login_sessions (revoked_at);

CREATE UNIQUE INDEX ix_sf_users_username_lower ON sf_users (lower(username));

UPDATE alembic_version SET version_num='1_quality_remediation' WHERE alembic_version.version_num = '0_baseline';

COMMIT;

