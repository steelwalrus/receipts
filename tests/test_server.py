import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path

from receipts.server import make_server
from receipts.store import Store


class ServerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "r.db")
        self.server = make_server(self.store, port=0)
        self.port = self.server.server_port
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.token = self.call("GET", "/api/overview")[1]["token"]

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def call(self, method, path, body=None, headers=None, token=True):
        conn = http.client.HTTPConnection("127.0.0.1", self.port)
        sent = {"Host": f"127.0.0.1:{self.port}"}
        if body is not None:
            sent["Content-Type"] = "application/json"
        if token and method != "GET":
            sent["X-Receipts-Token"] = self.token
        sent.update(headers or {})
        conn.request(method, path, json.dumps(body) if body is not None else None, sent)
        response = conn.getresponse()
        raw = response.read()
        conn.close()
        try:
            return response.status, json.loads(raw)
        except ValueError:
            return response.status, raw

    def test_entry_round_trip(self):
        status, role = self.call("POST", "/api/roles", {"title": "Head of Engineering", "started": "2021"})
        self.assertEqual(status, 201)
        status, entry = self.call("POST", "/api/entries", {"title": "Thing", "happened_from": "2022",
                                                            "competencies": ["delivery"]})
        self.assertEqual(status, 201)
        self.assertEqual(entry["role"]["id"], role["id"])
        status, entry = self.call("PATCH", f"/api/entries/{entry['id']}", {"result": "Shipped"})
        self.assertEqual((status, entry["result"]), (200, "Shipped"))
        status, found = self.call("GET", "/api/entries?q=shipped")
        self.assertEqual([e["id"] for e in found], [entry["id"]])
        self.assertEqual(self.call("DELETE", f"/api/entries/{entry['id']}")[0], 200)
        self.assertEqual(self.call("GET", f"/api/entries/{entry['id']}")[0], 404)

    def test_validation_errors_are_400_with_a_message(self):
        status, body = self.call("POST", "/api/entries", {"title": "Thing", "happened_from": "spring"})
        self.assertEqual(status, 400)
        self.assertIn("should look like", body["error"])

    def test_writes_need_the_token(self):
        status, _ = self.call("POST", "/api/roles", {"title": "X", "started": "2020"}, token=False)
        self.assertEqual(status, 403)

    def test_foreign_host_and_origin_are_refused(self):
        self.assertEqual(self.call("GET", "/api/overview", headers={"Host": "evil.example"})[0], 403)
        status, _ = self.call("POST", "/api/roles", {"title": "X", "started": "2020"},
                              headers={"Origin": "http://evil.example"})
        self.assertEqual(status, 403)

    def test_static_files_and_traversal(self):
        status, body = self.call("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(b"<title>Receipts</title>", body)
        self.assertEqual(self.call("GET", "/../store.py")[0], 404)
        self.assertEqual(self.call("GET", "/fonts/../../store.py")[0], 404)

    def test_exports(self):
        self.call("POST", "/api/roles", {"title": "Dev", "started": "2016"})
        status, data = self.call("GET", "/api/export.json")
        self.assertEqual((status, data["format"]), (200, "receipts/1"))
        status, text = self.call("GET", "/api/export.md")
        self.assertEqual(status, 200)
        self.assertIn(b"## Dev", text)


if __name__ == "__main__":
    unittest.main()
