#!/usr/bin/env python3
"""Bases evaluator vs Obsidian's own engine (`obsidian base:query`).

Seeds edge-case tasks into the TEST vault, then for every view in the
vault's .base files plus a battery of expressions (including everything the
view editor can generate), asks Obsidian which notes match (via a temporary
table view) and compares with OmaForge's evaluator (app/bases.js under node).
Views with a sort, plus SORTS below, are also compared for order: Obsidian's
JSON output is in display order, checked against the app's computeBase
(app/views.js) on the same notes.
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
    # min/max: an empty argument empties the result
    'max(0, 10 - number(date(due))) == null', 'max(1, 2) == 2', 'min(5, -2, 3) == -2', 'max(0, nosuch) == null',
]


# Extra orderings, each over every #todo note.
SORTS = [
    [{"property": "due", "direction": "ASC"}],
    [{"property": "due", "direction": "DESC"}],
    [{"property": "scheduled", "direction": "ASC"}],
    [{"property": "priority", "direction": "ASC"}],
    [{"property": "priority", "direction": "DESC"}],
    [{"property": "status", "direction": "ASC"}],
    [{"property": "file.name", "direction": "ASC"}],
    [{"property": "file.name", "direction": "DESC"}],
    [{"property": "title", "direction": "ASC"}],
    [{"property": "dateCreated", "direction": "DESC"}],
    [{"property": "file.mtime", "direction": "DESC"}],
    [{"property": "contexts", "direction": "ASC"}],
    [{"property": "projects", "direction": "ASC"}],
    [{"property": "status", "direction": "ASC"}, {"property": "due", "direction": "ASC"}],
    [{"property": "priority", "direction": "DESC"}, {"property": "file.name", "direction": "ASC"}],
]


# Groupings, each over every #todo note (with a sort, so the order inside
# each group is checked too).
GROUPS = [
    ({"property": "status", "direction": "ASC"}, [{"property": "due", "direction": "ASC"}]),
    ({"property": "status", "direction": "DESC"}, [{"property": "file.name", "direction": "ASC"}]),
    ({"property": "priority", "direction": "ASC"}, [{"property": "due", "direction": "DESC"}]),
    ({"property": "due", "direction": "ASC"}, [{"property": "file.name", "direction": "ASC"}]),
    ({"property": "scheduled", "direction": "DESC"}, [{"property": "file.name", "direction": "ASC"}]),
    ({"property": "projects", "direction": "ASC"}, [{"property": "file.name", "direction": "ASC"}]),
    ({"property": "contexts", "direction": "ASC"}, [{"property": "file.name", "direction": "ASC"}]),
    ({"property": "file.folder", "direction": "ASC"}, [{"property": "file.name", "direction": "ASC"}]),
]


def grouped(rel, names):
    """Obsidian's groups for each named view of a .base file, in display
    order: {view: [[key, [paths]]]}. base:query flattens groups, so this opens
    the file in a tab and reads each view's groupedData (polled, as the CLI
    drops slow replies)."""
    obs_eval('(()=>{window.__omfg=null;const sleep=t=>new Promise(r=>setTimeout(r,t));(async()=>{'
             'const leaf=app.workspace.getLeaf("tab");await leaf.openFile(app.vault.getFileByPath(%s));const out={};'
             'for(const n of %s){leaf.view.controller.selectView(n);await sleep(1200);'
             'const d=leaf.view.controller.view.data;out[n]=d.groupedData.map(g=>[g.hasKey()?String(g.key):"",g.entries.map(e=>e.file.path)])}'
             'leaf.detach();window.__omfg=out})().catch(e=>{window.__omfg={err:String(e)}});return "kicked"})()'
             % (json.dumps(rel), json.dumps(names)))
    for _ in range(len(names) * 4 + 30):
        time.sleep(0.5)
        out = obs_eval("JSON.stringify(window.__omfg)")
        if out and out != "null":
            res = json.loads(out)
            if "err" in res:
                raise RuntimeError("groupedData %s: %s" % (rel, res["err"]))
            return res
    raise RuntimeError("groupedData %s timed out" % rel)


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


def query(rel, view, fmt="paths"):
    """Run Obsidian's base:query handler in-app and poll for the result: the
    CLI drops replies that take longer than about a second, and a query over
    a 4,000-note vault takes longer than that."""
    key = json.dumps([rel, view, fmt])
    obs_eval('(()=>{window.__omfq=window.__omfq||{};const k=%s;window.__omfq[k]=null;'
             'app.cli.handlers.get("base:query").handler({path:%s,view:%s,format:%s})'
             '.then(r=>{window.__omfq[k]={ok:String(r)}}).catch(e=>{window.__omfq[k]={err:String(e)}});return "kicked"})()'
             % (json.dumps(key), json.dumps(rel), json.dumps(view), json.dumps(fmt)))
    for _ in range(60):
        time.sleep(0.5)
        out = obs_eval("JSON.stringify(window.__omfq[%s])" % json.dumps(key))
        if out and out != "null":
            res = json.loads(out)
            if "err" in res:
                raise RuntimeError("base:query %s: %s" % (view, res["err"]))
            if fmt == "json":     # rows in the view's display order
                return json.loads(res["ok"])
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
        # Distinct modification times (a minute apart) so file.mtime sorts
        # aren't decided by writes that landed within the same millisecond.
        t0 = time.time() - 3600
        for i, rel in enumerate(seeded):
            os.utime(os.path.join(VAULT, rel), (t0 + 60 * i, t0 + 60 * i))
        for rel in seeded:
            wait_indexed(rel)
        v = Vault(VAULT)
        v.scan()
        s = v.settings
        task_map = {t["path"]: t for t in tasks.all_tasks(v, tasks.today()) if not t["error"]}

        cases = []  # (label, top_filters, formulas, view_filters, compiled filter, raw sort, compiled sort)
        copies = []  # (copy label, original label)
        groupby = {}  # label -> (raw groupBy, compiled group)
        for d in bases.all_views(v):
            if d.get("unsupported") or d["file"].startswith(PROBE_DIR):
                continue
            with open(os.path.join(VAULT, d["file"])) as f:
                raw = bases.load_base(f.read())
            rv = next(x for x in raw["views"] if str(x.get("name")) == d["name"])
            cases.append(("view %s › %s" % (d["fileName"], d["name"]), raw.get("filters"), raw.get("formulas"),
                          rv.get("filters"), d["filter"], rv.get("sort"), d.get("sort")))
            if rv.get("groupBy") and d.get("group"):
                groupby[cases[-1][0]] = (rv["groupBy"], d["group"])
            # "Duplicate as editable view" must give Obsidian the same view.
            if not d.get("model"):
                m, _notes = bases.closest_model(v, d["file"], d["name"])
                cd = bases.base_dict(m, s)
                cview = cd["views"][0]
                cdesc = bases.views_in(v, "copy.base", "\n".join(bases.dump(cd)))[0]
                copies.append(("copy %s › %s" % (d["fileName"], d["name"]), "view %s › %s" % (d["fileName"], d["name"])))
                cases.append((copies[-1][0], cd.get("filters"), cd.get("formulas"), cview.get("filters"),
                              cdesc["filter"], cview.get("sort"), cdesc.get("sort")))
                if cview.get("groupBy") and cdesc.get("group"):
                    groupby[cases[-1][0]] = (cview["groupBy"], cdesc["group"])
        comp = bases.Compiler({})
        top = {"and": ['file.hasTag("todo")']}
        for e in EXPRESSIONS:
            cases.append(("expr " + e, top, None, {"and": [e]}, ["and", [comp.compile(top["and"][0]), comp.compile(e)]], None, None))
        for c in editor_conditions(s):
            e = bases.condition_expr(c, s)
            cases.append(("editor %s %s %s" % (c["field"], c["op"], c.get("value", "")), top, None, {"and": [e]},
                          ["and", [comp.compile(top["and"][0]), comp.compile(e)]], None, None))
        for gb, srt in GROUPS:
            label = "group %s %s, sort %s" % (gb["property"], gb["direction"].lower(), srt[0]["property"])
            cases.append((label, top, None, None, comp.compile(top["and"][0]), srt, [bases.sort_ast(x, comp) for x in srt]))
            groupby[label] = (gb, bases.sort_ast(gb, comp))
        for srt in SORTS:
            cases.append(("sort " + ", ".join("%s %s" % (x["property"], x["direction"].lower()) for x in srt), top, None, None,
                          comp.compile(top["and"][0]), srt, [bases.sort_ast(x, comp) for x in srt]))

        # Obsidian's answers: one throwaway base per distinct (filters, formulas)
        # header, every case a table view in it; written once, indexed, queried.
        expected, order, values, ogroups, ui_order = {}, {}, {}, {}, {}
        groups = {}
        for i, (label, tf, fm, vf, _ast, srt, _sast) in enumerate(cases):
            key = json.dumps([tf, fm], sort_keys=True)
            groups.setdefault(key, (tf, fm, []))[2].append((i, label, vf, srt))
        for gi, (tf, fm, items) in enumerate(groups.values()):
            d = {}
            if tf:
                d["filters"] = tf
            if fm:
                d["formulas"] = fm
            d["views"] = []
            for i, label, vf, srt in items:
                view = {"type": "table", "name": "P%d" % i}
                if vf:
                    view["filters"] = vf
                if label in groupby:
                    view["groupBy"] = groupby[label][0]
                if srt:
                    # Obsidian only sorts by a property that's also a shown
                    # column, and its JSON carries only shown columns.
                    props = [x.get("property") or x.get("column") for x in srt]
                    if label in groupby:
                        props.append(groupby[label][0].get("property"))
                    view["order"] = ["file.name"] + [x for x in dict.fromkeys(props) if x and x != "file.name"]
                    view["sort"] = srt
                d["views"].append(view)
            probe = "%s/probe%d.base" % (PROBE_DIR, gi)
            with open(os.path.join(VAULT, probe), "w") as f:
                f.write("\n".join(bases.dump(d)) + "\n")
            wait_indexed(probe)
            time.sleep(1)
            # Order comes from the rendered view (groupedData), not base:query:
            # the two differ (base:query applies sorts on properties no note
            # has, so its ties come out in path order; the view lists by name).
            gnames = [("P%d" % i, label) for i, label, _vf, srt in items if srt or label in groupby]
            if gnames:
                got_groups = grouped(probe, [n for n, _ in gnames])
                for n, label in gnames:
                    ogroups[label] = [[k, [p for p in ps if p in task_map]] for k, ps in got_groups[n]]
                    ogroups[label] = [g for g in ogroups[label] if g[1]]
                    ui_order[label] = [p for g in ogroups[label] for p in g[1]]
            for i, label, vf, srt in items:
                if srt:
                    rows = [row for row in query(probe, "P%d" % i, "json") if row["path"] in task_map]
                    order[label] = ui_order[label]
                    # JSON keys drop the "file."/"formula."/"note." prefix
                    values[label] = {row["path"]: [row.get((x.get("property") or x.get("column")).split(".")[-1]) for x in srt]
                                     for row in rows}
                    expected[label] = sorted(order[label])
                else:
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

        # Order: the app's own sort (views.js computeBase) on the notes Obsidian
        # agreed belong in the view.
        sorted_cases = [c for c in cases if c[5]]
        payload = {"views": [{"id": c[0], "filter": c[4], "sort": c[6], "group": groupby.get(c[0], (None, None))[1]}
                             for c in sorted_cases], "tasks": task_map,
                   "settings": s.public(), "today": T.isoformat(), "now": int(time.time() * 1000)}
        mine = json.loads(subprocess.run(["node", os.path.join(HERE, "bases-order.mjs")], input=json.dumps(payload),
                                         capture_output=True, text=True, check=True).stdout)
        ofails = 0
        for label, *_ in [c for c in sorted_cases if c[0] not in groupby]:
            want = order[label]
            have = [p for p in mine[label] if p in set(want)]
            ok = have == want
            ofails += not ok
            msg = ""
            if not ok:
                at = next(i for i, (a, b) in enumerate(zip(want, have)) if a != b)
                nm = lambda xs: ["%s %s" % (os.path.basename(x)[:-3][:24], values[label][x]) for x in xs]  # noqa: E731
                msg = "\n      first difference at row %d of %d\n      obsidian: %s\n      omaforge: %s" % (
                    at, len(want), nm(want[max(0, at - 1):at + 4]), nm(have[max(0, at - 1):at + 4]))
            print("order %-56s %s%s" % (label[:56], "PASS" if ok else "FAIL", msg))
        nflat = len([c for c in sorted_cases if c[0] not in groupby])
        print("\n%d/%d sorted views in Obsidian's order" % (nflat - ofails, nflat))

        # Groups: same groups in the same order, each with the same tasks in
        # the same order. Compared by membership (labels are formatted
        # differently: Obsidian's key vs OmaForge's display label).
        gfails = 0
        for label in [c[0] for c in sorted_cases if c[0] in groupby]:
            want, have = ogroups[label], mine[label + "#groups"]
            ok = [g[1] for g in want] == [[p for p in g[1] if p in set(order[label])] for g in have if any(p in set(order[label]) for p in g[1])]
            gfails += not ok
            msg = ""
            if not ok:
                nm = lambda ps: [os.path.basename(p)[:-3][:18] for p in ps[:6]]  # noqa: E731
                msg = "\n      obsidian: %s\n      omaforge: %s" % (
                    [(k, len(ps)) for k, ps in want], [(k, len(ps)) for k, ps in have])
                for (wk, wp), (hk, hp) in zip(want, have):
                    if wp != [p for p in hp if p in set(order[label])]:
                        msg += "\n      first differing group %r / %r:\n        obsidian: %s\n        omaforge: %s" % (wk, hk, nm(wp), nm(hp))
                        break
            print("groups %-55s %s%s" % (label[:55], "PASS" if ok else "FAIL", msg))
        ngroups = len([c for c in sorted_cases if c[0] in groupby])
        print("\n%d/%d grouped views in Obsidian's group order" % (ngroups - gfails, ngroups))

        # Copies made by "Duplicate as editable view" vs their originals, both
        # as Obsidian sees them.
        cfails = 0
        for copy, orig in copies:
            ok = expected[copy] == expected[orig] and order.get(copy) == order.get(orig)
            cfails += not ok
            print("same as original: %-45s %s" % (copy[5:50], "PASS" if ok else "FAIL"))
        print("\n%d/%d copies identical in Obsidian" % (len(copies) - cfails, len(copies)))
        return fails + ofails + cfails + gfails
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
