import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import ".."
import "../views.js" as V
import "../dates.js" as D
import "../recur.js" as R

// Editor for one task. Every control writes one field via Backend.update,
// which compare-and-swaps against the value shown here.
Rectangle {
  id: d
  property var task: null
  property bool closable: false
  signal closeRequested()
  signal leave()          // Esc out of an entry box: back to the list

  function focusFirst() { titleEdit.forceActiveFocus(); titleEdit.selectAll() }
  // TextEdit swallows Tab (it would insert \t), so move focus ourselves.
  function tabFrom(item, forward) {
    var next = item.nextItemInFocusChain(forward)
    if (next) next.forceActiveFocus()
  }
  signal openInObsidian(var task)
  signal requestDelete(var task)
  signal requestMenu(var items, real x, real y)   // shown by the window's ContextMenu

  // Tasks plugin mode: a task is a checkbox line, with Tasks' own fields.
  readonly property bool tasksMode: Backend.mode === "tasks"
  // In Tasks mode the core describes Tasks' statuses/priorities in the same
  // shape as TaskNotes' (see inline.settings_public), so these just work.
  readonly property var statusOptions: Backend.settings.statuses
  readonly property var priorityOptions: Backend.settings.priorities.slice().reverse()

  // Reminders ----------------------------------------------------------------
  // TaskNotes' Reminder objects: {id, type: relative|absolute, relatedTo,
  // offset (ISO 8601 duration), absoluteTime, description}.
  function reminders() { return d.task && d.task.props && Array.isArray(d.task.props.reminders) ? d.task.props.reminders : [] }
  function durText(iso) {
    var m = String(iso || "").match(/^([+-])?P(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?)?$/)
    if (!m) return iso
    var parts = []
    if (m[2]) parts.push(m[2] + "w"); if (m[3]) parts.push(m[3] + "d"); if (m[4]) parts.push(m[4] + "h"); if (m[5]) parts.push(m[5] + "m")
    return { sign: m[1] === "-" ? -1 : 1, text: parts.join(" ") || "0m" }
  }
  function reminderText(r) {
    if (r.type === "absolute") return "At " + D.pretty(String(r.absoluteTime || "").slice(0, 16), new Date())
    var dt = durText(r.offset), anchor = r.relatedTo === "scheduled" ? "scheduled" : "due"
    if (typeof dt === "string") return dt + " (" + anchor + ")"
    if (dt.text === "0m") return "At " + anchor + " time"
    // A date-only anchor is midnight, so "+9h" reads better as a clock time.
    var anchorVal = d.task ? d.task[anchor] : ""
    if (anchorVal && anchorVal.length === 10) {
      var mins = 0, m = String(r.offset).match(/^([+-])?P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?)?$/)
      if (m) {
        mins = (Number(m[2] || 0) * 1440 + Number(m[3] || 0) * 60 + Number(m[4] || 0)) * (m[1] === "-" ? -1 : 1)
        var dayOff = Math.floor(mins / 1440), hm = ((mins % 1440) + 1440) % 1440
        var clock = ("0" + Math.floor(hm / 60)).slice(-2) + ":" + ("0" + hm % 60).slice(-2)
        return (dayOff === 0 ? "On the " + anchor + " day" : dayOff === -1 ? "Day before " + anchor : Math.abs(dayOff) + " days " + (dayOff < 0 ? "before " : "after ") + anchor) + " at " + clock
      }
    }
    return dt.text + (dt.sign < 0 ? " before " : " after ") + anchor
  }
  function setReminders(list) { d.set("reminders", list) }
  function addReminder(r) {
    var list = reminders().slice()
    r.id = "rem_" + Date.now()
    list.push(r)
    setReminders(list)
  }
  function reminderPresets() {
    var items = [], t = d.task
    ;["due", "scheduled"].forEach(function (anchor) {
      var v = t ? t[anchor] : ""
      if (!v) return
      var label = anchor === "due" ? "Due" : "Scheduled"
      items.push({ header: label + " " + V.prettyDate(v, Backend.today) })
      var rel = function (offset) { return function () { d.addReminder({ type: "relative", relatedTo: anchor, offset: offset }) } }
      if (v.length > 10) {
        items.push({ text: "At the time", action: rel("PT0M") })
        items.push({ text: "5 minutes before", action: rel("-PT5M") })
        items.push({ text: "15 minutes before", action: rel("-PT15M") })
        items.push({ text: "1 hour before", action: rel("-PT1H") })
        items.push({ text: "1 day before", action: rel("-P1D") })
      } else {
        items.push({ text: "On the day at 09:00", action: rel("PT9H") })
        items.push({ text: "Day before at 18:00", action: rel("-PT6H") })
        items.push({ text: "Two days before at 09:00", action: rel("-P1DT15H") })
      }
    })
    if (!items.length) items.push({ text: "Give the task a due or scheduled date for relative reminders", enabled: false })
    items.push({ separator: true })
    var at = function (text) { return function () { var r = D.parse(text, new Date(), Backend.prefs.dates); d.addReminder({ type: "absolute", absoluteTime: r.value + ":00" }) } }
    var dflt = (Backend.prefs.dates || {}).defaultTime || "09:00"
    items.push({ text: "In 10 minutes", icon: "󰔟", action: at("+10m") })
    items.push({ text: "In 1 hour", icon: "󰔟", action: at("+1h") })
    items.push({ text: "Tomorrow at " + dflt, icon: "󰃭", action: at("tomorrow " + dflt) })
    items.push({ text: "At a specific time…", icon: "󰥔", hint: "fri 3pm, +2h", action: function () { absField.visible = true; absField.input.forceActiveFocus() } })
    return items
  }
  color: Theme.a(Theme.fg, 0.02)

  property string bodyText: ""
  property string bodyHash: ""
  property string bodyFor: ""
  property bool bodyDirty: false

  onTaskChanged: {
    if (!task) { bodyFor = ""; return }
    if (task.path !== bodyFor) loadBody()
  }
  function loadBody() {
    if (bodyDirty && bodyFor) saveBody()
    var path = task.path
    bodyFor = path
    bodyDirty = false
    if (task.error) { bodyText = ""; return }
    Backend.body(task, function (r) {
      if (!r.ok || !d.task || d.task.path !== path) return
      d.bodyText = r.result.body
      d.bodyHash = r.result.hash
      bodyArea.text = r.result.body
      d.bodyDirty = false
    })
  }
  function saveBody() {
    if (!bodyDirty || !bodyFor) return
    var t = Backend.tasks[bodyFor]
    if (!t) return
    var text = bodyArea.text
    var path = bodyFor
    Backend.saveBody(t, text, bodyHash, function (r) {
      if (r.ok) { if (d.bodyFor === path) { d.bodyHash = r.result.hash; d.bodyDirty = bodyArea.text !== text } }
    })
  }

  function set(field, value, target) {
    var t = target || d.task
    if (!t) return
    var f = {}
    f[field] = value
    Backend.update(t, f)
  }
  function splitList(s) {
    return s.split(",").map(function (x) { return x.trim() }).filter(function (x) { return x.length })
  }


  Txt {
    anchors.centerIn: parent
    visible: !d.task
    text: "Select a task"
    color: Theme.faint
  }

  ScrollView {
    id: scroll
    visible: !!d.task
    anchors.fill: parent
    contentWidth: availableWidth
    ScrollBar.horizontal.policy: ScrollBar.AlwaysOff

    ColumnLayout {
      width: scroll.availableWidth
      spacing: Theme.px(12)

      Item {
        Layout.fillWidth: true
        Layout.preferredHeight: d.closable ? Theme.px(30) : Theme.px(4)
        Btn {
          visible: d.closable
          anchors { right: parent.right; rightMargin: Theme.pad; bottom: parent.bottom }
          quiet: true; text: "✕"; tip: "Close (Esc)"
          onClicked: d.closeRequested()
        }
      }

      // Problem files: show why, never offer edits.
      Rectangle {
        visible: !!(d.task && d.task.error)
        Layout.fillWidth: true
        Layout.leftMargin: Theme.pad; Layout.rightMargin: Theme.pad
        implicitHeight: errCol.implicitHeight + Theme.px(16)
        color: Theme.a(Theme.red, 0.12)
        border.color: Theme.a(Theme.red, 0.5)
        Column {
          id: errCol
          anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter; margins: Theme.px(8) }
          spacing: 4
          Txt { text: "Can't read this note's properties"; font.bold: true; color: Theme.red }
          Txt { width: parent.width; wrapMode: Text.Wrap; elide: Text.ElideNone; text: d.task ? d.task.error : ""; color: Theme.fg; font.pixelSize: Theme.fsSmall }
          Txt { width: parent.width; wrapMode: Text.Wrap; elide: Text.ElideNone; color: Theme.faint; font.pixelSize: Theme.fsSmall
                text: "TaskNotes can't read it either. OmaForge won't write to it — fix the YAML in Obsidian and it will reappear." }
        }
      }

      // Title wraps (they're often sentences). Enter commits, Shift+Enter
      // is ignored: a title is one line in the file.
      Rectangle {
        visible: !!(d.task && !d.task.error)
        Layout.fillWidth: true
        Layout.leftMargin: Theme.pad; Layout.rightMargin: Theme.pad
        implicitHeight: titleEdit.contentHeight + Theme.px(14)
        color: titleEdit.activeFocus ? Theme.hoverFill : "transparent"
        border.width: titleEdit.activeFocus ? 1 : 0
        border.color: Theme.accent
        TextEdit {
          id: titleEdit
          anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter; margins: Theme.px(7) }
          wrapMode: TextEdit.Wrap
          color: Theme.fg
          selectionColor: Theme.a(Theme.accent, 0.4)
          font.family: Theme.font
          font.pixelSize: Theme.fsLarge
          font.bold: true
          property var target: null
          property string initial: ""
          activeFocusOnTab: true
          text: d.task ? d.task.title : ""
          onActiveFocusChanged: {
            if (activeFocus) { target = d.task; initial = text }
            else commit()
          }
          function commit() {
            var v = text.replace(/\s+/g, " ").trim()
            if (target && v && v !== initial) { initial = v; d.set("title", v, target) }
            else if (!v) text = initial
          }
          Keys.onPressed: e => {
            if (e.key === Qt.Key_Return || e.key === Qt.Key_Enter) { commit(); d.leave(); e.accepted = true }
            else if (e.key === Qt.Key_Escape) { text = initial; d.leave(); e.accepted = true }
            else if (e.key === Qt.Key_Tab) { d.tabFrom(titleEdit, true); e.accepted = true }
            else if (e.key === Qt.Key_Backtab) { d.tabFrom(titleEdit, false); e.accepted = true }
          }
        }
      }

      GridLayout {
        visible: !!(d.task && !d.task.error)
        Layout.fillWidth: true
        Layout.leftMargin: Theme.pad; Layout.rightMargin: Theme.pad
        columns: 2
        columnSpacing: Theme.px(12)
        rowSpacing: Theme.px(8)

        Txt { text: "Status"; color: Theme.faint }
        Flow {
          Layout.fillWidth: true
          spacing: 6
          Repeater {
            model: d.statusOptions
            Chip {
              required property var modelData
              text: modelData.label || modelData.value
              tint: Theme.tint(modelData.color)
              filled: d.task && d.task.status === modelData.value
              onClicked: if (d.task.status !== modelData.value) Backend.setStatus(d.task, modelData.value)
            }
          }
        }

        Txt { text: "Priority"; color: Theme.faint }
        Flow {
          Layout.fillWidth: true
          spacing: 6
          Repeater {
            model: d.priorityOptions
            Chip {
              required property var modelData
              text: modelData.label || modelData.value
              tint: Theme.tint(modelData.color)
              filled: d.task && d.task.priority === modelData.value
              onClicked: d.set("priority", modelData.value)
            }
          }
        }

        Txt { text: "Due"; color: Theme.faint }
        DateRow { field: "due"; Layout.fillWidth: true }

        Txt { text: "Scheduled"; color: Theme.faint }
        DateRow { field: "scheduled"; Layout.fillWidth: true }

        Txt { text: "Start"; color: Theme.faint; visible: d.tasksMode }
        DateRow { field: "start"; Layout.fillWidth: true; visible: d.tasksMode }

        Txt { text: "Repeats"; color: Theme.faint; Layout.alignment: Qt.AlignTop; topPadding: 6 }
        Column {
          Layout.fillWidth: true
          spacing: 6
          Row {
            spacing: 4
            Field {
              id: recField
              width: Theme.px(230)
              tabbable: true
              ctx: d.task
              placeholder: "every weekday, every 2 weeks on fri…"
              text: d.task && d.task.recurrence ? (d.tasksMode ? d.task.recurrence : R.describe(d.task.recurrence)) : ""
              onEscaped: d.leave()
              onCommitted: (v, t) => {
                var r = R.parse(v, new Date())
                if (r.error) { Backend.notice("warn", r.error); input.text = t && t.recurrence ? (d.tasksMode ? t.recurrence : R.describe(t.recurrence)) : ""; return }
                d.set("recurrence", r.clear ? "" : r.rule, t)
              }
            }
            Btn {
              id: recPresetBtn
              quiet: true; text: "▾"; tip: "Common repeats"
              implicitHeight: recField.height
              onClicked: { var p = recPresetBtn.mapToItem(null, 0, recPresetBtn.height); d.requestMenu(d.repeatPresets(), p.x, p.y) }
            }
          }
          Txt {
            readonly property var pv: recField.input.activeFocus && recField.input.text !== recField._initial && recField.input.text.trim() !== ""
                                       ? R.parse(recField.input.text, new Date()) : null
            visible: !!pv
            text: !pv ? "" : pv.clear ? "→ doesn't repeat" : pv.error ? "? " + pv.error : "→ " + pv.text
            color: pv && pv.error ? Theme.yellow : Theme.accent
            font.pixelSize: Theme.fsSmall
            width: parent.width; wrapMode: Text.Wrap; elide: Text.ElideNone
          }
          Row {
            visible: !!(d.task && d.task.recurring)
            spacing: 4
            Txt { text: "Next one counts from"; color: Theme.faint; font.pixelSize: Theme.fsSmall; height: Theme.px(24) }
            Btn {
              implicitHeight: Theme.px(24); text: "the schedule"
              active: !!(d.task && !d.isWhenDone(d.task))
              onClicked: d.tasksMode ? d.set("whenDone", false) : d.set("recurrenceAnchor", "scheduled")
            }
            Btn {
              implicitHeight: Theme.px(24); text: "when done"
              active: !!(d.task && d.isWhenDone(d.task))
              onClicked: d.tasksMode ? d.set("whenDone", true) : d.set("recurrenceAnchor", "completion")
            }
          }
          Row {
            spacing: 6
            visible: !!(d.task && d.task.recurring && d.task.occurrence)
            Txt { text: d.task && d.task.occurrence ? "Next: " + V.prettyDate(d.task.occurrence, Backend.today) : ""; color: Theme.faint; height: Theme.px(26) }
            Btn { text: "Done"; onClicked: Backend.toggleComplete(d.task, "") }
            Btn { text: "Skip"; visible: !d.tasksMode; onClicked: Backend.skip(d.task, "") }
          }
          Txt {
            visible: !!(d.task && d.task.recurring)
            text: d.task ? (d.task.completeInstances || []).length + " done, " + (d.task.skippedInstances || []).length + " skipped" : ""
            color: Theme.faint; font.pixelSize: Theme.fsSmall
          }
        }

        Txt { text: "Projects"; color: Theme.faint; visible: !d.tasksMode }
        Field {
          visible: !d.tasksMode
          tabbable: true
          onEscaped: d.leave()
          Layout.fillWidth: true
          text: d.task ? (d.task.projectsRaw || []).join(", ") : ""
          ctx: d.task
          placeholder: "[[Project note]], …"
          onCommitted: (v, t) => d.set("projects", d.splitList(v).map(function (p) { return /^\[\[.*\]\]$/.test(p) ? p : "[[" + p + "]]" }), t)
        }

        Txt { text: "Contexts"; color: Theme.faint; visible: !d.tasksMode }
        Field {
          visible: !d.tasksMode
          tabbable: true
          onEscaped: d.leave()
          Layout.fillWidth: true
          text: d.task ? (d.task.contexts || []).join(", ") : ""
          ctx: d.task
          placeholder: "home, phone, …"
          onCommitted: (v, t) => d.set("contexts", d.splitList(v).map(function (c) { return c.replace(/^@/, "") }), t)
        }

        Txt { text: "Tags"; color: Theme.faint }
        Field {
          tabbable: true
          onEscaped: d.leave()
          Layout.fillWidth: true
          text: d.task ? (d.task.tags || []).join(", ") : ""
          ctx: d.task
          placeholder: "tag, other/tag"
          onCommitted: (v, t) => d.set("tags", d.splitList(v).map(function (x) { return x.replace(/^#/, "") }), t)
        }

        Txt { text: "Reminders"; color: Theme.faint; Layout.alignment: Qt.AlignTop; topPadding: 4; visible: !d.tasksMode }
        Column {
          visible: !d.tasksMode
          Layout.fillWidth: true
          spacing: 4
          Repeater {
            model: d.reminders()
            Row {
              required property var modelData
              required property int index
              spacing: 6
              Txt { text: "󰂚 " + d.reminderText(modelData); height: Theme.px(22) }
              Btn {
                quiet: true; text: "✕"; tip: "Remove reminder"; implicitHeight: Theme.px(22)
                onClicked: { var l = d.reminders().slice(); l.splice(index, 1); d.setReminders(l) }
              }
            }
          }
          Row {
            spacing: 6
            Btn {
              id: addRemBtn
              text: "+ reminder"; quiet: true
              onClicked: { var p = addRemBtn.mapToItem(null, 0, addRemBtn.height); d.requestMenu(d.reminderPresets(), p.x, p.y) }
            }
            DateField {
              id: absField
              visible: false
              width: Theme.px(210)
              ctx: d.task
              placeholder: "+10m, fri 3pm, tomorrow 9am"
              onPicked: (v, t) => {
                if (!v) { visible = false; return }
                // A reminder needs a time; a bare date gets the default (or 09:00).
                var full = v.length > 10 ? v : v + "T" + ((Backend.prefs.dates || {}).defaultTime || "09:00")
                d.addReminder({ type: "absolute", absoluteTime: full + ":00" })
                input.text = ""; visible = false
              }
              onEscaped: { input.text = ""; visible = false; d.leave() }
            }
          }
        }

        Txt { text: "Blocked by"; color: Theme.faint; Layout.alignment: Qt.AlignTop; topPadding: 4 }
        Column {
          Layout.fillWidth: true
          spacing: 2
          Repeater {
            model: d.task ? d.task.blockedBy : []
            Row {
              required property var modelData
              required property int index
              spacing: 6
              Txt {
                height: Theme.px(22)
                text: (modelData.done ? "✓ " : "⛔ ") + modelData.title + (modelData.path ? "" : "  (not found)")
                color: modelData.done ? Theme.faint : Theme.fg
              }
              Btn { quiet: true; text: "✕"; tip: "Remove"; implicitHeight: Theme.px(22); onClicked: d.setBlockers(d.blockersExcept(index)) }
            }
          }
          Btn {
            id: addBlockBtn
            quiet: true; text: "+ blocked by…"
            onClicked: d.pickBlocker(addBlockBtn)
          }
        }

        Txt { text: "Blocking"; color: Theme.faint; visible: d.blocking.length > 0; Layout.alignment: Qt.AlignTop }
        Column {
          visible: d.blocking.length > 0
          Layout.fillWidth: true
          Repeater {
            model: d.blocking
            Txt { required property var modelData; text: "→ " + modelData.title; color: modelData.done ? Theme.faint : Theme.fg }
          }
        }
      }

      // Tasks mode: where the line lives (no body: a task is one line).
      Txt {
        visible: !!(d.tasksMode && d.task)
        Layout.fillWidth: true
        Layout.leftMargin: Theme.pad; Layout.rightMargin: Theme.pad
        wrapMode: Text.WrapAnywhere; elide: Text.ElideNone
        font.pixelSize: Theme.fsSmall
        color: Theme.faint
        text: d.task && d.tasksMode ? "In " + d.task.file + ", line " + (d.task.line + 1) + "\n" + (d.task.rawLine || "").trim() : ""
      }

      // Body ---------------------------------------------------------------
      Rectangle {
        visible: !!(d.task && !d.task.error && !d.tasksMode)
        Layout.fillWidth: true
        Layout.leftMargin: Theme.pad; Layout.rightMargin: Theme.pad
        Layout.preferredHeight: Math.max(Theme.px(180), bodyArea.implicitHeight + Theme.px(16))
        color: bodyArea.activeFocus ? Theme.hoverFill : Theme.normalFill
        border.width: 1
        border.color: bodyArea.activeFocus ? Theme.accent : Theme.a(Theme.fg, 0.18)
        TextEdit {
          id: bodyArea
          anchors.fill: parent
          anchors.margins: Theme.px(8)
          wrapMode: TextEdit.Wrap
          color: Theme.fg
          selectionColor: Theme.a(Theme.accent, 0.4)
          font.family: Theme.font
          font.pixelSize: Theme.fs
          activeFocusOnTab: true
          onTextChanged: if (activeFocus) d.bodyDirty = text !== d.bodyText
          onActiveFocusChanged: if (!activeFocus) d.saveBody()
          Keys.onPressed: e => {
            if (e.key === Qt.Key_S && (e.modifiers & Qt.ControlModifier)) { d.saveBody(); e.accepted = true }
            else if (e.key === Qt.Key_Escape) { d.saveBody(); d.leave(); e.accepted = true }
            else if (e.key === Qt.Key_Tab) { d.tabFrom(bodyArea, true); e.accepted = true }
            else if (e.key === Qt.Key_Backtab) { d.tabFrom(bodyArea, false); e.accepted = true }
          }
        }
        Txt {
          anchors { left: parent.left; top: parent.top; margins: Theme.px(8) }
          visible: bodyArea.text === "" && !bodyArea.activeFocus
          text: "Notes…"
          color: Theme.a(Theme.fg, 0.35)
        }
        Txt {
          anchors { right: parent.right; bottom: parent.bottom; margins: 4 }
          visible: d.bodyDirty
          text: "unsaved · Ctrl+S"
          font.pixelSize: Theme.fsSmall
          color: Theme.yellow
        }
      }

      // Footer ---------------------------------------------------------------
      Flow {
        visible: !!d.task
        Layout.fillWidth: true
        Layout.leftMargin: Theme.pad; Layout.rightMargin: Theme.pad
        spacing: 6
        Btn { text: "Open in Obsidian"; icon: "󰏌"; onClicked: d.openInObsidian(d.task) }
        Btn { visible: !!(d.task && !d.task.error && !d.tasksMode); text: d.task && d.task.archived ? "Unarchive" : "Archive"; icon: "󰆧"; onClicked: Backend.archive(d.task, !d.task.archived) }
        Btn { visible: !!(d.task && !d.task.error); text: "Delete"; icon: "󰆴"; textColor: Theme.red; onClicked: d.requestDelete(d.task) }
      }
      Txt {
        visible: !!d.task
        Layout.fillWidth: true
        Layout.leftMargin: Theme.pad; Layout.rightMargin: Theme.pad
        Layout.bottomMargin: Theme.pad
        wrapMode: Text.WrapAnywhere
        elide: Text.ElideNone
        font.pixelSize: Theme.fsSmall
        color: Theme.a(Theme.fg, 0.4)
        text: !d.task ? "" : d.tasksMode
              ? (d.task.created ? "created " + d.task.created : "") + (d.task.completedDate ? (d.task.created ? " · " : "") + (d.task.statusType === "CANCELLED" ? "cancelled " : "done ") + d.task.completedDate : "")
              : d.task.path + (d.task.dateCreated ? "\ncreated " + V.d10(d.task.dateCreated) : "") + (d.task.dateModified ? " · modified " + V.d10(d.task.dateModified) : "")
      }
    }
  }

  // Repeats -------------------------------------------------------------------
  function isWhenDone(t) { return d.tasksMode ? !!t.whenDone : !!(t.props && t.props.recurrence_anchor === "completion") }
  function weekdayOf(v) { var a = (v || Backend.today).slice(0, 10).split("-"); return new Date(+a[0], +a[1] - 1, +a[2]) }
  function repeatPresets() {
    var base = weekdayOf(d.task && (d.task.scheduled || d.task.due))
    var dn = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"][base.getDay()]
    var mons = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    var set = function (text) { return function () { var r = R.parse(text, new Date()); d.set("recurrence", r.clear ? "" : r.rule) } }
    var cur = d.task && d.task.recurrence ? d.task.recurrence : ""
    var items = [
      { text: "Every day", action: set("daily") },
      { text: "Every weekday", action: set("weekdays") },
      { text: "Every week on " + dn, action: set("every week on " + dn) },
      { text: "Every other week on " + dn, action: set("every 2 weeks on " + dn) },
      { text: "Every month on the " + R.ordinal(base.getDate()), action: set("monthly on the " + base.getDate()) },
      { text: "Every year on " + base.getDate() + " " + mons[base.getMonth()], action: set("every year on " + base.getDate() + " " + mons[base.getMonth()]) },
      { separator: true },
      { text: "Doesn't repeat", enabled: !!cur, action: set("none") }]
    return items
  }

  // Dependencies ----------------------------------------------------------------
  // The raw blockedBy entries, as dicts the core can write back unchanged.
  function rawBlockers() {
    var raw = d.task && d.task.raw ? d.task.raw.blockedBy : null
    return (Array.isArray(raw) ? raw : raw ? [raw] : []).map(function (b) { return typeof b === "string" ? { uid: b } : b })
  }
  function blockersExcept(i) { var l = rawBlockers(); l.splice(i, 1); return l }
  function setBlockers(list) { d.set("blockedBy", list) }
  // Tasks that list this one in their blockedBy.
  readonly property var blocking: {
    Backend.revision
    if (!d.task) return []
    var out = []
    for (var p in Backend.tasks) {
      var t = Backend.tasks[p]
      if (t.error || !t.blockedBy) continue
      for (var i = 0; i < t.blockedBy.length; i++) if (t.blockedBy[i].path === d.task.path) { out.push(t); break }
    }
    return out
  }
  function pickBlocker(anchor, forTask) {
    var task = forTask || d.task
    var already = (task.blockedBy || []).map(function (b) { return b.path })
    var opts = []
    for (var p in Backend.tasks) {
      var t = Backend.tasks[p]
      if (t.error || t.archived || t.path === task.path || already.indexOf(t.path) >= 0) continue
      if (!(t.title || "").trim()) continue     // an empty "- [ ]" line: nothing to pick it by
      var where = d.tasksMode ? (t.notes || []) : (t.projects || []).concat((t.contexts || []).map(function (c) { return "@" + c }))
      opts.push({ label: t.title, sub: (t.done ? "done · " : "") + where.join("  "), value: t.path, done: t.done })
    }
    opts.sort(function (a, b) { return (a.done - b.done) || a.label.localeCompare(b.label) })
    Backend.picker.open(anchor, "Blocked by which task?", opts, function (path) {
      var raw = task.raw ? task.raw.blockedBy : null
      var list = (Array.isArray(raw) ? raw : raw ? [raw] : []).map(function (b) { return typeof b === "string" ? { uid: b } : b })
      list.push({ path: path })
      Backend.update(task, { blockedBy: list })
    })
  }

  // Default time from Settings, for dates picked without one.
  function withDefault(day) {
    if (d.tasksMode) return day     // Tasks dates have no time
    var p = Backend.prefs.dates || {}
    return p.useDefaultTime && p.defaultTime ? day + "T" + p.defaultTime : day
  }
  // Move a date by n days, keeping its time (or using the default time).
  function shifted(v, n) {
    if (!v) return withDefault(V.addDays(Backend.today, n))
    return V.addDays(v.slice(0, 10), n) + v.slice(10)
  }

  component DateRow: Flow {
    id: dr
    property string field
    spacing: 6
    DateField {
      dateOnly: d.tasksMode     // Tasks dates have no time
      width: Theme.px(190)
      value: d.task && d.task[dr.field] ? d.task[dr.field] : ""
      ctx: d.task
      onPicked: (v, t) => d.set(dr.field, v, t)
      onEscaped: d.leave()
    }
    Btn { quiet: true; text: "Today"; onClicked: { var v = d.task[dr.field]; d.set(dr.field, v && v.length > 10 ? Backend.today + v.slice(10) : d.withDefault(Backend.today)) } }
    Btn { quiet: true; text: "+1d"; onClicked: d.set(dr.field, d.shifted(d.task[dr.field], 1)) }
    Btn { quiet: true; text: "+1w"; onClicked: d.set(dr.field, d.shifted(d.task[dr.field], 7)) }
    Btn { quiet: true; text: "✕"; tip: "Clear"; visible: !!(d.task && d.task[dr.field]); onClicked: d.set(dr.field, "") }
  }
}
