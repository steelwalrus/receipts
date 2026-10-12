import http.client
import json
import tempfile
import threading
import unittest

from receipts.server import make_server
from receipts.store import Store


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.store=Store(self.tmp.name)
        self.server=make_server(self.store,0)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        self.token=self.request("GET","/api/state")[1]["token"]

    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join();self.tmp.cleanup()

    def request(self,method,path,body=None,headers=None):
        connection=http.client.HTTPConnection("127.0.0.1",self.server.server_port,timeout=5)
        connection.request(method,path,body,headers or {})
        response=connection.getresponse()
        content=response.read()
        result=(response.status,json.loads(content) if response.getheader("Content-Type","").startswith("application/json") else content)
        connection.close()
        return result

    def post(self,path,body,extra=None):
        return self.request("POST",path,json.dumps(body),{"Content-Type":"application/json","X-Receipts-Token":self.token,**(extra or {})})

    def test_ui_assets_and_no_private_file_serving(self):
        self.assertEqual(200,self.request("GET","/")[0])
        self.assertEqual(200,self.request("GET","/app.js")[0])
        self.assertEqual(404,self.request("GET","/../receipts.sqlite3")[0])
        self.assertEqual(404,self.request("GET","/receipts.sqlite3")[0])

    def test_capture_note_search_roundtrip_and_data_export(self):
        status,conv=self.post("/api/conversations",{"title":"Fictional example"})
        self.assertEqual(201,status)
        body="  I coached someone.\n\n<em>literal text</em>  "
        status,message=self.post("/api/messages",{"conversation_id":conv["id"],"body":body})
        self.assertEqual(201,status)
        self.assertEqual(body,self.request("GET","/api/messages/"+message["id"])[1]["body"])
        status,note=self.post("/api/notes",{"title":"Coaching","body":"Derived","source_ids":[message["id"]]})
        self.assertEqual(201,status)
        self.assertTrue(self.request("GET","/api/search?q=coaching")[1]["results"])
        self.assertEqual("receipts-export-v1",self.request("GET","/api/export")[1]["format"])

    def test_host_origin_and_token_boundaries(self):
        self.assertEqual(403,self.request("GET","/api/state",headers={"Host":"attacker.example"})[0])
        self.assertEqual(403,self.request("GET","/api/state",headers={"Origin":"https://attacker.example"})[0])
        self.assertEqual(403,self.request("GET","/api/state",headers={"Sec-Fetch-Site":"cross-site"})[0])
        self.assertEqual(403,self.request("POST","/api/conversations",'{}',{"Content-Type":"application/json"})[0])
        self.assertEqual(403,self.post("/api/conversations",{"title":"Bad"},{"Origin":"https://attacker.example"})[0])
        self.assertEqual(0,self.store.stats()["conversations"])

    def test_validation_is_recoverable(self):
        self.assertEqual(400,self.post("/api/messages",{"body":"hello","conversation_id":"missing"})[0])
        self.assertEqual(400,self.post("/api/conversations",{"title":""})[0])
        self.assertEqual(200,self.request("GET","/api/state")[0])


if __name__=="__main__":unittest.main()
