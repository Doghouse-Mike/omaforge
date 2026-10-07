#!/usr/bin/env python3
"""Differential test: TaskNotes (inside a running Obsidian) vs OmaForge.

For each scenario, two identical synthetic task notes are written into the
TEST vault. TaskNotes performs the operation on copy A (via the Obsidian CLI
`eval`), OmaForge's core performs it on copy B, and the resulting
frontmatter is compared (timestamps aside). TaskNotes is then asked to read
copy B, proving it understands what we wrote.

Refuses to run against anything but the disposable test vault.
"""
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "core"))

from omaforge import tasks  # noqa: E402
from omaforge.frontmatter import Note  # noqa: E402
from omaforge.vault import Vault  # noqa: E402

# A disposable copy of a vault, open in Obsidian. Never point this at a vault you care about.
VAULT = os.path.expanduser(os.environ.get("OMAFORGE_TEST_VAULT", ""))
VAULT_NAME = os.path.basename(VAULT.rstrip("/"))
CLI = os.path.join(HERE, "obsidian-test")
FOLDER = "TaskNotes/Tasks"
IGNORE = {"dateModified", "dateCreated"}

if not VAULT or not os.path.isdir(VAULT):
    sys.exit("set OMAFORGE_TEST_VAULT to a disposable vault copy that's open in Obsidian")
os.environ.setdefault("OMAFORGE_TEST_VAULT_NAME", VAULT_NAME)


def require_test_vault():
    """Stop before anything runs unless Obsidian is on the test vault (the CLI
    otherwise acts on whatever vault is open)."""
    r = subprocess.run([CLI, "eval", "code=1"], capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        sys.exit(r.stderr.strip() or "Obsidian isn't on the test vault; aborting")


def _eval(code):
    r = subprocess.run([CLI, "eval", "code=" + code], capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise SystemExit("stopped: " + (r.stderr.strip() or "Obsidian CLI failed"))
    out = r.stdout.strip()
    return out[3:] if out.startswith("=> ") else out


def obs(js):
    """Run async JS in Obsidian and wait for its result. The code is started
    in-app and polled: the CLI drops replies that take over about a second."""
    key = "k%d" % time.monotonic_ns()
    body = "const p=app.plugins.plugins.tasknotes;const c=p.cacheManager;const S=p.taskService;" \
           "const T=async(x)=>{for(let i=0;i<40;i++){const t=await c.getTaskInfo(x);if(t)return t;await new Promise(r=>setTimeout(r,100))}throw new Error('no task '+x)};" \
           "%s" % js
    _eval("(()=>{window.__omfd=window.__omfd||{};const k=%s;window.__omfd[k]=null;"
          "(async()=>{%s})().then(r=>{window.__omfd[k]={ok:String(r)}}).catch(e=>{window.__omfd[k]={ok:'ERR '+e}});return 'kicked'})()"
          % (json.dumps(key), body))
    for _ in range(120):
        time.sleep(0.25)
        out = _eval("JSON.stringify(window.__omfd[%s])" % json.dumps(key))
        if out and out != "null":
            return json.loads(out)["ok"]
    return "ERR timeout"


def fm(path):
    with open(os.path.join(VAULT, path), encoding="utf-8") as f:
        text = f.read()
    d = Note(text).data()
    return {k: v for k, v in d.items() if k not in IGNORE}, text


def write(path, text):
    full = os.path.join(VAULT, path)
    with open(full, "w", encoding="utf-8") as f:
        f.write(text)


def cleanup(*paths):
    for p in paths:
        for base in (p, p.replace("TaskNotes/Tasks/", "TaskNotes/Archive/")):
            full = os.path.join(VAULT, base)
            if os.path.exists(full):
                os.unlink(full)


SEED_PLAIN = """---
status: todo
priority: normal
due: 2026-10-10
scheduled: 2026-10-08
contexts:
  - home
projects:
  - "[[Some Project]]"
dateCreated: 2026-10-01T10:00:00.000+01:00
dateModified: 2026-10-01T10:00:00.000+01:00
tags:
  - todo
  - extra
---

Body text stays.
"""

SEED_DONE = SEED_PLAIN.replace("status: todo", "status: done").replace(
    "dateModified: 2026-10-01T10:00:00.000+01:00", "dateModified: 2026-10-01T10:00:00.000+01:00\ncompletedDate: 2026-10-02")

SEED_WEEKLY = """---
status: todo
priority: normal
scheduled: 2026-09-28
due: 2026-09-29
recurrence: DTSTART:20260928;FREQ=WEEKLY;BYDAY=MO
dateCreated: 2026-09-20T10:00:00.000+01:00
dateModified: 2026-09-20T10:00:00.000+01:00
tags:
  - todo
---
"""

SEED_DAILY_NODT = """---
status: todo
priority: high
scheduled: 2026-10-01T09:00
recurrence: FREQ=DAILY;INTERVAL=2
complete_instances:
  - 2026-10-01
dateCreated: 2026-09-20T10:00:00.000+01:00
dateModified: 2026-09-20T10:00:00.000+01:00
tags:
  - todo
---
"""

REMS = '[{"id":"rem_1","type":"relative","relatedTo":"due","offset":"-PT15M"},{"id":"rem_2","type":"absolute","absoluteTime":"2026-10-09T09:00:00","description":"Ring the bank"}]'

# (name, seed, TaskNotes JS acting on task `t` at path A, our request)
SCENARIOS = [
    ("complete", SEED_PLAIN, 'await S.updateProperty(t,"status","done")', {"op": "toggleComplete"}),
    ("uncomplete", SEED_DONE, 'await S.updateProperty(t,"status","todo")', {"op": "toggleComplete"}),
    ("in-progress", SEED_PLAIN, 'await S.updateProperty(t,"status","in-progress")', {"op": "setStatus", "status": "in-progress"}),
    ("done->archived restamps", SEED_DONE, 'await S.updateProperty(t,"status","archived")', None),  # see below
    ("priority", SEED_PLAIN, 'await S.updateProperty(t,"priority","high")', {"op": "update", "set": {"priority": "high"}}),
    ("set due", SEED_PLAIN, 'await S.updateProperty(t,"due","2026-11-01")', {"op": "update", "set": {"due": "2026-11-01"}}),
    ("clear due", SEED_PLAIN, 'await S.updateProperty(t,"due",undefined)', {"op": "update", "set": {"due": ""}}),
    ("datetime scheduled", SEED_PLAIN, 'await S.updateProperty(t,"scheduled","2026-10-09T14:30")', {"op": "update", "set": {"scheduled": "2026-10-09T14:30"}}),
    ("contexts", SEED_PLAIN, 'await S.updateTask(t,{contexts:["home","@desk"]})', {"op": "update", "set": {"contexts": ["home", "@desk"]}}),
    ("clear projects", SEED_PLAIN, 'await S.updateTask(t,{projects:[]})', {"op": "update", "set": {"projects": []}}),
    ("tags", SEED_PLAIN, 'await S.updateTask(t,{tags:["todo","extra","new/one"]})', {"op": "update", "set": {"tags": ["extra", "new/one"]}}),
    ("archive", SEED_PLAIN, 'await S.toggleArchive(t)', {"op": "archive", "on": True}),
    ("recurring complete", SEED_WEEKLY, 'await S.toggleRecurringTaskComplete(t)', {"op": "toggleComplete"}),
    ("recurring skip", SEED_WEEKLY, 'await S.toggleRecurringTaskSkipped(t)', {"op": "skipInstance"}),
    ("set reminders", SEED_PLAIN, 'await S.updateProperty(t,"reminders",%s)' % REMS,
     {"op": "update", "set": {"reminders": json.loads(REMS)}}),
    ("clear reminders", SEED_PLAIN.replace("tags:", "reminders:\n  - id: rem_1\n    type: relative\n    relatedTo: due\n    offset: -PT15M\ntags:"),
     'await S.updateProperty(t,"reminders",[])', {"op": "update", "set": {"reminders": []}}),
    ("add repeat", SEED_PLAIN.replace("scheduled: 2026-10-08", "scheduled: 2026-10-09"),
     'await S.updateTask(t,{recurrence:"FREQ=WEEKLY;BYDAY=MO"})', {"op": "update", "set": {"recurrence": "FREQ=WEEKLY;BYDAY=MO"}}),
    ("add repeat, timed", SEED_PLAIN.replace("scheduled: 2026-10-08", "scheduled: 2026-10-09T14:30"),
     'await S.updateTask(t,{recurrence:"FREQ=WEEKLY;BYDAY=MO"})', {"op": "update", "set": {"recurrence": "FREQ=WEEKLY;BYDAY=MO"}}),
    ("add repeat, due only", SEED_PLAIN.replace("scheduled: 2026-10-08\n", ""),
     'await S.updateTask(t,{recurrence:"FREQ=WEEKLY;BYDAY=MO"})', {"op": "update", "set": {"recurrence": "FREQ=WEEKLY;BYDAY=MO"}}),
    ("add repeat, every 2 weeks", SEED_PLAIN.replace("scheduled: 2026-10-08", "scheduled: 2026-10-01"),
     'await S.updateTask(t,{recurrence:"FREQ=WEEKLY;INTERVAL=2;BYDAY=FR"})', {"op": "update", "set": {"recurrence": "FREQ=WEEKLY;INTERVAL=2;BYDAY=FR"}}),
    ("change repeat", SEED_WEEKLY, 'await S.updateTask(t,{recurrence:"FREQ=MONTHLY;BYMONTHDAY=1"})',
     {"op": "update", "set": {"recurrence": "FREQ=MONTHLY;BYMONTHDAY=1"}}),
    ("clear repeat", SEED_WEEKLY, 'await S.updateTask(t,{recurrence:undefined})', {"op": "update", "set": {"recurrence": ""}}),
    ("anchor completion", SEED_WEEKLY, 'await S.updateTask(t,{recurrence_anchor:"completion"})',
     {"op": "update", "set": {"recurrenceAnchor": "completion"}}),
    ("blocked by", SEED_PLAIN, 'await S.updateTask(t,{blockedBy:[{uid:"[[Some Other Task]]",reltype:"FINISHTOSTART"}]})',
     {"op": "update", "set": {"blockedBy": [{"uid": "[[Some Other Task]]", "reltype": "FINISHTOSTART"}]}}),
    ("unblock", SEED_PLAIN.replace("tags:", "blockedBy:\n  - uid: \"[[X]]\"\n    reltype: FINISHTOSTART\ntags:"),
     'await S.updateTask(t,{blockedBy:[]})', {"op": "update", "set": {"blockedBy": []}}),
    ("unarchive", SEED_PLAIN.replace("  - extra", "  - extra\n  - archived"), 'await S.toggleArchive(t)', {"op": "archive", "on": False}),
    ("recurring uncomplete", SEED_WEEKLY.replace("tags:", "complete_instances:\n  - 2026-09-28\nskipped_instances: []\ntags:"),
     'await S.toggleRecurringTaskComplete(t, new Date(Date.UTC(2026,8,28)))', {"op": "toggleComplete", "date": "2026-09-28"}),
    ("completion anchor", SEED_WEEKLY.replace("tags:", "recurrence_anchor: completion\ntags:"),
     'await S.toggleRecurringTaskComplete(t)', {"op": "toggleComplete"}),
    ("recurring no DTSTART complete", SEED_DAILY_NODT, 'await S.toggleRecurringTaskComplete(t)', {"op": "toggleComplete"}),
]


CREATES = [
    ("create plain", {"title": "zz difftest create", "due": "2026-10-10", "contexts": ["home"], "projects": ["[[Some Project]]"], "tags": ["extra"]}),
    ("create odd title", {"title": "zz difftest: what? #1", "priority": "high"}),
    ("create recurring", {"title": "zz difftest weekly", "scheduled": "2026-10-05", "recurrence": "FREQ=WEEKLY;BYDAY=MO"}),
    ("create collision", {"title": "zz difftest create"}),
]


def run_creates(vault, day):
    failures = 0
    made = []
    try:
        return _run_creates(vault, day, made)
    finally:
        for p in made:
            cleanup(p)


def _run_creates(vault, day, made):
    failures = 0
    for name, fields in CREATES:
        js_fields = dict(fields, status="todo", priority=fields.get("priority", "normal"), tags=["todo"] + fields.get("tags", []))
        pa = obs("const r=await S.createTask(%s);return r.file.path" % json.dumps(js_fields))
        if not pa or pa.startswith("ERR"):
            raise RuntimeError("TaskNotes createTask failed: %r" % pa)
        made.append(pa)
        time.sleep(0.8)
        # Same title on our side, in a sibling folder name, so both see the same collisions.
        r = tasks.OPS["create"](vault, {"fields": dict(fields, title=fields["title"].replace("zz difftest", "zz difftesu"))}, day)
        pb = r["task"]["path"]
        made.append(pb)
        fa, ta = fm(pa)
        fb, tb = fm(pb)
        if "title" in fa:
            fa["title"] = fa["title"].replace("zz difftest", "zz difftesu")
        if fa.get("recurrence") and fb.get("recurrence"):
            pass
        name_ok = os.path.basename(pa).replace("zz difftest", "zz difftesu") == os.path.basename(pb)
        layout_ok = list(fa) == list(fb) and ta.endswith("---\n\n") == tb.endswith("---\n\n")
        ok = fa == fb and name_ok and layout_ok
        failures += not ok
        print("%-32s %s" % (name, "PASS" if ok else "FAIL"))
        if not ok:
            print("    files: %s | %s" % (pa, pb))
            print("    TaskNotes:", json.dumps(fa))
            print("    ours:     ", json.dumps(fb))
            if not layout_ok:
                print("    key order / trailing blank line differ")
    return failures


def run():
    require_test_vault()
    vault = Vault(VAULT)
    vault.scan()
    day = tasks.today()
    failures = 0
    for i, (name, seed, js, req) in enumerate(SCENARIOS):
        a = "%s/zz-difftest-%02d-A.md" % (FOLDER, i)
        b = "%s/zz-difftest-%02d-B.md" % (FOLDER, i)
        cleanup(a, b)
        try:
            failures += scenario(vault, day, name, seed, js, req, a, b)
        finally:
            cleanup(a, b)
    failures += run_creates(vault, day)
    total = len(SCENARIOS) + len(CREATES)
    print("\n%d/%d passed" % (total - failures, total))
    return failures


def scenario(vault, day, name, seed, js, req, a, b):
        write(a, seed)
        write(b, seed)
        time.sleep(0.6)
        res = obs('const t=await T(%s);const r=%s;return "ok"' % (json.dumps(a), js))
        if req is None:
            req = {"op": "setStatus", "status": "archived"}
        vault.scan()
        task = tasks.task_for(vault, b, day)
        r = tasks.OPS[req["op"]](vault, dict(req, path=b, expect=task["expect"]), day)
        b2 = (r.get("task") or {}).get("path") or b
        a2 = a if os.path.exists(os.path.join(VAULT, a)) else a.replace("Tasks/", "Archive/")
        time.sleep(1.0)
        fa, ta = fm(a2)
        fb, tb = fm(b2)
        same_place = os.path.dirname(a2) == os.path.dirname(b2)
        body_ok = ta.split("---", 2)[2] == tb.split("---", 2)[2]
        if name == "done->archived restamps":
            # TaskNotes defers auto-archive 5 min (only while Obsidian runs);
            # we archive at once. Compare everything but the tag + folder.
            fb = dict(fb, tags=[t for t in fb.get("tags", []) if t != "archived"])
            same_place = True
        read_back = obs('const t=await T(%s);return JSON.stringify([t.title,t.status,t.scheduled||"",t.due||"",t.archived])' % json.dumps(b2))
        ok = fa == fb and same_place and body_ok and not read_back.startswith("ERR")
        print("%-32s %s %s" % (name, "PASS" if ok else "FAIL", "" if res == "ok" else "(TaskNotes: %s)" % res))
        if not ok:
            for k in sorted(set(fa) | set(fb)):
                if fa.get(k) != fb.get(k):
                    print("    %-20s TaskNotes=%r  ours=%r" % (k, fa.get(k), fb.get(k)))
            if not same_place:
                print("    folder: TaskNotes=%s ours=%s" % (a2, b2))
            if not body_ok:
                print("    body differs")
            print("    TaskNotes reads ours as:", read_back)
        cleanup(a2, b2)
        return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(1 if run() else 0)
