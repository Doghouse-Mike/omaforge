"""TaskNotes 4.15+ moved-occurrence identity (`recurrence_original_date`).

Expected values come from TaskNotes 4.16.1 itself (tools/difftest.py, the
"moved" scenarios); these pin them down without Obsidian.
"""
from omaforge.frontmatter import Note

from .test_tasks import DAY, VaultCase

PATH = "TaskNotes/Tasks/Weekly.md"
WEEKLY = """---
status: todo
priority: normal
scheduled: 2026-12-07
due: 2026-12-08
recurrence: DTSTART:20260928;FREQ=WEEKLY;BYDAY=MO
complete_instances:
  - 2026-09-28
dateCreated: 2026-09-20T10:00:00.000+01:00
dateModified: 2026-09-20T10:00:00.000+01:00
tags:
  - todo
---
"""
MOVED = WEEKLY.replace("scheduled: 2026-12-07\ndue: 2026-12-08", "scheduled: 2026-12-09\ndue: 2026-12-10") \
    .replace("tags:", "recurrence_original_date: 2026-12-07\ntags:")


class MovedOccurrence(VaultCase):
    def run_op(self, seed, op, **req):
        self.put(PATH, seed)
        t = self.task(PATH)
        self.op(op, path=PATH, expect=t["expect"], **req)
        d = Note(self.get(PATH)).data()
        return {k: (str(v) if k in ("scheduled", "due", "recurrence_original_date") and v is not None else v)
                for k, v in d.items()}

    def test_move_records_identity(self):
        d = self.run_op(WEEKLY, "update", set={"scheduled": "2026-12-09"})
        self.assertEqual(d["recurrence_original_date"], "2026-12-07")

    def test_move_back_clears(self):
        d = self.run_op(MOVED, "update", set={"scheduled": "2026-12-07"})
        self.assertNotIn("recurrence_original_date", d)

    def test_complete_ticks_identity_and_keeps_span(self):
        d = self.run_op(MOVED, "toggleComplete")
        self.assertEqual([str(x) for x in d["complete_instances"]], ["2026-09-28", "2026-12-07"])
        self.assertEqual((d["scheduled"], d["due"]), ("2026-12-14", "2026-12-15"))
        self.assertNotIn("recurrence_original_date", d)

    def test_moved_date_stands_for_identity(self):
        d = self.run_op(MOVED, "toggleComplete", date="2026-12-09")
        self.assertIn("2026-12-07", [str(x) for x in d["complete_instances"]])

    def test_other_occurrence_leaves_move_pending(self):
        d = self.run_op(MOVED, "toggleComplete", date="2026-12-14")
        self.assertEqual((d["scheduled"], d["due"]), ("2026-12-09", "2026-12-10"))
        self.assertEqual(d["recurrence_original_date"], "2026-12-07")

    def test_new_rule_clears(self):
        d = self.run_op(MOVED, "update", set={"recurrence": "FREQ=WEEKLY;BYDAY=TU"})
        self.assertNotIn("recurrence_original_date", d)
