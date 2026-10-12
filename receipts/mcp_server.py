"""MCP server: lets Claude, Codex or any MCP client read and curate the career record.

Run with `python -m receipts mcp` (stdio). Requires the `mcp` package.
"""

from __future__ import annotations

from pathlib import Path

import functools

try:  # mcp >= 2
    from mcp.server.mcpserver import MCPServer as _Server
    from mcp.server.mcpserver.exceptions import ToolError
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as _Server
    from mcp.server.fastmcp.exceptions import ToolError

from .store import Store

SKILLS = Path(__file__).parent / "skills"

INSTRUCTIONS = """\
Receipts is the user's private career record: roles on a timeline, and entries (stories,
achievements, things they handled) tagged with competencies so they can prepare for interviews.

- Call `overview` first in a session to see roles, competency slugs and profiles.
- One story per entry. A long ramble usually holds several entries; split them.
- Dates can be partial ("2019", "2019-06", "2021-Q3"). Set approximate=true when the user is unsure.
  Leave role_id empty and it is inferred from the date.
- Write summaries and STAR fields in plain first person, in the user's voice. Don't inflate.
- Never invent numbers, dates or outcomes. Put open questions in `follow_ups` instead.
- Keep `raw` to the user's own words for that story, lightly trimmed, not your paraphrase.
- Keep unnecessary personal details about other people (health, immigration, nationality) out of entries.
- Search before adding, and update an existing entry rather than duplicating it.
For detailed workflows use the prompts: capture, prep, review.
"""


def _brief(e: dict, detail: bool = False) -> dict:
    out = {"id": e["id"], "title": e["title"], "when": e["when"],
           "role": f"{e['role']['title']}, {e['role']['organisation']}".strip(", ") if e["role"] else None,
           "competencies": e["competencies"], "tags": e["tags"], "strength": e["strength"],
           "completeness": e["completeness"], "missing": e["missing"], "summary": e["summary"]}
    if detail:
        out.update({k: e[k] for k in ("situation", "task", "action", "result", "impact", "follow_ups")})
    return out


def _skill_text(name: str) -> str:
    text = (SKILLS / name / "SKILL.md").read_text(encoding="utf-8")
    if text.startswith("---"):
        text = text.split("---", 2)[2]
    return text.strip()


def build(store: Store) -> _Server:
    server = _Server("receipts", instructions=INSTRUCTIONS)

    def tool(fn):
        """Register a tool whose validation errors reach the model as readable messages."""
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except (ValueError, KeyError) as error:
                raise ToolError(str(error).strip("'\"")) from error
        return server.tool()(wrapper)

    @tool
    def overview() -> dict:
        """Roles, competency slugs (with entry counts), target-role profiles, tags and totals."""
        return {
            "stats": store.stats(),
            "roles": [{k: r[k] for k in ("id", "title", "organisation", "label", "entry_count")} for r in store.roles()],
            "competencies": [{k: c[k] for k in ("slug", "name", "area", "entry_count")} for c in store.competencies()],
            "profiles": [{"slug": p["slug"], "name": p["name"]} for p in store.profiles()],
            "tags": [t["tag"] for t in store.tags()],
        }

    @tool
    def add_role(title: str, started: str, organisation: str = "", ended: str | None = None,
                 summary: str = "") -> dict:
        """Add a role to the timeline. Dates are partial ISO (2019, 2019-06). Leave `ended` empty for a current role."""
        return store.add_role(title, started, organisation, ended, summary)

    @tool
    def update_role(role_id: int, title: str | None = None, organisation: str | None = None,
                    started: str | None = None, ended: str | None = None, summary: str | None = None) -> dict:
        """Change a role. Only the fields you pass are updated. Pass ended="present" to make it current."""
        changes = {k: v for k, v in dict(title=title, organisation=organisation, started=started,
                                          ended=ended, summary=summary).items() if v is not None}
        return store.update_role(role_id, **changes)

    @tool
    def add_entry(title: str, summary: str, happened_from: str | None = None, happened_to: str | None = None,
                  approximate: bool = False, role_id: int | None = None, competencies: list[str] | None = None,
                  tags: list[str] | None = None, situation: str = "", task: str = "", action: str = "",
                  result: str = "", impact: str = "", follow_ups: str = "", raw: str = "",
                  strength: int = 2) -> dict:
        """Record one story or achievement.

        summary: two or three plain sentences. competencies: slugs from `overview`.
        tags: free-form (projects, teams, technologies). impact: concrete numbers or outcomes only.
        follow_ups: what's still unknown or needs checking. raw: the user's own words for this story.
        strength: 1 minor, 2 solid, 3 headline story. role_id: leave empty to infer from the date.
        """
        fields = dict(summary=summary, happened_from=happened_from, happened_to=happened_to,
                      approximate=approximate, competencies=competencies or [], tags=tags or [],
                      situation=situation, task=task, action=action, result=result, impact=impact,
                      follow_ups=follow_ups, raw=raw, strength=strength)
        if role_id is not None:
            fields["role_id"] = role_id
        return _brief(store.add_entry(title, **fields), detail=True)

    @tool
    def update_entry(entry_id: int, title: str | None = None, summary: str | None = None,
                     happened_from: str | None = None, happened_to: str | None = None,
                     approximate: bool | None = None, role_id: int | None = None,
                     competencies: list[str] | None = None, tags: list[str] | None = None,
                     situation: str | None = None, task: str | None = None, action: str | None = None,
                     result: str | None = None, impact: str | None = None, follow_ups: str | None = None,
                     raw: str | None = None, strength: int | None = None) -> dict:
        """Update an entry. Only the fields you pass change. competencies and tags replace the
        existing lists, so pass the full list. Use role_id=0 to unassign the role."""
        given = dict(title=title, summary=summary, happened_from=happened_from, happened_to=happened_to,
                     approximate=approximate, role_id=role_id, competencies=competencies, tags=tags,
                     situation=situation, task=task, action=action, result=result, impact=impact,
                     follow_ups=follow_ups, raw=raw, strength=strength)
        changes = {k: v for k, v in given.items() if v is not None}
        if changes.get("role_id") == 0:
            changes["role_id"] = None
        return _brief(store.update_entry(entry_id, **changes), detail=True)

    @tool
    def delete_entry(entry_id: int) -> str:
        """Delete an entry permanently. Confirm with the user first."""
        store.delete_entry(entry_id)
        return f"Deleted entry {entry_id}"

    @tool
    def get_entry(entry_id: int) -> dict:
        """Everything about one entry, including the STAR fields and the user's raw words."""
        return store.entry(entry_id)

    @tool
    def search_entries(query: str = "", role_id: int | None = None, competency: str | None = None,
                       tag: str | None = None, date_from: str | None = None, date_to: str | None = None,
                       detail: bool = False, limit: int = 25) -> dict:
        """Find entries by keywords and/or filters. Keyword search is literal (stemmed), so try
        synonyms or filter by competency. detail=true adds the STAR fields."""
        found = store.entries(query, role_id, competency, tag, date_from, date_to, limit=limit)
        return {"count": len(found), "entries": [_brief(e, detail) for e in found]}

    @tool
    def timeline() -> dict:
        """Roles in order with the titles and dates of their entries, plus entries with no role."""
        data = store.timeline()
        slim = lambda e: {"id": e["id"], "title": e["title"], "when": e["when"], "completeness": e["completeness"]}
        return {"roles": [{"id": r["id"], "title": r["title"], "organisation": r["organisation"],
                           "label": r["label"], "summary": r["summary"], "entries": [slim(e) for e in r["entries"]]}
                          for r in data["roles"]],
                "unplaced": [slim(e) for e in data["unplaced"]]}

    @tool
    def coverage(profile: str | None = None) -> dict:
        """How well the record covers each competency. With a profile slug (see overview), lists each
        core/useful competency for that role as covered, thin or missing: use it to find gaps."""
        data = store.coverage(profile)
        comps = {c["slug"]: c for c in data["competencies"]}
        if profile:
            p = data["profile"]
            return {"profile": p["name"], "score": p["score"],
                    "competencies": [{**g, "name": comps[g["slug"]]["name"],
                                      "best": sorted(comps[g["slug"]]["entries"],
                                                     key=lambda e: (-e["strength"], -e["completeness"]))[:3]}
                                     for g in p["competencies"]]}
        return {"competencies": [{"slug": c["slug"], "name": c["name"], "area": c["area"], "entries": c["total"],
                                  "best_strength": c["best_strength"]} for c in data["competencies"]]}

    @tool
    def set_profile(slug: str, name: str, core: list[str], useful: list[str] | None = None,
                    description: str = "") -> dict:
        """Create or replace a target-role profile, e.g. from a job description. core and useful are
        competency slugs. Then call coverage(profile=slug) to see gaps."""
        return store.set_profile(slug, name, core, useful, description)

    @tool
    def add_competency(slug: str, name: str, area: str, description: str = "") -> dict:
        """Add a competency when nothing in the framework fits. Area: People, Organisation, Delivery,
        Technical, Business, or a new one. Prefer existing competencies."""
        return store.add_competency(slug, name, area, description)

    @server.prompt()
    def capture() -> str:
        """Talk through career memories and record them."""
        return _skill_text("receipts-capture")

    @server.prompt()
    def prep(target_role: str) -> str:
        """Build an interview prep kit for a target role or job description."""
        return _skill_text("receipts-prep") + f"\n\nTarget role or job description:\n{target_role}"

    @server.prompt()
    def review() -> str:
        """Tidy the record and find gaps worth filling."""
        return _skill_text("receipts-review")

    return server


def run(store: Store) -> None:
    build(store).run("stdio")
