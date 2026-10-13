import QtQuick
import QtQuick.Controls
import ".."

// Grouped list, flattened into one ListView (header rows + task rows) so
// keyboard navigation and scrolling treat it as a single list.
FocusScope {
  id: tl
  property var groups: []
  property string emptyText: "Nothing here."   // or why the view can't be shown
  property string selectedPath: ""
  property bool compact: false
  signal select(string path)
  signal toggle(var task)
  signal open(var task)
  signal menu(var task, real x, real y)

  property var flat: {
    var out = []
    for (var g = 0; g < groups.length; g++) {
      var grp = groups[g]
      if (grp.label) out.push({ header: true, label: grp.label, count: grp.tasks.length, key: grp.key })
      for (var i = 0; i < grp.tasks.length; i++) out.push({ header: false, task: grp.tasks[i] })
    }
    return out
  }
  readonly property var taskRows: flat.filter(function (r) { return !r.header })

  function indexOfSelected() {
    for (var i = 0; i < taskRows.length; i++) if (taskRows[i].task.path === selectedPath) return i
    return -1
  }
  function step(delta) {
    if (!taskRows.length) return
    var i = indexOfSelected()
    i = i < 0 ? (delta > 0 ? 0 : taskRows.length - 1) : Math.max(0, Math.min(taskRows.length - 1, i + delta))
    select(taskRows[i].task.path)
    ensureVisible()
  }
  function ensureVisible() {
    for (var i = 0; i < flat.length; i++)
      if (!flat[i].header && flat[i].task.path === selectedPath) { view.positionViewAtIndex(i, ListView.Contain); return }
  }
  function selectedTask() { var i = indexOfSelected(); return i < 0 ? null : taskRows[i].task }

  ListView {
    id: view
    anchors.fill: parent
    clip: true
    model: tl.flat
    boundsBehavior: Flickable.StopAtBounds
    reuseItems: true
    ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
    delegate: Loader {
      id: ld
      required property var modelData
      required property int index
      width: view.width
      sourceComponent: modelData.header ? headerC : rowC
      Component {
        id: headerC
        Item {
          height: Theme.px(34)
          Txt {
            anchors { left: parent.left; leftMargin: Theme.px(12); bottom: parent.bottom; bottomMargin: Theme.px(6) }
            text: ld.modelData.label + "  " + ld.modelData.count
            font.bold: true
            color: ld.modelData.label === "Overdue" ? Theme.red : ld.modelData.label === "Today" ? Theme.accent : Theme.a(Theme.fg, 0.7)
          }
          Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.a(Theme.fg, 0.2) }
        }
      }
      Component {
        id: rowC
        TaskRow {
          task: ld.modelData.task
          compact: tl.compact
          selected: ld.modelData.task.path === tl.selectedPath
          onActivated: { tl.forceActiveFocus(); tl.select(task.path); tl.open(task) }
          onToggled: tl.toggle(task)
          onContextMenu: (x, y) => { tl.select(task.path); tl.menu(task, x, y) }
        }
      }
    }
  }

  Txt {
    anchors.centerIn: parent
    width: Math.min(implicitWidth, parent.width - Theme.px(48))
    visible: tl.flat.length === 0
    text: tl.emptyText
    wrapMode: Text.Wrap
    elide: Text.ElideNone
    horizontalAlignment: Text.AlignHCenter
    color: Theme.faint
  }
}
