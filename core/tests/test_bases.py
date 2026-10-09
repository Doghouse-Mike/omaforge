import os

from omaforge import bases
from omaforge.vault import VaultError

from .test_tasks import DAY, VaultCase

MODEL = {
    "name": "Home this week", "match": "all", "layout": "list", "group": "status",
    "sort": {"field": "priority", "dir": "desc"},
    "conditions": [
        {"field": "status", "op": "open", "value": ""},
        {"field": "due", "op": "onOrBefore", "value": "+7"},
        {"field": "contexts", "op": "lacks", "value": "office"},
        {"field": "projects", "op": "has", "value": "[[House]]"},
        {"field": "tags", "op": "has", "value": "home"},
        {"field": "archived", "op": "no", "value": ""},
    ],
}


class Parser(VaultCase):
    def test_precedence_and_formulas(self):
        c = bases.Compiler({"w": 'if(priority == "high", 3, 1)', "u": "formula.w + 1"})
        self.assertEqual(c.compile("a || b && !c"),
                         ["bin", "||", ["prop", "a"], ["bin", "&&", ["prop", "b"], ["un", "!", ["prop", "c"]]]])
        self.assertEqual(c.compile("formula.u")[0], "bin")

    def test_unsupported_is_reported(self):
        c = bases.Compiler({"loop": "formula.loop"})
        for bad in ("this.file.name", "formula.loop", "formula.missing", "nope(1)", "x.frobnicate()"):
            with self.assertRaises(bases.Unsupported, msg=bad):
                c.compile(bad)


class Editor(VaultCase):
    def test_every_condition_round_trips(self):
        s = self.v.settings
        conds = [{"field": "status", "op": op, "value": v} for op, v in
                 (("is", "todo"), ("isNot", "done"), ("open", ""), ("completed", ""))]
        conds += [{"field": "priority", "op": "is", "value": "high"}]
        for f in ("due", "scheduled", "completedDate"):
            conds += [{"field": f, "op": "empty", "value": ""}, {"field": f, "op": "notEmpty", "value": ""}]
            for op in ("before", "after", "on", "onOrBefore", "onOrAfter"):
                for v in ("today", "+3", "-2", "2026-12-25"):
                    conds.append({"field": f, "op": op, "value": v})
        for f in ("contexts", "projects", "tags", "title"):
            for op in ("has", "lacks"):
                conds.append({"field": f, "op": op, "value": "[[X]]" if f == "projects" else "x"})
        conds += [{"field": "archived", "op": o, "value": ""} for o in ("yes", "no")]
        conds += [{"field": "recurring", "op": o, "value": ""} for o in ("yes", "no")]
        for c in conds:
            back = bases.parse_condition(bases.condition_expr(c, s), s)
            self.assertEqual(back, c, c)

    def test_model_file_model(self):
        text = bases.render_base(MODEL, self.v.settings)
        models = bases.editable_models(self.v, "x.base", bases.load_base(text))
        self.assertEqual(models["Home this week"], MODEL)

    def test_hand_edited_file_is_not_editable(self):
        # Only files that regenerate exactly are editable, so nothing in them
        # can be lost by a rewrite.
        text = bases.render_base(MODEL, self.v.settings)
        d = bases.load_base(text)
        d["views"].append({"type": "table", "name": "Other"})
        self.assertEqual(bases.editable_models(self.v, "x.base", d), {})
        d = bases.load_base(text)
        d["views"][0]["limit"] = 10
        self.assertEqual(bases.editable_models(self.v, "x.base", d), {})
        d = bases.load_base(text)
        d["views"][0]["order"] = ["file.name"]
        self.assertEqual(bases.editable_models(self.v, "x.base", d), {})

    def test_hand_written_condition_is_kept_as_written(self):
        text = bases.render_base(MODEL, self.v.settings)
        d = bases.load_base(text)
        d["views"][0]["filters"]["and"].append({"or": ['file.name.contains("z")', "priority == \"high\""]})
        m = bases.editable_models(self.v, "x.base", d)["Home this week"]
        self.assertEqual(m["conditions"][-1]["field"], "raw")
        self.assertEqual(bases.jsonish(bases.base_dict(m, self.v.settings)), bases.jsonish(d))

    def test_closest_model_copies_hand_made_views_exactly(self):
        s = self.v.settings
        hand = {"filters": {"and": ['file.hasTag("%s")' % s.task_tag, "file.inFolder(\"TaskNotes\")"]},
                "formulas": {"w": "if(priority == \"high\", 2, 1)", "u": "formula.w * 2", "unused": "1"},
                "views": [{"type": "table", "name": "Mine", "filters": {"or": ['status == "todo"', {"and": ["due", "!scheduled"]}]},
                           "sort": [{"property": "formula.u", "direction": "DESC"}, {"property": "file.name", "direction": "ASC"}],
                           "groupBy": {"property": "priority", "direction": "DESC"}},
                          {"type": "tasknotesCalendar", "name": "Cal"}]}
        rel = "TaskNotes/Views/hand.base"
        self.v.write(rel, "\n".join(bases.dump(hand)) + "\n", create=True)
        m, notes = bases.closest_model(self.v, rel, "Mine")
        self.assertEqual(m["name"], "Mine copy")
        self.assertEqual(m["match"], "all")
        self.assertEqual([c["field"] for c in m["conditions"]], ["raw", "raw"])   # folder check, then the or-group
        self.assertEqual(m["sort"]["field"], "raw")
        self.assertEqual(m["groupDir"], "DESC")
        self.assertEqual(sorted(m["formulas"]), ["u", "w"])
        copy = bases.base_dict(m, s)
        # same filter as the original, and the copy is an editable OmaForge view
        orig = [v for v in bases.views_in(self.v, rel, self.v.read(rel)) if v["name"] == "Mine"][0]
        mine = bases.views_in(self.v, "c.base", "\n".join(bases.dump(copy)))[0]
        # the file-wide folder check moves into the view's own conditions
        o_top, o_view = orig["filter"][1]
        self.assertEqual(mine["filter"][1][1], ["and", [o_top[1][1], o_view]])
        self.assertEqual(mine["sort"], orig["sort"])
        self.assertTrue(mine.get("model"))
        _, notes = bases.closest_model(self.v, rel, "Cal")
        self.assertTrue(any("list" in n for n in notes))

    def test_save_edit_delete(self):
        r = bases.OPS["saveView"](self.v, {"model": MODEL}, DAY)
        self.assertEqual(r["file"], "TaskNotes/Views/Home this week.base")
        view = [v for v in r["views"] if v["file"] == r["file"]][0]
        self.assertEqual(view["model"], MODEL)
        self.assertFalse(view["unsupported"])
        # same name again: new file, never an overwrite
        r2 = bases.OPS["saveView"](self.v, {"model": MODEL}, DAY)
        self.assertEqual(r2["file"], "TaskNotes/Views/Home this week-2.base")
        # edit in place
        edited = dict(MODEL, match="any")
        bases.OPS["saveView"](self.v, {"model": edited, "file": r["file"]}, DAY)
        self.assertIn("    filters:\n      or:", self.get(r["file"]))
        # a hand-made base can't be overwritten or deleted
        self.put("TaskNotes/Views/mine.base", "filters:\n  and:\n    - file.hasTag(\"todo\")\nviews:\n  - type: table\n    name: Mine\n    order:\n      - file.name\n")
        with self.assertRaises(VaultError):
            bases.OPS["saveView"](self.v, {"model": MODEL, "file": "TaskNotes/Views/mine.base"}, DAY)
        with self.assertRaises(VaultError):
            bases.OPS["deleteView"](self.v, {"file": "TaskNotes/Views/mine.base"}, DAY)

    def test_read_only_vault_refuses(self):
        self.v.settings.quarantined = "read-only for test"
        with self.assertRaises(VaultError):
            bases.OPS["saveView"](self.v, {"model": MODEL}, DAY)
        self.assertFalse(os.path.exists(os.path.join(self.dir, "TaskNotes/Views")))
