import QtQuick
import QtQuick.Controls
import ".."
import "../views.js" as V
import "../bases.js" as B

// Builds an Obsidian Bases view. Saving writes one .base file into
// TaskNotes/Views (or rewrites the one being edited); the same file opens
// as a view in Obsidian.
Rectangle {
  id: ed
  visible: false
  color: Theme.a(Theme.bg, 0.75)
  z: 95
  signal saved(string viewId)
  signal closed()
  signal deleted(string file)

  property string file: ""          // editing this .base file ("" = new)
  property var model: blank()
  property int previewCount: -1
  property string previewError: ""
  property var pickerFor: null      // {options: [{value,label}], pick: fn, anchor: item}

  function blank() {
    return { name: "", match: "all", conditions: [{ field: "status", op: "open", value: "" }],
             sort: { field: "due", dir: "asc" }, group: "none", layout: "list" }
  }
  function openNew(seed) {
    file = ""
    model = seed || blank()
    show()
  }
  function openEdit(view) {
    file = view.file
    model = JSON.parse(JSON.stringify(view.model))
    show()
  }
  function show() {
    visible = true
    previewTimer.restart()
    nameField.input.forceActiveFocus()
  }
  function deleteCurrent() {
    var f = ed.file
    if (!f) return
    Backend.deleteView(f, function (r) { if (r.ok) { Backend.notice("info", "View moved to the trash"); ed.close(); ed.deleted(f) } })
  }
  function close() { nameField.input.focus = false; visible = false; pickerFor = null; closed() }
  function touch() { model = JSON.parse(JSON.stringify(model)); previewTimer.restart() }

  readonly property var fields: [
    { value: "status", label: "Status" }, { value: "priority", label: "Priority" },
    { value: "due", label: "Due date" }, { value: "scheduled", label: "Scheduled" }, { value: "completedDate", label: "Completed on" },
    { value: "projects", label: "Project" }, { value: "contexts", label: "Context" }, { value: "tags", label: "Tag" },
    { value: "title", label: "Title" }, { value: "archived", label: "Archived" }, { value: "recurring", label: "Repeating" }
  ]
  function opsFor(field) {
    if (field === "status") return [{ value: "open", label: "is not completed" }, { value: "completed", label: "is completed" },
                                     { value: "is", label: "is" }, { value: "isNot", label: "is not" }]
    if (field === "priority") return [{ value: "is", label: "is" }, { value: "isNot", label: "is not" }]
    if (field === "due" || field === "scheduled" || field === "completedDate")
      return [{ value: "onOrBefore", label: "on or before" }, { value: "before", label: "before" }, { value: "on", label: "on" },
              { value: "onOrAfter", label: "on or after" }, { value: "after", label: "after" },
              { value: "notEmpty", label: "is set" }, { value: "empty", label: "is empty" }]
    if (field === "projects" || field === "contexts") return [{ value: "has", label: "includes" }, { value: "lacks", label: "doesn't include" }]
    if (field === "tags") return [{ value: "has", label: "has" }, { value: "lacks", label: "doesn't have" }]
    if (field === "title") return [{ value: "has", label: "contains" }, { value: "lacks", label: "doesn't contain" }]
    return [{ value: "yes", label: "yes" }, { value: "no", label: "no" }]
  }
  // What kind of value input a condition needs.
  function valueKind(c) {
    if (c.field === "status") return (c.op === "is" || c.op === "isNot") ? "status" : "none"
    if (c.field === "priority") return "priority"
    if (c.field === "due" || c.field === "scheduled" || c.field === "completedDate") return (c.op === "empty" || c.op === "notEmpty") ? "none" : "date"
    if (c.field === "archived" || c.field === "recurring") return "none"
    return "text"
  }
  function defaultValue(c) {
    var k = valueKind(c)
    if (k === "status") return (Backend.settings.statuses[0] || {}).value || ""
    if (k === "priority") return (Backend.settings.priorities[Backend.settings.priorities.length - 1] || {}).value || ""
    if (k === "date") return "today"
    return ""
  }
  function labelOf(list, v) { for (var i = 0; i < list.length; i++) if (list[i].value === v) return list[i].label; return v }
  function suggestions(field) {
    var key = field === "projects" ? "projects" : field === "contexts" ? "contexts" : "tags"
    var facets = V.facetCounts(Backend.tasks, key)
    return facets.map(function (f) { return { value: field === "projects" ? "[[" + f.name + "]]" : f.name, label: f.name } })
  }

  function openPicker(anchor, options, pick) { pickerFor = { anchor: anchor, options: options, pick: pick } }

  Timer {
    id: previewTimer
    interval: 250
    onTriggered: {
      var m = ed.model
      Backend.previewView(m, function (r) {
        if (!r.ok) { ed.previewError = r.message; ed.previewCount = -1; return }
        var v = r.result.view
        if (!v || v.unsupported) { ed.previewError = v ? v.unsupported : "nothing to preview"; ed.previewCount = -1; return }
        ed.previewError = ""
        var byName = B.index(Backend.tasks), now = Date.now(), n = 0
        for (var p in Backend.tasks) if (!Backend.tasks[p].error && B.matches(v, Backend.tasks[p], byName, now)) n++
        ed.previewCount = n
      })
    }
  }

  function save() {
    if (!model.name || !model.name.trim()) { nameField.input.forceActiveFocus(); Backend.notice("warn", "Give the view a name"); return }
    Backend.saveView(model, file, function (r) {
      if (!r.ok) return
      ed.close()
      ed.saved(r.result.id)
      Backend.notice("info", "Saved " + r.result.file)
    })
  }

  MouseArea { anchors.fill: parent; onClicked: ed.pickerFor = null }

  Rectangle {
    id: box
    anchors.centerIn: parent
    width: Math.min(Theme.px(640), ed.width - Theme.px(32))
    height: Math.min(col.implicitHeight + Theme.px(28), ed.height - Theme.px(32))
    color: Theme.bg
    border.color: Theme.accent
    MouseArea { anchors.fill: parent; onClicked: ed.pickerFor = null }

    Keys.onEscapePressed: { if (ed.pickerFor) ed.pickerFor = null; else ed.close() }
    Keys.onPressed: e => {
      if ((e.key === Qt.Key_Return || e.key === Qt.Key_Enter) && (e.modifiers & Qt.ControlModifier)) { ed.save(); e.accepted = true }
    }

    Flickable {
      anchors.fill: parent
      anchors.margins: Theme.px(14)
      contentHeight: col.implicitHeight
      clip: true
      boundsBehavior: Flickable.StopAtBounds

      Column {
        id: col
        width: parent.width
        spacing: Theme.px(12)

        Txt { text: ed.file ? "Edit view" : "New view"; font.bold: true; font.pixelSize: Theme.fsLarge }

        Row {
          spacing: 8
          width: parent.width
          Txt { text: "Name"; color: Theme.faint; width: Theme.px(70); height: nameField.height }
          Field {
            id: nameField
            width: parent.width - Theme.px(78)
            tabbable: true
            text: ed.model.name
            placeholder: "e.g. Home this week"
            input.onTextChanged: if (input.activeFocus && ed.model.name !== input.text) { ed.model.name = input.text }
            onEscaped: ed.close()
          }
        }

        Row {
          spacing: 6
          Txt { text: "Show tasks matching"; color: Theme.faint; height: Theme.px(26) }
          Btn { text: "all"; active: ed.model.match !== "any"; onClicked: { ed.model.match = "all"; ed.touch() } }
          Btn { text: "any"; active: ed.model.match === "any"; onClicked: { ed.model.match = "any"; ed.touch() } }
          Txt { text: "of these conditions"; color: Theme.faint; height: Theme.px(26) }
        }

        Column {
          width: parent.width
          spacing: 6
          Repeater {
            model: ed.model.conditions
            delegate: Row {
              id: crow
              required property var modelData
              required property int index
              spacing: 6
              readonly property var c: modelData
              Btn {
                id: pk1
                width: Theme.px(120)
                text: ed.labelOf(ed.fields, crow.c.field) + " ▾"
                onClicked: ed.openPicker(pk1, ed.fields, function (v) {
                  var c = ed.model.conditions[crow.index]
                  c.field = v; c.op = ed.opsFor(v)[0].value; c.value = ed.defaultValue(c); ed.touch()
                })
              }
              Btn {
                id: pk2
                width: Theme.px(150)
                text: ed.labelOf(ed.opsFor(crow.c.field), crow.c.op) + " ▾"
                onClicked: ed.openPicker(pk2, ed.opsFor(crow.c.field), function (v) {
                  var c = ed.model.conditions[crow.index]
                  var kindBefore = ed.valueKind(c)
                  c.op = v
                  if (ed.valueKind(c) !== kindBefore) c.value = ed.defaultValue(c)
                  ed.touch()
                })
              }
              // value
              Btn {
                id: pk3
                visible: ed.valueKind(crow.c) === "status" || ed.valueKind(crow.c) === "priority"
                width: Theme.px(150)
                property var opts: (ed.valueKind(crow.c) === "status" ? Backend.settings.statuses : Backend.settings.priorities)
                                     .map(function (s) { return { value: s.value, label: s.label || s.value } })
                text: ed.labelOf(opts, crow.c.value) + " ▾"
                onClicked: ed.openPicker(pk3, opts, function (v) { ed.model.conditions[crow.index].value = v; ed.touch() })
              }
              Field {
                id: valField
                visible: ed.valueKind(crow.c) === "date" || ed.valueKind(crow.c) === "text"
                width: Theme.px(150)
                tabbable: true
                text: crow.c.value || ""
                placeholder: ed.valueKind(crow.c) === "date" ? "today, +7, -1, 2026-12-25" : crow.c.field === "projects" ? "[[Project]]" : ""
                onCommitted: (v) => { ed.model.conditions[crow.index].value = v.trim(); ed.touch() }
                onEscaped: ed.close()
              }
              Btn {
                visible: ed.valueKind(crow.c) === "text" && crow.c.field !== "title"
                quiet: true; text: "▾"; tip: "Pick an existing one"
                onClicked: ed.openPicker(valField, ed.suggestions(crow.c.field), function (v) { ed.model.conditions[crow.index].value = v; ed.touch() })
              }
              Btn {
                quiet: true; text: "✕"; tip: "Remove condition"
                onClicked: { ed.model.conditions.splice(crow.index, 1); ed.touch() }
              }
            }
          }
          Btn { text: "+ condition"; quiet: true; onClicked: { ed.model.conditions.push({ field: "status", op: "open", value: "" }); ed.touch() } }
        }

        Row {
          spacing: 6
          Txt { text: "Sort by"; color: Theme.faint; width: Theme.px(70); height: Theme.px(26) }
          Btn {
            id: pk4
            width: Theme.px(140)
            property var opts: [{ value: "none", label: "nothing" }, { value: "due", label: "due date" }, { value: "scheduled", label: "scheduled" },
                                { value: "priority", label: "priority" }, { value: "status", label: "status" }, { value: "title", label: "title" },
                                { value: "dateCreated", label: "created" }, { value: "completedDate", label: "completed on" }]
            text: ed.labelOf(opts, ed.model.sort.field) + " ▾"
            onClicked: ed.openPicker(pk4, opts, function (v) { ed.model.sort.field = v; ed.touch() })
          }
          Btn {
            visible: ed.model.sort.field !== "none"
            text: ed.model.sort.dir === "desc" ? "↓ descending" : "↑ ascending"
            onClicked: { ed.model.sort.dir = ed.model.sort.dir === "desc" ? "asc" : "desc"; ed.touch() }
          }
        }

        Row {
          spacing: 6
          Txt { text: "Show as"; color: Theme.faint; width: Theme.px(70); height: Theme.px(26) }
          Btn { text: "list"; active: ed.model.layout !== "board"; onClicked: { ed.model.layout = "list"; ed.touch() } }
          Btn { text: "board"; active: ed.model.layout === "board"; onClicked: { ed.model.layout = "board"; ed.touch() } }
          Txt { visible: ed.model.layout !== "board"; text: "  grouped by"; color: Theme.faint; height: Theme.px(26) }
          Btn {
            id: pk5
            visible: ed.model.layout !== "board"
            width: Theme.px(120)
            property var opts: [{ value: "none", label: "nothing" }, { value: "status", label: "status" }, { value: "priority", label: "priority" },
                                { value: "due", label: "due date" }, { value: "scheduled", label: "scheduled" },
                                { value: "projects", label: "project" }, { value: "contexts", label: "context" }]
            text: ed.labelOf(opts, ed.model.group) + " ▾"
            onClicked: ed.openPicker(pk5, opts, function (v) { ed.model.group = v; ed.touch() })
          }
        }

        Txt {
          width: parent.width
          wrapMode: Text.Wrap
          elide: Text.ElideNone
          color: ed.previewError ? Theme.yellow : Theme.faint
          text: ed.previewError ? "⚠ " + ed.previewError
                : ed.previewCount < 0 ? " " : "Matches " + ed.previewCount + " task" + (ed.previewCount === 1 ? "" : "s") + " right now"
        }
        Txt {
          width: parent.width
          wrapMode: Text.Wrap
          elide: Text.ElideNone
          font.pixelSize: Theme.fsSmall
          color: Theme.a(Theme.fg, 0.4)
          text: ed.file ? "Saves to " + ed.file : "Saves as a new .base file in " + (Backend.settings.tasksFolder || "").replace(/\/[^\/]*$/, "") + "/Views — it opens in Obsidian too."
        }

        Row {
          spacing: 8
          Btn { text: "Save (Ctrl+Enter)"; active: true; onClicked: ed.save() }
          Btn { text: "Cancel (Esc)"; onClicked: ed.close() }
          Btn {
            visible: ed.file !== ""
            text: "Delete view"
            textColor: Theme.red
            onClicked: ed.deleteCurrent()
          }
        }
      }
    }
  }

  // One shared dropdown list, positioned under whichever control asked.
  Rectangle {
    id: picker
    visible: !!ed.pickerFor
    z: 200
    property point at: ed.pickerFor ? ed.pickerFor.anchor.mapToItem(ed, 0, ed.pickerFor.anchor.height + 2) : Qt.point(0, 0)
    x: Math.min(at.x, ed.width - width - 8)
    y: Math.min(at.y, ed.height - height - 8)
    width: Math.max(Theme.px(160), pickCol.implicitWidth + 8)
    height: Math.min(pickCol.implicitHeight + 8, Theme.px(320))
    color: Theme.bg
    border.color: Theme.border
    Flickable {
      anchors.fill: parent
      anchors.margins: 4
      contentHeight: pickCol.implicitHeight
      clip: true
      Column {
        id: pickCol
        Repeater {
          model: ed.pickerFor ? ed.pickerFor.options : []
          Rectangle {
            required property var modelData
            width: Math.max(picker.width - 8, optTxt.implicitWidth + 16)
            height: Theme.px(24)
            color: optMa.containsMouse ? Theme.hoverFill : "transparent"
            Txt {
              id: optTxt
              anchors { left: parent.left; leftMargin: 8; verticalCenter: parent.verticalCenter }
              text: modelData.label
            }
            MouseArea {
              id: optMa
              anchors.fill: parent
              hoverEnabled: true
              onClicked: { var f = ed.pickerFor.pick; ed.pickerFor = null; f(modelData.value) }
            }
          }
        }
        Txt { visible: ed.pickerFor && !ed.pickerFor.options.length; text: "  nothing to pick yet  "; color: Theme.faint; height: Theme.px(24) }
      }
    }
  }
}
