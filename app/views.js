.pragma library
.import "bases.js" as B

// Pure view logic: which tasks a sidebar entry shows, how they group and
// sort. Dates are compared as "YYYY-MM-DD" strings (first 10 chars), which
// is exactly how TaskNotes stores them.

function d10(s) { return s ? String(s).slice(0, 10) : "" }

function addDays(day, n) {
  var p = day.split("-")
  var d = new Date(Number(p[0]), Number(p[1]) - 1, Number(p[2]) + n)
  return fmt(d)
}
function fmt(d) {
  function z(n) { return (n < 10 ? "0" : "") + n }
  return d.getFullYear() + "-" + z(d.getMonth() + 1) + "-" + z(d.getDate())
}
function weekday(day) {
  var p = day.split("-")
  return ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"][new Date(Number(p[0]), Number(p[1]) - 1, Number(p[2])).getDay()]
}
var MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
function prettyDate(day, today) {
  if (!day) return ""
  var d = d10(day)
  var time = String(day).length > 10 ? " " + String(day).slice(11, 16) : ""
  if (d === today) return "Today" + time
  if (d === addDays(today, 1)) return "Tomorrow" + time
  if (d === addDays(today, -1)) return "Yesterday" + time
  if (d > today && d <= addDays(today, 6)) return weekday(d).slice(0, 3) + time
  var p = d.split("-")
  var s = Number(p[2]) + " " + MONTHS[Number(p[1]) - 1]
  if (p[0] !== today.slice(0, 4)) s += " " + p[0]
  return s + time
}

function isOpen(t) { return !t.error && !t.done && !t.archived }

// The date a task is "for": earliest of due/scheduled. For a recurring task
// TaskNotes keeps `scheduled` on the next open occurrence, and the core
// reports that as t.occurrence.
function nextDate(t) {
  var a = d10(t.due), b = d10(t.occurrence || t.scheduled)
  if (a && b) return a < b ? a : b
  return a || b
}

function dueBucket(day, today) {
  if (!day) return { key: "9", label: "No date" }
  if (day < today) return { key: "0", label: "Overdue" }
  if (day === today) return { key: "1", label: "Today" }
  if (day === addDays(today, 1)) return { key: "2", label: "Tomorrow" }
  if (day <= addDays(today, 6)) return { key: "3" + day, label: weekday(day) }
  var p = day.split("-")
  return { key: "4" + day.slice(0, 7), label: MONTHS[Number(p[1]) - 1] + " " + p[0] }
}

function priorityWeight(t, settings) {
  var ps = settings.priorities || []
  for (var i = 0; i < ps.length; i++) if (ps[i].value === t.priority) return ps[i].weight || 0
  return 0
}
function statusOrder(t, settings) {
  var ss = settings.statuses || []
  for (var i = 0; i < ss.length; i++) if (ss[i].value === t.status) return i
  return ss.length
}

function compareDefault(a, b, settings) {
  var da = nextDate(a) || "9999", db = nextDate(b) || "9999"
  if (da !== db) return da < db ? -1 : 1
  var pa = priorityWeight(a, settings), pb = priorityWeight(b, settings)
  if (pa !== pb) return pb - pa
  return a.title.toLowerCase() < b.title.toLowerCase() ? -1 : 1
}

// Sidebar entries ------------------------------------------------------------

function smartLists() {
  return [
    { id: "today", label: "Today", icon: "󰃶" },
    { id: "upcoming", label: "Upcoming", icon: "󰃭" },
    { id: "open", label: "All open", icon: "󰄱" },
    { id: "done", label: "Completed", icon: "󰄲" },
    { id: "archived", label: "Archived", icon: "󰆧" },
  ]
}

function facetCounts(tasks, key) {
  var counts = {}
  for (var p in tasks) {
    var t = tasks[p]
    if (!isOpen(t)) continue
    var vs = t[key] || []
    for (var i = 0; i < vs.length; i++) counts[vs[i]] = (counts[vs[i]] || 0) + 1
  }
  var out = []
  for (var k in counts) out.push({ name: k, count: counts[k] })
  out.sort(function (a, b) { return a.name.toLowerCase() < b.name.toLowerCase() ? -1 : 1 })
  return out
}

function matchesSearch(t, q) {
  if (!q) return true
  q = q.toLowerCase()
  var hay = [t.title, t.status, t.priority].concat(t.tags || [], t.contexts || [], t.projects || []).join(" ").toLowerCase()
  var words = q.split(/\s+/)
  for (var i = 0; i < words.length; i++) if (words[i] && hay.indexOf(words[i]) < 0) return false
  return true
}

// Returns { groups: [{ key, label, tasks: [...] }], count }
function compute(viewId, tasks, settings, today, opts) {
  opts = opts || {}
  var list = []
  var filter, groupBy, sorter
  var colon = viewId.indexOf(":")
  var kind = colon < 0 ? viewId : viewId.slice(0, colon)
  var arg = colon < 0 ? "" : viewId.slice(colon + 1)
  var showDone = !!opts.showDone

  switch (kind) {
  case "today":
    filter = function (t) { var d = nextDate(t); return isOpen(t) && d && d <= today }
    groupBy = "date"
    break
  case "upcoming":
    filter = function (t) { return isOpen(t) && !!nextDate(t) }
    groupBy = "date"
    break
  case "open":
    filter = isOpen
    groupBy = opts.groupBy || "status"
    break
  case "done":
    filter = function (t) { return !t.error && t.done && !t.archived }
    groupBy = "none"
    sorter = function (a, b) { return (d10(b.completedDate) || "") < (d10(a.completedDate) || "") ? -1 : 1 }
    break
  case "archived":
    filter = function (t) { return !t.error && t.archived }
    groupBy = "none"
    break
  case "problems":
    filter = function (t) { return !!t.error }
    groupBy = "none"
    break
  case "project":
  case "context":
  case "tag":
  case "note":
    var key = kind === "project" ? "projects" : kind === "context" ? "contexts" : kind === "note" ? "notes" : "tags"
    filter = function (t) {
      return (showDone ? !t.error && !t.archived : isOpen(t)) && (t[key] || []).indexOf(arg) >= 0
    }
    groupBy = opts.groupBy || "status"
    break
  case "base": {
    var bv = null
    for (var b = 0; b < (opts.baseViews || []).length; b++) if (opts.baseViews[b].id === viewId) bv = opts.baseViews[b]
    if (!bv) return { groups: [], count: 0, unsupported: "view not found (file moved or renamed?)" }
    if (bv.unsupported) return { groups: [], count: 0, unsupported: bv.unsupported }
    return computeBase(bv, tasks, settings, today, opts)
  }
  case "saved":
    var sv = null
    for (var s = 0; s < (settings.savedViews || []).length; s++) if (settings.savedViews[s].id === arg) sv = settings.savedViews[s]
    if (!sv) return { groups: [], count: 0, unsupported: "saved view not found" }
    var ev = savedViewFilter(sv.query || {}, today)
    if (ev.unsupported) return { groups: [], count: 0, unsupported: ev.unsupported }
    filter = function (t) { return !t.error && ev.fn(t) }
    groupBy = mapGroupKey(sv.query && sv.query.groupKey) || "none"
    sorter = savedViewSorter(sv.query || {}, settings)
    break
  default:
    filter = isOpen
    groupBy = "none"
  }

  for (var p in tasks) {
    var t = tasks[p]
    if (filter(t) && matchesSearch(t, opts.search)) list.push(t)
  }
  list.sort(sorter || function (a, b) { return compareDefault(a, b, settings) })
  return { groups: group(list, groupBy, settings, today), count: list.length }
}

function group(list, by, settings, today) {
  if (by === "none") return [{ key: "all", label: "", tasks: list }]
  var groups = {}, order = []
  function add(key, label, t, sortKey) {
    if (!groups[key]) { groups[key] = { key: key, label: label, sort: sortKey, tasks: [] }; order.push(key) }
    groups[key].tasks.push(t)
  }
  for (var i = 0; i < list.length; i++) {
    var t = list[i]
    if (by === "date") {
      var b = dueBucket(nextDate(t), today)
      add(b.key, b.label, t, b.key)
    } else if (by === "status") {
      var so = statusOrder(t, settings)
      add("s" + t.status, statusLabel(t.status, settings), t, String(100 + so))
    } else if (by === "priority") {
      var w = priorityWeight(t, settings)
      add("p" + t.priority, priorityLabel(t.priority, settings), t, String(100 - w))
    } else if (by === "project") {
      var pr = (t.projects && t.projects.length) ? t.projects[0] : ""
      add("j" + pr, pr || "No project", t, pr ? "0" + pr.toLowerCase() : "1")
    } else if (by === "context") {
      var cx = (t.contexts && t.contexts.length) ? t.contexts[0] : ""
      add("c" + cx, cx || "No context", t, cx ? "0" + cx.toLowerCase() : "1")
    }
  }
  var out = order.map(function (k) { return groups[k] })
  out.sort(function (a, b) { return a.sort < b.sort ? -1 : a.sort > b.sort ? 1 : 0 })
  return out
}

function statusLabel(v, settings) {
  var ss = settings.statuses || []
  for (var i = 0; i < ss.length; i++) if (ss[i].value === v) return ss[i].label || v
  return v || "No status"
}
function statusColor(v, settings) {
  var ss = settings.statuses || []
  for (var i = 0; i < ss.length; i++) if (ss[i].value === v) return ss[i].color
  return ""
}
function priorityLabel(v, settings) {
  var ps = settings.priorities || []
  for (var i = 0; i < ps.length; i++) if (ps[i].value === v) return ps[i].label || v
  return v || "No priority"
}
function priorityColor(v, settings) {
  var ps = settings.priorities || []
  for (var i = 0; i < ps.length; i++) if (ps[i].value === v) return ps[i].color
  return ""
}

// Saved views (TaskNotes' own filter builder, from data.json) ----------------

function mapGroupKey(k) {
  if (!k || k === "none") return "none"
  if (k === "due" || k === "scheduled") return "date"
  if (k === "status" || k === "priority" || k === "project" || k === "context") return k
  return "none"
}

function savedViewSorter(q, settings) {
  var key = q.sortKey, dir = q.sortDirection === "desc" ? -1 : 1
  if (!key) return null
  return function (a, b) {
    var va, vb
    if (key === "priority") { va = priorityWeight(a, settings); vb = priorityWeight(b, settings) }
    else if (key === "status") { va = statusOrder(a, settings); vb = statusOrder(b, settings) }
    else if (key === "title") { va = a.title.toLowerCase(); vb = b.title.toLowerCase() }
    else { va = d10(a[key]) || "9999"; vb = d10(b[key]) || "9999" }
    if (va === vb) return compareDefault(a, b, settings)
    return (va < vb ? -1 : 1) * dir
  }
}

var PROP = {
  status: function (t) { return t.status },
  priority: function (t) { return t.priority },
  title: function (t) { return t.title },
  due: function (t) { return d10(t.due) },
  scheduled: function (t) { return d10(t.scheduled) },
  completedDate: function (t) { return d10(t.completedDate) },
  dateCreated: function (t) { return d10(t.dateCreated) },
  dateModified: function (t) { return d10(t.dateModified) },
  tags: function (t) { return t.tags || [] },
  contexts: function (t) { return t.contexts || [] },
  projects: function (t) { return t.projects || [] },
  archived: function (t) { return !!t.archived },
  recurrence: function (t) { return t.recurrence || "" },
  blocked: function (t) { return !!t.blocked },
  timeEstimate: function (t) { return t.timeEstimate || 0 },
}

function resolveDateValue(v, today) {
  // TaskNotes stores either a literal date or a relative token.
  if (!v) return ""
  var s = String(v)
  if (s === "today") return today
  if (s === "tomorrow") return addDays(today, 1)
  if (s === "yesterday") return addDays(today, -1)
  var m = s.match(/^([+-]?\d+)d$/)
  if (m) return addDays(today, Number(m[1]))
  return d10(s)
}

function savedViewFilter(q, today) {
  var unsupported = ""
  function build(node) {
    if (!node) return function () { return true }
    if (node.type === "group") {
      var kids = (node.children || []).map(build)
      if (!kids.length) return function () { return true }
      if (node.conjunction === "or") return function (t) { for (var i = 0; i < kids.length; i++) if (kids[i](t)) return true; return false }
      return function (t) { for (var i = 0; i < kids.length; i++) if (!kids[i](t)) return false; return true }
    }
    var get = PROP[node.property]
    if (!get) { unsupported = "filter on '" + node.property + "'"; return function () { return false } }
    var op = node.operator, val = node.value
    var isDate = ["due", "scheduled", "completedDate", "dateCreated", "dateModified"].indexOf(node.property) >= 0
    if (isDate) val = resolveDateValue(val, today)
    function eq(a, b) { return String(a).toLowerCase() === String(b).toLowerCase() }
    function has(x, v) {
      if (Array.isArray(x)) { for (var i = 0; i < x.length; i++) if (eq(x[i], v)) return true; return false }
      return String(x).toLowerCase().indexOf(String(v).toLowerCase()) >= 0
    }
    function anyOf(x, vs) {
      vs = Array.isArray(vs) ? vs : [vs]
      for (var i = 0; i < vs.length; i++) if (Array.isArray(x) ? has(x, vs[i]) : eq(x, vs[i])) return true
      return false
    }
    function empty(x) { return x === "" || x === null || x === undefined || x === false || (Array.isArray(x) && !x.length) }
    switch (op) {
    case "is": return function (t) { return anyOf(get(t), val) }
    case "is-not": return function (t) { return !anyOf(get(t), val) }
    case "contains": return function (t) { return anyOf(get(t), val) || has(get(t), val) }
    case "does-not-contain": return function (t) { return !(anyOf(get(t), val) || has(get(t), val)) }
    case "is-empty": return function (t) { return empty(get(t)) }
    case "is-not-empty": return function (t) { return !empty(get(t)) }
    case "is-checked": return function (t) { return !!get(t) }
    case "is-not-checked": return function (t) { return !get(t) }
    case "is-before": return function (t) { var x = get(t); return !!x && x < val }
    case "is-after": return function (t) { var x = get(t); return !!x && x > val }
    case "is-on-or-before": return function (t) { var x = get(t); return !!x && x <= val }
    case "is-on-or-after": return function (t) { var x = get(t); return !!x && x >= val }
    case "is-greater-than": return function (t) { return Number(get(t)) > Number(val) }
    case "is-less-than": return function (t) { return Number(get(t)) < Number(val) }
    }
    unsupported = "operator '" + op + "'"
    return function () { return false }
  }
  var fn = build(q)
  return { fn: fn, unsupported: unsupported }
}

// Bases (.base) views ----------------------------------------------------------

function computeBase(bv, tasks, settings, today, opts) {
  var byName = B.index(tasks)
  var now = Date.now()
  var list = []
  for (var p in tasks) {
    var t = tasks[p]
    if (t.error) continue
    if (B.matches(bv, t, byName, now) && matchesSearch(t, opts.search)) list.push(t)
  }
  // Obsidian ignores a sort on a note property that no task in the view has
  // (TaskNotes' tasknotes_manual_order before anything is dragged, or
  // completedDate in a list of open tasks); with no sort left it lists by
  // file name.
  var sorts = (bv.sort || []).filter(function (s) {
    if (!s.ast || s.ast[0] !== "prop") return true
    return list.some(function (t) { return t.props && t.props[s.ast[1]] !== undefined })
  })
  function baseName(t) { return t.path.slice(t.path.lastIndexOf("/") + 1).replace(/\.md$/, "") }
  var keys = {}
  function sortKey(t, i) {
    var k = t.path + "#" + i
    if (!(k in keys)) {
      // Obsidian sorts file.name without its extension ("Oracle weekly"
      // before "Oracle weekly (copy)"), though the value itself has one.
      keys[k] = sorts[i].key === "file.name" ? baseName(t) : B.sortValue(B.value(sorts[i].ast, t, byName, now))
    }
    return keys[k]
  }
  function byPath(a, b) { return B.compareValues(a.path, b.path) || (a.path < b.path ? -1 : a.path > b.path ? 1 : 0) }
  list.sort(function (a, b) {
    // No sort: Obsidian lists by file name.
    if (!sorts.length) return B.compareValues(baseName(a), baseName(b)) || byPath(a, b)
    for (var i = 0; i < sorts.length; i++) {
      var c = B.compareValues(sortKey(a, i), sortKey(b, i))
      if (c) return sorts[i].dir === "desc" && !(sortKey(a, i) === null || sortKey(b, i) === null) ? -c : c
    }
    // Ties fall back to the full path, ascending whatever the direction, as
    // Obsidian's views do (checked by tools/basestest.py).
    return byPath(a, b)
  })
  var groups
  if (bv.layout === "dates") {
    var prop = bv.dateProperty
    list = list.filter(function (t) { return prop ? !!t[prop] : !!nextDate(t) })
    if (prop === "dateCreated" || prop === "dateModified" || prop === "completedDate") {
      // Past-facing dates: one group per day, newest first.
      list.sort(function (a, b) { return d10(b[prop]) < d10(a[prop]) ? -1 : d10(b[prop]) > d10(a[prop]) ? 1 : 0 })
      var days = {}, dorder = []
      list.forEach(function (t) {
        var k = d10(t[prop])
        if (!days[k]) { days[k] = { key: "d" + k, label: prettyDate(k, today), tasks: [] }; dorder.push(k) }
        days[k].tasks.push(t)
      })
      groups = dorder.map(function (k) { return days[k] })
    } else {
      groups = group(list, "date", settings, today)
    }
  } else if (bv.group && bv.layout !== "board") {
    var gs = {}, order = []
    for (var i = 0; i < list.length; i++) {
      var raw = B.value(bv.group.ast, list[i], byName, now)
      var lab = B.label(raw)
      // Obsidian puts a date and a date-with-time on the same day in one
      // group, labelled by whichever comes first.
      var id = B.isDate(raw) ? B.formatDate(raw, "YYYY-MM-DD")
        : /^\d{4}-\d{2}-\d{2}([T ]|$)/.test(lab) ? lab.slice(0, 10) : lab
      if (!gs[id]) { gs[id] = { key: "g" + id, label: lab || "None", sort: B.sortValue(raw), tasks: [] }; order.push(id) }
      gs[id].tasks.push(list[i])
    }
    groups = order.map(function (k) { return gs[k] })
    groups.sort(function (a, b) {
      var c = B.compareValues(a.sort, b.sort)
      var empty = a.sort === null || a.sort === undefined || a.sort === "" || b.sort === null || b.sort === undefined || b.sort === ""
      return bv.group.dir === "desc" && !empty ? -c : c      // no-value group stays last
    })
  } else {
    groups = [{ key: "all", label: "", tasks: list }]
  }
  return { groups: groups, count: list.length, layout: bv.layout === "board" ? "board" : "list" }
}
