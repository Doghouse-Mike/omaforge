import QtQuick
import ".."

// Single-line input. Commits on Enter/blur (not every keystroke): each
// commit is a file write, and Obsidian may be watching that file.
Rectangle {
  id: f
  property alias text: input.text
  property string placeholder: ""
  property alias input: input
  property bool mono: true
  // Part of the editor's Tab order (title → dates → lists → notes).
  property bool tabbable: false
  // ctx: whatever the field is editing (the task). Snapshotted at focus so a
  // commit-on-blur after the selection moved still writes to the right task.
  property var ctx: null
  property var _ctx: null
  signal committed(string value, var target)
  signal escaped()
  implicitHeight: Theme.px(28)
  color: input.activeFocus ? Theme.hoverFill : Theme.normalFill
  border.width: 1
  border.color: input.activeFocus ? Theme.accent : Theme.a(Theme.fg, 0.18)
  property string _initial: ""
  TextInput {
    id: input
    anchors.fill: parent
    anchors.leftMargin: Theme.px(8)
    anchors.rightMargin: Theme.px(8)
    verticalAlignment: TextInput.AlignVCenter
    color: Theme.fg
    selectionColor: Theme.a(Theme.accent, 0.4)
    selectedTextColor: Theme.fg
    font.family: Theme.font
    font.pixelSize: Theme.fs
    clip: true
    // Unfocused, show the start of long text rather than wherever the
    // cursor last was.
    autoScroll: activeFocus
    onTextChanged: if (!activeFocus) cursorPosition = 0
    activeFocusOnTab: f.tabbable
    onActiveFocusChanged: {
      if (!activeFocus) cursorPosition = 0
      if (activeFocus) { f._initial = text; f._ctx = f.ctx }
      else if (text !== f._initial) { f._initial = text; f.committed(text, f._ctx) }
    }
    Keys.onReturnPressed: { if (text !== f._initial) { f._initial = text; f.committed(text, f._ctx) } }
    Keys.onEnterPressed: { if (text !== f._initial) { f._initial = text; f.committed(text, f._ctx) } }
    Keys.onEscapePressed: { text = f._initial; f.escaped() }
    // Explicit, so Tab never falls through to the window's own key handling.
    Keys.onTabPressed: { var n = nextItemInFocusChain(true); if (n) n.forceActiveFocus() }
    Keys.onBacktabPressed: { var n = nextItemInFocusChain(false); if (n) n.forceActiveFocus() }
  }
  Txt {
    anchors.fill: input
    visible: input.text === "" && !input.activeFocus
    text: f.placeholder
    color: Theme.a(Theme.fg, 0.35)
  }
}
