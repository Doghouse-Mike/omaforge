#!/usr/bin/env python3
"""Bases evaluator vs Obsidian's own engine (`obsidian base:query`).

Seeds edge-case tasks into the TEST vault, then for every view in the
vault's .base files plus a battery of expressions (including everything the
view editor can generate), asks Obsidian which notes match (via a temporary
table view) and compares with OmaForge's evaluator (app/bases.js under node).
Cleans up after itself. Refuses to run against anything but the test vault.
"""
import json
import os
import subprocess
import sys
import time
from datetime import date, timedelta

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "core"))

from omaforge import bases, tasks  # noqa: E402
from omaforge.vault import Vault  # noqa: E402

VAULT = os.path.expanduser(os.environ.get("OMAFORGE_TEST_VAULT", ""))
PROBE_DIR = "zz-omaforge-oracle"
SEED_DIR = "TaskNotes/Tasks"
CLI = os.path.join(HERE, "obsidian-test")

T = date.today()
D = lambda n: (T + timedelta(days=n)).isoformat()  # noqa: E731

SEEDS = {
    "zz-bt due today": {"status": "todo", "priority": "high", "due": D(0)},
    "zz-bt due today 0930": {"status": "todo", "priority": "low", "due": D(0) + "T09:30"},
    "zz-bt overdue": {"status": "in-progress", "due": D(-3), "contexts": ["home", "Big Desk"]},
    "zz-bt in 7": {"status": "todo", "due": D(7), "scheduled": D(1), "projects": ["[[House]]"]},
    "zz-bt in 8": {"status": "todo", "due": D(8), "projects": ["[[House|the house]]", "[[Other]]"]},
    "zz-bt done": {"status": "done", "due": D(-1), "completedDate": D(-1), "tags_extra": ["Work/Deep"]},
    "zz-bt archived": {"status": "archived", "tags_extra": ["archived"]},
    "zz-bt weekly done today": {"status": "todo", "scheduled": D(7), "recurrence": "DTSTART:%s;FREQ=WEEKLY" % T.strftime("%Y%m%d"),
                                "complete_instances": [D(0)]},
    "zz-bt no dates": {"status": "todo", "priority": "none", "tags_extra": ["work"]},
}

EXPRESSIONS = [
    'date(due) == today()', 'date(due).date() == today()', 'date(due) < today()', 'date(due) <= today() + "7 days"',
    'date(due) <= today() + "7d"', 'date(due).date() <= today() + "7 days"', 'date(due) > today() - "2 days"',
    'date(due).isEmpty()', '!date(due).isEmpty()', 'due', '!due', 'due.isEmpty()',
    'complete_instances.contains(today().format("yyyy-MM-dd"))',
    'complete_instances.contains(today().format("YYYY-MM-DD"))',
    'list(projects).contains(link("House"))', 'list(projects).contains("[[House]]")',
    'projects.contains(link("House"))', 'list(contexts).contains("home")', 'contexts.contains("Big Desk")',
    'file.hasTag("work")', 'file.hasTag("Work")', 'file.hasTag("archived")', 'file.hasTag("work/deep")',
    'status != "done" && status != "archived"', 'status == "todo" || priority == "high"',
    'recurrence.isEmpty()', '!recurrence.isEmpty()', 'file.name.lower().contains("zz-bt in")',
    'file.inFolder("TaskNotes/Tasks")', 'file.hasProperty("completedDate")',
    'if(priority == "high", true, false)', 'number(date(due)) > number(today())',
    '((number(date(due)) - number(today())) / 86400000).floor() == 7',
    'list(contexts).length == 2', 'priority.isEmpty()',
    # null propagation (Obsidian: !null is null, null.contains() is null)
    '!list(contexts).contains("home")', 'list(contexts).contains("home") == false', 'contexts.contains("home") != true',
    '!due', '!date(due)', 'due == null', '!priority', '!!status', '!(status == "done")', '!recurrence',
    'date(due) <= today()', 'date(due) >= today()', 'date(due) > today()', 'date(due) != today()',
]


def editor_conditions(s):
    conds = []
    for st in s.statuses:
        conds += [{"field": "status", "op": "is", "value": st["value"]}, {"field": "status", "op": "isNot", "value": st["value"]}]
    conds += [{"field": "status", "op": "open"}, {"field": "status", "op": "completed"}]
    for p in s.priorities:
        conds.append({"field": "priority", "op": "is", "value": p["value"]})
    for f in ("due", "scheduled", "completedDate"):
        conds += [{"field": f, "op": "empty"}, {"field": f, "op": "notEmpty"}]
        for op in ("before", "after", "on", "onOrBefore", "onOrAfter"):
            for v in ("today", "+7", "-1", D(1)):
                conds.append({"field": f, "op": op, "value": v})
    conds += [{"field": "contexts", "op": "has", "value": "home"}, {"field": "contexts", "op": "lacks", "value": "home"},
              {"field": "projects", "op": "has", "value": "[[House]]"}, {"field": "projects", "op": "lacks", "value": "[[House]]"},
              {"field": "tags", "op": "has", "value": "work"}, {"field": "tags", "op": "lacks", "value": "work"},
              {"field": "archived", "op": "yes"}, {"field": "archived", "op": "no"},
              {"field": "recurring", "op": "yes"}, {"field": "recurring", "op": "no"},
              {"field": "title", "op": "has", "value": "In 7"}]
    return conds


def seed_text(fields):
    lines = ["---"]
    for k, v in fields.items():
        if k == "tags_extra":
            continue
        if isinstance(v, list):
            lines.append("%s:" % k)
            lines += ['  - "%s"' % x for x in v]
        else:
            lines.append("%s: %s" % (k, v))
    lines += ["tags:", "  - todo"] + ["  - %s" % t for t in fields.get("tags_extra", [])] + ["---", ""]
    return "\n".join(lines)


def obs_eval(code):
    r = subprocess.run([CLI, "eval", "code=" + code], capture_output=True, text=True, timeout=60)
    out = r.stdout.strip()
    return out[3:] if out.startswith("=> ") else out


def wait_indexed(rel, timeout=30):
    for _ in range(timeout * 2):
        if obs_eval("app.vault.getFileByPath(%s)?'yes':'no'" % json.dumps(rel)) == "yes":
            # and its metadata (tags, frontmatter) parsed
            if rel.endswith(".base") or obs_eval("app.metadataCache.getCache(%s)?'yes':'no'" % json.dumps(rel)) == "yes":
                return
        time.sleep(0.5)
    raise RuntimeError("Obsidian never indexed %s" % rel)


def query(rel, view):
    """Run Obsidian's base:query handler in-app and poll for the result: the
    CLI drops replies that take longer than about a second, and a query over
    a 4,000-note vault takes longer than that."""
    key = json.dumps([rel, view])
    obs_eval('(()=>{window.__omfq=window.__omfq||{};const k=%s;window.__omfq[k]=null;'
             'app.cli.handlers.get("base:query").handler({path:%s,view:%s,format:"paths"})'
             '.then(r=>{window.__omfq[k]={ok:String(r)}}).catch(e=>{window.__omfq[k]={err:String(e)}});return "kicked"})()'
             % (json.dumps(key), json.dumps(rel), json.dumps(view)))
    for _ in range(60):
        time.sleep(0.5)
        out = obs_eval("JSON.stringify(window.__omfq[%s])" % json.dumps(key))
        if out and out != "null":
            res = json.loads(out)
            if "err" in res:
                raise RuntimeError("base:query %s: %s" % (view, res["err"]))
            return sorted(p for p in res["ok"].splitlines() if p.endswith(".md"))
    raise RuntimeError("base:query %s timed out" % view)


def main():
    if not VAULT or not os.path.isdir(VAULT):
        sys.exit("set OMAFORGE_TEST_VAULT to a disposable vault copy that's open in Obsidian")
    os.environ.setdefault("OMAFORGE_TEST_VAULT_NAME", os.path.basename(VAULT.rstrip("/")))
    r = subprocess.run([CLI, "eval", "code=1"], capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        sys.exit(r.stderr.strip() or "Obsidian isn't on the test vault; aborting")
    os.makedirs(os.path.join(VAULT, PROBE_DIR), exist_ok=True)
    seeded = []
    try:
        for name, fields in SEEDS.items():
            rel = "%s/%s.md" % (SEED_DIR, name)
            with open(os.path.join(VAULT, rel), "w") as f:
                f.write(seed_text(fields))
            seeded.append(rel)
        for rel in seeded:
            wait_indexed(rel)
        v = Vault(VAULT)
        v.scan()
        s = v.settings
        task_map = {t["path"]: t for t in tasks.all_tasks(v, tasks.today()) if not t["error"]}

        cases = []  # (label, top_filters, formulas, view_filters, compiled filter)
        for d in bases.all_views(v):
            if d.get("unsupported") or d["file"].startswith(PROBE_DIR):
                continue
            with open(os.path.join(VAULT, d["file"])) as f:
                raw = bases.load_base(f.read())
            vf = next(x.get("filters") for x in raw["views"] if str(x.get("name")) == d["name"])
            cases.append(("view %s › %s" % (d["fileName"], d["name"]), raw.get("filters"), raw.get("formulas"), vf, d["filter"]))
        comp = bases.Compiler({})
        top = {"and": ['file.hasTag("todo")']}
        for e in EXPRESSIONS:
            cases.append(("expr " + e, top, None, {"and": [e]}, ["and", [comp.compile(top["and"][0]), comp.compile(e)]]))
        for c in editor_conditions(s):
            e = bases.condition_expr(c, s)
            cases.append(("editor %s %s %s" % (c["field"], c["op"], c.get("value", "")), top, None, {"and": [e]},
                          ["and", [comp.compile(top["and"][0]), comp.compile(e)]]))

        # Obsidian's answers: one throwaway base per distinct (filters, formulas)
        # header, every case a table view in it; written once, indexed, queried.
        expected = {}
        groups = {}
        for i, (label, tf, fm, vf, _ast) in enumerate(cases):
            key = json.dumps([tf, fm], sort_keys=True)
            groups.setdefault(key, (tf, fm, []))[2].append((i, label, vf))
        for gi, (tf, fm, items) in enumerate(groups.values()):
            d = {}
            if tf:
                d["filters"] = tf
            if fm:
                d["formulas"] = fm
            d["views"] = []
            for i, label, vf in items:
                view = {"type": "table", "name": "P%d" % i}
                if vf:
                    view["filters"] = vf
                d["views"].append(view)
            probe = "%s/probe%d.base" % (PROBE_DIR, gi)
            with open(os.path.join(VAULT, probe), "w") as f:
                f.write("\n".join(bases.dump(d)) + "\n")
            wait_indexed(probe)
            time.sleep(1)
            for i, label, vf in items:
                expected[label] = [p for p in query(probe, "P%d" % i) if p in task_map]

        payload = {"views": [{"id": c[0], "filter": c[4]} for c in cases], "tasks": task_map,
                   "now": int(time.time() * 1000)}
        got = json.loads(subprocess.run(["node", os.path.join(HERE, "bases-eval.mjs")], input=json.dumps(payload),
                                        capture_output=True, text=True, check=True).stdout)
        fails = 0
        for label, *_ in cases:
            e, g = set(expected[label]), set(got[label])
            ok = e == g
            fails += not ok
            print("%-62s %s%s" % (label[:62], "PASS" if ok else "FAIL", "" if ok else
                  "\n      obsidian only: %s\n      omaforge only: %s" % (
                      sorted(os.path.basename(x) for x in e - g), sorted(os.path.basename(x) for x in g - e))))
        print("\n%d/%d match Obsidian" % (len(cases) - fails, len(cases)))
        return fails
    finally:
        for rel in seeded:
            try:
                os.unlink(os.path.join(VAULT, rel))
            except OSError:
                pass
        p = os.path.join(VAULT, PROBE_DIR)
        for f in os.listdir(p):
            os.unlink(os.path.join(p, f))
        os.rmdir(p)


if __name__ == "__main__":
    sys.exit(1 if main() else 0)
