.pragma library

// Evaluator for Obsidian Bases expressions, as compiled by
// core/omaforge/bases.py into small JSON trees. Semantics follow Obsidian's
// own engine, checked against `obsidian base:query` (tools/basestest.py):
// dates are local, `today()` is local midnight, durations are strings like
// "7 days", `format()` uses moment tokens, and "[[Note]]" strings behave as
// links.

var DAY = 86400000

function isDate(v) { return v !== null && typeof v === "object" && v.__date === true }
function isLink(v) { return v !== null && typeof v === "object" && v.__link === true }
function isFile(v) { return v !== null && typeof v === "object" && v.__file === true }
function mkDate(t, time) { return { __date: true, t: t, time: !!time } }

function parseDate(v) {
  if (v === null || v === undefined || v === "") return null
  if (isDate(v)) return v
  if (typeof v === "number") return mkDate(v, true)
  var s = String(v).trim()
  var m = s.match(/^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d+))?)?)?(Z|[+-]\d{2}:?\d{2})?$/)
  if (!m) return null
  if (m[8]) { var t = Date.parse(s.replace(" ", "T")); return isNaN(t) ? null : mkDate(t, true) }
  var d = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]), Number(m[4] || 0), Number(m[5] || 0), Number(m[6] || 0))
  return mkDate(d.getTime(), m[4] !== undefined)
}

function midnight(t) { var d = new Date(t); return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime() }

function linkTarget(v) {
  var s
  if (isLink(v)) s = v.path
  else if (isFile(v)) s = v.task.path
  else s = String(v)
  var m = s.match(/^\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|[^\]]*)?\]\]$/)
  if (m) s = m[1]
  s = s.replace(/\.md$/, "")
  var slash = s.lastIndexOf("/")
  return s.slice(slash + 1).toLowerCase()
}
function looksLikeLink(v) { return typeof v === "string" && /^\[\[[^\]]+\]\]$/.test(v) }

function truthy(v) {
  if (v === null || v === undefined || v === false || v === 0 || v === "") return false
  if (Array.isArray(v)) return v.length > 0
  return true
}

function eq(a, b) {
  if (a === undefined) a = null
  if (b === undefined) b = null
  if (isDate(a) || isDate(b)) {
    // Obsidian: equality is by calendar day when either side has no time
    // (date("…T09:30") == today() is true), but < and > use the instant.
    var da = parseDate(a), db = parseDate(b)
    if (!da || !db) return false
    if (!da.time || !db.time) return midnight(da.t) === midnight(db.t)
    return da.t === db.t
  }
  if (isLink(a) || isLink(b) || isFile(a) || isFile(b) || (looksLikeLink(a) && looksLikeLink(b))) {
    if (a === null || b === null) return a === b
    return linkTarget(a) === linkTarget(b)
  }
  if (Array.isArray(a) && Array.isArray(b))
    return a.length === b.length && a.every(function (x, i) { return eq(x, b[i]) })
  return a === b
}

function cmp(a, b) {
  if (isDate(a) || isDate(b)) {
    var da = parseDate(a), db = parseDate(b)
    if (!da || !db) return null
    return da.t < db.t ? -1 : da.t > db.t ? 1 : 0
  }
  if (a === null || a === undefined || b === null || b === undefined) return null
  if (typeof a === "number" && typeof b === "number") return a < b ? -1 : a > b ? 1 : 0
  var sa = String(a), sb = String(b)
  return sa < sb ? -1 : sa > sb ? 1 : 0
}

var UNITS = { y: "y", yr: "y", year: "y", years: "y", M: "M", month: "M", months: "M", w: "w", week: "w", weeks: "w",
              d: "d", day: "d", days: "d", h: "h", hour: "h", hours: "h", m: "m", min: "m", minute: "m", minutes: "m",
              s: "s", sec: "s", second: "s", seconds: "s" }
function parseDuration(s) {
  if (typeof s !== "string") return null
  var m = s.trim().match(/^([+-]?\d+(?:\.\d+)?)\s*([A-Za-z]+)$/)
  if (!m) return null
  var u = UNITS[m[2]] || UNITS[m[2].toLowerCase()]
  return u ? { n: Number(m[1]), u: u } : null
}
function addDuration(d, dur, sign) {
  var n = dur.n * sign, x = new Date(d.t)
  if (dur.u === "y") x.setFullYear(x.getFullYear() + n)
  else if (dur.u === "M") x.setMonth(x.getMonth() + n)
  else if (dur.u === "w") x.setDate(x.getDate() + 7 * n)
  else if (dur.u === "d") x.setDate(x.getDate() + n)
  else return mkDate(d.t + n * { h: 3600000, m: 60000, s: 1000 }[dur.u], true)
  return mkDate(x.getTime(), d.time)
}

var DAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
var MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
function pad(n, w) { var s = String(n); while (s.length < w) s = "0" + s; return s }
// moment.js tokens, as Obsidian uses them (so "yyyy-MM-dd" gives "2026-10-Tu").
function formatDate(d, fmt) {
  var x = new Date(d.t)
  var map = {
    YYYY: pad(x.getFullYear(), 4), yyyy: pad(x.getFullYear(), 4), YY: pad(x.getFullYear() % 100, 2),
    MMMM: MONTHS[x.getMonth()], MMM: MONTHS[x.getMonth()].slice(0, 3), MM: pad(x.getMonth() + 1, 2), M: String(x.getMonth() + 1),
    DD: pad(x.getDate(), 2), D: String(x.getDate()),
    dddd: DAYS[x.getDay()], ddd: DAYS[x.getDay()].slice(0, 3), dd: DAYS[x.getDay()].slice(0, 2), d: String(x.getDay()),
    HH: pad(x.getHours(), 2), H: String(x.getHours()), mm: pad(x.getMinutes(), 2), m: String(x.getMinutes()),
    ss: pad(x.getSeconds(), 2), s: String(x.getSeconds())
  }
  return String(fmt).replace(/\[([^\]]*)\]|YYYY|yyyy|YY|MMMM|MMM|MM|M|DD|D|dddd|ddd|dd|d|HH|H|mm|m|ss|s/g,
                             function (tok, lit) { return lit !== undefined ? lit : map[tok] })
}

function toList(v) { return v === null || v === undefined ? [] : Array.isArray(v) ? v : [v] }

function tagList(task) {
  var raw = task.props ? task.props.tags : null
  var out = []
  toList(raw).forEach(function (t) { if (t !== null && t !== undefined) out.push(String(t).trim().replace(/^#/, "").replace(/\s+/g, "-").toLowerCase()) })
  return out
}
function hasTag(task, want) {
  want = String(want).replace(/^#/, "").toLowerCase()
  return tagList(task).some(function (t) { return t === want || t.indexOf(want + "/") === 0 })
}

function fileObj(task) { return { __file: true, task: task } }

function fileField(task, name, ctx) {
  var p = task.path
  var base = p.slice(p.lastIndexOf("/") + 1)
  switch (name) {
  case "name": return base
  case "basename": return base.replace(/\.md$/, "")
  case "path": return p
  case "folder": return p.lastIndexOf("/") < 0 ? "" : p.slice(0, p.lastIndexOf("/"))
  case "ext": return "md"
  case "tags": return tagList(task).map(function (t) { return "#" + t })
  case "properties": return task.props || {}
  case "mtime": return task.mtime ? mkDate(task.mtime, true) : null
  case "ctime": return task.ctime ? mkDate(task.ctime, true) : null
  }
  return null
}

function get(obj, name, ctx) {
  if (obj === null || obj === undefined) return null
  if (isFile(obj)) return fileField(obj.task, name, ctx)
  if (isDate(obj)) {
    var x = new Date(obj.t)
    return { year: x.getFullYear(), month: x.getMonth() + 1, day: x.getDate(), hour: x.getHours(),
             minute: x.getMinutes(), second: x.getSeconds() }[name]
  }
  if (isLink(obj)) {
    if (name === "path") return obj.path
    return null
  }
  if (typeof obj === "object" && !Array.isArray(obj)) {
    var v = obj[name]
    return v === undefined ? null : v
  }
  return null
}

function resolveFile(v, ctx) {
  if (v === null || v === undefined) return null
  if (isFile(v)) return v
  var key = linkTarget(v)
  var t = ctx.byName[key]
  return t ? fileObj(t) : null
}

function call(name, args, ctx, scope) {
  var a = function (i) { return ev(args[i], ctx, scope) }
  switch (name) {
  case "if": return truthy(a(0)) ? a(1) : (args.length > 2 ? a(2) : null)
  case "date": return parseDate(a(0))
  case "today": return mkDate(midnight(ctx.now), false)
  case "now": return mkDate(ctx.now, true)
  case "list": { var lv = a(0); return lv === null || lv === undefined ? null : toList(lv) }
  case "link": return { __link: true, path: String(a(0)) }
  case "number": {
    var v = a(0)
    if (v === null || v === undefined) return null     // Obsidian: number(null) is null, not 0
    if (isDate(v)) return v.t
    if (typeof v === "boolean") return v ? 1 : 0
    var n = Number(v); return isNaN(n) ? null : n
  }
  case "string": { var s = a(0); return s === null ? "" : isDate(s) ? formatDate(s, "YYYY-MM-DD") : String(s) }
  case "min": case "max": {
    // As Obsidian: any empty argument makes the result empty (so
    // max(0, 10 - <no date>) is null, not 0); text is a type error.
    var nums = args.map(function (x) { return ev(x, ctx, scope) })
    if (!nums.length || nums.some(function (x) { return x === null || x === undefined })) return null
    if (nums.some(function (x) { return typeof x !== "number" })) throw new Error("Type error in \"" + name + "\": expected numbers")
    return Math[name].apply(null, nums)
  }
  case "file": return resolveFile(a(0), ctx)
  case "file.hasTag": return args.some(function (x) { return hasTag(ctx.task, ev(x, ctx, scope)) })
  case "file.hasProperty": { var k = a(0); return !!ctx.task.props && ctx.task.props[k] !== undefined }
  case "file.inFolder": { var f = String(a(0)).replace(/\/$/, ""); return ctx.task.path.indexOf(f + "/") === 0 }
  case "file.asLink": return { __link: true, path: ctx.task.path }
  }
  throw new Error("unsupported function " + name)
}

function method(name, obj, args, ctx, scope) {
  var a = function (i) { return ev(args[i], ctx, scope) }
  // Null propagates through methods (null.contains(x) is null, not false),
  // except the emptiness tests.
  if ((obj === null || obj === undefined) && name !== "isEmpty" && name !== "isTruthy" && name !== "toString") return null
  function lambda(i, extra) { return function (value, index, acc) { return ev(args[i], ctx, Object.assign({}, scope, { value: value, index: index, acc: acc }, extra || {})) } }
  switch (name) {
  case "isEmpty":
    if (obj === null || obj === undefined || obj === "") return true
    if (Array.isArray(obj)) return obj.length === 0
    if (typeof obj === "object" && !isDate(obj) && !isLink(obj) && !isFile(obj)) return Object.keys(obj).length === 0
    return false
  case "isTruthy": return truthy(obj)
  case "contains":
    if (Array.isArray(obj)) { var x = a(0); return obj.some(function (o) { return eq(o, x) }) }
    if (obj === null || obj === undefined) return false
    return String(obj).indexOf(String(a(0))) >= 0
  case "containsAny": case "containsAll": {
    var vals = args.map(function (x) { return ev(x, ctx, scope) })
    var has = function (v) { return Array.isArray(obj) ? obj.some(function (o) { return eq(o, v) }) : String(obj).indexOf(String(v)) >= 0 }
    return name === "containsAny" ? vals.some(has) : vals.every(has)
  }
  case "date": { var d = parseDate(obj); return d ? mkDate(midnight(d.t), false) : null }
  case "format": { var d2 = parseDate(obj); return d2 ? formatDate(d2, a(0)) : null }
  case "floor": case "round": case "ceil": case "abs": return typeof obj === "number" ? Math[name](obj) : null
  case "lower": return obj === null ? null : String(obj).toLowerCase()
  case "upper": return obj === null ? null : String(obj).toUpperCase()
  case "trim": return obj === null ? null : String(obj).trim()
  case "startsWith": return obj !== null && String(obj).indexOf(String(a(0))) === 0
  case "endsWith": { if (obj === null) return false; var s = String(obj), e = String(a(0)); return s.slice(s.length - e.length) === e }
  case "toString": return obj === null ? "" : isDate(obj) ? formatDate(obj, "YYYY-MM-DD") : String(obj)
  case "length": return Array.isArray(obj) || typeof obj === "string" ? obj.length : 0
  case "filter": return toList(obj).filter(function (v, i) { return truthy(lambda(0)(v, i)) })
  case "map": return toList(obj).map(function (v, i) { return lambda(0)(v, i) })
  case "reduce": { var acc = args.length > 1 ? a(1) : null; toList(obj).forEach(function (v, i) { acc = lambda(0)(v, i, acc) }); return acc }
  case "join": return toList(obj).map(function (v) { return v === null ? "" : String(v) }).join(args.length ? a(0) : ",")
  case "slice": return toList(obj).slice(a(0), args.length > 1 ? a(1) : undefined)
  case "unique": { var out = []; toList(obj).forEach(function (v) { if (!out.some(function (o) { return eq(o, v) })) out.push(v) }); return out }
  case "sort": return toList(obj).slice().sort(function (x, y) { return cmp(x, y) || 0 })
  case "reverse": return toList(obj).slice().reverse()
  case "flat": return [].concat.apply([], toList(obj).map(toList))
  }
  throw new Error("unsupported method ." + name)
}

function arith(op, x, y) {
  if (op === "+" || op === "-") {
    var sign = op === "+" ? 1 : -1
    if (isDate(x)) {
      var dur = parseDuration(y)
      if (dur) return addDuration(x, dur, sign)
      if (typeof y === "number") return mkDate(x.t + sign * y, x.time)
      if (op === "-" && isDate(parseDate(y))) return x.t - parseDate(y).t
      return null
    }
    if (op === "+" && (typeof x === "string" || typeof y === "string")) return (x === null ? "" : String(x)) + (y === null ? "" : String(y))
    if (typeof x === "number" && typeof y === "number") return x + sign * y
    return null
  }
  if (typeof x !== "number" || typeof y !== "number") return null
  if (op === "*") return x * y
  if (op === "/") return y === 0 ? null : x / y
  if (op === "%") return y === 0 ? null : x % y
  return null
}

function ev(n, ctx, scope) {
  switch (n[0]) {
  case "lit": return n[1]
  case "arr": return n[1].map(function (x) { return ev(x, ctx, scope) })
  case "prop": { var p = ctx.task.props ? ctx.task.props[n[1]] : undefined; return p === undefined ? null : p }
  case "var": return scope && scope[n[1]] !== undefined ? scope[n[1]] : null
  case "file": return fileField(ctx.task, n[1], ctx)
  case "fn": return call(n[1], n[2], ctx, scope)
  case "m": return method(n[1], ev(n[2], ctx, scope), n[3], ctx, scope)
  case "get": return get(ev(n[1], ctx, scope), n[2], ctx)
  case "idx": {
    var o = ev(n[1], ctx, scope), k = ev(n[2], ctx, scope)
    if (Array.isArray(o)) { var v = o[k]; return v === undefined ? null : v }
    return get(o, String(k), ctx)
  }
  case "un": {
    var x = ev(n[2], ctx, scope)
    // Obsidian: !null is null (so `!due` matches nothing when due is unset).
    if (x === null || x === undefined) return null
    return n[1] === "!" ? !truthy(x) : (typeof x === "number" ? -x : null)
  }
  case "bin": {
    var op = n[1]
    if (op === "&&") return truthy(ev(n[2], ctx, scope)) && truthy(ev(n[3], ctx, scope))
    if (op === "||") return truthy(ev(n[2], ctx, scope)) || truthy(ev(n[3], ctx, scope))
    var a = ev(n[2], ctx, scope), b = ev(n[3], ctx, scope)
    if (op === "==") return eq(a, b)
    if (op === "!=") return !eq(a, b)
    if (op === "<" || op === "<=" || op === ">" || op === ">=") {
      var c = cmp(a, b)
      if (c === null) return false
      return op === "<" ? c < 0 : op === "<=" ? c <= 0 : op === ">" ? c > 0 : c >= 0
    }
    return arith(op, a, b)
  }
  case "and": return n[1].every(function (x) { return truthy(ev(x, ctx, scope)) })
  case "or": return n[1].some(function (x) { return truthy(ev(x, ctx, scope)) })
  case "not": return !n[1].some(function (x) { return truthy(ev(x, ctx, scope)) })
  }
  throw new Error("unknown node " + n[0])
}

// Public API -------------------------------------------------------------------

function index(tasks) {
  var byName = {}
  for (var p in tasks) {
    var t = tasks[p]
    var base = p.slice(p.lastIndexOf("/") + 1).replace(/\.md$/, "").toLowerCase()
    if (!byName[base]) byName[base] = t
    byName[p.replace(/\.md$/, "").toLowerCase()] = t
  }
  return byName
}

function context(task, byName, now) { return { task: task, byName: byName, now: now } }

// Does `task` pass the view's filter? Errors count as "no" (and are reported).
function matches(view, task, byName, now) {
  try { return truthy(ev(view.filter, context(task, byName, now), {})) }
  catch (e) { return false }
}

function value(ast, task, byName, now) {
  try { return ev(ast, context(task, byName, now), {}) } catch (e) { return null }
}

function sortValue(v) {
  if (isDate(v)) return v.t
  if (isLink(v) || isFile(v)) return linkTarget(v)
  if (Array.isArray(v)) return v.map(function (x) { return String(x) }).join(", ")
  return v
}

function compareValues(a, b) {
  var na = a === null || a === undefined || a === "", nb = b === null || b === undefined || b === ""
  if (na || nb) return na === nb ? 0 : na ? 1 : -1   // empty last
  if (typeof a === "number" && typeof b === "number") return a - b
  return String(a).localeCompare(String(b), undefined, { numeric: true, sensitivity: "base" })
}

function label(v) {
  if (v === null || v === undefined || v === "" || (Array.isArray(v) && !v.length)) return ""
  if (isDate(v)) return formatDate(v, v.time ? "YYYY-MM-DD HH:mm" : "YYYY-MM-DD")
  if (isLink(v) || isFile(v)) return linkTarget(v)
  if (Array.isArray(v)) return v.map(label).join(", ")
  if (looksLikeLink(v)) return v.slice(2, -2)
  return String(v)
}
