import json
import unittest
from datetime import datetime

from omaforge import notify

CFG = notify.settings({})


def ts(s):
    return datetime.fromisoformat(s).timestamp()


def task(**kw):
    t = {"path": "TaskNotes/Tasks/x.md", "title": "X", "done": False, "archived": False, "error": None,
         "recurring": False, "completeInstances": [], "due": "", "scheduled": "", "occurrence": "", "props": {}}
    t.update(kw)
    return t


def rel(offset, to="due", rid="r1"):
    return {"id": rid, "type": "relative", "relatedTo": to, "offset": offset}


class Durations(unittest.TestCase):
    def test_iso(self):
        self.assertEqual(notify.duration_s("-PT15M"), -900)
        self.assertEqual(notify.duration_s("P1D"), 86400)
        self.assertEqual(notify.duration_s("-P1DT2H"), -93600)
        self.assertEqual(notify.duration_s("P1M"), 30 * 86400)   # TaskNotes: month = 30 days
        self.assertEqual(notify.duration_s("PT0M"), 0)
        self.assertIsNone(notify.duration_s("15 minutes"))
        self.assertIsNone(notify.duration_s("P"))


class Reminders(unittest.TestCase):
    def fire(self, t, now, state=None, cfg=CFG):
        return [e for e in notify.due_events([t], ts(now), cfg, state or {}) if e["kind"] in ("reminder", "timed")]

    def test_relative_before_due(self):
        t = task(due="2026-10-08T14:00", props={"reminders": [rel("-PT15M")]})
        self.assertEqual(self.fire(t, "2026-10-08T13:44"), [])
        ev = [e for e in self.fire(t, "2026-10-08T13:45") if e["kind"] == "reminder"]
        self.assertEqual(len(ev), 1)
        self.assertEqual(ev[0]["body"], "Due in 15 minutes")

    def test_date_only_anchor_is_local_midnight(self):
        t = task(due="2026-10-08", props={"reminders": [rel("-PT1H")]})
        self.assertEqual(len(self.fire(t, "2026-10-07T23:00")), 1)

    def test_absolute(self):
        t = task(props={"reminders": [{"id": "a", "type": "absolute", "absoluteTime": "2026-10-08T09:00:00", "description": "Ring the bank"}]})
        ev = self.fire(t, "2026-10-08T09:00:30")
        self.assertEqual([e["body"] for e in ev], ["Ring the bank"])

    def test_fires_once(self):
        t = task(due="2026-10-08T14:00", props={"reminders": [rel("PT0M")]})
        ev = self.fire(t, "2026-10-08T14:00")
        state = {"fired": {e["key"]: 1 for e in ev}}
        self.assertEqual(self.fire(t, "2026-10-08T14:05", state), [])

    def test_catch_up_window(self):
        t = task(due="2026-10-08T14:00", props={"reminders": [rel("PT0M")]})
        self.assertTrue(self.fire(t, "2026-10-09T13:59"))     # 24h late still fires
        self.assertFalse(self.fire(t, "2026-10-09T14:01"))    # older is history

    def test_done_archived_and_completed_occurrence_skip(self):
        r = {"reminders": [rel("PT0M")]}
        self.assertFalse(self.fire(task(due="2026-10-08T14:00", done=True, props=r), "2026-10-08T14:01"))
        self.assertFalse(self.fire(task(due="2026-10-08T14:00", archived=True, props=r), "2026-10-08T14:01"))
        rec = task(scheduled="2026-10-08T14:00", recurring=True, completeInstances=["2026-10-08"],
                   props={"reminders": [rel("PT0M", "scheduled")]})
        self.assertFalse(self.fire(rec, "2026-10-08T14:01"))
        rec["completeInstances"] = []
        self.assertTrue(self.fire(rec, "2026-10-08T14:01"))

    def test_timed_tasks_and_lead_time(self):
        t = task(due="2026-10-08T14:00", scheduled="2026-10-08")
        ev = self.fire(t, "2026-10-08T14:00")
        self.assertEqual([(e["kind"], e["body"]) for e in ev], [("timed", "Due now")])  # date-only scheduled: no timed event
        cfg = notify.settings({"notifications": {"timedTasks": {"minutesBefore": 10}}})
        self.assertTrue(self.fire(t, "2026-10-08T13:50", cfg=cfg))
        cfg = notify.settings({"notifications": {"timedTasks": {"enabled": False}, "reminders": {"enabled": False}}})
        self.assertFalse(self.fire(t, "2026-10-08T14:00", cfg=cfg))

    def test_snooze_refires(self):
        e = {"key": "k", "kind": "reminder", "at": 0, "path": "p", "title": "X", "body": "b"}
        state = {"snoozed": {"k": {"until": int(ts("2026-10-08T14:15")), "event": e}}}
        self.assertFalse([x for x in notify.due_events([], ts("2026-10-08T14:14"), CFG, state) if x["kind"] == "reminder"])
        got = [x for x in notify.due_events([], ts("2026-10-08T14:15"), CFG, state) if x["kind"] == "reminder"]
        self.assertEqual(got[0]["snoozedFrom"], "k")


class Daily(unittest.TestCase):
    def test_summary_once_after_time(self):
        tl = [task(due="2026-10-08"), task(path="b.md", title="Late", due="2026-10-01"), task(path="c.md", due="2026-10-20")]
        none = notify.due_events(tl, ts("2026-10-08T08:59"), CFG, {})
        self.assertFalse([e for e in none if e["kind"] == "summary"])
        ev = [e for e in notify.due_events(tl, ts("2026-10-08T09:00"), CFG, {}) if e["kind"] == "summary"]
        self.assertEqual(ev[0]["title"], "Today: 1 for today, 1 overdue")
        self.assertFalse([e for e in notify.due_events(tl, ts("2026-10-08T10:00"), CFG, {"summary": "2026-10-08"})
                          if e["kind"] == "summary"])

    def test_overdue_silent_when_nothing_late(self):
        ev = [e for e in notify.due_events([task(due="2026-10-09")], ts("2026-10-08T17:00"), CFG, {}) if e["kind"] == "overdue"]
        self.assertTrue(ev[0]["silent"])   # still recorded, so it won't retry all evening


if __name__ == "__main__":
    unittest.main()
