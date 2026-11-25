-- Знакомство, цели, шаги, отметки, копилка и силы по дням.
ALTER TABLE users
    ADD COLUMN name                text,
    ADD COLUMN morning_time        time NOT NULL DEFAULT '08:30',
    ADD COLUMN evening_time        time NOT NULL DEFAULT '21:30',
    ADD COLUMN onboarded_at        timestamptz,
    ADD COLUMN consent_selfhelp_at timestamptz,
    ADD COLUMN consent_pd_at       timestamptz,
    ADD COLUMN crisis_at           timestamptz;

CREATE TABLE goals (
    id          bigserial PRIMARY KEY,
    user_id     bigint NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    title       text NOT NULL,
    answers     jsonb NOT NULL DEFAULT '{}',
    main_risk   text,
    draft_plan  jsonb,
    plan_source text,
    status      text NOT NULL DEFAULT 'draft',  -- draft, active, paused, done, archived
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX goals_user ON goals (user_id, status);

CREATE TABLE goal_stages (
    id       bigserial PRIMARY KEY,
    goal_id  bigint NOT NULL REFERENCES goals (id) ON DELETE CASCADE,
    position integer NOT NULL,
    title    text NOT NULL,
    done_at  timestamptz
);
CREATE INDEX goal_stages_goal ON goal_stages (goal_id, position);

CREATE TABLE steps (
    id         bigserial PRIMARY KEY,
    user_id    bigint NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    goal_id    bigint NOT NULL REFERENCES goals (id) ON DELETE CASCADE,
    title      text NOT NULL,
    minutes    integer NOT NULL DEFAULT 15,
    if_then    text,
    day        date NOT NULL,
    status     text NOT NULL DEFAULT 'planned',  -- planned, done, partial, not_done
    checked_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX steps_goal_day ON steps (goal_id, day DESC, id DESC);

CREATE TABLE evidence (
    id         bigserial PRIMARY KEY,
    user_id    bigint NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    step_id    bigint REFERENCES steps (id) ON DELETE SET NULL,
    kind       text NOT NULL,  -- step_done, step_partial, insight, return
    text       text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX evidence_user ON evidence (user_id, created_at DESC);

CREATE TABLE day_energy (
    user_id bigint NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    day     date NOT NULL,
    value   smallint NOT NULL CHECK (value BETWEEN 1 AND 5),
    PRIMARY KEY (user_id, day)
);
