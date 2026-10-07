import QtQuick
import QtQuick.Controls
import ".."
import "../views.js" as V

// Kanban: one column per TaskNotes status (in its configured order).
// Dropping a card on a column sets that status.
FocusScope {
  id: board
  property var tasks: []          // already filtered + sorted
  property string selectedPath: ""
  signal select(string path)
  signal toggle(var task)
  signal setStatus(var task, string status)
  signal menu(var task, real x, real y)

  readonly property var columns: {
    var ss = Backend.settings.statuses || []
    var cols = []
    for (var i = 0; i < ss.length; i++) {
      var items = board.tasks.filter(function (t) { return t.status === ss[i].value })
      // Completed statuses only get a column if something is in them, so a
      // board of open work isn't padded with empty Done/Archived lanes.
      if (ss[i].isCompleted && !items.length) continue
      cols.push({ status: ss[i], tasks: items })
    }
    var known = ss.map(function (s) { return s.value })
    var other = board.tasks.filter(function (t) { return known.indexOf(t.status) < 0 })
    if (other.length) cols.push({ status: { value: "", label: "Other", color: "" }, tasks: other })
    return cols
  }

  function step(dx, dy) {
    var ci = -1, ri = -1
    for (var c = 0; c < columns.length; c++)
      for (var r = 0; r < columns[c].tasks.length; r++)
        if (columns[c].tasks[r].path === selectedPath) { ci = c; ri = r }
    if (ci < 0) { if (columns.length && columns[0].tasks.length) select(columns[0].tasks[0].path); return }
    if (dx) {
      var nc = ci + dx
      while (nc >= 0 && nc < columns.length && !columns[nc].tasks.length) nc += dx
      if (nc < 0 || nc >= columns.length) return
      select(columns[nc].tasks[Math.min(ri, columns[nc].tasks.length - 1)].path)
    } else {
      var col = columns[ci].tasks
      select(col[Math.max(0, Math.min(col.length - 1, ri + dy))].path)
    }
  }

  ScrollView {
    anchors.fill: parent
    contentWidth: lanes.implicitWidth
    ScrollBar.vertical.policy: ScrollBar.AlwaysOff
    Row {
      id: lanes
      height: board.height
      spacing: Theme.px(10)
      padding: Theme.px(10)
      Repeater {
        model: board.columns
        delegate: Rectangle {
          id: lane
          required property var modelData
          width: Theme.px(280)
          height: lanes.height - Theme.px(20)
          color: drop.containsDrag ? Theme.hoverFill : Theme.a(Theme.fg, 0.025)
          border.width: drop.containsDrag ? 1 : 0
          border.color: Theme.accent
          readonly property color tint: Theme.tint(lane.modelData.status.color)

          Row {
            id: laneHead
            x: Theme.px(10); y: Theme.px(8)
            spacing: Theme.px(8)
            Rectangle { width: Theme.px(8); height: width; radius: width / 2; color: lane.tint; anchors.verticalCenter: parent.verticalCenter }
            Txt { text: lane.modelData.status.label || lane.modelData.status.value; font.bold: true }
            Txt { text: lane.modelData.tasks.length; color: Theme.faint }
          }
          ListView {
            id: cards
            anchors { top: laneHead.bottom; topMargin: Theme.px(8); left: parent.left; right: parent.right; bottom: parent.bottom; margins: Theme.px(6) }
            clip: true
            spacing: Theme.px(6)
            model: lane.modelData.tasks
            delegate: Rectangle {
              id: card
              required property var modelData
              width: cards.width
              height: inner.implicitHeight
              color: Theme.bg
              border.width: 1
              border.color: modelData.path === board.selectedPath ? Theme.accent : Theme.a(Theme.fg, 0.14)
              Drag.active: dragMa.drag.active
              Drag.keys: ["omaforge-task"]
              Drag.source: card
              Drag.hotSpot.x: width / 2
              Drag.hotSpot.y: height / 2
              property var task: modelData
              TaskRow {
                id: inner
                width: parent.width
                task: card.modelData
                selected: false
                color: "transparent"
                onActivated: { board.forceActiveFocus(); board.select(task.path) }
                onToggled: board.toggle(task)
                onContextMenu: (x, y) => { board.select(task.path); board.menu(task, x, y) }
              }
              MouseArea {
                id: dragMa
                anchors.fill: parent
                anchors.leftMargin: Theme.px(32)  // leave the checkbox clickable
                drag.target: pressedButtons & Qt.LeftButton ? card : null
                drag.threshold: 8
                propagateComposedEvents: true
                acceptedButtons: Qt.LeftButton | Qt.RightButton
                onClicked: mouse => {
                  board.forceActiveFocus(); board.select(card.modelData.path)
                  if (mouse.button === Qt.RightButton) { var p = mapToItem(null, mouse.x, mouse.y); board.menu(card.modelData, p.x, p.y) }
                }
                onReleased: {
                  if (drag.active || card.Drag.active) card.Drag.drop()
                  card.x = 0; card.y = card.y  // snap back; the list rebuilds on the status change
                  cards.forceLayout()
                }
              }
            }
          }
          DropArea {
            id: drop
            anchors.fill: parent
            keys: ["omaforge-task"]
            onDropped: drag => {
              var t = drag.source.task
              if (t && lane.modelData.status.value && t.status !== lane.modelData.status.value)
                board.setStatus(t, lane.modelData.status.value)
            }
          }
        }
      }
    }
  }
}
