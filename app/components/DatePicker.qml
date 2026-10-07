import QtQuick
import ".."
import "../dates.js" as D

// Calendar + time chooser. open(anchor, value, done(valueOrEmpty), opts).
// Keys: arrows move a day/week, PgUp/PgDn a month, t today, n no time,
// digits jump to the time box, Enter picks, Delete clears, Esc cancels.
Item {
  id: pk
  anchors.fill: parent
  visible: false
  z: 160

  property var done: null
  property var anchorItem: null
  property int year: 2026
  property int month: 0          // 0-11
  property string sel: ""        // YYYY-MM-DD
  property string time: ""       // HH:MM or ""
  property var restoreFocus: null
  readonly property var prefs: Backend.prefs.dates || { defaultTime: "09:00", useDefaultTime: true }

  function pad(n) { return (n < 10 ? "0" : "") + n }
  function ymd(d) { return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate()) }
  function toDate(s) { var a = s.split("-"); return new Date(+a[0], +a[1] - 1, +a[2]) }

  function open(anchor, value, cb) {
    restoreFocus = pk.Window.activeFocusItem
    anchorItem = anchor
    done = cb
    var v = String(value || "")
    var now = new Date()
    sel = v ? v.slice(0, 10) : ymd(now)
    time = v.length > 10 ? v.slice(11, 16) : (v ? "" : (prefs.useDefaultTime ? prefs.defaultTime : ""))
    var d = toDate(sel)
    year = d.getFullYear(); month = d.getMonth()
    timeBox.input.text = ""
    visible = true
    box.forceActiveFocus()
  }
  function close() {
    visible = false
    if (restoreFocus) restoreFocus.forceActiveFocus()
  }
  function value() { return time ? sel + "T" + time : sel }
  function commit() { var cb = done, v = value(); close(); if (cb) cb(v) }
  function clear() { var cb = done; close(); if (cb) cb("") }
  function move(days) {
    var d = toDate(sel); d.setDate(d.getDate() + days)
    sel = ymd(d); year = d.getFullYear(); month = d.getMonth()
  }
  function moveMonth(n) {
    var d = toDate(sel)
    var last = new Date(d.getFullYear(), d.getMonth() + n + 1, 0).getDate()
    var nd = new Date(d.getFullYear(), d.getMonth() + n, Math.min(d.getDate(), last))
    sel = ymd(nd); year = nd.getFullYear(); month = nd.getMonth()
  }
  function showMonth(n) { var d = new Date(year, month + n, 1); year = d.getFullYear(); month = d.getMonth() }
  // 42 cells, weeks starting Monday
  readonly property var cells: {
    var first = new Date(year, month, 1)
    var lead = (first.getDay() + 6) % 7
    var out = []
    for (var i = 0; i < 42; i++) {
      var d = new Date(year, month, 1 - lead + i)
      out.push({ ymd: ymd(d), day: d.getDate(), inMonth: d.getMonth() === month, weekend: d.getDay() === 0 || d.getDay() === 6 })
    }
    return out
  }
  readonly property string today: ymd(new Date())
  readonly property var quickTimes: {
    var t = [prefs.defaultTime || "09:00", "12:00", "15:00", "18:00"]
    return t.filter(function (x, i) { return t.indexOf(x) === i })
  }

  MouseArea { anchors.fill: parent; onPressed: pk.close() }

  Rectangle {
    id: box
    // anchor: an Item (open below it) or a plain {x, y} in window coordinates
    property point at: !pk.anchorItem ? Qt.point(40, 40)
                       : pk.anchorItem.mapToItem ? pk.anchorItem.mapToItem(pk, 0, pk.anchorItem.height + 4)
                       : Qt.point(pk.anchorItem.x, pk.anchorItem.y)
    x: Math.max(4, Math.min(at.x, pk.width - width - 4))
    y: at.y + height + 4 > pk.height ? Math.max(4, at.y - height - (pk.anchorItem && pk.anchorItem.height ? pk.anchorItem.height : 0) - 8) : at.y
    width: Theme.px(300)
    height: col.implicitHeight + Theme.px(20)
    color: Theme.bg
    border.color: Theme.accent
    focus: true
    MouseArea { anchors.fill: parent }

    Keys.onPressed: e => {
      var k = e.key
      if (k === Qt.Key_Left) pk.move(-1)
      else if (k === Qt.Key_Right) pk.move(1)
      else if (k === Qt.Key_Up) pk.move(-7)
      else if (k === Qt.Key_Down) pk.move(7)
      else if (k === Qt.Key_PageUp) pk.moveMonth(-1)
      else if (k === Qt.Key_PageDown) pk.moveMonth(1)
      else if (k === Qt.Key_T) { pk.sel = pk.today; var d = pk.toDate(pk.today); pk.year = d.getFullYear(); pk.month = d.getMonth() }
      else if (k === Qt.Key_N) pk.time = ""
      else if (k === Qt.Key_Return || k === Qt.Key_Enter) pk.commit()
      else if (k === Qt.Key_Delete || k === Qt.Key_Backspace) pk.clear()
      else if (k === Qt.Key_Escape) pk.close()
      else if (e.text && /[0-9]/.test(e.text)) { timeBox.input.forceActiveFocus(); timeBox.input.text = e.text; return }
      else if (k === Qt.Key_Tab) { timeBox.input.forceActiveFocus() }
      else return
      e.accepted = true
    }

    Column {
      id: col
      x: Theme.px(10); y: Theme.px(10)
      width: parent.width - Theme.px(20)
      spacing: Theme.px(8)

      Item {
        width: parent.width
        height: Theme.px(24)
        Btn { anchors.left: parent.left; quiet: true; text: "‹"; tip: "PgUp"; onClicked: pk.showMonth(-1) }
        Txt {
          anchors.centerIn: parent
          font.bold: true
          text: ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"][pk.month] + " " + pk.year
        }
        Btn { anchors.right: parent.right; quiet: true; text: "›"; tip: "PgDn"; onClicked: pk.showMonth(1) }
      }

      Grid {
        columns: 7
        spacing: 2
        Repeater {
          model: ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]
          Txt { required property string modelData; width: (col.width - 12) / 7; horizontalAlignment: Text.AlignHCenter; text: modelData; color: Theme.faint; font.pixelSize: Theme.fsSmall }
        }
        Repeater {
          model: pk.cells
          Rectangle {
            required property var modelData
            width: (col.width - 12) / 7
            height: Theme.px(26)
            readonly property bool isSel: modelData.ymd === pk.sel
            color: isSel ? Theme.accent : cellMa.containsMouse ? Theme.hoverFill : "transparent"
            border.width: modelData.ymd === pk.today && !isSel ? 1 : 0
            border.color: Theme.accent
            Txt {
              anchors.centerIn: parent
              text: modelData.day
              color: parent.isSel ? Theme.bg : !modelData.inMonth ? Theme.a(Theme.fg, 0.3) : modelData.weekend ? Theme.faint : Theme.fg
              font.bold: parent.isSel
            }
            MouseArea {
              id: cellMa
              anchors.fill: parent
              hoverEnabled: true
              onClicked: { pk.sel = modelData.ymd; if (!modelData.inMonth) { var d = pk.toDate(modelData.ymd); pk.year = d.getFullYear(); pk.month = d.getMonth() } }
              onDoubleClicked: { pk.sel = modelData.ymd; pk.commit() }
            }
          }
        }
      }

      Flow {
        width: parent.width
        spacing: 4
        Repeater {
          model: pk.quickTimes
          Btn { required property string modelData; text: modelData; active: pk.time === modelData; onClicked: pk.time = modelData }
        }
        Btn { text: "no time"; tip: "n"; active: pk.time === ""; onClicked: pk.time = "" }
        Field {
          id: timeBox
          width: Theme.px(70)
          placeholder: "14:30"
          onCommitted: v => {
            var r = D.parse("today " + v, new Date(), {})
            if (r.time) { pk.time = r.time; input.text = ""; box.forceActiveFocus() }
            else Backend.notice("warn", "Times look like 14:30, 2pm or noon")
          }
          onEscaped: box.forceActiveFocus()
        }
      }

      Row {
        spacing: 6
        Txt { text: D.pretty(pk.value(), new Date()); font.bold: true; height: Theme.px(26) }
      }
      Row {
        spacing: 6
        Btn { text: "Set (Enter)"; active: true; onClicked: pk.commit() }
        Btn { text: "Clear"; tip: "Delete"; onClicked: pk.clear() }
        Btn { text: "Cancel"; tip: "Esc"; onClicked: pk.close() }
      }
    }
  }
}
