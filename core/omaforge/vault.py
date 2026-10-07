"""The vault: TaskNotes settings, an incremental scan, and guarded writes.

The vault is the only state. Every write is compare-and-swap against what the
UI last saw: if the note changed on disk since then and the change touches a
field we're about to edit, the write is refused as a conflict rather than
merged by guesswork.
"""
import hashlib
import json
import os
import re
import stat
import tempfile

from .frontmatter import FrontmatterError, Note

DEFAULT_FIELDS = {
    "title": "title", "status": "status", "priority": "priority", "due": "due",
    "scheduled": "scheduled", "contexts": "contexts", "projects": "projects",
    "timeEstimate": "timeEstimate", "completedDate": "completedDate",
    "dateCreated": "dateCreated", "dateModified": "dateModified",
    "recurrence": "recurrence", "recurrenceAnchor": "recurrence_anchor",
    "archiveTag": "archived", "completeInstances": "complete_instances",
    "skippedInstances": "skipped_instances", "blockedBy": "blockedBy",
    "reminders": "reminders", "sortOrder": "tasknotes_manual_order",
}

DEFAULT_STATUSES = [
    {"value": "open", "label": "Open", "color": "#808080", "isCompleted": False, "order": 1},
    {"value": "in-progress", "label": "In progress", "color": "#0066cc", "isCompleted": False, "order": 2},
    {"value": "done", "label": "Done", "color": "#00aa00", "isCompleted": True, "order": 3},
]
DEFAULT_PRIORITIES = [
    {"value": "none", "label": "None", "color": "#cccccc", "weight": 0},
    {"value": "low", "label": "Low", "color": "#00aa00", "weight": 1},
    {"value": "normal", "label": "Normal", "color": "#ffaa00", "weight": 2},
    {"value": "high", "label": "High", "color": "#ff0000", "weight": 3},
]

HEAD_BYTES = 256 * 1024
CONFIG = os.path.expanduser(os.environ.get("OMAFORGE_CONFIG", "~/.config/omaforge/config.json"))


def load_config():
    try:
        with open(CONFIG, encoding="utf-8") as f:
            c = json.load(f)
        return c if isinstance(c, dict) else {}
    except (OSError, ValueError):
        return {}


def save_config(conf):
    """Atomically rewrite config.json (OmaForge's own file, not the vault)."""
    os.makedirs(os.path.dirname(CONFIG), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(CONFIG), prefix=".config-", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(conf, f, indent=2)
        f.write("\n")
    os.replace(tmp, CONFIG)


def write_allowed(vault_path):
    """Writes are opt-in per vault: the path must be listed in
    config.json's "writableVaults". Anything else opens read-only."""
    allowed = list(load_config().get("writableVaults") or [])
    # `omaforge --demo` opens a throwaway copy of the bundled demo vault.
    if os.environ.get("OMAFORGE_DEMO_VAULT"):
        allowed.append(os.environ["OMAFORGE_DEMO_VAULT"])
    real = os.path.realpath(vault_path)
    return any(os.path.realpath(os.path.expanduser(str(p))) == real for p in allowed)  # frontmatter lives at the top; never slurp huge notes to scan


class VaultError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


class Settings:
    """TaskNotes' data.json, read-only. If it exists but can't be parsed we
    are 'quarantined': reads work with defaults, writes are refused."""

    def __init__(self, vault_path):
        self.path = os.path.join(vault_path, ".obsidian", "plugins", "tasknotes", "data.json")
        self.raw = {}
        self.quarantined = None
        try:
            with open(self.path, encoding="utf-8") as f:
                self.raw = json.load(f)
            if not isinstance(self.raw, dict):
                raise ValueError("not an object")
        except FileNotFoundError:
            self.quarantined = "TaskNotes settings not found; is the plugin installed in this vault?"
        except (OSError, ValueError) as e:
            self.raw = {}
            self.quarantined = "TaskNotes settings unreadable (%s)" % e
        r = self.raw
        self.fields = dict(DEFAULT_FIELDS)
        self.fields.update({k: v for k, v in (r.get("fieldMapping") or {}).items() if isinstance(v, str) and v})
        self.statuses = sorted(r.get("customStatuses") or DEFAULT_STATUSES, key=lambda s: s.get("order", 0))
        self.priorities = sorted(r.get("customPriorities") or DEFAULT_PRIORITIES, key=lambda p: p.get("weight", 0))
        self.tasks_folder = (r.get("tasksFolder") or "TaskNotes/Tasks").strip("/")
        self.archive_folder = (r.get("archiveFolder") or "TaskNotes/Archive").strip("/")
        self.move_archived = bool(r.get("moveArchivedTasks", False))
        self.id_method = r.get("taskIdentificationMethod") or "tag"
        self.task_tag = (r.get("taskTag") or "task").lstrip("#")
        self.prop_name = r.get("taskPropertyName") or ""
        self.prop_value = r.get("taskPropertyValue") or ""
        self.excluded = [p.strip().strip("/") for p in str(r.get("excludedFolders") or "").split(",") if p.strip()]
        self.default_status = r.get("defaultTaskStatus") or self.statuses[0]["value"]
        self.default_priority = r.get("defaultTaskPriority") or "normal"
        self.store_title_in_filename = bool(r.get("storeTitleInFilename", True))
        self.filename_format = r.get("taskFilenameFormat") or "title"
        self.saved_views = r.get("savedViews") or []
        # Where TaskNotes keeps its .base views (next to the tasks folder).
        parent = os.path.dirname(self.tasks_folder)
        self.views_folder = (parent + "/Views") if parent else "Views"

    def f(self, name):
        """Frontmatter key for an internal field name (honours fieldMapping)."""
        return self.fields.get(name, name)

    def status(self, value):
        for s in self.statuses:
            if s.get("value") == value:
                return s
        return None

    def is_completed(self, value):
        s = self.status(value)
        return bool(s and s.get("isCompleted"))

    def public(self):
        return {
            "statuses": self.statuses, "priorities": self.priorities,
            "tasksFolder": self.tasks_folder, "archiveFolder": self.archive_folder,
            "taskTag": self.task_tag, "idMethod": self.id_method,
            "defaultStatus": self.default_status, "defaultPriority": self.default_priority,
            "savedViews": self.saved_views, "readOnly": self.quarantined,
        }


def resolve_mode(vault_path, conf=None):
    """Which task format this vault is used in: "tasknotes" or "tasks"
    (Obsidian Tasks plugin). config.json "taskFormat" decides; "auto" (the
    default) prefers TaskNotes when its plugin is enabled."""
    from . import inline
    conf = conf if conf is not None else load_config()
    want = os.environ.get("OMAFORGE_TASK_FORMAT") or str(conf.get("taskFormat") or "auto")
    if want in ("tasknotes", "tasks"):
        return want
    try:
        with open(os.path.join(vault_path, ".obsidian", "community-plugins.json"), encoding="utf-8") as f:
            enabled = json.load(f)
    except (OSError, ValueError):
        enabled = []
    if "tasknotes" in enabled:
        return "tasknotes"
    if inline.PLUGIN_ID in enabled:
        return "tasks"
    return "tasknotes"


class Entry:
    __slots__ = ("rel", "mtime", "size", "data", "error", "has_fm", "inline")

    def __init__(self, rel, mtime, size):
        self.rel, self.mtime, self.size = rel, mtime, size
        # data None = frontmatter not parsed because it can't be a task
        self.data, self.error, self.has_fm = {}, None, False
        self.inline = []   # Tasks mode: (line_no, line) checkbox lines


def file_hash(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


class Vault:
    def __init__(self, path, settings=None):
        self.path = os.path.realpath(os.path.expanduser(path))
        if not os.path.isdir(self.path):
            raise VaultError("no-vault", "vault folder not found: %s" % self.path)
        self.settings = settings or Settings(self.path)
        self.mode = resolve_mode(self.path)
        if self.mode == "tasks":
            from . import inline
            self.tasks_settings = inline.TasksSettings(self.path)
            # TaskNotes' settings don't matter in Tasks mode.
            if self.settings.quarantined and "TaskNotes settings" in self.settings.quarantined:
                self.settings.quarantined = None
        if not self.settings.quarantined and not write_allowed(self.path):
            self.settings.quarantined = ("Read-only: this vault isn't listed in writableVaults in %s" % CONFIG)
        self.entries = {}       # rel -> Entry (every note with readable head)
        self.own_writes = {}    # rel -> (mtime_ns, size) we produced

    def app_setting(self, key, default=None):
        """A value from Obsidian's own .obsidian/app.json (absent = default)."""
        try:
            with open(os.path.join(self.path, ".obsidian", "app.json"), encoding="utf-8") as f:
                return json.load(f).get(key, default)
        except (OSError, ValueError, AttributeError):
            return default

    # -- paths -----------------------------------------------------------

    def abs(self, rel):
        full = os.path.realpath(os.path.join(self.path, rel))
        if not full.startswith(self.path + os.sep):
            raise VaultError("bad-path", "path escapes vault: %r" % rel)
        return full

    def rel(self, full):
        return os.path.relpath(full, self.path).replace(os.sep, "/")

    # -- scanning --------------------------------------------------------

    def walk(self):
        for dirpath, dirnames, filenames in os.walk(self.path):
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            for fn in filenames:
                if fn.endswith(".md") and not fn.startswith("."):
                    yield os.path.join(dirpath, fn)

    def scan(self):
        """Refresh entries from disk. Returns (changed_rels, removed_rels)."""
        seen = set()
        changed = []
        for full in self.walk():
            try:
                st = os.stat(full)
            except OSError:
                continue
            rel = self.rel(full)
            seen.add(rel)
            old = self.entries.get(rel)
            if old and old.mtime == st.st_mtime_ns and old.size == st.st_size:
                continue
            e = Entry(rel, st.st_mtime_ns, st.st_size)
            self._load_head(full, e)
            self.entries[rel] = e
            if self.own_writes.get(rel) == (st.st_mtime_ns, st.st_size):
                continue  # our own write: UI already has the result
            changed.append(rel)
        removed = [r for r in self.entries if r not in seen]
        for r in removed:
            del self.entries[r]
        return changed, removed

    def _load_head(self, full, e):
        try:
            with open(full, "rb") as f:
                raw = f.read(HEAD_BYTES) if self.mode != "tasks" else f.read()
            text = raw.decode("utf-8", errors="replace")
        except OSError as ex:
            e.error = "unreadable: %s" % ex
            return
        if self.mode == "tasks":
            from . import inline
            e.inline = inline.candidate_lines(text) if "[" in text else []
            return
        if not (text.startswith("---") or text.startswith("﻿---")):
            return
        note = Note(text)
        e.has_fm = note.has_fm
        # Cheap prefilter: a note whose frontmatter never mentions the task
        # tag/property can't be a task, so skip the (slow) YAML parse.
        if note.has_fm and not self._may_be_task(note.fm_text()):
            e.data = None
            return
        if note.has_fm:
            try:
                e.data = note.data()
            except FrontmatterError as ex:
                e.error = str(ex)

    def _may_be_task(self, fm_text):
        """The task tag as a whole token (so 'todo' doesn't match an imported
        'todoist://' link); for the property method, the property name."""
        s = self.settings
        if s.id_method != "tag":
            return bool(s.prop_name) and s.prop_name.lower() in fm_text.lower()
        if not hasattr(self, "_tag_re"):
            self._tag_re = re.compile(r"(?<![\w/#-])#?%s(?:/[\w/-]*)?(?![\w:-])" % re.escape(s.task_tag), re.IGNORECASE)
        return bool(self._tag_re.search(fm_text))

    # -- reading/writing a whole note ---------------------------------------

    def read(self, rel):
        full = self.abs(rel)
        try:
            with open(full, encoding="utf-8", newline="") as f:
                text = f.read()
        except FileNotFoundError:
            raise VaultError("missing", "%s is gone (moved, deleted, or still syncing)" % rel)
        return text

    def check_writable(self):
        if self.settings.quarantined:
            raise VaultError("read-only", self.settings.quarantined)

    def write(self, rel, text, expect_hash=None, create=False):
        """Atomically write a note. expect_hash: refuse unless the file on
        disk still hashes to this. create: refuse if the file exists."""
        self.check_writable()
        full = self.abs(rel)
        if create:
            if os.path.lexists(full):
                raise VaultError("exists", "%s already exists" % rel)
        elif expect_hash is not None and file_hash(self.read(rel)) != expect_hash:
            raise VaultError("conflict", "%s changed on disk; reloaded" % rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        try:
            mode = stat.S_IMODE(os.stat(full).st_mode)
        except OSError:
            mode = 0o644
        fd, tmp = tempfile.mkstemp(prefix=".omaforge-", suffix=".tmp", dir=os.path.dirname(full))
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
                f.write(text)
                f.flush()
                os.fsync(f.fileno())
            os.chmod(tmp, mode)
            if create:
                os.link(tmp, full)  # fails if something appeared meanwhile
                os.unlink(tmp)
            else:
                os.replace(tmp, full)
        except FileExistsError:
            os.unlink(tmp)
            raise VaultError("exists", "%s already exists" % rel)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        st = os.stat(full)
        self.own_writes[rel] = (st.st_mtime_ns, st.st_size)
        if not rel.endswith(".md"):
            return None
        e = Entry(rel, st.st_mtime_ns, st.st_size)
        self._load_head(full, e)
        self.entries[rel] = e
        return e

    def move(self, rel, new_rel):
        self.check_writable()
        src, dst = self.abs(rel), self.abs(new_rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        try:
            os.link(src, dst)  # no clobbering: fails if dst exists
        except FileExistsError:
            raise VaultError("exists", "%s already exists" % new_rel)
        os.unlink(src)
        e = self.entries.pop(rel, None)
        if e:
            e.rel = new_rel
            self.entries[new_rel] = e
            st = os.stat(dst)
            self.own_writes[new_rel] = (st.st_mtime_ns, st.st_size)
        return new_rel
