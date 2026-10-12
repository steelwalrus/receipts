"""Command line: python -m receipts <command>."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import webbrowser
from pathlib import Path

from .store import Store

SKILL_TARGETS = {"claude": Path.home() / ".claude" / "skills", "codex": Path.home() / ".agents" / "skills"}


def main(argv=None):
    parser = argparse.ArgumentParser(prog="receipts", description="A private record of your career.")
    parser.add_argument("--db", help="Database file (default: RECEIPTS_DB or your local app data folder)")
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="Open the web UI")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--no-browser", action="store_true")
    sub.add_parser("mcp", help="Run the MCP server on stdio (for Claude, Codex and other MCP clients)")
    sub.add_parser("status", help="Show where the database is and what's in it")
    backup = sub.add_parser("backup", help="Write a consistent copy of the database")
    backup.add_argument("path")
    export = sub.add_parser("export", help="Export everything as JSON, or as readable Markdown")
    export.add_argument("path")
    export.add_argument("--markdown", action="store_true")
    imp = sub.add_parser("import", help="Merge a JSON export into this database")
    imp.add_argument("path")
    skills = sub.add_parser("install-skills", help="Copy the capture/prep/review skills for your agent")
    skills.add_argument("target", help="claude, codex, or a skills directory")

    args = parser.parse_args(argv)
    try:
        if args.command == "install-skills":
            return install_skills(args.target)
        store = Store(args.db)
        if args.command == "serve":
            from .server import make_server
            server = make_server(store, args.port)
            url = f"http://127.0.0.1:{server.server_port}"
            print(f"Receipts: {url}  (database: {store.path})", flush=True)
            if not args.no_browser:
                webbrowser.open(url)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass
            return
        if args.command == "mcp":
            from .mcp_server import run
            return run(store)
        if args.command == "status":
            print(json.dumps({"database": str(store.path), **store.stats()}, indent=2))
        elif args.command == "backup":
            print(f"Backed up to {store.backup(args.path)}")
        elif args.command == "export":
            from .portable import export_json, export_markdown
            target = Path(args.path)
            if target.exists():
                raise ValueError(f"{target} already exists")
            text = export_markdown(store) if args.markdown else json.dumps(export_json(store), ensure_ascii=False, indent=2)
            target.write_text(text, encoding="utf-8")
            print(f"Exported to {target}")
        elif args.command == "import":
            from .portable import import_json
            data = json.loads(Path(args.path).read_text(encoding="utf-8-sig"))
            print(json.dumps(import_json(store, data), indent=2))
    except (ValueError, KeyError, OSError, RuntimeError) as error:
        print(f"receipts: {str(error).strip(chr(39))}", file=sys.stderr)
        sys.exit(1)


def install_skills(target: str):
    source = Path(__file__).parent / "skills"
    destination = SKILL_TARGETS.get(target, Path(target).expanduser())
    destination.mkdir(parents=True, exist_ok=True)
    for skill in sorted(p for p in source.iterdir() if (p / "SKILL.md").exists()):
        shutil.copytree(skill, destination / skill.name, dirs_exist_ok=True)
        print(f"Installed {skill.name} -> {destination / skill.name}")


if __name__ == "__main__":
    main()
