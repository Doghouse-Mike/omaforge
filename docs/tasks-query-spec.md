# Obsidian Tasks 8.5.0 query-language spec (```tasks blocks)

What the Obsidian **Tasks** plugin 8.5.0 does with the text of a ` ```tasks `
block: how it parses each line, which tasks each filter keeps, how it sorts and
groups the result. Written from the source, for a plain-JavaScript
re-implementation. Companion to `tasks-plugin-spec.md` (task-line format,
statuses, recurrence), which this document does not repeat.

**Sources.** `src/…:N` means obsidian-tasks at tag `8.5.0` (HEAD `84704d3`).
`tests/…` and `docs/…` come from the same checkout. Two libraries do part of
the work: **chrono-node 2.3.9** for natural-language dates (`package.json:83`)
and **moment** for date arithmetic. Obsidian supplies `moment` as
`window.moment`, and its locale follows Obsidian's language setting.

**Conventions.** "ci" means case-insensitive. Every regex is quoted verbatim.
`localeCompare*` means `a.localeCompare(b, undefined, { numeric: true })`.
A re-implementation in JS should call exactly this, because the results depend
on ICU collation (for example `"a" < "A" < "b"` and `"2" < "10"`).
A "date" is a moment at local midnight. Task dates are read with
`moment(str, 'YYYY-MM-DD')` and can be **invalid**, which is different from
missing (`null`); see `tasks-plugin-spec.md` §3.2.

Contents: 1 pipeline · 2 filters · 3 layout · 4 sorting · 5 grouping ·
6 what the query sees · 7 priorities for implementers.

---

## 1. Query parsing pipeline

### 1.1 Assembling the full query (`src/Query/QueryRendererHelper.ts:78-94`)

```
combined = new Query(globalQuery.source + '\n' + fileDefaults.source + '\n' + block.source, file)
```

- **Query File Defaults** (`src/Query/QueryFileDefaults.ts`) are lines
  generated from `TQ_*` frontmatter properties of the file that contains the
  query (`TQ_short_mode`, `TQ_show_tree`, `TQ_extra_instructions`, …). They are
  prepended to the block.
- If the defaults+block query has `ignore global query`, the global query is
  dropped. Otherwise the **global query** (setting `globalQuery`, default `''`,
  `src/Config/Settings.ts:119`) is prepended.
- `Query.append` concatenates the **source text** and re-parses everything
  (`src/Query/Query.ts:273-277`; an empty side is skipped). So it is a single
  query: global filters, sorts and groups come first, and an error in the
  global query breaks every block that does not ignore it.
- `ignore global query` is detected by `/^ignore global query/i`
  (`Query.ts:56`). It is a prefix match, so trailing text is ignored.

### 1.2 Line continuation (`src/Query/Scanner.ts:19-108`)

The source is split on `'\n'`, and an extra `'\n'` is appended first, so a
final trailing `\` still flushes.

- If a raw line ends with exactly one `\`, it continues onto the next line.
  The `\` and any spaces/tabs before it are removed (`/[ \t]*\\$/`).
- A continued-into line has its leading `/^[ \t]*/` stripped. It is then
  joined to the previous one with **one space**.
- If a line ends with `\\`, the last `\` is dropped (giving a literal `\`), and
  the line is **not** continued.
- Statements that are empty or whitespace-only after joining are discarded.
  This is how blank lines are ignored.
- Each statement is then `.trim()`med (`src/Query/Statement.ts:24`). Every
  later regex sees trimmed text, so indentation never matters.

### 1.3 Placeholders (`Query.ts:174-257`, `src/Scripting/ExpandPlaceholders.ts`)

This step runs for each statement, before line parsing.

1. If the statement contains both `{{` and `}}` and the query has no file,
   the query fails with an error ("…contains a placeholder … but no file path
   has been supplied…"). This check runs even on comment lines.
2. If the statement matches `/^#.*/` (a comment), it is returned unchanged.
   Placeholders inside comments are never expanded.
3. Otherwise `expandPlaceholders` runs repeatedly until the output stops
   changing, up to **10 iterations** (`Query.ts:201`). A substituted value that
   itself contains `{{…}}` is therefore expanded too.
4. If anything changed, the continuation rules (§1.2) are applied again to the
   result. The result is split on `\n`, each line trimmed, and empty lines
   dropped. **Each remaining line becomes its own statement**, so a
   multi-line value expands into several instructions.

How one placeholder is evaluated. The text between `\{\{(.*?)\}\}` (lazy,
global) is trimmed, then:

| placeholder (exact, after trim) | value (`src/Scripting/KnownPlaceholderResolver.ts`, `src/Scripting/TasksFile.ts`) |
|---|---|
| `query.file.path` | path of the file containing the query, e.g. `a/b/c.md` |
| `query.file.pathWithoutExtension` | path with `/\.md$/` removed |
| `query.file.root` | see §6.3; e.g. `a/`, or `/` for a file at the vault root |
| `query.file.folder` | see §6.3; e.g. `a/b/`, or `/` |
| `query.file.filename` | `c.md` (from `/([^/]+)$/`, or `''`) |
| `query.file.filenameWithoutExtension` | `c` |
| `query.file.outlinks`, `…outlinksInProperties`, `…outlinksInBody` | arrays of link objects, emitted as JSON (rarely useful) |
| `query.file.property('x')` / `("x")` | the frontmatter value. The key match is ci. Arrays have `null`s removed. Regex: `^query\.file\.property\((['"])([^'"]*)\1\)$` |
| `query.file.hasProperty('x')` | `true`/`false` (false if the key is missing or the value is `null`) |
| `preset.<name>` | the preset's text, verbatim (it can be multi-line) |
| any other dotted name, e.g. `query.file.frontmatter.x` | resolved by Mustache as a property path |

- A value of `null` is an error ("Invalid placeholder result 'null'. Check
  for missing file property…"). A missing property gives `null`. Objects and
  arrays are emitted with `JSON.stringify`, and other values with `String()`.
  HTML escaping is turned off.
- An unknown dotted name is an error: `Unknown property: query.file.xyz`
  (mustache-validator).
- **JavaScript in queries is OFF by default in 8.5.0**
  (`src/Config/EnableJsInTasksQueries.ts:4`). When it is off, any placeholder
  that is not in the table above and does not match
  `/^[A-Za-z_$][\w$]*(\.[A-Za-z_$][\w$]*)*$/` throws
  `JsInTasksQueriesDisabledError`. That includes Mustache comments
  `{{! … }}` and sections `{{#…}}`. So the safe subset is exactly the
  table above. Placeholders are always evaluated against the **query's**
  file, never the task's file.
- Placeholder errors are wrapped as `There was an error expanding one or more
  placeholders.\n\nThe error message was:\n    …\n\nThe problem is in:\n    <line>`.

### 1.4 Line dispatch (`Query.ts:123-163`)

The first matching case wins. All regexes run on the expanded, trimmed
statement.

| # | test | effect |
|---|---|---|
| 1 | `/^preset +(.*)/i` | preset, §1.5 |
| 2 | `/^short/i` | short mode (display only). **Prefix match**: `shortcut` also counts |
| 3 | `/^full/i` | full mode (display only), also a prefix match |
| 4 | `/^explain/i` | show the explanation (display only), also a prefix match |
| 5 | `/^ignore global query/i` | §1.1 |
| 6 | `/^limit (groups )?(to )?(\d+)( tasks?)?/i` | §3.1 (unanchored end) |
| 7 | `parseSorter` (`/^sort by /i`, then the fields) | §4. If no field matches, fall through |
| 8 | `parseGrouper` (`/^group by /i`, then the fields) | §5. If no field matches, fall through |
| 9 | `/^view +(.*)/i` | `view list` / `view columns by <group field> [reverse]` |
| 10 | `/^(hide|show) +(.*)/i` | §3.2 |
| 11 | `/^#.*/` | comment, ignored |
| 12 | `FilterParser.parseFilter` | §2 |
| — | otherwise | error `do not understand query` |

`sort by` / `group by` lines that match no field reach step 12 and normally
fail as `do not understand query`.

### 1.5 Presets (`Query.ts:520-545`, `src/Query/Presets/Presets.ts`)

- `preset <name>`: the name is `match[1].trim()` and is looked up
  **case-sensitively** as a key of the `presets` setting. An unknown name is
  an error: `Cannot find preset "<name>" in the Tasks settings` plus a list of
  the defined presets.
- The preset text is split with the continuation rules (§1.2). Each line has
  its placeholders expanded **once** (no 10-iteration loop) and is fed to
  §1.4. Comments and nested `preset` lines therefore work. There is no
  recursion guard: a preset that includes itself overflows the stack, and that
  is caught and reported as an error.
- `{{preset.name}}` (§1.3) is the other route. It is textual substitution and
  works anywhere in a line.
- Built-in defaults (`Presets.ts`): `this_file` = `path includes
  {{query.file.path}}`; `this_folder` = `folder includes {{query.file.folder}}`;
  `this_folder_only` = `filter by function task.file.folder ===
  query.file.folder` (this **fails while JS is disabled**); `this_root` =
  `root includes {{query.file.root}}`; and `hide_date_fields`,
  `hide_non_date_fields`, `hide_query_elements`, `hide_everything`, which
  expand to lists of `hide …` lines.

### 1.6 Errors

- Parsing stops at the **first** failing statement, and the **whole query**
  becomes an error. Nothing is searched, and the renderer shows
  `Tasks query: <message>` (`src/Renderer/HtmlQueryResultsRenderer.ts:107`).
- The message format is `<message>\nProblem line: "<raw line>"`. If
  continuation or placeholders changed the line, the format is instead
  `Problem statement:` followed by `raw => joined => expanded`
  (`Query.ts:344-354`).
- Any statement that a field claims but then rejects is fatal, for example
  `due someday`, `priority is above`, or an invalid regex.
- Runtime errors, such as a function throwing during search, give
  `QueryResult.fromError('Search failed…')` (`Query.ts:360-405`).

---

## 2. Filters

### 2.1 How a filter line is matched (`src/Query/FilterParser.ts:41-78`)

Field classes are tried **in this order**. The first one whose
`canCreateFilterForLine` returns true **owns** the line. If that field then
fails to parse it, the line is an error; other fields are not tried.

`status.name`, `status.type`, status (`done`/`not done`), recurring, priority,
happens, cancelled, created, start, scheduled, due, done (date), path, folder,
root, backlink (never claims), description, tags, heading, exclude sub-items,
filename, urgency (never claims), recurrence, function, id, depends on,
blocking, random (never claims), **boolean (last)**.

Fixed-phrase instructions (`FilterInstruction`, `src/Query/Filter/FilterInstruction.ts:20`)
match the **whole trimmed line**, ci (`toLocaleLowerCase` equality). Any extra
or doubled internal space breaks the match.

All filter lines are ANDed (`Query.ts:367-372`). Each filter is applied in
sequence to the task list.

### 2.2 Text filters (`src/Query/Filter/TextField.ts`)

Regex: `new RegExp('^(?:' + field + ') (' + ops + ') (.*)', 'i')`. `ops` is
`includes|does not include|regex matches|regex does not match`. Multi-value
fields (tags) also accept `include|do not include` (`MultiTextField.ts`).

- The operator is lower-cased. If it contains `include`, the filter is a
  substring match. If it contains `regex`, it is a regex match. If it contains
  `not`, the result is negated.
- **includes**: `value.toLocaleLowerCase().includes(needle.toLocaleLowerCase())`.
  This is ci, not anchored, and has no word boundaries. The needle is
  everything after the operator's following space. Extra spaces stay in the
  needle, but trailing spaces are lost because the line was trimmed. An empty
  needle cannot occur, because `x includes` with nothing after it does not
  match the regex and fails.
- **regex**: the needle must match `/^\/(.+)\/([^/]*)$/`. It is compiled as
  `new RegExp(body, flags)` and tested with `value.match(re) !== null`. It is
  **case-sensitive unless the `i` flag is given**. Errors are: not in `/…/`
  form (`Invalid instruction…`), invalid flags or syntax (`Parsing regular
  expression…`), a body longer than 500 characters, or one that `safe-regex2`
  rejects with star-height limit 25 (`src/lib/RegExpTools.ts`). A JS port can
  skip the safety check.

| field (`fieldName`) | value searched | source |
|---|---|---|
| `description` | `task.description` with the global filter removed: the **first** occurrence as a plain substring, then `.trim()` (`GlobalFilter.removeAsSubstringFrom`). Tags stay in. | `DescriptionField.ts` |
| `path` | full vault path including `.md`, e.g. `a/b/c.md` | `PathField.ts` |
| `folder` | `task.file.folder` (§6.3), with a trailing `/` | `FolderField.ts` |
| `root` | `task.file.root` (§6.3) | `RootField.ts` |
| `filename` | `<name>.md`, or `''` if the path does not end in `.md` | `FilenameField.ts` |
| `heading` | the preceding heading text (§6.2), or `''` | `HeadingField.ts` |
| `status.name` | `task.status.name` (e.g. `Todo`, `In Progress`) | `StatusNameField.ts` |
| `recurrence` | `recurrence.toText()` (the normalised rule text, e.g. `every week`), or `''` | `RecurrenceField.ts` |
| `id` | `task.id` (`''` if none) | `IdField.ts` |
| `tag` / `tags` | **each** tag separately; true if **any** tag matches (`matchesAnyOf`). The negated form is true when **no** tag matches | `TagsField.ts` |

- `backlink` is not a filter. `backlink includes x` is not claimed and fails
  with `do not understand query`.
- Tags (`task.tags`) are `description.match(/(^|\s)#[^ !@#$%^&*(),.?":{}|<>]+/g)`
  trimmed, so each one keeps its `#` (`src/Task/TaskRegularExpressions.ts:67`).
  They come only from the description. File/frontmatter tags are not included.
  A tag **exactly equal** to the global filter is removed. Nested tags are
  plain strings: `tags include #a` matches `#a`, `#a/b`, `#abc` and `#xa`,
  because it is a substring match. To match exactly, use a regex such as
  `tags regex matches /^#a($|\/)/i`. `tags include a` (no `#`) also matches.
  Number-only tags such as `#123` count.
- Extra fixed phrases: `has tag`, `has tags`, `no tag`, `no tags`, `has id`,
  `no id`.

### 2.3 Status filters

- `done`: status type is `DONE`, `CANCELLED` or `NON_TASK`. `not done`: every
  other type (`TODO`, `IN_PROGRESS`, `ON_HOLD`, `EMPTY`)
  (`src/Query/Filter/StatusField.ts`, `src/Task/Task.ts:544-550`).
  These are exact phrases.
- `status.type is|is not <TYPE>`: the regex is
  `^(?:status\.type) (is|is not) ([^ ]+)$` (ci), and `<TYPE>` is upper-cased
  and must be a `StatusType` key: `TODO DONE IN_PROGRESS ON_HOLD CANCELLED
  NON_TASK EMPTY`. Any line **starting** with `status.type` is claimed
  (`/^(?:status\.type)/i`), so a malformed one is an error that comes with a
  help message.
- `status.name includes|does not include|regex matches|regex does not match …`: see §2.2.

### 2.4 Date filters (`src/Query/Filter/DateField.ts`, `src/DateTime/DateParser.ts`, `src/DateTime/DateRange.ts`)

Fields: `due`, `scheduled`, `start`, `created`, `done`, `cancelled`,
`happens`. **The keyword used in filter lines is `starts`**, not `start`
(`StartDateField.ts`). `start before …` is not a valid filter.

**Fixed phrases** (exact, ci): `has <f> date`, `no <f> date`,
`<f> date is invalid`, where `<f>` is the field name (`start`, not `starts`).
`happens` only has `has happens date` and `no happens date`, which are true if
**any** of start, scheduled or due is non-null. Invalid dates count as present.

**Search lines**:
`new RegExp('^' + kw + ' (((?:on|in) or before|before|(?:on|in) or after|after|on|in)? ?(.*))', 'i')`.
`kw` is the field name (`starts` for start). Any line beginning `kw ` is
claimed, so `due someday` is an error and does not fall through to another
field.

1. If the line contains `<%` or the literal text `YYYY-MM-DD`, it is an error
   ("unexpanded template text") (`src/lib/TemplatingPluginTools.ts`).
2. `keyword` = group 2 lower-cased, or none. `text` = group 3.
3. `range = parseDateRange(text)` (below). If that is invalid, retry with
   `chrono.parseDate(group1)`, where group1 includes the keyword (for example
   `in two weeks`), and use it as a single-day range. If both are invalid, the
   error is `do not understand <f> date`.
4. The predicate, given task date `d` (moment at midnight):

| keyword | true when |
|---|---|
| none, `on`, `in` | `d >= range.start && d <= range.end` |
| `before` | `d < range.start` |
| `after` | `d > range.end` |
| `on or before`, `in or before` | `d <= range.end` |
| `on or after`, `in or after` | `d >= range.start` |

- **Missing date (`null`)**: false for every field, **except `starts`, which
  returns true**. A task with no start date matches every `starts …` line
  (`StartDateField.ts`). Use `(has start date) AND (starts before …)` to avoid
  that.
- **Invalid date**: false for every keyword, including `starts`, because
  moment comparisons with an invalid date are false.
- **`happens`**: true if **any** of start, scheduled or due (nulls skipped)
  satisfies the predicate (`HappensDateField.ts`). It is **not** limited to
  the earliest date. For sorting and grouping, "happens" means the
  **earliest valid** one of the three (`Task.ts:749-767`).
- `scheduled` includes a scheduled date inferred from the filename, if the
  `useFilenameAsScheduledDate` setting is on (default off).

**`parseDateRange(text)`**: three parsers are tried in order, and the first
valid result wins. All bounds are `startOf('day')` local. If end < start the
two are swapped (`DateRange.ts`).

1. **Relative range.** The regex is `/(last|this|next) (week|month|quarter|year)/`.
   It is **case-sensitive and unanchored**, so it matches anywhere in the text:
   `next weekend` counts as `next week`, while `Next Week` falls through to
   chrono.
   - `this X` is `[startOf(X), endOf(X)]` around today. `week` means the **ISO
     week, Monday to Sunday**.
   - `last` / `next` shift both bounds by ±1 X. For month and quarter the end
     is then recomputed as `endOf(X)`.
   - Tests (with today 2021-10-06): `last week` gives 2021-09-27..10-03,
     `next month` gives 2021-11-01..11-30, `next quarter` gives
     2022-01-01..03-31, and `last year` gives 2020-01-01..12-31.
2. **Numbered range.** Each form is anchored and may have surrounding
   whitespace:
   - `/^\s*[0-9]{4}\s*$/`: a year.
   - `/^\s*[0-9]{4}-Q[1-4]\s*$/`: a quarter.
   - `/^\s*[0-9]{4}-[0-9]{2}\s*$/`: a month (`2024-02` gives 02-01..02-29;
     `2023-13` and `2023-00` are invalid).
   - `/^\s*[0-9]{4}-W[0-9]{2}\s*$/`: an ISO week (`2019-W01` gives
     2018-12-31..2019-01-06; `2018-W53` and `2021-W00` are invalid).
   - The `Q` and `W` are upper-case only.
3. **Absolute or natural language** via `chrono.parse(text)`. One result gives
   a single day. Two or more results give the range from `results[0].start`
   to `results[1].start`, so `2026-01-01 2026-01-31` is a range. An
   unparseable half is skipped: `2013-99-29 2014-08-19` gives the single day
   2014-08-19.
   - chrono's own `X to Y` range result is **ignored**, so `A to B` becomes
     just A.

**Single day vs range, summarised:**

| text | result |
|---|---|
| `2026-10-13` | that day |
| `2026-10-13 2026-10-20` | inclusive range |
| `2026`, `2026-Q4`, `2026-10`, `2026-W42` | the whole year, quarter, month or ISO week |
| `last/this/next week|month|quarter|year` (lower-case) | the whole period |
| `today`, `tomorrow`, `yesterday` | that day |
| `monday`…`sunday` (no modifier) | the **closest** such day, within −3..+3 days of today (chrono `toDayJSWeekday`: whichever of weekday−7, weekday or weekday+7 in a **Sunday-based** week is nearest) |
| `this|next|last <weekday>` | that weekday in the current Sunday–Saturday week, or ±7 days |
| `in N days|weeks|months|years`, `N days … ago` (N a digit or `a`/`an`/`one`…`twelve`) | that single day (today ± N units) |
| `14 October`, `May` | the current year (1 May for a bare month) |

**Complex, treat as unsupported:** any other chrono input. That includes
mixed-case relative ranges, times of day (stripped by `startOf('day')`), two
words-only dates, `X to Y`, and locale-dependent formats such as `05/06/2026`
(chrono reads it as US MM/DD).

Relative dates are fixed when the query is **parsed**, and the plugin
re-renders queries at midnight.

### 2.5 Other filters

| line (exact unless noted) | true when | source |
|---|---|---|
| `priority [is] [above|below|not] <p>`, regex `/^priority(\s+is)?(\s+(above|below|not))?(\s+(lowest|low|none|medium|high|highest))$/i` | priorities are the strings `Highest '0'`, `High '1'`, `Medium '2'`, `None '3'`, `Low '4'`, `Lowest '5'` (`src/Task/Priority.ts`). `above`: `task.priority.localeCompare(p) < 0`, meaning more important. `below`: `> 0`. `not`: `!==`. Without a modifier: `===`. `normal` is **not** accepted; use `none`. A line that does not match the regex is not claimed and fails as `do not understand query` | `PriorityField.ts` |
| `is recurring` / `is not recurring` | the task has (or has not) a *valid* recurrence rule | `RecurringField.ts` |
| `exclude sub-items` | `indentation === ''`. Otherwise take the text after the **last** `>` in the indentation: it is a sub-item unless that text matches `/^ ?$/`. Only the leading whitespace and `>` prefix is used, not the parent | `ExcludeSubItemsField.ts` |
| `has depends on` / `no depends on` | `dependsOn.length > 0` / `=== 0`. Nothing else: there is **no** `depends on includes`. Any other wording fails as `do not understand query` | `DependsOnField.ts` |
| `is blocked` / `is not blocked` | blocked = the task is not done, and some id in `dependsOn` equals the `id` of a **not-done** task in *all tasks* (§6.1). Missing ids are ignored | `Task.ts:559-580` |
| `is blocking` / `is not blocking` | blocking = `id !== ''`, the task is not done, and some not-done task has this id in its `dependsOn` | `Task.ts:589-605` |
| `filter by function <js>` (regex `^filter by function (.*)`, ci) | the JS expression returns `true`. A non-boolean result throws. **Disabled by default** (error `JavaScript is now disabled in Tasks queries by default…`) | `FunctionField.ts` |

"Done" in the dependency rules means status type `DONE`, `CANCELLED` or
`NON_TASK`.

### 2.6 Boolean combinations (`BooleanField.ts`, `BooleanDelimiters.ts`, `BooleanPreprocessor.ts`, library `boon-js`)

**Recognition.** A line is boolean only if **no other field claimed it**
(boolean is last). It must also match (unanchored, flag `g`):

```
(.*(AND|OR|XOR|NOT)\s*[\(\[\{"].*|[\(\[\{"].+[\)\]\}"])
```

**Delimiters.** Strip the leading `/^[A-Z ]*\s*/` (unary operators). The next
character and the **last** character of the line must be one pair: `()`, `[]`,
`{}` or `""`. That one pair is then the only delimiter for the whole line;
mixing pairs is an error ("…Combinations of those delimiters are no longer
supported.").

**Operators.** `AND`, `OR`, `XOR`, `NOT`, `AND NOT`, `OR NOT`. They are
**upper-case only**, and lower-case `and` is not an operator. The
precedence is **NOT > XOR > AND > OR**, and binary operators are
left-associative (`docs/Queries/Combining Filters.md` "Execution Priority").
`A AND NOT B` = `A AND (NOT B)`.

**Leaves.** A leaf is the text inside the innermost delimiters, with the
delimiter characters and spaces trimmed from both ends. It is parsed with the
full §2.1 filter parser, so leaves can be any filter, including another field
or `filter by function`. It **cannot** be another boolean line, and it cannot
start or end with the chosen delimiter characters: `(description includes (x))`
breaks, so use `[ … ]` for that line.

**Errors.** An unparseable leaf, an unknown operator or bad nesting makes the
whole query an error. The message starts with `Could not interpret the
following instruction as a Boolean combination:`.

**Implementation advice.** Tokenise into delimiter groups and upper-case
operator words, and parse recursively. A group whose content contains
operators or nested groups is a sub-expression; otherwise it is a leaf line.
The real preprocessor splits on
`close\s*(?:AND|OR|AND +NOT|OR +NOT|XOR)\s*open` and `NOT\s*open`, then
replaces leaves with `f1`, `f2`, … for boon-js. That matches the recursive
model for every well-formed line.

---

## 3. Layout and limits

### 3.1 Limits (`Query.ts:460-475`, `:376-391`)

- `limit N`, `limit to N`, `limit N tasks`, `limit to N task` set the overall
  limit. It is applied **after sorting and before grouping**:
  `sorted.slice(0, N)`. `limit 0` shows nothing.
- `limit groups N` / `limit groups to N tasks` keeps the first N tasks of
  **each** group, after grouping. It is a no-op with no `group by`.
- The regex end is unanchored, so `limit 5 foo` is accepted. If there are
  several limit lines, the last one wins.
- The displayed total count is the number of tasks **before** `limit`.
  `limit groups` recalculates it as the number of unique tasks shown.

### 3.2 Display-only instructions (they never change which tasks match or their order)

- `short mode` / `full mode` (prefix regexes, §1.4) and `explain`.
- `hide <x>` / `show <x>`: `x` is lower-cased and matched with `startsWith`
  in this order (`src/Layout/QueryLayoutOptions.ts`, `TaskLayoutOptions.ts:105-135`):
  - Query level: `backlink`, `edit button`, `nested backlink`,
    `postpone button`, `task count`, `group count` (hidden by default),
    `toolbar`, `tree` (hidden by default), `urgency` (hidden by default).
  - Task level: `cancelled date`, `created date`, `depends on`, `done date`,
    `due date`, `id`, `on completion`, `priority`, `recurrence rule`,
    `scheduled date`, `start date`, `tags`.
  - Anything else is the error `do not understand hide/show option`.
- `show tree`: renders each matching task with **all** its child list items
  and tasks, in file order, whether or not the children matched. A matching
  child of a matching parent is drawn under the parent rather than at top
  level. The search itself is unchanged
  (`src/Renderer/QueryResultsRendererBase.ts:154-200`).
- `view list` / `view columns by <field> [reverse]`: the columns view
  prepends that grouper to the `group by` list (`Query.ts:381-384`). It
  changes grouping, not filtering.

---

## 4. Sorting

### 4.1 Recognition (`src/Query/Filter/Field.ts:35-57`)

The default regex per field is
`new RegExp('^sort by ' + escape(field) + '( reverse)?', 'i')`. **The end is
not anchored**: `sort by duex` sorts by due, and `sort by tags` matches the
`tag` sorter. Fields are tried in §2.1 order. `reverse` multiplies the
comparator by −1, and that reverses missing-value placement too.

### 4.2 Comparators (ascending; negative means a comes first)

| `sort by …` | comparator |
|---|---|
| `status` | `Todo` (not done) before `Done` |
| `status.name` | `localeCompare*` on the name |
| `status.type` | `localeCompare*` on `typeGroupText` (`%%1%%IN_PROGRESS`, `%%2%%TODO`, `%%3%%ON_HOLD`, `%%4%%DONE`, `%%5%%CANCELLED`, `%%6%%NON_TASK`, `%%7%%EMPTY`). The order is therefore IN_PROGRESS, TODO, ON_HOLD, DONE, CANCELLED, NON_TASK, EMPTY (`src/Statuses/Status.ts:150-182`) |
| `recurring` | recurring before non-recurring |
| `priority` | `a.priority.localeCompare(b.priority)` on `'0'..'5'`, so Highest, High, Medium, None, Low, Lowest |
| `due`, `scheduled`, `start`, `created`, `done`, `cancelled`, `happens` | `compareByDate` (`src/DateTime/DateTools.ts:3-27`): **invalid < valid (ascending) < null**. Two nulls or two invalids tie. `happens` uses the earliest valid of start, scheduled and due, or null |
| `path` | `localeCompare*` on the full path |
| `filename` | `localeCompare*` on `name.md` (or `''`) |
| `heading` | `localeCompare*` on the heading (`''` if none, which sorts first) |
| `id` | `localeCompare*` on the id (`''` first) |
| `description` | `localeCompare*` on a **cleaned** description (`DescriptionField.ts`): (1) remove the global filter (first substring, then trim); (2) if it starts with `/^\[\[?([^\]]*)]]?/`, replace that link with its inner text after the first `|` (the alias) or the whole inner text; (3) then, once each and in this order, unwrap a leading `/^\*\*([^*]+)\*\*/`, `/^\*([^*]+)\*/`, `/^==([^=]+)==/`, `/^__([^_]+)__/`, `/^_([^_]+)_/`. There is **no** stripping of `#`, tags, or "the" |
| `tag [reverse] [N]`, regex `/^sort by tag( reverse)?[\s]*(\d+)?/i` | compares the N-th tag (default 1) in description order with `localeCompare*`. Tasks with no tags come last. Tasks with fewer than N tags come after those that have N. `sort by tag 2 reverse` **ignores** `reverse`, because it must come before N |
| `urgency` | `b.urgency - a.urgency`, i.e. **highest first** |
| `random` | `hash(a) - hash(b)`. `hash(s)`: `h=9; for each char: h=Math.imul(h ^ s.charCodeAt(i), 9**9); return h ^ (h>>>9)`. `s = moment().format('Y-MM-DD') + ' ' + task.description`, so the order is stable within a day (`RandomField.ts`) |
| `function [reverse] <js>` | JS sort key. Disabled by default. `null` sorts first, `true` before `false`, strings use `localeCompare*`, dates use `compareByDate` (`FunctionField.ts`) |

There is **no** sorting by `folder`, `root`, `backlink`, `recurrence`, `tags`
as a set, or `blocking`. Such lines fail as `do not understand query`.

### 4.3 Default order (`src/Query/Sort/Sort.ts:13-33`)

The final comparator is: the user's `sort by` lines in written order (global
query first), then **always**
`status.type`, `urgency`, `due`, `priority`, `path`, each ascending. The first
non-zero result wins. `Array.prototype.sort` is stable, so remaining ties keep
the input order: the cache's task order, which is file by file, top to
bottom.

### 4.4 Urgency (`src/Task/Urgency.ts`)

```js
u = 0
if (due valid) {
  daysOverdue = Math.round(moment().startOf('day').diff(due) / 86400000)  // local days; Math.round absorbs DST 23/25h
  m = daysOverdue >= 7 ? 1.0 : daysOverdue >= -14 ? ((daysOverdue + 14) * 0.8) / 21 + 0.2 : 0.2
  u += m * 12.0
}
if (scheduled valid && moment().isSameOrAfter(scheduled)) u += 5.0   // scheduled today or earlier (now vs midnight)
if (start valid && moment().isBefore(start)) u += -3.0               // start date tomorrow or later
u += { Highest: 1.5*6, High: 1.0*6, Medium: 0.65*6, None: 0.325*6, Low: 0, Lowest: -0.3*6 }[priority]
```

- Due today gives 8.8 (14·0.8/21+0.2 = 0.7333…, times 12).
- Overdue by 7 days or more gives 12. Due 14 or more days ahead gives 2.4.
- Invalid or missing dates contribute 0.
- Do the arithmetic in JS doubles as written: `0.325*6 = 1.9500000000000002`.
  Comparators use the raw number, and display and grouping use `toFixed(2)`.

---

## 5. Grouping

### 5.1 Recognition

The regex per field is `new RegExp('^group by ' + escape(field) + '( reverse)?$', 'i')`.
It is **anchored**, so there is exactly one space before `reverse` and nothing
may follow. For tags the field word is the plural only: `group by tags`, never
`group by tag`. The function form is `^group by function( reverse)? (.*)`.

### 5.2 Group names

| `group by …` | name(s) per task |
|---|---|
| `status` | `Done` or `Todo` |
| `status.name` | the raw status name |
| `status.type` | `%%1%%IN_PROGRESS` … `%%7%%EMPTY` (§4.2) |
| `recurring` | `Recurring` / `Not Recurring` |
| `priority` | `%%0%%Highest priority`, `%%1%%High priority`, `%%2%%Medium priority`, `%%3%%Normal priority`, `%%4%%Low priority`, `%%5%%Lowest priority` (`Task.ts:627-632`) |
| `due`, `scheduled`, `start`, `created`, `done`, `cancelled`, `happens` | `date.format('YYYY-MM-DD dddd')`, e.g. `2026-10-13 Tuesday` (`dddd` follows the moment locale); null gives `No <f> date` (e.g. `No start date`); invalid gives `%%0%% Invalid <f> date`. `happens` uses the earliest valid date, so it is never "invalid" |
| `path` | `path.replace('.md','')` (first occurrence), then escape |
| `folder` | `task.file.folder`, escaped |
| `root` | `task.file.root`, escaped |
| `filename` | `[[<name without .md>]]`, or `Unknown Location` |
| `backlink` | `[[<file>]]`, or `[[<file>#<heading>|<file> > <heading>]]`, or `Unknown Location` |
| `heading` | the heading, or `(No heading)` if null or empty |
| `tags` | **one group per tag** (`#a`, `#a/b`, …), or `(No tags)` |
| `recurrence` | `recurrence.toText()`, or `None` |
| `id` | the raw id (`''`, an empty heading, if none) |
| `urgency` | `urgency.toFixed(2)` |
| `function <js>` | the expression result: an array gives several groups; `null` gives `[]`, treated as `''`; a non-integer number is `toFixed(5)`; anything else is `toString()`. A thrown error becomes the group name `Error: Failed calculating expression "…". The error message was: …`. Disabled by default |

- "Escape" means `s.replace(/\\/g,'\\\\').replace(/_/g,'\\_')`
  (`TextField.ts:126`), so `_` is not read as italics when the heading is
  rendered.
- `%%…%%` is an Obsidian comment. It is part of the name and so drives
  ordering, but it is **hidden when the heading is rendered** as Markdown. A
  re-implementation should sort on the full string and display the string with
  `/%%.*?%%/g` removed.
- `description`, `random`, `blocking` and `tag` (singular) do not group, and
  fail as `do not understand query`.

### 5.3 Building and ordering groups (`src/Query/Group/*`)

- The input is the **sorted and limited** task list (§3.1). For each grouper
  in order, each task is placed under every name the grouper returns, and an
  empty array becomes `['']`. A task with several tags therefore appears once
  under **each** tag. A duplicated tag (`#a … #a`) puts the task **twice** in
  the same group, because there is no de-duplication (`TaskGroupingTree.ts`).
- Leaves are flattened into paths (`[name1, name2, …]`). The groups are then
  sorted by comparing each path level with `localeCompare*`. At the first
  difference, the result is negated if that level's grouper has `reverse`
  (`TaskGroups.ts:102-117`). Consequences:
  - Dates order chronologically. `%%0%% Invalid…` comes first, because
    punctuation sorts before digits, and `No … date` comes last.
  - `Done` comes before `Todo`, and `Not Recurring` before `Recurring`.
  - Priorities and status types order by their `%%n%%` prefixes.
- **Urgency is the exception**: `group by urgency` is created with
  `reverse = true`, giving highest urgency first, and `group by urgency
  reverse` gives lowest first (`UrgencyField.ts`). The order is string-numeric
  `localeCompare*`, so **negative urgencies mis-order** (`-3.00` sorts after
  `-1.80`).
- Within a group, tasks keep the §4 sort order.
- Headings: a heading is emitted for a level only when its name differs from
  the previous group's name at that level, or when a higher level changed
  (`GroupDisplayHeadingSelector.ts`). Level k is rendered as `#` × min(4+k, 6),
  so h4, h5 and h6 for every deeper level.
- With no `group by`, there is one unnamed group and no headings.

---

## 6. What the query sees

### 6.1 The task set

- The task set is every **Task** in the vault cache: checkbox list items that
  Obsidian recognises, in `.md` files, outside code, comments and
  frontmatter. When a global filter is set, a line is a Task only if it
  contains the global filter substring (`tasks-plugin-spec.md` §1).
- Non-task list items are never results. They do appear as children when
  `show tree` is on.
- The query's own file is not special. Tasks in the same note are included.
- `allTasks`, used by `is blocked`, `is blocking` and functions, is this full
  set **before** any query filter (`src/Query/SearchInfo.ts`,
  `Query.ts:363`).

### 6.2 Heading

`precedingHeader` is the text of the **last Obsidian heading whose start line
is ≤ the task's line**, of any level, or `null` if there is none
(`src/Obsidian/Cache.ts:427-441`). The text is Obsidian's
`HeadingCache.heading`: no leading `#`s, inline Markdown kept. Headings inside
code blocks are not headings.

### 6.3 File-derived values (`src/Scripting/TasksFile.ts`, `src/Task/ListItem.ts:234-241`)

| value | rule | `a/b/c.md` | `c.md` |
|---|---|---|---|
| path | vault-relative, including the extension | `a/b/c.md` | `c.md` |
| filename (filter) | `/([^/]+)\.md$/` group 1, plus `.md`; `''` if there is no `.md` | `c.md` | `c.md` |
| folder | `path.substring(0, path.lastIndexOf(filename))`, or `'/'` if that is empty | `a/b/` | `/` |
| root | change `\` to `/`, drop a leading `/`, then everything up to and including the first `/`, or `'/'` if there is none | `a/` | `/` |

### 6.4 Parent / sub-item

- `exclude sub-items` uses **only the indentation text** (§2.5). It never
  uses the parent link.
- The parent/child tree, used only by `show tree` and scripting, comes from
  Obsidian's `listItem.parent` (`src/Obsidian/FileParser.ts:134-141`).

---

## 7. Most common instructions in the docs (implement these first)

Counted from instruction lines inside ` ```tasks ` and ` ```text ` fences
under `docs/`. Error and explain output lines are excluded.

1. Boolean combinations `(…) AND|OR|NOT (…)`: 72
2. `not done`: 48
3. `<date field> <date>` with an implicit `on` (`due today`, `happens this week`, …): 19, plus 4 with an explicit `on`
4. `description includes …`: 19
5. `<date field> before …`: 18
6. `filename includes …`: 17
7. `path includes …`: 16
8. `explain`: 11
9. `folder includes …`: 9
10. `description regex matches /…/`: 9
11. `hide …` / `show …`: 9 / 5
12. `<date field> after …`: 7
13. `root includes …`: 6
14. `priority is …`: 5
15. `sort by due`, `sort by path`, `group by path`, `preset …`: 4 each, followed by `sort by status.type`, `no <f> date`, `heading includes`, `is not blocked`, `limit`, `group by heading`, `group by folder`
