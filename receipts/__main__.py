"""Run with python -m receipts. JSON output makes the same operations usable by Codex."""

import argparse
import json
import sys
from pathlib import Path

from .store import Store,CODE_ROOT


def main():
    parser = argparse.ArgumentParser(description="Receipts — preserve your words, find your evidence")
    parser.add_argument("--vault",help="Private data directory outside this code checkout")
    sub = parser.add_subparsers(dest="command",required=True)
    server = sub.add_parser("serve",help="Start the local interface")
    server.add_argument("--port",type=int,default=8765)
    sub.add_parser("status")
    sub.add_parser("conversations")
    conv = sub.add_parser("conversation",help="Create a conversation")
    conv.add_argument("title")
    append = sub.add_parser("append",help="Append exact text from a UTF-8 file or stdin")
    append.add_argument("conversation_id")
    append.add_argument("--file",default="-",help="UTF-8 file, or - for stdin")
    append.add_argument("--role",choices=["user","assistant","system","tool"],default="user")
    append.add_argument("--external-id",help="Stable source ID for idempotent agent logging")
    imp = sub.add_parser("import",help="Import a conversation export or text file")
    imp.add_argument("file")
    search = sub.add_parser("search")
    search.add_argument("query")
    search.add_argument("--interview",action="store_true")
    search.add_argument("--include-assistant",action="store_true")
    search.add_argument("--kind",choices=["all","message","note"],default="all")
    get = sub.add_parser("get")
    get.add_argument("kind",choices=["message","note","conversation"])
    get.add_argument("id")
    note = sub.add_parser("note",help="Create a source-linked note or revision from JSON")
    note.add_argument("file",help="JSON file containing title, body, source_ids, optional tags/status/supersedes_id")
    export = sub.add_parser("export")
    export.add_argument("file")
    snapshot = sub.add_parser("snapshot")
    snapshot.add_argument("file")
    sync = sub.add_parser("sync",help="Transfer a snapshot using an existing PRIVATE GitHub repository")
    sync.add_argument("direction",choices=["push","pull"])
    sync.add_argument("--repo",required=True,help="owner/private-repository (must already exist and have a commit)")
    args = parser.parse_args()
    try:
        store = Store(args.vault)
        if args.command=="serve":
            from .server import serve
            serve(store,args.port)
            return
        if args.command=="status":
            result = {"vault":str(store.vault),**store.stats()}
        elif args.command=="conversations":
            result = store.conversations()
        elif args.command=="conversation":
            result = store.create_conversation(args.title)
        elif args.command=="append":
            body = (sys.stdin.buffer.read() if args.file=="-" else Path(args.file).read_bytes()).decode("utf-8")
            result = store.append(args.conversation_id,body,args.role,args.external_id)
        elif args.command=="import":
            from .importer import import_bytes
            path = Path(args.file)
            result = import_bytes(store,path.read_bytes(),path.name)
        elif args.command=="search":
            result = store.search(args.query,args.kind,args.include_assistant,args.interview)
        elif args.command=="get":
            result = getattr(store,args.kind)(args.id)
        elif args.command=="note":
            result = store.save_note(**json.loads(Path(args.file).read_text("utf-8-sig")))
        elif args.command=="snapshot":
            result = {"snapshot":str(store.snapshot(args.file))}
        elif args.command=="export":
            target = Path(args.file).resolve()
            if target==CODE_ROOT or CODE_ROOT in target.parents:
                raise ValueError("Keep private exports outside the public checkout")
            target.parent.mkdir(parents=True,exist_ok=True)
            with target.open("x",encoding="utf-8",newline="") as handle:
                json.dump(store.export(),handle,ensure_ascii=False,indent=2)
            result = {"export":str(target)}
        elif args.command=="sync":
            from .sync import sync_snapshot
            result = sync_snapshot(store,args.direction,args.repo)
        print(json.dumps(result,ensure_ascii=False,indent=2))
    except (ValueError,KeyError,OSError,RuntimeError) as error:
        print(json.dumps({"error":str(error)},ensure_ascii=False),file=sys.stderr)
        sys.exit(1)


if __name__=="__main__":
    if hasattr(sys.stdout,"reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    main()
