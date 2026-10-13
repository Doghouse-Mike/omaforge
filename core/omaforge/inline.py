"""Obsidian Tasks plugin support: tasks as checkbox lines inside notes.

A Tasks task is one line ("- [ ] Pay rent 📅 2026-11-01") anywhere in the
vault, so its identity is (file, line) and that moves as the note is edited.
Every write therefore re-reads the file and checks the line still says what
the UI showed; if it moved, the unique identical line is used; otherwise the
write is refused as a conflict. Parsing and serialising follow Tasks 8.4.0
(docs/tasks-plugin-spec.md).
"""
import json
import os
import re
from datetime import date as _date

PLUGIN_ID = "obsidian-tasks-plugin"
KEY_SEP = "::L"          # task key: "<file>::L<line number>"

FENCE = re.compile(r"^\s*(```|~~~)")


CORE_STATUSES = [
    {"symbol": " ", "name": "Todo", "nextStatusSymbol": "x", "type": "TODO"},
    {"symbol": "x", "name": "Done", "nextStatusSymbol": " ", "type": "DONE"},
]
DEFAULTS = {"globalFilter": "", "removeGlobalFilter": False, "setCreatedDate": False, "setDoneDate": True,
            "setCancelledDate": True, "recurrenceOnNextLine": False, "removeScheduledDateOnRecurrence": False,
            "taskFormat": "tasksPluginEmoji"}


class TasksSettings:
    """The Tasks plugin's data.json, read-only, with Tasks' defaults."""

    def __init__(self, vault_path):
        self.path = os.path.join(vault_path, ".obsidian", "plugins", PLUGIN_ID, "data.json")
        raw = {}
        try:
            with open(self.path, encoding="utf-8") as f:
                raw = json.load(f)
            if not isinstance(raw, dict):
                raw = {}
        except (OSError, ValueError):
            raw = {}
        self.raw = raw
        for k, v in DEFAULTS.items():
            setattr(self, k, raw.get(k, v) if raw.get(k) is not None else v)
        ss = raw.get("statusSettings") or {}
        core = ss.get("coreStatuses") or CORE_STATUSES
        custom = ss.get("customStatuses") or []
        self.statuses = []
        seen = set()
        for st in list(core) + list(custom):
            sym = str(st.get("symbol", ""))
            if len(sym) != 1 or sym in seen:
                continue
            seen.add(sym)
            self.statuses.append({"symbol": sym, "name": st.get("name") or sym,
                                  "next": str(st.get("nextStatusSymbol", "x")), "type": st.get("type") or "TODO"})

    def status(self, sym):
        for st in self.statuses:
            if st["symbol"] == sym:
                return st
        # Status.createUnknownStatus: TODO type, named "Unknown", advancing to "x".
        return {"symbol": sym, "name": "Unknown", "next": "x", "type": "TODO"}

    def next_status(self, st):
        """StatusRegistry.getNextStatusOrCreate."""
        return self.status(st["next"]) if st.get("next") else self.status("x")

    def next_recurrence_status(self, new):
        """StatusRegistry.getNextRecurrenceStatusOrCreate: the first TODO, then
        IN_PROGRESS, status following `new`; else a plain space."""
        for wanted in ("TODO", "IN_PROGRESS"):
            st = self.next_status(new)
            for _ in range(max(1, len(self.statuses))):
                if st["type"] == wanted:
                    return st
                st = self.next_status(st)
        return self.status(" ")

    def public(self):
        return {"statuses": self.statuses, "globalFilter": self.globalFilter, "taskFormat": self.taskFormat,
                # for ```tasks queries (app/tasksquery.js); presets None = Tasks' defaults
                "globalQuery": self.raw.get("globalQuery") or "", "presets": self.raw.get("presets")}


def plugin_enabled(vault_path, plugin=PLUGIN_ID):
    try:
        with open(os.path.join(vault_path, ".obsidian", "community-plugins.json"), encoding="utf-8") as f:
            return plugin in json.load(f)
    except (OSError, ValueError):
        return False


def key(rel, line_no):
    return "%s%s%d" % (rel, KEY_SEP, line_no)


def split_key(k):
    if KEY_SEP not in k:
        return None, None
    rel, _, n = k.rpartition(KEY_SEP)
    try:
        return rel, int(n)
    except ValueError:
        return None, None


def is_inline_key(k):
    return KEY_SEP in str(k or "")


def candidate_lines(text):
    """(line_no, line) for checkbox-looking lines outside fenced code blocks
    and outside frontmatter. Line numbers are 0-based, as Tasks reports them."""
    return scan(text)[0]


HEADING = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+(.*?))?(?:[ \t]+#+)?[ \t]*$")
QUERY_FENCE = re.compile(r"^((?:[ \t]*>)*)[ \t]*(`{3,}|~{3,})[ \t]*tasks[ \t]*$")
QUOTE = re.compile(r"^(?:[ \t]*>[ \t]?)+")


def scan(text):
    """One pass over a note: (candidates, meta, queries).
    candidates: (line_no, line) checkbox-looking lines, as candidate_lines.
    meta: {line_no: {"heading": nearest heading above or "", "parent": line
           of the list item it's nested under, or None}}
    queries: [(line_no of the fence, source, heading above)] for ```tasks blocks."""
    out, meta, queries = [], {}, []
    lines = text.split("\n")
    i = 0
    if lines and lines[0].strip() == "---":
        for j in range(1, len(lines)):
            if lines[j].strip() == "---":
                i = j + 1
                break
    fence = None
    query = None             # (start line, quote prefix, body lines) inside ```tasks
    in_list = False          # inside a Markdown list (so indented items count)
    prev_blank = True
    heading = ""
    stack = []               # open list items: (indent, line_no)
    for n in range(i, len(lines)):
        line = lines[n].rstrip("\r")
        m = FENCE.match(QUOTE.sub("", line))
        if m:
            if fence is None:
                fence = m.group(1)
                q = QUERY_FENCE.match(line)
                query = (n, q.group(2), []) if q else None
            elif m.group(1) == fence[:3] and QUOTE.sub("", line).strip().startswith(fence):
                if query:
                    queries.append((query[0], "\n".join(query[2]), heading))
                fence, query = None, None
            in_list, prev_blank, stack = False, False, []
            continue
        if fence is not None:
            if query is not None:
                query[2].append(QUOTE.sub("", line))
            continue
        if not line.strip():
            prev_blank = True
            continue
        h = HEADING.match(line)
        if h:
            heading = (h.group(2) or "").strip()
            in_list, prev_blank, stack = False, False, []
            continue
        indent = indent_width(line)
        is_item = LIST_ITEM.match(line) is not None
        if indent >= 4 and not in_list:
            # An indented code block (after a blank line) or a paragraph's
            # continuation: never a list item to Obsidian, so never a task.
            prev_blank = False
            continue
        if is_item:
            in_list = True
            iw = indent_width(QUOTE.sub("", line))
            while stack and stack[-1][0] >= iw:
                stack.pop()
            parent = stack[-1][1] if stack else None
            stack.append((iw, n))
            if CHECKBOX_HINT.match(line):
                out.append((n, line))
                meta[n] = {"heading": heading, "parent": parent}
        elif indent < 2 and prev_blank:
            in_list, stack = False, []      # a new paragraph ends the list
        prev_blank = False
    return out, meta, queries


CHECKBOX_HINT = re.compile(r"^[\s\t>]*(?:[-*+]|[0-9]+[.)])\s+\[.\]")
LIST_ITEM = re.compile(r"^[\s\t>]*(?:[-*+]|[0-9]+[.)])(?:\s|$)")


def indent_width(line):
    w = 0
    for ch in line:
        if ch == " ":
            w += 1
        elif ch == "\t":
            w += 4 - (w % 4)
        else:
            break
    return w


# ------------------------------------------------------------ UI settings ----

TYPE_COLOR = {"TODO": "#808080", "IN_PROGRESS": "#0066cc", "DONE": "#00aa00", "CANCELLED": "#aa3333", "NON_TASK": "#888888"}
PRIORITIES = [  # Tasks' six levels, as TaskNotes-style {value,label,color,weight}
    {"value": "lowest", "label": "Lowest", "color": "#0088aa", "weight": 0},
    {"value": "low", "label": "Low", "color": "#00aa00", "weight": 1},
    {"value": "none", "label": "None", "color": "#cccccc", "weight": 2},
    {"value": "medium", "label": "Medium", "color": "#ffaa00", "weight": 3},
    {"value": "high", "label": "High", "color": "#ff6600", "weight": 4},
    {"value": "highest", "label": "Highest", "color": "#ff0000", "weight": 5},
]


def settings_public(vault):
    """Tasks' statuses and priorities in the shape the UI already uses for
    TaskNotes, so lists, the board and the editor work unchanged."""
    ts = vault.tasks_settings
    statuses = [{"value": st["symbol"], "label": st["name"], "color": TYPE_COLOR.get(st["type"], "#808080"),
                 "isCompleted": st["type"] in ("DONE", "CANCELLED"), "order": i, "type": st["type"]}
                for i, st in enumerate(ts.statuses) if st["type"] != "NON_TASK"]
    return {"statuses": statuses, "priorities": PRIORITIES, "tasksFolder": "", "archiveFolder": "",
            "taskTag": ts.globalFilter, "idMethod": "tasks", "defaultStatus": " ", "defaultPriority": "none",
            "savedViews": [], "readOnly": vault.settings.quarantined}


# ------------------------------------------------------- guarded line edits --

def locate(lines, line_no, raw):
    """Index of the task line the UI showed. Same place and same text: use it.
    Moved (lines added above) but unique: follow it. Otherwise: conflict."""
    from .vault import VaultError
    if 0 <= line_no < len(lines) and lines[line_no].rstrip("\r") == raw:
        return line_no
    hits = [i for i, l in enumerate(lines) if l.rstrip("\r") == raw]
    if len(hits) == 1:
        return hits[0]
    if not hits:
        raise VaultError("conflict", "that task line changed in the note since it was shown; reloaded")
    raise VaultError("conflict", "that task line appears %d times in the note; edit it in Obsidian" % len(hits))


def edit_lines(vault, rel, mutate):
    """Read rel, let mutate(lines) change the list of lines in place, write it
    back atomically (compare-and-swap on the whole file). Line endings are
    kept as the file has them."""
    from .vault import file_hash
    text = vault.read(rel)
    nl = "\r\n" if "\r\n" in text else "\n"
    lines = text.split(nl)
    result = mutate(lines)
    vault.write(rel, nl.join(lines), expect_hash=file_hash(text))
    return result


# ------------------------------------------------------------ daily notes ----

def daily_note_path(vault_path, day):
    """Today's daily note per Obsidian's core Daily Notes settings, or None if
    the format is one we can't render safely. (We never create daily notes:
    templates may need Obsidian.)"""
    try:
        with open(os.path.join(vault_path, ".obsidian", "daily-notes.json"), encoding="utf-8") as f:
            conf = json.load(f)
    except (OSError, ValueError):
        conf = {}
    fmt = conf.get("format") or "YYYY-MM-DD"
    folder = (conf.get("folder") or "").strip("/")
    y, m, d = day.split("-")
    tokens = {"YYYY": y, "MM": m, "DD": d}
    out, i = "", 0
    while i < len(fmt):
        for tok in ("YYYY", "MM", "DD"):
            if fmt.startswith(tok, i):
                out += tokens[tok]
                i += len(tok)
                break
        else:
            ch = fmt[i]
            if ch.isalpha():
                return None      # other moment tokens (dddd, MMM, ...): don't guess
            out += ch
            i += 1
    return (folder + "/" if folder else "") + out + ".md"


# ------------------------------------------------------- parse / serialise --
# Ported from Tasks' DefaultTaskSerializer / DataviewTaskSerializer.

TASK_RE = re.compile(r"^([\s\t>]*)([-*+]|[0-9]+[.)]) +\[(.)\] *(.*)$")
BLOCK_LINK_RE = re.compile(r" \^[a-zA-Z0-9-]+$")
HASHTAG_RE = re.compile(r"(^|\s)#[^ !@#$%^&*(),.?\":{}|<>]+")
HASHTAG_END_RE = re.compile(r"(^|\s)#[^ !@#$%^&*(),.?\":{}|<>]+$")
TASK_ID = r"[a-zA-Z0-9-_]+"
TASK_ID_SEQ = TASK_ID + r"( *, *" + TASK_ID + r" *)*"
VS16 = "️?"

PRIORITY_EMOJI = {"🔺": "highest", "⏫": "high", "🔼": "medium", "🔽": "low", "⏬": "lowest"}
EMOJI_FOR = {v: k for k, v in PRIORITY_EMOJI.items()}


def _f(symbols, value):
    src = symbols + VS16 + ((" *" + value) if value else "") + "$"
    return re.compile(src)


EMOJI = {
    "priority": _f("(🔺|⏫|🔼|🔽|⏬)", ""),
    "start": _f("🛫", r"([0-9]{4}-[0-9]{2}-[0-9]{2})"),
    "created": _f("➕", r"([0-9]{4}-[0-9]{2}-[0-9]{2})"),
    "scheduled": _f("(?:⏳|⌛)", r"([0-9]{4}-[0-9]{2}-[0-9]{2})"),
    "due": _f("(?:📅|📆|🗓)", r"([0-9]{4}-[0-9]{2}-[0-9]{2})"),
    "done": _f("✅", r"([0-9]{4}-[0-9]{2}-[0-9]{2})"),
    "cancelled": _f("❌", r"([0-9]{4}-[0-9]{2}-[0-9]{2})"),
    "recurrence": _f("🔁", r"([a-zA-Z0-9, !]+)"),
    "onCompletion": _f("🏁", r"([a-zA-Z]+)"),
    "dependsOn": _f("⛔", "(" + TASK_ID_SEQ + ")"),
    "id": _f("🆔", "(" + TASK_ID + ")"),
}
EMOJI_SYM = {"start": "🛫", "created": "➕", "scheduled": "⏳", "due": "📅", "done": "✅", "cancelled": "❌",
             "recurrence": "🔁", "onCompletion": "🏁", "dependsOn": "⛔", "id": "🆔"}


def _dv(inner):
    return re.compile(r"(?:(?=[^\]]+\])\[|(?=[^)]+\))\() *" + inner + r" *[)\]](?: *,)?$")


DATAVIEW = {
    "priority": _dv(r"priority:: *(highest|high|medium|low|lowest)"),
    "start": _dv(r"start:: *([0-9]{4}-[0-9]{2}-[0-9]{2})"),
    "created": _dv(r"created:: *([0-9]{4}-[0-9]{2}-[0-9]{2})"),
    "scheduled": _dv(r"scheduled:: *([0-9]{4}-[0-9]{2}-[0-9]{2})"),
    "due": _dv(r"due:: *([0-9]{4}-[0-9]{2}-[0-9]{2})"),
    "done": _dv(r"completion:: *([0-9]{4}-[0-9]{2}-[0-9]{2})"),
    "cancelled": _dv(r"cancelled:: *([0-9]{4}-[0-9]{2}-[0-9]{2})"),
    "recurrence": _dv(r"repeat:: *([a-zA-Z0-9, !]+)"),
    "onCompletion": _dv(r"onCompletion:: *([a-zA-Z]+)"),
    "dependsOn": _dv("dependsOn:: *(" + TASK_ID_SEQ + ")"),
    "id": _dv("id:: *(" + TASK_ID + ")"),
}
DV_SYM = {"start": "start::", "created": "created::", "scheduled": "scheduled::", "due": "due::", "done": "completion::",
          "cancelled": "cancelled::", "recurrence": "repeat::", "onCompletion": "onCompletion::",
          "dependsOn": "dependsOn::", "id": "id::"}

# Extraction order inside each pass (Tasks' deserialize loop).
PASS_ORDER = ["priority", "done", "cancelled", "due", "scheduled", "start", "created", "recurrence",
              "onCompletion", "tags", "id", "dependsOn"]
# Write order (TaskLayoutComponent minus description/blockLink).
WRITE_ORDER = ["id", "dependsOn", "priority", "recurrence", "onCompletion", "created", "start", "scheduled",
               "due", "cancelled", "done"]


def parse_line(line, ts):
    """A task line -> dict of its parts, or None if it isn't a task (or the
    global filter excludes it)."""
    m = TASK_RE.match(line.rstrip("\r"))
    if not m:
        return None
    indent, marker, sym, rest = m.group(1), m.group(2), m.group(3), m.group(4)
    raw_rest = rest
    hard_break = ""
    hb = re.search(r" {2,}$", raw_rest)
    if hb:
        hard_break = hb.group(0)
    body = rest.strip()
    block = ""
    bm = BLOCK_LINK_RE.search(body)
    if bm:
        block = bm.group(0)
        body = BLOCK_LINK_RE.sub("", body).strip()
    gf = ts.globalFilter or ""
    if gf and gf not in body:
        return None
    regs = DATAVIEW if ts.taskFormat == "dataview" else EMOJI
    f = {"priority": "none", "start": "", "created": "", "scheduled": "", "due": "", "done": "", "cancelled": "",
         "recurrence": "", "onCompletion": "", "id": "", "dependsOn": []}
    trailing = ""
    runs = 0
    while True:
        matched = False
        for name in PASS_ORDER:
            if name == "tags":
                mm = HASHTAG_END_RE.search(body)
                if mm:
                    tag = mm.group(0).strip()
                    trailing = tag if not trailing else tag + " " + trailing
                    body = body[:mm.start()].strip()
                    matched = True
                continue
            mm = regs[name].search(body)
            if not mm:
                continue
            if name == "priority":
                v = mm.group(1)
                f["priority"] = PRIORITY_EMOJI.get(v, v)
            elif name == "dependsOn":
                f["dependsOn"] = [x for x in mm.group(1).replace(" ", "").split(",") if x]
            elif name == "onCompletion":
                v = mm.group(1).strip().lower()
                f[name] = v if v in ("keep", "delete") else ""
            elif name in ("recurrence", "id"):
                f[name] = mm.group(1).strip()
            else:
                f[name] = mm.group(1)
            body = body[:mm.start()].strip()
            matched = True
        runs += 1
        if not matched or runs > 20:
            break
    if trailing:
        body = body + (" " if body else "") + trailing
    tags = [t.strip() for t in (x.group(0) for x in HASHTAG_RE.finditer(body))]
    tags = [t for t in tags if t != gf]
    f.update({"indent": indent, "marker": marker, "status": sym, "description": body, "blockLink": block,
              "hardBreak": hard_break, "tags": tags})
    return f


def _valid_date(v):
    try:
        _date.fromisoformat(v)
        return v
    except ValueError:
        return "Invalid date"      # what moment prints for e.g. 2024-02-30


def _rule_text(text):
    """Tasks re-renders the 🔁 rule on every write (rrule.js toText), and drops
    one it can't read."""
    from . import rrule_text
    r = rrule_text.parse(text)
    return rrule_text.to_text(r) if r else ""


def serialize(p, ts):
    """The parts -> a line, exactly as Tasks writes it."""
    dv = ts.taskFormat == "dataview"
    out = p["description"]
    for name in WRITE_ORDER:
        v = p.get(name)
        if name == "recurrence" and v:
            v = _rule_text(v)
        elif name in ("created", "start", "scheduled", "due", "cancelled", "done") and v:
            v = _valid_date(v)
        if not v or (name == "priority" and v == "none"):
            continue
        if name == "priority":
            piece = ("priority:: " + v) if dv else EMOJI_FOR[v]
        elif name == "dependsOn":
            piece = (DV_SYM if dv else EMOJI_SYM)[name] + " " + ",".join(v)
        elif name == "onCompletion" and v.lower() == "ignore":
            continue
        else:
            piece = (DV_SYM if dv else EMOJI_SYM)[name] + " " + v
        out += ("  [" + piece + "]") if dv else (" " + piece)
    out += p.get("blockLink") or ""
    return "%s%s [%s] %s%s" % (p["indent"], p["marker"], p["status"], out, p.get("hardBreak") or "")


# ---------------------------------------------------------- task records ----

def _title(p, ts):
    """Description for display: global filter removed (if Tasks is set to
    hide it) and trailing tags dropped (they're shown as chips)."""
    d = p["description"]
    gf = ts.globalFilter or ""
    if gf and ts.removeGlobalFilter:
        d = re.sub(r"(^|\s)" + re.escape(gf) + r"($|\s)", " ", d).strip()
    while True:
        m = HASHTAG_END_RE.search(d)
        if not m or not d[:m.start()].strip():
            break
        d = d[:m.start()].strip()
    return d or p["description"]


def build(vault, rel, n, line, p, ids):
    ts = vault.tasks_settings
    st = ts.status(p["status"])
    done = st["type"] in ("DONE", "CANCELLED")
    rec = p["recurrence"]
    deps = []
    for d in p["dependsOn"]:
        target = ids.get(d)
        if target:
            deps.append({"title": target["title"], "path": target["path"], "done": target["done"]})
        else:
            deps.append({"title": d, "path": "", "done": False})
    e = vault.entries.get(rel)
    return {
        "path": key(rel, n), "file": rel, "line": n, "raw": {}, "rawLine": line,
        "expect": {"line": line},
        "title": _title(p, ts), "description": p["description"],
        "status": p["status"], "statusType": st["type"], "done": done, "archived": False, "error": None,
        "priority": p["priority"], "due": p["due"], "scheduled": p["scheduled"], "start": p["start"],
        "created": p["created"], "dateCreated": p["created"], "dateModified": "",
        "completedDate": p["done"] or p["cancelled"], "cancelledDate": p["cancelled"],
        "recurring": bool(rec), "recurrence": rec, "recurrenceText": rec[:1].upper() + rec[1:] if rec else "",
        "whenDone": rec.endswith("when done"), "occurrence": "", "completeInstances": [], "skippedInstances": [],
        "tags": [t.lstrip("#") for t in p["tags"]], "allTags": p["tags"], "contexts": [], "projects": [],
        "projectsRaw": [], "notes": [os.path.basename(rel)[:-3]],
        "taskId": p["id"], "dependsOn": p["dependsOn"], "blockedBy": deps,
        "blocked": any(not b["done"] for b in deps if b["path"]),
        "onCompletion": p["onCompletion"], "props": {}, "mtime": (e.mtime // 1_000_000) if e else 0,
        # For ```tasks queries (app/tasksquery.js)
        "statusName": st["name"], "doneDate": p["done"], "indentation": p["indent"],
        "ruleText": _query_rule_text(rec),
        "heading": (e.meta.get(n) or {}).get("heading", "") if e else "",
        "parentLine": (e.meta.get(n) or {}).get("parent") if e else None,
        "source": "tasks",
    }


def _query_rule_text(text):
    """recurrence.toText() as a query sees it: the normalised rule, or "" if
    Tasks can't read it (then the task isn't recurring at all)."""
    if not text:
        return ""
    from . import rrule_text
    r = rrule_text.parse(text)
    return rrule_text.to_text(r) if r else ""


def note_props(text):
    """A note's properties as Tasks' TasksFile.frontmatter sees them, for
    query file defaults (TQ_*) and {{query.file.property('x')}}. tags is
    always there, as a list of "#tag" (Obsidian's parseFrontMatterTags)."""
    from .frontmatter import Note
    try:
        data = Note(text).data() if text.lstrip("\ufeff").startswith("---") else {}
    except Exception:
        data = {}
    out = json.loads(json.dumps(data or {}, default=str))
    raw = out.get("tags", out.get("tag"))
    if isinstance(raw, str):
        raw = [t for t in re.split(r"[,\s]+", raw) if t]
    tags = ["#" + str(t).lstrip("#") for t in (raw or []) if t is not None and str(t).strip()]
    out = {k: v for k, v in out.items() if k not in ("tags", "tag")}
    out["tags"] = tags
    return out


def all_queries(vault):
    """Every ```tasks block in the vault, for the sidebar's Queries."""
    out = []
    for rel, e in sorted(vault.entries.items()):
        for n, source, heading in e.queries:
            note = os.path.basename(rel)[:-3]
            out.append({"id": "query:%s%s%d" % (rel, KEY_SEP, n), "file": rel, "line": n, "source": source,
                        "note": note, "name": heading or note, "props": e.props})
    return out


def _parsed(vault):
    ts = vault.tasks_settings
    out = []
    for rel, e in vault.entries.items():
        for n, line in e.inline:
            p = parse_line(line, ts)
            if p:
                out.append((rel, n, line, p))
    return out


def all_tasks(vault, day):
    parsed = _parsed(vault)
    # First pass for ids (dependencies point at 🆔 values), then the records.
    ids = {}
    for rel, n, line, p in parsed:
        if p["id"]:
            st = vault.tasks_settings.status(p["status"])
            ids[p["id"]] = {"title": _title(p, vault.tasks_settings), "path": key(rel, n),
                            "done": st["type"] in ("DONE", "CANCELLED")}
    tasks = [build(vault, rel, n, line, p, ids) for rel, n, line, p in parsed]
    vault.inline_keys = {}
    for t in tasks:
        vault.inline_keys.setdefault(t["file"], set()).add(t["path"])
    return tasks


def delta(vault, changed, removed, day):
    """Live update after files changed: their old keys out, new tasks in.
    (Dependencies across files are re-resolved from the whole vault.)"""
    before = getattr(vault, "inline_keys", {})
    gone = set()
    for rel in list(changed) + list(removed):
        gone |= before.get(rel, set())
    tasks = all_tasks(vault, day)
    files = set(changed)
    up = [t for t in tasks if t["file"] in files]
    gone -= {t["path"] for t in up}
    return up, sorted(gone)



# ------------------------------------------------------------- completing --
# Task.handleNewStatus + Recurrence/Occurrence + handleOnCompletion.

from datetime import date as _date, datetime as _dt, timedelta as _td  # noqa: E402


def _d(s):
    try:
        return _date.fromisoformat(s) if s else None
    except ValueError:
        return None


def set_status(p, ts, new_sym, today):
    """[lines' parts] after moving task p to status new_sym (Tasks' order:
    [next occurrence, this task], or reversed with recurrenceOnNextLine)."""
    from . import rrule_text
    old = ts.status(p["status"])
    new = ts.status(new_sym)
    if new["symbol"] == old["symbol"]:
        return [p]

    def new_date(kind, old_date, enabled):
        if new["type"] == kind:
            if old["type"] != kind:
                return today if enabled else ""
            return old_date
        return ""

    toggled = dict(p)
    toggled["status"] = new["symbol"]
    toggled["done"] = new_date("DONE", p["done"], ts.setDoneDate)
    toggled["cancelled"] = new_date("CANCELLED", p["cancelled"], ts.setCancelledDate)
    out = [toggled]
    if new["type"] == "DONE" and old["type"] != "DONE" and p["recurrence"]:
        nxt = next_occurrence(p, ts, today)
        if nxt is not None:
            n = dict(p)
            n.update(nxt)
            n["status"] = ts.next_recurrence_status(new)["symbol"]
            n["_isNext"] = True
            n.update({"blockLink": "", "id": "", "dependsOn": [], "done": "", "cancelled": "",
                      "created": today if ts.setCreatedDate else ""})
            out = [n, toggled]
    # 🏁 delete: drop the completed instance (only when it became DONE)
    if p.get("onCompletion") == "delete" and new["type"] == "DONE" and old["type"] != "DONE":
        out = [x for x in out if x is not toggled]
    if ts.recurrenceOnNextLine:
        out.reverse()
    return out


def toggle(p, ts, today):
    return set_status(p, ts, ts.next_status(ts.status(p["status"]))["symbol"], today)


def toggle_lines(line, ts, today):
    p = parse_line(line, ts)
    if not p:
        return [line]
    return [serialize(x, ts) for x in toggle(p, ts, today)]


def reference_date(p, ts):
    order = ["due", "start", "scheduled"] if ts.removeScheduledDateOnRecurrence else ["due", "scheduled", "start"]
    for k in order:
        if p.get(k):
            return _d(p[k])
    return None


def next_occurrence(p, ts, today):
    """{start, scheduled, due} for the next occurrence, or None if the rule
    has no further dates (or doesn't parse)."""
    from . import rrule_text
    rule = rrule_text.parse(p["recurrence"])
    if rule is None:
        return None
    ref = reference_date(p, ts)
    when_done = rule["whenDone"]
    base = _d(today) if (when_done or ref is None) else ref
    nxt = rrule_text.next_after(rule, base)
    if nxt is None:
        return None
    if ref is None:
        return {"start": "", "scheduled": "", "due": ""}
    shift = nxt - ref
    remove_sched = ts.removeScheduledDateOnRecurrence and bool(p["start"] or p["due"])
    out = {}
    for k in ("start", "scheduled", "due"):
        if not p[k] or (k == "scheduled" and remove_sched):
            out[k] = ""
        else:
            out[k] = (_d(p[k]) + shift).isoformat()
    return out


# ---------------------------------------------------------------- ops -------
# Same request shapes as the TaskNotes ops (core/omaforge/tasks.py), so the
# UI doesn't care which format it's talking to. `path` is a line key.

def _today():
    return _date.today().isoformat()


def _target(vault, req):
    from .vault import VaultError
    vault.check_writable()
    rel, n = split_key(req.get("path") or "")
    if rel is None:
        raise VaultError("bad-path", "not a Tasks line: %r" % req.get("path"))
    shown = (req.get("expect") or {}).get("line")
    if shown is None:
        e = vault.entries.get(rel)
        shown = dict(e.inline).get(n) if e else None
    if shown is None:
        raise VaultError("missing", "that task line is gone (edited elsewhere?)")
    return rel, n, shown


def _result(vault, rel, day, focus_line=None):
    """Refresh rel's entry and send its tasks back (old keys removed)."""
    vault.scan()
    up, gone = delta(vault, [rel], [], day)
    task = None
    if focus_line is not None:
        task = next((t for t in up if t["line"] == focus_line), None)
    return {"task": task, "path": task["path"] if task else None, "_upsert": up, "_remove": gone}


def _replace(vault, req, day, change):
    """change(parts) -> list of parts to put where the line was. The UI keeps
    following this task (not a newly added next occurrence)."""
    from .vault import VaultError
    rel, n, shown = _target(vault, req)
    ts = vault.tasks_settings

    def mutate(lines):
        i = locate(lines, n, shown)
        p = parse_line(lines[i], ts)
        if p is None:
            raise VaultError("conflict", "that line isn't a task any more")
        new = change(p)
        lines[i:i + 1] = [serialize(x, ts) for x in new]
        keep = next((k for k, x in enumerate(new) if not x.get("_isNext")), None)
        return None if keep is None else i + keep

    focus = edit_lines(vault, rel, mutate)
    return _result(vault, rel, day, focus)


def op_toggle(vault, req, day):
    ts = vault.tasks_settings
    return _replace(vault, req, day, lambda p: toggle(p, ts, _today()))


def op_set_status(vault, req, day):
    from .vault import VaultError
    ts = vault.tasks_settings
    sym = str(req.get("status", ""))
    if len(sym) != 1:
        raise VaultError("bad-status", "a Tasks status is one character")
    return _replace(vault, req, day, lambda p: set_status(p, ts, sym, _today()))


def _tasks_by_key(vault, day):
    return {t["path"]: t for t in all_tasks(vault, day)}


def op_update(vault, req, day):
    """Edit fields of one line. Keys as the UI sends them: title, priority,
    due, scheduled, start, created, doneDate, cancelledDate, recurrence (an
    RRULE from the repeat box, or ""), whenDone, tags, blockedBy ([{path}] /
    [{uid}] entries). Setting a done/cancelled date leaves the status alone,
    as Tasks' column-view drops do."""
    from . import rrule_text
    from .vault import VaultError
    ts = vault.tasks_settings
    fields = dict(req.get("set") or {})
    extra_writes = []
    # Give any new blocker its 🆔 first, before this line is read for editing
    # (the blocker may be in the same note).
    if "blockedBy" in fields:
        resolved = []
        for b in fields["blockedBy"] or []:
            if isinstance(b, dict) and b.get("path"):
                resolved.append({"uid": _ensure_id(vault, b["path"], day, extra_writes)})
            else:
                resolved.append(b)
        fields["blockedBy"] = resolved

    def change(p):
        for name, value in fields.items():
            if name == "title":
                v = re.sub(r"\s+", " ", str(value)).strip()
                if not v:
                    raise VaultError("bad-title", "a task needs some text")
                # Keep trailing tags that the title box doesn't show.
                tags = " ".join(t for t in p["tags"] if t not in v.split())
                p["description"] = (v + (" " + tags if tags else "")).strip()
            elif name == "priority":
                if value not in ("highest", "high", "medium", "none", "low", "lowest"):
                    raise VaultError("bad-field", "unknown priority %r" % value)
                p["priority"] = value
            elif name in ("due", "scheduled", "start", "created", "doneDate", "cancelledDate"):
                v = str(value or "")[:10]
                if v and not re.match(r"^\d{4}-\d{2}-\d{2}$", v):
                    raise VaultError("bad-field", "dates look like 2026-10-09")
                p[{"doneDate": "done", "cancelledDate": "cancelled"}.get(name, name)] = v
            elif name == "recurrence":
                v = str(value or "").strip()
                if not v:
                    p["recurrence"] = ""
                else:
                    rule = rrule_text.from_rrule(v)
                    if rule is None:
                        raise VaultError("bad-field", "Tasks can't express that repeat")
                    rule["whenDone"] = p["recurrence"].endswith("when done")
                    p["recurrence"] = rrule_text.to_text(rule)
            elif name == "whenDone":
                if not p["recurrence"]:
                    raise VaultError("bad-field", "set a repeat first")
                base = re.sub(r"\s+when done$", "", p["recurrence"])
                p["recurrence"] = base + (" when done" if value else "")
            elif name == "tags":
                want = ["#" + str(t).lstrip("#") for t in (value or []) if str(t).strip()]
                d = p["description"]
                for t in p["tags"]:
                    if t not in want:
                        d = re.sub(r"(^|\s)" + re.escape(t) + r"(?=$|\s)", " ", d)
                d = re.sub(r"\s+", " ", d).strip()
                for t in want:
                    if t not in p["tags"]:
                        d += " " + t
                p["description"] = d.strip()
            elif name == "blockedBy":
                deps = []
                for b in value or []:
                    if isinstance(b, dict) and b.get("path"):
                        deps.append(_ensure_id(vault, b["path"], day, extra_writes))
                    elif isinstance(b, dict) and b.get("uid"):
                        deps.append(str(b["uid"]))
                p["dependsOn"] = [d for d in deps if d]
            else:
                raise VaultError("bad-field", "can't edit %r in Tasks mode" % name)
        return [p]

    r = _replace(vault, req, day, change)
    # Blockers in other notes changed too (they got an id): send those notes' tasks.
    for rel in set(extra_writes) - {r["task"]["file"] if r.get("task") else None}:
        extra = _result(vault, rel, day)
        r["_upsert"] += extra["_upsert"]
        r["_remove"] += extra["_remove"]
    return r


def _ensure_id(vault, key_path, day, writes):
    """A dependency needs the blocker to have a 🆔. Give it one if missing
    (6 random lowercase letters/digits, like Tasks), and return it."""
    import random
    import string
    from .vault import VaultError
    ts = vault.tasks_settings
    rel, n = split_key(key_path)
    e = vault.entries.get(rel)
    shown = dict(e.inline).get(n) if e else None
    if shown is None:
        raise VaultError("missing", "the blocking task's line is gone")
    p = parse_line(shown, ts)
    if p and p["id"]:
        return p["id"]
    existing = {t["taskId"] for t in all_tasks(vault, day) if t["taskId"]}
    new_id = None
    while not new_id or new_id in existing:
        new_id = "".join(random.choice(string.ascii_lowercase + string.digits) for _ in range(6))

    def mutate(lines):
        i = locate(lines, n, shown)
        q = parse_line(lines[i], ts)
        q["id"] = new_id
        lines[i] = serialize(q, ts)
    edit_lines(vault, rel, mutate)
    writes.append(rel)
    return new_id


def op_delete(vault, req, day):
    rel, n, shown = _target(vault, req)

    def mutate(lines):
        i = locate(lines, n, shown)
        del lines[i]
    edit_lines(vault, rel, mutate)
    r = _result(vault, rel, day)
    r["trashedTo"] = "nowhere (the line was removed from %s)" % rel
    return r


def op_duplicate(vault, req, day):
    """A copy just below, open and without completion dates, id or block link."""
    ts = vault.tasks_settings
    rel, n, shown = _target(vault, req)

    def mutate(lines):
        i = locate(lines, n, shown)
        p = parse_line(lines[i], ts)
        q = dict(p)
        q.update({"status": " " if ts.status(p["status"])["type"] in ("DONE", "CANCELLED") else p["status"],
                  "done": "", "cancelled": "", "id": "", "blockLink": "",
                  "created": _today() if ts.setCreatedDate else p["created"]})
        lines.insert(i + 1, serialize(q, ts))
        return i + 1
    focus = edit_lines(vault, rel, mutate)
    return _result(vault, rel, day, focus)


def inbox_path(vault, day):
    """Where a new task goes: today's daily note if wanted and it exists,
    otherwise the inbox note (created if missing)."""
    from .notify import format_prefs
    prefs = format_prefs()["tasksInbox"]
    if prefs["target"] == "daily":
        dn = daily_note_path(vault.path, day)
        if dn and os.path.isfile(vault.abs(dn)):
            return dn
    return str(prefs["note"]).strip().lstrip("/")


def op_create(vault, req, day):
    from .vault import VaultError
    ts = vault.tasks_settings
    vault.check_writable()
    fields = req.get("fields") or {}
    title = re.sub(r"\s+", " ", str(fields.get("title") or "")).strip()
    if not title:
        raise VaultError("bad-title", "a task needs some text")
    gf = ts.globalFilter or ""
    desc = title if (not gf or gf in title) else gf + " " + title
    tags = " ".join("#" + str(t).lstrip("#") for t in (fields.get("tags") or []))
    p = {"indent": "", "marker": "-", "status": " ", "description": (desc + (" " + tags if tags else "")).strip(),
         "priority": fields.get("priority") or "none", "start": "", "created": _today() if ts.setCreatedDate else "",
         "scheduled": str(fields.get("scheduled") or "")[:10], "due": str(fields.get("due") or "")[:10],
         "done": "", "cancelled": "", "recurrence": "", "onCompletion": "", "id": "", "dependsOn": [],
         "blockLink": "", "hardBreak": "", "tags": []}
    line = serialize(p, ts)
    rel = str(fields.get("file") or "").strip() or inbox_path(vault, day)
    if not rel.endswith(".md"):
        raise VaultError("bad-path", "tasks go in a .md note")
    full = vault.abs(rel)
    if not os.path.exists(full):
        vault.write(rel, line + "\n", create=True)
        n = 0
    else:
        def mutate(lines):
            # Append after the last non-empty line, keeping a final newline.
            while lines and lines[-1] == "":
                lines.pop()
            lines.append(line)
            lines.append("")
            return len(lines) - 2
        n = edit_lines(vault, rel, mutate)
    r = _result(vault, rel, day, n)
    r["note"] = "Added to %s" % rel
    return r


def op_body(vault, req, day):
    return {"body": "", "hash": ""}


OPS = {
    "update": op_update, "setStatus": op_set_status, "toggleComplete": op_toggle, "delete": op_delete,
    "duplicate": op_duplicate, "create": op_create, "body": op_body,
}
