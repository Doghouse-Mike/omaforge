import QtQuick
import ".."

// Notification settings (config.json -> "notifications"), read and written by
// the core; the omaforge-notify service picks changes up on its next poll.
Rectangle {
  id: dlg
  visible: false
  color: Theme.a(Theme.bg, 0.75)
  z: 96
  signal closed()

  property var s: null
  property var dates: ({ defaultTime: "09:00", useDefaultTime: true })
  property var service: ({ active: "unknown", enabled: "unknown" })
  property var dnd: null    // Omarchy's Do Not Disturb (null = unknown)
  property bool dirty: false

  function open() {
    Backend.request("getNotify", {}, function (r) {
      if (!r.ok) return
      dlg.s = r.result.settings
      dlg.dates = r.result.dates
      dlg.dnd = r.result.dnd
      dlg.service = r.result.service
      dlg.dirty = false
      dlg.visible = true
      box.forceActiveFocus()
    })
  }
  function close() { visible = false; closed() }
  function touch() { s = JSON.parse(JSON.stringify(s)); dirty = true }
  function save() {
    Backend.request("setNotify", { settings: s, dates: dates }, function (r) {
      if (!r.ok) return
      Backend.prefs = { dates: r.result.dates }
      dlg.s = r.result.settings
      dlg.service = r.result.service
      dlg.dirty = false
      Backend.notice("info", "Notification settings saved")
      dlg.close()
    })
  }

  MouseArea { anchors.fill: parent; onClicked: dlg.close() }

  Rectangle {
    id: box
    anchors.centerIn: parent
    width: Math.min(Theme.px(560), dlg.width - Theme.px(32))
    height: col.implicitHeight + Theme.px(28)
    color: Theme.bg
    border.color: Theme.accent
    focus: true
    MouseArea { anchors.fill: parent }
    Keys.onEscapePressed: dlg.close()
    Keys.onPressed: e => {
      if ((e.key === Qt.Key_Return || e.key === Qt.Key_Enter) && (e.modifiers & Qt.ControlModifier)) { dlg.save(); e.accepted = true }
    }

    Column {
      id: col
      x: Theme.px(14); y: Theme.px(14)
      width: parent.width - Theme.px(28)
      spacing: Theme.px(12)

      Txt { text: "Dates"; font.bold: true; font.pixelSize: Theme.fsLarge }
      Section {
        title: "Default time"
        hint: "Picking or typing a date without a time gives it this time. Note: TaskNotes counts a task due at a time as overdue from that time, not from the end of the day."
        Toggle { on: !!dlg.dates.useDefaultTime; onToggled: v => { dlg.dates.useDefaultTime = v; dlg.dates = JSON.parse(JSON.stringify(dlg.dates)); dlg.dirty = true } }
        Txt { text: "  time"; color: Theme.faint; height: Theme.px(26) }
        Field {
          width: Theme.px(64)
          tabbable: true
          text: dlg.dates.defaultTime
          onCommitted: v => { dlg.dates.defaultTime = v.trim(); dlg.dates = JSON.parse(JSON.stringify(dlg.dates)); dlg.dirty = true }
        }
      }
      Rectangle { width: col.width; height: 1; color: Theme.divider }

      Txt { text: "Notifications"; font.bold: true; font.pixelSize: Theme.fsLarge }

      component Toggle: Row {
        id: tg
        property bool on: false
        signal toggled(bool v)
        spacing: 4
        Btn { text: "on"; active: tg.on; onClicked: tg.toggled(true) }
        Btn { text: "off"; active: !tg.on; onClicked: tg.toggled(false) }
      }
      component Section: Column {
        property string title
        property string hint
        default property alias content: inner.data
        width: col.width
        spacing: 4
        Txt { text: parent.title; font.bold: true }
        Txt { visible: parent.hint !== ""; width: col.width; text: parent.hint; color: Theme.faint; font.pixelSize: Theme.fsSmall; wrapMode: Text.Wrap; elide: Text.ElideNone }
        Row { id: inner; spacing: 8 }
      }

      Section {
        title: "Reminders"
        hint: "TaskNotes reminders on a task (add them in the task pane). Fire up to a day late if the computer was off."
        Toggle { on: !!(dlg.s && dlg.s.reminders.enabled); onToggled: v => { dlg.s.reminders.enabled = v; dlg.touch() } }
      }
      Section {
        title: "Tasks with a time"
        hint: "A task due or scheduled at a time (e.g. 14:00) notifies at that time, no reminder needed."
        Toggle { on: !!(dlg.s && dlg.s.timedTasks.enabled); onToggled: v => { dlg.s.timedTasks.enabled = v; dlg.touch() } }
        Txt { text: "  notify"; color: Theme.faint; height: Theme.px(26) }
        Field {
          width: Theme.px(48)
          tabbable: true
          text: dlg.s ? String(dlg.s.timedTasks.minutesBefore) : "0"
          onCommitted: v => { var n = parseInt(v); if (!isNaN(n) && n >= 0) { dlg.s.timedTasks.minutesBefore = n; dlg.touch() } }
        }
        Txt { text: "minutes early"; color: Theme.faint; height: Theme.px(26) }
      }
      Section {
        title: "Morning summary"
        hint: "Once a day: how many tasks are for today and overdue."
        Toggle { on: !!(dlg.s && dlg.s.morningSummary.enabled); onToggled: v => { dlg.s.morningSummary.enabled = v; dlg.touch() } }
        Txt { text: "  at"; color: Theme.faint; height: Theme.px(26) }
        Field {
          width: Theme.px(64)
          tabbable: true
          text: dlg.s ? dlg.s.morningSummary.time : "09:00"
          onCommitted: v => { dlg.s.morningSummary.time = v.trim(); dlg.touch() }
        }
      }
      Section {
        title: "Overdue nudge"
        hint: "Once a day, only if something is overdue."
        Toggle { on: !!(dlg.s && dlg.s.overdue.enabled); onToggled: v => { dlg.s.overdue.enabled = v; dlg.touch() } }
        Txt { text: "  at"; color: Theme.faint; height: Theme.px(26) }
        Field {
          width: Theme.px(64)
          tabbable: true
          text: dlg.s ? dlg.s.overdue.time : "17:00"
          onCommitted: v => { dlg.s.overdue.time = v.trim(); dlg.touch() }
        }
      }
      Section {
        title: "Break through Do Not Disturb"
        hint: "Send reminders and timed tasks as urgent alerts, which Omarchy shows even with Do Not Disturb on. They then appear under \"notify-send\" rather than OmaForge."
        Toggle { on: !!(dlg.s && dlg.s.breakThroughDnd); onToggled: v => { dlg.s.breakThroughDnd = v; dlg.touch() } }
      }
      Section {
        title: "Snooze"
        Txt { text: "Snooze button waits"; color: Theme.faint; height: Theme.px(26) }
        Field {
          width: Theme.px(48)
          tabbable: true
          text: dlg.s ? String(dlg.s.snoozeMinutes) : "15"
          onCommitted: v => { var n = parseInt(v); if (!isNaN(n) && n > 0) { dlg.s.snoozeMinutes = n; dlg.touch() } }
        }
        Txt { text: "minutes"; color: Theme.faint; height: Theme.px(26) }
      }

      Rectangle { width: col.width; height: 1; color: Theme.divider }

      Row {
        spacing: 8
        Txt {
          height: Theme.px(26)
          text: dlg.service.active === "active" ? "● Background service running" : "○ Background service " + dlg.service.active
          color: dlg.service.active === "active" ? Theme.green : Theme.yellow
        }
        Btn { text: "Send a test"; quiet: true; onClicked: Backend.request("testNotify", {}, function (r) { if (r.ok) { dlg.service = r.result.service; dlg.dnd = r.result.dnd } }) }
      }
      Txt {
        visible: dlg.dnd === true
        width: col.width
        wrapMode: Text.Wrap; elide: Text.ElideNone
        color: Theme.yellow
        text: "⚠ Omarchy's Do Not Disturb is on: notifications go straight to the notification history" + (dlg.s && dlg.s.breakThroughDnd ? ", except reminders (set to break through)." : ". Turn it off, or switch on \"Break through Do Not Disturb\" above.")
      }
      Txt {
        width: col.width
        wrapMode: Text.Wrap; elide: Text.ElideNone
        font.pixelSize: Theme.fsSmall
        color: Theme.faint
        text: "Turn off notifications in TaskNotes' own settings in Obsidian, or reminders will arrive twice while Obsidian is open."
      }

      Row {
        spacing: 8
        Btn { text: "Save (Ctrl+Enter)"; active: true; onClicked: dlg.save() }
        Btn { text: "Cancel (Esc)"; onClicked: dlg.close() }
      }
    }
  }
}
