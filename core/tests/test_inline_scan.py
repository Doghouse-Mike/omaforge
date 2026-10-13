import unittest

from omaforge import inline


def found(text):
    return [n for n, _ in inline.candidate_lines(text)]


class Scan(unittest.TestCase):
    def test_basic_markers_and_quotes(self):
        text = "- [ ] a\n* [x] b\n+ [/] c\n1. [ ] d\n2) [ ] e\n> - [ ] f\n- not a task\n- [] nope\n"
        self.assertEqual(found(text), [0, 1, 2, 3, 4, 5])

    def test_frontmatter_and_fences_skipped(self):
        text = "---\ntitle: x\nlist:\n- [ ] not me\n---\n- [ ] me\n```\n- [ ] code\n```\n~~~md\n- [ ] code\n~~~\n- [ ] me too\n"
        self.assertEqual(found(text), [5, 12])

    def test_indented_items_only_inside_lists(self):
        # A tab-indented checkbox after a paragraph is an indented code block.
        text = "Intro paragraph.\n\n\t- [x] code, not a task\n\nText.\n- [ ] parent\n\t- [ ] child\n    - [ ] spaces child\n"
        self.assertEqual(found(text), [5, 6, 7])

    def test_list_survives_blank_lines_but_not_paragraphs(self):
        text = "- [ ] one\n\n  - [ ] nested after blank\n\nParagraph ends it\n\n\t- [ ] code again\n"
        self.assertEqual(found(text), [0, 2])
        # A line right under an item (no blank) continues it, so the list stays open.
        text = "- [ ] one\nlazy continuation\n\n\t- [ ] still in the list\n"
        self.assertEqual(found(text), [0, 3])

    def test_headings_parents_and_query_blocks(self):
        text = ("# Top\n- [ ] a\n    - [ ] child\n    - note\n        - [ ] grandchild\n\n## Next ##\n"
                "```tasks\nnot done\n# a comment\n```\n> ```tasks\n> due today\n> ```\n- [ ] b\n"
                "```js\n- [ ] not a task\n```\n")
        cands, meta, queries = inline.scan(text)
        self.assertEqual([n for n, _ in cands], [1, 2, 4, 14])
        self.assertEqual(meta[1], {"heading": "Top", "parent": None})
        self.assertEqual(meta[2]["parent"], 1)
        self.assertEqual(meta[4]["parent"], 3)            # nested under the plain "note" bullet
        self.assertEqual(meta[14]["heading"], "Next")
        self.assertEqual(queries, [(7, "not done\n# a comment", "Next"), (11, "due today", "Next")])

    def test_note_props_for_queries(self):
        p = inline.note_props("---\nTQ_short_mode: true\nwhen: 2026-10-13\nn: 3\nlisty:\n  - a\n  -\n"
                              "tags: alpha, beta\n---\nbody\n")
        self.assertEqual(p, {"TQ_short_mode": True, "when": "2026-10-13", "n": 3, "listy": ["a", None],
                             "tags": ["#alpha", "#beta"]})
        self.assertEqual(inline.note_props("no frontmatter"), {"tags": []})

    def test_keys(self):
        k = inline.key("Daily notes/2026-10-07.md", 12)
        self.assertEqual(inline.split_key(k), ("Daily notes/2026-10-07.md", 12))
        self.assertTrue(inline.is_inline_key(k))
        self.assertFalse(inline.is_inline_key("TaskNotes/Tasks/x.md"))


if __name__ == "__main__":
    unittest.main()
