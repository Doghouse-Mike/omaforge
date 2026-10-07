"""Line-preserving YAML frontmatter editing.

TaskNotes notes are hand-edited, synced, and touched by other plugins, so the
one rule here is: a write changes only the lines of the fields it was asked to
change. Everything else -- key order, quoting, list indentation, comments,
line endings, the note body -- comes back byte-for-byte. YAML is only ever
*parsed* (for reading values); it is never re-serialised as a whole.
"""
import re
from datetime import date, datetime

import yaml

FM_DELIM = re.compile(r"^---[ \t]*$")
TOP_KEY = re.compile(r"^([^\s#:'\"\-][^:]*?|'[^']*'|\"[^\"]*\"):(?:[ \t]|$)")
DATEISH = re.compile(r"^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:\d{2})?)?$")
SAFE_PLAIN = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_ ./()+,&@!-]*$")


class FrontmatterError(Exception):
    pass


class Note:
    """A markdown note split into frontmatter blocks and body.

    blocks: list of [key, [lines]] in file order. A block is a top-level key
    line plus every following line until the next top-level key (continuation
    lines, list items, comments, blank lines all stay attached to it).
    lead: lines before the first key (comments/blank), kept verbatim.
    """

    def __init__(self, text):
        self.bom = text.startswith("\ufeff")
        if self.bom:
            text = text[1:]
        self.newline = "\r\n" if "\r\n" in text else "\n"
        lines = text.split(self.newline)
        self.has_fm = False
        self.lead = []
        self.blocks = []
        self.close_line = "---"
        self.open_line = "---"
        end = None
        if lines and FM_DELIM.match(lines[0]):
            for i in range(1, len(lines)):
                if FM_DELIM.match(lines[i]):
                    end = i
                    break
        if end is None:
            self.body = text
            self.tail_sep = True  # if frontmatter gets added, body follows it
            return
        self.tail_sep = end + 1 < len(lines)
        self.has_fm = True
        self.open_line = lines[0]
        self.close_line = lines[end]
        self.body = self.newline.join(lines[end + 1:])
        current = None
        for line in lines[1:end]:
            m = TOP_KEY.match(line) if line and not line[0].isspace() else None
            if m:
                current = [_unquote_key(m.group(1)), [line]]
                self.blocks.append(current)
            elif current is None:
                self.lead.append(line)
            else:
                current[1].append(line)

    # -- reading ---------------------------------------------------------

    def fm_text(self):
        out = list(self.lead)
        for _k, lines in self.blocks:
            out.extend(lines)
        return self.newline.join(out)

    def data(self):
        """Parsed frontmatter as a dict. Raises FrontmatterError on invalid
        YAML -- the caller decides; we never 'repair' a file we can't read."""
        if not self.has_fm:
            return {}
        try:
            d = yaml.load(self.fm_text(), Loader=_Loader)
        except yaml.YAMLError as e:
            raise FrontmatterError(str(e).split("\n")[0]) from e
        if d is None:
            return {}
        if not isinstance(d, dict):
            raise FrontmatterError("frontmatter is not a mapping")
        return d

    def keys(self):
        return [k for k, _ in self.blocks]

    def render(self):
        bom = "\ufeff" if self.bom else ""
        if not self.has_fm:
            return bom + self.body
        head = [self.open_line] + self.lead
        for _k, lines in self.blocks:
            head.extend(lines)
        head.append(self.close_line)
        text = self.newline.join(head)
        if self.tail_sep:
            text += self.newline + self.body
        return bom + text

    # -- writing ---------------------------------------------------------

    def _list_indent(self):
        """Match the file's own block-list style ("- x" vs "  - x")."""
        for _k, lines in self.blocks:
            for line in lines[1:]:
                m = re.match(r"^(\s*)- ", line)
                if m:
                    return m.group(1)
        return "  "

    def set(self, key, value):
        """Set key to value, replacing only that key's block (or appending).
        value None removes the key."""
        if value is None:
            return self.remove(key)
        self.has_fm = True
        new_lines = render_field(key, value, self._list_indent())
        for block in self.blocks:
            if block[0] == key:
                if parse_lines(block[1]) == parse_lines(new_lines):
                    return False  # semantically unchanged: keep original bytes
                block[1] = new_lines
                return True
        # Appending after a block that ends in blank/comment lines would
        # bury the key below them; insert before trailing blanks instead.
        if self.blocks:
            last = self.blocks[-1][1]
            trail = []
            while len(last) > 1 and last[-1].strip() == "":
                trail.insert(0, last.pop())
            self.blocks.append([key, new_lines + trail])
        else:
            self.blocks.append([key, new_lines])
        return True

    def remove(self, key):
        before = len(self.blocks)
        self.blocks = [b for b in self.blocks if b[0] != key]
        return len(self.blocks) != before


def _unquote_key(k):
    k = k.strip()
    if len(k) >= 2 and k[0] == k[-1] and k[0] in "'\"":
        return k[1:-1]
    return k


class _Loader(yaml.SafeLoader):
    """SafeLoader that keeps timestamps as the strings they were written as.

    Obsidian's YAML parser doesn't coerce dates, so neither do we: a value
    reads back exactly as the user (or TaskNotes) wrote it."""


# Obsidian parses YAML 1.2: no timestamp coercion, and only true/false are
# booleans (1.1's yes/no/on/off stay strings).
_Loader.yaml_implicit_resolvers = {
    k: [(tag, rx) for tag, rx in v
        if tag not in ("tag:yaml.org,2002:timestamp", "tag:yaml.org,2002:bool")]
    for k, v in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
_Loader.add_implicit_resolver(
    "tag:yaml.org,2002:bool", re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$"),
    list("tTfF"))


def parse_lines(lines):
    try:
        return yaml.load("\n".join(lines), Loader=_Loader)
    except yaml.YAMLError:
        return object()  # never equal to anything


def scalar(value):
    """Render a scalar the way Obsidian's serializer would: plain where that
    round-trips unchanged, otherwise double-quoted. Dates are the exception:
    2026-10-07 stays plain (PyYAML 1.1 would coerce it, but TaskNotes writes
    it plain and every reader here treats it as a string)."""
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, datetime):
        value = value.isoformat()
    elif isinstance(value, date):
        value = value.isoformat()
    s = str(value)
    if s == "":
        return "''"
    if DATEISH.match(s):
        return s
    if SAFE_PLAIN.match(s) and s == s.strip():
        try:
            # Plain only if a YAML 1.1 reader (PyYAML, other tools) and a 1.2
            # reader (Obsidian) both read it back as this exact string.
            if (yaml.load("k: " + s, Loader=_Loader) == {"k": s}
                    and yaml.safe_load("k: " + s) == {"k": s}):
                return s
        except yaml.YAMLError:
            pass
    # Double quotes, as Obsidian's own serializer writes them.
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\t", "\\t") + '"'


def render_field(key, value, list_indent="  "):
    k = key if SAFE_PLAIN.match(key) else scalar(key)
    if isinstance(value, (list, tuple)):
        if not value:
            return ["%s: []" % k]
        out = ["%s:" % k]
        for item in value:
            if isinstance(item, dict):
                first = True
                for ik, iv in item.items():
                    prefix = list_indent + ("- " if first else "  ")
                    out.append("%s%s: %s" % (prefix, ik, scalar(iv)))
                    first = False
            else:
                out.append("%s- %s" % (list_indent, scalar(item)))
        return out
    if isinstance(value, dict):
        out = ["%s:" % k]
        for ik, iv in value.items():
            out.append("  %s: %s" % (ik, scalar(iv)))
        return out
    return ["%s: %s" % (k, scalar(value))]
