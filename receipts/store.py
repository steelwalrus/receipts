"""SQLite storage for roles, entries and the competency framework."""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from . import dates
from .schema import MIGRATIONS
from .search import fts_query

TEXT_FIELDS = ("title", "summary", "situation", "task", "action", "result", "impact", "follow_ups", "raw")
ENTRY_FIELDS = TEXT_FIELDS + ("role_id", "happened_from", "happened_to", "approximate", "strength",
                              "competencies", "tags")
ROLE_FIELDS = ("title", "organisation", "started", "ended", "summary")

# What a story needs before it's interview-ready. Used for completeness and gap hints.
STORY_PARTS = {
    "when": lambda e: bool(e["happened_from"]),
    "role": lambda e: e["role_id"] is not None,
    "competencies": lambda e: bool(e["competencies"]),
    "situation": lambda e: bool(e["situation"].strip()),
    "action": lambda e: bool(e["action"].strip()),
    "result": lambda e: bool(e["result"].strip()),
    "impact": lambda e: bool(e["impact"].strip()),
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def default_path() -> Path:
    if os.environ.get("RECEIPTS_DB"):
        return Path(os.environ["RECEIPTS_DB"]).expanduser()
    if os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        base = Path(os.environ["LOCALAPPDATA"])
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "receipts" / "receipts.db"


def _tag(value) -> str:
    tag = str(value).strip().lower()
    if not tag or len(tag) > 40:
        raise ValueError(f"Tag '{value}' should be 1–40 characters")
    return tag


class Store:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else default_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._migrate()

    # -- plumbing ---------------------------------------------------------

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def _migrate(self):
        db = sqlite3.connect(self.path, isolation_level=None)
        try:
            db.execute("PRAGMA journal_mode = WAL")
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version > len(MIGRATIONS):
                raise RuntimeError(f"{self.path} was created by a newer version of Receipts")
            for number, migration in enumerate(MIGRATIONS[version:], start=version + 1):
                db.execute("BEGIN IMMEDIATE")
                try:
                    migration(db)
                    db.execute(f"PRAGMA user_version = {number}")
                    db.execute("COMMIT")
                except Exception:
                    db.execute("ROLLBACK")
                    raise
        finally:
            db.close()

    # -- competencies and profiles -----------------------------------------

    def competencies(self) -> list[dict]:
        with self._db() as db:
            rows = db.execute("""
                SELECT c.slug, c.name, c.area, c.description, COUNT(ec.entry_id) AS entry_count
                FROM competencies c LEFT JOIN entry_competencies ec ON ec.competency_id = c.id
                GROUP BY c.id ORDER BY c.position, c.name""")
            return [dict(r) for r in rows]

    def add_competency(self, slug: str, name: str, area: str, description: str = "") -> dict:
        slug = slug.strip().lower().replace(" ", "-")
        if not slug or not name.strip() or not area.strip():
            raise ValueError("A competency needs a slug, name and area")
        with self._db() as db:
            if db.execute("SELECT 1 FROM competencies WHERE slug = ?", (slug,)).fetchone():
                raise ValueError(f"Competency '{slug}' already exists")
            position = db.execute("SELECT COALESCE(MAX(position), 0) + 1 FROM competencies").fetchone()[0]
            db.execute("INSERT INTO competencies (slug, name, area, description, position) VALUES (?, ?, ?, ?, ?)",
                       (slug, name.strip(), area.strip(), description.strip(), position))
        return {"slug": slug, "name": name.strip(), "area": area.strip(), "description": description.strip()}

    def profiles(self) -> list[dict]:
        with self._db() as db:
            profiles = [dict(r) for r in db.execute("SELECT id, slug, name, description FROM profiles ORDER BY id")]
            for profile in profiles:
                rows = db.execute("""
                    SELECT c.slug, pc.core FROM profile_competencies pc
                    JOIN competencies c ON c.id = pc.competency_id
                    WHERE pc.profile_id = ? ORDER BY c.position""", (profile.pop("id"),))
                rows = list(rows)
                profile["core"] = [r["slug"] for r in rows if r["core"]]
                profile["useful"] = [r["slug"] for r in rows if not r["core"]]
            return profiles

    def set_profile(self, slug: str, name: str, core: list[str], useful: list[str] | None = None,
                    description: str = "") -> dict:
        """Create or replace a target-role profile (e.g. built from a job description)."""
        slug = slug.strip().lower().replace(" ", "-")
        if not slug or not name.strip() or not core:
            raise ValueError("A profile needs a slug, a name and at least one core competency")
        with self._db() as db:
            core_ids = self._competency_ids(db, core)
            useful_ids = [i for i in self._competency_ids(db, useful or []) if i not in core_ids]
            db.execute("DELETE FROM profiles WHERE slug = ?", (slug,))
            profile_id = db.execute("INSERT INTO profiles (slug, name, description) VALUES (?, ?, ?)",
                                    (slug, name.strip(), description.strip())).lastrowid
            db.executemany("INSERT INTO profile_competencies VALUES (?, ?, ?)",
                           [(profile_id, i, 1) for i in core_ids] + [(profile_id, i, 0) for i in useful_ids])
        return next(p for p in self.profiles() if p["slug"] == slug)

    def delete_profile(self, slug: str) -> None:
        with self._db() as db:
            if not db.execute("DELETE FROM profiles WHERE slug = ?", (slug,)).rowcount:
                raise KeyError(f"No profile '{slug}'")

    @staticmethod
    def _competency_ids(db, values) -> list[int]:
        if isinstance(values, str):
            values = [values]
        known = {}
        for row in db.execute("SELECT id, slug, name FROM competencies"):
            known[row["slug"]] = row["id"]
            known[row["name"].lower()] = row["id"]
        ids, unknown = [], []
        for value in values:
            key = str(value).strip().lower()
            if key in known:
                if known[key] not in ids:
                    ids.append(known[key])
            else:
                unknown.append(str(value))
        if unknown:
            slugs = sorted(r[0] for r in db.execute("SELECT slug FROM competencies"))
            raise ValueError(f"Unknown competency: {', '.join(unknown)}. Use one of: {', '.join(slugs)} "
                             "(or add a new competency first)")
        return ids

    # -- roles --------------------------------------------------------------

    def roles(self) -> list[dict]:
        with self._db() as db:
            rows = db.execute("""
                SELECT r.*, COUNT(e.id) AS entry_count FROM roles r
                LEFT JOIN entries e ON e.role_id = r.id
                GROUP BY r.id ORDER BY r.started, r.id""")
            return [_role_dict(r) for r in rows]

    def role(self, role_id: int) -> dict:
        for role in self.roles():
            if role["id"] == int(role_id):
                return role
        _missing("role", role_id)

    def add_role(self, title: str, started: str, organisation: str = "", ended: str | None = None,
                 summary: str = "") -> dict:
        values = _role_values({"title": title, "organisation": organisation, "started": started,
                               "ended": ended, "summary": summary})
        with self._db() as db:
            role_id = db.execute("""
                INSERT INTO roles (title, organisation, started, ended, summary, created_at, updated_at)
                VALUES (:title, :organisation, :started, :ended, :summary, :stamp, :stamp)""",
                {**values, "stamp": now()}).lastrowid
        return self.role(role_id)

    def update_role(self, role_id: int, **changes) -> dict:
        current = self.role(role_id)
        unknown = set(changes) - set(ROLE_FIELDS)
        if unknown:
            raise ValueError(f"Unknown role field: {', '.join(sorted(unknown))}")
        values = _role_values({**{k: current[k] for k in ROLE_FIELDS}, **changes})
        with self._db() as db:
            db.execute("""UPDATE roles SET title = :title, organisation = :organisation, started = :started,
                          ended = :ended, summary = :summary, updated_at = :u WHERE id = :id""",
                       {**values, "u": now(), "id": int(role_id)})
            for entry_id, in db.execute("SELECT id FROM entries WHERE role_id = ?", (int(role_id),)).fetchall():
                self._reindex(db, entry_id)
        return self.role(role_id)

    def delete_role(self, role_id: int) -> None:
        """Delete a role. Its entries stay, unassigned."""
        with self._db() as db:
            ids = [r[0] for r in db.execute("SELECT id FROM entries WHERE role_id = ?", (int(role_id),))]
            if not db.execute("DELETE FROM roles WHERE id = ?", (int(role_id),)).rowcount:
                _missing("role", role_id)
            for entry_id in ids:
                self._reindex(db, entry_id)

    @staticmethod
    def _role_for_date(db, when: str) -> int | None:
        """The role held at a given (partial) date; the most recently started one if they overlap."""
        point = dates.lower_bound(when)
        for row in db.execute("SELECT id, started, ended FROM roles ORDER BY started DESC, id DESC"):
            if dates.lower_bound(row["started"]) <= point and (
                    not row["ended"] or point <= dates.upper_bound(row["ended"])):
                return row["id"]
        return None

    # -- entries ------------------------------------------------------------

    def add_entry(self, title: str, **fields) -> dict:
        values = self._entry_values({"title": title, **fields}, partial=False)
        stamp = now()
        with self._db() as db:
            if "role_id" not in fields and values.get("happened_from"):
                values["role_id"] = self._role_for_date(db, values["happened_from"])
            self._check_role(db, values.get("role_id"))
            columns = [k for k in values if k not in ("competencies", "tags")]
            entry_id = db.execute(
                f"INSERT INTO entries ({', '.join(columns)}, created_at, updated_at) "
                f"VALUES ({', '.join('?' for _ in columns)}, ?, ?)",
                [values[k] for k in columns] + [stamp, stamp]).lastrowid
            self._set_links(db, entry_id, values)
            self._reindex(db, entry_id)
        return self.entry(entry_id)

    def update_entry(self, entry_id: int, **changes) -> dict:
        """Change only the fields given. Lists (competencies, tags) are replaced, not merged."""
        current = self.entry(entry_id)
        values = self._entry_values(changes, partial=True)
        if not values:
            return current
        with self._db() as db:
            if "role_id" not in changes and current["role_id"] is None and values.get("happened_from"):
                values["role_id"] = self._role_for_date(db, values["happened_from"])
            self._check_role(db, values.get("role_id"))
            start = values.get("happened_from", current["happened_from"])
            end = values.get("happened_to", current["happened_to"])
            _check_order(start, end)
            columns = [k for k in values if k not in ("competencies", "tags")]
            if columns:
                db.execute(f"UPDATE entries SET {', '.join(f'{k} = ?' for k in columns)}, updated_at = ? WHERE id = ?",
                           [values[k] for k in columns] + [now(), int(entry_id)])
            else:
                db.execute("UPDATE entries SET updated_at = ? WHERE id = ?", (now(), int(entry_id)))
            self._set_links(db, int(entry_id), values)
            self._reindex(db, int(entry_id))
        return self.entry(entry_id)

    def delete_entry(self, entry_id: int) -> None:
        with self._db() as db:
            if not db.execute("DELETE FROM entries WHERE id = ?", (int(entry_id),)).rowcount:
                _missing("entry", entry_id)
            db.execute("DELETE FROM entries_fts WHERE rowid = ?", (int(entry_id),))

    def entry(self, entry_id: int) -> dict:
        with self._db() as db:
            rows = db.execute(_ENTRY_SELECT + " WHERE e.id = ?", (int(entry_id),)).fetchall()
            if not rows:
                _missing("entry", entry_id)
            return self._hydrate(db, rows)[0]

    def entries(self, query: str = "", role_id: int | None = None, competency: str | None = None,
                tag: str | None = None, date_from: str | None = None, date_to: str | None = None,
                min_strength: int = 1, limit: int = 200) -> list[dict]:
        """Filter and search entries. Text search ranks by relevance; otherwise newest first."""
        where, params = ["e.strength >= ?"], [int(min_strength)]
        if role_id not in (None, ""):
            where.append("e.role_id = ?")
            params.append(int(role_id))
        if competency:
            where.append("e.id IN (SELECT ec.entry_id FROM entry_competencies ec "
                         "JOIN competencies c ON c.id = ec.competency_id WHERE c.slug = ?)")
            params.append(competency)
        if tag:
            where.append("e.id IN (SELECT entry_id FROM entry_tags WHERE tag = ?)")
            params.append(_tag(tag))
        with self._db() as db:
            rows = []
            if query and query.strip():
                for mode in ("AND", "OR"):
                    match = fts_query(query, mode)
                    if not match:
                        break
                    rows = db.execute(
                        _ENTRY_SELECT + " JOIN entries_fts f ON f.rowid = e.id WHERE entries_fts MATCH ? AND "
                        + " AND ".join(where) + " ORDER BY bm25(entries_fts, 4.0, 2.0, 1.0, 2.0)",
                        [match] + params).fetchall()
                    if rows:
                        break
            else:
                rows = db.execute(_ENTRY_SELECT + " WHERE " + " AND ".join(where)
                                  + " ORDER BY e.happened_from IS NULL, e.happened_from DESC, e.id DESC",
                                  params).fetchall()
            result = self._hydrate(db, rows)
        lo = dates.lower_bound(dates.normalise(date_from)) if date_from else None
        hi = dates.upper_bound(dates.normalise(date_to)) if date_to else None
        if lo or hi:
            result = [e for e in result if e["happened_from"] and _overlaps(e, lo, hi)]
        return result[:max(1, int(limit))]

    def tags(self) -> list[dict]:
        with self._db() as db:
            return [dict(r) for r in db.execute(
                "SELECT tag, COUNT(*) AS entry_count FROM entry_tags GROUP BY tag ORDER BY entry_count DESC, tag")]

    # -- views ----------------------------------------------------------------

    def timeline(self) -> dict:
        roles = self.roles()
        entries = sorted(self.entries(limit=100_000),
                         key=lambda e: (dates.lower_bound(e["happened_from"]) if e["happened_from"] else "9999", e["id"]))
        by_role = {r["id"]: [] for r in roles}
        unplaced = []
        for e in entries:
            (by_role[e["role_id"]] if e["role_id"] in by_role else unplaced).append(_brief(e))
        for role in roles:
            role["entries"] = by_role[role["id"]]
        return {"roles": roles, "unplaced": unplaced}

    def coverage(self, profile: str | None = None) -> dict:
        """Competency × role counts, and for a profile, which competencies are missing or thin."""
        roles = self.roles()
        competencies = self.competencies()
        entries = self.entries(limit=100_000)
        cells = {c["slug"]: {"total": 0, "by_role": {}, "best_strength": 0, "best_completeness": 0.0,
                             "entries": []} for c in competencies}
        for e in entries:
            for slug in e["competencies"]:
                cell = cells[slug]
                cell["total"] += 1
                key = str(e["role_id"]) if e["role_id"] is not None else "none"
                cell["by_role"][key] = cell["by_role"].get(key, 0) + 1
                cell["best_strength"] = max(cell["best_strength"], e["strength"])
                cell["best_completeness"] = max(cell["best_completeness"], e["completeness"])
                cell["entries"].append({"id": e["id"], "title": e["title"], "strength": e["strength"],
                                        "completeness": e["completeness"]})
        result = {"roles": [{"id": r["id"], "title": r["title"], "organisation": r["organisation"],
                             "label": r["label"]} for r in roles],
                  "competencies": [{**c, **cells[c["slug"]]} for c in competencies]}
        if profile:
            target = next((p for p in self.profiles() if p["slug"] == profile), None)
            if not target:
                raise KeyError(f"No profile '{profile}'")
            gaps = []
            for slug in target["core"] + target["useful"]:
                cell = cells[slug]
                core = slug in target["core"]
                if cell["total"] == 0:
                    status = "missing"
                elif cell["best_strength"] < 2 or cell["best_completeness"] < 0.5:
                    status = "thin"
                else:
                    status = "covered"
                gaps.append({"slug": slug, "core": core, "status": status, "entries": cell["total"]})
            result["profile"] = {**target, "competencies": gaps,
                                 "score": _score(gaps)}
        return result

    def stats(self) -> dict:
        with self._db() as db:
            counts = db.execute("""SELECT
                (SELECT COUNT(*) FROM roles) AS roles,
                (SELECT COUNT(*) FROM entries) AS entries,
                (SELECT COUNT(DISTINCT competency_id) FROM entry_competencies) AS competencies_covered,
                (SELECT COUNT(*) FROM competencies) AS competencies,
                (SELECT MIN(started) FROM roles) AS first_role""").fetchone()
        return dict(counts)

    def backup(self, destination: str | Path) -> Path:
        """Consistent copy of the live database (safe while the app is running)."""
        destination = Path(destination).expanduser()
        if destination.exists():
            raise ValueError(f"{destination} already exists")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as src:
            dst = sqlite3.connect(destination)
            try:
                src.backup(dst)
            finally:
                dst.close()
        return destination

    # -- internals -------------------------------------------------------------

    def _entry_values(self, fields: dict, partial: bool) -> dict:
        unknown = set(fields) - set(ENTRY_FIELDS)
        if unknown:
            raise ValueError(f"Unknown entry field: {', '.join(sorted(unknown))}")
        values = {}
        for key, value in fields.items():
            if key in TEXT_FIELDS:
                value = "" if value is None else str(value)
                if key == "title":
                    value = value.strip()
                    if not value or len(value) > 200:
                        raise ValueError("Title should be 1–200 characters")
                values[key] = value
            elif key in ("happened_from", "happened_to"):
                values[key] = dates.normalise(value)
            elif key == "approximate":
                values[key] = int(bool(value))
            elif key == "strength":
                if int(value) not in (1, 2, 3):
                    raise ValueError("Strength should be 1 (minor), 2 (solid) or 3 (headline story)")
                values[key] = int(value)
            elif key == "role_id":
                values[key] = None if value in (None, "") else int(value)
            elif key == "competencies":
                values[key] = list(value or []) if not isinstance(value, str) else [value]
            elif key == "tags":
                values[key] = sorted({_tag(t) for t in ([value] if isinstance(value, str) else value or [])})
        if not partial and "title" not in values:
            raise ValueError("An entry needs a title")
        if not partial:
            _check_order(values.get("happened_from"), values.get("happened_to"))
        return values

    @staticmethod
    def _check_role(db, role_id):
        if role_id is not None and not db.execute("SELECT 1 FROM roles WHERE id = ?", (role_id,)).fetchone():
            _missing("role", role_id)

    def _set_links(self, db, entry_id: int, values: dict):
        if "competencies" in values:
            ids = self._competency_ids(db, values["competencies"])
            db.execute("DELETE FROM entry_competencies WHERE entry_id = ?", (entry_id,))
            db.executemany("INSERT INTO entry_competencies VALUES (?, ?)", [(entry_id, i) for i in ids])
        if "tags" in values:
            db.execute("DELETE FROM entry_tags WHERE entry_id = ?", (entry_id,))
            db.executemany("INSERT INTO entry_tags VALUES (?, ?)", [(entry_id, t) for t in values["tags"]])

    def _reindex(self, db, entry_id: int):
        row = db.execute(_ENTRY_SELECT + " WHERE e.id = ?", (entry_id,)).fetchall()
        db.execute("DELETE FROM entries_fts WHERE rowid = ?", (entry_id,))
        if not row:
            return
        e = self._hydrate(db, row)[0]
        story = "\n".join(e[k] for k in ("situation", "task", "action", "result", "impact", "follow_ups", "raw"))
        labels = " ".join([e["role"]["title"], e["role"]["organisation"]] if e["role"] else []) + " " + \
            " ".join(e["competency_names"] + e["tags"])
        db.execute("INSERT INTO entries_fts (rowid, title, summary, story, labels) VALUES (?, ?, ?, ?, ?)",
                   (entry_id, e["title"], e["summary"], story, labels))

    @staticmethod
    def _hydrate(db, rows) -> list[dict]:
        entries = [dict(r) for r in rows]
        if not entries:
            return []
        ids = [e["id"] for e in entries]
        marks = ",".join("?" for _ in ids)
        comps, tags = {}, {}
        for r in db.execute(f"""SELECT ec.entry_id, c.slug, c.name FROM entry_competencies ec
                                JOIN competencies c ON c.id = ec.competency_id
                                WHERE ec.entry_id IN ({marks}) ORDER BY c.position""", ids):
            comps.setdefault(r["entry_id"], []).append((r["slug"], r["name"]))
        for r in db.execute(f"SELECT entry_id, tag FROM entry_tags WHERE entry_id IN ({marks}) ORDER BY tag", ids):
            tags.setdefault(r["entry_id"], []).append(r["tag"])
        for e in entries:
            e["competencies"] = [slug for slug, _ in comps.get(e["id"], [])]
            e["competency_names"] = [name for _, name in comps.get(e["id"], [])]
            e["tags"] = tags.get(e["id"], [])
            e["approximate"] = bool(e["approximate"])
            title, organisation = e.pop("role_title"), e.pop("role_organisation")
            e["role"] = {"id": e["role_id"], "title": title, "organisation": organisation} if e["role_id"] else None
            e["when"] = dates.span_label(e["happened_from"], e["happened_to"], e["approximate"])
            missing = [part for part, check in STORY_PARTS.items() if not check(e)]
            e["missing"] = missing
            e["completeness"] = round(1 - len(missing) / len(STORY_PARTS), 2)
        return entries


_ENTRY_SELECT = """SELECT e.*, r.title AS role_title, r.organisation AS role_organisation
                   FROM entries e LEFT JOIN roles r ON r.id = e.role_id"""


def _missing(kind, ident):
    raise KeyError(f"No {kind} with id {ident}")


def _check_order(start, end):
    if end and not start:
        raise ValueError("Set happened_from before happened_to")
    if start and end and dates.lower_bound(end) < dates.lower_bound(start):
        raise ValueError("happened_to is before happened_from")


def _overlaps(entry, lo, hi):
    start = dates.lower_bound(entry["happened_from"])
    end = dates.upper_bound(entry["happened_to"] or entry["happened_from"])
    return (not lo or end >= lo) and (not hi or start <= hi)


def _role_values(values: dict) -> dict:
    title = str(values.get("title") or "").strip()
    if not title or len(title) > 120:
        raise ValueError("Role title should be 1–120 characters")
    started = dates.normalise(values.get("started"))
    if not started:
        raise ValueError("A role needs a start date")
    ended = dates.normalise(values.get("ended"))
    _check_order(started, ended)
    return {"title": title, "organisation": str(values.get("organisation") or "").strip(),
            "started": started, "ended": ended, "summary": str(values.get("summary") or "")}


def _role_dict(row) -> dict:
    role = dict(row)
    role["label"] = dates.span_label(role["started"], role["ended"], open_ended="present")
    start = dates.lower_bound(role["started"])
    end = dates.upper_bound(role["ended"]) if role["ended"] else datetime.now(timezone.utc).date().isoformat()
    months = (int(end[:4]) - int(start[:4])) * 12 + int(end[5:7]) - int(start[5:7]) + 1
    role["months"] = max(1, months)
    return role


def _brief(e: dict) -> dict:
    keys = ("id", "title", "summary", "when", "happened_from", "happened_to", "approximate", "strength",
            "competencies", "competency_names", "tags", "completeness", "missing", "role_id")
    return {k: e[k] for k in keys}


def _score(gaps: list[dict]) -> dict:
    core = [g for g in gaps if g["core"]]
    return {"core_total": len(core),
            "core_covered": sum(g["status"] == "covered" for g in core),
            "core_thin": sum(g["status"] == "thin" for g in core),
            "core_missing": sum(g["status"] == "missing" for g in core)}
