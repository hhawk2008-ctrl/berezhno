-- Пользователи, коды входа по почте и сеансы.
CREATE TABLE users (
    id            bigserial PRIMARY KEY,
    email         text NOT NULL UNIQUE,
    timezone      text NOT NULL DEFAULT 'Europe/Moscow',
    created_at    timestamptz NOT NULL DEFAULT now(),
    last_login_at timestamptz
);

CREATE TABLE login_codes (
    id         bigserial PRIMARY KEY,
    email      text NOT NULL,
    code_hash  text NOT NULL,
    ip         text,
    attempts   integer NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL,
    used_at    timestamptz
);
CREATE INDEX login_codes_email_created ON login_codes (email, created_at DESC);
CREATE INDEX login_codes_ip_created ON login_codes (ip, created_at DESC);

CREATE TABLE auth_sessions (
    id         bigserial PRIMARY KEY,
    user_id    bigint NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    token_hash text NOT NULL UNIQUE,
    user_agent text,
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL
);
CREATE INDEX auth_sessions_user ON auth_sessions (user_id);
