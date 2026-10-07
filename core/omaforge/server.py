"""JSON-lines bridge between the QML front end and the vault.

stdin:  {"id": 1, "op": "update", ...}
stdout: {"id": 1, "ok": true, "result": ...}   (one reply per request)
        {"event": "tasks", "upsert": [...], "remove": [...], "full": bool}
        {"event": "settings", ...}

The vault is polled (cheap stat walk) rather than inotify-watched: recursive
inotify needs a watch per folder, misses moves into unwatched trees, and a
sync client rewriting hundreds of files would flood it.
"""
import json
import os
import select
import sys
import time
import traceback

from . import bases, inline, notify, tasks
from .vault import Vault, VaultError

POLL_SEC = 1.5


class Server:
    def __init__(self, out=sys.stdout):
        self.out = out
        self.vault = None
        self.settings_mtime = None
        self.today = tasks.today()

    def send(self, obj):
        self.out.write(json.dumps(obj, ensure_ascii=False, default=str) + "\n")
        self.out.flush()

    # -- vault lifecycle -----------------------------------------------------

    def open(self, path):
        self.vault = Vault(path)
        self.settings_mtime = self._settings_stat()
        self.vault.scan()
        self.bases_sig = bases.bases_signature(self.vault)
        return self.snapshot()

    def snapshot(self):
        v = self.vault
        return {
            "vault": v.path,
            "vaultName": os.path.basename(v.path),
            "settings": v.settings.public() if v.mode == "tasknotes" else inline.settings_public(v),
            "today": self.today,
            "tasks": tasks.all_tasks(v, self.today),
            "views": bases.all_views(v) if v.mode == "tasknotes" else [],
            "mode": v.mode,
            "advancedUri": inline.plugin_enabled(v.path, "obsidian-advanced-uri"),
            "tasksPlugin": v.tasks_settings.public() if v.mode == "tasks" else None,
            "prefs": {"dates": notify.date_prefs()},
        }

    def _settings_stat(self):
        try:
            st = os.stat(self.vault.settings.path)
            return (st.st_mtime_ns, st.st_size)
        except OSError:
            return None

    def poll(self):
        if not self.vault:
            return
        st = self._settings_stat()
        new_day = tasks.today()
        if st != self.settings_mtime or new_day != self.today:
            # Settings or the date changed: every derived field may differ.
            self.settings_mtime = st
            self.today = new_day
            self.vault = Vault(self.vault.path)
            self.vault.scan()
            snap = self.snapshot()
            self.send({"event": "reset", **snap})
            return
        sig = bases.bases_signature(self.vault)
        if sig != getattr(self, "bases_sig", None):
            self.bases_sig = sig
            self.send({"event": "views", "views": bases.all_views(self.vault)})
        changed, removed = self.vault.scan()
        if self.vault.mode == "tasks":
            if changed or removed:
                up, gone = inline.delta(self.vault, changed, removed, self.today)
                self.send({"event": "tasks", "upsert": up, "remove": gone})
            return
        if changed or removed:
            self.send({"event": "tasks",
                       "upsert": [t for t in (tasks.task_for(self.vault, r, self.today) for r in changed) if t],
                       "remove": removed + [r for r in changed if not tasks.task_for(self.vault, r, self.today)]})

    # -- requests ------------------------------------------------------------

    def handle(self, req):
        op = req.get("op")
        if op == "open":
            return self.open(req["vault"])
        if not self.vault:
            raise VaultError("no-vault", "no vault open")
        if op == "snapshot":
            return self.snapshot()
        engine = inline.OPS if self.vault.mode == "tasks" else tasks.OPS
        fn = engine.get(op) or bases.OPS.get(op) or notify.OPS.get(op)
        if not fn:
            raise VaultError("bad-op", "unknown op %r" % op)
        result = fn(self.vault, req, self.today)
        # A write's own results go back in the reply; push the same task to
        # every listener as an event so lists update without a rescan.
        upsert = result.pop("_upsert", []) if isinstance(result, dict) else []
        remove = result.pop("_remove", []) if isinstance(result, dict) else []
        if upsert or remove:
            self.send({"event": "tasks", "upsert": upsert, "remove": remove})
        return result

    def run(self, inp=sys.stdin):
        buf = b""
        fd = inp.fileno()
        last_poll = time.monotonic()
        while True:
            timeout = max(0.0, POLL_SEC - (time.monotonic() - last_poll))
            ready, _, _ = select.select([fd], [], [], timeout)
            if ready:
                chunk = os.read(fd, 65536)
                if not chunk:
                    return
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    if line.strip():
                        self.dispatch(line)
            if time.monotonic() - last_poll >= POLL_SEC:
                last_poll = time.monotonic()
                try:
                    self.poll()
                except Exception as e:  # never let a bad file kill the bridge
                    self.send({"event": "error", "message": "scan failed: %s" % e})

    def dispatch(self, line):
        rid = None
        try:
            req = json.loads(line)
            rid = req.get("id")
            self.send({"id": rid, "ok": True, "result": self.handle(req)})
        except VaultError as e:
            self.send({"id": rid, "ok": False, "code": e.code, "message": str(e)})
        except Exception as e:
            traceback.print_exc(file=sys.stderr)
            self.send({"id": rid, "ok": False, "code": "internal", "message": "%s: %s" % (type(e).__name__, e)})


def main():
    Server().run()
