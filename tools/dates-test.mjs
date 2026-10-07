// node tools/dates-test.mjs — app/dates.js against a fixed clock.
import { readFileSync } from "node:fs";
import vm from "node:vm";
const src = readFileSync(new URL("../app/dates.js", import.meta.url), "utf8").replace(/^\.pragma library\s*/, "");
const D = {};
vm.runInNewContext(src + "\nexports.parse = parse; exports.compact = compact; exports.pretty = pretty;", { exports: D });
const now = new Date(2026, 9, 7, 22, 40);            // Wed 7 Oct 2026, 22:40
const opts = { defaultTime: "09:00", useDefaultTime: true };
const off = { defaultTime: "09:00", useDefaultTime: false };
const cases = [
  ["January 1st 2027", "2027-01-01T09:00"], ["january 1st, 2027", "2027-01-01T09:00"], ["1 Jan", "2027-01-01T09:00"],
  ["jan 1", "2027-01-01T09:00"], ["1st of January", "2027-01-01T09:00"], ["Sept 3", "2027-09-03T09:00"],
  ["31 dec 2026", "2026-12-31T09:00"], ["1/2/27", "2027-02-01T09:00"], ["1/2", "2027-02-01T09:00"], ["12/10", "2026-10-12T09:00"],
  ["2027-01-01", "2027-01-01T09:00"], ["30 feb", "ERR"], ["the 15th", "2026-10-15T09:00"], ["5th", "2026-11-05T09:00"],
  ["today", "2026-10-07T09:00"], ["tomorrow", "2026-10-08T09:00"], ["tom", "2026-10-08T09:00"],
  ["fri", "2026-10-09T09:00"], ["friday", "2026-10-09T09:00"], ["wed", "2026-10-07T09:00"], ["next fri", "2026-10-16T09:00"],
  ["next week", "2026-10-12T09:00"], ["weekend", "2026-10-10T09:00"], ["end of month", "2026-10-31T09:00"],
  ["next month", "2026-11-01T09:00"],
  ["+10m", "2026-10-07T22:50"], ["+1h", "2026-10-07T23:40"], ["in 2 hours", "2026-10-08T00:40"], ["in 10 minutes", "2026-10-07T22:50"],
  ["+3d", "2026-10-10T09:00"], ["in a week", "2026-10-14T09:00"], ["-1d", "2026-10-06T09:00"], ["+1mo", "2026-11-07T09:00"],
  ["3pm", "2026-10-08T15:00"], ["23:00", "2026-10-07T23:00"], ["noon", "2026-10-08T12:00"],
  ["fri 9am", "2026-10-09T09:00"], ["fri 3pm", "2026-10-09T15:00"], ["tomorrow at noon", "2026-10-08T12:00"],
  ["at 3pm tomorrow", "2026-10-08T15:00"], ["tomorrow 15:30", "2026-10-08T15:30"], ["9.30am fri", "2026-10-09T09:30"],
  ["tomorrow at 9", "2026-10-08T09:00"], ["tonight", "2026-10-07T20:00".replace("07T20", "08T20")],
  ["1 jan 2027 14:00", "2027-01-01T14:00"], ["fri all day", "2026-10-09"], ["tomorrow no time", "2026-10-08"],
  ["+1week at 1PM", "2026-10-14T13:00"], ["+1week", "2026-10-14T09:00"], ["in 3 days 9am", "2026-10-10T09:00"],
  ["+2d noon", "2026-10-09T12:00"], ["in 2 weeks at 14:30", "2026-10-21T14:30"], ["+1d all day", "2026-10-08"],
  ["blah", "ERR"], ["25:00", "ERR"], ["", "CLEAR"],
];
let fail = 0;
for (const [input, want] of cases) {
  const r = D.parse(input, now, opts);
  const got = r.clear ? "CLEAR" : r.error ? "ERR" : r.value;
  if (got !== want) { fail++; console.log(`FAIL ${JSON.stringify(input)}: got ${got} (${r.error || r.pretty || ""}), want ${want}`); }
}
// default time switched off: dates stay dates, times stay times
for (const [input, want] of [["fri", "2026-10-09"], ["fri 3pm", "2026-10-09T15:00"], ["+1h", "2026-10-07T23:40"]]) {
  const r = D.parse(input, now, off);
  if (r.value !== want) { fail++; console.log(`FAIL (no default) ${input}: got ${r.value}, want ${want}`); }
}
// What the boxes display must read back to the same value.
for (const v of ["2026-10-07T09:30", "2026-10-08T09:30", "2026-10-06", "2026-10-15T14:00", "2026-10-15", "2027-01-01T09:00", "2027-01-01"]) {
  for (const show of [D.compact(v, now), D.pretty(v, now)]) {
    const r = D.parse(show, now, off);
    if (r.value !== v) { fail++; console.log(`FAIL round-trip ${v} -> "${show}" -> ${r.value || r.error}`); }
  }
}
console.log(D.parse("January 1st 2027", now, opts).pretty, "|", D.parse("+10m", now, opts).pretty);
console.log(fail ? `${fail} failed` : `all ${cases.length + 3} passed`);
process.exit(fail ? 1 : 0);
