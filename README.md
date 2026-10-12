# Receipts

**Keep the words. Find the story.**

A private career evidence bank that runs on your computer. Capture free-form accounts,
keep original conversations intact, extract source-linked notes, and find examples for
interview questions. The public repository contains the application, never your records.

## Run locally

Requires **Python 3.11+ with SQLite FTS5**. No pip packages, Node server, API key, or model
subscription is required to run the application.

```sh
git clone https://github.com/steelwalrus/receipts.git
cd receipts
python -m receipts serve
```

Open **http://127.0.0.1:8765**. On systems where Python is named `python3` or `py`, use that
command instead. The server binds only to loopback; it is not a hosted/multi-user server.

By default, the private vault is `%LOCALAPPDATA%/Receipts` on Windows and
`~/.local/share/Receipts` elsewhere. Choose another directory with `RECEIPTS_VAULT` or:

```sh
python -m receipts --vault ../my-private-records serve
```

Keep the vault **outside this checkout**. The application rejects vaults, CLI exports,
and snapshots inside its own source tree. Original imports, database copies, and exports
are private data too. Nothing in the application uploads records automatically.

## What the MVP does

- Capture original messages without trimming, spelling correction, or summarisation.
- Preserve user and assistant roles separately. Assistant claims are excluded from
  search by default; they are not treated as personal evidence.
- Import ChatGPT `conversations.json`, an individual ChatGPT conversation object,
  Codex chat-reader JSON, `.txt`, `.md`, and a small generic interchange format.
- Keep the exact bytes of imported files in SQLite alongside extracted messages.
- Retain exported ChatGPT branches and non-text metadata. Text is searchable; binary
  attachments are **not downloaded**. Their references survive in the original import.
- Append-only original messages with SHA-256 checksums. Add corrections as new messages.
- Create free-form notes with tags, review status, and one or more message links.
  Editing creates another revision and preserves the old one.
- Search the full original text and current notes using SQLite FTS5 with stemming.
- Enter an interview question, retrieve candidates using transparent keyword/topic
  expansion, inspect the sources, and copy/download an evidence pack for Codex.
- Export/restore a lossless JSON archive, create consistent SQLite backups, and transfer
  snapshots through an existing private GitHub repository.

Interview retrieval is lexical, **not semantic AI search**. It does not generate answers.
The interface displays the searched terms so you can refine them. The library shows
the latest 100 messages plus current notes; full conversations and search remain available.

## Keep conversations intact

Import via **Data & backups**, or:

```sh
python -m receipts --vault ../my-private-records import /private/path/conversations.json
```

Importing a complete ChatGPT account export imports **all conversations in that file**.
For one conversation, supply its individual JSON object. A chat-reader export may expose
only recent history; Receipts labels those imports as potentially incomplete. It rejects
messages explicitly flagged as truncated and never fills in missing history.

An identical file import is a no-op. Messages with the same external ID and exact text
are deduplicated. Reusing an ID with changed text fails the entire import rather than
silently overwriting a source. Missing dates fall back to import time; metadata retains
the original timestamp information. Import-file bytes remain the fidelity reference,
including original non-text content and multipart message structure.

Generic interchange format:

```json
{
  "title": "A project I remembered",
  "external_id": "my-journal:2026",
  "messages": [
    {"external_id": "my-journal:message-1", "role": "user", "body": "My exact words.\nIncluding whitespace."},
    {"external_id": "my-journal:message-2", "role": "assistant", "body": "The assistant response."}
  ]
}
```

## Work with Codex

The CLI is the MVP integration: JSON in/out, with the same validation and database code
as the UI. See [AGENTS.md](AGENTS.md) for the source-preserving workflow. An MCP server is
not required and is not included in this version.

```sh
python -m receipts --vault ../my-private-records conversation "Career memories"
python -m receipts --vault ../my-private-records conversations
python -m receipts --vault ../my-private-records append CONVERSATION_ID --file /private/path/message.txt --external-id chat:message-123
python -m receipts --vault ../my-private-records search "Tell me about coaching someone" --interview
python -m receipts --vault ../my-private-records get message MESSAGE_ID
python -m receipts --vault ../my-private-records note /private/path/note.json
```

`append` reads exact UTF-8 bytes from a file (`--file`) or stdin (`--file -`). Prefer a
file when shells might change whitespace. Use `--role assistant` to log assistant replies.
Logging requires the agent to run these operations; Receipts cannot automatically
intercept arbitrary ChatGPT/Codex conversations. When using Codex, retrieved text is sent
into its context and uses that plan's allowance. The app itself makes no model API calls.

Note JSON:

```json
{
  "title": "Developing an engineer",
  "body": "Free-form summary, outcomes, caveats, and follow-up questions.",
  "source_ids": ["MESSAGE_ID"],
  "tags": ["coaching", "leadership"],
  "status": "draft"
}
```

To revise a note, add `"supersedes_id": "PREVIOUS_NOTE_ID"`. Source links are mandatory.
Notes are interpretations, never replacements for the source. `reviewed` is a user's
review status, not external verification of a claim.

## Backups and another computer

Create a consistent SQLite snapshot using SQLite's backup API, including committed WAL
content. Do not copy the live database while it is changing.

```sh
python -m receipts --vault ../my-private-records snapshot /private/backups/receipts-2026-10-12.sqlite3
python -m receipts --vault ../my-private-records export /private/backups/archive.json
```

Snapshot/export commands refuse to overwrite an existing output file. JSON exports can
be imported into an **empty** vault. They include base64 representations of original
import files, complete note revisions, and source relationships.

For GitHub snapshot transfer:

1. Create a **private** GitHub repository for records, initialised with a README.
2. Install Git and authenticate through Git Credential Manager or `gh auth login`.
   Alternatively, supply `GH_TOKEN`/`GITHUB_TOKEN` with read/write access to that repo.
3. Push from the first computer, then pull into an empty vault on the other computer.

```sh
python -m receipts --vault ../my-private-records sync push --repo YOUR_NAME/PRIVATE_RECORDS
python -m receipts --vault ../my-private-records sync pull --repo YOUR_NAME/PRIVATE_RECORDS
```

The script verifies GitHub repository privacy before transferring anything and again
before pushing. If it cannot verify privacy, it stops. A fresh temporary checkout stages
only `receipts.sqlite3` and `snapshot.json`. Credentials are never stored in the vault.

Use **one writer at a time: pull → work → push**. The last synced content fingerprint is
kept in `sync-state.json` beside the live database. A push rejects unexpected remote
changes; a pull rejects unsynced local changes. Git pushes never force. Conflicts need a
separate vault/manual reconciliation; SQLite files are never Git-merged.

Before a pull, a backup of the current database is created under `backups/`. Restore uses
SQLite's backup API under a cross-process lock, so local writes cannot race the restore.
The UI may be open; refresh it after a CLI restore or import. The vault and snapshots are
not application-encrypted. A private GitHub repository controls access, but anyone with
repository access can read the snapshot and its history. Sync is optional and manual.

## Small data model

The main records are conversations, immutable messages, and free-form notes.
`note_sources` connects notes to messages; tags are a JSON list. `imports` holds the
original uploaded bytes. An FTS5 index is derived from originals and current notes.
Schema changes are versioned with SQLite `user_version`; unsupported versions are rejected.
There is no entity graph, embedding service, or model-written SQL.

## Development and validation

```sh
python -m unittest discover -s tests -v
python -m compileall -q receipts
```

Tests cover exact text and raw-file preservation, import rollback/deduplication, branches,
source links, note revisions, retrieval, lossless export/restore, database backups,
same-origin HTTP protections, and divergent snapshot transfers using local Git remotes.
All test data is fictional. The backend uses Python's standard library; the UI is plain
HTML, CSS, and browser JavaScript. No JavaScript backend or frontend build step.

MIT licensed. This is a personal local tool; deploying it as a public service would require
a different authentication, authorisation, and server setup.
