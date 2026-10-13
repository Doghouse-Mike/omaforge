.pragma library

// Obsidian Tasks ```tasks query blocks, evaluated over OmaForge's Tasks-mode
// records (core/omaforge/inline.py build()). Semantics follow Tasks 8.5.0 as
// written up in docs/tasks-query-spec.md (section numbers below refer to it);
// tools/tasksquerytest.py checks the results against the plugin itself.
//
//   evaluate(source, tasks, { file, settings, today })
//     -> { error } | { unsupported } | { total, groups: [{ names, tasks }] }
//
// `error` is what Tasks would show as an error; `unsupported` means Tasks
// would accept the line but OmaForge can't reproduce it (say, a date phrase
// outside the subset below), so the caller shows the query dimmed rather than
// with a wrong answer. Group names are Tasks' own, including the hidden
// %%n%% ordering prefixes; displayName() strips those for display.

function lc(a, b) { return String(a).localeCompare(String(b), undefined, { numeric: true }) }

function Unsupported(msg) { this.unsupported = msg }
function QueryError(msg) { this.error = msg }

// ---- Days: whole days since 1970-01-01 (UTC arithmetic, so no DST) --------

var WEEKDAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]

function mk(y, m, d) { return Date.UTC(y, m - 1, d) / 86400000 }
function parts(n) { var d = new Date(n * 86400000); return [d.getUTCFullYear(), d.getUTCMonth() + 1, d.getUTCDate()] }
function ymd(n) { return new Date(n * 86400000).toISOString().slice(0, 10) }
function dow(n) { return new Date(n * 86400000).getUTCDay() }        // 0 = Sunday
function daysInMonth(y, m) { return new Date(Date.UTC(y, m, 0)).getUTCDate() }
function addMonths(n, k) {
  var p = parts(n), t = p[0] * 12 + (p[1] - 1) + k, y = Math.floor(t / 12), m = t % 12 + 1
  return mk(y, m, Math.min(p[2], daysInMonth(y, m)))
}

// A task date: null (missing), NaN (invalid, e.g. 2026-02-30) or a day.
function dayOf(s) {
  if (s === null || s === undefined || s === "") return null
  var m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(s))
  if (!m) return NaN
  var y = +m[1], mo = +m[2], d = +m[3]
  if (mo < 1 || mo > 12 || d < 1 || d > daysInMonth(y, mo)) return NaN
  return mk(y, mo, d)
}
function valid(d) { return d !== null && !isNaN(d) }

// ---- §2.4 date ranges -----------------------------------------------------

var NUMWORDS = { a: 1, an: 1, one: 1, two: 2, three: 3, four: 4, five: 5, six: 6, seven: 7, eight: 8, nine: 9,
                 ten: 10, eleven: 11, twelve: 12 }
var UNIT = "(days?|weeks?|months?|years?)"
var WDAY = { sunday: 0, sun: 0, monday: 1, mon: 1, tuesday: 2, tue: 2, tues: 2, wednesday: 3, wed: 3,
             thursday: 4, thu: 4, thur: 4, thurs: 4, friday: 5, fri: 5, saturday: 6, sat: 6 }

function shift(today, n, unit) {
  unit = unit.replace(/s$/, "")
  if (unit === "day") return today + n
  if (unit === "week") return today + 7 * n
  if (unit === "month") return addMonths(today, n)
  return addMonths(today, 12 * n)
}

function relativeRange(text, today) {
  var m = /(last|this|next) (week|month|quarter|year)/.exec(text)     // case-sensitive, unanchored
  if (!m) return null
  var k = m[1] === "last" ? -1 : m[1] === "next" ? 1 : 0, p = parts(today), s, e
  if (m[2] === "week") {
    s = today - (dow(today) + 6) % 7 + 7 * k          // ISO week: Monday..Sunday
    return { start: s, end: s + 6 }
  }
  if (m[2] === "month") {
    s = addMonths(mk(p[0], p[1], 1), k); var q = parts(s)
    return { start: s, end: mk(q[0], q[1], daysInMonth(q[0], q[1])) }
  }
  if (m[2] === "quarter") {
    s = addMonths(mk(p[0], Math.floor((p[1] - 1) / 3) * 3 + 1, 1), 3 * k)
    var e3 = addMonths(s, 2), r = parts(e3)
    return { start: s, end: mk(r[0], r[1], daysInMonth(r[0], r[1])) }
  }
  return { start: mk(p[0] + k, 1, 1), end: mk(p[0] + k, 12, 31) }
}

function isoWeekStart(y, w) {
  var jan4 = mk(y, 1, 4), mon = jan4 - (dow(jan4) + 6) % 7
  return mon + 7 * (w - 1)
}
function isoWeeksIn(y) {
  var dec28 = mk(y, 12, 28)
  return Math.round((dec28 - isoWeekStart(y, 1)) / 7) + 1
}

function numberedRange(text) {
  var m
  if ((m = /^\s*([0-9]{4})\s*$/.exec(text))) return { start: mk(+m[1], 1, 1), end: mk(+m[1], 12, 31) }
  if ((m = /^\s*([0-9]{4})-Q([1-4])\s*$/.exec(text))) {
    var qs = mk(+m[1], (+m[2] - 1) * 3 + 1, 1), qe = parts(addMonths(qs, 2))
    return { start: qs, end: mk(qe[0], qe[1], daysInMonth(qe[0], qe[1])) }
  }
  if ((m = /^\s*([0-9]{4})-([0-9]{2})\s*$/.exec(text))) {
    var mo = +m[2]
    if (mo < 1 || mo > 12) return null
    return { start: mk(+m[1], mo, 1), end: mk(+m[1], mo, daysInMonth(+m[1], mo)) }
  }
  if ((m = /^\s*([0-9]{4})-W([0-9]{2})\s*$/.exec(text))) {
    var w = +m[2]
    if (w < 1 || w > isoWeeksIn(+m[1])) return null
    var ws = isoWeekStart(+m[1], w)
    return { start: ws, end: ws + 6 }
  }
  return null
}

// The chrono subset (§2.4 table): one phrase -> a day, null (not a date at
// all), or throws Unsupported for anything chrono might read differently.
function phraseDay(text, today) {
  var t = text.trim().toLowerCase(), m
  if (t === "today") return today
  if (t === "tomorrow") return today + 1
  if (t === "yesterday") return today - 1
  if (WDAY[t] !== undefined) {
    var diff = WDAY[t] - dow(today), best = diff
    ;[diff - 7, diff + 7].forEach(function (x) { if (Math.abs(x) < Math.abs(best)) best = x })
    return today + best
  }
  if ((m = /^(this|next|last) ([a-z]+)$/.exec(t)) && WDAY[m[2]] !== undefined)
    return today - dow(today) + WDAY[m[2]] + (m[1] === "next" ? 7 : m[1] === "last" ? -7 : 0)
  if ((m = new RegExp("^in (\\d+|[a-z]+) " + UNIT + "$").exec(t))) {
    var n = /^\d+$/.test(m[1]) ? +m[1] : NUMWORDS[m[1]]
    if (n !== undefined) return shift(today, n, m[2])
  }
  if ((m = new RegExp("^(\\d+|[a-z]+) " + UNIT + " ago$").exec(t))) {
    var k = /^\d+$/.test(m[1]) ? +m[1] : NUMWORDS[m[1]]
    if (k !== undefined) return shift(today, -k, m[2])
  }
  if (/^\d{4}-\d{2}-\d{2}$/.test(t)) {
    var d = dayOf(t)
    if (valid(d)) return d
    throw new Unsupported("date \"" + text.trim() + "\"")
  }
  throw new Unsupported("date \"" + text.trim() + "\"")
}

function dateRange(text, today) {
  var r = relativeRange(text, today) || numberedRange(text)
  if (r) return r
  var t = text.trim()
  // Absolute dates: one is a day; two make a range (an impossible one is skipped).
  var abs = t.split(/\s+/)
  if (abs.length === 2 && abs.every(function (x) { return /^\d{4}-\d{2}-\d{2}$/.test(x) })) {
    var ds = abs.map(dayOf).filter(valid)
    if (ds.length === 2) return ds[0] <= ds[1] ? { start: ds[0], end: ds[1] } : { start: ds[1], end: ds[0] }
    if (ds.length === 1) return { start: ds[0], end: ds[0] }
    throw new Unsupported("date \"" + t + "\"")
  }
  var d = phraseDay(t, today)
  return { start: d, end: d }
}

// ---- Task values ------------------------------------------------------------

var PRIO = { highest: "0", high: "1", medium: "2", none: "3", low: "4", lowest: "5" }
var PRIO_GROUP = ["Highest", "High", "Medium", "Normal", "Low", "Lowest"]
var TYPE_TEXT = { IN_PROGRESS: "%%1%%IN_PROGRESS", TODO: "%%2%%TODO", ON_HOLD: "%%3%%ON_HOLD", DONE: "%%4%%DONE",
                  CANCELLED: "%%5%%CANCELLED", NON_TASK: "%%6%%NON_TASK", EMPTY: "%%7%%EMPTY" }

function isDone(t) { return t.statusType === "DONE" || t.statusType === "CANCELLED" || t.statusType === "NON_TASK" }
function dates(t) {
  if (!t._d) t._d = { due: dayOf(t.due), scheduled: dayOf(t.scheduled), start: dayOf(t.start), created: dayOf(t.created),
                      done: dayOf(t.doneDate), cancelled: dayOf(t.cancelledDate) }
  return t._d
}
function happens(t) {
  var d = dates(t), best = null
  ;[d.start, d.scheduled, d.due].forEach(function (x) { if (valid(x) && (best === null || x < best)) best = x })
  return best
}
function filename(t) { var m = /([^/]+)\.md$/.exec(t.file); return m ? m[1] + ".md" : "" }
function folder(t) { var f = filename(t), p = f ? t.file.substring(0, t.file.lastIndexOf(f)) : ""; return p || "/" }
function root(t) {
  var p = t.file.replace(/\\/g, "/").replace(/^\//, ""), i = p.indexOf("/")
  return i < 0 ? "/" : p.slice(0, i + 1)
}
function withoutGlobalFilter(s, gf) {
  if (gf && s.indexOf(gf) >= 0) s = s.replace(gf, "")
  return s.trim()
}
function tagsOf(t, gf) { return (t.allTags || []).filter(function (x) { return !gf || x !== gf }) }
function prioCode(t) { return PRIO[t.priority] || "3" }

function urgency(t, today) {
  var d = dates(t), u = 0
  if (valid(d.due)) {
    var over = today - d.due
    u += (over >= 7 ? 1.0 : over >= -14 ? ((over + 14) * 0.8) / 21 + 0.2 : 0.2) * 12.0
  }
  if (valid(d.scheduled) && d.scheduled <= today) u += 5.0
  if (valid(d.start) && d.start > today) u += -3.0
  u += { "0": 1.5 * 6, "1": 1.0 * 6, "2": 0.65 * 6, "3": 0.325 * 6, "4": 0, "5": -0.3 * 6 }[prioCode(t)]
  return u
}

// ---- §1.2 continuation, §1.3 placeholders, §1.5 presets ---------------------

function statements(src) {
  var out = [], cur = null
  var lines = (src + "\n").split("\n")
  for (var i = 0; i < lines.length; i++) {
    var raw = lines[i], cont = false
    if (/\\\\$/.test(raw)) raw = raw.slice(0, -1)
    else if (/\\$/.test(raw)) { raw = raw.replace(/[ \t]*\\$/, ""); cont = true }
    if (cur !== null) { cur.text += " " + raw.replace(/^[ \t]*/, ""); cur.raw += "\n" + lines[i] }
    else cur = { text: raw, raw: lines[i] }
    if (!cont) {
      if (cur.text.trim()) out.push({ text: cur.text.trim(), raw: cur.raw })
      cur = null
    }
  }
  return out
}

var DEFAULT_PRESETS = {
  this_file: "path includes {{query.file.path}}",
  this_folder: "folder includes {{query.file.folder}}",
  this_folder_only: "filter by function task.file.folder === query.file.folder",
  this_root: "root includes {{query.file.root}}",
  hide_date_fields: "# Hide any values for all date fields\nhide due date\nhide scheduled date\nhide start date\nhide created date\nhide done date\nhide cancelled date",
  hide_non_date_fields: "# Hide all the non-date fields, but not tags\nhide id\nhide depends on\nhide recurrence rule\nhide on completion\nhide priority",
  hide_query_elements: "# Hide postpone, edit and backinks\nhide postpone button\nhide edit button\nhide backlinks",
  hide_everything: "# Hide everything except description and any tags\npreset hide_date_fields\npreset hide_non_date_fields\npreset hide_query_elements",
}

function fileValues(file) {
  var name = (/([^/]+)$/.exec(file) || [, ""])[1]
  var t = { file: file }
  return {
    "query.file.path": file, "query.file.pathWithoutExtension": file.replace(/\.md$/, ""),
    "query.file.root": root(t), "query.file.folder": folder(t),
    "query.file.filename": name, "query.file.filenameWithoutExtension": name.replace(/\.md$/, ""),
  }
}

function expand(text, ctx) {
  return text.replace(/\{\{(.*?)\}\}/g, function (_, inner) {
    var k = inner.trim()
    if (ctx.files[k] !== undefined) return ctx.files[k]
    var p = /^preset\.([A-Za-z_$][\w$]*)$/.exec(k)
    if (p) {
      if (ctx.presets[p[1]] === undefined) throw new QueryError("There was an error expanding one or more placeholders.\n\nThe error message was:\n    Unknown property: " + k)
      return ctx.presets[p[1]]
    }
    if (/^query\.file\.(property|hasProperty)\(/.test(k)) throw new Unsupported("{{" + k + "}} (note properties)")
    if (/^[A-Za-z_$][\w$]*(\.[A-Za-z_$][\w$]*)*$/.test(k))
      throw new QueryError("There was an error expanding one or more placeholders.\n\nThe error message was:\n    Unknown property: " + k)
    throw new QueryError("JavaScript is now disabled in Tasks queries by default.")
  })
}

// ---- §2 filters ---------------------------------------------------------------

var TEXT_FIELDS = ["status.name", "path", "folder", "root", "description", "tags?", "heading", "filename", "recurrence", "id"]
var DATE_FIELDS = [["happens", "happens"], ["cancelled", "cancelled"], ["created", "created"], ["starts", "start"],
                   ["scheduled", "scheduled"], ["due", "due"], ["done", "done"]]
var STATUS_TYPES = ["TODO", "DONE", "IN_PROGRESS", "ON_HOLD", "CANCELLED", "NON_TASK", "EMPTY"]

function textValue(field, t, ctx) {
  switch (field) {
  case "status.name": return t.statusName || ""
  case "path": return t.file
  case "folder": return folder(t)
  case "root": return root(t)
  case "description": return withoutGlobalFilter(t.description || "", ctx.gf)
  case "heading": return t.heading || ""
  case "filename": return filename(t)
  case "recurrence": return t.ruleText || ""
  case "id": return t.taskId || ""
  }
  return ""
}

function regexOf(needle) {
  var m = /^\/(.+)\/([^/]*)$/.exec(needle)
  if (!m) throw new QueryError("Invalid instruction: regex must be in the form /pattern/flags")
  try { return new RegExp(m[1], m[2]) } catch (e) { throw new QueryError("Parsing regular expression: " + e.message) }
}

function textFilter(line, ctx) {
  for (var i = 0; i < TEXT_FIELDS.length; i++) {
    var f = TEXT_FIELDS[i], multi = f === "tags?"
    var ops = "includes|does not include|regex matches|regex does not match" + (multi ? "|include|do not include" : "")
    var m = new RegExp("^(?:" + f + ") (" + ops + ") (.*)", "i").exec(line)
    if (!m) continue
    var op = m[1].toLowerCase(), needle = m[2], neg = op.indexOf("not") >= 0, test
    if (op.indexOf("regex") >= 0) { var re = regexOf(needle); test = function (v) { return v.match(re) !== null } }
    else { var n = needle.toLocaleLowerCase(); test = function (v) { return v.toLocaleLowerCase().indexOf(n) >= 0 } }
    if (multi) return function (t) { var any = tagsOf(t, ctx.gf).some(test); return neg ? !any : any }
    return (function (field) { return function (t) { var r = test(textValue(field, t, ctx)); return neg ? !r : r } })(f)
  }
  return null
}

function dateFilter(line, ctx) {
  var low = line.toLowerCase()
  for (var i = 0; i < DATE_FIELDS.length; i++) {
    var kw = DATE_FIELDS[i][0], field = DATE_FIELDS[i][1]
    if (low === "has " + field + " date") return field === "happens"
      ? function (t) { var d = dates(t); return d.start !== null || d.scheduled !== null || d.due !== null }
      : (function (f) { return function (t) { return dates(t)[f] !== null } })(field)
    if (low === "no " + field + " date") return field === "happens"
      ? function (t) { var d = dates(t); return d.start === null && d.scheduled === null && d.due === null }
      : (function (f) { return function (t) { return dates(t)[f] === null } })(field)
    if (field !== "happens" && low === field + " date is invalid")
      return (function (f) { return function (t) { var d = dates(t)[f]; return d !== null && isNaN(d) } })(field)
    if (low.indexOf(kw + " ") !== 0) continue
    // claimed: from here on it's this date field or an error
    if (line.indexOf("<%") >= 0 || line.indexOf("YYYY-MM-DD") >= 0)
      throw new QueryError("Instruction contains unexpanded template text")
    var m = new RegExp("^" + kw + " (((?:on|in) or before|before|(?:on|in) or after|after|on|in)? ?(.*))", "i").exec(line)
    var key = m[2] ? m[2].toLowerCase() : "", range
    try { range = dateRange(m[3], ctx.today) }
    catch (e) {
      if (!(e instanceof Unsupported)) throw e
      try { var d1 = phraseDay(m[1], ctx.today); range = { start: d1, end: d1 } }
      catch (e2) { throw e }
    }
    var pred = function (d) {
      if (key === "before") return d < range.start
      if (key === "after") return d > range.end
      if (key === "on or before" || key === "in or before") return d <= range.end
      if (key === "on or after" || key === "in or after") return d >= range.start
      return d >= range.start && d <= range.end
    }
    if (field === "happens") return function (t) {
      var d = dates(t)
      return [d.start, d.scheduled, d.due].some(function (x) { return valid(x) && pred(x) })
    }
    return (function (f) {
      return function (t) {
        var d = dates(t)[f]
        if (d === null) return f === "start"           // no start date: matches every "starts" line
        return !isNaN(d) && pred(d)
      }
    })(field)
  }
  return null
}

function simpleFilter(line, ctx) {
  var low = line.toLowerCase(), m
  // status.name is a text field (below); status.type / done / not done:
  if (/^(?:status\.type)/i.test(line)) {
    m = /^(?:status\.type) (is|is not) ([^ ]+)$/i.exec(line)
    if (!m || STATUS_TYPES.indexOf(m[2].toUpperCase()) < 0) throw new QueryError("Invalid status.type instruction")
    var want = m[2].toUpperCase(), isNot = m[1].toLowerCase() === "is not"
    return function (t) { return (t.statusType === want) !== isNot }
  }
  if (low === "done") return isDone
  if (low === "not done") return function (t) { return !isDone(t) }
  if (low === "is recurring") return function (t) { return !!t.ruleText }
  if (low === "is not recurring") return function (t) { return !t.ruleText }
  m = /^priority(\s+is)?(\s+(above|below|not))?(\s+(lowest|low|none|medium|high|highest))$/i.exec(line)
  if (m) {
    var p = PRIO[m[5].toLowerCase()], mod = (m[3] || "").toLowerCase()
    return function (t) {
      var c = lc(prioCode(t), p)
      return mod === "above" ? c < 0 : mod === "below" ? c > 0 : mod === "not" ? prioCode(t) !== p : prioCode(t) === p
    }
  }
  var df = dateFilter(line, ctx)
  if (df) return df
  if (low === "has tag" || low === "has tags") return function (t) { return tagsOf(t, ctx.gf).length > 0 }
  if (low === "no tag" || low === "no tags") return function (t) { return tagsOf(t, ctx.gf).length === 0 }
  var tf = textFilter(line, ctx)
  if (tf) return tf
  if (low === "exclude sub-items") return function (t) {
    var ind = t.indentation || ""
    if (ind === "") return true
    return /^ ?$/.test(ind.slice(ind.lastIndexOf(">") + 1))
  }
  if (/^filter by function/i.test(line)) throw new QueryError("JavaScript is now disabled in Tasks queries by default.")
  if (low === "has id") return function (t) { return !!t.taskId }
  if (low === "no id") return function (t) { return !t.taskId }
  if (low === "has depends on") return function (t) { return (t.dependsOn || []).length > 0 }
  if (low === "no depends on") return function (t) { return (t.dependsOn || []).length === 0 }
  if (low === "is blocked") return function (t) { return blocked(t, ctx) }
  if (low === "is not blocked") return function (t) { return !blocked(t, ctx) }
  if (low === "is blocking") return function (t) { return blocking(t, ctx) }
  if (low === "is not blocking") return function (t) { return !blocking(t, ctx) }
  return null
}

function blocked(t, ctx) {
  if (isDone(t)) return false
  return (t.dependsOn || []).some(function (id) { return ctx.openIds[id] })
}
function blocking(t, ctx) {
  if (!t.taskId || isDone(t)) return false
  return !!ctx.openDeps[t.taskId]
}

// §2.6: (A) AND (B) OR NOT (C) ... with one delimiter pair per line.
var PAIRS = { "(": ")", "[": "]", "{": "}", "\"": "\"" }

function booleanFilter(line, ctx) {
  if (!/(.*(AND|OR|XOR|NOT)\s*[\(\[\{"].*|[\(\[\{"].+[\)\]\}"])/.test(line)) return null
  var fail = function (why) {
    throw new QueryError("Could not interpret the following instruction as a Boolean combination:\n    " + line + "\n\nThe problem is:\n    " + why)
  }
  var body = line.replace(/^[A-Z ]*\s*/, ""), open = body.charAt(0), close = PAIRS[open]
  if (!close || line.charAt(line.length - 1) !== close) fail("All filters in a Boolean instruction must be inside one of these pairs of delimiter characters: (...) or [...] or {...} or \"...\". Combinations of those delimiters are no longer supported.")
  // Tasks only splits where a closing delimiter meets an operator meets an
  // opening one (or NOT meets an opening one); with no such joint, everything
  // between the first opener and the last closer is one filter line, so
  // "(due today) and (done)" is the date filter "due today) and (done".
  var o = esc(open), c = esc(close)
  if (!new RegExp(c + "\\s*(?:AND|OR|AND +NOT|OR +NOT|XOR)\\s*" + o + "|NOT\\s*" + o).test(line)) {
    var whole = body.slice(1, body.length - 1).trim()
    var only = filterLine(whole, ctx, true)
    if (!only) fail("do not understand query: " + whole)
    return only
  }
  var s = line, i = 0
  function ws() { while (i < s.length && /\s/.test(s.charAt(i))) i++ }
  function word() { var m = /^(AND|OR|XOR|NOT)\b/.exec(s.slice(i)); return m ? m[1] : null }
  function group() {
    ws()
    if (s.charAt(i) !== open) fail("malformed Boolean expression")
    var depth = 0, start = i
    for (; i < s.length; i++) {
      var c = s.charAt(i)
      if (open === close) { if (c === open && i > start) { i++; break } continue }
      if (c === open) depth++
      else if (c === close && --depth === 0) { i++; break }
    }
    var inner = s.slice(start + 1, i - 1)
    if (open !== close && (inner.indexOf(open) >= 0)) {
      var sub = s, si = i
      s = inner; i = 0
      var e = orExpr()
      ws()
      if (i < s.length) fail("malformed Boolean expression")
      s = sub; i = si
      return e
    }
    var leaf = inner.trim()
    var f = filterLine(leaf, ctx, true)
    if (!f) fail("do not understand query: " + leaf)
    return f
  }
  function unary() { ws(); if (word() === "NOT") { i += 3; var g = unary(); return function (t) { return !g(t) } } return group() }
  function xorExpr() { var a = unary(); for (;;) { ws(); if (word() !== "XOR") return a; i += 3; var b = unary(), x = a; a = (function (p, q) { return function (t) { return p(t) !== q(t) } })(x, b) } }
  function andExpr() { var a = xorExpr(); for (;;) { ws(); if (word() !== "AND") return a; i += 3; var b = xorExpr(), x = a; a = (function (p, q) { return function (t) { return p(t) && q(t) } })(x, b) } }
  function orExpr() { var a = andExpr(); for (;;) { ws(); if (word() !== "OR") return a; i += 2; var b = andExpr(), x = a; a = (function (p, q) { return function (t) { return p(t) || q(t) } })(x, b) } }
  var e = orExpr()
  ws()
  if (i < s.length) fail("malformed Boolean expression")
  return e
}

function filterLine(line, ctx, leaf) {
  var f = simpleFilter(line, ctx)
  if (f || leaf) return f
  return booleanFilter(line, ctx)
}

// ---- §4 sorting -----------------------------------------------------------------

function cmpDate(a, b) {
  if (a === null || b === null) return a === b ? 0 : a === null ? 1 : -1
  if (isNaN(a) || isNaN(b)) return isNaN(a) && isNaN(b) ? 0 : isNaN(a) ? -1 : 1
  return a - b
}

function cleanDescription(t, gf) {
  var s = withoutGlobalFilter(t.description || "", gf)
  var m = /^\[\[?([^\]]*)]]?/.exec(s)
  if (m) { var inner = m[1], bar = inner.indexOf("|"); s = (bar >= 0 ? inner.slice(bar + 1) : inner) + s.slice(m[0].length) }
  ;[/^\*\*([^*]+)\*\*/, /^\*([^*]+)\*/, /^==([^=]+)==/, /^__([^_]+)__/, /^_([^_]+)_/].forEach(function (re) {
    var r = re.exec(s); if (r) s = r[1] + s.slice(r[0].length)
  })
  return s
}

function hash(s) {
  var h = 9
  for (var i = 0; i < s.length; ) h = Math.imul(h ^ s.charCodeAt(i++), Math.pow(9, 9))
  return h ^ (h >>> 9)
}

function sorterFor(name, ctx) {
  switch (name) {
  case "status.name": return function (a, b) { return lc(a.statusName || "", b.statusName || "") }
  case "status.type": return function (a, b) { return lc(TYPE_TEXT[a.statusType] || "", TYPE_TEXT[b.statusType] || "") }
  case "status": return function (a, b) { return (isDone(a) ? 1 : 0) - (isDone(b) ? 1 : 0) }
  case "recurring": return function (a, b) { return (a.ruleText ? 0 : 1) - (b.ruleText ? 0 : 1) }
  case "priority": return function (a, b) { return lc(prioCode(a), prioCode(b)) }
  case "happens": return function (a, b) { return cmpDate(happens(a), happens(b)) }
  case "path": return function (a, b) { return lc(a.file, b.file) }
  case "filename": return function (a, b) { return lc(filename(a), filename(b)) }
  case "heading": return function (a, b) { return lc(a.heading || "", b.heading || "") }
  case "id": return function (a, b) { return lc(a.taskId || "", b.taskId || "") }
  case "description": return function (a, b) { return lc(cleanDescription(a, ctx.gf), cleanDescription(b, ctx.gf)) }
  case "urgency": return function (a, b) { return urgency(b, ctx.today) - urgency(a, ctx.today) }
  case "random": return function (a, b) { var d = ymd(ctx.today); return hash(d + " " + a.description) - hash(d + " " + b.description) }
  }
  if (["cancelled", "created", "start", "scheduled", "due", "done"].indexOf(name) >= 0)
    return function (a, b) { return cmpDate(dates(a)[name], dates(b)[name]) }
  return null
}

var SORT_FIELDS = ["status.name", "status.type", "status", "recurring", "priority", "happens", "cancelled", "created",
                   "start", "scheduled", "due", "done", "path", "description", "tag", "heading", "filename", "urgency",
                   "function", "id", "random"]

function esc(s) { return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") }

function sortLine(line, ctx) {
  if (!/^sort by /i.test(line)) return null
  for (var i = 0; i < SORT_FIELDS.length; i++) {
    var f = SORT_FIELDS[i], m
    if (f === "tag") {
      m = /^sort by tag( reverse)?[\s]*(\d+)?/i.exec(line)
      if (!m) continue
      var n = m[2] ? +m[2] : 1
      // Has an n-th tag (compared) < has fewer tags < has none.
      var tier = function (t) { var k = tagsOf(t, ctx.gf).length; return k >= n ? 0 : k > 0 ? 1 : 2 }
      return { reverse: !!m[1], cmp: function (a, b) {
        var ka = tier(a), kb = tier(b)
        if (ka !== kb) return ka - kb
        return ka === 0 ? lc(tagsOf(a, ctx.gf)[n - 1], tagsOf(b, ctx.gf)[n - 1]) : 0
      } }
    }
    m = new RegExp("^sort by " + esc(f) + "( reverse)?", "i").exec(line)
    if (!m) continue
    if (f === "function") throw new QueryError("JavaScript is now disabled in Tasks queries by default.")
    return { reverse: !!m[1], cmp: sorterFor(f, ctx) }
  }
  return null
}

// ---- §5 grouping ----------------------------------------------------------------

var GROUP_FIELDS = ["status.name", "status.type", "status", "recurring", "priority", "happens", "cancelled", "created",
                    "start", "scheduled", "due", "done", "path", "folder", "root", "backlink", "tags", "heading",
                    "filename", "urgency", "recurrence", "id"]

function escGroup(s) { return s.replace(/\\/g, "\\\\").replace(/_/g, "\\_") }

function dateGroup(d, f) {
  if (d === null) return "No " + f + " date"
  if (isNaN(d)) return "%%0%% Invalid " + f + " date"
  return ymd(d) + " " + WEEKDAYS[dow(d)]
}

function groupNames(field, t, ctx) {
  switch (field) {
  case "status.name": return [t.statusName || ""]
  case "status.type": return [TYPE_TEXT[t.statusType] || ""]
  case "status": return [isDone(t) ? "Done" : "Todo"]
  case "recurring": return [t.ruleText ? "Recurring" : "Not Recurring"]
  case "priority": var c = +prioCode(t); return ["%%" + c + "%%" + PRIO_GROUP[c] + " priority"]
  case "happens": return [dateGroup(happens(t), "happens")]
  case "path": return [escGroup(t.file.replace(".md", ""))]
  case "folder": return [escGroup(folder(t))]
  case "root": return [escGroup(root(t))]
  case "filename": var fn = filename(t); return [fn ? "[[" + fn.replace(/\.md$/, "") + "]]" : "Unknown Location"]
  case "backlink":
    var b = filename(t).replace(/\.md$/, "")
    if (!b) return ["Unknown Location"]
    return [t.heading ? "[[" + b + "#" + t.heading + "|" + b + " > " + t.heading + "]]" : "[[" + b + "]]"]
  case "tags": var tg = tagsOf(t, ctx.gf); return tg.length ? tg : ["(No tags)"]
  case "heading": return [t.heading ? t.heading : "(No heading)"]
  case "urgency": return [urgency(t, ctx.today).toFixed(2)]
  case "recurrence": return [t.ruleText || "None"]
  case "id": return [t.taskId || ""]
  }
  return [dateGroup(dates(t)[field], field)]
}

function groupLine(line) {
  if (!/^group by /i.test(line)) return null
  if (/^group by function( reverse)? (.*)/i.test(line)) throw new QueryError("JavaScript is now disabled in Tasks queries by default.")
  for (var i = 0; i < GROUP_FIELDS.length; i++) {
    var m = new RegExp("^group by " + esc(GROUP_FIELDS[i]) + "( reverse)?$", "i").exec(line)
    if (m) return { field: GROUP_FIELDS[i], reverse: GROUP_FIELDS[i] === "urgency" ? !m[1] : !!m[1] }
  }
  return null
}

// ---- §3.2 display-only lines -------------------------------------------------------

var HIDE_OPTIONS = ["backlink", "edit button", "nested backlink", "postpone button", "task count", "group count",
                    "toolbar", "tree", "urgency", "cancelled date", "created date", "depends on", "done date",
                    "due date", "id", "on completion", "priority", "recurrence rule", "scheduled date", "start date", "tags"]

// ---- The query ---------------------------------------------------------------------

function parse(source, ctx) {
  var q = { filters: [], sorts: [], groups: [], limit: null, groupLimit: null, ignoreGlobal: false }
  function one(st, depth) {
    var line = st.text, m
    if (line.indexOf("{{") >= 0 && line.indexOf("}}") >= 0 && !/^#/.test(line)) {
      var prev = line, n = 0
      do { prev = line; line = expand(line, ctx) } while (line !== prev && ++n < 10)
      if (line !== st.text) {
        statements(line).forEach(function (s) { one({ text: s.text, raw: st.raw }, depth) })
        return
      }
    }
    if ((m = /^preset +(.*)/i.exec(line))) {
      var name = m[1].trim()
      if (ctx.presets[name] === undefined) throw new QueryError("Cannot find preset \"" + name + "\" in the Tasks settings")
      if (depth > 20) throw new QueryError("preset recursion")
      statements(ctx.presets[name]).forEach(function (s) { one(s, depth + 1) })
      return
    }
    if (/^short/i.test(line) || /^full/i.test(line) || /^explain/i.test(line)) return
    if (/^ignore global query/i.test(line)) { q.ignoreGlobal = true; return }
    if ((m = /^limit (groups )?(to )?(\d+)( tasks?)?/i.exec(line))) { if (m[1]) q.groupLimit = +m[3]; else q.limit = +m[3]; return }
    var s = sortLine(line, ctx)
    if (s) { q.sorts.push(s); return }
    var g = groupLine(line)
    if (g) { q.groups.push(g); return }
    if ((m = /^view +(.*)/i.exec(line))) {
      if (/^list$/i.test(m[1].trim())) return
      throw new Unsupported("the columns view")
    }
    if ((m = /^(hide|show) +(.*)/i.exec(line))) {
      var opt = m[2].toLowerCase()
      if (HIDE_OPTIONS.some(function (o) { return opt.indexOf(o) === 0 })) return
      throw new QueryError("do not understand hide/show option")
    }
    if (/^#.*/.test(line)) return
    var f = filterLine(line, ctx, false)
    if (!f) throw new QueryError("do not understand query")
    q.filters.push(f)
  }
  statements(source).forEach(function (st) {
    try { one(st, 0) }
    catch (e) {
      if (e instanceof QueryError) e.error += "\nProblem line: \"" + st.raw.trim() + "\""
      throw e
    }
  })
  return q
}

function evaluate(source, tasks, opts) {
  var settings = opts.settings || {}
  var ctx = { today: dayOf(opts.today), gf: settings.globalFilter || "", files: fileValues(opts.file || ""),
              presets: settings.presets || DEFAULT_PRESETS, openIds: {}, openDeps: {} }
  tasks.forEach(function (t) {
    if (isDone(t)) return
    if (t.taskId) ctx.openIds[t.taskId] = true
    ;(t.dependsOn || []).forEach(function (d) { ctx.openDeps[d] = true })
  })
  var q
  try {
    q = parse(source, ctx)
    var gq = settings.globalQuery || ""
    if (gq.trim() && !q.ignoreGlobal) q = parse(gq + "\n" + source, ctx)
  } catch (e) {
    if (e instanceof QueryError) return { error: e.error }
    if (e instanceof Unsupported) return { unsupported: e.unsupported }
    throw e
  }
  // Tasks' own order of the cache: file by file, top to bottom.
  var list = tasks.slice().sort(function (a, b) { return a.file < b.file ? -1 : a.file > b.file ? 1 : a.line - b.line })
  q.filters.forEach(function (f) { list = list.filter(f) })
  var sorters = q.sorts.concat(["status.type", "urgency", "due", "priority", "path"].map(function (n) {
    return { reverse: false, cmp: sorterFor(n, ctx) }
  }))
  list = list.map(function (t, i) { return { t: t, i: i } })
  list.sort(function (a, b) {
    for (var k = 0; k < sorters.length; k++) {
      var c = sorters[k].cmp(a.t, b.t)
      if (c) return sorters[k].reverse ? -c : c
    }
    return a.i - b.i
  })
  list = list.map(function (x) { return x.t })
  var total = list.length
  if (q.limit !== null) list = list.slice(0, q.limit)
  var groups
  if (!q.groups.length) groups = [{ names: [], tasks: list }]
  else {
    var byKey = {}, order = []
    list.forEach(function (t) {
      var paths = [[]]
      q.groups.forEach(function (g) {
        var names = groupNames(g.field, t, ctx), next = []
        paths.forEach(function (p) { names.forEach(function (n) { next.push(p.concat([n])) }) })
        paths = next
      })
      paths.forEach(function (p) {
        var k = JSON.stringify(p)
        if (!byKey[k]) { byKey[k] = { names: p, tasks: [] }; order.push(k) }
        byKey[k].tasks.push(t)
      })
    })
    groups = order.map(function (k) { return byKey[k] })
    groups.sort(function (a, b) {
      for (var l = 0; l < q.groups.length; l++) {
        var c = lc(a.names[l], b.names[l])
        if (c) return q.groups[l].reverse ? -c : c
      }
      return 0
    })
    if (q.groupLimit !== null)
      groups.forEach(function (g) { g.tasks = g.tasks.slice(0, q.groupLimit) })   // the total stays as it was
  }
  return { total: total, groups: groups }
}

// A group name as shown: Tasks' hidden %%…%% ordering prefixes removed.
function displayName(name) { return String(name).replace(/%%.*?%%/g, "").trim() }
