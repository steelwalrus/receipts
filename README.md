# Receipts

A private, local record of your career for interview prep. You talk your history through with
Claude or Codex; they write it into a small SQLite database as roles on a timeline and entries
(the stories behind them), tagged against a competency framework. Later you point the same agent at it
to build STAR answers for a target role and to find the gaps.

There's also a local web UI to browse the timeline, see coverage by competency, and edit entries.

Nothing leaves your machine except what you choose to send to your AI agent.

## Install

Python 3.10 or later.

```sh
git clone https://github.com/steelwalrus/receipts.git
cd receipts
pip install -e .            # or: uv tool install -e .
```

This gives you a `receipts` command. The database lives at `%LOCALAPPDATA%\receipts\receipts.db` on
Windows and `~/.local/share/receipts/receipts.db` elsewhere. Set `RECEIPTS_DB` or pass `--db PATH` to
use another file. Keep it out of this repository.

## Connect your agent

Receipts is an MCP server. Register it once, then talk to it from any project.

**Claude Code**

```sh
claude mcp add --scope user receipts -- receipts mcp
receipts install-skills claude
```

**Claude Desktop**: add this to `claude_desktop_config.json`:

```json
{ "mcpServers": { "receipts": { "command": "receipts", "args": ["mcp"] } } }
```

**Codex**: add this to `~/.codex/config.toml`:

```toml
[mcp_servers.receipts]
command = "receipts"
args = ["mcp"]
```

then `receipts install-skills codex`.

If `receipts` isn't on your PATH, use the full path to it, or `python` with `["-m", "receipts", "mcp"]`.

## Use it

There are three skills (also available as MCP prompts named `capture`, `prep` and `review`):

| Skill | Use it when | What it does |
|---|---|---|
| `receipts-capture` | You're remembering things | Splits what you say into entries, dates them, tags competencies, asks a couple of follow-up questions |
| `receipts-prep` | You have an interview or a job description | Builds a target-role profile, checks coverage, drafts STAR answers from your entries, lists the gaps |
| `receipts-review` | You want to tidy up | Finds undated, incomplete or duplicate entries and timeline gaps, then works through them with you |

Examples:

> I just remembered: at Acme I had to move a team off a vendor we were paying £200k a year…

> I'm interviewing for a Head of Engineering role. Here's the job description. Help me prepare.

> What's missing from my record for an Engineering Manager role?

## Web UI

```sh
receipts serve
```

Opens http://127.0.0.1:8765. **Timeline** shows your roles over time and every entry under them.
**Entries** is search and filtering. **Coverage** is a grid of competencies against roles; pick a
target role to see what's covered, thin or missing. Click any entry to read or edit it.

## How the data works

- **Roles**: title, organisation, start and end. Dates can be partial: `2016`, `2018-06`, `2021-Q3`.
- **Entries**: one story each. Title, summary, when it happened (partial dates, optionally marked
  approximate), the role (worked out from the date if you don't set it), situation, task, action,
  result, impact, things still to confirm, your own words, strength (minor, solid, headline), tags,
  and the competencies it shows.
- **Competencies**: 21 to start with, grouped into People, Organisation, Delivery, Technical and
  Business. Add your own.
- **Profiles**: target roles (Engineering Manager, Director, Head of Engineering, CTO) listing their
  core and useful competencies. The prep skill creates new ones from job descriptions.

An entry is interview-ready when it has a date, role, competencies, situation, action, result and impact.
The UI shows which of those are missing.

## Backups and other machines

```sh
receipts backup ~/backups/receipts-2026-10-12.db   # safe while the app is running
receipts export ~/backups/receipts.json            # portable JSON
receipts export ~/career-record.md --markdown      # readable, good for pasting into an AI
receipts import ~/backups/receipts.json            # merges; skips entries you already have
```

## Development

```sh
python -m unittest discover -s tests -v
```

Standard library plus the `mcp` package. The UI is plain HTML, CSS and JavaScript with no build step.
See [AGENTS.md](AGENTS.md) for how the code is laid out.

The font is Schibsted Grotesk (SIL Open Font License, see `receipts/static/fonts/OFL.txt`).

MIT licensed.
