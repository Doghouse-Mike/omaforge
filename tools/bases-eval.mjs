// Run app/bases.js under node: stdin {views:[{id, filter}], tasks:{path: task}, now}
// -> stdout {id: [matching paths]}. Used by tools/basestest.py.
import { readFileSync } from "node:fs";
import vm from "node:vm";
const src = readFileSync(new URL("../app/bases.js", import.meta.url), "utf8").replace(/^\.pragma library\s*/, "");
const B = {};
vm.runInNewContext(src + "\nexports.matches = matches; exports.index = index; exports.value = value;", { exports: B });
const input = JSON.parse(readFileSync(0, "utf8"));
const byName = B.index(input.tasks);
const out = {};
for (const v of input.views) {
  out[v.id] = Object.keys(input.tasks).filter(p => B.matches(v, input.tasks[p], byName, input.now)).sort();
}
process.stdout.write(JSON.stringify(out));
