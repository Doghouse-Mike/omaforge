import QtQuick
import QtQuick.Controls
import ".."
import "../views.js" as V

Rectangle {
  id: side
  property string current: "today"
  property bool focused: false        // has the keyboard (Ctrl+Tab): j/k change list
  signal picked(string viewId)
  signal newView()
  signal openSettings()
  signal contextMenu(var entry, real x, real y)   // window coordinates
  color: Theme.a(Theme.fg, 0.025)
  Rectangle {
    anchors.fill: parent
    z: 50
    color: "transparent"
    border.width: side.focused ? 2 : 0
    border.color: Theme.accent
  }

  // Rebuilt on every vault change; cheap at a few hundred tasks.
  property var model: {
    Backend.revision
    var tasks = Backend.tasks, s = Backend.settings, today = Backend.today
    var out = []
    var smart = V.smartLists()
    for (var i = 0; i < smart.length; i++) {
      var r = V.compute(smart[i].id, tasks, s, today, {})
      out.push({ kind: "item", id: smart[i].id, label: smart[i].label, icon: smart[i].icon, count: smart[i].id === "done" || smart[i].id === "archived" ? -1 : r.count,
                 alert: smart[i].id === "today" && overdue(tasks, today) })
    }
    var problems = 0
    for (var p in tasks) if (tasks[p].error) problems++
    if (problems) out.push({ kind: "item", id: "problems", label: "Problems", icon: "", count: problems, alert: true })
    function section(title, key, prefix, icon) {
      var facets = V.facetCounts(tasks, key)
      if (!facets.length) return
      out.push({ kind: "header", label: title })
      for (var j = 0; j < facets.length; j++)
        out.push({ kind: "item", id: prefix + ":" + facets[j].name, label: facets[j].name, icon: icon, count: facets[j].count })
    }
    // Views: Bases (.base) views, grouped by file, then TaskNotes' legacy
    // saved views. Counts only for views that evaluate.
    if (Backend.mode !== "tasks") out.push({ kind: "header", label: "Views", add: true })
    var bvs = Backend.views || [], lastFile = ""
    for (var b = 0; b < bvs.length; b++) {
      var bv = bvs[b]
      if (bv.fileName !== lastFile) {
        lastFile = bv.fileName
        var many = bvs.filter(function (x) { return x.fileName === bv.fileName }).length > 1
        if (many) out.push({ kind: "subheader", label: bv.fileName })
      }
      // Badge = what's still to do; the view itself still shows everything it matches.
      var c = bv.unsupported ? -1 : openCount(V.compute(bv.id, tasks, s, today, { baseViews: bvs }))
      out.push({ kind: "item", id: bv.id, label: bv.name, icon: bv.layout === "board" ? "󰕰" : bv.layout === "dates" ? "󰃭" : "󰈲",
                 count: c, dim: !!bv.unsupported, tip: bv.unsupported, mine: !!bv.model })
    }
    var views = Backend.mode === "tasks" ? [] : (s.savedViews || [])
    if (views.length) {
      out.push({ kind: "subheader", label: "TaskNotes saved views" })
      for (var k = 0; k < views.length; k++) out.push({ kind: "item", id: "saved:" + views[k].id, label: views[k].name, icon: "󰈲", count: -1 })
    }
    section("Notes", "notes", "note", "󰈙")
    section("Projects", "projects", "project", "󰉋")
    section("Contexts", "contexts", "context", "@")
    section("Tags", "tags", "tag", "#")
    return out
  }

  function openCount(result) {
    var n = 0
    for (var g = 0; g < result.groups.length; g++)
      for (var i = 0; i < result.groups[g].tasks.length; i++) if (V.isOpen(result.groups[g].tasks[i])) n++
    return n
  }

  function overdue(tasks, today) {
    for (var p in tasks) { var t = tasks[p]; var d = V.nextDate(t); if (V.isOpen(t) && d && d < today) return true }
    return false
  }

  // Keyboard: the main window moves through items with these.
  function step(delta) {
    var items = model.filter(function (m) { return m.kind === "item" })
    var idx = items.findIndex(function (m) { return m.id === current })
    var n = Math.max(0, Math.min(items.length - 1, idx + delta))
    if (items[n]) {
      picked(items[n].id)
      list.positionViewAtIndex(model.indexOf(items[n]), ListView.Contain)   // keep it on screen
    }
  }

  Column {
    id: head
    anchors { left: parent.left; right: parent.right; top: parent.top; margins: Theme.pad }
    spacing: 2
    Item {
      width: parent.width
      height: titleTxt.implicitHeight
      Txt { id: titleTxt; text: "OmaForge"; font.pixelSize: Theme.fsLarge; font.bold: true; color: Theme.accent }
      Btn {
        anchors { right: parent.right; verticalCenter: parent.verticalCenter }
        quiet: true; icon: "󰒓"; tip: "Settings"
        implicitHeight: Theme.px(22)
        onClicked: side.openSettings()
      }
    }
    Txt {
      width: parent.width
      text: Backend.vaultName
      color: Theme.faint
      font.pixelSize: Theme.fsSmall
    }
  }

  ListView {
    id: list
    anchors { left: parent.left; right: parent.right; top: head.bottom; bottom: parent.bottom; topMargin: Theme.pad }
    clip: true
    model: side.model
    boundsBehavior: Flickable.StopAtBounds
    ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
    delegate: Item {
      id: row
      required property var modelData
      width: list.width
      height: modelData.kind === "header" ? Theme.px(30) : modelData.kind === "subheader" ? Theme.px(22) : Theme.px(26)
      readonly property bool sel: modelData.id === side.current
      Txt {
        visible: row.modelData.kind === "header"
        anchors { left: parent.left; leftMargin: Theme.pad; bottom: parent.bottom; bottomMargin: 4 }
        text: row.modelData.label.toUpperCase()
        color: Theme.a(Theme.fg, 0.45)
        font.pixelSize: Theme.fsSmall
        font.letterSpacing: 1
      }
      Btn {
        visible: !!row.modelData.add
        anchors { right: parent.right; rightMargin: Theme.px(8); bottom: parent.bottom; bottomMargin: 1 }
        implicitHeight: Theme.px(20)
        quiet: true
        text: "+ new"
        tip: "New view"
        onClicked: side.newView()
      }
      Txt {
        visible: row.modelData.kind === "subheader"
        anchors { left: parent.left; leftMargin: Theme.px(14); bottom: parent.bottom; bottomMargin: 3 }
        text: row.modelData.label
        color: Theme.a(Theme.fg, 0.38)
        font.pixelSize: Theme.fsSmall
      }
      Rectangle {
        visible: row.modelData.kind === "item"
        anchors.fill: parent
        anchors.leftMargin: 4
        anchors.rightMargin: 4
        color: row.sel ? Theme.selectedFill : ma.containsMouse ? Theme.hoverFill : "transparent"
        Rectangle { visible: row.sel; width: 2; height: parent.height; color: Theme.accent }
        Txt {
          id: ic
          anchors { left: parent.left; leftMargin: Theme.px(10); verticalCenter: parent.verticalCenter }
          width: Theme.px(16)
          text: row.modelData.icon || ""
          color: row.sel ? Theme.accent : Theme.faint
          horizontalAlignment: Text.AlignHCenter
        }
        Txt {
          anchors { left: ic.right; leftMargin: Theme.px(8); right: cnt.left; rightMargin: 6; verticalCenter: parent.verticalCenter }
          text: row.modelData.label || ""
          color: row.sel ? Theme.accent : row.modelData.dim ? Theme.a(Theme.fg, 0.35) : Theme.fg
        }
        Txt {
          id: cnt
          anchors { right: parent.right; rightMargin: Theme.px(10); verticalCenter: parent.verticalCenter }
          text: row.modelData.count > 0 ? row.modelData.count : ""
          color: row.modelData.alert ? Theme.red : Theme.faint
          font.pixelSize: Theme.fsSmall
        }
        MouseArea {
          id: ma
          anchors.fill: parent
          hoverEnabled: true
          cursorShape: Qt.PointingHandCursor
          acceptedButtons: Qt.LeftButton | Qt.RightButton
          onClicked: mouse => {
            if (mouse.button === Qt.RightButton) {
              var p = mapToItem(null, mouse.x, mouse.y)
              side.contextMenu(row.modelData, p.x, p.y)
            } else side.picked(row.modelData.id)
          }
        }
        Tip { text: row.modelData.tip || ""; show: ma.containsMouse && !!row.modelData.tip }
      }
    }
  }
}
