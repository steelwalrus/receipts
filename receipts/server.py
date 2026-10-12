"""Loopback-only HTTP interface. All writes require a same-origin request and token."""

import json
import secrets
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit, unquote

from .importer import import_bytes

STATIC = Path(__file__).parent / "static"


def make_server(store, port=8765):
    token = secrets.token_urlsafe(32)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass  # URL queries and evidence must not leak into access logs.

        def respond(self, status, body, content_type="application/json; charset=utf-8", filename=None):
            if not isinstance(body,bytes):
                body = json.dumps(body,ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type",content_type)
            self.send_header("Content-Length",str(len(body)))
            self.send_header("Cache-Control","no-store")
            self.send_header("X-Content-Type-Options","nosniff")
            self.send_header("Referrer-Policy","no-referrer")
            self.send_header("Content-Security-Policy","default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
            if filename:
                self.send_header("Content-Disposition",f'attachment; filename="{filename}"')
            self.end_headers()
            self.wfile.write(body)

        def guarded(self):
            expected = {f"127.0.0.1:{self.server.server_port}",f"localhost:{self.server.server_port}"}
            if self.headers.get("Host") not in expected:
                self.respond(403,{"error":"Receipts only accepts local requests"})
                return False
            origin = self.headers.get("Origin")
            if origin and origin not in {"http://"+h for h in expected}:
                self.respond(403,{"error":"Cross-origin requests are not allowed"})
                return False
            if self.headers.get("Sec-Fetch-Site") == "cross-site":
                self.respond(403,{"error":"Cross-site requests are not allowed"})
                return False
            return True

        def do_GET(self):
            if not self.guarded():
                return
            url = urlsplit(self.path)
            query = parse_qs(url.query)
            try:
                if url.path=="/api/state":
                    return self.respond(200,{"stats":store.stats(),"conversations":store.conversations(),
                                             "notes":store.notes(),"messages":store.recent_messages(),"token":token,"version":"0.1.0"})
                if url.path=="/api/search":
                    return self.respond(200,store.search(query.get("q",[""])[0],query.get("kind",["all"])[0],
                        query.get("assistant",["false"])[0]=="true",query.get("interview",["false"])[0]=="true"))
                for prefix,getter in (("/api/conversations/",store.conversation),("/api/messages/",store.message),("/api/notes/",store.note)):
                    if url.path.startswith(prefix):
                        return self.respond(200,getter(url.path[len(prefix):]))
                if url.path=="/api/export":
                    return self.respond(200,store.export(),filename="receipts-export.json")
                paths = {"/":"index.html","/app.js":"app.js","/style.css":"style.css","/favicon.svg":"favicon.svg"}
                if url.path in paths:
                    suffix = Path(paths[url.path]).suffix
                    types = {".html":"text/html; charset=utf-8",".js":"text/javascript; charset=utf-8",".css":"text/css; charset=utf-8",".svg":"image/svg+xml"}
                    return self.respond(200,(STATIC/paths[url.path]).read_bytes(),types[suffix])
                self.respond(404,{"error":"Not found"})
            except (ValueError,KeyError) as error:
                self.respond(400 if isinstance(error,ValueError) else 404,{"error":str(error)})
            except Exception:
                self.respond(500,{"error":"Unable to read the vault. Check the local database and retry"})

        def do_POST(self):
            if not self.guarded():
                return
            if not secrets.compare_digest(self.headers.get("X-Receipts-Token",""),token):
                return self.respond(403,{"error":"Reload Receipts before saving"})
            try:
                length = int(self.headers.get("Content-Length","0"))
                if length<=0 or length>100_000_000:
                    return self.respond(413,{"error":"File must be smaller than 100 MB"})
                payload = self.rfile.read(length)
                path = urlsplit(self.path).path
                if path=="/api/import":
                    filename = Path(unquote(self.headers.get("X-Filename","import.json"))).name
                    return self.respond(200,import_bytes(store,payload,filename))
                if not self.headers.get("Content-Type","").startswith("application/json"):
                    return self.respond(415,{"error":"Expected JSON"})
                data = json.loads(payload)
                if not isinstance(data,dict):
                    raise ValueError("Expected an object")
                if path=="/api/conversations":
                    return self.respond(201,store.create_conversation(data.get("title")))
                if path=="/api/messages":
                    return self.respond(201,store.append(data.get("conversation_id"),data.get("body"),data.get("role","user")))
                if path=="/api/notes":
                    return self.respond(201,store.save_note(data.get("title"),data.get("body"),data.get("source_ids"),
                        data.get("tags"),data.get("status","draft"),data.get("supersedes_id")))
                self.respond(404,{"error":"Not found"})
            except (ValueError,KeyError,UnicodeError,sqlite3.IntegrityError) as error:
                self.respond(400,{"error":str(error)})
            except Exception:
                self.respond(500,{"error":"Unable to save. Your entry has not been cleared; retry after checking the vault"})

    return ThreadingHTTPServer(("127.0.0.1",port),Handler)


def serve(store,port=8765):
    server = make_server(store,port)
    print(f"Receipts is running at http://127.0.0.1:{server.server_port}",flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
