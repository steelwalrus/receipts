"""Import original text without rewriting it; retain the exact uploaded bytes too."""

import base64
import hashlib
import json
from datetime import datetime, timezone

from .store import json_text, now, stable_id


def timestamp(value):
    if isinstance(value,(int,float)):
        return datetime.fromtimestamp(value,timezone.utc).isoformat()
    return value if isinstance(value,str) and value else now()


def content_text(content):
    """Text parts stay verbatim. Non-text parts remain in raw metadata and import bytes."""
    if isinstance(content,str):
        return content
    if isinstance(content,dict):
        parts = content.get("parts")
        if parts is not None:
            return "\n".join(p for p in parts if isinstance(p,str))
        return content.get("text","")
    if isinstance(content,list):
        return "\n".join(p.get("text","") for p in content if isinstance(p,dict) and p.get("type")=="text")
    return ""


def chatgpt_conversation(conv):
    cid = "chatgpt:" + str(conv.get("id") or conv.get("conversation_id") or stable_id(json_text(conv)))
    mapping = conv.get("mapping",{})
    active = set()
    current = conv.get("current_node")
    while current and current in mapping and current not in active:
        active.add(current)
        current = mapping[current].get("parent")
    messages = []
    for node_id,node in mapping.items():
        msg = node.get("message")
        if not msg:
            continue
        role = msg.get("author",{}).get("role","tool")
        role = role if role in ("user","assistant","system","tool") else "tool"
        body = content_text(msg.get("content"))
        if not body:
            body = "[Non-text message: original content is retained in the imported file and message metadata.]"
        messages.append({"body":body,"role":role,"external_id":"chatgpt-message:"+str(msg.get("id") or node_id),
                         "created_at":timestamp(msg.get("create_time") or conv.get("create_time")),
                         "metadata":{"original":msg,"node_id":node_id,"parent":node.get("parent"),
                                     "active_branch":node_id in active if active else None}})
    messages.sort(key=lambda m:m["created_at"])
    return {"external_id":cid,"title":conv.get("title") or "Imported conversation",
            "created_at":timestamp(conv.get("create_time")),"messages":messages,
            "metadata":{"format":"chatgpt-export","branches_preserved":True}}


def read_thread_conversation(data):
    thread = data["thread"]
    messages = []
    for turn in reversed(data["turns"]):
        for index,item in enumerate(turn.get("items",[])):
            if item.get("truncated"):
                raise ValueError("An imported message is truncated. Import a complete source instead")
            role = {"userMessage":"user","agentMessage":"assistant"}.get(item.get("type"))
            if not role:
                continue
            body = item.get("text") if role=="assistant" else content_text(item.get("content"))
            if not body:
                continue
            messages.append({"body":body,"role":role,
                "external_id":"chatgpt-message:"+str(item.get("id") or f"{turn['id']}:{index}"),
                "created_at":timestamp(turn.get("startedAt") if role=="user" else turn.get("completedAt")),
                "metadata":{"original":item,"turn_id":turn["id"]}})
    notice = data.get("import_notice") or "Imported the history exposed by the chat reader; completeness of earlier history is not guaranteed."
    return {"external_id":"chatgpt:"+thread["id"],"title":thread.get("title") or "Imported conversation",
            "created_at":timestamp(thread.get("createdAt")),"messages":messages,
            "metadata":{"format":"chat-reader","import_notice":notice}}


def import_bytes(store, payload, filename="import.json"):
    if not isinstance(payload,bytes) or len(payload)>100_000_000:
        raise ValueError("Import must be a file smaller than 100 MB")
    checksum = hashlib.sha256(payload).hexdigest()
    iid = stable_id("import:"+checksum)
    text = payload.decode("utf-8-sig")
    if filename.lower().endswith((".txt",".md")):
        data = None
        conversations = [{"external_id":"file:"+checksum,"title":filename,
            "messages":[{"body":text,"role":"user","external_id":"file-message:"+checksum}],
            "metadata":{"format":"text-file","filename":filename}}]
    else:
        data = json.loads(text)
        if isinstance(data,dict) and data.get("format")=="receipts-export-v1":
            return restore_export(store,data)
        if isinstance(data,dict) and "thread" in data and "turns" in data:
            conversations = [read_thread_conversation(data)]
        elif isinstance(data,dict) and "mapping" in data:
            conversations = [chatgpt_conversation(data)]
        elif isinstance(data,list) and all(isinstance(c,dict) and "mapping" in c for c in data):
            conversations = [chatgpt_conversation(c) for c in data]
        elif isinstance(data,dict) and isinstance(data.get("messages"),list):
            # Simple, documented interchange format. It must contain actual source text.
            conversations = [{"external_id":data.get("external_id") or "file:"+checksum,
                "title":data.get("title") or filename,"metadata":data.get("metadata",{}),
                "messages":[{"body":m["body"],"role":m.get("role","user"),
                    "external_id":m.get("external_id") or f"file-message:{checksum}:{i}",
                    "created_at":m.get("created_at"),"metadata":m.get("metadata",{})}
                    for i,m in enumerate(data["messages"])]}]
        else:
            raise ValueError("Use a ChatGPT conversations.json export, chat-reader JSON, Receipts export, or plain text file")
    if not conversations or not any(c["messages"] for c in conversations):
        raise ValueError("No messages found in this file")
    notices = [c.get("metadata",{}).get("import_notice","") for c in conversations]
    with store.connection() as db:
        if db.execute("SELECT id FROM imports WHERE sha256=?",(checksum,)).fetchone():
            return {"added":0,"duplicate":True,"import_id":iid,"notice":"This exact file was already imported"}
        db.execute("INSERT INTO imports VALUES (?,?,?,?,?,?)",(iid,filename,checksum,payload,now(),"\n".join(n for n in notices if n)))
        added = 0
        duplicates = 0
        ids = []
        for conv in conversations:
            cid = store._conversation(db,conv["title"],conv["external_id"],conv.get("metadata"),conv.get("created_at"))
            ids.append(cid)
            for message in conv["messages"]:
                _,fresh = store._append(db,cid,import_id=iid,**message)
                added += int(fresh)
                duplicates += int(not fresh)
    return {"added":added,"duplicates":duplicates,"import_id":iid,"conversation_ids":ids,
            "notice":"\n".join(n for n in notices if n)}


def restore_export(store,data):
    """Restore exports only to an empty vault; merging unknown histories is not lossless."""
    if data.get("schema_version") != 1:
        raise ValueError("Unsupported export schema")
    tables = data.get("tables",{})
    names = ("meta","imports","conversations","messages","notes","note_sources")
    if set(tables) != set(names):
        raise ValueError("Export is missing required tables")
    with store.connection() as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("PRAGMA defer_foreign_keys=ON")
        if any(db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in names if t!="meta"):
            raise ValueError("A Receipts export can only be restored into an empty vault")
        db.execute("DELETE FROM meta")
        for table in names:
            allowed = {r[1] for r in db.execute(f"PRAGMA table_info({table})")}
            for source in tables[table]:
                row = dict(source)
                if table=="imports":
                    row["payload"] = base64.b64decode(row.pop("payload_base64"),validate=True)
                    if hashlib.sha256(row["payload"]).hexdigest()!=row["sha256"]:
                        raise ValueError("Imported file checksum does not match")
                if table=="messages" and hashlib.sha256(row["body"].encode("utf-8")).hexdigest()!=row["sha256"]:
                    raise ValueError("Message checksum does not match")
                if set(row)!=allowed:
                    raise ValueError("Export fields do not match this schema")
                # All identifiers are from the validated schema above, never arbitrary input.
                columns = list(row)
                db.execute(f"INSERT INTO {table} ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",list(row.values()))
        db.execute("DELETE FROM search_index")
        db.execute("""INSERT INTO search_index SELECT m.id,'message',c.title,m.body,'',m.role
            FROM messages m JOIN conversations c ON c.id=m.conversation_id""")
        db.execute("""INSERT INTO search_index SELECT n.id,'note',n.title,n.body,
            (SELECT group_concat(value,' ') FROM json_each(n.tags)),'note' FROM notes n
            WHERE NOT EXISTS(SELECT 1 FROM notes newer WHERE newer.supersedes_id=n.id)""")
    return {"added":len(tables["messages"]),"restored":True}
