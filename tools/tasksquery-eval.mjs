// Run app/tasksquery.js (the ```tasks query evaluator) under node:
// stdin {queries: [{id, source, file}], tasks: [inline task records],
//        tasksSettings: Tasks' data.json, today: "YYYY-MM-DD"}
// -> stdout {id: {error} | {total, groups: [{names, tasks: [keys]}]}}.
// Used by tools/tasksquerytest.py.
import { readFileSync } from "node:fs";
import vm from "node:vm";
const load = f => readFileSync(new URL("../app/" + f, import.meta.url), "utf8")
  .replace(/^\.pragma library\s*/, "").replace(/^\.import .*$/gm, "");
const C = {};
vm.runInNewContext(load("chrono.js") + "\nexports.chrono = chrono;", { exports: C, Date });
const Q = {};
vm.runInNewContext(load("tasksquery.js") + "\nexports.evaluate = evaluate;", { exports: Q, Date, C });
const input = JSON.parse(readFileSync(0, "utf8"));
const out = {};
for (const q of input.queries) {
  let r;
  try { r = Q.evaluate(q.source, input.tasks, { file: q.file, settings: input.tasksSettings, today: input.today }); }
  catch (e) { out[q.id] = { crash: String(e && e.stack || e) }; continue; }
  out[q.id] = r.error ? { error: r.error } : r.unsupported ? { unsupported: r.unsupported }
    : { total: r.total, groups: r.groups.map(g => ({ names: g.names, tasks: g.tasks.map(t => t.path) })) };
}
process.stdout.write(JSON.stringify(out));
