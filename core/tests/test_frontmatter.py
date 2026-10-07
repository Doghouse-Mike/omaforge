import unittest

from omaforge.frontmatter import FrontmatterError, Note, scalar


class RoundTrip(unittest.TestCase):
    CASES = [
        "no frontmatter at all\n",
        "---\ntitle: x\n---\nbody\n",
        "---\ntitle: x\n---",
        "---\n---\nbody",
        "﻿---\r\ntitle: x\r\ntags:\r\n  - todo\r\n---\r\nbody\r\n",
        "---\n# comment first\ntitle: x\n\nlist:\n- a\n- b\n---\n\n# Heading\n",
    ]

    def test_unchanged_render_is_identical(self):
        for text in self.CASES:
            self.assertEqual(Note(text).render(), text, repr(text))


class Edits(unittest.TestCase):
    def test_set_replaces_only_that_field(self):
        text = "---\ntitle:   spaced  # keep\nstatus: todo\ntags:\n- todo\n---\nbody\n"
        n = Note(text)
        n.set("status", "done")
        self.assertEqual(n.render(), text.replace("status: todo", "status: done"))

    def test_semantically_equal_set_keeps_bytes(self):
        text = "---\nstatus: \"todo\"\n---\n"
        n = Note(text)
        self.assertFalse(n.set("status", "todo"))
        self.assertEqual(n.render(), text)

    def test_append_matches_list_indent(self):
        n = Note("---\ntags:\n- todo\n---\n")
        n.set("contexts", ["home", "@desk"])
        self.assertIn('contexts:\n- home\n- "@desk"\n', n.render())
        n = Note("---\ntags:\n  - todo\n---\n")
        n.set("projects", ["[[Proj]]"])
        self.assertIn('projects:\n  - "[[Proj]]"\n', n.render())

    def test_append_goes_before_trailing_blank_lines(self):
        n = Note("---\ntitle: x\n\n---\n")
        n.set("due", "2026-10-07")
        self.assertEqual(n.render(), "---\ntitle: x\ndue: 2026-10-07\n\n---\n")

    def test_remove(self):
        n = Note("---\na: 1\nb:\n  - x\nc: 3\n---\n")
        n.remove("b")
        self.assertEqual(n.render(), "---\na: 1\nc: 3\n---\n")

    def test_add_frontmatter_to_plain_note(self):
        n = Note("just body\n")
        n.set("title", "T")
        self.assertEqual(n.render(), "---\ntitle: T\n---\njust body\n")

    def test_crlf_preserved_on_edit(self):
        n = Note("---\r\nstatus: todo\r\n---\r\nb\r\n")
        n.set("status", "done")
        self.assertEqual(n.render(), "---\r\nstatus: done\r\n---\r\nb\r\n")

    def test_dates_stay_strings(self):
        d = Note("---\ndue: 2026-10-07\nc: 2026-10-02T11:26:44.935+01:00\n---\n").data()
        self.assertEqual(d, {"due": "2026-10-07", "c": "2026-10-02T11:26:44.935+01:00"})

    def test_yaml12_booleans(self):
        d = Note("---\na: yes\nb: off\nc: true\n---\n").data()
        self.assertEqual(d, {"a": "yes", "b": "off", "c": True})

    def test_invalid_yaml_raises(self):
        with self.assertRaises(FrontmatterError):
            Note("---\ntitle: Shirt [id:: 1]\n---\n").data()


class Scalars(unittest.TestCase):
    def test_roundtrip_types(self):
        for v in ["todo", "2026-10-07", "2026-10-07T09:30", "yes", "null", "123",
                  "a: b", "#tag", "[[Link]]", "it's", "", " pad ", "multi\nline", "@ctx"]:
            n = Note("---\n---\n")
            n.set("k", v)
            self.assertEqual(n.data(), {"k": v}, v)
        self.assertEqual(scalar("2026-10-07"), "2026-10-07")
        self.assertEqual(scalar("yes"), '"yes"')
        self.assertEqual(scalar('say "hi"'), '"say \\"hi\\""')


if __name__ == "__main__":
    unittest.main()
