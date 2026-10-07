import QtQuick
import ".."
import "../dates.js" as D

// A date/time box: shows the value readably, takes natural language
// ("fri 3pm", "+10m", "January 1st 2027"), previews what it understood as
// you type, and opens the calendar with ↓ or the button.
Column {
  id: df
  property string value: ""          // TaskNotes form: YYYY-MM-DD[THH:mm]
  property var ctx: null
  property string placeholder: dateOnly ? "fri, +3d, 1 jan…" : "fri 3pm, +1h, 1 jan…"
  property alias input: field.input
  property bool tabbable: true
  property bool dateOnly: false    // strip times (e.g. Obsidian Tasks dates)
  signal picked(string value, var target)   // "" = clear
  signal escaped()
  spacing: 2

  readonly property var opts: dateOnly ? { useDefaultTime: false } : (Backend.prefs.dates || { defaultTime: "09:00", useDefaultTime: true })
  readonly property var preview: field.input.activeFocus && field.input.text !== field._initial && field.input.text.trim() !== ""
                                 ? D.parse(field.input.text, new Date(), opts) : null

  function openPicker() {
    var target = df.ctx
    Backend.datePicker.open(field, df.value, function (v) { df.picked(df.dateOnly ? v.slice(0, 10) : v, target) })
  }

  Row {
    spacing: 4
    Field {
      id: field
      width: df.width > 0 ? df.width - pickBtn.width - 4 : Theme.px(170)
      tabbable: df.tabbable
      ctx: df.ctx
      placeholder: df.placeholder
      text: df.value ? D.compact(df.value, new Date()) : ""
      input.Keys.onDownPressed: df.openPicker()
      onEscaped: df.escaped()
      onCommitted: (v, t) => {
        var r = D.parse(v, new Date(), df.opts)
        if (r.clear) { df.picked("", t); return }
        if (r.error) {
          Backend.notice("warn", "Didn't understand \"" + v + "\" — try fri 3pm, +1h, tomorrow, 1 jan or 2027-01-01 (↓ opens the calendar)")
          input.text = df.value ? D.compact(df.value, new Date()) : ""
          return
        }
        df.picked(df.dateOnly ? r.value.slice(0, 10) : r.value, t)
      }
      input.onActiveFocusChanged: if (input.activeFocus) input.selectAll()
    }
    Btn {
      id: pickBtn
      quiet: true; icon: "󰃭"; tip: "Calendar (↓)"
      implicitHeight: field.height
      onClicked: df.openPicker()
    }
  }
  Txt {
    visible: !!df.preview
    text: !df.preview ? "" : df.preview.clear ? "→ clear" : df.preview.error ? "? " + df.preview.error : "→ " + df.preview.pretty
    color: df.preview && df.preview.error ? Theme.yellow : Theme.accent
    font.pixelSize: Theme.fsSmall
  }
}
