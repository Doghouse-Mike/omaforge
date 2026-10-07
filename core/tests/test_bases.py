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
        text = bases.render_base(MODEL, self.v.settings)
        d = bases.load_base(text)
        d["views"][0]["filters"]["and"].append("file.name.contains(\"z\") || true")
        self.assertEqual(bases.editable_models(self.v, "x.base", d), {})
        d = bases.load_base(text)
        d["views"].append({"type": "table", "name": "Other"})
        self.assertEqual(bases.editable_models(self.v, "x.base", d), {})

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
