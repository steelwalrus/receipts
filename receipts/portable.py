"""JSON export/import (for backups and moving machines) and a readable Markdown export."""

from __future__ import annotations

from .store import Store, now

FORMAT = "receipts/1"
_ENTRY_KEYS = ("title", "summary", "happened_from", "happened_to", "approximate", "situation", "task",
               "action", "result", "impact", "follow_ups", "raw", "strength", "competencies", "tags")


def export_json(store: Store) -> dict:
    roles = store.roles()
    keys = {r["id"]: f"role-{i + 1}" for i, r in enumerate(roles)}
    return {
        "format": FORMAT,
        "exported_at": now(),
        "competencies": [{k: c[k] for k in ("slug", "name", "area", "description")} for c in store.competencies()],
        "profiles": store.profiles(),
        "roles": [{"key": keys[r["id"]], **{k: r[k] for k in ("title", "organisation", "started", "ended", "summary")}}
                  for r in roles],
        "entries": [{**{k: e[k] for k in _ENTRY_KEYS}, "role": keys.get(e["role_id"])}
                    for e in store.entries(limit=1_000_000)],
    }


def import_json(store: Store, data: dict) -> dict:
    """Merge an export into this database. Existing roles are matched, duplicate entries skipped."""
    if data.get("format") != FORMAT:
        raise ValueError(f"Expected a {FORMAT} export")
    known = {c["slug"] for c in store.competencies()}
    for comp in data.get("competencies", []):
        if comp["slug"] not in known:
            store.add_competency(comp["slug"], comp["name"], comp["area"], comp.get("description", ""))
    existing_profiles = {p["slug"] for p in store.profiles()}
    for profile in data.get("profiles", []):
        if profile["slug"] not in existing_profiles:
            store.set_profile(profile["slug"], profile["name"], profile["core"], profile.get("useful"),
                              profile.get("description", ""))

    role_ids, roles_added = {}, 0
    current = {(r["title"], r["organisation"], r["started"]): r["id"] for r in store.roles()}
    for role in data.get("roles", []):
        match = (role["title"], role.get("organisation", ""), role["started"])
        if match not in current:
            current[match] = store.add_role(role["title"], role["started"], role.get("organisation", ""),
                                            role.get("ended"), role.get("summary", ""))["id"]
            roles_added += 1
        role_ids[role["key"]] = current[match]

    seen = {(e["title"], e["happened_from"]) for e in store.entries(limit=1_000_000)}
    added = skipped = 0
    for entry in data.get("entries", []):
        fields = {k: entry[k] for k in _ENTRY_KEYS if k in entry and k != "title"}
        if entry.get("role") in role_ids:
            fields["role_id"] = role_ids[entry["role"]]
        key = (entry["title"], fields.get("happened_from"))
        if key in seen:
            skipped += 1
            continue
        store.add_entry(entry["title"], **fields)
        seen.add(key)
        added += 1
    return {"roles_added": roles_added, "entries_added": added, "entries_skipped": skipped}


def export_markdown(store: Store) -> str:
    timeline = store.timeline()
    names = {c["slug"]: c["name"] for c in store.competencies()}
    lines = ["# Career record", ""]

    def write_entry(e):
        full = store.entry(e["id"])
        lines.extend([f"### {full['title']}", ""])
        meta = [full["when"]] if full["when"] else []
        if full["competencies"]:
            meta.append(", ".join(names[c] for c in full["competencies"]))
        if meta:
            lines.extend([f"*{' · '.join(meta)}*", ""])
        if full["summary"]:
            lines.extend([full["summary"], ""])
        for key in ("situation", "task", "action", "result", "impact"):
            if full[key].strip():
                lines.extend([f"**{key.capitalize()}:** {full[key].strip()}", ""])
        if full["follow_ups"].strip():
            lines.extend([f"**Still to confirm:** {full['follow_ups'].strip()}", ""])

    for role in reversed(timeline["roles"]):
        heading = role["title"] + (f", {role['organisation']}" if role["organisation"] else "")
        lines.extend([f"## {heading}", "", f"*{role['label']}*", ""])
        if role["summary"]:
            lines.extend([role["summary"], ""])
        for e in reversed(role["entries"]):
            write_entry(e)
    if timeline["unplaced"]:
        lines.extend(["## Not yet placed on the timeline", ""])
        for e in timeline["unplaced"]:
            write_entry(e)
    return "\n".join(lines).rstrip() + "\n"
