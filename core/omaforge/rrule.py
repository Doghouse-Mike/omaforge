"""RFC 5545 RRULE expansion, in floating time, without python-dateutil.

A standard Omarchy install doesn't ship dateutil, so this covers what
TaskNotes' recurrence editor and Obsidian Tasks' 🔁 text produce -- FREQ
DAILY..YEARLY, INTERVAL, COUNT, UNTIL, BYDAY (numbered too), BYMONTHDAY,
BYMONTH, BYSETPOS, WKST -- and refuses the rest (BYHOUR, BYYEARDAY,
BYWEEKNO, sub-daily FREQ, ...) with Unsupported rather than guessing.

Expansion follows dateutil exactly, and so rrule.js, which is a port of it
(oracle-checked against dateutil on random rules). Three of its quirks are
kept on purpose: the first WEEKLY period starts at DTSTART, not at WKST
(matters to BYSETPOS); a numbered BYDAY counts within the year for YEARLY
without BYMONTH, within the month otherwise, and its number is ignored
for DAILY and WEEKLY.
"""
import re
from datetime import date, datetime, timedelta

WEEKDAYS = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")
BYDAY_RE = re.compile(r"^([+-]?\d{1,2})?(MO|TU|WE|TH|FR|SA|SU)$")
PARTS = {"FREQ", "INTERVAL", "COUNT", "UNTIL", "BYDAY", "BYMONTHDAY", "BYMONTH", "BYSETPOS", "WKST"}
UNSUPPORTED_PARTS = {"BYSECOND", "BYMINUTE", "BYHOUR", "BYYEARDAY", "BYWEEKNO", "BYEASTER"}


class Unsupported(Exception):
    """A valid rule using a part this module deliberately doesn't expand."""


def _int_list(value, lo, hi):
    out = []
    for item in value.split(","):
        n = int(item)
        if not (lo <= abs(n) <= hi) or n == 0:
            raise ValueError("value out of range: %r" % item)
        out.append(n)
    return out


class RRule:
    """One rule. `parts` is {KEY: value} as written in the RRULE (keys
    upper-case); `start` is DTSTART as a naive datetime. Raises ValueError
    for a malformed rule (where dateutil would too) and Unsupported for a
    valid one using parts it doesn't cover."""

    def __init__(self, parts, start):
        for key in parts:
            if key in UNSUPPORTED_PARTS:
                raise Unsupported("repeat rules using %s aren't supported" % key)
            if key not in PARTS:
                raise ValueError("unknown RRULE part %r" % key)
        freq = str(parts.get("FREQ", "")).upper()
        if freq in ("HOURLY", "MINUTELY", "SECONDLY"):
            raise Unsupported("%s repeats aren't supported" % freq.lower())
        if freq not in ("DAILY", "WEEKLY", "MONTHLY", "YEARLY"):
            raise ValueError("bad FREQ %r" % freq)
        self.freq, self.start = freq, start
        self.interval = int(parts.get("INTERVAL", "1"))
        if self.interval < 1:
            raise ValueError("INTERVAL must be positive")
        self.count = int(parts["COUNT"]) if "COUNT" in parts else None
        self.until = None
        if "UNTIL" in parts:
            u = parts["UNTIL"].upper().rstrip("Z")
            self.until = datetime.strptime(u, "%Y%m%dT%H%M%S" if "T" in u else "%Y%m%d")
        self.wkst = WEEKDAYS.index(parts.get("WKST", "MO").upper())
        self.bymonth = _int_list(parts["BYMONTH"], 1, 12) if "BYMONTH" in parts else []
        if any(m < 0 for m in self.bymonth):
            raise ValueError("BYMONTH must be positive")
        self.bymonthday = _int_list(parts["BYMONTHDAY"], 1, 31) if "BYMONTHDAY" in parts else []
        self.bysetpos = _int_list(parts["BYSETPOS"], 1, 366) if "BYSETPOS" in parts else []
        self.byweekday, self.bynweekday = set(), []
        for item in parts["BYDAY"].upper().split(",") if "BYDAY" in parts else []:
            m = BYDAY_RE.match(item.strip())
            if not m:
                raise ValueError("bad BYDAY %r" % item)
            wd = WEEKDAYS.index(m.group(2))
            n = int(m.group(1)) if m.group(1) else 0
            if n == 0 or freq in ("DAILY", "WEEKLY"):
                self.byweekday.add(wd)  # dateutil ignores the number below MONTHLY
            elif not 1 <= abs(n) <= 53:
                raise ValueError("bad BYDAY %r" % item)
            else:
                self.bynweekday.append((wd, n))
        # dateutil's defaults when no day-selecting part is given.
        if not (self.bymonthday or self.byweekday or self.bynweekday):
            if freq == "YEARLY":
                self.bymonth = self.bymonth or [start.month]
                self.bymonthday = [start.day]
            elif freq == "MONTHLY":
                self.bymonthday = [start.day]
            elif freq == "WEEKLY":
                self.byweekday = {start.weekday()}

    def _period_days(self, k):
        """Every day of the k-th period, before any BYxxx filtering."""
        s, step = self.start.date(), self.interval * k
        if self.freq == "DAILY":
            return [s + timedelta(days=step)]
        if self.freq == "WEEKLY":
            ws = s - timedelta(days=(s.weekday() - self.wkst) % 7) + timedelta(weeks=step)
            return [ws + timedelta(days=i) for i in range(7) if k or ws + timedelta(days=i) >= s]
        if self.freq == "MONTHLY":
            y, m = divmod(s.year * 12 + s.month - 1 + step, 12)
            first, months = date(y, m + 1, 1), 1
        else:
            first, months = date(s.year + step, 1, 1), 12
        y2, m2 = divmod(first.year * 12 + first.month - 1 + months, 12)
        return [first + timedelta(days=i) for i in range((date(y2, m2 + 1, 1) - first).days)]

    def _nth_ok(self, d, days):
        if self.freq == "YEARLY" and not self.bymonth:
            scope = [x for x in days if x.weekday() == d.weekday()]
        else:
            scope = [x for x in days if x.month == d.month and x.weekday() == d.weekday()]
        pos = scope.index(d)
        return any(wd == d.weekday() and (n - 1 == pos if n > 0 else len(scope) + n == pos)
                   for wd, n in self.bynweekday)

    def _matches(self, d, days):
        if self.bymonth and d.month not in self.bymonth:
            return False
        if self.bymonthday:
            last = (date(d.year + d.month // 12, d.month % 12 + 1, 1) - timedelta(days=1)).day \
                if d < date(9999, 12, 1) else 31
            if not any(d.day == (n if n > 0 else last + 1 + n) for n in self.bymonthday):
                return False
        # Plain and numbered weekdays are separate filters that must both
        # pass (so mixing them narrows, not widens) -- dateutil and rrule.js.
        if self.byweekday and d.weekday() not in self.byweekday:
            return False
        if self.bynweekday and not self._nth_ok(d, days):
            return False
        return True

    def _iter(self, stop):
        """Occurrences in order, ending once a period starts after `stop`
        (every later one starts later still) or the calendar runs out."""
        t, emitted, k = self.start.time(), 0, 0
        while True:
            try:
                days = self._period_days(k)
            except (ValueError, OverflowError):
                return
            k += 1
            if not days:
                continue
            if days[0] > stop.date():
                return
            chosen = [d for d in days if self._matches(d, days)]
            if self.bysetpos:
                chosen = sorted({chosen[p - 1 if p > 0 else len(chosen) + p]
                                 for p in self.bysetpos if -len(chosen) <= p <= len(chosen)})
            for d in chosen:
                o = datetime.combine(d, t)
                if o < self.start:
                    continue
                if (self.until is not None and o > self.until) or \
                        (self.count is not None and emitted >= self.count):
                    return
                yield o
                emitted += 1

    def between(self, lo, hi, inc=True):
        out = []
        for o in self._iter(hi):
            if o > hi or (not inc and o == hi):
                break
            if o > lo or (inc and o == lo):
                out.append(o)
        return out

    def after(self, dt, inc=False):
        """First occurrence after dt, or None. Any pattern that occurs at all
        recurs within 400 Gregorian years per INTERVAL step, so searching
        that far is the same as searching forever."""
        try:
            stop = dt.replace(year=dt.year + 400 * self.interval)
        except ValueError:
            stop = datetime(9999, 12, 31, 23, 59, 59)
        for o in self._iter(stop):
            if o > dt or (inc and o == dt):
                return o
        return None
