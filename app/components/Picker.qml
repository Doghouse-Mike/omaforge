import QtQuick
import ".."

// Searchable list chooser. open(at, title, options, done, opts)
//   at: an Item (opens below it) or {x, y}
//   options: [{ label, sub, value }]
//   opts.free: also offer "Use “<typed text>”" when nothing matches exactly
// Type to filter, ↑/↓ to move, Enter to choose, Esc to cancel.
Item {
  id: pk
  anchors.fill: parent
  visible: false
  z: 165

  property string title: ""
  property var options: []
  property var done: null
  property bool free: false
  property var at: null
  property int current: 0
  property var restoreFocus: null

  readonly property var shown: {
    var q = search.text.trim().toLowerCase()
    var words = q.split(/\s+/).filter(function (w) { return w })
    var out = options.filter(function (o) {
      var hay = (o.label + " " + (o.sub || "")).toLowerCase()
      return words.every(function (w) { return hay.indexOf(w) >= 0 })
    })
    if (free && q && !options.some(function (o) { return o.label.toLowerCase() === q }))
      out = out.concat([{ label: "Use “" + search.text.trim() + "”", value: search.text.trim(), freeText: true }])
    return out.slice(0, 200)
  }

  function open(anchor, t, opts, cb, extra) {
    restoreFocus = pk.Window.activeFocusItem
    at = anchor; title = t; options = opts || []; done = cb
    free = !!(extra && extra.free)
    search.text = ""
    current = 0
    visible = true
    search.forceActiveFocus()
  }
  function close() { visible = false; if (restoreFocus) restoreFocus.forceActiveFocus() }
  function choose(i) {
    var o = shown[i]
    if (!o) return
    var cb = done
    close()
    if (cb) cb(o.value, o)
  }

  MouseArea { anchors.fill: parent; onPressed: pk.close() }

  Rectangle {
    id: box
    property point p: !pk.at ? Qt.point(60, 60)
                      : pk.at.mapToItem ? pk.at.mapToItem(pk, 0, pk.at.height + 4) : Qt.point(pk.at.x, pk.at.y)
    x: Math.max(4, Math.min(p.x, pk.width - width - 4))
    y: Math.max(4, Math.min(p.y, pk.height - height - 4))
    width: Theme.px(360)
    height: Math.min(col.implicitHeight + Theme.px(16), pk.height - 8)
    color: Theme.bg
    border.color: Theme.accent
    MouseArea { anchors.fill: parent }

    Column {
      id: col
      x: Theme.px(8); y: Theme.px(8)
      width: parent.width - Theme.px(16)
      spacing: Theme.px(6)
      Txt { text: pk.title; font.bold: true; visible: pk.title !== "" }
      Rectangle {
        width: parent.width
        height: Theme.px(28)
        color: Theme.hoverFill
        border.color: Theme.accent
        TextInput {
          id: search
          anchors { fill: parent; leftMargin: 8; rightMargin: 8 }
          verticalAlignment: TextInput.AlignVCenter
          color: Theme.fg
          font.family: Theme.font
          font.pixelSize: Theme.fs
          clip: true
          onTextChanged: pk.current = 0
          Keys.onPressed: e => {
            if (e.key === Qt.Key_Down) pk.current = Math.min(pk.shown.length - 1, pk.current + 1)
            else if (e.key === Qt.Key_Up) pk.current = Math.max(0, pk.current - 1)
            else if (e.key === Qt.Key_Return || e.key === Qt.Key_Enter) pk.choose(pk.current)
            else if (e.key === Qt.Key_Escape) pk.close()
            else if (e.key === Qt.Key_Tab) {}
            else return
            e.accepted = true
          }
        }
        Txt {
          anchors { left: parent.left; leftMargin: 8; verticalCenter: parent.verticalCenter }
          visible: search.text === ""
          text: "type to filter…"
          color: Theme.a(Theme.fg, 0.35)
        }
      }
      ListView {
        id: lv
        width: parent.width
        height: Math.min(contentHeight, Theme.px(320))
        clip: true
        model: pk.shown
        currentIndex: pk.current
        onCurrentIndexChanged: positionViewAtIndex(currentIndex, ListView.Contain)
        delegate: Rectangle {
          required property var modelData
          required property int index
          width: lv.width
          height: Theme.px(modelData.sub ? 40 : 28)
          color: index === pk.current ? Theme.selectedFill : rowMa.containsMouse ? Theme.hoverFill : "transparent"
          Column {
            anchors { left: parent.left; right: parent.right; leftMargin: 8; rightMargin: 8; verticalCenter: parent.verticalCenter }
            Txt { width: parent.width; text: modelData.label; color: index === pk.current ? Theme.accent : modelData.freeText ? Theme.faint : Theme.fg }
            Txt { visible: !!modelData.sub; width: parent.width; text: modelData.sub || ""; color: Theme.faint; font.pixelSize: Theme.fsSmall }
          }
          MouseArea { id: rowMa; anchors.fill: parent; hoverEnabled: true; onClicked: pk.choose(index) }
        }
      }
      Txt { visible: pk.shown.length === 0; text: "Nothing matches"; color: Theme.faint }
    }
  }
}
