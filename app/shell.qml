//@ pragma AppId omaforge
//@ pragma UseQApplication
import QtQuick
import QtQuick.Controls
import Quickshell
import Quickshell.Io
import "components"
import "views.js" as V

ShellRoot {
  id: shell

  Component.onCompleted: Backend.start()

  // `omaforge` (the launcher) calls this when an instance is already up.
  IpcHandler {
    target: "omaforge"
    function show(): void { win.visible = true; search.input.forceActiveFocus(); search.input.focus = false; root.forceActiveFocus() }
    function newTask(): void { win.visible = true; root.startNew() }
    function quit(): void { Qt.quit() }
    // Scripting/test hooks: drive the UI without synthesising real input.
    function view(id: string): void { win.visible = true; root.pickView(id) }
    // From a notification: show this task, keeping the current list if it's in it.
    function openTask(path: string): void {
      win.visible = true
      if (!root.flatTasks.some(function (t) { return t.path === path })) {
        var t = Backend.tasks[path]
        root.pickView(t && (t.done || t.archived) ? (t.archived ? "archived" : "done") : "open")
      }
      root.selectedPath = path
      root.detailOpen = true; root.overlayDetail = true
      list.ensureVisible()
    }
    function settings(): void { settingsDlg.open() }
    function pickBlocker(): void { detail.pickBlocker(null) }
    function pickerFilter(text: string): string { picker.open === undefined; return JSON.stringify(picker.shown.map(function (o) { return o.label })) }
    function pickerChoose(label: string): string {
      for (var i = 0; i < picker.shown.length; i++) if (picker.shown[i].label === label) { picker.choose(i); return "ok" }
      return "not in list"
    }
    function picker(value: string): void { datePicker.open({ x: 300, y: 120 }, value, function (v) { Backend.notice("info", "picked " + v) }) }
    function pickerKey(k: string): void {
      var m = { left: Qt.Key_Left, right: Qt.Key_Right, down: Qt.Key_Down, pgdn: Qt.Key_PageDown, enter: Qt.Key_Return, n: Qt.Key_N, t: Qt.Key_T }
      if (k === "enter") datePicker.commit(); else if (k === "n") datePicker.time = ""
      else if (k === "left") datePicker.move(-1); else if (k === "right") datePicker.move(1)
      else if (k === "down") datePicker.move(7); else if (k === "pgdn") datePicker.moveMonth(1)
    }
    function newView(): void { root.startNewView() }
    function editorSet(json: string): void { viewEditor.model = JSON.parse(json); viewEditor.touch() }
    function editorSave(): void { viewEditor.save() }
    function editCurrentView(): void { if (root.currentBase && root.currentBase.model) viewEditor.openEdit(root.currentBase) }
    function editorDelete(): void { viewEditor.deleteCurrent() }
    // Menus by test hook: which entries, and run one by its text.
    function menuFor(id: string): string {
      var entry = { id: id, kind: "item" }
      var items = id.indexOf("task:") === 0 ? root.taskMenu(Backend.tasks[id.slice(5)]) : root.viewMenu(entry)
      ctxMenu.open(root.width / 3, root.height / 3, items)
      return JSON.stringify(items.map(function (i) { return i.separator ? "—" : (i.text + (i.enabled === false ? " (off)" : "") + (i.submenu ? " ›" : "")) }))
    }
    // "Item" or "Submenu/Item"
    function menuPick(text: string): string {
      var parts = text.split("/")
      for (var i = 0; i < ctxMenu.items.length; i++) if (ctxMenu.items[i].text === parts[0]) {
        ctxMenu.activate(i)
        if (parts.length === 1) return "ok"
        var sub = ctxMenu.sub
        for (var j = 0; j < sub.items.length; j++) if (sub.items[j].text === parts[1]) { sub.activate(j); return "ok" }
        return "no such sub-item"
      }
      return "no such item"
    }
    function create(title: string): void { root.createTask(title) }
    function duplicateView(id: string): void { root.duplicateView(Backend.views.filter(function (v) { return v.id === id })[0]) }
    function editorState(): string { return JSON.stringify({ visible: viewEditor.visible, model: viewEditor.model, notes: viewEditor.notes, count: viewEditor.previewCount, original: viewEditor.originalCount, error: viewEditor.previewError }) }
    function confirmDelete(): void { confirmBox.del() }
    function select(n: int): void { var t = root.flatTasks[n]; if (t) root.selectedPath = t.path }
    function press(key: string): string { return root.pressNamed(key) ? "ok" : "unknown key" }
    // Renders the app's own contents to a PNG (never other windows).
    function snapshot(path: string): string {
      root.grabToImage(function (r) { r.saveToFile(path) })
      return "ok"
    }
    // What Tab does from the current focus (same focus-chain step).
    function tab(forward: bool): string {
      var fi = win.contentItem.Window.activeFocusItem
      if (!fi) return "no focus"
      var next = fi.nextItemInFocusChain(forward)
      if (next) next.forceActiveFocus()
      return String(next)
    }
    function state(): string {
      var fi = win.contentItem ? win.contentItem.Window.activeFocusItem : null
      return JSON.stringify({ focus: fi ? (fi.objectName || String(fi).split("(")[0]) + (fi.text !== undefined ? ":" + String(fi.text).slice(0, 24) : "") : "",
                              view: root.viewId, selected: root.selectedPath, layout: root.layout,
                              count: root.result.count, detail: detail.visible, narrow: root.narrow, pane: root.focusedPane() })
    }
    function cyclePane(dir: int): string { root.cyclePane(dir); return root.focusedPane() }
  }

  FloatingWindow {
    id: win
    title: "OmaForge" + (Backend.vaultName ? " — " + Backend.vaultName : "")
    implicitWidth: 1280
    implicitHeight: 800
    minimumSize: Qt.size(720, 420)
    color: Theme.bg
    visible: true
    // Closing the window ends the app; the vault is the state, so there's
    // nothing to keep alive in the background.
    onVisibleChanged: if (!visible) Qt.quit()

    // A plain Item, not a FocusScope: a scope hands focus back to whichever
    // child last had it, so "focus the list" could land in a hidden field.
    Item {
      id: root
      anchors.fill: parent
      focus: true

      property string viewId: "today"
      property string selectedPath: ""
      // Ctrl+Tab: the sidebar takes the keyboard (j/k change list) until
      // Enter/Esc or the next Ctrl+Tab. List and task pane use real focus.
      property bool sidebarFocus: false
      onActiveFocusChanged: if (!activeFocus) sidebarFocus = false
      property string layout: "list"     // list | board
      property string groupBy: "status"
      property bool showDone: false
      property bool detailOpen: true
      property bool overlayDetail: false   // narrow mode: editor slid over the list
      // Tiled at half a 1080p screen the window is ~950px wide: the editor
      // then slides over the list instead of claiming a fixed column.
      readonly property bool narrow: width < Theme.px(1100)
      readonly property bool detailDocked: !narrow

      readonly property var result: {
        Backend.revision
        return V.compute(viewId, Backend.tasks, Backend.settings, Backend.today,
                         { search: search.text, groupBy: groupBy, showDone: showDone, baseViews: Backend.views,
                           queries: Backend.queries, tasksPlugin: Backend.tasksPlugin })
      }
      readonly property var flatTasks: {
        var out = []
        for (var g = 0; g < result.groups.length; g++) out = out.concat(result.groups[g].tasks)
        return out
      }
      readonly property var selectedTask: { Backend.revision; return Backend.tasks[selectedPath] || null }
      readonly property string viewTitle: {
        var id = viewId, i = id.indexOf(":")
        if (i < 0) { var s = V.smartLists().filter(function (x) { return x.id === id })[0]; return s ? s.label : id === "problems" ? "Problems" : id }
        var kind = id.slice(0, i), arg = id.slice(i + 1)
        if (kind === "saved") { var v = (Backend.settings.savedViews || []).filter(function (x) { return x.id === arg })[0]; return v ? v.name : arg }
        if (kind === "base") { var bv = currentBase; return bv ? bv.name : arg.replace(/^.*::/, "") }
        if (kind === "query") { var qb = (Backend.queries || []).filter(function (x) { return x.id === id })[0]; return qb ? qb.name : "Query" }
        return (kind === "context" ? "@" : kind === "tag" ? "#" : "") + arg
      }
      readonly property bool facetView: /^(project|context|tag|open):?/.test(viewId)

      readonly property var currentBase: {
        Backend.revision
        if (viewId.indexOf("base:") !== 0) return null
        return (Backend.views || []).filter(function (v) { return v.id === viewId })[0] || null
      }
      property string userLayout: "list"   // what b last chose; base board views override it
      function pickView(id) {
        viewId = id
        var bv = currentBase
        layout = bv && bv.layout === "board" ? "board" : userLayout
        if (!flatTasks.some(function (t) { return t.path === selectedPath })) selectedPath = flatTasks.length ? flatTasks[0].path : "" }
      function toggle(t) {
        if (!t) return
        // Recurring: the core picks the occurrence (scheduled date, or today
        // for completion-anchored repeats), as TaskNotes does. The row stays
        // open afterwards, so say what happened -- otherwise a tick looks
        // like it did nothing and invites a second one.
        Backend.toggleComplete(t, "", function (r) {
          if (!r.ok || !t.recurring || !r.result.task) return
          var before = t.completeInstances || [], after = r.result.task.completeInstances || []
          var added = after.filter(function (x) { return before.indexOf(x) < 0 })
          var removed = before.filter(function (x) { return after.indexOf(x) < 0 })
          var nxt = r.result.task.occurrence ? " · next: " + V.prettyDate(r.result.task.occurrence, Backend.today) : ""
          if (added.length) Backend.notice("info", "Done for " + V.prettyDate(added[0], Backend.today) + nxt)
          else if (removed.length) Backend.notice("info", "Un-done " + V.prettyDate(removed[0], Backend.today) + nxt)
        })
      }
      function cycleStatus(t, dir) {
        var ss = Backend.settings.statuses || []
        var i = ss.findIndex(function (s) { return s.value === t.status })
        var n = ss[(i + dir + ss.length) % ss.length]
        if (n) Backend.setStatus(t, n.value)
      }
      function bumpPriority(t, dir) {
        var ps = Backend.settings.priorities || []
        var i = ps.findIndex(function (p) { return p.value === t.priority })
        var n = ps[Math.max(0, Math.min(ps.length - 1, i + dir))]
        if (n && n.value !== t.priority) Backend.update(t, { priority: n.value })
      }
      function startNewView() {
        // Seed from where you are: a project/context/tag list becomes a condition.
        var i = viewId.indexOf(":"), kind = viewId.slice(0, i), arg = viewId.slice(i + 1)
        var conds = [{ field: "status", op: "open", value: "" }]
        if (kind === "project") conds.push({ field: "projects", op: "has", value: "[[" + arg + "]]" })
        if (kind === "context") conds.push({ field: "contexts", op: "has", value: arg })
        if (kind === "tag") conds.push({ field: "tags", op: "has", value: arg })
        viewEditor.openNew({ name: "", match: "all", conditions: conds, sort: { field: "due", dir: "asc" }, group: "none", layout: "list" })
      }
      // "file.base#View" opens that view; the bare file shows whichever view
      // was used last (and many views share tasks-default.base).
      function openBaseInObsidian(bv) { obsidianOpen(bv.file + "#" + bv.name) }
      function startNew() { newBar.visible = true; newField.input.forceActiveFocus() }
      // A copy of any view as an OmaForge view: exact for ones made here; for
      // hand-made ones the core maps what it can to editor rows and keeps the
      // rest as written (see bases.closest_model).
      function duplicateView(bv) {
        if (bv.model) {
          var m = JSON.parse(JSON.stringify(bv.model)); m.name = bv.name + " copy"
          viewEditor.openNew(m)
          return
        }
        Backend.closestModel(bv.file, bv.name, function (r) {
          if (r.ok) viewEditor.openNew(r.result.model, { notes: r.result.notes, from: bv })
        })
      }
      function createTask(title) {
        title = title.trim()
        if (!title) return
        var fields = { title: title }
        // New tasks inherit what the current view is about.
        var i = viewId.indexOf(":"), kind = viewId.slice(0, i), arg = viewId.slice(i + 1)
        if (kind === "project") fields.projects = ["[[" + arg.replace(/^\[\[|\]\]$/g, "") + "]]"]
        if (kind === "context") fields.contexts = [arg]
        if (kind === "tag") fields.tags = [arg]
        if (kind === "note") {
          // Tasks mode: add the line to the note you're looking at.
          for (var p in Backend.tasks) if ((Backend.tasks[p].notes || [])[0] === arg) { fields.file = Backend.tasks[p].file; break }
        }
        if (viewId === "today") fields.scheduled = Backend.today
        Backend.create(fields, function (r) { if (r.ok) root.selectedPath = r.result.path })
      }
      // ---- Context menus ---------------------------------------------------
      // Each returns a plain list for ContextMenu (see its header for the item
      // shape). Add entries here as new actions come along.
      function copyText(s) { Quickshell.execDetached(["wl-copy", "--", s]); Backend.notice("info", "Copied " + s) }
      function obsidianOpen(path) {
        Quickshell.execDetached(["xdg-open", "obsidian://open?vault=" + encodeURIComponent(Backend.vaultName) + "&file=" + encodeURIComponent(path)])
      }
      function viewMenu(entry) {
        var id = entry.id || "", i = id.indexOf(":"), kind = i < 0 ? id : id.slice(0, i), arg = i < 0 ? "" : id.slice(i + 1)
        var items = []
        if (kind === "base") {
          var bv = (Backend.views || []).filter(function (v) { return v.id === id })[0]
          var mine = !!(bv && bv.model)
          // Only a .base file OmaForge can regenerate exactly is editable here
          // (hand-made, or edited in Obsidian since): a rewrite could lose
          // something. Say so rather than greying out with no reason.
          items.push({ text: "Edit view", icon: "✎", enabled: mine, hint: mine ? "" : "can't rewrite safely — duplicate it",
                       action: function () { root.pickView(id); viewEditor.openEdit(bv) } })
          items.push({ text: mine ? "Duplicate as new view" : "Duplicate as editable view", icon: "󰆏",
                       enabled: !!bv && !bv.unsupported, hint: bv && bv.unsupported ? "can't read this view" : "",
                       action: function () { root.duplicateView(bv) } })
          items.push({ separator: true })
          items.push({ text: "Open in Obsidian", icon: "󰏌", action: function () { root.openBaseInObsidian(bv) } })
          items.push({ text: "Copy file path", icon: "󰆏", action: function () { root.copyText(bv.file) } })
          items.push({ separator: true })
          items.push({ text: "Delete view…", icon: "󰆴", danger: true, enabled: mine,
                       hint: mine ? "" : "delete it in Obsidian",
                       action: function () { viewEditor.openEdit(bv); viewEditor.deleteCurrent() } })
          return items
        }
        if (kind === "saved")
          return [{ text: "TaskNotes saved view", icon: "󰈲", enabled: false, hint: "edit it in TaskNotes' settings" },
                  { separator: true },
                  { text: "New view…", icon: "+", action: function () { root.startNewView() } }]
        if (kind === "query") {
          var qb = (Backend.queries || []).filter(function (x) { return x.id === id })[0]
          if (!qb) return []
          return [{ text: "Show results", icon: "󰈲", action: function () { root.pickView(id) } },
                  { text: "Open query in Obsidian", icon: "󰏌", action: function () { root.openInObsidian({ file: qb.file, line: qb.line }) } },
                  { text: "Copy query", icon: "󰆏", action: function () { root.copyText(qb.source) } }]
        }
        if (kind === "note") {
          var f = ""
          for (var p in Backend.tasks) if ((Backend.tasks[p].notes || [])[0] === arg) { f = Backend.tasks[p].file; break }
          return [{ text: "Show this note's tasks", icon: "󰈲", action: function () { root.pickView(id) } },
                  { text: "Open note in Obsidian", icon: "󰏌", enabled: !!f, action: function () { root.obsidianOpen(f) } }]
        }
        if (kind === "project" || kind === "context" || kind === "tag") {
          items.push({ text: "Show this list", icon: "󰈲", action: function () { root.pickView(id) } })
          items.push({ text: "New view from this " + kind, icon: "+",
                       action: function () { root.pickView(id); root.startNewView() } })
          if (kind === "project")
            items.push({ text: "Open project note in Obsidian", icon: "󰏌", action: function () { root.obsidianOpen(arg.replace(/^\[\[|\]\]$/g, "")) } })
          return items
        }
        // smart lists, headers
        if (entry.kind === "item") items.push({ text: "Show this list", icon: "󰈲", action: function () { root.pickView(id) } })
        items.push({ text: "New view…", icon: "+", action: function () { root.startNewView() } })
        return items
      }
      function taskMenu(t) {
        if (!t) return []
        if (t.error)
          return [{ text: "Open in Obsidian to fix", icon: "󰏌", action: function () { root.openInObsidian(t) } },
                  { text: "Copy path", icon: "󰆏", action: function () { root.copyText(t.path) } }]
        var s = Backend.settings, items = []
        if (t.recurring) {
          items.push({ text: "Complete this occurrence", icon: "✓", hint: t.occurrence ? V.prettyDate(t.occurrence, Backend.today) : "", action: function () { root.toggle(t) } })
          if (Backend.mode !== "tasks")   // Tasks has no "skip"
            items.push({ text: "Skip this occurrence", icon: "↷", action: function () { Backend.skip(t, "") } })
        } else {
          items.push({ text: t.done ? "Mark not done" : "Complete", icon: "✓", hint: "x", action: function () { root.toggle(t) } })
        }
        items.push({ text: "Status", icon: "◐", submenu: (s.statuses || []).map(function (st) {
          return { text: st.label || st.value, checked: t.status === st.value, action: function () { Backend.setStatus(t, st.value) } } }) })
        items.push({ text: "Priority", icon: "!", submenu: (s.priorities || []).slice().reverse().map(function (p) {
          return { text: p.label || p.value, checked: t.priority === p.value, action: function () { Backend.update(t, { priority: p.value }) } } }) })
        // Quick dates keep an existing time, else use the default time.
        function quick(field, day) {
          var cur = t[field] || "", p = Backend.prefs.dates || {}
          return cur.length > 10 ? day + cur.slice(10) : (p.useDefaultTime && p.defaultTime ? day + "T" + p.defaultTime : day)
        }
        function dateMenu(field) {
          var set = function (v) { var f = {}; f[field] = v; Backend.update(t, f) }
          return [
            { text: "Today", action: function () { set(quick(field, Backend.today)) } },
            { text: "Tomorrow", action: function () { set(quick(field, V.addDays(Backend.today, 1))) } },
            { text: "In a week", action: function () { set(quick(field, V.addDays(Backend.today, 7))) } },
            { text: "Pick…", icon: "󰃭", action: function () { datePicker.open({ x: ctxMenu.at.x, y: ctxMenu.at.y }, t[field] || "", function (v) { set(v) }) } },
            { separator: true },
            { text: "Clear", enabled: !!t[field], action: function () { set("") } }]
        }
        items.push({ text: "Due", icon: "󰥔", submenu: dateMenu("due") })
        items.push({ text: "Scheduled", icon: "󰃭", submenu: dateMenu("scheduled") })
        // Projects: replace with one (the common case); "Other…" searches or
        // takes a new name.
        var setProject = function (name) { Backend.update(t, { projects: name ? ["[[" + name + "]]"] : [] }) }
        var projItems = V.facetCounts(Backend.tasks, "projects").map(function (p) {
          return { text: p.name, checked: (t.projects || []).indexOf(p.name) >= 0, action: function () { setProject(p.name) } }
        })
        if (projItems.length) projItems.push({ separator: true })
        projItems.push({ text: "Other…", icon: "󰍉", action: function () {
          var opts = V.facetCounts(Backend.tasks, "projects").map(function (p) { return { label: p.name, value: p.name } })
          picker.open({ x: ctxMenu.at.x, y: ctxMenu.at.y }, "Move to which project?", opts, function (v) { setProject(v) }, { free: true })
        } })
        projItems.push({ text: "No project", enabled: (t.projects || []).length > 0, action: function () { setProject("") } })
        if (Backend.mode !== "tasks") items.push({ text: "Move to project", icon: "󰉋", submenu: projItems })
        items.push({ text: "Blocked by…", icon: "⛔", action: function () { detail.pickBlocker({ x: ctxMenu.at.x, y: ctxMenu.at.y }, t) } })
        items.push({ separator: true })
        items.push({ text: "Edit", icon: "✎", hint: "Enter", action: function () { root.selectedPath = t.path; root.detailOpen = true; root.overlayDetail = true; detail.focusFirst() } })
        items.push({ text: "Open in Obsidian", icon: "󰏌", hint: "o", action: function () { root.openInObsidian(t) } })
        var noteFile = t.file !== undefined ? t.file : t.path
        items.push({ text: "Copy link", icon: "󰌷", hint: t.file !== undefined ? "to its note" : "", action: function () { root.copyText("[[" + noteFile.replace(/^.*\//, "").replace(/\.md$/, "") + "]]") } })
        items.push({ text: "Copy as Markdown", icon: "󰍔", action: function () { root.copyText(t.raw && t.file !== undefined ? t.raw.replace(/^[\s>]+/, "") : root.taskMarkdown(t)) } })
        items.push({ text: "Duplicate", icon: "󰆏", action: function () {
          Backend.duplicate(t, function (r) { if (r.ok) { root.selectedPath = r.result.path; Backend.notice("info", "Duplicated as \"" + r.result.task.title + "\"") } })
        } })
        items.push({ separator: true })
        if (Backend.mode !== "tasks") items.push({ text: t.archived ? "Unarchive" : "Archive", icon: "󰆧", action: function () { Backend.archive(t, !t.archived) } })
        items.push({ text: "Delete…", icon: "󰆴", danger: true, action: function () { confirm.task = t; confirm.visible = true } })
        return items
      }
      // "- [ ] [[Note|Title]] — due Fri 9 Oct, @home, #tag" (Obsidian-ready)
      function taskMarkdown(t) {
        var name = t.path.replace(/^.*\//, "").replace(/\.md$/, "")
        var link = name === t.title ? "[[" + name + "]]" : "[[" + name + "|" + t.title + "]]"
        var bits = []
        if (t.due) bits.push("due " + V.prettyDate(t.due, Backend.today))
        if (t.scheduled && !t.recurring) bits.push("scheduled " + V.prettyDate(t.scheduled, Backend.today))
        if (t.recurring) bits.push(t.recurrenceText.toLowerCase())
        ;(t.contexts || []).forEach(function (c) { bits.push("@" + c) })
        ;(t.tags || []).forEach(function (g) { bits.push("#" + g) })
        return "- [" + (t.done ? "x" : " ") + "] " + link + (bits.length ? " — " + bits.join(", ") : "")
      }
      function openTaskMenuForSelected() {
        var t = selectedTask
        if (!t) return
        ctxMenu.open(centre.x + Theme.px(60), centre.y + Theme.px(90), taskMenu(t))
      }

      function openInObsidian(t) {
        if (t.file !== undefined && t.line !== undefined) {
          // A Tasks line: jump to it when Advanced URI is there, else open its note.
          var uri = Backend.advancedUri
            ? "obsidian://adv-uri?vault=" + encodeURIComponent(Backend.vaultName) + "&filepath=" + encodeURIComponent(t.file) + "&line=" + (t.line + 1)
            : "obsidian://open?vault=" + encodeURIComponent(Backend.vaultName) + "&file=" + encodeURIComponent(t.file.replace(/\.md$/, ""))
          Quickshell.execDetached(["xdg-open", uri])
          return
        }
        var uri = "obsidian://open?vault=" + encodeURIComponent(Backend.vaultName) + "&file=" + encodeURIComponent(t.path.replace(/\.md$/, ""))
        Quickshell.execDetached(["xdg-open", uri])
      }
      function step(delta) {
        if (layout === "board") board.step(0, delta)
        else list.step(delta)
      }

      // Ctrl+Tab / Ctrl+Shift+Tab: sidebar → list → task pane, and round.
      function focusedPane() {
        var fi = win.contentItem.Window.activeFocusItem
        for (var it = fi; it; it = it.parent) if (it === detail) return "detail"
        return sidebarFocus ? "sidebar" : "list"
      }
      function cyclePane(dir) {
        if (viewEditor.visible || settingsDlg.visible || datePicker.visible || picker.visible || confirm.visible) return
        var panes = ["sidebar", "list"]
        if (selectedTask) panes.push("detail")
        var i = panes.indexOf(focusedPane())
        var next = panes[(i + dir + panes.length) % panes.length]
        if (next === "detail") {
          sidebarFocus = false
          detailOpen = true; overlayDetail = true
          detail.focusFirst()
        } else {
          if (search.input.activeFocus) search.input.focus = false
          root.forceActiveFocus()
          sidebarFocus = next === "sidebar"
        }
      }
      Shortcut { sequences: ["Ctrl+Tab"]; context: Qt.WindowShortcut; onActivated: root.cyclePane(1) }
      Shortcut { sequences: ["Ctrl+Shift+Tab", "Ctrl+Backtab"]; context: Qt.WindowShortcut; onActivated: root.cyclePane(-1) }

      // Keys a text box doesn't use (Tab, arrows, …) bubble up to here; never
      // act on them while typing, or ↓ in a field would move the selection.
      Keys.onPressed: e => {
        var fi = win.contentItem.Window.activeFocusItem
        if (fi && fi.cursorPosition !== undefined) return
        if (handleKey(e.key, e.modifiers)) e.accepted = true
      }

      readonly property var keyNames: ({
        j: Qt.Key_J, k: Qt.Key_K, h: Qt.Key_H, l: Qt.Key_L, x: Qt.Key_X, s: Qt.Key_S, b: Qt.Key_B,
        d: Qt.Key_D, n: Qt.Key_N, e: Qt.Key_E, o: Qt.Key_O, plus: Qt.Key_Plus, minus: Qt.Key_Minus,
        esc: Qt.Key_Escape, "?": Qt.Key_Question, "[": Qt.Key_BracketLeft, "]": Qt.Key_BracketRight,
        tab: Qt.Key_Tab, "1": Qt.Key_1, "2": Qt.Key_2, "3": Qt.Key_3, "4": Qt.Key_4, "5": Qt.Key_5, enter: Qt.Key_Return
      })
      function pressNamed(name) {
        var shift = name === "S"
        var k = keyNames[shift ? "s" : name]
        if (k === undefined) return false
        handleKey(k, shift ? Qt.ShiftModifier : 0)
        return true
      }

      function handleKey(key, modifiers) {
        if (datePicker.visible || picker.visible) return false
        if (settingsDlg.visible) {
          if (key === Qt.Key_Escape) { settingsDlg.close(); return true }
          return false
        }
        if (viewEditor.visible) {
          if (key === Qt.Key_Escape) { viewEditor.close(); return true }
          return false
        }
        if (sidebarFocus) {
          switch (key) {
          case Qt.Key_J: case Qt.Key_Down: sidebar.step(1); return true
          case Qt.Key_K: case Qt.Key_Up: sidebar.step(-1); return true
          case Qt.Key_Return: case Qt.Key_Enter: case Qt.Key_Escape: case Qt.Key_L: case Qt.Key_Right:
            sidebarFocus = false; return true
          }
        }
        var t = selectedTask
        var e = { key: key, modifiers: modifiers }
        var ctrl = modifiers & Qt.ControlModifier
        if (ctrl && key === Qt.Key_Q) { Qt.quit(); return true }
        switch (key) {
        case Qt.Key_J: case Qt.Key_Down: step(1); break
        case Qt.Key_K: case Qt.Key_Up: step(-1); break
        case Qt.Key_H: case Qt.Key_Left: if (layout === "board") board.step(-1, 0); else sidebar.step(-1); break
        case Qt.Key_L: case Qt.Key_Right: if (layout === "board") board.step(1, 0); else sidebar.step(1); break
        case Qt.Key_BracketLeft: sidebar.step(-1); break
        case Qt.Key_BracketRight: sidebar.step(1); break
        case Qt.Key_Space: case Qt.Key_X: toggle(t); break
        case Qt.Key_N: case Qt.Key_A: startNew(); break
        case Qt.Key_Slash: search.input.forceActiveFocus(); break
        case Qt.Key_S: if (t) cycleStatus(t, e.modifiers & Qt.ShiftModifier ? -1 : 1); break
        case Qt.Key_Plus: case Qt.Key_Equal: if (t) bumpPriority(t, 1); break
        case Qt.Key_Minus: if (t) bumpPriority(t, -1); break
        case Qt.Key_B: layout = layout === "board" ? "list" : "board"; userLayout = layout; break
        case Qt.Key_D: detailOpen = !detailOpen; break
        case Qt.Key_O: if (t) openInObsidian(t); break
        case Qt.Key_E: case Qt.Key_Return: case Qt.Key_Enter: detailOpen = true; overlayDetail = true; break
        case Qt.Key_Question: help.visible = !help.visible; break
        case Qt.Key_Menu: openTaskMenuForSelected(); break
        case Qt.Key_Tab:
          if (!t) return false
          detailOpen = true; overlayDetail = true
          detail.focusFirst()
          break
        case Qt.Key_Escape:
          if (help.visible) help.visible = false
          else if (overlayDetail && narrow) overlayDetail = false
          else { search.input.text = "" }
          break
        case Qt.Key_1: case Qt.Key_2: case Qt.Key_3: case Qt.Key_4: case Qt.Key_5:
          var sm = V.smartLists()[e.key - Qt.Key_1]; if (sm) pickView(sm.id); break
        default: return false
        }
        return true
      }

      // Opaque base so self-snapshots match the window (Hyprland applies
      // the user's window opacity on top as usual).
      Rectangle { anchors.fill: parent; color: Theme.bg; z: -100 }

      Sidebar {
        id: sidebar
        anchors { left: parent.left; top: parent.top; bottom: parent.bottom }
        width: root.narrow ? Theme.px(190) : Theme.px(230)
        current: root.viewId
        focused: root.sidebarFocus
        onPicked: id => root.pickView(id)
        onNewView: root.startNewView()
        onOpenSettings: settingsDlg.open()
        onContextMenu: (entry, x, y) => ctxMenu.open(x, y, root.viewMenu(entry))
      }
      Rectangle { anchors.left: sidebar.right; height: parent.height; width: 1; color: Theme.divider }

      // Centre column --------------------------------------------------------
      Item {
        id: centre
        anchors { left: sidebar.right; leftMargin: 1; top: parent.top; bottom: parent.bottom; right: detail.visible && root.detailDocked ? detail.left : parent.right }

        Rectangle {
          id: header
          width: parent.width
          height: Theme.px(52)
          color: "transparent"
          Txt {
            id: viewLabel
            anchors { left: parent.left; leftMargin: Theme.px(14); verticalCenter: parent.verticalCenter }
            width: Math.min(implicitWidth, Math.max(Theme.px(60), headerControls.x - x - countLabel.implicitWidth - Theme.px(24)))
            text: root.viewTitle
            font.pixelSize: Theme.fsTitle
            font.bold: true
          }
          Txt {
            id: countLabel
            anchors { left: viewLabel.right; leftMargin: Theme.px(10); verticalCenter: parent.verticalCenter }
            // The reason itself goes in the empty list (it can be long).
            text: root.result.unsupported ? "⚠" : root.result.count
            color: root.result.unsupported ? Theme.yellow : Theme.faint
          }
          Row {
            id: headerControls
            anchors { right: parent.right; rightMargin: Theme.px(12); verticalCenter: parent.verticalCenter }
            spacing: 6
            Field {
              id: search
              width: header.width < Theme.px(620) ? Theme.px(110) : Theme.px(190)
              placeholder: "/ filter"
              input.onTextChanged: text = input.text
              property string text: ""
              Keys.onEscapePressed: { input.text = ""; root.forceActiveFocus() }
              input.Keys.onDownPressed: root.forceActiveFocus()
              onEscaped: { input.text = ""; root.forceActiveFocus() }
              onCommitted: root.forceActiveFocus()
            }
            Btn {
              visible: root.layout === "list" && root.facetView
              text: header.width < Theme.px(620) ? "⊞ " + root.groupBy : "group: " + root.groupBy
              onClicked: { var o = ["status", "priority", "project", "context", "none"]; root.groupBy = o[(o.indexOf(root.groupBy) + 1) % o.length] }
            }
            Btn {
              visible: !!(root.currentBase && root.currentBase.model)
              text: header.width < Theme.px(620) ? "✎" : "✎ Edit view"
              tip: "Edit this view"
              onClicked: viewEditor.openEdit(root.currentBase)
            }
            Btn {
              visible: !!root.currentBase
              icon: "󰏌"
              tip: "Open " + (root.currentBase ? root.currentBase.file : "") + " in Obsidian"
              onClicked: root.openBaseInObsidian(root.currentBase)
            }
            Btn { visible: /^(project|context|tag):/.test(root.viewId); text: root.showDone ? "hide done" : "show done"; onClicked: root.showDone = !root.showDone }
            Btn { icon: "󰕰"; tip: "List / board (b)"; active: root.layout === "board"; onClicked: root.layout = root.layout === "board" ? "list" : "board" }
            Btn { icon: "󰍜"; tip: "Detail pane (d)"; active: root.detailOpen; onClicked: root.detailOpen = !root.detailOpen }
            Btn { icon: "+"; text: header.width < Theme.px(620) ? "" : "New"; tip: "New task (n)"; onClicked: root.startNew() }
          }
          Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.divider }
        }

        Rectangle {
          id: newBar
          visible: false
          anchors { top: header.bottom; left: parent.left; right: parent.right }
          height: visible ? Theme.px(44) : 0
          color: Theme.a(Theme.accent, 0.06)
          Field {
            id: newField
            anchors { fill: parent; margins: Theme.px(8) }
            placeholder: "New task title — Enter to add, Esc to cancel" + (root.viewId === "today" ? " (scheduled today)" : "")
            onCommitted: (v) => { root.createTask(v); input.text = ""; newField._initial = "" }
            onEscaped: { input.text = ""; newBar.visible = false; root.forceActiveFocus() }
            input.onActiveFocusChanged: if (!input.activeFocus && input.text === "") newBar.visible = false
          }
        }

        TaskList {
          id: list
          visible: root.layout === "list"
          anchors { top: newBar.bottom; left: parent.left; right: parent.right; bottom: parent.bottom }
          groups: root.result.groups
          emptyText: root.result.unsupported ? "⚠ Can't show this view.\n\n" + root.result.unsupported : "Nothing here."
          selectedPath: root.selectedPath
          onSelect: p => { root.selectedPath = p; root.forceActiveFocus() }
          onOpen: t => { root.overlayDetail = true }
          onToggle: t => root.toggle(t)
          onMenu: (t, x, y) => ctxMenu.open(x, y, root.taskMenu(t))
        }
        Board {
          id: board
          visible: root.layout === "board"
          anchors { top: newBar.bottom; left: parent.left; right: parent.right; bottom: parent.bottom }
          tasks: root.flatTasks
          selectedPath: root.selectedPath
          onSelect: p => { root.selectedPath = p; root.forceActiveFocus() }
          onToggle: t => root.toggle(t)
          onSetStatus: (t, s) => Backend.setStatus(t, s)
          onMenu: (t, x, y) => ctxMenu.open(x, y, root.taskMenu(t))
        }
      }

      Rectangle { visible: detail.visible; anchors.right: detail.left; height: parent.height; width: 1; color: Theme.divider; z: 20 }
      Detail {
        id: detail
        // Docked: always there when open. Overlay (narrow): only while a
        // task is selected, Esc/d closes it.
        visible: root.detailOpen && (root.detailDocked || (root.selectedTask !== null && root.overlayDetail))
        anchors { right: parent.right; top: parent.top; bottom: parent.bottom }
        width: root.detailDocked ? Math.min(Theme.px(440), parent.width * 0.4) : Math.min(Theme.px(440), parent.width * 0.62)
        color: root.detailDocked ? Theme.a(Theme.fg, 0.02) : Theme.bg
        z: 20
        task: root.selectedTask
        closable: !root.detailDocked
        onLeave: root.forceActiveFocus()
        onCloseRequested: { root.overlayDetail = false; root.forceActiveFocus() }
        onOpenInObsidian: t => root.openInObsidian(t)
        onRequestMenu: (items, x, y) => ctxMenu.open(x, y, items)
        onRequestDelete: t => { confirm.task = t; confirm.visible = true }
      }

      // Notices --------------------------------------------------------------
      Column {
        anchors { bottom: parent.bottom; horizontalCenter: centre.horizontalCenter; bottomMargin: Theme.px(16) }
        spacing: 6
        z: 50
        Repeater {
          model: toasts.items
          Rectangle {
            required property var modelData
            width: Math.min(Theme.px(520), centre.width - 40)
            height: tt.implicitHeight + Theme.px(14)
            color: Theme.bg
            border.width: 1
            border.color: modelData.kind === "error" ? Theme.red : modelData.kind === "warn" ? Theme.yellow : Theme.accent
            Txt { id: tt; anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter; margins: Theme.px(10) }
                  text: modelData.text; wrapMode: Text.Wrap; elide: Text.ElideNone }
          }
        }
      }
      QtObject {
        id: toasts
        property var items: []
        function push(kind, text) {
          items = items.concat([{ kind: kind, text: text, at: Date.now() }]).slice(-3)
          expire.restart()
        }
      }
      Timer {
        id: expire
        interval: 5000
        onTriggered: { toasts.items = toasts.items.filter(function (i) { return Date.now() - i.at < 4800 }); if (toasts.items.length) restart() }
      }
      Connections {
        target: Backend
        function onNotice(kind, message) { toasts.push(kind, message) }
      }

      // Fatal / loading ---------------------------------------------------------
      Rectangle {
        anchors.fill: parent
        visible: !Backend.ready || Backend.fatal !== ""
        color: Theme.bg
        z: 100
        Txt {
          anchors.centerIn: parent
          width: parent.width * 0.6
          horizontalAlignment: Text.AlignHCenter
          wrapMode: Text.Wrap
          elide: Text.ElideNone
          text: Backend.fatal || "Reading vault…"
          color: Backend.fatal ? Theme.red : Theme.faint
        }
      }

      // Delete confirmation ---------------------------------------------------
      Rectangle {
        id: confirm
        property var task: null
        visible: false
        anchors.fill: parent
        color: Theme.a(Theme.bg, 0.7)
        z: 90
        onVisibleChanged: if (visible) confirmBox.forceActiveFocus()
        MouseArea { anchors.fill: parent; onClicked: confirm.visible = false }
        Rectangle {
          id: confirmBox
          anchors.centerIn: parent
          width: Theme.px(440); height: cc.implicitHeight + Theme.px(28)
          color: Theme.bg
          border.color: Theme.red
          focus: true
          Keys.onEscapePressed: { confirm.visible = false; root.forceActiveFocus() }
          Keys.onReturnPressed: del()
          function del() {
            var gone = confirm.task
            Backend.remove(gone, function (r) {
              if (r.ok) Backend.notice("info", gone.rawLine !== undefined ? "Line removed" : "Moved to " + r.result.trashedTo)
            })
            confirm.visible = false
            root.forceActiveFocus()
          }
          Column {
            id: cc
            anchors { left: parent.left; right: parent.right; top: parent.top; margins: Theme.px(14) }
            spacing: Theme.px(10)
            Txt { text: "Delete this task?"; font.bold: true; font.pixelSize: Theme.fsLarge }
            Txt { width: parent.width; text: confirm.task ? confirm.task.title : ""; wrapMode: Text.Wrap; elide: Text.ElideNone }
            Txt { width: parent.width; color: Theme.faint; font.pixelSize: Theme.fsSmall; wrapMode: Text.Wrap; elide: Text.ElideNone
                  text: confirm.task && confirm.task.rawLine !== undefined
                        ? "The line is removed from " + confirm.task.file + ". (Obsidian's file history can bring it back.)"
                        : "The note goes to the trash Obsidian uses for this vault, so it can be restored." }
            Row {
              spacing: 8
              Btn { text: "Delete (Enter)"; textColor: Theme.red; onClicked: confirmBox.del() }
              Btn { text: "Cancel (Esc)"; onClicked: { confirm.visible = false; root.forceActiveFocus() } }
            }
          }
        }
      }

      ViewEditor {
        id: viewEditor
        anchors.fill: parent
        onSaved: id => root.pickView(id)
        onDeleted: f => { if (root.currentBase === null || root.currentBase.file === f) root.pickView("today") }
        onClosed: root.forceActiveFocus()
      }

      Picker {
        id: picker
        Component.onCompleted: Backend.picker = picker
      }

      DatePicker {
        id: datePicker
        Component.onCompleted: Backend.datePicker = datePicker
      }

      SettingsDialog {
        id: settingsDlg
        anchors.fill: parent
        onClosed: root.forceActiveFocus()
      }

      ContextMenu {
        id: ctxMenu
        onFinished: if (!viewEditor.visible && !confirm.visible) root.forceActiveFocus()
      }

      // Shortcut help ---------------------------------------------------------
      Rectangle {
        id: help
        visible: false
        anchors.centerIn: parent
        width: Theme.px(460); height: hc.implicitHeight + Theme.px(28)
        color: Theme.bg
        border.color: Theme.accent
        z: 80
        Column {
          id: hc
          anchors { left: parent.left; right: parent.right; top: parent.top; margins: Theme.px(14) }
          spacing: 4
          Txt { text: "Keys"; font.bold: true; font.pixelSize: Theme.fsLarge; bottomPadding: 6 }
          Repeater {
            model: [
              ["j / k", "next / previous task"], ["[ / ]", "previous / next list"], ["1–5", "Today, Upcoming, All, Completed, Archived"],
              ["x / space", "complete (this occurrence, if repeating)"], ["s / S", "next / previous status"], ["+ / -", "raise / lower priority"],
              ["n", "new task in this list"], ["right-click / Menu", "actions for a task or list"], ["Tab", "edit fields (Tab / Shift+Tab between, Esc back)"], ["Ctrl+Tab", "next pane: lists, tasks, task (Shift: back)"], ["/", "filter"], ["b", "list / board"], ["d", "toggle detail pane"],
              ["o", "open in Obsidian"], ["Ctrl+S", "save notes"], ["Ctrl+Q", "quit"], ["?", "this help"]
            ]
            Row {
              required property var modelData
              Txt { width: Theme.px(110); text: modelData[0]; color: Theme.accent }
              Txt { text: modelData[1] }
            }
          }
        }
      }
    }
  }
}
