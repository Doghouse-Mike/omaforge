"""A shared or synced vault is untrusted input: hostile files must neither
hang the core nor blow up its memory, and unsupported repeat rules are
refused before anything is written."""
import os
import signal
import unittest

from omaforge import bases, tasks
from omaforge.vault import MAX_FILE_BYTES, VaultError

from .test_tasks import DAY, TASK, VaultCase

BOMB = "---\ntags:\n  - todo\na: &a [x, x, x, x, x, x, x, x, x]\n" + "".join(
    "%s: &%s [%s]\n" % (c, c, ", ".join(["*" + p] * 9)) for p, c in zip("abcdefgh", "bcdefghi")) + "---\n"


class Hostile(VaultCase):
    def setUp(self):
        super().setUp()
        # A hang is the failure mode under test: fail it instead of waiting.
        signal.signal(signal.SIGALRM, lambda *a: self.fail("timed out (blocked on a hostile file)"))
        signal.alarm(10)

    def tearDown(self):
        signal.alarm(0)
        super().tearDown()

    def test_fifo_and_device_skipped(self):
        os.mkfifo(os.path.join(self.dir, "TaskNotes/Tasks/pipe.md"))
        os.mkfifo(os.path.join(self.dir, "TaskNotes/Views.base"))
        os.symlink("/dev/zero", os.path.join(self.dir, "TaskNotes/Tasks/zero.md"))
        self.v.scan()
        self.assertIn("unreadable", self.v.entries["TaskNotes/Tasks/pipe.md"].error)
        self.assertIn("unreadable", self.v.entries["TaskNotes/Tasks/zero.md"].error)
        self.assertIsNotNone(tasks.task_for(self.v, "TaskNotes/Tasks/Buy milk.md", DAY))
        bases.all_views(self.v)
        with self.assertRaises(VaultError):
            self.v.read("TaskNotes/Tasks/pipe.md")

    def test_symlink_to_regular_note_still_works(self):
        os.symlink(os.path.join(self.dir, "TaskNotes/Tasks/Buy milk.md"),
                   os.path.join(self.dir, "TaskNotes/Tasks/Linked.md"))
        self.v.scan()
        self.assertEqual(self.v.read("TaskNotes/Tasks/Linked.md"), TASK)

    def test_oversized_note_refused(self):
        self.put("TaskNotes/Tasks/Huge.md", TASK + "x" * (MAX_FILE_BYTES + 1))
        self.v.scan()  # frontmatter mode only reads the head
        with self.assertRaises(VaultError) as cm:
            self.v.read("TaskNotes/Tasks/Huge.md")
        self.assertEqual(cm.exception.code, "unreadable")

    def test_yaml_alias_bomb_rejected(self):
        self.put("TaskNotes/Tasks/Bomb.md", BOMB)
        self.v.scan()
        self.assertIn("aliases", self.v.entries["TaskNotes/Tasks/Bomb.md"].error)
        views = bases.views_in(self.v, "Bomb.base", "views: &v [{type: table, name: x}]\nmore: *v\n")
        self.assertIn("aliases", views[0]["unsupported"])


class UnsupportedRepeats(VaultCase):
    def test_setting_unsupported_rule_refused(self):
        for bad in ("FREQ=HOURLY", "FREQ=DAILY;BYHOUR=9", "FREQ=YEARLY;BYWEEKNO=20"):
            with self.assertRaises(VaultError) as cm:
                self.op("update", path="TaskNotes/Tasks/Buy milk.md", set={"recurrence": bad}, expect={})
            self.assertEqual(cm.exception.code, "unsupported")

    def test_existing_unsupported_rule_lists_but_wont_tick(self):
        rel = "TaskNotes/Tasks/Hourly.md"
        self.put(rel, TASK.replace("tags:", "recurrence: DTSTART:20261001;FREQ=HOURLY\ntags:"))
        self.assertIsNotNone(self.task(rel))
        before = self.get(rel)
        with self.assertRaises(VaultError) as cm:
            self.op("toggleComplete", path=rel, expect={})
        self.assertEqual(cm.exception.code, "unsupported")
        self.assertEqual(self.get(rel), before)


if __name__ == "__main__":
    unittest.main()
