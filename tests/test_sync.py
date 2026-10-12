import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from receipts.store import Store
from receipts.sync import sync_snapshot,verify_private
from receipts import sync


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        self.remote=self.root/"remote.git"
        subprocess.run(["git","init","--bare","--initial-branch=main",str(self.remote)],check=True,capture_output=True)
        initial=self.root/"initial";initial.mkdir()
        subprocess.run(["git","clone",str(self.remote),str(initial)],check=True,capture_output=True)
        (initial/"README.md").write_text("Synthetic private-records test repository")
        for args in (("add","README.md"),("-c","user.name=Test","-c","user.email=test@localhost","commit","-m","Initial"),("push","origin","main")):
            subprocess.run(["git","-C",str(initial),*args],check=True,capture_output=True)
        original=sync.run_git
        def local_git(directory,*args,**kwargs):
            args=tuple(str(self.remote) if str(arg).startswith("https://github.com/") else arg for arg in args)
            return original(directory,*args,**kwargs)
        self.privacy=patch("receipts.sync.verify_private",return_value="main");self.privacy.start()
        self.git=patch("receipts.sync.run_git",side_effect=local_git);self.git.start()
        self.a=Store(self.root/"a");self.b=Store(self.root/"b")
        self.conv=self.a.create_conversation("Synthetic sync story")
        self.a.append(self.conv["id"],"Unchanged original\r\ntext")

    def tearDown(self):
        self.git.stop();self.privacy.stop();self.tmp.cleanup()

    def test_push_pull_and_conflicts_do_not_lose_local_records(self):
        sync_snapshot(self.a,"push","example/private-records")
        sync_snapshot(self.b,"pull","example/private-records")
        self.assertEqual(self.a.fingerprint(),self.b.fingerprint())
        self.a.append(self.conv["id"],"Computer A changes")
        sync_snapshot(self.a,"push","example/private-records")
        self.b.append(self.conv["id"],"Computer B changes")
        before=self.b.fingerprint()
        with self.assertRaises(ValueError):sync_snapshot(self.b,"push","example/private-records")
        with self.assertRaises(ValueError):sync_snapshot(self.b,"pull","example/private-records")
        self.assertEqual(before,self.b.fingerprint())

    def test_clean_pull_preserves_previous_database_as_backup(self):
        sync_snapshot(self.a,"push","example/private-records")
        sync_snapshot(self.b,"pull","example/private-records")
        self.a.append(self.conv["id"],"Later story")
        sync_snapshot(self.a,"push","example/private-records")
        result=sync_snapshot(self.b,"pull","example/private-records")
        self.assertTrue(Path(result["previous_backup"]).exists())
        self.assertEqual(self.a.fingerprint(),self.b.fingerprint())

    def test_public_remote_is_rejected_before_any_git_operation(self):
        with patch("receipts.sync.verify_private",side_effect=ValueError("Repository is public")),patch("receipts.sync.run_git") as git:
            with self.assertRaises(ValueError):sync_snapshot(self.a,"push","example/public-code")
            git.assert_not_called()

    def test_network_failure_does_not_record_success_or_modify_vault(self):
        before=self.a.fingerprint()
        with patch("receipts.sync.run_git",side_effect=ValueError("No connection")):
            with self.assertRaises(ValueError):sync_snapshot(self.a,"push","example/private-records")
        self.assertFalse((self.a.vault/"sync-state.json").exists())
        self.assertEqual(before,self.a.fingerprint())


class PrivacyTests(unittest.TestCase):
    def test_visibility_must_be_explicitly_private(self):
        import io
        for payload in ({"private":False,"visibility":"public"},{"private":True,"visibility":"internal"},{}):
            with patch("receipts.sync.github_token",return_value="synthetic-token"),patch("receipts.sync.urlopen",return_value=io.BytesIO(json.dumps(payload).encode())):
                with self.assertRaises(ValueError):verify_private("example/records")


if __name__=="__main__":unittest.main()
