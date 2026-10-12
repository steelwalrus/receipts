"""Explicit GitHub-private snapshot transfer. Single writer, never binary merging."""

import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile
from pathlib import Path
from urllib.request import Request,urlopen

from .store import APP_ID,CODE_ROOT,SCHEMA_VERSION,now


def run_git(directory,*args,input_text=None):
    import base64
    environment = {**os.environ,"GIT_TERMINAL_PROMPT":"0"}
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token:
        environment.update(GIT_CONFIG_COUNT="1",GIT_CONFIG_KEY_0="http.https://github.com/.extraheader",
            GIT_CONFIG_VALUE_0="Authorization: Basic "+base64.b64encode(("x-access-token:"+token).encode()).decode())
    options = ["-c","http.sslBackend=openssl"] if os.name=="nt" else []
    result = subprocess.run(["git",*options,"-C",str(directory),*args],
        input=input_text,capture_output=True,text=True,encoding="utf-8",timeout=90,
        env=environment)
    if result.returncode:
        raise ValueError("Git operation failed. Check authentication, connectivity, and repository access. No database was replaced")
    return result.stdout.strip()


def github_token():
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token:
        return token
    if shutil.which("gh"):
        result = subprocess.run(["gh","auth","token","--hostname","github.com"],capture_output=True,text=True,timeout=15)
        if result.returncode==0 and result.stdout.strip():
            return result.stdout.strip()
    # Standard Git Credential Manager can supply credentials without persisting them here.
    result = subprocess.run(["git","credential","fill"],input="protocol=https\nhost=github.com\n\n",
        capture_output=True,text=True,timeout=20,env={**os.environ,"GIT_TERMINAL_PROMPT":"0","GCM_INTERACTIVE":"never"})
    if result.returncode==0:
        values = dict(line.split("=",1) for line in result.stdout.splitlines() if "=" in line)
        if values.get("password"):
            return values["password"]
    raise ValueError("Sign in with GitHub CLI (gh auth login) or Git Credential Manager, or set GH_TOKEN. Private visibility must be verified")


def verify_private(repo):
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+",repo):
        raise ValueError("Use a GitHub repository in owner/name form")
    request = Request("https://api.github.com/repos/"+repo,headers={
        "Authorization":"Bearer "+github_token(),"Accept":"application/vnd.github+json","User-Agent":"Receipts/0.1"})
    try:
        with urlopen(request,timeout=20) as response:
            data = json.load(response)
    except Exception as error:
        raise ValueError("Could not verify repository privacy and access; transfer cancelled") from error
    if data.get("private") is not True or data.get("visibility") not in ("private",None):
        raise ValueError("Refusing to transfer career records to a repository that is not private")
    if data.get("full_name","").lower()!=repo.lower():
        raise ValueError("Repository identity changed; use its current owner/name")
    return data.get("default_branch") or "main"


def validate_snapshot(path,expected_sha=None):
    path = Path(path).resolve()
    if expected_sha and hashlib.sha256(path.read_bytes()).hexdigest()!=expected_sha:
        raise ValueError("Snapshot checksum does not match its manifest")
    db = sqlite3.connect(path.as_uri()+"?mode=ro",uri=True)
    try:
        if db.execute("PRAGMA application_id").fetchone()[0]!=APP_ID:
            raise ValueError("This is not a Receipts database")
        if db.execute("PRAGMA user_version").fetchone()[0]!=SCHEMA_VERSION:
            raise ValueError("Unsupported snapshot version")
        if db.execute("PRAGMA integrity_check").fetchone()[0]!="ok" or db.execute("PRAGMA foreign_key_check").fetchall():
            raise ValueError("Snapshot integrity check failed")
        for body,checksum in db.execute("SELECT body,sha256 FROM messages"):
            if hashlib.sha256(body.encode("utf-8")).hexdigest()!=checksum:
                raise ValueError("An original message checksum does not match")
    finally:
        db.close()


def restore_snapshot(store,path):
    """Call under the vault lock. Online backup safely replaces the destination DB."""
    validate_snapshot(path)
    with store.lock.hold():
        previous = store.snapshot(store.vault/"backups"/("before-restore-"+now().replace(":","-")+".sqlite3"))
        source = sqlite3.connect(Path(path).resolve().as_uri()+"?mode=ro",uri=True)
        destination = sqlite3.connect(store.path)
        try:
            source.backup(destination)
        finally:
            source.close()
            destination.close()
        return previous


def sync_snapshot(store,direction,repo):
    if direction not in ("push","pull"):
        raise ValueError("Choose push or pull")
    branch = verify_private(repo)  # Fail closed before cloning, uploading, or restoring.
    state_path = store.vault/"sync-state.json"
    with store.lock.hold():
        state = json.loads(state_path.read_text("utf-8")) if state_path.exists() else {}
        if state and state.get("repository")!=repo.lower():
            raise ValueError("This vault is paired with a different repository. Use a separate vault")
        local_hash = store.fingerprint()
        with tempfile.TemporaryDirectory(prefix="receipts-sync-") as directory:
            checkout = Path(directory)
            # A fresh checkout avoids stale working trees and accidentally staged local files.
            run_git(checkout,"clone","--depth","1","--branch",branch,"https://github.com/"+repo+".git",".")
            snapshot = checkout/"receipts.sqlite3"
            manifest_path = checkout/"snapshot.json"
            if manifest_path.is_symlink() or snapshot.is_symlink():
                raise ValueError("Snapshot paths cannot be symbolic links")
            manifest = json.loads(manifest_path.read_text("utf-8")) if manifest_path.exists() else None
            if snapshot.exists()!=bool(manifest):
                raise ValueError("Remote snapshot or manifest is missing; repair the private repository first")
            if manifest:
                if manifest.get("format")!="receipts-snapshot-v1":
                    raise ValueError("Unsupported snapshot manifest")
                validate_snapshot(snapshot,manifest.get("sha256"))
            remote_hash = manifest.get("content_hash") if manifest else None
            base = state.get("content_hash")
            if direction=="push":
                if remote_hash and remote_hash not in (base,local_hash):
                    raise ValueError("Remote records have changed. Pull first; divergent databases cannot be merged automatically")
                if local_hash!=remote_hash:
                    if snapshot.exists():
                        snapshot.unlink()  # Only the verified file in our new temporary checkout.
                    store.snapshot(snapshot)
                    manifest = {"format":"receipts-snapshot-v1","schema_version":SCHEMA_VERSION,
                        "created_at":now(),"content_hash":local_hash,
                        "sha256":hashlib.sha256(snapshot.read_bytes()).hexdigest()}
                    manifest_path.write_text(json.dumps(manifest,indent=2)+"\n",encoding="utf-8")
                    run_git(checkout,"add","--","receipts.sqlite3","snapshot.json")
                    run_git(checkout,"-c","user.name=Receipts","-c","user.email=receipts@localhost","commit","-m","Save private Receipts snapshot")
                    verify_private(repo)  # Check again immediately before transmission.
                    run_git(checkout,"push","origin","HEAD:"+branch)  # No force push; rejects competing writers.
                resulting_hash = local_hash
                result = {"direction":"push","repository":repo,"changed":local_hash!=remote_hash}
            else:
                if not manifest:
                    raise ValueError("No snapshot has been pushed to this private repository")
                empty = not any(store.stats()[key] for key in ("conversations","messages","notes","imports"))
                if not empty and local_hash not in (base,remote_hash):
                    raise ValueError("Local records have unpushed changes. Push first or pull into a new vault; nothing overwritten")
                previous = None
                if local_hash!=remote_hash:
                    previous = restore_snapshot(store,snapshot)
                resulting_hash = store.fingerprint()
                if resulting_hash!=remote_hash:
                    if previous:
                        restore_snapshot(store,previous)
                    raise ValueError("Restored content did not match the snapshot manifest; previous database preserved")
                result = {"direction":"pull","repository":repo,"changed":local_hash!=remote_hash,
                          "previous_backup":str(previous) if previous else None}
            temporary = state_path.with_suffix(".tmp")
            temporary.write_text(json.dumps({"repository":repo.lower(),"content_hash":resulting_hash,"synced_at":now()},indent=2),encoding="utf-8")
            temporary.replace(state_path)
            return result
