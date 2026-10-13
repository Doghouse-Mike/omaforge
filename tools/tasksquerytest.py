#!/usr/bin/env python3
"""OmaForge's ```tasks query evaluator (app/tasksquery.js) vs the Tasks plugin.

Needs a disposable vault open in Obsidian with the Tasks plugin enabled
(OMAFORGE_TEST_VAULT, as for tools/taskstest.py). Seeds a note of varied
tasks dated relative to today, renders a probe ```tasks block (to get a live
query renderer), then runs every query in QUERIES through Tasks' own
pipeline (global query, file defaults, placeholders included) and through
OmaForge's evaluator, comparing errors, groups (names and order) and the
tasks in each group, in order. Cleans up after itself.

Tasks are handed to Tasks in file-then-line order. Its own cache order is
history-dependent (it can list a file's tasks out of line order), and that
order decides tasks that tie on every sort key including path; OmaForge uses
line order for those.
"""
import json
import os
import subprocess
import sys
import time
from datetime import date, timedelta

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "core"))

import difftest as D  # noqa: E402  (test-vault guard, Obsidian eval helpers)
from omaforge import inline  # noqa: E402
from omaforge.vault import Vault  # noqa: E402

PROBE_DIR = "zz-omaforge-oracle"
T = date.today()
d = lambda n: (T + timedelta(days=n)).isoformat()  # noqa: E731

SEED = """# Query seeds

## Home
- [ ] Book the boiler service ⏫ 📅 {d0}
- [ ] Bins out 🔁 every week 📅 {d1}
- [/] Sort the loft #declutter ⏳ {d0}
- [ ] Renew car insurance 🔺 📅 {dm1}
    - [ ] Get three quotes #errands 📅 {dm1}
    - Plain bullet
        - [ ] Deep child 🔽
- [x] Mow the lawn ✅ {dm2} 📅 {dm3}
- [-] Paint the fence ❌ {dm1}
- [ ] Starts later 🛫 {d5} 📅 {d9}
- [ ] Started already 🛫 {dm4} ⏳ {d2}
- [ ] Undated #home/garden ⏬
- [ ] Created only ➕ {dm10}

## Work / Projects
- [ ] Draft the Q4 plan 🆔 q4plan 📅 {d5} #work
- [ ] Share the Q4 plan ⛔ q4plan 📅 {d6} #work
- [ ] Far future 📅 {d40} #work
- [ ] Long overdue 📅 {dm20} 🔼
- [x] Done long ago ✅ {dm30}
- [ ] the article starts with the 📅 {d3}
- [ ] UPPER case task 📅 {d3}
1. [ ] Numbered item 📅 {d14}
> - [ ] Quoted task ⏳ {d1}
""".format(d0=d(0), d1=d(1), d2=d(2), d3=d(3), d5=d(5), d6=d(6), d9=d(9), d14=d(14), d40=d(40),
           dm1=d(-1), dm2=d(-2), dm3=d(-3), dm4=d(-4), dm10=d(-10), dm20=d(-20), dm30=d(-30))

# Restrict every query to the seeds (plus whatever the query adds), so the
# answers are about known tasks; the global-scope queries come at the end.
SCOPE = "path includes %s/seed" % PROBE_DIR

# Each is a whole query, run after SCOPE; a leading "!" runs it unscoped.
QUERIES = [
    # status
    "not done", "done", "status.type is IN_PROGRESS", "status.type is not TODO", "status.name includes progress",
    "status.type is frobbed",
    # dates: keywords, ranges, phrases
    "due today", "due on today", "due before today", "due after today", "due on or before today",
    "due on or after tomorrow", "due in next week", "due this week", "due next week", "due last week",
    "due this month", "due next month", "due this quarter", "due this year", "due before tomorrow",
    "due %s" % d(1), "due %s %s" % (d(-3), d(3)), "due in %s" % T.strftime("%Y-%m"), "due %s" % T.strftime("%Y"),
    "due %s" % T.strftime("%G-W%V"), "due in 3 days", "due 2 days ago", "due yesterday", "due tomorrow",
    "due monday", "due friday", "due next friday", "due last monday",
    "scheduled before tomorrow", "scheduled after yesterday", "starts before today", "starts after today",
    "starts on or before today", "(has start date) AND (starts before today)", "created before today",
    "done after %s" % d(-5), "done before today", "cancelled on %s" % d(-1), "happens before today",
    "happens on or after %s" % d(2), "happens next week", "has due date", "no due date", "has start date",
    "no scheduled date", "has happens date", "no happens date", "due date is invalid",
    "due someday", "due YYYY-MM-DD",
    # priority, recurrence, tags, text
    "priority is high", "priority is above medium", "priority is below none", "priority is not none",
    "priority is normal", "priority above low", "is recurring", "is not recurring", "recurrence includes week",
    "tags include #declutter", "tags do not include #work", "tag includes home", "tags include #home/garden",
    "has tags", "no tags", "tags regex matches /^#w/",
    "description includes the", "description does not include plan", "description regex matches /^[A-Z]/",
    "description regex matches /plan$/i", "description regex matches nope", "path includes seed",
    "filename includes seed", "folder includes oracle", "root includes zz", "heading includes Work",
    "heading includes home", "id includes q4", "has id", "no id",
    # dependencies, structure
    "is blocked", "is not blocked", "is blocking", "is not blocking", "has depends on", "no depends on",
    "exclude sub-items",
    # boolean
    "(due today) OR (due tomorrow)", "(not done) AND (priority is high)", "NOT (done)",
    "(due before today) AND NOT (done)", "(has due date) XOR (has scheduled date)",
    "((due today) OR (priority is highest)) AND (not done)", "[description includes (x)] OR [done]",
    "(due today) AND [done]", "(due today) and (done)", "(frobnicate) OR (done)",
    # sorting
    "sort by due", "sort by due reverse", "sort by priority", "sort by urgency", "sort by description",
    "sort by status", "sort by status.type", "sort by happens", "sort by start", "sort by created reverse",
    "sort by path", "sort by filename", "sort by heading", "sort by id", "sort by tag", "sort by tag 2",
    "sort by recurring", "sort by duex", "sort by function task.due",
    # grouping
    "group by due", "group by priority", "group by status", "group by status.type", "group by status.name",
    "group by tags", "group by heading", "group by filename", "group by folder", "group by path", "group by root",
    "group by backlink", "group by happens", "group by recurring", "group by recurrence", "group by urgency",
    "group by urgency reverse", "group by start", "group by scheduled reverse", "group by id",
    "group by priority\ngroup by heading", "group by tags reverse", "group by description",
    # limits and layout
    "limit 3", "limit to 2 tasks", "sort by due\nlimit 4", "group by heading\nlimit groups 2",
    "limit 0", "hide due date\nshort mode\nexplain", "show tree", "hide frobs", "view list",
    # the columns view
    "view columns by priority", "view columns by priority reverse", "view columns by due",
    "view columns by status.type\ngroup by heading", "view columns by tags\nlimit groups 2",
    "view columns by urgency", "view columns by happens\nsort by description",
    "group by heading\nview columns by priority", "view columns by priority\nview list",
    "view columns by", "view columns by frobs", "view columns", "view sideways", "view list please",
    "view columns by description",
    # continuation, comments, presets, placeholders
    "not done \\\n  AND (due today)", "# a comment\nnot done", "(not done) AND \\\n  (due today)",
    "path includes {{query.file.folder}}", "preset this_folder", "preset nonesuch",
    "filter by function task.isDone", "frobnicate",
    # the whole vault (hundreds of real tasks)
    "!not done", "!done\nsort by done reverse\nlimit 40", "!group by folder\ngroup by filename",
    "!group by tags\nlimit groups 3", "!(done) AND (description includes the)\ngroup by root",
    "!sort by description\nlimit 60", "!group by status.name\ngroup by priority", "!exclude sub-items\nnot done",
]

RUN_JS = r"""(()=>{window.__omtq=null;setTimeout(()=>{try{
const R=window.__omtqLeaf.view.previewMode._children.find(k=>k.queryResultsRenderer).queryResultsRenderer;
const all=app.plugins.plugins["obsidian-tasks-plugin"].getTasks().slice().sort((a,b)=>{const p=a.taskLocation.path,q=b.taskLocation.path;return p<q?-1:p>q?1:a.taskLocation.lineNumber-b.taskLocation.lineNumber});
const run=src=>{const keep=R.source;R.source=src;try{const q=R.makeQueryFromSourceAndTasksFile();
 if(q.error)return {error:q.error};const res=q.applyQueryToTasks(all.slice());  /* it sorts in place */
 return {total:res.totalTasksCountBeforeLimit,groups:res.taskGroups.groups.map(g=>({names:g.groups,
 tasks:g.tasks.map(t=>t.taskLocation.path+"::L"+t.taskLocation.lineNumber)}))}}
 catch(e){return {error:"EXCEPTION "+e}}finally{R.source=keep}};
window.__omtq=JSON.stringify(%s.map(run))}catch(e){window.__omtq=JSON.stringify({err:String(e.stack)})}},0);return "kicked"})()"""


def obs(js):
    """A quick synchronous eval in Obsidian (slow work is kicked and polled)."""
    return D._eval(js)


def oracle(sources):
    obs(RUN_JS % json.dumps(sources))
    for _ in range(120):
        time.sleep(0.5)
        out = obs("window.__omtq")
        if out and out not in ("null", "undefined"):
            res = json.loads(out)
            if isinstance(res, dict) and "err" in res:
                raise RuntimeError(res["err"])
            return res
    raise RuntimeError("Tasks query oracle timed out")


def wait_for(js_true, what, timeout=30):
    for _ in range(timeout * 2):
        if obs(js_true) == "yes":
            return
        time.sleep(0.5)
    raise RuntimeError("timed out waiting for " + what)


def main():
    D.require_test_vault()
    vault_path = D.VAULT
    pdir = os.path.join(vault_path, PROBE_DIR)
    os.makedirs(pdir, exist_ok=True)
    try:
        with open(os.path.join(pdir, "seed.md"), "w") as f:
            f.write(SEED)
        with open(os.path.join(pdir, "q.md"), "w") as f:
            f.write("```tasks\nnot done\nlimit 1\n```\n")
        wait_for('app.plugins.plugins["obsidian-tasks-plugin"].getTasks().some(t=>t.taskLocation.path==%s)?"yes":"no"'
                 % json.dumps(PROBE_DIR + "/seed.md"), "Tasks to index the seeds")
        obs('(async()=>{const leaf=app.workspace.getLeaf("tab");window.__omtqLeaf=leaf;'
            'await leaf.openFile(app.vault.getFileByPath(%s),{state:{mode:"preview"}})})(),"k"' % json.dumps(PROBE_DIR + "/q.md"))
        wait_for('window.__omtqLeaf&&window.__omtqLeaf.view.previewMode&&window.__omtqLeaf.view.previewMode._children'
                 '.some(k=>k.queryResultsRenderer)?"yes":"no"', "the probe query to render")

        sources = [SCOPE + "\n" + q if not q.startswith("!") else q[1:] for q in QUERIES]
        want = oracle(sources)

        v = Vault(vault_path)
        v.mode = "tasks"
        v.tasks_settings = inline.TasksSettings(v.path)
        v.entries.clear()
        v.scan()
        tasks = inline.all_tasks(v, T.isoformat())
        payload = {"queries": [{"id": str(i), "source": s, "file": PROBE_DIR + "/q.md"} for i, s in enumerate(sources)],
                   "tasks": tasks, "settings": inline.settings_public(v), "tasksSettings": v.tasks_settings.raw,
                   "today": T.isoformat()}
        got = json.loads(subprocess.run(["node", os.path.join(HERE, "tasksquery-eval.mjs")], input=json.dumps(payload),
                                        capture_output=True, text=True, check=True).stdout)
        fails = skipped = 0
        for i, q in enumerate(QUERIES):
            w, g = want[i], got[str(i)]
            label = q.replace("\n", " ⏎ ")
            if "unsupported" in g:
                # OmaForge declines rather than guessing: shown dimmed in the app.
                skipped += 1
                print("%-70s SKIP (%s)" % (label[:70], g["unsupported"]))
                continue
            if "error" in w or "error" in g:
                ok = ("error" in w) == ("error" in g)
            else:
                ok = w["total"] == g["total"] and w["groups"] == g["groups"]
            fails += not ok
            print("%-70s %s" % (label[:70], "PASS" if ok else "FAIL"))
            if not ok:
                if "groups" in w and "groups" in g and len(w["groups"]) == len(g["groups"]) and w["total"] == g["total"]:
                    for wg, gg in zip(w["groups"], g["groups"]):
                        if wg != gg:
                            at = next((k for k, (x, y) in enumerate(zip(wg["tasks"], gg["tasks"])) if x != y), 0)
                            print("      group %s, first difference at %d:" % (wg["names"], at))
                            print("        tasks:    %s" % wg["tasks"][max(0, at - 1):at + 4])
                            print("        omaforge: %s" % gg["tasks"][max(0, at - 1):at + 4])
                            break
                else:
                    print("      tasks:    %s" % json.dumps(w)[:600])
                    print("      omaforge: %s" % json.dumps(g)[:600])
        print("\n%d/%d queries match Tasks (%d unsupported, shown dimmed)" % (len(QUERIES) - fails - skipped, len(QUERIES) - skipped, skipped))
        return fails
    finally:
        try:
            obs("(window.__omtqLeaf&&window.__omtqLeaf.detach(),'ok')")
        except Exception:
            pass
        for f in ("seed.md", "q.md"):
            try:
                os.unlink(os.path.join(pdir, f))
            except OSError:
                pass
        try:
            os.rmdir(pdir)
        except OSError:
            pass


if __name__ == "__main__":
    sys.exit(1 if main() else 0)
