import base64
import hashlib
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from receipts.importer import import_bytes
from receipts.store import Store
from receipts.sync import restore_snapshot,validate_snapshot


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = Store(self.root/"vault")
        self.conv = self.store.create_conversation("Fictional career notes")

    def tearDown(self):
        self.tmp.cleanup()

    def message(self,body="I coached a junior engineer through a difficult project."):
        return self.store.append(self.conv["id"],body)

    def test_exact_text_including_unicode_whitespace_and_encoded_entities(self):
        original = "  I remmeber…\r\n\r\n\t£10 → café 😀 &#x20;\n  "
        saved = self.message(original)
        reopened = Store(self.root/"vault").message(saved["id"])
        self.assertEqual(original,reopened["body"])
        self.assertEqual(hashlib.sha256(original.encode()).hexdigest(),reopened["sha256"])

    def test_immutability_is_enforced_in_sqlite(self):
        message = self.message()
        for sql in ("UPDATE messages SET body='changed' WHERE id=?","DELETE FROM messages WHERE id=?"):
            with self.assertRaises(sqlite3.IntegrityError),self.store.connection() as db:
                db.execute(sql,(message["id"],))

    def test_agent_append_is_idempotent_and_conflicting_text_is_rejected(self):
        first = self.store.append(self.conv["id"],"Verbatim","user","source:1")
        again = self.store.append(self.conv["id"],"Verbatim","user","source:1")
        self.assertEqual(first["id"],again["id"])
        with self.assertRaises(ValueError):
            self.store.append(self.conv["id"],"Changed","user","source:1")
        self.assertEqual(1,self.store.stats()["messages"])

    def test_raw_file_preserved_and_reimport_deduplicated(self):
        payload = b'{ "title": "test", "messages": [{"body":"  Original\\r\\ntext  "}]}\r\n'
        result = import_bytes(self.store,payload,"test.json")
        self.assertEqual(1,result["added"])
        self.assertTrue(import_bytes(self.store,payload,"test.json")["duplicate"])
        with self.store.connection() as db:
            self.assertEqual(payload,db.execute("SELECT payload FROM imports").fetchone()[0])
        self.assertEqual("  Original\r\ntext  ",self.store.recent_messages()[0]["body"])

    def test_import_failure_rolls_back_all_records(self):
        payload = json.dumps({"messages":[{"body":"Valid message"},{"body":""}]}).encode()
        with self.assertRaises(ValueError):import_bytes(self.store,payload)
        self.assertEqual(0,self.store.stats()["imports"])
        self.assertEqual(0,self.store.stats()["messages"])

    def test_chat_reader_preserves_assistant_and_rejects_truncation(self):
        data = {"thread":{"id":"fictional-thread","title":"Fictional chat"},"turns":[
            {"id":"turn-1","startedAt":100,"completedAt":101,"items":[
                {"type":"userMessage","id":"u1","content":[{"type":"text","text":"Raw  words\n"}]},
                {"type":"agentMessage","id":"a1","text":"Assistant opinion"}]}]}
        self.assertEqual(2,import_bytes(self.store,json.dumps(data).encode())["added"])
        data["turns"][0]["items"][1]["truncated"] = True
        with self.assertRaises(ValueError):import_bytes(self.store,json.dumps(data).encode())

    def test_chatgpt_export_keeps_alternative_branches_and_non_text(self):
        data = {"id":"fictional-thread","title":"Branch test","current_node":"b","mapping":{
            "a":{"parent":None,"message":{"id":"m1","author":{"role":"user"},"create_time":1,"content":{"parts":["Original"]}}},
            "b":{"parent":"a","message":{"id":"m2","author":{"role":"assistant"},"create_time":2,"content":{"parts":["First branch"]}}},
            "c":{"parent":"a","message":{"id":"m3","author":{"role":"user"},"create_time":3,"content":{"parts":[{"asset_pointer":"image-reference"}]}}}}}
        self.assertEqual(3,import_bytes(self.store,json.dumps([data]).encode())["added"])
        messages = self.store.recent_messages()
        alt = next(m for m in messages if m["external_id"].endswith("m3"))
        self.assertFalse(alt["metadata"]["active_branch"])
        self.assertEqual("image-reference",alt["metadata"]["original"]["content"]["parts"][0]["asset_pointer"])

    def test_notes_require_sources_and_keep_revisions(self):
        source = self.message()
        first = self.store.save_note("Coaching","Draft",[source["id"]],["Leadership"])
        second = self.store.save_note("Coaching","Corrected",[source["id"]],["Leadership"],supersedes_id=first["id"])
        self.assertEqual([second["id"]],[n["id"] for n in self.store.notes()])
        self.assertEqual("Draft",self.store.note(first["id"])["body"])
        self.assertEqual(first["id"],second["supersedes_id"])
        with self.assertRaises(ValueError):self.store.save_note("Bad","Body",[])
        with self.assertRaises(ValueError):self.store.save_note("Bad","Body",["not-a-source"])
        self.assertEqual(1,len(self.store.notes()))
        with self.assertRaises(ValueError):
            self.store.save_note("Race","Body",[source["id"]],supersedes_id=first["id"])

    def test_search_covers_raw_text_and_tags_without_assistant_claims(self):
        source = self.message("I helped a colleague prepare for promotion.")
        self.store.append(self.conv["id"],"I saved fictional millions in hosting costs.","assistant")
        self.store.save_note("Growth","Supported a colleague",[source["id"]],["coaching"])
        self.assertTrue(self.store.search("promotion")["results"])
        self.assertEqual("note",self.store.search("coaching")["results"][0]["kind"])
        self.assertFalse(self.store.search("millions")["results"])
        self.assertTrue(self.store.search("millions",include_assistant=True)["results"])
        self.assertTrue(self.store.search("Tell me about coaching someone",interview=True)["results"])
        self.store.search('" OR * NOT : ; DROP TABLE messages')
        self.assertEqual(2,self.store.stats()["messages"])

    def test_export_restores_every_byte_note_revision_and_link(self):
        payload = '{"messages":[{"body":"Original\\r\\n😀"}]}'.encode()
        import_bytes(self.store,payload)
        mid = self.store.recent_messages()[0]["id"]
        first = self.store.save_note("Original summary","First",[mid])
        self.store.save_note("Revised summary","Second",[mid],supersedes_id=first["id"])
        export = json.dumps(self.store.export()).encode()
        target = Store(self.root/"restored")
        import_bytes(target,export)
        self.assertEqual(self.store.export(),target.export())
        self.assertEqual(self.store.fingerprint(),target.fingerprint())
        with self.assertRaises(ValueError):import_bytes(target,export)
        self.assertTrue(target.search("Revised summary")["results"])

    def test_tampered_export_does_not_restore(self):
        self.message()
        data = self.store.export()
        data["tables"]["messages"][0]["body"]="Tampered"
        target=Store(self.root/"new")
        with self.assertRaises(ValueError):import_bytes(target,json.dumps(data).encode())
        self.assertEqual(0,target.stats()["messages"])

    def test_snapshot_contains_committed_wal_and_restore_keeps_backup(self):
        source=self.message("Exact\r\ntext")
        snapshot=self.store.snapshot(self.root/"snap.sqlite3")
        validate_snapshot(snapshot)
        self.message("Newer local record")
        backup=restore_snapshot(self.store,snapshot)
        self.assertTrue(backup.exists())
        self.assertEqual(1,self.store.stats()["messages"])
        self.assertEqual("Exact\r\ntext",self.store.message(source["id"])["body"])
        with closing(sqlite3.connect(backup)) as db:
            self.assertEqual(2,db.execute("SELECT COUNT(*) FROM messages").fetchone()[0])
        with self.assertRaises(ValueError):self.store.snapshot(snapshot)


if __name__=="__main__":unittest.main()
