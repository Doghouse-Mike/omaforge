"""Tasks: reading notes as TaskNotes tasks, and every mutation the UI makes.

Write formats follow what TaskNotes 4.13 itself produces (verified by having
the plugin perform each operation in a test vault and diffing the files):

- timestamps: 2026-10-06T22:24:04.581+01:00 (local, ms, offset)
- completedDate / instance dates: YYYY-MM-DD
- every write bumps dateModified
- completing a recurring task appends the *current occurrence* (the
  scheduled date) to complete_instances and moves scheduled to the next
  occurrence that is neither completed nor skipped
- archiving adds the archive tag and, with moveArchivedTasks, moves the note
  between the tasks and archive folders
"""
import json
import os
import re
import subprocess
from datetime import date, datetime, timedelta

from . import recurrence
from .frontmatter import FrontmatterError, Note
from .vault import VaultError, file_hash

INVALID_FILENAME = re.compile(r'[<>:"/\\|?*#\[\]]')


def today():
    return date.today().isoformat()


def now_ts():
    n = datetime.now().astimezone()
    off = n.strftime("%z")
    return n.strftime("%Y-%m-%dT%H:%M:%S.") + "%03d" % (n.microsecond // 1000) + off[:3] + ":" + off[3:]


def as_list(v):
    if v is None or v == "":
        return []
    if isinstance(v, list):
        return [x for x in v if x is not None and x != ""]
    return [v]


def norm_tag(t):
    """TaskNotes' tag normalisation: trim, drop one leading #, whitespace
    runs become '-'."""
    t = str(t).strip()
    if t.startswith("#"):
        t = t[1:].strip()
    return re.sub(r"\s+", "-", t)


def tag_matches(tag, want):
    tag, want = tag.lower(), want.lower()
    return tag == want or tag.startswith(want + "/")


def link_target(v):
    """'[[Folder/Note|Alias]]' -> ('Folder/Note', 'Alias')."""
    s = str(v).strip()
    m = re.match(r"^\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|([^\]]+))?\]\]$", s)
    if m:
        return m.group(1).strip(), (m.group(2) or "").strip()
    m = re.match(r"^\[([^\]]*)\]\(([^)]+)\)$", s)  # markdown link
    if m:
        return m.group(2).strip(), m.group(1).strip()
    return s, ""


def link_display(v):
    target, alias = link_target(v)
    if alias:
        return alias
    return os.path.basename(target)[:-3] if target.endswith(".md") else os.path.basename(target)


# ------------------------------------------------------------------ reading ---

def is_task(vault, data):
    s = vault.settings
    if not isinstance(data, dict):
        return False
    if s.id_method == "property":
        if not (s.prop_name and s.prop_value):
            return False
        v = data.get(s.prop_name)
        for x in as_list(v):
            if isinstance(x, bool):
                if s.prop_value.lower() in ("true", "false") and x == (s.prop_value.lower() == "true"):
                    return True
            elif x == s.prop_value:
                return True
        return False
    return any(tag_matches(norm_tag(t), s.task_tag) for t in tags_of(data))


def tags_of(data):
    """Only the frontmatter `tags` key counts, and a string value is ONE tag
    (never split on commas/spaces) -- exactly as TaskNotes reads it."""
    v = data.get("tags")
    if isinstance(v, str):
        items = [v] if v.strip() else []
    elif isinstance(v, list):
        items = [str(x) for x in v if x is not None]
    else:
        items = []
    out = []
    for t in items:
        n = norm_tag(t)
        if n and n not in out:
            out.append(n)
    return out


def excluded(vault, rel):
    return any(rel == f or rel.startswith(f + "/") for f in vault.settings.excluded)


def norm_choice(value, choices, default):
    """Status/priority normalisation: exact value, unique exact label,
    case-insensitive value, case-insensitive label; unknown kept as-is."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return default
    if isinstance(value, list):
        if len(value) != 1:
            return default
        value = value[0]
    v = str(value)
    for c in choices:
        if c.get("value") == v:
            return v
    labels = [c for c in choices if c.get("label") == v]
    if len(labels) == 1:
        return labels[0]["value"]
    for c in choices:
        if str(c.get("value", "")).lower() == v.lower():
            return c["value"]
    for c in choices:
        if str(c.get("label", "")).lower() == v.lower():
            return c["value"]
    return v


def in_task_area(vault, rel):
    """Unparseable notes only count as 'problems' when they sit where tasks
    live -- a broken note elsewhere in the vault is none of our business."""
    s = vault.settings
    return rel.startswith(s.tasks_folder + "/") or rel.startswith(s.archive_folder + "/")


def task_for(vault, rel, day, index=None):
    e = vault.entries.get(rel)
    if not e or e.data is None:
        return None
    if e.error:
        if not in_task_area(vault, rel):
            return None
        return {"path": rel, "title": os.path.basename(rel)[:-3], "error": e.error,
                "status": "", "priority": "", "done": False, "archived": False, "raw": {}, "expect": {}}
    if excluded(vault, rel) or not is_task(vault, e.data):
        return None
    return build(vault, rel, e.data, day, index)


RAW_FIELDS = ["title", "status", "priority", "due", "scheduled", "contexts", "projects",
              "recurrence", "completeInstances", "skippedInstances", "completedDate",
              "blockedBy", "timeEstimate", "dateCreated", "dateModified", "reminders"]


def build(vault, rel, d, day, index=None):
    s = vault.settings
    f = s.f
    raw = {name: d.get(f(name)) for name in RAW_FIELDS}
    raw["tags"] = d.get("tags")
    title = d.get(f("title"))
    if isinstance(title, list):
        title = ", ".join(str(x) for x in title)
    title = str(title).strip() if title is not None and str(title).strip() else os.path.basename(rel)[:-3]
    all_tags = tags_of(d)
    archived = any(t.lower() == s.f("archiveTag").lower() for t in all_tags)
    hide = {s.task_tag.lower(), s.f("archiveTag").lower()}
    status = norm_choice(d.get(f("status")), s.statuses, s.default_status)
    anchor = "completion" if str(d.get(f("recurrenceAnchor")) or "") == "completion" else "scheduled"
    rec = d.get(f("recurrence"))
    rec = rec if isinstance(rec, str) and rec.strip() else ""
    completed = [str(x)[:10] for x in as_list(d.get(f("completeInstances")))]
    skipped = [str(x)[:10] for x in as_list(d.get(f("skippedInstances")))]
    scheduled = str(d.get(f("scheduled")) or "")
    occurrence = ""
    if rec:
        occurrence = scheduled[:10] or recurrence.next_open(
            rec, day, completed, skipped, anchor, fallback_start=date_or_none(d.get(f("dateCreated")))) or ""
    blocked_by = []
    for b in as_list(d.get(f("blockedBy"))):
        uid = b.get("uid") if isinstance(b, dict) else b
        if not uid:
            continue
        target = resolve_link(vault, str(uid), rel, index)
        info = {"title": link_display(uid), "path": target or "", "done": False}
        if target and target in vault.entries and vault.entries[target].data and not excluded(vault, target):
            td = vault.entries[target].data
            info["done"] = s.is_completed(norm_choice(td.get(f("status")), s.statuses, s.default_status))
            t2 = td.get(f("title"))
            info["title"] = str(t2) if t2 else os.path.basename(target)[:-3]
        blocked_by.append(info)
    return {
        "path": rel,
        "title": title,
        "status": status,
        "done": s.is_completed(status),
        "priority": norm_choice(d.get(f("priority")), s.priorities, "normal"),
        "due": str(d.get(f("due")) or ""),
        "scheduled": scheduled,
        "contexts": [str(c).lstrip("@") for c in as_list(d.get(f("contexts")))],
        "projectsRaw": [str(p) for p in as_list(d.get(f("projects")))],
        "projects": [link_display(p) for p in as_list(d.get(f("projects")))],
        "tags": [t for t in all_tags if t.lower() not in hide],
        "archived": archived,
        "recurring": bool(rec),
        "recurrence": rec,
        "recurrenceText": recurrence.describe(rec) if rec else "",
        "occurrence": occurrence,
        "completeInstances": completed,
        "skippedInstances": skipped,
        "completedDate": str(d.get(f("completedDate")) or ""),
        "dateCreated": str(d.get(f("dateCreated")) or ""),
        "dateModified": str(d.get(f("dateModified")) or ""),
        "blockedBy": blocked_by,
        "blocked": any(not b["done"] for b in blocked_by),
        "timeEstimate": d.get(f("timeEstimate")) or 0,
        "error": None,
        "props": jsonable(d),          # full frontmatter, for Bases filters
        "mtime": mtime_ms(vault, rel),
        "raw": jsonable(raw),
        "expect": jsonable(raw),
    }


def mtime_ms(vault, rel):
    e = vault.entries.get(rel)
    return e.mtime // 1_000_000 if e else 0


def date_or_none(v):
    try:
        return date.fromisoformat(str(v)[:10])
    except (ValueError, TypeError):
        return None


def jsonable(v):
    return json.loads(json.dumps(v, default=str))


def resolve_link(vault, target, from_rel, index=None):
    """Resolve a wikilink target to a vault path the way Obsidian would:
    exact path first, then a unique basename match."""
    t, _ = link_target(target)
    t = t[:-3] if t.endswith(".md") else t
    if (t + ".md") in vault.entries:
        return t + ".md"
    rel_dir = os.path.dirname(from_rel)
    cand = os.path.normpath(os.path.join(rel_dir, t)) + ".md"
    if cand in vault.entries:
        return cand
    idx = index if index is not None else basename_index(vault)
    hits = idx.get(os.path.basename(t).lower())
    return hits[0] if hits else None


def basename_index(vault):
    idx = {}
    for rel in vault.entries:
        idx.setdefault(os.path.basename(rel)[:-3].lower(), []).append(rel)
    for v in idx.values():
        v.sort(key=lambda r: (r.count("/"), r))  # Obsidian prefers the shallowest
    return idx


def all_tasks(vault, day):
    if getattr(vault, "mode", "tasknotes") == "tasks":
        from . import inline
        return inline.all_tasks(vault, day)
    return _all_tasknotes(vault, day)


def _all_tasknotes(vault, day):
    idx = basename_index(vault)
    out = []
    for rel in vault.entries:
        t = task_for(vault, rel, day, idx)
        if t:
            out.append(t)
    return out


# ------------------------------------------------------------------ writing ---

def load(vault, rel):
    text = vault.read(rel)
    note = Note(text)
    try:
        data = note.data()
    except FrontmatterError as e:
        raise VaultError("unparseable", "%s has invalid properties (%s); fix it in Obsidian first" % (rel, e))
    if not is_task(vault, data):
        raise VaultError("not-task", "%s is no longer a task" % rel)
    return text, note, data


def check_expect(vault, rel, data, expect):
    """Field-level compare-and-swap: refuse if any field we're about to touch
    no longer holds the value the UI showed."""
    for name, shown in (expect or {}).items():
        key = "tags" if name == "tags" else vault.settings.f(name)
        now = jsonable(data.get(key))
        if now != shown:
            raise VaultError("conflict", "%s: '%s' changed on disk (now %s); showing the new version" % (
                os.path.basename(rel)[:-3], name, json.dumps(now)))


def commit(vault, rel, text, note, day):
    note.set(vault.settings.f("dateModified"), now_ts())
    vault.write(rel, note.render(), expect_hash=file_hash(text))
    return task_for(vault, rel, day)


def result(task, removed=None):
    r = {"task": task, "path": task["path"] if task else None, "_upsert": [task] if task else []}
    if removed:
        r["_remove"] = removed
    return r


def first_completed_status(s):
    for st in s.statuses:
        if st.get("isCompleted"):
            return st["value"]
    return "done"


def open_status(s):
    st = s.status(s.default_status)
    if st and not st.get("isCompleted"):
        return s.default_status
    for st in s.statuses:
        if not st.get("isCompleted"):
            return st["value"]
    return "open"


def is_recurring(s, data):
    rec = data.get(s.f("recurrence"))
    return isinstance(rec, str) and bool(rec.strip())


def apply_status(s, note, data, status, day):
    """Spec §3: completing (non-recurring) always re-stamps completedDate;
    leaving a completed status deletes it; recurring tasks never touch it."""
    note.set(s.f("status"), status)
    if is_recurring(s, data):
        return
    if s.is_completed(status):
        note.set(s.f("completedDate"), day)
    else:
        note.remove(s.f("completedDate"))


def op_set_status(vault, req, day):
    rel = req["path"]
    s = vault.settings
    text, note, data = load(vault, rel)
    check_expect(vault, rel, data, pick(req.get("expect"), ["status"]))
    status = str(req["status"])
    st = s.status(status)
    if not st:
        raise VaultError("bad-status", "unknown status %r" % status)
    apply_status(s, note, data, status, day)
    task = commit(vault, rel, text, note, day)
    # TaskNotes only auto-archives while Obsidian is running and saw the
    # change, so a status set here would never be archived. Do it now.
    if st.get("autoArchive") and not is_recurring(s, data) and task and not task["archived"]:
        r = op_archive(vault, {"path": task["path"], "on": True}, day)
        r["note"] = "%s tasks are auto-archived" % (st.get("label") or status)
        return r
    return result(task)


def pick(d, keys):
    return {k: v for k, v in (d or {}).items() if k in keys}


def op_toggle_complete(vault, req, day):
    rel = req["path"]
    s = vault.settings
    text, note, data = load(vault, rel)
    if is_recurring(s, data):
        return recurring_mark(vault, req, day, "completeInstances")
    check_expect(vault, rel, data, pick(req.get("expect"), ["status"]))
    status = norm_choice(data.get(s.f("status")), s.statuses, s.default_status)
    new = open_status(s) if s.is_completed(status) else first_completed_status(s)
    apply_status(s, note, data, new, day)
    return result(commit(vault, rel, text, note, day))


def op_skip(vault, req, day):
    return recurring_mark(vault, req, day, "skippedInstances")


def recurring_mark(vault, req, day, list_name):
    """Spec §4.4: toggle one occurrence in complete_instances or
    skipped_instances, then move scheduled (and due, if it would fall behind)
    to the next open occurrence on/after max(today, instance)."""
    rel = req["path"]
    s = vault.settings
    f = s.f
    text, note, data = load(vault, rel)
    check_expect(vault, rel, data, pick(req.get("expect"), ["scheduled", "completeInstances", "skippedInstances", "recurrence"]))
    rule = str(data.get(f("recurrence")))
    anchor = "completion" if str(data.get(f("recurrenceAnchor")) or "") == "completion" else "scheduled"
    scheduled = str(data.get(f("scheduled")) or "")
    due = str(data.get(f("due")) or "")
    created = date_or_none(data.get(f("dateCreated")))
    fallback = date_or_none(scheduled) or created
    completed = [str(x)[:10] for x in as_list(data.get(f("completeInstances")))]
    skipped = [str(x)[:10] for x in as_list(data.get(f("skippedInstances")))]
    # Completion-anchored repeats count from when you actually did it.
    default = day if anchor == "completion" else (scheduled[:10] or due[:10] or day)
    target = (req.get("date") or default)[:10]
    inst = recurrence.instance_for(rule, target, completed, skipped, anchor, fallback)

    mine, other = (completed, skipped) if list_name == "completeInstances" else (skipped, completed)
    adding = inst not in mine
    if adding:
        mine.append(inst)
        if inst in other:
            other.remove(inst)
    else:
        mine.remove(inst)

    if anchor == "completion" and list_name == "completeInstances" and adding:
        if not recurrence.has_dtstart(rule):
            rule = recurrence.with_dtstart(rule, scheduled, str(data.get(f("dateCreated")) or ""))
        rule = recurrence.set_dtstart_date(rule, inst)
    # (The spec says scheduled-anchor completions add a missing DTSTART too;
    # TaskNotes 4.13.8 observably doesn't, and we follow the plugin.)

    time_suffix = scheduled[10:] if len(scheduled) > 10 else ""
    # Scheduled anchor: the working copy's scheduled becomes the instance
    # before advancing; completion anchor keeps the old scheduled (so due's
    # offset is measured from it).
    work_sched = scheduled if anchor == "completion" else inst + time_suffix
    floor = max(day, inst)
    nxt = recurrence.next_open(rule, floor, completed, skipped, anchor, fallback)
    new_sched, new_due = scheduled, due
    if nxt:
        new_sched = nxt + time_suffix
        if due and work_sched:
            try:
                if due[:10] < nxt:
                    delta = d10(due) - d10(work_sched)
                    new_due = (d10(nxt) + delta).isoformat() + due[10:]
            except ValueError:
                pass

    note.set(f("completeInstances"), completed)
    note.set(f("skippedInstances"), skipped)
    if rule != str(data.get(f("recurrence"))):
        note.set(f("recurrence"), rule)
    if new_sched:
        note.set(f("scheduled"), new_sched)
    if new_due:
        note.set(f("due"), new_due)
    return result(commit(vault, rel, text, note, day))


def d10(v):
    return date.fromisoformat(str(v)[:10])


def op_update(vault, req, day):
    rel = req["path"]
    s = vault.settings
    f = s.f
    text, note, data = load(vault, rel)
    fields = req.get("set") or {}
    check_expect(vault, rel, data, {k: v for k, v in (req.get("expect") or {}).items() if k != "title"})
    new_title = None
    for name, value in fields.items():
        if name == "title":
            new_title = str(value).strip()
            continue
        if name == "status":
            apply_status(s, note, data, str(value), day)
        elif name == "tags":
            # Keep the identifying + archive tags whatever the UI sent (it
            # hides them); TaskNotes' edit path appends the task tag.
            keep_lower = (s.task_tag.lower(), f("archiveTag").lower())
            visible = []
            for t in as_list(value):
                n = norm_tag(t)
                if n and n.lower() not in keep_lower and n not in visible:
                    visible.append(n)
            current = tags_of(data)
            out = [t for t in current if t.lower() in keep_lower or t in visible]
            out += [t for t in visible if t not in out]
            if s.id_method == "tag" and not any(tag_matches(t, s.task_tag) for t in out):
                out.append(s.task_tag)
            if out:
                note.set("tags", out)
            else:
                note.remove("tags")
        elif name in ("due", "scheduled", "priority"):
            v = str(value or "").strip()
            if v:
                note.set(f(name), v)
            else:
                note.remove(f(name))
            if name == "scheduled" and v and is_recurring(s, data):
                old = str(data.get(f("scheduled")) or "")
                if v[:10] != old[:10]:
                    # §3: rescheduling a recurring task drops instance marks
                    # on/after the new date; empty lists lose their key.
                    for lname in ("completeInstances", "skippedInstances"):
                        vals = [str(x)[:10] for x in as_list(data.get(f(lname)))]
                        kept = [x for x in vals if x < v[:10]]
                        if kept != vals:
                            if kept:
                                note.set(f(lname), kept)
                            else:
                                note.remove(f(lname))
                    rule = str(data.get(f("recurrence")))
                    if not recurrence.has_dtstart(rule):
                        note.set(f("recurrence"), recurrence.with_dtstart(rule, v, str(data.get(f("dateCreated")) or "")))
        elif name == "recurrence":
            set_recurrence(s, note, data, str(value or "").strip(), day)
        elif name == "recurrenceAnchor":
            if value not in ("scheduled", "completion"):
                raise VaultError("bad-field", "anchor must be scheduled or completion")
            note.set(f("recurrenceAnchor"), value)
        elif name == "blockedBy":
            deps = []
            for b in as_list(value):
                if isinstance(b, dict) and b.get("path"):
                    deps.append({"uid": "[[%s]]" % linktext(vault, b["path"]), "reltype": "FINISHTOSTART"})
                elif isinstance(b, dict) and b.get("uid"):
                    deps.append({k: str(b[k]) for k in ("uid", "reltype", "gap") if b.get(k)})
                else:
                    raise VaultError("bad-field", "malformed dependency %r" % (b,))
            if deps:
                note.set(f("blockedBy"), deps)
            else:
                note.remove(f("blockedBy"))
        elif name == "reminders":
            # TaskNotes' Reminder shape, in its key order.
            rems = []
            for r in as_list(value):
                if not isinstance(r, dict) or r.get("type") not in ("relative", "absolute"):
                    raise VaultError("bad-field", "malformed reminder %r" % (r,))
                keys = ["id", "type"] + (["relatedTo", "offset"] if r["type"] == "relative" else ["absoluteTime"]) + ["description"]
                rems.append({k: str(r[k]) for k in keys if r.get(k) not in (None, "")})
            # TaskNotes keeps an emptied list as `reminders: []`.
            note.set(f("reminders"), rems)
        elif name in ("contexts", "projects"):
            vals = [str(x) for x in as_list(value)]
            if vals:
                note.set(f(name), vals)
            else:
                note.remove(f(name))
        else:
            raise VaultError("bad-field", "can't edit %r here" % name)
    if new_title is not None:
        return retitle(vault, rel, text, note, data, new_title, day)
    return result(commit(vault, rel, text, note, day))


def linktext(vault, rel):
    """Obsidian's shortest link text: the bare name if it's unique in the
    vault, otherwise the path without .md."""
    stem = os.path.basename(rel)[:-3]
    same = [r for r in vault.entries if os.path.basename(r)[:-3].lower() == stem.lower()]
    return stem if len(same) <= 1 else rel[:-3]


def set_recurrence(s, note, data, body, day):
    """TaskNotes' edit-path rules (verified against 4.13.8): clearing removes
    `recurrence` only; setting one moves scheduled to the first occurrence
    from today on (counting the rule from the old scheduled date, else
    dateCreated, skipping done/skipped occurrences), moves due by the same
    amount if there was a scheduled date, and sets DTSTART to that day."""
    f = s.f
    if not body:
        note.remove(f("recurrence"))
        return
    body = re.sub(r"DTSTART:[^;]+;?", "", body).strip().lstrip(";")
    if body.upper().startswith("RRULE:"):
        body = body[6:]
    if "FREQ=" not in body.upper():
        raise VaultError("bad-field", "not a repeat rule: %r" % body)
    sched = str(data.get(f("scheduled")) or "")
    due = str(data.get(f("due")) or "")
    basis = date_or_none(sched) or date_or_none(data.get(f("dateCreated"))) or date_or_none(day)
    completed = [str(x)[:10] for x in as_list(data.get(f("completeInstances")))]
    skipped = [str(x)[:10] for x in as_list(data.get(f("skippedInstances")))]
    nxt = recurrence.next_open("DTSTART:%s;%s" % (basis.strftime("%Y%m%d"), body), day, completed, skipped)
    if not nxt:
        raise VaultError("bad-field", "that rule has no upcoming dates")
    suffix = sched[10:] if len(sched) > 10 else ""
    if suffix:
        hm = suffix[1:].replace(":", "")
        dtstart = "%sT%s00Z" % (nxt.replace("-", ""), hm[:4])
    else:
        dtstart = nxt.replace("-", "")
    note.set(f("recurrence"), "DTSTART:%s;%s" % (dtstart, body))
    note.set(f("scheduled"), nxt + suffix)
    if due and sched:
        try:
            moved = d10(nxt) - d10(sched)
            note.set(f("due"), (d10(due) + moved).isoformat() + due[10:])
        except ValueError:
            pass


def sanitize_title(title):
    s = re.sub(r"\s+", " ", str(title).strip())
    s = "".join(c for c in s if not (ord(c) <= 31 or 127 <= ord(c) <= 159)).strip()
    return s or "untitled"


RESERVED = re.compile(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])$", re.IGNORECASE)


def sanitize_filename(title):
    s = sanitize_title(title)
    s = INVALID_FILENAME.sub("", s)
    s = re.sub(r"^\.+|\.+$", "", s).strip()
    s = s or "untitled"
    if RESERVED.match(s):
        s = "task-" + s
    return s


def backlinks(vault, rel):
    """Notes that link to rel by name. A plain on-disk rename would break
    them (only Obsidian's own rename rewrites links)."""
    stem = re.escape(os.path.basename(rel)[:-3])
    path_noext = re.escape(rel[:-3])
    pat = re.compile(r"\[\[(?:%s|%s)(?:\.md)?[|#\]]" % (stem, path_noext), re.IGNORECASE)
    hits = []
    for full in vault.walk():
        r = vault.rel(full)
        if r == rel:
            continue
        try:
            with open(full, encoding="utf-8", errors="replace") as fh:
                if pat.search(fh.read()):
                    hits.append(r)
        except OSError:
            pass
    return hits


def retitle(vault, rel, text, note, data, title, day):
    """TaskNotes renames the note when titles live in filenames. We do the
    same unless other notes link to it: Obsidian's rename would rewrite those
    links, ours can't, so we keep the filename and store `title:` instead --
    TaskNotes reads that identically."""
    s = vault.settings
    tkey = s.f("title")
    stored = sanitize_title(title)
    if not s.store_title_in_filename:
        note.set(tkey, stored)
        return result(commit(vault, rel, text, note, day))
    stem = sanitize_filename(stored)
    folder = os.path.dirname(rel)
    new_rel = (folder + "/" if folder else "") + stem + ".md"
    links = backlinks(vault, rel) if new_rel != rel else []
    if new_rel == rel or links:
        if os.path.basename(rel)[:-3] == stored:
            note.remove(tkey)
        else:
            note.set(tkey, stored)
        r = result(commit(vault, rel, text, note, day))
        if links:
            r["note"] = "Kept the filename because %d note(s) link to it; title saved as a property" % len(links)
        return r
    new_rel = unique_path(vault, folder, stem)
    if os.path.basename(new_rel)[:-3] == stored:
        note.remove(tkey)
    else:
        note.set(tkey, stored)
    commit(vault, rel, text, note, day)
    vault.move(rel, new_rel)
    return result(task_for(vault, new_rel, day), removed=[rel])


def unique_path(vault, folder, stem):
    """name.md, then name-2.md ... name-999.md (spec §2.2)."""
    base = (folder + "/" if folder else "")
    rel = base + stem + ".md"
    if not os.path.lexists(vault.abs(rel)):
        return rel
    for i in range(2, 1000):
        rel = "%s%s-%d.md" % (base, stem, i)
        if not os.path.lexists(vault.abs(rel)):
            return rel
    return "%s%s-%s.md" % (base, stem[:50], base36(int(datetime.now().timestamp() * 1000)))


def op_archive(vault, req, day):
    """Spec §5: a tag, not a status. Archive appends the tag and moves the
    note to the archive folder; unarchive removes it and moves the note to
    the tasks folder root. If the destination exists the tag change stands
    and the note stays put."""
    rel = req["path"]
    s = vault.settings
    atag = s.f("archiveTag")
    text, note, data = load(vault, rel)
    check_expect(vault, rel, data, pick(req.get("expect"), ["tags"]))
    on = bool(req.get("on"))
    raw = data.get("tags")
    if on:
        tags = [] if raw is None else list(raw) if isinstance(raw, list) else [raw]
        if atag not in [str(t) for t in tags]:
            tags.append(atag)
        note.set("tags", [str(t) for t in tags])
    else:
        if isinstance(raw, list):
            tags = [t for t in raw if str(t) != atag]
            if tags:
                note.set("tags", [str(t) for t in tags])
            else:
                note.remove("tags")
    commit(vault, rel, text, note, day)
    new_rel, msg = rel, None
    if s.move_archived:
        dest = (s.archive_folder if on else s.tasks_folder) + "/" + os.path.basename(rel)
        if dest != rel:
            if os.path.lexists(vault.abs(dest)):
                msg = "%s, but not moved: %s already exists" % ("Archived" if on else "Unarchived", dest)
            else:
                new_rel = vault.move(rel, dest)
    r = result(task_for(vault, new_rel, day), removed=[rel] if new_rel != rel else None)
    if msg:
        r["note"] = msg
    return r


def op_create(vault, req, day):
    """Spec §2: fixed key order, tags last with the task tag first, title:
    only when the filename can't represent it, '---\\n\\n' even with no body."""
    s = vault.settings
    f = s.f
    vault.check_writable()
    fields = req.get("fields") or {}
    if not str(fields.get("title") or "").strip():
        raise VaultError("bad-title", "title can't be empty")
    stored = sanitize_title(fields["title"])
    if s.store_title_in_filename or s.filename_format == "title":
        stem = sanitize_filename(stored)
    elif s.filename_format == "timestamp":
        stem = datetime.now().strftime("%Y-%m-%d-%H%M%S")
    else:
        n = datetime.now()
        stem = n.strftime("%y%m%d") + base36(n.hour * 3600 + n.minute * 60 + n.second)
    rel = unique_path(vault, s.tasks_folder, stem)
    ts = now_ts()
    note = Note("---\n---\n")
    note.body = "\n"
    if not (s.store_title_in_filename and os.path.basename(rel)[:-3] == stored):
        note.set(f("title"), stored)
    status = str(fields.get("status") or s.default_status or "todo")
    note.set(f("status"), status)
    note.set(f("priority"), str(fields.get("priority") or s.default_priority or "normal"))
    for name in ("due", "scheduled"):
        if fields.get(name):
            note.set(f(name), str(fields[name]))
    for name in ("contexts", "projects"):
        vals = [str(x) for x in as_list(fields.get(name))]
        if vals:
            note.set(f(name), vals)
    rec = str(fields.get("recurrence") or "").strip()
    if not rec and s.is_completed(status):
        note.set(f("completedDate"), day)
    if rec:
        note.set(f("recurrence"), recurrence.with_dtstart(rec, str(fields.get("scheduled") or ""), ts))
    note.set(f("dateCreated"), ts)
    note.set(f("dateModified"), ts)
    tags = []
    if s.id_method == "tag":
        tags.append(s.task_tag)
    for t in as_list(fields.get("tags")):
        n = norm_tag(t)
        if n and n.lower() not in [x.lower() for x in tags]:
            tags.append(n)
    for r in as_list(fields.get("reminders")):
        if isinstance(r, dict):
            keys = ["id", "type"] + (["relatedTo", "offset"] if r.get("type") == "relative" else ["absoluteTime"]) + ["description"]
            note.set(f("reminders"), [{k: str(x[k]) for k in keys if x.get(k) not in (None, "")}
                                     for x in as_list(fields.get("reminders")) if isinstance(x, dict)])
            break
    if s.id_method == "property" and s.prop_name:
        note.set(s.prop_name, s.prop_value)
    if tags:
        note.set("tags", tags)
    if fields.get("body"):
        note.body = "\n" + str(fields["body"]).replace("\r\n", "\n").strip("\n") + "\n"
    vault.write(rel, note.render(), create=True)
    return result(task_for(vault, rel, day))


def op_duplicate(vault, req, day):
    """A fresh, open copy of a task: same properties, reminders and notes;
    no completion history, no dependencies."""
    import time as _time
    s = vault.settings
    f = s.f
    rel = req["path"]
    text, note, data = load(vault, rel)
    t = build(vault, rel, data, day)   # from the note as read now, not the scan cache
    rec = str(data.get(f("recurrence")) or "")
    rec = re.sub(r"DTSTART:[^;]+;?", "", rec).strip()
    rems = []
    for i, r in enumerate(as_list(data.get(f("reminders")))):
        if isinstance(r, dict):
            r = dict(r)
            r["id"] = "rem_%d_%d" % (int(_time.time() * 1000), i)
            rems.append(r)
    fields = {
        "title": t["title"] + " (copy)",
        "priority": t["priority"],
        "due": data.get(f("due")) or "",
        "scheduled": data.get(f("scheduled")) or "",
        "contexts": t["contexts"],
        "projects": t["projectsRaw"],
        "tags": t["tags"],
        "recurrence": rec,
        "reminders": rems,
        "body": note.body,
    }
    return op_create(vault, {"fields": fields}, day)


def base36(n):
    chars = "0123456789abcdefghijklmnopqrstuvwxyz"
    out = ""
    while True:
        n, r = divmod(n, 36)
        out = chars[r] + out
        if not n:
            return out


def op_delete(vault, req, day):
    rel = req["path"]
    vault.check_writable()
    text, note, data = load(vault, rel)
    check_expect(vault, rel, data, pick(req.get("expect"), ["status", "title"]))
    full = vault.abs(rel)
    option = vault.app_setting("trashOption", "system")
    if option == "local":
        dest = ".trash/" + os.path.basename(rel)
        i = 1
        while os.path.lexists(vault.abs(dest)):
            dest = ".trash/%s %d.md" % (os.path.basename(rel)[:-3], i)
            i += 1
        os.makedirs(vault.abs(".trash"), exist_ok=True)
        os.rename(full, vault.abs(dest))
        where = "the vault's .trash folder"
    else:
        # "system" (Obsidian's default) and "none" both go to the system
        # trash: we never permanently delete a note.
        r = subprocess.run(["gio", "trash", "--", full], capture_output=True, text=True)
        if r.returncode != 0:
            raise VaultError("trash-failed", "couldn't move to trash: %s" % r.stderr.strip())
        where = "the system trash"
    vault.entries.pop(rel, None)
    return {"trashedTo": where, "_remove": [rel]}


def op_body(vault, req, day):
    rel = req["path"]
    text = vault.read(rel)
    note = Note(text)
    return {"body": note.body, "hash": file_hash(text)}


def op_save_body(vault, req, day):
    rel = req["path"]
    text = vault.read(rel)
    if file_hash(text) != req.get("hash"):
        raise VaultError("conflict", "The note changed on disk while you were editing; your text is still in the editor — copy it, then reselect the task")
    note = Note(text)
    try:
        data = note.data()
    except FrontmatterError as e:
        raise VaultError("unparseable", str(e))
    body = str(req.get("body", ""))
    if note.newline != "\n":
        body = body.replace("\r\n", "\n").replace("\n", note.newline)
    note.body = body
    note.tail_sep = True
    if note.has_fm and is_task(vault, data):
        note.set(vault.settings.f("dateModified"), now_ts())
    new_text = note.render()
    vault.write(rel, new_text, expect_hash=file_hash(text))
    task = task_for(vault, rel, day)
    return {"hash": file_hash(new_text), "task": task, "_upsert": [task] if task else []}


OPS = {
    "update": op_update,
    "setStatus": op_set_status,
    "toggleComplete": op_toggle_complete,
    "skipInstance": op_skip,
    "archive": op_archive,
    "create": op_create,
    "duplicate": op_duplicate,
    "delete": op_delete,
    "body": op_body,
    "saveBody": op_save_body,
}
