"""Obsidian Bases (.base) views: parse, validate, generate.

Reading: every task-related .base file in the vault is parsed; each view's
filters, sort and groupBy become a small JSON syntax tree that the UI
evaluates live (app/bases.js). Formulas referenced as `formula.x` are
inlined. Anything outside the supported subset (e.g. `this`, which depends
on the note Obsidian has open) marks the view unsupported, with a reason --
we never show a silently-wrong result.

Writing: OmaForge's view editor produces a simple model (conditions, sort,
group, layout) that becomes one .base file per view. A file is editable in
OmaForge only if regenerating it from the model reproduces it exactly, so
hand-built bases (formulas, several views) are never rewritten.
"""
import json
import os
import re

import yaml

from .frontmatter import _Loader

# ---------------------------------------------------------------- parser ----


class Unsupported(Exception):
    pass


TOKEN = re.compile(r"""
    (?P<ws>\s+)
  | (?P<num>\d+(?:\.\d+)?)
  | (?P<str>"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')
  | (?P<id>[A-Za-z_][A-Za-z0-9_]*)
  | (?P<op>&&|\|\||==|!=|<=|>=|[<>+\-*/%!().,\[\]])
""", re.VERBOSE)

BINARY = {"||": 1, "&&": 2, "==": 3, "!=": 3, "<": 4, "<=": 4, ">": 4, ">=": 4,
          "+": 5, "-": 5, "*": 6, "/": 6, "%": 6}


def tokenize(src):
    out, i = [], 0
    while i < len(src):
        m = TOKEN.match(src, i)
        if not m:
            raise Unsupported("can't read %r" % src[i:i + 12])
        i = m.end()
        kind = m.lastgroup
        if kind == "ws":
            continue
        v = m.group(kind)
        if kind == "num":
            out.append(("lit", float(v) if "." in v else int(v)))
        elif kind == "str":
            out.append(("lit", json.loads('"%s"' % v[1:-1].replace('"', '\\"')) if v[0] == "'" else json.loads(v)))
        elif kind == "id":
            out.append(("lit", True) if v == "true" else ("lit", False) if v == "false"
                       else ("lit", None) if v == "null" else ("id", v))
        else:
            out.append(("op", v))
    out.append(("end", None))
    return out


class Parser:
    def __init__(self, src):
        self.t = tokenize(src)
        self.i = 0

    def peek(self):
        return self.t[self.i]

    def take(self, kind=None, val=None):
        tok = self.t[self.i]
        if (kind and tok[0] != kind) or (val is not None and tok[1] != val):
            raise Unsupported("expected %s near %r" % (val or kind, tok[1]))
        self.i += 1
        return tok

    def parse(self):
        e = self.expr(0)
        self.take("end")
        return e

    def expr(self, min_prec):
        left = self.unary()
        while True:
            kind, v = self.peek()
            if kind != "op" or v not in BINARY or BINARY[v] < min_prec:
                return left
            self.i += 1
            right = self.expr(BINARY[v] + 1)
            left = ["bin", v, left, right]

    def unary(self):
        kind, v = self.peek()
        if kind == "op" and v in ("!", "-"):
            self.i += 1
            return ["un", v, self.unary()]
        return self.postfix(self.primary())

    def primary(self):
        kind, v = self.take()
        if kind == "lit":
            return ["lit", v]
        if kind == "id":
            return ["id", v]
        if kind == "op" and v == "(":
            e = self.expr(0)
            self.take("op", ")")
            return e
        if kind == "op" and v == "[":
            items = []
            if self.peek() != ("op", "]"):
                while True:
                    items.append(self.expr(0))
                    if self.peek() == ("op", ","):
                        self.i += 1
                        continue
                    break
            self.take("op", "]")
            return ["arr", items]
        raise Unsupported("unexpected %r" % v)

    def postfix(self, e):
        while True:
            kind, v = self.peek()
            if kind == "op" and v == ".":
                self.i += 1
                e = ["mem", e, self.take("id")[1]]
            elif kind == "op" and v == "[":
                self.i += 1
                key = self.expr(0)
                self.take("op", "]")
                e = ["idx", e, key]
            elif kind == "op" and v == "(":
                self.i += 1
                args = []
                if self.peek() != ("op", ")"):
                    while True:
                        args.append(self.expr(0))
                        if self.peek() == ("op", ","):
                            self.i += 1
                            continue
                        break
                self.take("op", ")")
                e = ["call", e, args]
            else:
                return e


# ------------------------------------------------------------ validation ----
# Turn the raw parse into the evaluator's vocabulary, rejecting anything the
# evaluator (app/bases.js) doesn't implement.

FUNCTIONS = {"date", "today", "now", "list", "link", "if", "number", "min", "max", "file", "string"}
METHODS = {"isEmpty", "contains", "containsAny", "containsAll", "date", "format", "floor", "round",
           "ceil", "abs", "lower", "upper", "startsWith", "endsWith", "filter", "map", "reduce",
           "toString", "isTruthy", "trim", "join", "slice", "unique", "sort", "reverse", "flat", "length"}
FILE_FIELDS = {"name", "basename", "path", "folder", "ext", "tags", "properties", "ctime", "mtime"}
FILE_METHODS = {"hasTag", "hasProperty", "inFolder", "asLink"}
LAMBDA_VARS = {"value", "index", "acc"}


class Compiler:
    def __init__(self, formulas):
        self.formulas = formulas or {}
        self.stack = []

    def compile(self, src):
        if re.search(r"\bthis\b", re.sub(r'"(?:[^"\\]|\\.)*"', "", str(src))):
            raise Unsupported("depends on the note open in Obsidian (this)")
        return self.node(Parser(str(src)).parse(), 0)

    def formula(self, name):
        if name not in self.formulas:
            raise Unsupported("unknown formula %r" % name)
        if name in self.stack:
            raise Unsupported("formula %r refers to itself" % name)
        self.stack.append(name)
        try:
            return self.node(Parser(str(self.formulas[name])).parse(), 0)
        finally:
            self.stack.pop()

    def node(self, n, lam):
        t = n[0]
        if t == "lit":
            return n
        if t == "arr":
            return ["arr", [self.node(x, lam) for x in n[1]]]
        if t == "id":
            name = n[1]
            if name == "this":
                raise Unsupported("depends on the note open in Obsidian (this)")
            if name in LAMBDA_VARS:
                if not lam:
                    raise Unsupported("%r outside filter/map" % name)
                return ["var", name]
            if name in ("file", "note", "formula"):
                raise Unsupported("bare %r" % name)
            return ["prop", name]
        if t == "un":
            return ["un", n[1], self.node(n[2], lam)]
        if t == "bin":
            return ["bin", n[1], self.node(n[2], lam), self.node(n[3], lam)]
        if t == "idx":
            base = n[1]
            if base == ["id", "note"] and n[2][0] == "lit":
                return ["prop", str(n[2][1])]
            return ["idx", self.node(base, lam), self.node(n[2], lam)]
        if t == "mem":
            base, name = n[1], n[2]
            if base == ["id", "note"]:
                return ["prop", name]
            if base == ["id", "formula"]:
                return self.formula(name)
            if base == ["id", "file"]:
                if name not in FILE_FIELDS:
                    raise Unsupported("file.%s" % name)
                return ["file", name]
            if base == ["id", "this"]:
                raise Unsupported("depends on the note open in Obsidian (this)")
            if name == "length":
                return ["m", "length", self.node(base, lam), []]
            return ["get", self.node(base, lam), name]
        if t == "call":
            callee, args = n[1], n[2]
            if callee[0] == "id":
                fn = callee[1]
                if fn not in FUNCTIONS:
                    raise Unsupported("function %s()" % fn)
                return ["fn", fn, [self.node(a, lam) for a in args]]
            if callee[0] == "mem":
                base, m = callee[1], callee[2]
                if base == ["id", "file"]:
                    if m not in FILE_METHODS:
                        raise Unsupported("file.%s()" % m)
                    return ["fn", "file." + m, [self.node(a, lam) for a in args]]
                if m not in METHODS:
                    raise Unsupported(".%s()" % m)
                inner = lam + 1 if m in ("filter", "map", "reduce") else lam
                return ["m", m, self.node(base, lam), [self.node(a, inner) for a in args]]
            raise Unsupported("call of an expression")
        raise Unsupported("unknown node %r" % t)


def compile_filter(f, comp):
    """Filters are a string, or {and|or|not: [filters]}."""
    if f is None:
        return None
    if isinstance(f, str):
        return comp.compile(f)
    if isinstance(f, dict) and len(f) == 1:
        (k, v), = f.items()
        if k in ("and", "or", "not") and isinstance(v, list):
            kids = [compile_filter(x, comp) for x in v]
            return [k, [x for x in kids if x is not None]]
    raise Unsupported("filter shape %r" % (f,))


# ------------------------------------------------------------- discovery ----

LAYOUT = {"tasknotesTaskList": "list", "table": "list", "list": "list", "cards": "list",
          "tasknotesKanban": "board", "tasknotesCalendar": "dates", "tasknotesMiniCalendar": "dates"}


def load_base(text):
    d = yaml.load(text, Loader=_Loader)
    if not isinstance(d, dict):
        raise Unsupported("not a mapping")
    return d


def mentions_task_tag(obj, tag):
    s = json.dumps(obj)
    return bool(re.search(r'hasTag\(\\"#?%s(?:/[^\\"]*)?\\"' % re.escape(tag), s, re.IGNORECASE))


def sort_ast(item, comp):
    prop = item.get("property") or item.get("column")
    if not prop:
        return None
    return {"ast": comp.compile(prop), "dir": "desc" if str(item.get("direction", "ASC")).upper() == "DESC" else "asc",
            "key": prop}


def views_in(vault, rel, text):
    """-> list of view descriptors for one .base file (may be empty)."""
    tag = vault.settings.task_tag
    try:
        d = load_base(text)
    except (yaml.YAMLError, Unsupported) as e:
        return [{"id": "base:%s::" % rel, "file": rel, "name": os.path.basename(rel)[:-5],
                 "unsupported": "unreadable .base file (%s)" % str(e).split("\n")[0]}]
    views = d.get("views") or []
    top = d.get("filters")
    out = []
    try:
        model_by_name = editable_models(vault, rel, d)
    except Exception:  # a file we can't map is simply not editable
        model_by_name = {}
    for v in views:
        if not isinstance(v, dict):
            continue
        layout = LAYOUT.get(v.get("type"))
        if layout is None:
            continue  # workflows, pomodoro tables of other notes, ...
        if not (mentions_task_tag(top, tag) or mentions_task_tag(v.get("filters"), tag)):
            continue  # not a task view
        name = str(v.get("name") or "View")
        desc = {"id": "base:%s::%s" % (rel, name), "file": rel, "fileName": os.path.basename(rel)[:-5],
                "name": name, "layout": layout, "unsupported": "", "type": v.get("type")}
        comp = Compiler(d.get("formulas"))
        try:
            parts = [compile_filter(top, comp), compile_filter(v.get("filters"), comp)]
            desc["filter"] = ["and", [p for p in parts if p is not None]]
            desc["sort"] = [s for s in (sort_ast(x, comp) for x in (v.get("sort") or []) if isinstance(x, dict)) if s]
            g = v.get("groupBy")
            if isinstance(g, dict) and g.get("property"):
                desc["group"] = sort_ast(g, comp)
            elif layout == "board":
                desc["group"] = {"ast": ["prop", vault.settings.f("status")], "dir": "asc", "key": "status"}
            if layout == "dates":
                prop = (v.get("startDateProperty") or v.get("dateProperty") or "").replace("note.", "")
                prop = {"file.ctime": "dateCreated", "file.mtime": "dateModified"}.get(prop, prop)
                desc["dateProperty"] = prop if prop in ("due", "scheduled", "dateCreated", "dateModified", "completedDate") else ""
        except Unsupported as e:
            if "(this)" in str(e):
                continue  # only meaningful beside a note open in Obsidian
            desc["unsupported"] = str(e)
        if name in model_by_name:
            desc["model"] = model_by_name[name]
        out.append(desc)
    return out


def all_views(vault):
    out = []
    for full in walk_bases(vault):
        rel = vault.rel(full)
        try:
            with open(full, encoding="utf-8") as f:
                text = f.read()
        except OSError:
            continue
        out.extend(views_in(vault, rel, text))
    out.sort(key=lambda v: (not v["file"].startswith(vault.settings.views_folder + "/"), v["file"].lower()))
    return out


def walk_bases(vault):
    for dirpath, dirnames, filenames in os.walk(vault.path):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for fn in filenames:
            if fn.endswith(".base") and not fn.startswith("."):
                yield os.path.join(dirpath, fn)


def bases_signature(vault):
    """Cheap change detector for the poll loop."""
    sig = []
    for full in walk_bases(vault):
        try:
            st = os.stat(full)
            sig.append((full, st.st_mtime_ns, st.st_size))
        except OSError:
            pass
    return sorted(sig)


# ------------------------------------------------------- editor <-> YAML ----
# The model the view editor edits:
#   {name, match: all|any, conditions: [{field, op, value}], sort: {field, dir},
#    group: field|"none", layout: list|board}
# plus, for views copied from hand-made ones (see closest_model):
#   a condition {field: "raw", op: "raw", value: <expression or and/or group>,
#   label} kept exactly as written; sort {field: "raw", raw: [original sort
#   entries]}; groupDir "DESC"; formulas {name: expression}.

DATE_FIELDS = ("due", "scheduled", "completedDate")
ORDER = ["status", "priority", "due", "scheduled", "projects", "contexts", "file.tags", "file.name"]


def q(s):
    return json.dumps(str(s), ensure_ascii=False)


def date_value(v):
    """'today' | '+N' | '-N' | 'YYYY-MM-DD' -> Bases expression."""
    v = str(v or "").strip().lower()
    if v in ("", "0", "today", "+0"):
        return "today()"
    m = re.match(r"^([+-])\s*(\d+)$", v)
    if m:
        return 'today() %s "%s days"' % (m.group(1), m.group(2))
    if re.match(r"^\d{4}-\d{2}-\d{2}$", v):
        return 'date("%s")' % v
    raise ValueError("date value %r: use today, +N, -N or YYYY-MM-DD" % v)


def condition_expr(c, s):
    """One editor condition -> Bases expression string."""
    field, op, val = c.get("field"), c.get("op"), c.get("value")
    if field == "raw":
        if not val or not isinstance(val, (str, dict)):
            raise ValueError("empty kept-as-written condition")
        return val
    completed = [st["value"] for st in s.statuses if st.get("isCompleted")]
    if field == "status":
        if op == "open":
            return " && ".join('status != %s' % q(v) for v in completed) or "true"
        if op == "completed":
            return " || ".join('status == %s' % q(v) for v in completed) or "false"
        return "status %s %s" % ("==" if op == "is" else "!=", q(val))
    if field == "priority":
        return "priority %s %s" % ("==" if op == "is" else "!=", q(val))
    if field in DATE_FIELDS:
        if op == "empty":
            return "date(%s).isEmpty()" % field
        if op == "notEmpty":
            return "!date(%s).isEmpty()" % field
        cmp = {"before": "<", "after": ">", "on": "==", "onOrBefore": "<=", "onOrAfter": ">="}[op]
        return "date(%s).date() %s %s" % (field, cmp, date_value(val))
    # "lacks" must include tasks with no value at all; in Obsidian `!x` of a
    # missing value is null (no match), while `x != true` is true.
    if field == "contexts":
        e = "list(contexts).contains(%s)" % q(val)
        return e if op == "has" else e + " != true"
    if field == "projects":
        e = "list(projects).contains(link(%s))" % q(str(val).strip("[]"))
        return e if op == "has" else e + " != true"
    if field == "tags":
        e = "file.hasTag(%s)" % q(str(val).lstrip("#"))
        return e if op == "has" else "!" + e
    if field == "archived":
        e = "file.hasTag(%s)" % q(s.f("archiveTag"))
        return e if op == "yes" else "!" + e
    if field == "recurring":
        return "!recurrence.isEmpty()" if op == "yes" else "recurrence.isEmpty()"
    if field == "title":
        e = "file.name.lower().contains(%s)" % q(str(val).lower())
        return e if op == "has" else "!" + e
    raise ValueError("unknown condition %r" % c)


def priority_formula(s):
    parts = "0"
    for p in sorted(s.priorities, key=lambda p: p.get("weight", 0)):
        parts = 'if(priority == %s, %s, %s)' % (q(p["value"]), p.get("weight", 0), parts)
    return parts


def view_dict(model, s):
    conds = [condition_expr(c, s) for c in model.get("conditions") or []]
    view = {"type": "tasknotesKanban" if model.get("layout") == "board" else "tasknotesTaskList",
            "name": str(model.get("name") or "").strip()}
    if conds:
        view["filters"] = {"or" if model.get("match") == "any" else "and": conds}
    view["order"] = list(ORDER)
    srt = model.get("sort") or {}
    if srt.get("field") == "raw":
        view["sort"] = srt.get("raw") or []
    elif srt.get("field") and srt["field"] != "none":
        prop = "formula.priorityWeight" if srt["field"] == "priority" else \
            "file.name" if srt["field"] == "title" else srt["field"]
        view["sort"] = [{"property": prop, "direction": "DESC" if srt.get("dir") == "desc" else "ASC"}]
    g = model.get("group") or "none"
    if model.get("layout") == "board":
        g = "status"
    if g != "none":
        view["groupBy"] = {"property": g, "direction": model.get("groupDir") or "ASC"}
    return view


def base_dict(model, s):
    d = {"filters": {"and": ['file.hasTag(%s)' % q(s.task_tag)]}}
    formulas = dict(model.get("formulas") or {})
    if (model.get("sort") or {}).get("field") == "priority" and "priorityWeight" not in formulas:
        formulas["priorityWeight"] = priority_formula(s)
    if formulas:
        d["formulas"] = formulas
    d["views"] = [view_dict(model, s)]
    return d


def ystr(v):
    """A YAML scalar: plain when that reads back unchanged, else single-quoted."""
    s = str(v)
    if s and not re.match(r"^[\s!&*?|>'\"%@`#,\[\]{}-]", s) and ": " not in s and " #" not in s \
            and not s.endswith(":") and s == s.strip():
        try:
            if yaml.load("k: " + s, Loader=_Loader) == {"k": s} and yaml.safe_load("k: " + s) == {"k": s}:
                return s
        except yaml.YAMLError:
            pass
    return "'" + s.replace("'", "''") + "'"


def dump(d, indent=0):
    """Block-style YAML in the shape Obsidian writes .base files."""
    pad = " " * indent
    lines = []
    for k, v in d.items():
        if isinstance(v, dict):
            lines.append("%s%s:" % (pad, k))
            lines.extend(dump(v, indent + 2))
        elif isinstance(v, list):
            lines.append("%s%s:" % (pad, k))
            for item in v:
                if isinstance(item, dict):
                    sub = dump(item, indent + 4)
                    sub[0] = pad + "  - " + sub[0].lstrip()
                    lines.extend(sub)
                else:
                    lines.append("%s  - %s" % (pad, ystr(item)))
        else:
            lines.append("%s%s: %s" % (pad, k, ystr(v) if not isinstance(v, (int, float, bool)) else json.dumps(v)))
    return lines


def render_base(model, s):
    return "\n".join(dump(base_dict(model, s))) + "\n"


# Reverse mapping: recognise an editor-made condition from its expression.
def parse_condition(expr, s):
    try:
        return _parse_condition(expr, s)
    except (ValueError, KeyError, IndexError):
        return None


def _parse_condition(expr, s):
    completed = [st["value"] for st in s.statuses if st.get("isCompleted")]
    candidates = []
    statuses = [st["value"] for st in s.statuses]
    prios = [p["value"] for p in s.priorities]
    for op in ("open", "completed"):
        candidates.append({"field": "status", "op": op, "value": ""})
    m = re.match(r'^(status|priority) (==|!=) ("(?:[^"\\]|\\.)*")$', expr)
    if m:
        candidates.append({"field": m.group(1), "op": "is" if m.group(2) == "==" else "isNot", "value": json.loads(m.group(3))})
    m = re.match(r'^!?date\((\w+)\)', expr)
    if m and m.group(1) in DATE_FIELDS:
        for op in ("empty", "notEmpty"):
            candidates.append({"field": m.group(1), "op": op, "value": ""})
        m2 = re.match(r'^date\(\w+\)\.date\(\) (<|>|==|<=|>=) (.*)$', expr)
        if m2:
            op = {"<": "before", ">": "after", "==": "on", "<=": "onOrBefore", ">=": "onOrAfter"}[m2.group(1)]
            rhs = m2.group(2)
            r = re.match(r'^today\(\) ([+-]) "(\d+) days"$', rhs)
            d = re.match(r'^date\("(\d{4}-\d{2}-\d{2})"\)$', rhs)
            val = "today" if rhs == "today()" else (r.group(1) + r.group(2)) if r else d.group(1) if d else None
            if val is not None:
                candidates.append({"field": m.group(1), "op": op, "value": val})
    for field, pat in (("contexts", r'^()list\(contexts\)\.contains\((".*")\)( != true)?$'),
                       ("projects", r'^()list\(projects\)\.contains\(link\((".*")\)\)( != true)?$'),
                       ("tags", r'^(!?)file\.hasTag\((".*")\)$'),
                       ("title", r'^(!?)file\.name\.lower\(\)\.contains\((".*")\)$')):
        m = re.match(pat, expr)
        if m:
            val = json.loads(m.group(2))
            if field == "projects":
                val = "[[%s]]" % val
            op = "lacks" if (m.group(1) or (m.lastindex >= 3 and m.group(3))) else "has"
            if field == "tags" and val.lower() == s.f("archiveTag").lower():
                candidates.append({"field": "archived", "op": "no" if m.group(1) else "yes", "value": ""})
            candidates.append({"field": field, "op": op, "value": val})
    for op in ("yes", "no"):
        candidates.append({"field": "recurring", "op": op, "value": ""})
    for c in candidates:
        try:
            if condition_expr(c, s) == expr:
                return c
        except (ValueError, KeyError):
            pass
    return None


def expr_text(e):
    """A filter (expression or and/or/not group) as one readable line."""
    if isinstance(e, str):
        return e
    if isinstance(e, dict) and len(e) == 1:
        k, items = next(iter(e.items()))
        items = items if isinstance(items, list) else [items]
        inner = [expr_text(x) for x in items]
        if k == "not":
            return "not (%s)" % " and ".join(inner)
        return "(" + (" and " if k == "and" else " or ").join(inner) + ")"
    return json.dumps(e)


def raw_condition(e):
    return {"field": "raw", "op": "raw", "value": e, "label": expr_text(e)}


def as_condition(e, s):
    """An expression the editor understands as a row, else kept as written."""
    return (parse_condition(e, s) if isinstance(e, str) else None) or raw_condition(e)


EDITOR_SORTS = {"due", "scheduled", "status", "dateCreated", "completedDate"}


def model_from_view(v, d, s):
    f = v.get("filters")
    match, conds = "all", []
    if f:
        if isinstance(f, dict) and len(f) == 1 and list(f)[0] in ("and", "or") and isinstance(f[list(f)[0]], list):
            match = "any" if "or" in f else "all"
            conds = [as_condition(e, s) for e in f[list(f)[0]]]
        else:
            conds = [raw_condition(f)]
    srt = {"field": "none", "dir": "asc"}
    sorts = v.get("sort") or []
    if sorts:
        p = sorts[0].get("property") if isinstance(sorts[0], dict) else None
        fld = {"formula.priorityWeight": "priority", "file.name": "title"}.get(p, p)
        if len(sorts) == 1 and (fld in EDITOR_SORTS or fld in ("priority", "title")) and set(sorts[0]) <= {"property", "direction"}:
            srt = {"field": fld, "dir": "desc" if str(sorts[0].get("direction")).upper() == "DESC" else "asc"}
        else:
            srt = {"field": "raw", "dir": "asc", "raw": sorts}
    gb = v.get("groupBy") or {}
    g = gb.get("property") or "none"
    model = {"name": v.get("name"), "match": match, "conditions": conds, "sort": srt,
             "group": g, "layout": "board" if v.get("type") == "tasknotesKanban" else "list"}
    if g != "none" and str(gb.get("direction") or "ASC").upper() == "DESC":
        model["groupDir"] = "DESC"
    used = formulas_used(d.get("formulas") or {}, [f, sorts, gb])
    if srt["field"] == "priority" and used.get("priorityWeight") == priority_formula(s):
        del used["priorityWeight"]      # base_dict writes it for a priority sort anyway
    if used:
        model["formulas"] = used
    return model


def formulas_used(formulas, roots):
    """The formulas `roots` refer to, following formulas that use others,
    in the file's own order."""
    need, todo = set(), [json.dumps(roots)]
    while todo:
        for name in re.findall(r"formula\.(\w+)", todo.pop()):
            if name in formulas and name not in need:
                need.add(name)
                todo.append(str(formulas[name]))
    return {k: v for k, v in formulas.items() if k in need}


def editable_models(vault, rel, d):
    """{view name: model} when this whole file is exactly what the editor
    would write for that model (one view, our filters, our formulas)."""
    views = d.get("views") or []
    if len(views) != 1 or not isinstance(views[0], dict):
        return {}
    model = model_from_view(views[0], d, vault.settings)
    if not model:
        return {}
    try:
        regenerated = base_dict(model, vault.settings)
    except (ValueError, KeyError):
        return {}
    return {model["name"]: model} if jsonish(regenerated) == jsonish(d) else {}


def closest_model(vault, rel, name):
    """The editor model nearest to a hand-made view, for "Duplicate as
    editable view". Filters, sort and grouping are carried over exactly: what
    the editor has rows for becomes rows, the rest is kept as written.
    -> (model, notes) where notes say what changed."""
    s = vault.settings
    d = load_base(vault.read(rel))
    v = next((x for x in d.get("views") or [] if isinstance(x, dict) and str(x.get("name")) == name), None)
    if v is None:
        raise ValueError("no view %r in %s" % (name, rel))
    notes = []
    model = model_from_view(v, d, s)
    # The file-wide filter: the task-tag check is what every OmaForge view
    # starts with; anything else joins the view's own conditions.
    top = d.get("filters")
    tag_check = 'file.hasTag(%s)' % q(s.task_tag)
    extra = []
    if isinstance(top, dict) and list(top) == ["and"] and isinstance(top["and"], list):
        extra = [e for e in top["and"] if e != tag_check]
    elif top:
        extra = [top]
    if extra:
        if model["match"] == "any" and len(model["conditions"]) > 1:
            group = {"or": [c["value"] if c["field"] == "raw" else condition_expr(c, s) for c in model["conditions"]]}
            model["conditions"] = [raw_condition(group)]
        model["match"] = "all"
        model["conditions"] = [as_condition(e, s) for e in extra] + model["conditions"]
    if not mentions_task_tag(top, s.task_tag) and not mentions_task_tag(v.get("filters"), s.task_tag):
        notes.append("Only notes tagged #%s are included." % s.task_tag)
    if v.get("type") not in ("tasknotesTaskList", "tasknotesKanban", "table"):
        notes.append("Shown as a list: the original's %s layout isn't one the editor makes." % (v.get("type") or "?"))
    kept = sum(1 for c in model["conditions"] if c["field"] == "raw")
    if kept:
        notes.append("%s kept exactly as written. You can remove %s here, or edit the copy in Obsidian."
                     % ("1 condition is" if kept == 1 else "%d conditions are" % kept, "it" if kept == 1 else "them"))
    if model["sort"]["field"] == "raw":
        notes.append("The sort is kept as written. Pick another to replace it.")
    model["name"] = "%s copy" % name
    return model, notes


def op_closest_model(vault, req, day):
    from .vault import VaultError
    try:
        model, notes = closest_model(vault, req.get("file") or "", req.get("name") or "")
    except (OSError, ValueError, yaml.YAMLError, Unsupported) as e:
        raise VaultError("bad-view", str(e))
    return {"model": model, "notes": notes}


def jsonish(v):
    return json.loads(json.dumps(v, default=str))


# ---------------------------------------------------------------- ops -------

def unique_base_path(vault, stem):
    folder = vault.settings.views_folder
    rel = "%s/%s.base" % (folder, stem)
    i = 2
    while os.path.lexists(vault.abs(rel)):
        rel = "%s/%s-%d.base" % (folder, stem, i)
        i += 1
    return rel


def check_model(model, s):
    name = str(model.get("name") or "").strip()
    if not name:
        raise ValueError("a view needs a name")
    for c in model.get("conditions") or []:
        condition_expr(c, s)   # raises on bad input
    return name


def op_preview(vault, req, day):
    """Compile an editor model without writing it, for the live preview."""
    from .vault import VaultError
    model = req.get("model") or {}
    try:
        text = render_base(dict(model, name=model.get("name") or "Preview"), vault.settings)
    except (ValueError, KeyError) as e:
        raise VaultError("bad-view", str(e))
    views = views_in(vault, "preview.base", text)
    return {"view": views[0] if views else None, "yaml": text}


def op_save_view(vault, req, day):
    """Create a new .base view, or rewrite one OmaForge can regenerate."""
    from .vault import VaultError
    from .tasks import sanitize_filename
    model = req.get("model") or {}
    s = vault.settings
    try:
        name = check_model(model, s)
        text = render_base(model, s)
    except (ValueError, KeyError) as e:
        raise VaultError("bad-view", str(e))
    rel = req.get("file")
    if rel:
        if not rel.endswith(".base"):
            raise VaultError("bad-path", "not a .base file")
        current = vault.read(rel)
        if not editable_models(vault, rel, load_base(current)):
            raise VaultError("not-editable", "%s has been changed outside OmaForge; duplicate it instead" % rel)
        if current != req.get("expectText", current):
            raise VaultError("conflict", "%s changed on disk; reopen the editor" % rel)
        from .vault import file_hash
        vault.write(rel, text, expect_hash=file_hash(current))
    else:
        rel = unique_base_path(vault, sanitize_filename(name))
        vault.write(rel, text, create=True)
    return {"file": rel, "id": "base:%s::%s" % (rel, name), "views": all_views(vault)}


def op_delete_view(vault, req, day):
    import subprocess
    from .vault import VaultError
    rel = req.get("file") or ""
    if not rel.endswith(".base"):
        raise VaultError("bad-path", "not a .base file")
    vault.check_writable()
    current = vault.read(rel)
    if not editable_models(vault, rel, load_base(current)):
        raise VaultError("not-editable", "only views made in OmaForge can be deleted here")
    r = subprocess.run(["gio", "trash", "--", vault.abs(rel)], capture_output=True, text=True)
    if r.returncode != 0:
        raise VaultError("trash-failed", r.stderr.strip())
    return {"views": all_views(vault)}


def op_view_text(vault, req, day):
    rel = req.get("file") or ""
    if not rel.endswith(".base"):
        from .vault import VaultError
        raise VaultError("bad-path", "not a .base file")
    return {"text": vault.read(rel)}


OPS = {"closestModel": op_closest_model, "previewView": op_preview, "saveView": op_save_view, "deleteView": op_delete_view, "viewText": op_view_text}
