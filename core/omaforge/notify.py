"""omaforge-notify: notifications while OmaForge's window is closed.

A small long-running loop (systemd user service) that polls the vault and
sends desktop notifications through the Omarchy shell's notification server:

- TaskNotes reminders (the `reminders:` property, relative or absolute), with
  TaskNotes' own rules: a reminder fires once per (task, reminder id, time),
  up to 24h late (catch-up after sleep/boot), never for a completed task or
  completed occurrence, never for an archived task.
- Tasks with a time (`due`/`scheduled` like 2026-10-08T14:00), optionally
  some minutes early.
- A morning summary and an overdue nudge, once a day each at set times.

Each kind is switched and tuned in config.json -> "notifications". Buttons on
a notification act through the same guarded ops as the app (Done = the
app's toggle-complete, so a repeating task completes its occurrence).
"""
import json
import os
import re
import subprocess
import sys
import threading
import time
from datetime import date, datetime, timedelta

from . import tasks
from .vault import CONFIG, Vault, VaultError, load_config

STATE = os.path.expanduser(os.environ.get("OMAFORGE_NOTIFY_STATE", "~/.local/state/omaforge/notify.json"))
APP_DIR = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", "..", "app"))
LAUNCHER = os.path.realpath(os.path.join(APP_DIR, "..", "bin", "omaforge"))
POLL_SEC = 15
CATCH_UP = 24 * 3600

DEFAULTS = {
    "reminders": {"enabled": True},
    "timedTasks": {"enabled": True, "minutesBefore": 0},
    "morningSummary": {"enabled": True, "time": "09:00"},
    "overdue": {"enabled": True, "time": "17:00"},
    "snoozeMinutes": 15,
}


def settings(cfg=None):
    """Notification settings with defaults filled in, per section."""
    raw = (cfg if cfg is not None else load_config()).get("notifications") or {}
    out = json.loads(json.dumps(DEFAULTS))
    for k, v in raw.items():
        if isinstance(out.get(k), dict) and isinstance(v, dict):
            out[k].update(v)
        elif k in out:
            out[k] = v
    return out


# ------------------------------------------------------------------ time ----

DUR = re.compile(r"^([+-])?P(?:(\d+)Y)?(?:(\d+)M)?(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?$")


def duration_s(iso):
    """ISO 8601 duration -> seconds, as TaskNotes reads it (M=30d, Y=365d)."""
    m = DUR.match(str(iso or "").strip())
    if not m or not any(m.groups()[1:]):
        return None
    sign, y, mo, w, d, h, mi, s = m.groups()
    total = (int(y or 0) * 365 + int(mo or 0) * 30 + int(w or 0) * 7 + int(d or 0)) * 86400 \
        + int(h or 0) * 3600 + int(mi or 0) * 60 + int(s or 0)
    return -total if sign == "-" else total


def local_ts(value):
    """'2026-10-08' (local midnight), '2026-10-08T14:00[:ss]' (local) or an
    ISO string with an offset -> epoch seconds. None if unparseable."""
    s = str(value or "").strip()
    if not s:
        return None
    try:
        if re.match(r"^\d{4}-\d{2}-\d{2}$", s):
            return datetime.fromisoformat(s).timestamp()
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt.timestamp()  # naive = local time
    except ValueError:
        return None


def has_time(value):
    return bool(re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", str(value or "")))


def hhmm_today(hhmm, now):
    try:
        h, m = (int(x) for x in str(hhmm).split(":", 1))
    except ValueError:
        h, m = 9, 0
    d = datetime.fromtimestamp(now)
    return d.replace(hour=h, minute=m, second=0, microsecond=0).timestamp()


def fmt_offset(seconds):
    s = abs(int(seconds))
    for unit, n in (("day", 86400), ("hour", 3600), ("minute", 60)):
        if s >= n and s % n == 0:
            k = s // n
            return "%d %s%s" % (k, unit, "" if k == 1 else "s")
    return "%d minutes" % max(1, s // 60)


def when_text(ts, now):
    d = datetime.fromtimestamp(ts)
    today = date.fromtimestamp(now)
    hm = d.strftime("%H:%M")
    if d.date() == today:
        return "today %s" % hm
    if d.date() == today + timedelta(days=1):
        return "tomorrow %s" % hm
    return d.strftime("%a %-d %b %H:%M")


# --------------------------------------------------------------- events -----

def instance_done(task, anchor_value):
    """Is the task (or, if repeating, the occurrence on anchor's day) done?"""
    if task.get("recurring"):
        day = str(anchor_value or "")[:10]
        return bool(day) and day in (task.get("completeInstances") or [])
    return bool(task.get("done"))


def reminder_events(task, now, cfg):
    out = []
    for r in task.get("props", {}).get("reminders") or []:
        if not isinstance(r, dict):
            continue
        rid = str(r.get("id") or "")
        anchor_value = None
        if r.get("type") == "absolute":
            at = local_ts(r.get("absoluteTime"))
            body_when = None
        else:
            rel = r.get("relatedTo") if r.get("relatedTo") in ("due", "scheduled") else None
            off = duration_s(r.get("offset"))
            anchor_value = task.get(rel) if rel else None
            base = local_ts(anchor_value)
            if base is None or off is None:
                continue
            at = base + off
            if off < 0:
                body_when = "%s in %s" % (rel.capitalize(), fmt_offset(off))
            elif off == 0:
                body_when = "%s now" % rel.capitalize()
            else:
                body_when = "%s %s ago" % (rel.capitalize(), fmt_offset(off))
        if at is None:
            continue
        # TaskNotes: relative -> the anchor's occurrence; absolute -> the
        # occurrence on the reminder's own day.
        day = anchor_value if anchor_value else date.fromtimestamp(at).isoformat()
        if instance_done(task, day) or task.get("archived"):
            continue
        out.append({"key": json.dumps(["reminder", task["path"], rid, int(at)]), "kind": "reminder",
                    "at": at, "path": task["path"], "title": task["title"],
                    "body": r.get("description") or body_when or "Reminder"})
    return out


def timed_events(task, now, cfg):
    out = []
    early = int(cfg["timedTasks"].get("minutesBefore") or 0) * 60
    for field in ("due", "scheduled"):
        v = task.get(field)
        if not has_time(v) or instance_done(task, v) or task.get("archived"):
            continue
        t = local_ts(v)
        if t is None:
            continue
        label = "Due" if field == "due" else "Scheduled"
        body = "%s %s" % (label, when_text(t, now)) if early else "%s now" % label
        out.append({"key": json.dumps(["timed", task["path"], field, str(v), early]), "kind": "timed",
                    "at": t - early, "path": task["path"], "title": task["title"], "body": body})
    return out


def open_task(t):
    return not t.get("error") and not t.get("done") and not t.get("archived")


def next_day(t):
    days = [str(t.get("due") or "")[:10], str(t.get("occurrence") or t.get("scheduled") or "")[:10]]
    days = [d for d in days if d]
    return min(days) if days else ""


def daily_events(task_list, now, cfg, state):
    out = []
    today = date.fromtimestamp(now).isoformat()
    opened = [t for t in task_list if open_task(t)]
    if cfg["morningSummary"].get("enabled") and state.get("summary") != today \
            and now >= hhmm_today(cfg["morningSummary"].get("time"), now):
        on = [t for t in opened if next_day(t) == today]
        late = [t for t in opened if next_day(t) and next_day(t) < today]
        parts = []
        if on:
            parts.append("%d for today" % len(on))
        if late:
            parts.append("%d overdue" % len(late))
        titles = [t["title"] for t in (late + on)][:4]
        out.append({"key": "summary:" + today, "kind": "summary", "at": now, "path": "", "silent": not parts,
                    "title": "Today: " + (", ".join(parts) if parts else "nothing due"),
                    "body": "\n".join("• " + x for x in titles)})
    if cfg["overdue"].get("enabled") and state.get("overdue") != today \
            and now >= hhmm_today(cfg["overdue"].get("time"), now):
        late = [t for t in opened if next_day(t) and next_day(t) < today]
        out.append({"key": "overdue:" + today, "kind": "overdue", "at": now, "path": "", "silent": not late,
                    "title": "%d overdue task%s" % (len(late), "" if len(late) == 1 else "s"),
                    "body": "\n".join("• " + t["title"] for t in late[:5])})
    return out


def due_events(task_list, now, cfg, state):
    """Everything that should fire now and hasn't. Pure; tested directly."""
    fired = state.get("fired") or {}
    out = []
    for t in task_list:
        if t.get("error"):
            continue
        cand = []
        if cfg["reminders"].get("enabled"):
            cand += reminder_events(t, now, cfg)
        if cfg["timedTasks"].get("enabled"):
            cand += timed_events(t, now, cfg)
        for e in cand:
            if e["key"] not in fired and e["at"] <= now and now - e["at"] <= CATCH_UP:
                out.append(e)
    for key, s in list((state.get("snoozed") or {}).items()):
        if s.get("until", 0) <= now:
            e = dict(s["event"])
            e["key"] = key + ":snoozed:%d" % int(s["until"])
            e["snoozedFrom"] = key
            out.append(e)
    out += daily_events(task_list, now, cfg, state)
    out.sort(key=lambda e: e["at"])
    return out


# ----------------------------------------------------------------- daemon ---

class Daemon:
    def __init__(self):
        self.lock = threading.RLock()
        self.vault = None
        self.cfg_sig = None
        self.cfg = settings({})
        self.state = self.load_state()

    def load_state(self):
        try:
            with open(STATE, encoding="utf-8") as f:
                s = json.load(f)
                return s if isinstance(s, dict) else {}
        except (OSError, ValueError):
            return {}

    def save_state(self):
        os.makedirs(os.path.dirname(STATE), exist_ok=True)
        tmp = STATE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.state, f)
        os.replace(tmp, STATE)

    def reload_config(self):
        try:
            st = os.stat(CONFIG)
            sig = (st.st_mtime_ns, st.st_size)
        except OSError:
            sig = None
        if sig == self.cfg_sig and self.vault:
            return
        self.cfg_sig = sig
        conf = load_config()
        self.cfg = settings(conf)
        path = os.path.expanduser(conf.get("vault") or "")
        if path and (not self.vault or os.path.realpath(path) != self.vault.path):
            try:
                self.vault = Vault(path)
                self.vault.scan()
                log("watching %s" % self.vault.path)
            except VaultError as e:
                self.vault = None
                log("no vault: %s" % e)

    def tick(self):
        with self.lock:
            self.reload_config()
            if not self.vault:
                return
            self.vault.scan()
            now = time.time()
            day = tasks.today()
            task_list = tasks.all_tasks(self.vault, day)
            if not self.state.get("initialised"):
                # First ever run: what's already past is history, not news.
                for e in due_events(task_list, now, self.cfg, self.state):
                    self.mark(e, now)   # incl. today's summary/nudge if their time has passed
                self.state["initialised"] = int(now)
            for e in due_events(task_list, now, self.cfg, self.state):
                self.mark(e, now)
                if not e.get("silent"):
                    self.send(e)
            self.prune(now)
            self.save_state()

    def mark(self, e, now):
        if e["kind"] == "summary":
            self.state["summary"] = e["key"].split(":", 1)[1]
        elif e["kind"] == "overdue":
            self.state["overdue"] = e["key"].split(":", 1)[1]
        else:
            self.state.setdefault("fired", {})[e["key"]] = int(now)
        if e.get("snoozedFrom"):
            self.state.get("snoozed", {}).pop(e["snoozedFrom"], None)

    def prune(self, now):
        fired = self.state.get("fired") or {}
        for k in [k for k, ts in fired.items() if now - ts > 7 * 86400]:
            del fired[k]

    # -- sending --------------------------------------------------------------

    def send(self, e):
        log("notify %s: %s — %s" % (e["kind"], e["title"], e["body"].replace("\n", " | ")))
        threading.Thread(target=self._send, args=(e,), daemon=True).start()

    def _send(self, e):
        cmd = ["notify-send", "--app-name=OmaForge", "--icon=omaforge", "--wait"]
        if e["kind"] in ("reminder", "timed"):
            cmd += ["--expire-time=0", "--action=default=Open", "--action=done=Done",
                    "--action=snooze=Snooze %d min" % int(self.cfg.get("snoozeMinutes") or 15), "--action=open=Open"]
        else:
            cmd += ["--action=default=Open", "--action=open=Open OmaForge"]
        cmd += ["--", e["title"], e["body"]]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=12 * 3600)
            action = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else ""
        except (OSError, subprocess.TimeoutExpired):
            return
        if action:
            self.act(e, action)

    def act(self, e, action):
        log("action %s on %s" % (action, e["key"]))
        if action in ("default", "open"):
            if e.get("path"):
                open_app("openTask", e["path"])
            else:
                open_app("view", "today")
        elif action == "done" and e.get("path"):
            with self.lock:
                try:
                    self.vault.scan()
                    t = tasks.task_for(self.vault, e["path"], tasks.today())
                    if t and not t.get("done"):
                        r = tasks.OPS["toggleComplete"](self.vault, {"path": t["path"], "expect": t["expect"]}, tasks.today())
                        r.pop("_upsert", None)
                except VaultError as ex:
                    notify_plain("Couldn't complete \"%s\"" % e["title"], str(ex))
        elif action == "snooze":
            with self.lock:
                base = e.get("snoozedFrom") or e["key"]
                until = time.time() + 60 * int(self.cfg.get("snoozeMinutes") or 15)
                ev = {k: v for k, v in e.items() if k not in ("key", "snoozedFrom")}
                self.state.setdefault("snoozed", {})[base] = {"until": int(until), "event": ev}
                self.save_state()

    def run(self):
        log("omaforge-notify started")
        while True:
            try:
                self.tick()
            except Exception as ex:  # keep going; a bad note must not stop reminders
                log("tick failed: %s: %s" % (type(ex).__name__, ex))
            time.sleep(POLL_SEC)


def open_app(fn, arg):
    """Raise OmaForge (starting it if needed), then call one IPC function."""
    subprocess.run([LAUNCHER], capture_output=True, timeout=20)
    for _ in range(40):
        r = subprocess.run(["qs", "ipc", "-p", APP_DIR, "call", "omaforge", fn, arg], capture_output=True, text=True)
        if r.returncode == 0:
            return
        time.sleep(0.25)


def notify_plain(title, body):
    subprocess.run(["notify-send", "--app-name=OmaForge", "--icon=omaforge", "--", title, body], capture_output=True)


def log(msg):
    print(msg, flush=True)


def send_test():
    notify_plain("OmaForge notifications are working", "This is a test from the settings panel.")


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        send_test()
        return
    Daemon().run()


# ------------------------------------------------------- app-facing ops -----

SERVICE = "omaforge-notify.service"


def service_state():
    try:
        r = subprocess.run(["systemctl", "--user", "is-active", SERVICE], capture_output=True, text=True, timeout=5)
        active = r.stdout.strip()
        r = subprocess.run(["systemctl", "--user", "is-enabled", SERVICE], capture_output=True, text=True, timeout=5)
        return {"active": active, "enabled": r.stdout.strip()}
    except (OSError, subprocess.TimeoutExpired):
        return {"active": "unknown", "enabled": "unknown"}


DATE_DEFAULTS = {"defaultTime": "09:00", "useDefaultTime": True}


def date_prefs(cfg=None):
    raw = (cfg if cfg is not None else load_config()).get("dates") or {}
    out = dict(DATE_DEFAULTS)
    out.update({k: v for k, v in raw.items() if k in DATE_DEFAULTS})
    return out


def op_get(vault, req, day):
    return {"settings": settings(), "dates": date_prefs(), "service": service_state()}


def op_set(vault, req, day):
    from .vault import save_config
    new = req.get("settings") or {}
    conf = load_config()
    merged = settings({"notifications": new})
    for sec in ("morningSummary", "overdue"):
        if not re.match(r"^\d{1,2}:\d{2}$", str(merged[sec].get("time", ""))):
            raise VaultError("bad-setting", "time must look like 09:00")
    dates = date_prefs({"dates": req.get("dates") or {}})
    if not re.match(r"^\d{2}:\d{2}$", str(dates["defaultTime"])):
        raise VaultError("bad-setting", "default time must look like 09:00")
    conf["notifications"] = merged
    conf["dates"] = dates
    save_config(conf)
    return {"settings": merged, "dates": dates, "service": service_state()}


def op_test(vault, req, day):
    send_test()
    return {"service": service_state()}


OPS = {"getNotify": op_get, "setNotify": op_set, "testNotify": op_test}
