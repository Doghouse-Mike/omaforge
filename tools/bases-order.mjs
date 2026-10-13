// Run the app's own view sorting (app/views.js computeBase, which uses
// app/bases.js) under node: stdin {views:[{id, filter, sort}], tasks, settings,
// today, now} -> stdout {id: [paths in display order]}. Used by tools/basestest.py.
import { readFileSync } from "node:fs";
import vm from "node:vm";
const load = f => readFileSync(new URL("../app/" + f, import.meta.url), "utf8")
  .replace(/^\.pragma library\s*/, "").replace(/^\.import .*$/gm, "");
const B = {};
vm.runInNewContext(load("bases.js") + "\nfor (const k of ['matches','index','value','sortValue','compareValues','label','isDate','formatDate']) exports[k] = eval(k);", { exports: B });
const V = {};
vm.runInNewContext(load("views.js") + "\nexports.computeBase = computeBase;", { exports: V, B, Date });
const input = JSON.parse(readFileSync(0, "utf8"));
const out = {};
for (const v of input.views) {
  // Flat order without grouping (base:query flattens groups), then grouped.
  const r = V.computeBase({ filter: v.filter, sort: v.sort, layout: "list" }, input.tasks, input.settings, input.today, { search: "" });
  out[v.id] = r.groups.flatMap(g => g.tasks.map(t => t.path));
  if (v.group) {
    const g = V.computeBase({ filter: v.filter, sort: v.sort, group: v.group, layout: "list" }, input.tasks, input.settings, input.today, { search: "" });
    out[v.id + "#groups"] = g.groups.map(x => [x.label, x.tasks.map(t => t.path)]);
  }
}
process.stdout.write(JSON.stringify(out));
