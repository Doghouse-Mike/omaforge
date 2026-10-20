"""Obsidian Tasks' 🔁 rules: rrule.js English, read and written.

Tasks stores a repeat as rrule.js's own English ("every week on Monday",
"every 2 weeks on Tuesday, Friday when done"). It reads it with
RRule.parseText and writes it back with rrule.toText(), so OmaForge must
both understand the same phrases and produce the identical wording.

parse(text) -> {"freq", "interval", "byweekday", "bymonthday", "bymonth",
                "count", "until", "whenDone"} or None
to_text(rule) -> the text Tasks would write
next_after(rule, base_date) -> the next date (Tasks' Recurrence.next)
"""
from datetime import date, datetime, timedelta

from .rrule import WEEKDAYS, RRule


def _rrule(rule, dtstart):
    parts = {"FREQ": rule["freq"].upper(), "INTERVAL": str(rule.get("interval") or 1)}
    if rule.get("byweekday"):
        parts["BYDAY"] = ",".join("%s%s" % (n or "", WEEKDAYS[d]) for d, n in rule["byweekday"])
    if rule.get("bymonthday"):
        parts["BYMONTHDAY"] = ",".join(str(n) for n in rule["bymonthday"])
    if rule.get("bymonth"):
        parts["BYMONTH"] = ",".join(str(n) for n in rule["bymonth"])
    if rule.get("count"):
        parts["COUNT"] = str(rule["count"])
    if rule.get("until"):
        parts["UNTIL"] = rule["until"].strftime("%Y%m%dT235959")
    return RRule(parts, datetime(dtstart.year, dtstart.month, dtstart.day))


def _after(rule, base):
    """rrule.after(end of `base` day) with dtstart = base: first date > base."""
    r = _rrule(rule, base)
    n = r.after(datetime(base.year, base.month, base.day, 23, 59, 59))
    return n.date() if n else None


def next_after(rule, base):
    """Tasks' Recurrence.nextAfter, including its month/year clamping: an
    "every month" (no "on ...") rule from the 31st must not skip February."""
    nxt = _after(rule, base)
    if nxt is None:
        return None
    text = to_text(rule)
    if rule["freq"] == "monthly" and " on " not in text:
        step = rule.get("interval") or 1
        after = base
        while (nxt.year - after.year) * 12 + (nxt.month - after.month) > step:
            after = after - timedelta(days=1)
            nxt = _after(rule, after)
            if nxt is None:
                return None
    if rule["freq"] == "yearly":
        step = rule.get("interval") or 1
        after = base
        while nxt.year - after.year > step:
            after = after - timedelta(days=1)
            nxt = _after(rule, after)
            if nxt is None:
                return None
    return nxt


# ---------------------------------------------------------------- parse -----
# A port of rrule.js nlp/parsetext.js (docs/tasks-plugin-spec.md §10.1).
import re as _re

_TOKENS = [  # i18n order: on a tie in match length the earlier one wins
    ("number", r"[1-9][0-9]*"), ("numberAsText", r"(one|two|three)"), ("every", r"every"),
    ("day(s)", r"days?"), ("weekday(s)", r"weekdays?"), ("week(s)", r"weeks?"), ("hour(s)", r"hours?"),
    ("minute(s)", r"minutes?"), ("month(s)", r"months?"), ("year(s)", r"years?"), ("on", r"(on|in)"),
    ("at", r"(at|@)"), ("the", r"the"), ("first", r"first"), ("second", r"second"), ("third", r"third"),
    ("nth", r"([1-9][0-9]*)(\.|th|nd|rd|st)"), ("last", r"last"), ("for", r"for"), ("time(s)", r"times?"),
    ("until", r"(un)?til"),
    ("monday", r"mo(n(day)?)?"), ("tuesday", r"tu(e(s(day)?)?)?"), ("wednesday", r"we(d(n(esday)?)?)?"),
    ("thursday", r"th(u(r(sday)?)?)?"), ("friday", r"fr(i(day)?)?"), ("saturday", r"sa(t(urday)?)?"),
    ("sunday", r"su(n(day)?)?"),
    ("january", r"jan(uary)?"), ("february", r"feb(ruary)?"), ("march", r"mar(ch)?"), ("april", r"apr(il)?"),
    ("may", r"may"), ("june", r"june?"), ("july", r"july?"), ("august", r"aug(ust)?"),
    ("september", r"sep(t(ember)?)?"), ("october", r"oct(ober)?"), ("november", r"nov(ember)?"),
    ("december", r"dec(ember)?"),
    ("comma", r"(,\s*|(and|or)\s*)+"),
]
_TOKENS = [(n, _re.compile(r"^" + p, _re.IGNORECASE)) for n, p in _TOKENS]
_SKIP = _re.compile(r"^[ \r\n\t]+|^\.$")
_DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
_MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september",
           "october", "november", "december"]
MONTH_NAMES = [m.capitalize() for m in _MONTHS]
DAY_NAMES = [d.capitalize() for d in _DAYS]


class _Bad(Exception):
    pass


class _Tok:
    def __init__(self, text):
        self.text = text
        self.symbol = None
        self.value = None
        self.done = False
        self.next()

    def next(self):
        while True:
            if not self.text:
                self.symbol, self.value, self.done = None, None, True
                return False
            m = _SKIP.match(self.text)
            if m:
                self.text = self.text[m.end():]
                continue
            best = None
            for name, rx in _TOKENS:
                mm = rx.match(self.text)
                if mm and (best is None or len(mm.group(0)) > len(best[1].group(0))):
                    best = (name, mm)
            if best is None:          # nothing matches: the rest is ignored
                self.symbol, self.value, self.done, self.text = None, None, True, ""
                return False
            self.symbol, self.value = best
            self.text = self.text[best[1].end():]
            return True

    def accept(self, name):
        if self.symbol == name:
            v = self.value if self.value is not None else True
            self.next()
            return v
        return False


def _nth(t):
    s = t.symbol
    if s == "last":
        t.next()
        return -1
    if s == "first":
        t.next()
        return -1 if t.accept("last") else 1
    if s == "second":
        t.next()
        return -2 if t.accept("last") else 2
    if s == "third":
        t.next()
        return -3 if t.accept("last") else 3
    if s == "nth":
        v = int(t.value.group(1))
        if v > 366:
            raise _Bad()
        t.next()
        return -v if t.accept("last") else v
    return False


def _wkd(t):
    return _DAYS.index(t.symbol) if t.symbol in _DAYS else None


def _mon(t):
    return _MONTHS.index(t.symbol) + 1 if t.symbol in _MONTHS else None


def _on(t, r):
    on = t.accept("on")
    the = t.accept("the")
    if not (on or the):
        return
    while True:
        n = _nth(t)
        w = _wkd(t)
        m = _mon(t)
        if n is not False:
            if w is not None:
                t.next()
                r["byweekday"].append((w, n))
            else:
                r["bymonthday"].append(n)
                t.accept("day(s)")
        elif w is not None:
            t.next()
            r["byweekday"].append((w, 0))
        elif t.symbol == "weekday(s)":
            t.next()
            r["byweekday"] = [(i, 0) for i in range(5)]
        elif t.symbol == "week(s)":
            t.next()
            n2 = t.accept("number")
            if not n2:
                raise _Bad()
            while t.accept("comma"):
                if not t.accept("number"):
                    raise _Bad()
        elif m is not None:
            t.next()
            r["bymonth"].append(m)
        else:
            return
        if not (t.accept("comma") or t.accept("the") or t.accept("on")):
            return


def _at(t):
    if t.accept("at"):
        if not t.accept("number"):
            raise _Bad()
        while t.accept("comma"):
            if not t.accept("number"):
                raise _Bad()


def _f(t, r):
    if t.symbol == "until":
        rest = t.text.strip()
        d = _parse_until(rest)
        if d is None:
            raise _Bad()
        r["until"] = d
        t.text, t.done = "", True
    elif t.accept("for"):
        n = t.accept("number")
        if not n:
            raise _Bad()
        r["count"] = int(n.group(0))
        t.accept("time(s)")


def _parse_until(s):
    for fmt in ("%B %d, %Y", "%B %d %Y", "%b %d, %Y", "%b %d %Y", "%d %B %Y", "%d %b %Y", "%B %Y"):
        try:
            return datetime.strptime(s.strip(), fmt).date()
        except ValueError:
            pass
    return None


def parse(text):
    """'every 2 weeks on Monday when done' -> rule dict, or None if Tasks
    would drop it. Unrecognised trailing words are ignored, as rrule does."""
    m = _re.match(r"^([a-zA-Z0-9, !]+?)( when done)?$", str(text or "").strip(), _re.IGNORECASE)
    if not m:
        return None
    r = {"freq": None, "interval": 1, "byweekday": [], "bymonthday": [], "bymonth": [], "count": None,
         "until": None, "whenDone": m.group(2) is not None}
    try:
        t = _Tok(m.group(1).strip())
        if not t.accept("every"):
            raise _Bad()
        if t.done:
            raise _Bad()
        n = t.accept("number")
        if n:
            r["interval"] = int(n.group(0))
        if t.done:
            raise _Bad()
        s = t.symbol
        if s == "day(s)":
            r["freq"] = "daily"
            if t.next():
                _at(t)
                _f(t, r)
        elif s == "weekday(s)":
            r["freq"] = "weekly"
            r["byweekday"] = [(i, 0) for i in range(5)]
            t.next()
            _at(t)
            _f(t, r)
        elif s == "week(s)":
            r["freq"] = "weekly"
            if t.next():
                _on(t, r)
                _at(t)
                _f(t, r)
        elif s in ("hour(s)", "minute(s)"):
            return None          # sub-daily rules: not something a task date can use
        elif s == "month(s)":
            r["freq"] = "monthly"
            if t.next():
                _on(t, r)
                _f(t, r)
        elif s == "year(s)":
            r["freq"] = "yearly"
            if t.next():
                _on(t, r)
                _f(t, r)
        elif s in _DAYS:
            r["freq"] = "weekly"
            r["byweekday"] = [(_DAYS.index(s), 0)]
            if t.next():
                while t.accept("comma"):
                    if t.done:
                        raise _Bad()
                    w = _wkd(t)
                    if w is None:
                        raise _Bad()
                    r["byweekday"].append((w, 0))
                    t.next()
                # MDAYS
                if t.accept("on"):
                    t.accept("the")
                    while True:
                        n2 = _nth(t)
                        if n2 is False:
                            break
                        r["bymonthday"].append(n2)
                        if not t.accept("comma"):
                            break
                _at(t)
                _f(t, r)
        elif s in _MONTHS:
            r["freq"] = "yearly"
            r["bymonth"] = [_MONTHS.index(s) + 1]
            if t.next():
                while t.accept("comma"):
                    if t.done:
                        raise _Bad()
                    mm2 = _mon(t)
                    if mm2 is None:
                        raise _Bad()
                    r["bymonth"].append(mm2)
                    t.next()
                _on(t, r)
                _f(t, r)
        else:
            raise _Bad()
    except _Bad:
        return None
    return r


# --------------------------------------------------------------- toText -----
# A port of rrule.js nlp/totext.js for the shapes parse() produces.

def _nth_text(n):
    if n == -1:
        return "last"
    a = abs(n)
    suf = {1: "st", 21: "st", 31: "st", 2: "nd", 22: "nd", 3: "rd", 23: "rd"}.get(a, "th")
    return "%d%s%s" % (a, suf, " last" if n < 0 else "")


def _list(items, final=" and "):
    items = list(items)
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + final + items[-1]


def _plural(n, unit):
    return unit if n % 100 == 1 else unit + "s"


def _weekdays_text(byweekday):
    days = sorted(set(byweekday), key=lambda x: (x[0], x[1]))
    parts = []
    for d, n in days:
        parts.append(("the %s %s" % (_nth_text(n), DAY_NAMES[d])) if n else DAY_NAMES[d])
    return parts


def to_text(r):
    n = r.get("interval") or 1
    f = r["freq"]
    wd = r.get("byweekday") or []
    md = r.get("bymonthday") or []
    months = r.get("bymonth") or []
    plain = [d for d, k in wd if not k]
    out = ["every"]
    if f == "daily":
        out.append("day" if n == 1 else "%d %s" % (n, _plural(n, "day")))
    elif f == "weekly":
        if sorted(plain) == [0, 1, 2, 3, 4] and len(wd) == 5:
            out.append("weekday" if n == 1 else "%d %s on weekdays" % (n, _plural(n, "week")))
            wd = []
        elif sorted(plain) == list(range(7)) and len(wd) == 7:
            out.append("day" if n == 1 else "%d %s" % (n, _plural(n, "day")))
            wd = []
        else:
            out.append("week" if n == 1 else "%d %s" % (n, _plural(n, "week")))
            if wd:
                out.append("on " + ", ".join(_weekdays_text(wd)))
                wd = []
    elif f == "monthly":
        out.append("month" if n == 1 else "%d %s" % (n, _plural(n, "month")))
    elif f == "yearly":
        if months:
            if n != 1:
                out.append("%d %s" % (n, _plural(n, "year")))
            out.append(_list(MONTH_NAMES[m - 1] for m in sorted(months)))
        else:
            out.append("year" if n == 1 else "%d %s" % (n, _plural(n, "year")))
    if f in ("monthly", "yearly"):
        if md:
            pos = sorted(x for x in md if x > 0) + sorted((x for x in md if x < 0), reverse=True)
            out.append("on the " + _list(_nth_text(x) for x in pos))
        elif wd and sorted(plain) == [0, 1, 2, 3, 4] and len(wd) == 5:
            out.append("on weekdays")
        elif wd:
            out.append("on " + _list(_weekdays_text(wd)))
    if r.get("until"):
        u = r["until"]
        out.append("until %s %d, %d" % (MONTH_NAMES[u.month - 1], u.day, u.year))
    elif r.get("count"):
        c = r["count"]
        out.append("for %d %s" % (c, "time" if c == 1 else "times"))
    return " ".join(out) + (" when done" if r.get("whenDone") else "")


def from_rrule(body):
    """An RRULE (as OmaForge's repeat box makes them) -> rule dict, or None if
    Tasks' English can't say it."""
    p = {}
    for kv in str(body or "").split(";"):
        if "=" in kv:
            k, v = kv.split("=", 1)
            p[k.strip().upper()] = v.strip()
    f = {"DAILY": "daily", "WEEKLY": "weekly", "MONTHLY": "monthly", "YEARLY": "yearly"}.get(p.get("FREQ"))
    if not f:
        return None
    codes = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]
    wd = []
    for c in filter(None, p.get("BYDAY", "").split(",")):
        m = _re.match(r"^([+-]?\d+)?([A-Z]{2})$", c)
        if not m or m.group(2) not in codes:
            return None
        wd.append((codes.index(m.group(2)), int(m.group(1) or 0)))
    r = {"freq": f, "interval": int(p.get("INTERVAL", 1)), "byweekday": wd,
         "bymonthday": [int(x) for x in filter(None, p.get("BYMONTHDAY", "").split(","))],
         "bymonth": [int(x) for x in filter(None, p.get("BYMONTH", "").split(","))],
         "count": int(p["COUNT"]) if p.get("COUNT") else None,
         "until": datetime.strptime(p["UNTIL"][:8], "%Y%m%d").date() if p.get("UNTIL") else None,
         "whenDone": False}
    # Only keep what survives Tasks' own read-back of the wording.
    back = parse(to_text(r))
    return r if back is not None else None
