"""Local web UI. Binds to 127.0.0.1 only.

Writes need a per-run token served to the page, and every request must carry a local Host
header, which blocks other websites (including DNS-rebinding tricks) from reaching the API.
"""

from __future__ import annotations

import json
import re
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from . import __version__
from .portable import export_json, export_markdown
from .store import Store

STATIC = Path(__file__).parent / "static"
CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; font-src 'self'; img-src 'self' data:; "
       "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
MAX_BODY = 2_000_000
TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
         ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml", ".woff2": "font/woff2"}


def make_server(store: Store, port: int = 8765) -> ThreadingHTTPServer:
    token = secrets.token_urlsafe(24)

    class Handler(BaseHTTPRequestHandler):
        server_version = "receipts"

        def log_message(self, *args):  # keep career details out of the terminal
            pass

        # -- helpers ---------------------------------------------------------

        def send(self, status: int, body, content_type="application/json; charset=utf-8", download=None):
            if not isinstance(body, bytes):
                body = json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", CSP)
            if download:
                self.send_header("Content-Disposition", f'attachment; filename="{download}"')
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def local_request(self) -> bool:
            port = self.server.server_port
            allowed = {f"127.0.0.1:{port}", f"localhost:{port}"}
            origin = self.headers.get("Origin")
            if self.headers.get("Host") not in allowed or (origin and origin.removeprefix("http://") not in allowed):
                self.send(403, {"error": "Receipts only accepts requests from its own page"})
                return False
            return True

        def body(self) -> dict:
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                raise ValueError("Request too large")
            data = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(data, dict):
                raise ValueError("Expected a JSON object")
            return data

        def dispatch(self, method: str):
            if not self.local_request():
                return
            url = urlsplit(self.path)
            if method != "GET" and not secrets.compare_digest(self.headers.get("X-Receipts-Token", ""), token):
                return self.send(403, {"error": "Reload the page and try again"})
            try:
                if url.path.startswith("/api/"):
                    return self.api(method, url.path[5:], {k: v[0] for k, v in parse_qs(url.query).items()})
                if method == "GET":
                    return self.static(url.path)
                self.send(405, {"error": "Method not allowed"})
            except KeyError as error:
                self.send(404, {"error": str(error).strip("'\"")})
            except (ValueError, TypeError) as error:
                self.send(400, {"error": str(error)})
            except Exception:
                self.send(500, {"error": "Something went wrong reading or writing the database"})

        def static(self, path: str):
            name = "index.html" if path in ("/", "") else path.lstrip("/")
            target = (STATIC / name).resolve()
            if STATIC.resolve() not in target.parents or not target.is_file():
                return self.send(404, {"error": "Not found"})
            # Explicit types: Windows' registry sometimes maps .js to text/plain, which breaks modules.
            kind = TYPES.get(target.suffix, "application/octet-stream")
            self.send(200, target.read_bytes(), kind)

        # -- API -------------------------------------------------------------

        def api(self, method: str, path: str, query: dict):
            route = (method, re.sub(r"/\d+$", "/:id", path))
            ident = int(path.rsplit("/", 1)[1]) if route[1].endswith("/:id") else None

            if route == ("GET", "overview"):
                return self.send(200, {"version": __version__, "token": token, "stats": store.stats(),
                                       "roles": store.roles(), "competencies": store.competencies(),
                                       "profiles": store.profiles(), "tags": store.tags()})
            if route == ("GET", "timeline"):
                return self.send(200, store.timeline())
            if route == ("GET", "coverage"):
                return self.send(200, store.coverage(query.get("profile") or None))
            if route == ("GET", "entries"):
                return self.send(200, store.entries(query.get("q", ""), query.get("role"), query.get("competency"),
                                                    query.get("tag"), query.get("from"), query.get("to")))
            if route == ("GET", "entries/:id"):
                return self.send(200, store.entry(ident))
            if route == ("POST", "entries"):
                data = self.body()
                return self.send(201, store.add_entry(data.pop("title", ""), **data))
            if route == ("PATCH", "entries/:id"):
                return self.send(200, store.update_entry(ident, **self.body()))
            if route == ("DELETE", "entries/:id"):
                store.delete_entry(ident)
                return self.send(200, {"deleted": ident})
            if route == ("POST", "roles"):
                data = self.body()
                return self.send(201, store.add_role(data.pop("title", ""), data.pop("started", ""), **data))
            if route == ("PATCH", "roles/:id"):
                return self.send(200, store.update_role(ident, **self.body()))
            if route == ("DELETE", "roles/:id"):
                store.delete_role(ident)
                return self.send(200, {"deleted": ident})
            if route == ("GET", "export.json"):
                body = json.dumps(export_json(store), ensure_ascii=False, indent=2).encode("utf-8")
                return self.send(200, body, download="receipts.json")
            if route == ("GET", "export.md"):
                return self.send(200, export_markdown(store).encode("utf-8"), "text/markdown; charset=utf-8",
                                 download="career-record.md")
            self.send(404, {"error": "Not found"})

        def do_GET(self):
            self.dispatch("GET")

        def do_HEAD(self):
            self.dispatch("GET")

        def do_POST(self):
            self.dispatch("POST")

        def do_PATCH(self):
            self.dispatch("PATCH")

        def do_DELETE(self):
            self.dispatch("DELETE")

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def serve(store: Store, port: int = 8765) -> None:
    server = make_server(store, port)
    print(f"Receipts: http://127.0.0.1:{server.server_port}  (database: {store.path})", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
