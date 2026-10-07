#!/usr/bin/env python3
"""OmaForge's Obsidian Tasks support vs the Tasks plugin itself.

Needs a disposable vault open in Obsidian with the Tasks plugin enabled
(OMAFORGE_TEST_VAULT, as for tools/difftest.py). Three checks:

1. reading   every task in the vault, parsed by OmaForge, against Tasks'
             own parsed list (getTasks()), field by field
2. writing   for each sample line, Tasks' canonical form (ticked twice via
             its API, which re-serialises the line) must equal OmaForge's
             serialise(parse(line))
3. ticking   for each sample line, Tasks' executeToggleTaskDoneCommand()
             output must equal OmaForge's toggle_lines() for the same day
"""
import json
import os
import sys
from datetime import date

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "core"))

import difftest as D  # noqa: E402  (test-vault guard, Obsidian eval helpers)
from omaforge import inline  # noqa: E402
from omaforge.vault import Vault  # noqa: E402

TODAY = date.today().isoformat()

SAMPLES = [
    "- [ ] Plain task",
    "- [ ] Pay rent 📅 2026-11-01",
    "- [ ] Mixed order 📅 2026-11-01 ⏫ ⏳ 2026-10-30 🛫 2026-10-28",
    "- [ ] Tags kept #home #errands 🔼 📅 2026-11-02",
    "- [x] Done already 📅 2026-10-01 ✅ 2026-10-02",
    "- [/] In progress 📅 2026-11-03",
    "- [-] Cancelled thing ❌ 2026-10-03",
    "  - [ ] Indented subtask ⏬",
    "* [ ] Star bullet 🔽 ➕ 2026-10-01",
    "1. [ ] Numbered item 🔺",
    "> - [ ] In a quote 📅 2026-11-04",
    "- [ ] Weekly bins 🔁 every week on Monday 📅 2026-10-12",
    "- [ ] Every 2 weeks 🔁 every 2 weeks on Friday ⏳ 2026-10-09 📅 2026-10-10",
    "- [ ] Monthly rent 🔁 every month on the 1st 📅 2026-11-01",
    "- [ ] When done 🔁 every 3 days when done 📅 2026-10-05",
    "- [ ] Start and due 🔁 every week 🛫 2026-10-01 ⏳ 2026-10-03 📅 2026-10-05",
    "- [ ] Yearly 🔁 every year on January 1st 📅 2027-01-01",
    "- [ ] Has id 🆔 abc123 📅 2026-11-05",
    "- [ ] Depends ⛔ abc123 📅 2026-11-06",
    "- [ ] Delete when done 🏁 delete 📅 2026-11-07",
    "- [ ] Block link 📅 2026-11-08 ^my-block",
    "- [ ] Dataview style [due:: 2026-11-09] [priority:: high]",
    "- [ ] Trailing text after date 📅 2026-11-10 then more words",
    # normalisation on rewrite
    "- [ ] Alt emoji ⌛ 2026-11-11 📆 2026-11-12",
    "- [ ]   Extra   spaces  📅 2026-11-13",
    "- [ ] Tag between fields 📅 2026-11-14 #later ⏫",
    "- [ ] Duplicate field 📅 2026-11-15 📅 2026-11-16",
    "- [ ] Shorthand rule 🔁 every mon 📅 2026-10-12",
    "- [ ] Unreadable rule 🔁 daily 📅 2026-10-12",
    "- [ ] Month end clamp 🔁 every month 📅 2026-01-31",
    "- [ ] Pinned day skips 🔁 every month on the 31st 📅 2026-01-31",
    "- [ ] Leap clamp 🔁 every year 📅 2028-02-29",
    "- [ ] Last friday 🔁 every month on the last Friday 📅 2026-10-30",
    "- [ ] No dates repeat 🔁 every week",
    "- [ ] Scheduled only 🔁 every 3 days ⏳ 2026-10-05",
    "- [X] Uppercase X 📅 2026-11-17",
    "- [/] Recurring in progress 🔁 every day 📅 2026-10-07",
]


def obs(js):
    return D.obs(js)


def check_reading(vault):
    got = {t["path"]: t for t in inline.all_tasks(vault, TODAY)}
    raw = obs('return JSON.stringify(app.plugins.plugins["obsidian-tasks-plugin"].getTasks().map(t=>({'
              'k:t.taskLocation.path+"::L"+t.taskLocation.lineNumber, d:t.description, s:t.status.symbol, p:t.priority,'
              'due:t.dueDate?t.dueDate.format("YYYY-MM-DD"):"", sch:t.scheduledDate&&!t.scheduledDateIsInferred?t.scheduledDate.format("YYYY-MM-DD"):"",'
              'st:t.startDate?t.startDate.format("YYYY-MM-DD"):"", done:t.doneDate?t.doneDate.format("YYYY-MM-DD"):"",'
              'rec:t.recurrence?t.recurrence.toText():"", tags:t.tags, id:t.id||"", dep:t.dependsOn||[]})))')
    oracle = {o["k"]: o for o in json.loads(raw)}
    fails = 0
    missing = sorted(set(oracle) - set(got))
    extra = sorted(set(got) - set(oracle))
    for k in missing[:5] + extra[:5]:
        print("   %s %s" % ("missing" if k in oracle else "extra  ", k))
    fails += len(missing) + len(extra)
    for k in sorted(set(oracle) & set(got)):
        o, t = oracle[k], got[k]
        mine = {"d": t["description"], "s": t["status"], "p": PRIO_NUM.get(t["priority"]), "due": t["due"],
                "sch": t["scheduled"], "st": t["start"], "done": t["completedDate"], "rec": t["recurrence"],
                "tags": t["allTags"], "id": t["taskId"], "dep": t["dependsOn"]}
        theirs = {kk: o[kk] for kk in mine}
        if mine != theirs:
            fails += 1
            if fails <= 8:
                print("   DIFF", k)
                for kk in mine:
                    if mine[kk] != theirs[kk]:
                        print("      %-5s tasks=%r ours=%r" % (kk, theirs[kk], mine[kk]))
    print("reading: %d tasks, %d differences" % (len(oracle), fails))
    return fails


PRIO_NUM = {"highest": "0", "high": "1", "medium": "2", "none": "3", "low": "4", "lowest": "5"}


def toggle(line, path="omaforge-test.md"):
    out = obs('return JSON.stringify(app.plugins.plugins["obsidian-tasks-plugin"].apiV1'
              '.executeToggleTaskDoneCommand(%s, %s))' % (json.dumps(line), json.dumps(path)))
    return json.loads(out).split("\n")


def check_samples(ts):
    fails = 0
    for line in SAMPLES:
        once = toggle(line)
        # Toggle again to get Tasks' re-serialised form of the original
        # (non-recurring only: a recurring toggle adds a new line).
        ours_toggle = inline.toggle_lines(line, ts, date.today().isoformat())
        if "\n".join(ours_toggle) != "\n".join(once):     # a deleted line comes back as 
            fails += 1
            print("   TOGGLE %s\n      tasks: %s\n      ours:  %s" % (line, once, ours_toggle))
        # Ticking twice returns an open task to open, re-serialised: Tasks'
        # canonical form of the line. (Other statuses walk their own cycle.)
        p0 = inline.parse_line(line, ts)
        if p0 and ts.status(p0["status"])["type"] == "TODO" and not p0["onCompletion"] and len(once) == 1:
            twice = toggle(once[0])
            if len(twice) == 1 and inline.parse_line(twice[0], ts)["status"] == p0["status"]:
                canon = twice[0]
                p = inline.parse_line(line, ts)
                mine = inline.serialize(p, ts) if p else None
                if mine != canon:
                    fails += 1
                    print("   WRITE  %s\n      tasks: %s\n      ours:  %s" % (line, canon, mine))
    print("writing + ticking: %d samples, %d differences" % (len(SAMPLES), fails))
    return fails


def main():
    D.require_test_vault()
    vault = Vault(D.VAULT)
    if vault.mode != "tasks":
        vault.mode = "tasks"
        vault.tasks_settings = inline.TasksSettings(vault.path)
        vault.entries.clear()
    vault.scan()
    fails = check_reading(vault) + check_samples(vault.tasks_settings)
    print("\n%s" % ("all match Tasks" if not fails else "%d differences" % fails))
    return fails


if __name__ == "__main__":
    sys.exit(1 if main() else 0)
