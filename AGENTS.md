# Working on Receipts

This file is for changing the code. To record or use career content, use the `receipts` MCP tools and
the skills in `receipts/skills/`. Never put real career data in this repository: test fixtures,
screenshots, issues and commits use made-up content only.

## Layout

- `receipts/store.py`: all database access. Roles, entries, competencies, profiles, search, timeline, coverage.
- `receipts/schema.py`: migrations (append only; each bumps `PRAGMA user_version`) and the seeded
  competency framework and profiles.
- `receipts/dates.py`: partial dates (`2019`, `2019-06`, `2019-06-14`, `2019-Q2`).
- `receipts/search.py`: free text to FTS5 query.
- `receipts/mcp_server.py`: the MCP tools and prompts. Tool docstrings are what the agent reads, so keep them accurate.
  Raise `ValueError` or `KeyError` for bad input; the wrapper turns them into messages the agent can see.
- `receipts/skills/*/SKILL.md`: capture, prep and review workflows. Served as MCP prompts too.
- `receipts/server.py`: the local web UI's JSON API. Loopback only, Host/Origin checked, writes need the page token.
- `receipts/static/`: the UI. Plain JS, no build step, strict CSP (no inline scripts or style attributes;
  set styles through the CSSOM).
- `receipts/portable.py`: JSON export/import and Markdown export.

## Conventions

- Standard library only, apart from `mcp`. Support mcp 1.x and 2.x (see the imports in `mcp_server.py`).
- UI copy is plain and short. No taglines, no all-caps labels, no internal IDs or hashes beyond the entry number.
- Run `python -m unittest discover -s tests -v` before committing.
