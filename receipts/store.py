"""SQLite persistence. No model calls; sources and note revisions are append-only."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 1
APP_ID = 1380270928
CODE_ROOT = Path(__file__).resolve().parents[1]


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def stable_id(value):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "receipts:" + value))


def json_text(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def require_text(value, field, maximum=2_000_000):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be non-empty text")
    if len(value) > maximum:
        raise ValueError(f"{field} is too long (maximum {maximum:,} characters)")
    return value  # Deliberately do not strip or normalise source text.


def default_vault():
    if os.environ.get("RECEIPTS_VAULT"):
        return Path(os.environ["RECEIPTS_VAULT"]).expanduser().resolve()
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local" / "share"))
    return base / "Receipts"


SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS imports (
    id TEXT PRIMARY KEY, filename TEXT NOT NULL, sha256 TEXT NOT NULL UNIQUE,
    payload BLOB NOT NULL, imported_at TEXT NOT NULL, notice TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY, title TEXT NOT NULL, external_id TEXT UNIQUE,
    created_at TEXT NOT NULL, metadata TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL REFERENCES conversations(id),
    role TEXT NOT NULL CHECK(role IN ('user','assistant','system','tool')),
    body TEXT NOT NULL, sha256 TEXT NOT NULL, created_at TEXT NOT NULL,
    recorded_at TEXT NOT NULL, external_id TEXT UNIQUE, metadata TEXT NOT NULL DEFAULT '{}',
    import_id TEXT REFERENCES imports(id)
);
CREATE INDEX IF NOT EXISTS messages_conversation ON messages(conversation_id, created_at);
CREATE TABLE IF NOT EXISTS notes (
    id TEXT PRIMARY KEY, title TEXT NOT NULL, body TEXT NOT NULL, tags TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('draft','reviewed')), created_at TEXT NOT NULL,
    supersedes_id TEXT UNIQUE REFERENCES notes(id)
);
CREATE TABLE IF NOT EXISTS note_sources (
    note_id TEXT NOT NULL REFERENCES notes(id), message_id TEXT NOT NULL REFERENCES messages(id),
    PRIMARY KEY(note_id, message_id)
);
CREATE VIRTUAL TABLE IF NOT EXISTS search_index USING fts5(
    id UNINDEXED, kind UNINDEXED, title, body, tags, role UNINDEXED,
    tokenize='porter unicode61 remove_diacritics 2'
);
CREATE TRIGGER IF NOT EXISTS immutable_messages_update BEFORE UPDATE ON messages
BEGIN SELECT RAISE(ABORT, 'Original messages are immutable; append a correction'); END;
CREATE TRIGGER IF NOT EXISTS immutable_messages_delete BEFORE DELETE ON messages
BEGIN SELECT RAISE(ABORT, 'Original messages are immutable'); END;
CREATE TRIGGER IF NOT EXISTS immutable_notes_update BEFORE UPDATE ON notes
BEGIN SELECT RAISE(ABORT, 'Create a new note revision'); END;
CREATE TRIGGER IF NOT EXISTS immutable_notes_delete BEFORE DELETE ON notes
BEGIN SELECT RAISE(ABORT, 'Note revisions are immutable'); END;
CREATE TRIGGER IF NOT EXISTS immutable_imports_update BEFORE UPDATE ON imports
BEGIN SELECT RAISE(ABORT, 'Original imports are immutable'); END;
CREATE TRIGGER IF NOT EXISTS immutable_imports_delete BEFORE DELETE ON imports
BEGIN SELECT RAISE(ABORT, 'Original imports are immutable'); END;
"""


class Store:
    def __init__(self, vault=None):
        self.vault = Path(vault or default_vault()).expanduser().resolve()
        if self.vault == CODE_ROOT or CODE_ROOT in self.vault.parents:
            raise ValueError("The private vault must be outside the application checkout")
        self.vault.mkdir(parents=True, exist_ok=True)
        self.path = self.vault / "receipts.sqlite3"
        from .locking import VaultLock
        self.lock = VaultLock(self.vault / ".vault.lock")
        with self.connection() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            app_id = db.execute("PRAGMA application_id").fetchone()[0]
            if version > SCHEMA_VERSION or app_id not in (0, APP_ID):
                raise ValueError("Unsupported database; upgrade Receipts or select its own vault")
            db.executescript(SCHEMA)
            db.execute(f"PRAGMA application_id={APP_ID}")
            db.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            db.execute("INSERT OR IGNORE INTO meta VALUES ('database_id', ?)", (str(uuid.uuid4()),))

    @contextmanager
    def connection(self):
        with self.lock.hold():
            db = sqlite3.connect(self.path, timeout=15)
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("PRAGMA journal_mode=WAL")
            try:
                with db:
                    yield db
            finally:
                db.close()

    def _conversation(self, db, title, external_id=None, metadata=None, created_at=None):
        require_text(title, "title", 300)
        cid = stable_id(external_id) if external_id else str(uuid.uuid4())
        db.execute("INSERT OR IGNORE INTO conversations VALUES (?,?,?,?,?)",
                   (cid, title, external_id, created_at or now(), json_text(metadata or {})))
        return cid

    def create_conversation(self, title):
        with self.connection() as db:
            cid = self._conversation(db, title)
        return self.conversation(cid)

    def _append(self, db, conversation_id, body, role="user", external_id=None,
                created_at=None, metadata=None, import_id=None):
        require_text(body, "body")
        if role not in ("user", "assistant", "system", "tool"):
            raise ValueError("Invalid message role")
        conv = db.execute("SELECT * FROM conversations WHERE id=?", (conversation_id,)).fetchone()
        if not conv:
            raise ValueError("Conversation does not exist")
        if external_id:
            existing = db.execute("SELECT * FROM messages WHERE external_id=?", (external_id,)).fetchone()
            if existing:
                if (existing["body"], existing["role"], existing["conversation_id"]) != (body, role, conversation_id):
                    raise ValueError(f"Source {external_id} already exists with different content; nothing imported")
                return existing["id"], False
        mid = stable_id(external_id) if external_id else str(uuid.uuid4())
        db.execute("INSERT INTO messages VALUES (?,?,?,?,?,?,?,?,?,?)",
                   (mid, conversation_id, role, body, digest(body), created_at or now(), now(),
                    external_id, json_text(metadata or {}), import_id))
        db.execute("INSERT INTO search_index VALUES (?,?,?,?,?,?)",
                   (mid, "message", conv["title"], body, "", role))
        return mid, True

    def append(self, conversation_id, body, role="user", external_id=None, metadata=None):
        with self.connection() as db:
            mid, _ = self._append(db, conversation_id, body, role, external_id, metadata=metadata)
        return self.message(mid)

    def conversations(self):
        with self.connection() as db:
            return [dict(r) for r in db.execute("""SELECT c.*, COUNT(m.id) AS message_count,
                MAX(COALESCE(m.created_at,c.created_at)) AS last_message
                FROM conversations c LEFT JOIN messages m ON c.id=m.conversation_id
                GROUP BY c.id ORDER BY last_message DESC""")]

    def recent_messages(self, limit=100):
        with self.connection() as db:
            return [self._message_dict(r) for r in db.execute("""SELECT m.*,c.title AS conversation_title
                FROM messages m JOIN conversations c ON c.id=m.conversation_id
                ORDER BY m.created_at DESC,m.rowid DESC LIMIT ?""",(limit,))]

    def conversation(self, cid):
        with self.connection() as db:
            row = db.execute("SELECT * FROM conversations WHERE id=?", (cid,)).fetchone()
            if not row:
                raise KeyError("Conversation not found")
            result = dict(row)
            result["metadata"] = json.loads(result["metadata"])
            result["messages"] = [self._message_dict(r) for r in db.execute(
                "SELECT * FROM messages WHERE conversation_id=? ORDER BY created_at, rowid", (cid,))]
            return result

    @staticmethod
    def _message_dict(row):
        data = dict(row)
        data["metadata"] = json.loads(data["metadata"])
        return data

    def message(self, mid):
        with self.connection() as db:
            row = db.execute("""SELECT m.*, c.title AS conversation_title FROM messages m
                JOIN conversations c ON c.id=m.conversation_id WHERE m.id=?""", (mid,)).fetchone()
            if not row:
                raise KeyError("Message not found")
            return self._message_dict(row)

    def save_note(self, title, body, source_ids, tags=None, status="draft", supersedes_id=None):
        require_text(title, "title", 300)
        require_text(body, "body")
        if not isinstance(source_ids, list) or not source_ids or not all(isinstance(x,str) for x in source_ids):
            raise ValueError("A note needs at least one original message as a source")
        if status not in ("draft", "reviewed"):
            raise ValueError("Invalid note status")
        tags = tags or []
        if not isinstance(tags, list) or len(tags) > 30 or not all(isinstance(t,str) and 0 < len(t.strip()) <= 80 for t in tags):
            raise ValueError("Use up to 30 short text tags")
        tags = sorted(set(t.strip().lower() for t in tags))
        nid = str(uuid.uuid4())
        with self.connection() as db:
            if supersedes_id:
                if not db.execute("SELECT id FROM notes WHERE id=?", (supersedes_id,)).fetchone():
                    raise ValueError("Previous note does not exist")
                if db.execute("SELECT id FROM notes WHERE supersedes_id=?", (supersedes_id,)).fetchone():
                    raise ValueError("This note has a newer revision. Open it before editing")
            db.execute("INSERT INTO notes VALUES (?,?,?,?,?,?,?)",
                       (nid,title,body,json_text(tags),status,now(),supersedes_id))
            for mid in set(source_ids):
                if not db.execute("SELECT id FROM messages WHERE id=?",(mid,)).fetchone():
                    raise ValueError("A selected source does not exist")
                db.execute("INSERT INTO note_sources VALUES (?,?)",(nid,mid))
            if supersedes_id:
                db.execute("DELETE FROM search_index WHERE id=?",(supersedes_id,))
            db.execute("INSERT INTO search_index VALUES (?,?,?,?,?,?)",(nid,"note",title,body," ".join(tags),"note"))
        return self.note(nid)

    def notes(self):
        with self.connection() as db:
            return [self._note_dict(r) for r in db.execute("""SELECT n.*,
                (SELECT COUNT(*) FROM note_sources WHERE note_id=n.id) AS source_count
                FROM notes n WHERE NOT EXISTS(SELECT 1 FROM notes newer WHERE newer.supersedes_id=n.id)
                ORDER BY n.created_at DESC""")]

    @staticmethod
    def _note_dict(row):
        data = dict(row)
        data["tags"] = json.loads(data["tags"])
        return data

    def note(self, nid):
        with self.connection() as db:
            row = db.execute("SELECT * FROM notes WHERE id=?",(nid,)).fetchone()
            if not row:
                raise KeyError("Note not found")
            result = self._note_dict(row)
            ids = [r[0] for r in db.execute("SELECT message_id FROM note_sources WHERE note_id=?",(nid,))]
            result["sources"] = [self.message(mid) for mid in ids]
            result["newer_revision"] = next((r[0] for r in db.execute("SELECT id FROM notes WHERE supersedes_id=?",(nid,))),None)
            return result

    def stats(self):
        with self.connection() as db:
            result = {table: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                      for table in ("conversations","messages","imports")}
            result["user_messages"] = db.execute("SELECT COUNT(*) FROM messages WHERE role='user'").fetchone()[0]
            result["characters"] = db.execute("SELECT COALESCE(SUM(LENGTH(body)),0) FROM messages").fetchone()[0]
            result["notes"] = len(self.notes())
            result["tags"] = sorted({tag for n in self.notes() for tag in n["tags"]})
            result["import_notices"] = [r[0] for r in db.execute("SELECT notice FROM imports WHERE notice<>''")]
            return result

    def export(self):
        """Lossless portable JSON export, including raw imported files as base64."""
        import base64
        with self.connection() as db:
            db.execute("BEGIN")
            tables = {}
            for table in ("meta","imports","conversations","messages","notes","note_sources"):
                rows = [dict(r) for r in db.execute(f"SELECT * FROM {table} ORDER BY 1,2")]
                for row in rows:
                    if "payload" in row:
                        row["payload_base64"] = base64.b64encode(row.pop("payload")).decode("ascii")
                tables[table] = rows
        return {"format":"receipts-export-v1","schema_version":SCHEMA_VERSION,"tables":tables}

    def fingerprint(self):
        return digest(json_text(self.export()))

    def snapshot(self, destination):
        destination = Path(destination).expanduser().resolve()
        if destination == self.path or destination == CODE_ROOT or CODE_ROOT in destination.parents:
            raise ValueError("Snapshot must be outside the public checkout and not the live database")
        if destination.exists():
            raise ValueError("Snapshot destination already exists; choose a new filename")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as src:
            dst = sqlite3.connect(destination)
            try:
                src.backup(dst)
                dst.execute("PRAGMA journal_mode=DELETE")
                if dst.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise ValueError("Snapshot integrity check failed")
            finally:
                dst.close()
        return destination

    def search(self, query, kind="all", include_assistant=False, interview=False, limit=30):
        from .search import query_terms
        require_text(query,"query",2000)
        terms = query_terms(query, expand=interview)
        if not terms:
            return {"query":query,"terms":[],"results":[],"method":"Local full-text search"}
        match = " OR ".join('"' + t.replace('"','""') + '"' for t in terms)
        conditions = ["search_index MATCH ?"]
        params = [match]
        if kind in ("message","note"):
            conditions.append("kind=?")
            params.append(kind)
        if not include_assistant:
            conditions.append("role IN ('user','note')")
        params.append(max(1,min(int(limit),100)))
        with self.connection() as db:
            rows = db.execute("""SELECT id,kind,title,role,
                snippet(search_index,3,'','',' … ',48) AS excerpt,
                bm25(search_index,0,0,2,1,3,0) AS rank
                FROM search_index WHERE """ + " AND ".join(conditions) + " ORDER BY rank LIMIT ?",params).fetchall()
            results = []
            for row in rows:
                item = dict(row)
                if item["kind"] == "message":
                    source = self.message(item["id"])
                    item.update(created_at=source["created_at"],conversation_id=source["conversation_id"],tags=[])
                else:
                    note = self.note(item["id"])
                    item.update(created_at=note["created_at"],tags=note["tags"],status=note["status"],source_ids=[s["id"] for s in note["sources"]])
                results.append(item)
        return {"query":query,"terms":terms,"results":results,
                "method":"Local full-text search with topic expansion" if interview else "Local full-text search"}
