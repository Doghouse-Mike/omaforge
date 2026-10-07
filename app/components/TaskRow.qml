import QtQuick
import ".."
import "../views.js" as V

Rectangle {
  id: row
  property var task
  property bool selected: false
  property bool compact: false
  signal activated()
  signal toggled()
  signal contextMenu(real x, real y)

  readonly property string today: Backend.today
  readonly property string when: V.nextDate(task)
  readonly property bool overdue: !task.done && when !== "" && when < today
  readonly property color prioColor: Theme.tint(V.priorityColor(task.priority, Backend.settings))
  readonly property color statusColor: Theme.tint(V.statusColor(task.status, Backend.settings))

  implicitHeight: compact ? Theme.px(30) : Theme.px(44)
  color: selected ? Theme.selectedFill : ma.containsMouse ? Theme.hoverFill : "transparent"

  Rectangle { visible: row.selected; width: 2; height: parent.height; color: Theme.accent }

  // Completion box: ring in the priority colour; filled when done.
  Rectangle {
    id: box
    anchors { left: parent.left; leftMargin: Theme.px(12); verticalCenter: parent.verticalCenter }
    width: Theme.px(15); height: width; radius: width / 2
    color: row.task.done ? Theme.a(row.statusColor, 0.8) : boxMa.containsMouse ? Theme.a(row.prioColor, 0.25) : "transparent"
    border.width: 1.5
    border.color: row.task.done ? row.statusColor : row.prioColor
    Txt {
      anchors.centerIn: parent
      visible: row.task.done || boxMa.containsMouse
      text: "✓"
      font.pixelSize: Theme.fsSmall
      color: row.task.done ? Theme.bg : row.prioColor
    }
    MouseArea {
      id: boxMa
      anchors.fill: parent
      anchors.margins: -6
      hoverEnabled: true
      cursorShape: Qt.PointingHandCursor
      onClicked: row.toggled()
    }
  }

  Column {
    anchors { left: box.right; leftMargin: Theme.px(10); right: dateCol.left; rightMargin: Theme.px(8); verticalCenter: parent.verticalCenter }
    spacing: Theme.px(3)
    Txt {
      width: parent.width
      text: row.task.title
      font.strikeout: row.task.done
      color: row.task.done ? Theme.faint : Theme.fg
    }
    Row {
      visible: !row.compact && meta.count > 0
      width: parent.width
      clip: true
      spacing: Theme.px(8)
      Repeater {
        id: meta
        model: {
          var m = []
          var t = row.task
          if (t.status && !t.done && t.status !== Backend.settings.defaultStatus)
            m.push({ t: V.statusLabel(t.status, Backend.settings), c: row.statusColor })
          if (t.recurring) m.push({ t: "↻ " + (t.recurrenceText || "repeats"), c: Theme.faint })
          if (t.blocked) m.push({ t: "⛔ blocked", c: Theme.red })
          for (var n = 0; n < (t.notes || []).length; n++) m.push({ t: "󰈙 " + t.notes[n], c: Theme.blue })
          for (var i = 0; i < (t.projects || []).length; i++) m.push({ t: "󰉋 " + t.projects[i], c: Theme.blue })
          for (var j = 0; j < (t.contexts || []).length; j++) m.push({ t: "@" + t.contexts[j], c: Theme.green })
          for (var k = 0; k < (t.tags || []).length; k++) m.push({ t: "#" + t.tags[k], c: Theme.faint })
          return m
        }
        Txt { required property var modelData; text: modelData.t; color: modelData.c; font.pixelSize: Theme.fsSmall }
      }
    }
  }

  Column {
    id: dateCol
    anchors { right: parent.right; rightMargin: Theme.px(12); verticalCenter: parent.verticalCenter }
    Txt {
      anchors.right: parent.right
      text: row.task.done && row.task.completedDate ? "✓ " + V.prettyDate(row.task.completedDate, row.today)
            : row.when ? (row.task.due && V.d10(row.task.due) === row.when ? "󰥔 " : "") + V.prettyDate(row.task.due && V.d10(row.task.due) === row.when ? row.task.due : (row.task.occurrence || row.task.scheduled), row.today) : ""
      color: row.overdue ? Theme.red : row.when === row.today ? Theme.accent : Theme.faint
      font.pixelSize: Theme.fsSmall
    }
  }

  MouseArea {
    id: ma
    anchors.fill: parent
    z: -1
    hoverEnabled: true
    acceptedButtons: Qt.LeftButton | Qt.RightButton
    onClicked: mouse => {
      if (mouse.button === Qt.RightButton) { var p = mapToItem(null, mouse.x, mouse.y); row.contextMenu(p.x, p.y) }
      else row.activated()
    }
  }

  Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.divider }
}
