"""Core operations against a throwaway synthetic vault (never a real one)."""
import json
import os
import shutil
import tempfile
import unittest

from omaforge import tasks, vault as vault_mod
from omaforge.vault import Vault, VaultError

DAY = "2026-10-06"

SETTINGS = {
    "tasksFolder": "TaskNotes/Tasks", "archiveFolder": "TaskNotes/Archive", "moveArchivedTasks": True,
    "taskTag": "todo", "taskIdentificationMethod": "tag", "storeTitleInFilename": True,
    "taskFilenameFormat": "zettel", "defaultTaskStatus": "todo",
    "fieldMapping": {"recurrenceAnchor": "recurrence_anchor", "completeInstances": "complete_instances",
                     "skippedInstances": "skipped_instances", "archiveTag": "archived"},
    "customStatuses": [
        {"value": "todo", "label": "Todo", "isCompleted": False, "order": 0},
        {"value": "in-progress", "label": "In progress", "isCompleted": False, "order": 1},
        {"value": "done", "label": "Done", "isCompleted": True, "order": 2},
        {"value": "archived", "label": "Archived", "isCompleted": True, "order": 3, "autoArchive": True},
    ],
}

TASK = """---
status: todo
priority: normal
due: 2026-10-10
dateCreated: 2026-10-01T10:00:00.000+01:00
dateModified: 2026-10-01T10:00:00.000+01:00
tags:
  - todo
---

Body.
"""


class VaultCase(unittest.TestCase):
    writable = True

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="omaforge-test-")
        os.makedirs(os.path.join(self.dir, ".obsidian/plugins/tasknotes"))
        os.makedirs(os.path.join(self.dir, "TaskNotes/Tasks"))
        os.makedirs(os.path.join(self.dir, "TaskNotes/Archive"))
        with open(os.path.join(self.dir, ".obsidian/plugins/tasknotes/data.json"), "w") as f:
            json.dump(SETTINGS, f)
        self.cfg = os.path.join(self.dir, "config.json")
        with open(self.cfg, "w") as f:
            json.dump({"writableVaults": [self.dir] if self.writable else []}, f)
        self._old_cfg = vault_mod.CONFIG
        vault_mod.CONFIG = self.cfg
        self.put("TaskNotes/Tasks/Buy milk.md", TASK)
        self.v = Vault(self.dir)
        self.v.scan()

    def tearDown(self):
        vault_mod.CONFIG = self._old_cfg
        shutil.rmtree(self.dir)

    def put(self, rel, text):
        full = os.path.join(self.dir, rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as f:
            f.write(text)

    def get(self, rel):
        with open(os.path.join(self.dir, rel), encoding="utf-8") as f:
            return f.read()

    def task(self, rel="TaskNotes/Tasks/Buy milk.md"):
        self.v.scan()
        return tasks.task_for(self.v, rel, DAY)

    def op(self, name, **req):
        return tasks.OPS[name](self.v, req, DAY)


class Safety(VaultCase):
    def test_conflict_when_field_changed_on_disk(self):
        t = self.task()
        self.put("TaskNotes/Tasks/Buy milk.md", TASK.replace("due: 2026-10-10", "due: 2026-12-25"))
        with self.assertRaises(VaultError) as cm:
            self.op("update", path=t["path"], set={"due": "2026-11-01"}, expect={"due": t["raw"]["due"]})
        self.assertEqual(cm.exception.code, "conflict")
        self.assertIn("due: 2026-12-25", self.get("TaskNotes/Tasks/Buy milk.md"))

    def test_unrelated_change_on_disk_is_not_a_conflict(self):
        t = self.task()
        self.put("TaskNotes/Tasks/Buy milk.md", TASK.replace("Body.", "Body edited in Obsidian."))
        self.op("update", path=t["path"], set={"priority": "high"}, expect={"priority": t["raw"]["priority"]})
        text = self.get("TaskNotes/Tasks/Buy milk.md")
        self.assertIn("priority: high", text)
        self.assertIn("Body edited in Obsidian.", text)

    def test_unparseable_note_is_never_written(self):
        bad = "---\ntitle: Shirt [id:: 1]\ntags:\n  - todo\n---\n"
        self.put("TaskNotes/Tasks/bad.md", bad)
        t = self.task("TaskNotes/Tasks/bad.md")
        self.assertTrue(t["error"])
        with self.assertRaises(VaultError):
            self.op("toggleComplete", path=t["path"], expect={})
        self.assertEqual(self.get("TaskNotes/Tasks/bad.md"), bad)

    def test_todoist_link_is_not_a_problem(self):
        self.put("TaskNotes/Tasks/imported.md", "---\ntitle: x %%[tid:: [1](todoist://task?id=1)]%%\n---\n")
        self.assertIsNone(self.task("TaskNotes/Tasks/imported.md"))
        self.put("TaskNotes/Tasks/sub.md", "---\ntags:\n  - todo/work\n---\n")
        self.assertIsNotNone(self.task("TaskNotes/Tasks/sub.md"))

    def test_body_save_conflict(self):
        b = self.op("body", path="TaskNotes/Tasks/Buy milk.md")
        self.put("TaskNotes/Tasks/Buy milk.md", TASK.replace("Body.", "Changed elsewhere."))
        with self.assertRaises(VaultError) as cm:
            self.op("saveBody", path="TaskNotes/Tasks/Buy milk.md", body="Mine", hash=b["hash"])
        self.assertEqual(cm.exception.code, "conflict")

    def test_body_save_keeps_frontmatter_bytes(self):
        b = self.op("body", path="TaskNotes/Tasks/Buy milk.md")
        self.op("saveBody", path="TaskNotes/Tasks/Buy milk.md", body="\nNew body.\n", hash=b["hash"])
        text = self.get("TaskNotes/Tasks/Buy milk.md")
        self.assertTrue(text.startswith("---\nstatus: todo\npriority: normal\ndue: 2026-10-10\n"))
        self.assertTrue(text.endswith("---\n\nNew body.\n"))

    def test_missing_file_is_reported_not_recreated(self):
        os.unlink(os.path.join(self.dir, "TaskNotes/Tasks/Buy milk.md"))
        with self.assertRaises(VaultError) as cm:
            self.op("toggleComplete", path="TaskNotes/Tasks/Buy milk.md", expect={})
        self.assertEqual(cm.exception.code, "missing")
        self.assertFalse(os.path.exists(os.path.join(self.dir, "TaskNotes/Tasks/Buy milk.md")))

    def test_path_escape_refused(self):
        with self.assertRaises(VaultError):
            self.op("body", path="../outside.md")


class ReadOnly(VaultCase):
    writable = False

    def test_unlisted_vault_is_read_only(self):
        self.assertIn("writableVaults", self.v.settings.quarantined)
        before = self.get("TaskNotes/Tasks/Buy milk.md")
        with self.assertRaises(VaultError) as cm:
            self.op("toggleComplete", path="TaskNotes/Tasks/Buy milk.md", expect={})
        self.assertEqual(cm.exception.code, "read-only")
        with self.assertRaises(VaultError):
            self.op("create", fields={"title": "nope"})
        self.assertEqual(self.get("TaskNotes/Tasks/Buy milk.md"), before)
        self.assertEqual(os.listdir(os.path.join(self.dir, "TaskNotes/Tasks")), ["Buy milk.md"])


class Renames(VaultCase):
    def test_rename_when_unlinked(self):
        r = self.op("update", path="TaskNotes/Tasks/Buy milk.md", set={"title": "Buy oat milk"}, expect={})
        self.assertEqual(r["path"], "TaskNotes/Tasks/Buy oat milk.md")
        self.assertNotIn("title:", self.get(r["path"]))

    def test_linked_note_keeps_filename(self):
        self.put("Daily/2026-10-06.md", "Remember [[Buy milk]] today\n")
        r = self.op("update", path="TaskNotes/Tasks/Buy milk.md", set={"title": "Buy oat milk"}, expect={})
        self.assertEqual(r["path"], "TaskNotes/Tasks/Buy milk.md")
        self.assertIn("title: Buy oat milk", self.get(r["path"]))
        self.assertIn("link", r["note"])

    def test_unrepresentable_title_kept_as_property(self):
        r = self.op("update", path="TaskNotes/Tasks/Buy milk.md", set={"title": "Milk: why?"}, expect={})
        self.assertEqual(r["path"], "TaskNotes/Tasks/Milk why.md")
        self.assertIn('title: "Milk: why?"', self.get(r["path"]))


class Archive(VaultCase):
    def test_archive_moves_and_tags(self):
        r = self.op("archive", path="TaskNotes/Tasks/Buy milk.md", on=True, expect={})
        self.assertEqual(r["path"], "TaskNotes/Archive/Buy milk.md")
        self.assertIn("  - archived", self.get(r["path"]))
        r = self.op("archive", path=r["path"], on=False, expect={})
        self.assertEqual(r["path"], "TaskNotes/Tasks/Buy milk.md")
        self.assertNotIn("archived", self.get(r["path"]))

    def test_archive_collision_keeps_tag_and_place(self):
        self.put("TaskNotes/Archive/Buy milk.md", "occupied\n")
        r = self.op("archive", path="TaskNotes/Tasks/Buy milk.md", on=True, expect={})
        self.assertEqual(r["path"], "TaskNotes/Tasks/Buy milk.md")
        self.assertIn("already exists", r["note"])
        self.assertEqual(self.get("TaskNotes/Archive/Buy milk.md"), "occupied\n")

    def test_auto_archive_status(self):
        r = self.op("setStatus", path="TaskNotes/Tasks/Buy milk.md", status="archived", expect={})
        self.assertEqual(r["path"], "TaskNotes/Archive/Buy milk.md")
        text = self.get(r["path"])
        self.assertIn("status: archived", text)
        self.assertIn("completedDate: %s" % DAY, text)


class Dependencies(VaultCase):
    def test_blocked_by_path_becomes_shortest_link(self):
        self.put("TaskNotes/Tasks/Call the bank.md", TASK)
        r = self.op("update", path="TaskNotes/Tasks/Buy milk.md", set={"blockedBy": [{"path": "TaskNotes/Tasks/Call the bank.md"}]}, expect={})
        self.assertIn('blockedBy:\n  - uid: "[[Call the bank]]"\n    reltype: FINISHTOSTART', self.get(r["path"]))
        self.assertTrue(r["task"]["blocked"])
        # same name elsewhere in the vault -> the full path
        self.put("Elsewhere/Call the bank.md", "plain note\n")
        self.v.scan()
        r = self.op("update", path="TaskNotes/Tasks/Buy milk.md", set={"blockedBy": [{"path": "TaskNotes/Tasks/Call the bank.md"}]}, expect={})
        self.assertIn('"[[TaskNotes/Tasks/Call the bank]]"', self.get(r["path"]))
        r = self.op("update", path="TaskNotes/Tasks/Buy milk.md", set={"blockedBy": []}, expect={})
        self.assertNotIn("blockedBy", self.get(r["path"]))


class Repeats(VaultCase):
    def test_set_change_clear(self):
        # DAY is Tue 2026-10-06; the task has due 2026-10-10 and no scheduled date
        r = self.op("update", path="TaskNotes/Tasks/Buy milk.md", set={"recurrence": "FREQ=WEEKLY;BYDAY=FR"}, expect={})
        text = self.get(r["path"])
        self.assertIn("recurrence: DTSTART:20261009;FREQ=WEEKLY;BYDAY=FR", text)
        self.assertIn("scheduled: 2026-10-09", text)
        self.assertIn("due: 2026-10-10", text)            # no scheduled before -> due untouched
        r = self.op("update", path=r["path"], set={"recurrence": "FREQ=MONTHLY;BYMONTHDAY=1"}, expect={})
        text = self.get(r["path"])
        self.assertIn("scheduled: 2026-11-01", text)
        self.assertIn("due: 2026-11-02", text)            # moved with scheduled (+23 days)
        self.assertIn("DTSTART:20261101;", text)
        r = self.op("update", path=r["path"], set={"recurrence": ""}, expect={})
        self.assertNotIn("recurrence:", self.get(r["path"]))

    def test_bad_rules_refused(self):
        for bad in ("every blue moon", "FREQ=WEEKLY;UNTIL=20200101"):
            with self.assertRaises(VaultError):
                self.op("update", path="TaskNotes/Tasks/Buy milk.md", set={"recurrence": bad}, expect={})


class Duplicate(VaultCase):
    def test_duplicate(self):
        self.put("TaskNotes/Tasks/Weekly report.md", """---
status: done
priority: high
due: 2026-10-10
contexts:
  - work
recurrence: DTSTART:20261002;FREQ=WEEKLY;BYDAY=FR
complete_instances:
  - 2026-10-02
reminders:
  - id: rem_1
    type: relative
    relatedTo: due
    offset: -PT15M
dateCreated: 2026-10-01T10:00:00.000+01:00
tags:
  - todo
  - work
---

Notes stay.
""")
        r = self.op("duplicate", path="TaskNotes/Tasks/Weekly report.md")
        self.assertEqual(r["path"], "TaskNotes/Tasks/Weekly report (copy).md")
        text = self.get(r["path"])
        for want in ("status: todo", "priority: high", "due: 2026-10-10", "  - work", "offset: -PT15M",
                     "FREQ=WEEKLY;BYDAY=FR", "Notes stay."):
            self.assertIn(want, text)
        for gone in ("complete_instances", "id: rem_1\n", "status: done"):
            self.assertNotIn(gone, text)
        self.assertTrue(text.split("---")[1].rstrip().endswith("  - work"))  # tags still last


class Create(VaultCase):
    def test_collision_suffix(self):
        r = self.op("create", fields={"title": "Buy milk"})
        self.assertEqual(r["path"], "TaskNotes/Tasks/Buy milk-2.md")
        self.assertTrue(self.get(r["path"]).startswith("---\ntitle: Buy milk\nstatus: todo\n"))

    def test_layout(self):
        r = self.op("create", fields={"title": "Call mum", "due": "2026-10-09", "tags": ["home"]})
        text = self.get(r["path"])
        lines = text.split("\n")
        self.assertEqual(lines[1:4], ["status: todo", "priority: normal", "due: 2026-10-09"])
        self.assertTrue(text.endswith("tags:\n  - todo\n  - home\n---\n\n"))


if __name__ == "__main__":
    unittest.main()
