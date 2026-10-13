import QtQuick
import QtQuick.Controls
import ".."
import "../views.js" as V

// Kanban: one column per TaskNotes status (in its configured order).
// Dropping a card on a column sets that status.
// Or, for an Obsidian Tasks "view columns by X" query, the columns the query
// gives (givenColumns), with any further groups as headings inside them; a
// drop then copies the column's value of X, where Tasks allows that.
FocusScope {
  id: board
  property var tasks: []          // already filtered + sorted
  property string selectedPath: ""
  property var givenColumns: null    // [{name, label, sections: [{label, tasks}], sample}]
  property string columnsBy: ""      // the field they're grouped by
  signal select(string path)
  signal setField(var task, string field, var value)
  signal toggle(var task)
  signal setStatus(var task, string status)
  signal menu(var task, real x, real y)

  // Tasks only edits by drop for these (CreateEditingInstructionForGroup.ts).
  readonly property var dropFields: ({ priority: "priority", due: "due", scheduled: "scheduled", start: "start",
                                       created: "created", done: "doneDate", cancelled: "cancelledDate" })
  // What a drop on this column sets: {field, value}, or null if it can't
  // take drops (unsupported field, or an invalid date to copy).
  function dropFor(col) {
    var f = dropFields[columnsBy]
    if (!f || !col.sample) return null
    var v = col.sample[f] || ""
    if (f !== "priority" && v && !/^\d{4}-\d{2}-\d{2}/.test(v)) return null
    return { field: f, value: f === "priority" ? (v || "none") : String(v).slice(0, 10) }
  }

  // A card dropped on a column (also the test hook's way in).
  function dropTask(t, col) {
    if (!t || !col) return false
    if (givenColumns) {
      var d = col.drop
      if (!d) return false
      var cur = d.field === "priority" ? (t.priority || "none") : String(t[d.field] || "").slice(0, 10)
      if (cur !== d.value) setField(t, d.field, d.value)
      return true
    }
    if (!col.status.value || t.status === col.status.value) return false
    setStatus(t, col.status.value)
    return true
  }

  readonly property var columns: {
    if (givenColumns) {
      return givenColumns.map(function (c) {
        var rows = [], flat = []
        c.sections.forEach(function (sec) {
          if (sec.label) rows.push({ header: sec.label })
          sec.tasks.forEach(function (t) { rows.push({ task: t }); flat.push(t) })
        })
        return { status: { value: "", label: c.label, color: "" }, tasks: flat, rows: rows, drop: board.dropFor(c) }
      })
    }
    var ss = Backend.settings.statuses || []
    var cols = []
    for (var i = 0; i < ss.length; i++) {
      var items = board.tasks.filter(function (t) { return t.status === ss[i].value })
      // Completed statuses only get a column if something is in them, so a
      // board of open work isn't padded with empty Done/Archived lanes.
      if (ss[i].isCompleted && !items.length) continue
      cols.push({ status: ss[i], tasks: items, rows: items.map(function (t) { return { task: t } }) })
    }
    var known = ss.map(function (s) { return s.value })
    var other = board.tasks.filter(function (t) { return known.indexOf(t.status) < 0 })
    if (other.length) cols.push({ status: { value: "", label: "Other", color: "" }, tasks: other, rows: other.map(function (t) { return { task: t } }) })
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
          readonly property bool canDrop: board.givenColumns ? !!lane.modelData.drop : !!lane.modelData.status.value
          color: drop.containsDrag && canDrop ? Theme.hoverFill : Theme.a(Theme.fg, 0.025)
          border.width: drop.containsDrag && canDrop ? 1 : 0
          border.color: Theme.accent
          readonly property color tint: Theme.tint(lane.modelData.status.color)

          Row {
            id: laneHead
            x: Theme.px(10); y: Theme.px(8)
            spacing: Theme.px(8)
            Rectangle { visible: !board.givenColumns; width: Theme.px(8); height: width; radius: width / 2; color: lane.tint; anchors.verticalCenter: parent.verticalCenter }
            Txt { text: lane.modelData.status.label || lane.modelData.status.value; font.bold: true }
            Txt { text: lane.modelData.tasks.length; color: Theme.faint }
          }
          ListView {
            id: cards
            anchors { top: laneHead.bottom; topMargin: Theme.px(8); left: parent.left; right: parent.right; bottom: parent.bottom; margins: Theme.px(6) }
            clip: true
            spacing: Theme.px(6)
            model: lane.modelData.rows
            delegate: Item {
              id: row
              required property var modelData
              width: cards.width
              height: modelData.header ? head.implicitHeight + Theme.px(6) : card.height
              Txt {
                id: head
                visible: !!row.modelData.header
                y: Theme.px(4)
                text: row.modelData.header || ""
                color: Theme.faint
                font.pixelSize: Theme.fsSmall
                font.bold: true
              }
            Rectangle {
              id: card
              visible: !!row.modelData.task
              readonly property var modelData: row.modelData.task || ({})
              width: cards.width
              height: visible ? inner.implicitHeight : 0
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
                  card.x = 0; card.y = 0  // snap back; the list rebuilds on the change
                  cards.forceLayout()
                }
              }
            }
            }
          }
          DropArea {
            id: drop
            anchors.fill: parent
            keys: ["omaforge-task"]
            onDropped: drag => board.dropTask(drag.source.task, lane.modelData)
          }
        }
      }
    }
  }
}
