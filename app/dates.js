.pragma library

// Reads dates and times the way people type them, into TaskNotes' formats:
// "YYYY-MM-DD" or "YYYY-MM-DDTHH:mm" (local time). UK conventions: 1/2/27 is
// 1 February. Pure: everything takes `now` (a Date) so it's testable.
//
//   parse(text, now, opts) -> { value, date, time, pretty } | { error } | { clear: true }
//   opts: { defaultTime: "09:00", useDefaultTime: true }

var MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
var MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
var DAYS = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"]
var DAY_NAMES = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
var NAMED_TIMES = { noon: "12:00", midday: "12:00", midnight: "00:00", morning: "09:00", afternoon: "14:00",
                    evening: "18:00", tonight: "20:00", eod: "17:00" }

function pad(n) { return (n < 10 ? "0" : "") + n }
function ymd(d) { return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate()) }
function hm(d) { return pad(d.getHours()) + ":" + pad(d.getMinutes()) }
function day0(d) { return new Date(d.getFullYear(), d.getMonth(), d.getDate()) }
function addDays(d, n) { return new Date(d.getFullYear(), d.getMonth(), d.getDate() + n) }
function validDate(y, m, d) { var x = new Date(y, m, d); return x.getFullYear() === y && x.getMonth() === m && x.getDate() === d ? x : null }

// "jan", "janu", "january", "sept" -> 0..11
function monthIndex(word) {
  var w = String(word || "").toLowerCase()
  if (w.length < 3) return -1
  if (w === "sept") return 8
  for (var i = 0; i < 12; i++) if (MONTH_NAMES[i].toLowerCase().indexOf(w) === 0) return i
  return -1
}
function dayIndex(word) {
  if (!word) return -1
  var w = word.toLowerCase()
  for (var i = 0; i < 7; i++) {
    var full = DAY_NAMES[i].toLowerCase()
    if (w === full || w === DAYS[i] || (w.length >= 3 && full.indexOf(w) === 0)) return i
  }
  return -1
}

// "3pm", "15:30", "9", "9.30am", "noon" -> "HH:MM" (or null)
function readTime(s, loose) {
  s = s.trim()
  if (NAMED_TIMES[s]) return NAMED_TIMES[s]
  var m = s.match(/^(\d{1,2})(?:[:.](\d{2}))?\s*(am|pm|a|p)?$/)
  if (!m) return null
  var h = Number(m[1]), mi = Number(m[2] || 0), ap = m[3]
  if (!ap && !m[2] && !loose) return null       // a bare "9" is a time only after "at"
  if (mi > 59) return null
  if (ap) {
    if (h < 1 || h > 12) return null
    if (ap[0] === "p" && h !== 12) h += 12
    if (ap[0] === "a" && h === 12) h = 0
  } else if (h > 23) return null
  return pad(h) + ":" + pad(mi)
}

var UNIT = { m: "m", min: "m", mins: "m", minute: "m", minutes: "m", h: "h", hr: "h", hrs: "h", hour: "h", hours: "h",
             d: "d", day: "d", days: "d", w: "w", wk: "w", wks: "w", week: "w", weeks: "w",
             mo: "mo", mon: "mo", month: "mo", months: "mo", y: "y", yr: "y", year: "y", years: "y" }

// "+10m", "in 2 hours", "-3d", "in a week"
function readOffset(s, now) {
  var m = s.match(/^(?:([+-])\s*|in\s+)(\d+|a|an|one|two|three)\s*([a-z]+)$/)
  if (!m) return null
  var u = UNIT[m[3]]
  if (!u) return null
  var n = { a: 1, an: 1, one: 1, two: 2, three: 3 }[m[2]] || Number(m[2])
  if (m[1] === "-") n = -n
  if (u === "m" || u === "h") {
    var t = new Date(now.getTime() + n * (u === "m" ? 60000 : 3600000))
    t.setSeconds(0, 0)
    return { date: ymd(t), time: hm(t), exact: true }
  }
  var d = day0(now)
  if (u === "d") d = addDays(d, n)
  else if (u === "w") d = addDays(d, 7 * n)
  else if (u === "mo" || u === "y") {
    // Same day of the month, clamped (31 Jan + 1 month = 28/29 Feb).
    var months = u === "mo" ? n : 12 * n
    var last = new Date(d.getFullYear(), d.getMonth() + months + 1, 0).getDate()
    d = new Date(d.getFullYear(), d.getMonth() + months, Math.min(d.getDate(), last))
  }
  return { date: ymd(d), time: null }
}

// The date part, with any time already removed.
function readDate(s, now) {
  var today = day0(now)
  s = s.replace(/\s+/g, " ").trim()
  if (s === "") return { date: null }
  if (s === "today" || s === "tod" || s === "now") return { date: ymd(today) }
  if (/^(tomorrow|tmrw|tmr|tom)$/.test(s)) return { date: ymd(addDays(today, 1)) }
  if (s === "yesterday") return { date: ymd(addDays(today, -1)) }
  if (s === "next week") return { date: ymd(addDays(today, ((8 - today.getDay()) % 7) || 7)) }   // next Monday
  if (/^(this )?weekend$/.test(s)) return { date: ymd(addDays(today, (6 - today.getDay() + 7) % 7)) }
  if (/^(end of (the )?week|eow)$/.test(s)) return { date: ymd(addDays(today, (5 - today.getDay() + 7) % 7)) }
  if (/^(end of (the )?month|eom)$/.test(s)) return { date: ymd(new Date(today.getFullYear(), today.getMonth() + 1, 0)) }
  if (/^(next month|start of next month)$/.test(s)) return { date: ymd(new Date(today.getFullYear(), today.getMonth() + 1, 1)) }
  if (/^(end of (the )?year|eoy)$/.test(s)) return { date: ymd(new Date(today.getFullYear(), 11, 31)) }

  var m = s.match(/^(next |this )?([a-z]+)$/)
  if (m && dayIndex(m[2]) >= 0) {
    // "fri" = the coming Friday (today counts); "next fri" = a week after that.
    var delta = (dayIndex(m[2]) - today.getDay() + 7) % 7
    if (m[1] === "next ") delta += 7
    return { date: ymd(addDays(today, delta)) }
  }

  // "Thu 15 Oct" (as the boxes display it): a weekday in front of a date.
  m = s.match(/^([a-z]+),? (.*\d.*)$/)
  if (m && dayIndex(m[1]) >= 0) {
    var r = readDate(m[2], now)
    if (r.date && !/\d{4}/.test(m[2])) {
      // No year given: prefer the nearby year where that date IS that weekday.
      var want = dayIndex(m[1]), md = r.date.slice(4)
      for (var dy = -1; dy <= 1; dy++) {
        var parts = (String(now.getFullYear() + dy) + md).split("-")
        var c = validDate(+parts[0], +parts[1] - 1, +parts[2])
        if (c && c.getDay() === want && Math.abs(c - day0(now)) < 200 * 86400000) return { date: ymd(c) }
      }
    }
    return r
  }

  // ISO
  m = s.match(/^(\d{4})-(\d{1,2})-(\d{1,2})$/)
  if (m) { var iso = validDate(+m[1], +m[2] - 1, +m[3]); return iso ? { date: ymd(iso) } : { error: "no such date" } }

  // UK numeric: d/m, d/m/yy, d/m/yyyy (also . and -)
  m = s.match(/^(\d{1,2})[\/.-](\d{1,2})(?:[\/.-](\d{2}|\d{4}))?$/)
  if (m) return withYear(+m[1], +m[2] - 1, m[3], today)

  // "1 jan [2027]", "jan 1 [2027]", "1st of january", "january 1st, 2027"
  var t = s.replace(/(\d+)(st|nd|rd|th)\b/g, "$1").replace(/\bof\b/g, " ").replace(/,/g, " ").replace(/\s+/g, " ").trim()
  m = t.match(/^(\d{1,2}) ([a-z]+)(?: (\d{4}|\d{2}))?$/)
  if (m && monthIndex(m[2]) >= 0) return withYear(+m[1], monthIndex(m[2]), m[3], today)
  m = t.match(/^([a-z]+) (\d{1,2})(?: (\d{4}|\d{2}))?$/)
  if (m && monthIndex(m[1]) >= 0) return withYear(+m[2], monthIndex(m[1]), m[3], today)
  // "the 15th" / "15th": next time that day of the month comes round
  m = s.match(/^(?:the )?(\d{1,2})(st|nd|rd|th)$/)
  if (m) {
    for (var k = 0; k < 13; k++) {
      var c = validDate(today.getFullYear(), today.getMonth() + k, +m[1])
      if (c && c >= today) return { date: ymd(c) }
    }
  }
  return { error: "didn't understand \"" + s + "\"" }
}

// Without a year: the next time that day comes round (today counts).
function withYear(d, mo, y, today) {
  if (y) {
    var yy = y.length === 2 ? 2000 + Number(y) : Number(y)
    var x = validDate(yy, mo, d)
    return x ? { date: ymd(x) } : { error: "no such date" }
  }
  var cand = validDate(today.getFullYear(), mo, d)
  if (cand && cand < today) cand = validDate(today.getFullYear() + 1, mo, d)
  return cand ? { date: ymd(cand) } : { error: "no such date" }
}

function parse(text, now, opts) {
  opts = opts || {}
  var s = String(text || "").toLowerCase().trim()
  if (s === "" || s === "none" || s === "clear") return { clear: true }
  // The long display form: "Today, Wed 7 Oct, 09:30" -> "wed 7 oct 09:30"
  s = s.replace(/,/g, " ").replace(/\s+/g, " ").trim()
  s = s.replace(/^(today|tomorrow|yesterday) (?=[a-z]+ \d)/, "")

  var off = readOffset(s, now)
  if (off) return finish(off.date, off.time, now, opts, !!off.exact)

  var allDay = false
  s = s.replace(/\b(all ?day|no time|anytime)\b/, function () { allDay = true; return " " })

  // Peel a time off the end or the start ("fri 9am", "at 3pm tomorrow", "tomorrow at noon").
  var time = null
  var tm = s.match(/(?:^|\s)(?:at|@)\s*(\d{1,2}(?:[:.]\d{2})?\s*(?:am|pm|a|p)?|noon|midday|midnight)\s*$/)
  if (tm) { time = readTime(tm[1], true); s = s.slice(0, tm.index) }
  if (!time) {
    tm = s.match(/(?:^|\s)(\d{1,2}(?:[:.]\d{2})\s*(?:am|pm)?|\d{1,2}\s*(?:am|pm)|noon|midday|midnight|morning|afternoon|evening|tonight|eod)\s*$/)
    if (tm) { time = readTime(tm[1], false); if (time) s = s.slice(0, tm.index) }
  }
  if (!time) {
    tm = s.match(/^(?:at\s+|@\s*)?(\d{1,2}(?:[:.]\d{2})\s*(?:am|pm)?|\d{1,2}\s*(?:am|pm)|noon|midday|midnight|morning|afternoon|evening|tonight)(?:\s+|$)/)
    if (tm) { time = readTime(tm[1], false); if (time) s = s.slice(tm[0].length) }
  }
  s = s.replace(/^\s*(on|at|@)\s+/, "").replace(/\s+(at|on)\s*$/, "").trim()

  // An offset with a time: "+1week at 1pm", "in 3 days 9am".
  var off2 = s ? readOffset(s, now) : null
  if (off2 && !off2.exact) {
    if (allDay) time = null
    return finish(off2.date, time, now, opts, allDay)
  }

  var d = readDate(s, now)
  if (d.error) return { error: d.error }
  var date = d.date
  if (!date) {
    if (!time) return { error: "give a date or a time" }
    // Just a time: today if it's still ahead, otherwise tomorrow.
    var t = time.split(":")
    var at = new Date(now.getFullYear(), now.getMonth(), now.getDate(), +t[0], +t[1])
    date = ymd(at > now ? at : addDays(day0(now), 1))
  }
  if (allDay) time = null
  return finish(date, time, now, opts, allDay)
}

function finish(date, time, now, opts, noDefault) {
  if (!time && !noDefault && opts.useDefaultTime && opts.defaultTime) time = opts.defaultTime
  var value = time ? date + "T" + time : date
  return { value: value, date: date, time: time, pretty: pretty(value, now) }
}

function pretty(value, now) {
  if (!value) return ""
  var p = value.split("T")
  var a = p[0].split("-")
  var d = new Date(+a[0], +a[1] - 1, +a[2])
  var today = day0(now)
  var diff = Math.round((d - today) / 86400000)
  var label = diff === 0 ? "Today" : diff === 1 ? "Tomorrow" : diff === -1 ? "Yesterday" : ""
  var s = DAY_NAMES[d.getDay()].slice(0, 3) + " " + d.getDate() + " " + MONTH_NAMES[d.getMonth()].slice(0, 3)
  if (d.getFullYear() !== today.getFullYear()) s += " " + d.getFullYear()
  if (label) s = label + ", " + s
  return s + (p[1] ? ", " + p[1].slice(0, 5) : "")
}

// Short form for input boxes: "Tomorrow 09:30", "Thu 15 Oct 09:30", "1 Jan 2027".
function compact(value, now) {
  if (!value) return ""
  var p = value.split("T"), a = p[0].split("-")
  var d = new Date(+a[0], +a[1] - 1, +a[2])
  var diff = Math.round((d - day0(now)) / 86400000)
  var s = diff === 0 ? "Today" : diff === 1 ? "Tomorrow" : diff === -1 ? "Yesterday"
        : (d.getFullYear() !== now.getFullYear() ? d.getDate() + " " + MONTH_NAMES[d.getMonth()].slice(0, 3) + " " + d.getFullYear()
           : DAY_NAMES[d.getDay()].slice(0, 3) + " " + d.getDate() + " " + MONTH_NAMES[d.getMonth()].slice(0, 3))
  return s + (p[1] ? " " + p[1].slice(0, 5) : "")
}
