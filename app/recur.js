.pragma library
.import "dates.js" as D

// Reads repeat rules the way people say them into an RRULE body (without
// DTSTART: the core adds that, as TaskNotes does):
//   "every weekday", "every 2 weeks on fri", "monthly on the 1st",
//   "every last friday", "every year on 1 jan", "daily until 1 jan", ...
//   parse(text, now) -> { rule, text } | { error } | { clear: true }

var DAY = { mo: "MO", tu: "TU", we: "WE", th: "TH", fr: "FR", sa: "SA", su: "SU" }
var DAY_NAMES = { MO: "Monday", TU: "Tuesday", WE: "Wednesday", TH: "Thursday", FR: "Friday", SA: "Saturday", SU: "Sunday" }
var ORD = { first: 1, "1st": 1, second: 2, "2nd": 2, third: 3, "3rd": 3, fourth: 4, "4th": 4, last: -1 }
var NUM = { a: 1, an: 1, one: 1, two: 2, other: 2, three: 3, four: 4, five: 5, six: 6 }
var MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]

function dayCode(w) {
  w = String(w || "").toLowerCase().replace(/s$/, "")
  if (w.length < 2) return null
  for (var k in DAY) {
    var full = DAY_NAMES[DAY[k]].toLowerCase()
    if (full.indexOf(w) === 0 || w === k) return DAY[k]
  }
  if (w === "thur" || w === "thurs") return "TH"
  if (w === "tue" || w === "tues") return "TU"
  return null
}
function dayList(s) {
  var parts = s.split(/\s*(?:,|\band\b|&|\+)\s*/).filter(function (x) { return x })
  var out = []
  for (var i = 0; i < parts.length; i++) {
    var c = dayCode(parts[i].trim())
    if (!c) return null
    if (out.indexOf(c) < 0) out.push(c)
  }
  var order = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]
  out.sort(function (a, b) { return order.indexOf(a) - order.indexOf(b) })
  return out.length ? out : null
}
function monthIndex(w) {
  w = String(w || "").toLowerCase()
  if (w.length < 3) return -1
  for (var i = 0; i < 12; i++) if (D.MONTH_NAMES[i].toLowerCase().indexOf(w) === 0) return i
  return w === "sept" ? 8 : -1
}
function num(w) { return /^\d+$/.test(w) ? Number(w) : NUM[w] }

function parse(text, now) {
  var s = String(text || "").toLowerCase().replace(/,/g, " , ").replace(/\s+/g, " ").trim()
  if (s === "" || /^(none|never|no repeat|doesn't repeat|does not repeat|once)$/.test(s)) return { clear: true }
  s = s.replace(/ , /g, ", ").replace(/^repeat(s)? /, "").replace(/^every /, "every ")

  // Tail modifiers: "until <date>", "for 10 times" / "10 times" / "x10"
  var extra = []
  var m = s.match(/ (?:until|till|til|ending) (.+)$/)
  if (m) {
    var u = D.parse(m[1], now, {})
    if (!u.date) return { error: "couldn't read the end date \"" + m[1] + "\"" }
    extra.push("UNTIL=" + u.date.replace(/-/g, ""))
    s = s.slice(0, m.index)
  }
  m = s.match(/ (?:for )?(\d+) times$| x ?(\d+)$/)
  if (m) { extra.push("COUNT=" + (m[1] || m[2])); s = s.slice(0, m.index) }
  s = s.trim()

  var r = core(s)
  if (!r) return { error: "didn't understand \"" + text + "\" — try every weekday, every 2 weeks on fri, monthly on the 1st" }
  var rule = r.concat(extra).join(";")
  return { rule: rule, text: describe(rule) }
}

function core(s) {
  var m, n
  if (/^(daily|every ?day)$/.test(s)) return ["FREQ=DAILY"]
  if (/^(every )?weekdays?$|^every week ?day$|^(mon|monday) ?(to|-|through) ?(fri|friday)$/.test(s)) return ["FREQ=WEEKLY", "BYDAY=MO,TU,WE,TH,FR"]
  if (/^(every )?weekends?$/.test(s)) return ["FREQ=WEEKLY", "BYDAY=SA,SU"]
  if (/^(weekly|every week)$/.test(s)) return ["FREQ=WEEKLY"]
  if (/^(fortnightly|every fortnight)$/.test(s)) return ["FREQ=WEEKLY", "INTERVAL=2"]
  if (/^(monthly|every month)$/.test(s)) return ["FREQ=MONTHLY"]
  if (/^(yearly|annually|every year)$/.test(s)) return ["FREQ=YEARLY"]

  // every N days / weeks / months / years [on ...]
  m = s.match(/^every (\d+|a|an|one|two|three|four|five|six|other) (day|week|month|year)s?(?: on (?:the )?(.+))?$/)
  if (m) {
    n = num(m[1]); if (!n) return null
    var freq = { day: "DAILY", week: "WEEKLY", month: "MONTHLY", year: "YEARLY" }[m[2]]
    var out = ["FREQ=" + freq]
    if (n > 1) out.push("INTERVAL=" + n)
    if (m[3]) {
      var on = onPart(m[3], freq)
      if (!on) return null
      out = out.concat(on)
    }
    return out
  }
  // weekly on mon, thu / every week on fri
  m = s.match(/^(?:weekly|every week) on (.+)$/)
  if (m) { var dl = dayList(m[1]); return dl ? ["FREQ=WEEKLY", "BYDAY=" + dl.join(",")] : null }
  // monthly on the 1st / every month on the last friday
  m = s.match(/^(?:monthly|every month) on (?:the )?(.+)$/)
  if (m) { var mo = onPart(m[1], "MONTHLY"); return mo ? ["FREQ=MONTHLY"].concat(mo) : null }
  // yearly on 1 jan / every year on jan 1
  m = s.match(/^(?:yearly|annually|every year) on (.+)$/)
  if (m) { var yo = onPart(m[1], "YEARLY"); return yo ? ["FREQ=YEARLY"].concat(yo) : null }
  // on the 1st of every month / the 15th of each month
  m = s.match(/^(?:on )?(?:the )?(\d{1,2})(?:st|nd|rd|th)? (?:day )?of (?:every|each|the) month$/)
  if (m) return ["FREQ=MONTHLY", "BYMONTHDAY=" + Number(m[1])]
  if (/^(?:on )?(?:the )?last day of (?:every|each|the) month$/.test(s)) return ["FREQ=MONTHLY", "BYMONTHDAY=-1"]
  // every first monday / every last fri
  m = s.match(/^every (first|1st|second|2nd|third|3rd|fourth|4th|last) ([a-z]+)$/)
  if (m && dayCode(m[2])) return ["FREQ=MONTHLY", "BYDAY=" + ORD[m[1]] + dayCode(m[2])]
  // every 1 jan / every jan 1
  var y = yearDay(s.replace(/^every /, ""))
  if (/^every /.test(s) && y) return ["FREQ=YEARLY"].concat(y)
  // every 15th
  m = s.match(/^every (\d{1,2})(?:st|nd|rd|th)$/)
  if (m) return ["FREQ=MONTHLY", "BYMONTHDAY=" + Number(m[1])]
  // every mon and thu / mondays / every monday
  m = s.match(/^(?:every |on )?(.+)$/)
  if (m) {
    var dl2 = dayList(m[1])
    if (dl2) return ["FREQ=WEEKLY", "BYDAY=" + dl2.join(",")]
  }
  return null
}

function onPart(s, freq) {
  s = s.trim().replace(/^the /, "")
  if (freq === "WEEKLY" || freq === "DAILY") {
    var dl = dayList(s)
    return dl ? ["BYDAY=" + dl.join(",")] : null
  }
  if (freq === "MONTHLY") {
    var m = s.match(/^(\d{1,2})(?:st|nd|rd|th)?$/)
    if (m && +m[1] >= 1 && +m[1] <= 31) return ["BYMONTHDAY=" + Number(m[1])]
    if (/^last day$/.test(s)) return ["BYMONTHDAY=-1"]
    m = s.match(/^(first|1st|second|2nd|third|3rd|fourth|4th|last) ([a-z]+)$/)
    if (m && dayCode(m[2])) return ["BYDAY=" + ORD[m[1]] + dayCode(m[2])]
    return null
  }
  if (freq === "YEARLY") return yearDay(s)
  return null
}

function yearDay(s) {
  var t = s.replace(/(\d+)(st|nd|rd|th)\b/g, "$1").replace(/\bof\b/g, "").replace(/\s+/g, " ").trim()
  var m = t.match(/^(\d{1,2}) ([a-z]+)$/)
  if (m && monthIndex(m[2]) >= 0) return ["BYMONTH=" + (monthIndex(m[2]) + 1), "BYMONTHDAY=" + Number(m[1])]
  m = t.match(/^([a-z]+) (\d{1,2})$/)
  if (m && monthIndex(m[1]) >= 0) return ["BYMONTH=" + (monthIndex(m[1]) + 1), "BYMONTHDAY=" + Number(m[2])]
  return null
}

function ordinal(n) {
  n = Number(n)
  if (n === -1) return "last"
  var s = ["th", "st", "nd", "rd"], v = n % 100
  return n + (s[(v - 20) % 10] || s[v] || s[0])
}

// RRULE (with or without DTSTART) -> "Every 2 weeks on Friday"
function describe(rule) {
  var p = {}
  String(rule || "").split(";").forEach(function (kv) { var i = kv.indexOf("="); if (i > 0) p[kv.slice(0, i).toUpperCase()] = kv.slice(i + 1) })
  var f = p.FREQ, n = Number(p.INTERVAL || 1)
  if (!f) return String(rule || "")
  var unit = { DAILY: "day", WEEKLY: "week", MONTHLY: "month", YEARLY: "year" }[f]
  var s = n === 1 ? { DAILY: "Every day", WEEKLY: "Every week", MONTHLY: "Every month", YEARLY: "Every year" }[f]
                  : (n === 2 && f === "WEEKLY" ? "Every other week" : "Every " + n + " " + unit + "s")
  if (p.BYDAY) {
    var codes = p.BYDAY.split(",")
    if (f === "WEEKLY" && n === 1 && codes.join(",") === "MO,TU,WE,TH,FR") s = "Every weekday"
    else if (f === "WEEKLY" && n === 1 && codes.join(",") === "SA,SU") s = "Every weekend"
    else {
      s += " on " + codes.map(function (c) {
        var mm = c.match(/^(-?\d)?([A-Z]{2})$/)
        if (!mm) return c
        return (mm[1] ? "the " + ordinal(mm[1]) + " " : "") + DAY_NAMES[mm[2]]
      }).join(", ")
    }
  }
  if (p.BYMONTHDAY) s += " on the " + (p.BYMONTHDAY === "-1" ? "last day" : ordinal(p.BYMONTHDAY))
  if (p.BYMONTH) s = s.replace(/ on the (\d+\w+)$/, "") + " on " + (p.BYMONTHDAY ? Number(p.BYMONTHDAY) + " " : "") + D.MONTH_NAMES[Number(p.BYMONTH) - 1]
  if (p.COUNT) s += ", " + p.COUNT + " times"
  if (p.UNTIL) { var u = p.UNTIL.replace(/T.*/, ""); s += ", until " + u.slice(0, 4) + "-" + u.slice(4, 6) + "-" + u.slice(6, 8) }
  return s
}
