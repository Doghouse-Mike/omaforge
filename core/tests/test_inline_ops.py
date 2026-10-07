"""Tasks-mode operations on a synthetic vault."""
import json
import os
from datetime import date

from omaforge import inline, vault as vault_mod
from omaforge.vault import VaultError

from .test_tasks import VaultCase

NOTE = "Projects/Garden.md"
TEXT = """# Garden

- [ ] Plant bulbs 📅 2026-11-01
- [ ] Mow 🔁 every week on Saturday 📅 2026-10-10
- [x] Buy compost ✅ 2026-10-01
Some notes.
"""


class TasksCase(VaultCase):
    def setUp(self):
        super().setUp()
        cfg = json.load(open(self.cfg))
        cfg["taskFormat"] = "tasks"
        cfg["tasksInbox"] = {"target": "note", "note": "Inbox.md"}
        json.dump(cfg, open(self.cfg, "w"))
        os.makedirs(os.path.join(self.dir, ".obsidian/plugins/obsidian-tasks-plugin"))
        json.dump({"setCreatedDate": False, "statusSettings": {"customStatuses": [
            {"symbol": "/", "name": "In Progress", "nextStatusSymbol": "x", "type": "IN_PROGRESS"}]}},
            open(os.path.join(self.dir, ".obsidian/plugins/obsidian-tasks-plugin/data.json"), "w"))
        self.put(NOTE, TEXT)
        self.v = vault_mod.Vault(self.dir)
        self.v.scan()

    def tasks(self):
        self.v.scan()
        return {t["title"]: t for t in inline.all_tasks(self.v, date.today().isoformat())}

    def op(self, name, **req):
        return inline.OPS[name](self.v, req, date.today().isoformat())


class Ops(TasksCase):
    def test_mode_and_reading(self):
        self.assertEqual(self.v.mode, "tasks")
        t = self.tasks()
        self.assertEqual(set(t), {"Plant bulbs", "Mow", "Buy compost"})
        self.assertEqual(t["Plant bulbs"]["notes"], ["Garden"])
        self.assertTrue(t["Buy compost"]["done"])

    def test_complete_repeat_inserts_next_line_above(self):
        t = self.tasks()["Mow"]
        r = self.op("toggleComplete", path=t["path"], expect=t["expect"])
        lines = self.get(NOTE).split("\n")
        self.assertEqual(lines[3], "- [ ] Mow 🔁 every week on Saturday 📅 2026-10-17")
        self.assertTrue(lines[4].startswith("- [x] Mow 🔁 every week on Saturday 📅 2026-10-10 ✅ "))
        self.assertEqual(r["task"]["line"], 4)            # the UI keeps following the completed one

    def test_edit_fields_rewrites_only_that_line(self):
        t = self.tasks()["Plant bulbs"]
        self.op("update", path=t["path"], expect=t["expect"],
                set={"priority": "high", "scheduled": "2026-10-30", "title": "Plant tulip bulbs", "tags": ["garden"]})
        lines = self.get(NOTE).split("\n")
        self.assertEqual(lines[2], "- [ ] Plant tulip bulbs #garden ⏫ ⏳ 2026-10-30 📅 2026-11-01")
        self.assertEqual(lines[:2] + lines[3:], TEXT.split("\n")[:2] + TEXT.split("\n")[3:])

    def test_repeat_from_editor_rrule(self):
        t = self.tasks()["Plant bulbs"]
        self.op("update", path=t["path"], expect=t["expect"], set={"recurrence": "FREQ=WEEKLY;INTERVAL=2;BYDAY=FR"})
        self.assertIn("🔁 every 2 weeks on Friday 📅 2026-11-01", self.get(NOTE))
        t = self.tasks()["Plant bulbs"]
        self.op("update", path=t["path"], expect=t["expect"], set={"whenDone": True})
        self.assertIn("🔁 every 2 weeks on Friday when done", self.get(NOTE))

    def test_stale_line_is_a_conflict(self):
        t = self.tasks()["Plant bulbs"]
        self.put(NOTE, TEXT.replace("Plant bulbs", "Plant bulbs today"))
        with self.assertRaises(VaultError) as cm:
            self.op("toggleComplete", path=t["path"], expect=t["expect"])
        self.assertEqual(cm.exception.code, "conflict")

    def test_moved_line_is_followed(self):
        t = self.tasks()["Plant bulbs"]
        self.put(NOTE, "New first line\n" + TEXT)
        self.op("toggleComplete", path=t["path"], expect=t["expect"])
        self.assertIn("- [x] Plant bulbs 📅 2026-11-01 ✅ ", self.get(NOTE))

    def test_dependency_gets_an_id(self):
        t = self.tasks()
        self.op("update", path=t["Mow"]["path"], expect=t["Mow"]["expect"],
                set={"blockedBy": [{"path": t["Plant bulbs"]["path"]}]})
        text = self.get(NOTE)
        bulb_id = inline.parse_line(text.split("\n")[2], self.v.tasks_settings)["id"]
        self.assertRegex(bulb_id, r"^[a-z0-9]{6}$")
        self.assertIn("⛔ %s" % bulb_id, text)
        self.assertTrue(self.tasks()["Mow"]["blocked"])

    def test_create_delete_duplicate(self):
        r = self.op("create", fields={"title": "Ring the vet", "due": "2026-10-20"})
        self.assertEqual(self.get("Inbox.md"), "- [ ] Ring the vet 📅 2026-10-20\n")
        self.op("create", fields={"title": "Second", "file": NOTE})
        self.assertTrue(self.get(NOTE).rstrip("\n").endswith("- [ ] Second"))
        t = self.tasks()["Plant bulbs"]
        self.op("duplicate", path=t["path"], expect=t["expect"])
        self.assertEqual(self.get(NOTE).count("- [ ] Plant bulbs 📅 2026-11-01"), 2)
        t = self.tasks()["Buy compost"]
        self.op("delete", path=t["path"], expect=t["expect"])
        self.assertNotIn("Buy compost", self.get(NOTE))

    def test_status_change_and_cancel(self):
        t = self.tasks()["Plant bulbs"]
        self.op("setStatus", path=t["path"], expect=t["expect"], status="/")
        self.assertIn("- [/] Plant bulbs", self.get(NOTE))
