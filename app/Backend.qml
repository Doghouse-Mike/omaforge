pragma Singleton
import QtQuick
import Quickshell
import Quickshell.Io

// Owns the Python core process. Requests are JSON lines with an id; replies
// resolve the matching callback. Vault changes arrive as unsolicited events
// and are folded into `tasks` (path -> task), bumping `revision` so views
// recompute.
Singleton {
  id: root

  readonly property string appDir: Qt.resolvedUrl(".").toString().replace(/^file:\/\//, "").replace(/\/$/, "")
  readonly property string coreDir: appDir.replace(/\/app$/, "") + "/core"

  property string vaultPath: Quickshell.env("OMAFORGE_VAULT") || ""
  property string vaultName: ""
  property var settings: ({ statuses: [], priorities: [], savedViews: [] })
  property var tasks: ({})
  property var views: []
  property var datePicker: null   // set by the window (shared DatePicker)
  property var prefs: ({ dates: { defaultTime: "09:00", useDefaultTime: true } })          // .base views (core/omaforge/bases.py descriptors)
  property int revision: 0
  property string today: ""
  property bool ready: false
  property string fatal: ""
  property string lastError: ""

  signal notice(string kind, string message)

  property int _nextId: 1
  property var _pending: ({})
  // Writes before the process is up are dropped by Process, so queue them.
  property var _queue: []
  property bool _started: false

  property var _quiet: ({})
  // quiet: the caller shows its own error (e.g. the view editor's preview).
  function request(op, args, cb, quiet) {
    var id = _nextId++
    var msg = Object.assign({ id: id, op: op }, args || {})
    if (cb) _pending[id] = cb
    if (quiet) _quiet[id] = true
    var line = JSON.stringify(msg) + "\n"
    if (_started) proc.write(line)
    else _queue.push(line)
  }

  function applySnapshot(s) {
    vaultPath = s.vault
    vaultName = s.vaultName
    settings = s.settings
    today = s.today
    views = s.views || []
    if (s.prefs) prefs = s.prefs
    var map = {}
    for (var i = 0; i < s.tasks.length; i++) map[s.tasks[i].path] = s.tasks[i]
    tasks = map
    revision++
    ready = true
    if (s.settings.readOnly) notice("warn", s.settings.readOnly + " Read-only until fixed.")
  }

  function applyDelta(upsert, remove) {
    var map = tasks
    for (var i = 0; i < (remove || []).length; i++) delete map[remove[i]]
    for (var j = 0; j < (upsert || []).length; j++) map[upsert[j].path] = upsert[j]
    tasks = map
    revision++
  }

  function onLine(line) {
    var msg
    try { msg = JSON.parse(line) } catch (e) { console.warn("bad line from core:", line); return }
    if (msg.event === "tasks") { applyDelta(msg.upsert, msg.remove); return }
    if (msg.event === "reset") { applySnapshot(msg); return }
    if (msg.event === "views") { views = msg.views; revision++; return }
    if (msg.event === "error") { notice("error", msg.message); return }
    var cb = _pending[msg.id]
    var quiet = _quiet[msg.id]
    delete _pending[msg.id]
    delete _quiet[msg.id]
    if (!msg.ok && !quiet) {
      lastError = msg.message
      // A conflict means the note changed under us: the poll will deliver
      // the fresh version, so say so instead of failing silently.
      notice(msg.code === "conflict" ? "warn" : "error", msg.message)
    }
    if (cb) cb(msg)
  }

  function start() {
    if (!vaultPath) { fatal = "No vault configured. Set OMAFORGE_VAULT or pass --vault."; return }
    proc.running = true
    request("open", { vault: vaultPath }, function (r) {
      if (r.ok) applySnapshot(r.result)
      else fatal = r.message
    })
  }

  // Convenience wrappers ------------------------------------------------------
  // `expect` carries the values the UI showed, so the core can refuse a write
  // whose field changed on disk in the meantime.
  function update(task, fields, cb) {
    var expect = {}
    for (var k in fields) expect[k] = task.raw[k] === undefined ? null : task.raw[k]
    request("update", { path: task.path, set: fields, expect: expect }, cb)
  }
  function toggleComplete(task, date, cb) { request("toggleComplete", { path: task.path, date: date || "", expect: task.expect }, cb) }
  function setStatus(task, status, cb) { request("setStatus", { path: task.path, status: status, expect: task.expect }, cb) }
  function archive(task, on, cb) { request("archive", { path: task.path, on: on, expect: task.expect }, cb) }
  function skip(task, date, cb) { request("skipInstance", { path: task.path, date: date, expect: task.expect }, cb) }
  function create(fields, cb) { request("create", { fields: fields }, cb) }
  function remove(task, cb) { request("delete", { path: task.path, expect: task.expect }, cb) }
  function body(task, cb) { request("body", { path: task.path }, cb) }
  function previewView(model, cb) { request("previewView", { model: model }, cb, true) }
  function saveView(model, file, cb) {
    request("saveView", { model: model, file: file || "" }, function (r) {
      if (r.ok) { root.views = r.result.views; root.revision++ }
      if (cb) cb(r)
    })
  }
  function deleteView(file, cb) {
    request("deleteView", { file: file }, function (r) {
      if (r.ok) { root.views = r.result.views; root.revision++ }
      if (cb) cb(r)
    })
  }
  function saveBody(task, text, hash, cb) { request("saveBody", { path: task.path, body: text, hash: hash }, cb) }

  Process {
    id: proc
    command: ["python3", "-I", root.coreDir + "/omaforge-core"]
    stdinEnabled: true
    onStarted: {
      root._started = true
      var q = root._queue
      root._queue = []
      for (var i = 0; i < q.length; i++) proc.write(q[i])
    }
    stdout: SplitParser {
      splitMarker: "\n"
      onRead: data => root.onLine(data)
    }
    stderr: SplitParser {
      onRead: data => console.warn("core:", data)
    }
    onExited: (code, status) => {
      if (root.ready) root.fatal = "The vault process stopped (exit " + code + "). Restart OmaForge."
    }
  }
}
