import QtQuick
import ".."

// A right-click menu. open(x, y, items) with window coordinates; items:
//   { text, icon, hint, enabled (default true), danger, checked,
//     action: function () {...}, submenu: [items] }
//   { separator: true }     { header: "Section" }
// Keyboard: ↑/↓, Enter, → into a submenu, ←/Esc out. Click outside closes.
Item {
  id: menu
  anchors.fill: parent
  visible: false
  z: 150

  property var items: []
  property int current: -1
  property point at: Qt.point(0, 0)
  property var parentMenu: null     // set on submenus
  property var restoreFocus: null
  signal finished()

  function open(x, y, list) {
    restoreFocus = menu.Window.activeFocusItem
    items = list || []
    at = Qt.point(x, y)
    current = -1
    visible = true
    box.forceActiveFocus()
  }
  function close(all) {
    if (sub.visible) sub.close(false)
    visible = false
    if (all && parentMenu) parentMenu.close(true)
    else if (!parentMenu) {
      if (restoreFocus) restoreFocus.forceActiveFocus()
      finished()
    }
  }
  function selectable(i) { var it = items[i]; return !!it && !it.separator && !it.header && it.enabled !== false }
  function move(d) {
    var n = items.length
    for (var k = 1; k <= n; k++) {
      var i = ((current < 0 ? (d > 0 ? -1 : 0) : current) + d * k + n * 2) % n
      if (selectable(i)) { current = i; return }
    }
  }
  function activate(i) {
    var it = items[i]
    if (!selectable(i)) return
    if (it.submenu) { openSub(i); return }
    close(true)
    if (it.action) it.action()
  }
  function openSub(i) {
    var row = rows.itemAt(i)
    if (!row) return
    var p = row.mapToItem(menu, row.width - 2, -4)
    sub.open(p.x, p.y, items[i].submenu)
    sub.current = 0
    while (sub.current < sub.items.length && !sub.selectable(sub.current)) sub.current++
  }

  // Clicks outside close the whole menu (only the top-level menu owns this).
  MouseArea {
    anchors.fill: parent
    enabled: !menu.parentMenu
    acceptedButtons: Qt.LeftButton | Qt.RightButton
    onPressed: menu.close(false)
  }

  Rectangle {
    id: box
    x: Math.max(4, Math.min(menu.at.x, menu.width - width - 4))
    y: Math.max(4, Math.min(menu.at.y, menu.height - height - 4))
    width: Math.max(Theme.px(180), col.implicitWidth + Theme.px(8))
    height: col.implicitHeight + Theme.px(8)
    color: Theme.bg
    border.color: Theme.a(Theme.fg, 0.35)
    focus: true

    Keys.onPressed: e => {
      if (e.key === Qt.Key_Down || e.key === Qt.Key_J) menu.move(1)
      else if (e.key === Qt.Key_Up || e.key === Qt.Key_K) menu.move(-1)
      else if (e.key === Qt.Key_Return || e.key === Qt.Key_Enter || e.key === Qt.Key_Space) menu.activate(menu.current)
      else if (e.key === Qt.Key_Right || e.key === Qt.Key_L) { if (menu.items[menu.current] && menu.items[menu.current].submenu) menu.openSub(menu.current) }
      else if (e.key === Qt.Key_Left || e.key === Qt.Key_H) { if (menu.parentMenu) { menu.close(false); menu.parentMenu.focusBox() } }
      else if (e.key === Qt.Key_Escape) { if (menu.parentMenu) { menu.close(false); menu.parentMenu.focusBox() } else menu.close(false) }
      else return
      e.accepted = true
    }

    Column {
      id: col
      x: Theme.px(4); y: Theme.px(4)
      Repeater {
        id: rows
        model: menu.items
        delegate: Item {
          id: r
          required property var modelData
          required property int index
          readonly property bool sep: !!modelData.separator
          readonly property bool head: !!modelData.header
          readonly property bool on: modelData.enabled !== false
          width: Math.max(box.width - Theme.px(8), line.implicitWidth + Theme.px(20))
          implicitWidth: line.implicitWidth + Theme.px(20)
          height: sep ? Theme.px(9) : head ? Theme.px(22) : Theme.px(26)

          Rectangle { visible: r.sep; anchors.verticalCenter: parent.verticalCenter; width: parent.width; height: 1; color: Theme.divider }
          Txt {
            visible: r.head
            anchors { left: parent.left; leftMargin: Theme.px(8); bottom: parent.bottom; bottomMargin: 3 }
            text: r.head ? String(r.modelData.header).toUpperCase() : ""
            font.pixelSize: Theme.fsSmall; font.letterSpacing: 1
            color: Theme.a(Theme.fg, 0.45)
          }
          Rectangle {
            visible: !r.sep && !r.head
            anchors.fill: parent
            color: menu.current === r.index && r.on ? Theme.selectedFill : "transparent"
            Row {
              id: line
              anchors { left: parent.left; leftMargin: Theme.px(8); verticalCenter: parent.verticalCenter }
              spacing: Theme.px(8)
              Txt {
                width: Theme.px(16)
                horizontalAlignment: Text.AlignHCenter
                text: r.modelData.checked ? "✓" : (r.modelData.icon || "")
                color: r.modelData.danger ? Theme.red : r.on ? Theme.faint : Theme.a(Theme.fg, 0.25)
              }
              Txt {
                text: r.modelData.text || ""
                color: !r.on ? Theme.a(Theme.fg, 0.3) : r.modelData.danger ? Theme.red : menu.current === r.index ? Theme.accent : Theme.fg
              }
              Txt {
                visible: !!r.modelData.hint
                text: r.modelData.hint || ""
                color: Theme.a(Theme.fg, 0.35)
                font.pixelSize: Theme.fsSmall
              }
              Item { width: Theme.px(10); height: 1; visible: !!r.modelData.submenu }
            }
            Txt {
              visible: !!r.modelData.submenu
              anchors { right: parent.right; rightMargin: Theme.px(8); verticalCenter: parent.verticalCenter }
              text: "›"
              color: Theme.faint
            }
            MouseArea {
              anchors.fill: parent
              hoverEnabled: true
              acceptedButtons: Qt.LeftButton | Qt.RightButton
              onEntered: {
                if (!r.on) return
                menu.current = r.index
                if (r.modelData.submenu) menu.openSub(r.index)
                else if (sub.visible) sub.close(false)
              }
              onClicked: menu.activate(r.index)
            }
          }
        }
      }
    }
  }

  function focusBox() { box.forceActiveFocus() }

  // One level of submenus: the submenu is this same component, created with
  // parentMenu already set (so it doesn't create a submenu of its own).
  Loader {
    id: subLoader
    anchors.fill: parent
    Component.onCompleted: if (!menu.parentMenu) setSource("ContextMenu.qml", { parentMenu: menu })
  }
  readonly property var sub: subLoader.item ? subLoader.item
    : ({ visible: false, open: function () {}, close: function () {}, items: [], current: 0, selectable: function () { return false } })
}
