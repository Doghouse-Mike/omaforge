import QtQuick
import ".."

// A small label for status/priority/context/project/tag.
Rectangle {
  id: c
  property string text: ""
  property color tint: Theme.faint
  property bool filled: false
  signal clicked()
  implicitWidth: label.implicitWidth + Theme.px(10)
  implicitHeight: Theme.px(18)
  color: filled ? Theme.a(tint, 0.18) : "transparent"
  border.width: 1
  border.color: Theme.a(tint, 0.45)
  Txt {
    id: label
    anchors.centerIn: parent
    text: c.text
    color: c.tint
    font.pixelSize: Theme.fsSmall
  }
  MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: c.clicked() }
}
