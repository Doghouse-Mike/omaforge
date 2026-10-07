// node tools/recur-test.mjs — app/recur.js (repeat rules in plain English).
import { readFileSync } from "node:fs";
import vm from "node:vm";
const strip = f => readFileSync(new URL("../app/" + f, import.meta.url), "utf8").replace(/^\.pragma library\s*/, "").replace(/^\.import .*$/m, "");
// Separate contexts, like QML's `.import "dates.js" as D` namespacing.
const dctx = { exports: {} };
vm.runInNewContext(strip("dates.js") + "\nexports.parse = parse; exports.MONTH_NAMES = MONTH_NAMES;", dctx);
const ctx = { exports: {}, D: dctx.exports };
vm.runInNewContext(strip("recur.js") + "\nexports.parse = parse; exports.describe = describe;", ctx);
const R = ctx.exports;
const now = new Date(2026, 9, 7, 22, 40);
const cases = [
  ["daily", "FREQ=DAILY"], ["every day", "FREQ=DAILY"], ["every 3 days", "FREQ=DAILY;INTERVAL=3"],
  ["weekdays", "FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR"], ["every weekday", "FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR"],
  ["weekends", "FREQ=WEEKLY;BYDAY=SA,SU"], ["weekly", "FREQ=WEEKLY"], ["fortnightly", "FREQ=WEEKLY;INTERVAL=2"],
  ["every monday", "FREQ=WEEKLY;BYDAY=MO"], ["mondays", "FREQ=WEEKLY;BYDAY=MO"], ["every mon and thu", "FREQ=WEEKLY;BYDAY=MO,TH"],
  ["every fri, mon", "FREQ=WEEKLY;BYDAY=MO,FR"], ["weekly on tue, thurs", "FREQ=WEEKLY;BYDAY=TU,TH"],
  ["every 2 weeks on fri", "FREQ=WEEKLY;INTERVAL=2;BYDAY=FR"], ["every other week on monday", "FREQ=WEEKLY;INTERVAL=2;BYDAY=MO"],
  ["monthly", "FREQ=MONTHLY"], ["monthly on the 1st", "FREQ=MONTHLY;BYMONTHDAY=1"], ["every month on the 15th", "FREQ=MONTHLY;BYMONTHDAY=15"],
  ["on the 1st of every month", "FREQ=MONTHLY;BYMONTHDAY=1"], ["every 15th", "FREQ=MONTHLY;BYMONTHDAY=15"],
  ["last day of the month", "FREQ=MONTHLY;BYMONTHDAY=-1"], ["every last friday", "FREQ=MONTHLY;BYDAY=-1FR"],
  ["every first monday", "FREQ=MONTHLY;BYDAY=1MO"], ["monthly on the second tuesday", "FREQ=MONTHLY;BYDAY=2TU"],
  ["every 3 months", "FREQ=MONTHLY;INTERVAL=3"], ["yearly", "FREQ=YEARLY"], ["every year on 1 jan", "FREQ=YEARLY;BYMONTH=1;BYMONTHDAY=1"],
  ["every jan 1st", "FREQ=YEARLY;BYMONTH=1;BYMONTHDAY=1"], ["annually on 25 december", "FREQ=YEARLY;BYMONTH=12;BYMONTHDAY=25"],
  ["daily until 1 jan 2027", "FREQ=DAILY;UNTIL=20270101"], ["every weekday for 10 times", "FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR;COUNT=10"],
  ["weekly x5", "FREQ=WEEKLY;COUNT=5"], ["none", "CLEAR"], ["", "CLEAR"], ["sometimes", "ERR"], ["every blursday", "ERR"],
];
let fail = 0;
for (const [input, want] of cases) {
  const r = R.parse(input, now);
  const got = r.clear ? "CLEAR" : r.error ? "ERR" : r.rule;
  if (got !== want) { fail++; console.log(`FAIL ${JSON.stringify(input)}: got ${got} (${r.error || r.text || ""}), want ${want}`); }
}
const desc = [["FREQ=WEEKLY;INTERVAL=2;BYDAY=FR", "Every other week on Friday"], ["DTSTART:20261009;FREQ=MONTHLY;BYDAY=-1FR", "Every month on the last Friday"],
              ["FREQ=YEARLY;BYMONTH=12;BYMONTHDAY=25", "Every year on 25 December"], ["FREQ=MONTHLY;BYMONTHDAY=1", "Every month on the 1st"],
              ["FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR;COUNT=10", "Every weekday, 10 times"]];
for (const [rule, want] of desc) { const got = R.describe(rule); if (got !== want) { fail++; console.log(`FAIL describe ${rule}: "${got}", want "${want}"`); } }
console.log(fail ? `${fail} failed` : `all ${cases.length + desc.length} passed`);
process.exit(fail ? 1 : 0);
