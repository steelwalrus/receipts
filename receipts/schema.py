"""Schema migrations and the starting competency framework.

Each migration runs once, in order, and bumps PRAGMA user_version. Add new
migrations to the end of MIGRATIONS; never edit one that has shipped.
"""

COMPETENCIES = [
    # (slug, name, area, description)
    ("hiring", "Hiring", "People", "Defining roles, interviewing, closing candidates, building hiring processes."),
    ("coaching", "Coaching & mentoring", "People", "Developing individuals through feedback, mentoring and stretch."),
    ("performance", "Performance management", "People", "Setting expectations, handling underperformance, PIPs, exits."),
    ("talent", "Talent & career growth", "People", "Spotting potential, promotions, internal moves, succession."),
    ("difficult-conversations", "Difficult conversations", "People", "Delivering bad news, conflict, pushback, sensitive situations."),
    ("culture", "Team culture & engagement", "People", "Morale, trust, retention, psychological safety."),
    ("org-design", "Org design", "Organisation", "Team topology, reporting lines, role definitions such as EM/TL splits."),
    ("change", "Leading change", "Organisation", "Restructures, mergers, redundancies, transitions."),
    ("scaling", "Scaling teams", "Organisation", "Growing headcount and keeping the organisation working as it grows."),
    ("delivery", "Delivery & execution", "Delivery", "Planning, shipping, unblocking, landing projects."),
    ("process", "Engineering process", "Delivery", "Ways of working, agile practice, quality, developer experience."),
    ("incidents", "Incidents & reliability", "Delivery", "Running incidents, postmortems, SRE, uptime."),
    ("architecture", "Architecture & tech strategy", "Technical", "System design, technical direction, migrations, tech debt."),
    ("platform", "Platform & DevOps", "Technical", "Infrastructure, CI/CD, observability, cloud."),
    ("security", "Security & compliance", "Technical", "AppSec, DevSecOps, audits, data protection."),
    ("data", "Data & analytics", "Technical", "Data platforms, reporting, BI, data quality."),
    ("ai", "AI & innovation", "Technical", "Adopting AI and new technology, prototypes, skunkworks."),
    ("stakeholders", "Stakeholders & communication", "Business", "Working with execs, SLT, peers; presenting; influencing."),
    ("commercial", "Commercial & cost", "Business", "Budgets, cost reduction, vendor spend, ROI, business cases."),
    ("product", "Product partnership", "Business", "Working with product, prioritisation, roadmaps."),
    ("customer", "Customers & support", "Business", "Support operations, customer escalations, onboarding, migrations."),
]

PROFILES = [
    # (slug, name, description, core, useful)
    ("engineering-manager", "Engineering Manager",
     "Runs one or more teams: people, delivery and process.",
     ["hiring", "coaching", "performance", "difficult-conversations", "culture", "delivery", "process", "stakeholders"],
     ["talent", "incidents", "architecture", "product"]),
    ("director-of-engineering", "Director of Engineering",
     "Leads managers across several teams; owns org shape and outcomes.",
     ["org-design", "change", "hiring", "talent", "performance", "culture", "delivery", "stakeholders", "commercial", "scaling"],
     ["coaching", "process", "incidents", "architecture", "platform", "security", "product"]),
    ("head-of-engineering", "Head of Engineering / VP",
     "Owns the engineering function, its strategy and its budget.",
     ["org-design", "change", "scaling", "talent", "culture", "delivery", "architecture", "security", "stakeholders", "commercial"],
     ["hiring", "performance", "incidents", "platform", "data", "ai", "product", "customer"]),
    ("cto", "CTO",
     "Technology strategy and executive leadership.",
     ["architecture", "security", "ai", "org-design", "change", "scaling", "stakeholders", "commercial", "product"],
     ["talent", "culture", "platform", "data", "customer", "delivery"]),
]

V1 = """
CREATE TABLE roles (
    id           INTEGER PRIMARY KEY,
    title        TEXT NOT NULL,
    organisation TEXT NOT NULL DEFAULT '',
    started      TEXT NOT NULL,
    ended        TEXT,
    summary      TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);

CREATE TABLE competencies (
    id          INTEGER PRIMARY KEY,
    slug        TEXT NOT NULL UNIQUE,
    name        TEXT NOT NULL,
    area        TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    position    INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE entries (
    id            INTEGER PRIMARY KEY,
    title         TEXT NOT NULL,
    summary       TEXT NOT NULL DEFAULT '',
    role_id       INTEGER REFERENCES roles(id) ON DELETE SET NULL,
    happened_from TEXT,
    happened_to   TEXT,
    approximate   INTEGER NOT NULL DEFAULT 0,
    situation     TEXT NOT NULL DEFAULT '',
    task          TEXT NOT NULL DEFAULT '',
    action        TEXT NOT NULL DEFAULT '',
    result        TEXT NOT NULL DEFAULT '',
    impact        TEXT NOT NULL DEFAULT '',
    follow_ups    TEXT NOT NULL DEFAULT '',
    raw           TEXT NOT NULL DEFAULT '',
    strength      INTEGER NOT NULL DEFAULT 2 CHECK (strength BETWEEN 1 AND 3),
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
CREATE INDEX entries_role ON entries(role_id);
CREATE INDEX entries_when ON entries(happened_from);

CREATE TABLE entry_competencies (
    entry_id      INTEGER NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
    competency_id INTEGER NOT NULL REFERENCES competencies(id) ON DELETE CASCADE,
    PRIMARY KEY (entry_id, competency_id)
);

CREATE TABLE entry_tags (
    entry_id INTEGER NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
    tag      TEXT NOT NULL,
    PRIMARY KEY (entry_id, tag)
);

CREATE TABLE profiles (
    id          INTEGER PRIMARY KEY,
    slug        TEXT NOT NULL UNIQUE,
    name        TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT ''
);

CREATE TABLE profile_competencies (
    profile_id    INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    competency_id INTEGER NOT NULL REFERENCES competencies(id) ON DELETE CASCADE,
    core          INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (profile_id, competency_id)
);

CREATE VIRTUAL TABLE entries_fts USING fts5(
    title, summary, story, labels,
    tokenize = 'porter unicode61 remove_diacritics 2'
);
"""


def seed(db):
    db.executemany(
        "INSERT INTO competencies (slug, name, area, description, position) VALUES (?, ?, ?, ?, ?)",
        [(slug, name, area, desc, i) for i, (slug, name, area, desc) in enumerate(COMPETENCIES)],
    )
    for slug, name, description, core, useful in PROFILES:
        profile_id = db.execute(
            "INSERT INTO profiles (slug, name, description) VALUES (?, ?, ?)", (slug, name, description)
        ).lastrowid
        for comp, is_core in [(c, 1) for c in core] + [(c, 0) for c in useful]:
            db.execute(
                "INSERT INTO profile_competencies (profile_id, competency_id, core) "
                "SELECT ?, id, ? FROM competencies WHERE slug = ?",
                (profile_id, is_core, comp),
            )


def run_script(db, script):
    # executescript() would commit the migration's transaction early, so run statements one by one.
    for statement in script.split(";\n"):
        if statement.strip():
            db.execute(statement)


def migrate_v1(db):
    run_script(db, V1)
    seed(db)


MIGRATIONS = [migrate_v1]
