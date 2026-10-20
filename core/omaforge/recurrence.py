"""TaskNotes recurrence: "DTSTART:20261005;FREQ=WEEKLY;BYDAY=MO".

Mirrors @tasknotes/model's rrule.js usage (docs/tasknotes-spec.md §4):
everything is floating wall-clock time (DTSTART's trailing Z is cosmetic),
occurrences are compared as calendar dates, and searches are bounded by the
same per-frequency look-ahead windows so "no next occurrence" agrees too.
"""
import re
from datetime import date, datetime, timedelta

from .rrule import RRule, Unsupported

DAYS = {"MO": "Mon", "TU": "Tue", "WE": "Wed", "TH": "Thu", "FR": "Fri", "SA": "Sat", "SU": "Sun"}
FREQ = {"DAILY": ("day", "Daily"), "WEEKLY": ("week", "Weekly"), "MONTHLY": ("month", "Monthly"),
        "YEARLY": ("year", "Yearly")}
DTSTART_RE = re.compile(r"DTSTART:(\d{8}(?:T\d{6}Z?)?)")


def split(rule):
    """-> (dtstart datetime|None, body string, {KEY: value})"""
    rule = str(rule or "").strip()
    m = DTSTART_RE.search(rule)
    start = parse_dtstart(m.group(1)) if m else None
    body = re.sub(r"DTSTART:[^;]+;?", "", rule).strip().lstrip(";")
    if body.upper().startswith("RRULE:"):
        body = body[6:]
    parts = {}
    for chunk in body.split(";"):
        if "=" in chunk:
            k, v = chunk.split("=", 1)
            parts[k.strip().upper()] = v.strip()
    return start, body, parts


def parse_dtstart(v):
    for fmt in ("%Y%m%dT%H%M%SZ", "%Y%m%dT%H%M%S", "%Y%m%d"):
        try:
            return datetime.strptime(v, fmt)
        except ValueError:
            pass
    return None


def has_dtstart(rule):
    return bool(DTSTART_RE.search(str(rule or "")))


def lookahead(parts):
    try:
        i = max(1, int(parts.get("INTERVAL", "1")))
    except ValueError:
        i = 1
    return {"DAILY": max(30, 2 * i), "WEEKLY": max(90, 14 * i), "MONTHLY": max(400, 62 * i),
            "YEARLY": max(800, 732 * i)}.get(parts.get("FREQ"), 365)


def build(rule, fallback_start=None):
    """-> (rrule|None, dtstart, parts). fallback_start: date used when the
    rule has no DTSTART (TaskNotes: scheduled, then dateCreated). A rule we
    can't expand -- malformed or Unsupported -- gives None, so listing a
    task never fails over it; actions that change a task call check()."""
    start, body, parts = split(rule)
    if "FREQ" not in parts:
        return None, None, parts
    if start is None:
        if fallback_start is None:
            return None, None, parts
        start = datetime(fallback_start.year, fallback_start.month, fallback_start.day)
    # rrule.js treats a date-only UNTIL as midnight UTC; with floating times
    # that's midnight, so an occurrence later that day is excluded. (RRule
    # reads a date-only UNTIL as midnight and ignores a trailing Z.)
    try:
        return RRule(parts, start), start, parts
    except (ValueError, TypeError, Unsupported):
        return None, None, parts


def check(rule):
    """Raise Unsupported if the rule is one we'd refuse to expand."""
    _start, _body, parts = split(rule)
    if "FREQ" in parts:
        try:
            RRule(parts, datetime(2000, 1, 1))
        except (ValueError, TypeError):
            pass  # malformed: handled as "not a repeat", as before


def d(s):
    return date.fromisoformat(str(s)[:10])


def dt(day):
    return datetime(day.year, day.month, day.day)


def occurrences(r, start_day, end_day):
    return [o.date() for o in r.between(dt(start_day), dt(end_day) + timedelta(hours=23, minutes=59, seconds=59), inc=True)]


def is_occurrence(r, day):
    return bool(occurrences(r, day, day))


def instance_for(rule, target, completed, skipped, anchor="scheduled", fallback_start=None):
    """Which occurrence a 'complete'/'skip' on `target` applies to (§4.4.2)."""
    t = d(target)
    if anchor == "completion":
        return t.isoformat()
    r, start, parts = build(rule, fallback_start)
    if r is None:
        return t.isoformat()
    if is_occurrence(r, t):
        return t.isoformat()
    processed = set(completed) | set(skipped)
    window = occurrences(r, t - timedelta(days=lookahead(parts)), t)
    for o in reversed(window):
        if o.isoformat() not in processed:
            return o.isoformat()
    for o in occurrences(r, t, t + timedelta(days=lookahead(parts))):
        if o.isoformat() not in set(completed):
            return o.isoformat()
    return t.isoformat()


def next_open(rule, floor, completed=(), skipped=(), anchor="scheduled", fallback_start=None):
    """First occurrence >= floor not completed/skipped (§4.5). None if there
    isn't one inside TaskNotes' look-ahead window."""
    f = d(floor)
    r, start, parts = build(rule, fallback_start or f)
    if r is None:
        return None
    sd = start.date()
    if anchor == "completion":
        lo = sd
        for o in occurrences(r, lo, lo + timedelta(days=lookahead(parts))):
            if o > sd and o >= f and o.isoformat() not in set(skipped):
                return o.isoformat()
        return None
    lo = sd if sd < f else f
    processed = set(completed) | set(skipped)
    for o in occurrences(r, lo, f + timedelta(days=lookahead(parts))):
        if o >= f and o.isoformat() not in processed:
            return o.isoformat()
    return None


def with_dtstart(rule, scheduled="", created=""):
    """Prepend DTSTART the way TaskNotes does on create / when it's missing
    (§4.2): from scheduled, else dateCreated; time-bearing sources give the
    local wall-clock digits with a (meaningless) Z."""
    if has_dtstart(rule):
        return rule
    src = scheduled or created
    if not src:
        return rule
    s = str(src)
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?", s)
    if m and scheduled:
        v = "%s%s%sT%s%s%sZ" % (m.group(1), m.group(2), m.group(3), m.group(4), m.group(5), m.group(6) or "00")
    elif m:
        try:
            local = datetime.fromisoformat(s).astimezone() if re.search(r"[+-]\d{2}:\d{2}$|Z$", s) else datetime.fromisoformat(s)
            v = local.strftime("%Y%m%dT%H%M%SZ")
        except ValueError:
            v = "%s%s%s" % (m.group(1), m.group(2), m.group(3))
    else:
        m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", s)
        if not m:
            return rule
        v = "%s%s%s" % m.groups()
    return "DTSTART:%s;%s" % (v, rule)


def set_dtstart_date(rule, day):
    """Completion anchor: move DTSTART's date, keeping any time part."""
    def repl(m):
        v = m.group(1)
        return "DTSTART:" + day.replace("-", "") + v[8:]
    return DTSTART_RE.sub(repl, rule, count=1)


def describe(rule):
    _start, _body, p = split(rule)
    freq = p.get("FREQ")
    if freq not in FREQ:
        return str(rule)
    unit, word = FREQ[freq]
    try:
        n = int(p.get("INTERVAL", "1"))
    except ValueError:
        n = 1
    s = word if n == 1 else "Every %d %ss" % (n, unit)
    if p.get("BYDAY"):
        codes = p["BYDAY"].split(",")
        if freq == "MONTHLY" and any(c[:-2] for c in codes):
            ordn = {"1": "1st", "2": "2nd", "3": "3rd", "4": "4th", "-1": "last"}
            s += " on the " + ", ".join("%s %s" % (ordn.get(c[:-2], c[:-2]), DAYS.get(c[-2:], c)) for c in codes)
        elif set(codes) == {"MO", "TU", "WE", "TH", "FR"}:
            s = "Weekdays" if n == 1 else s + " on weekdays"
        else:
            s += " on " + ", ".join(DAYS.get(c[-2:], c) for c in codes)
    if p.get("BYMONTHDAY"):
        s += " on day " + p["BYMONTHDAY"]
    if p.get("COUNT"):
        s += ", %s times" % p["COUNT"]
    if p.get("UNTIL"):
        u = parse_dtstart(p["UNTIL"].rstrip("Z") if "T" in p["UNTIL"] else p["UNTIL"])
        s += ", until " + (u.date().isoformat() if u else p["UNTIL"])
    return s
