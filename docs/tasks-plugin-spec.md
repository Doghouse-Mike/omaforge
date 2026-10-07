# Obsidian Tasks 8.4.0 task-line behaviour spec (for omaforge)

What the Obsidian **Tasks** plugin 8.4.0 reads from and writes to a task line,
extracted from its source so an external editor can produce the same bytes Tasks
would.

**Sources** (citations use these prefixes):

- `src/…:N`: obsidian-tasks at tag 8.4.0 (`package.json` version 8.4.0, HEAD `a015261`).
- `rrule/…:N`: `rrule@2.8.1` (the version pinned by Tasks' `yarn.lock:8348`),
  `dist/esm/nlp/{parsetext,totext,i18n,index}.js`. **The text in the 🔁 field
  goes through this library, not through Tasks code.**
- `tests/…`: Tasks' own unit tests, used where they pin down a behaviour.

**Reference settings.** The "Default" column shows Tasks' built-in defaults
(`src/Config/Settings.ts:117-141`). The "Reference" column shows the settings
of the vault this spec was checked against.

| setting | Default | Reference | affects |
|---|---|---|---|
| `taskFormat` | `tasksPluginEmoji` | `tasksPluginEmoji` | which serializer (§3 vs §4) |
| `globalFilter` | `""` | `""` | which lines count as tasks (§1.3) |
| `removeGlobalFilter` | false | false | rendering only, never the file |
| `setCreatedDate` | **false** | **true** | ➕ on new tasks and on new recurrences (§6.3, §8) |
| `setDoneDate` | true | true | ✅ (§6.2) |
| `setCancelledDate` | true | true | ❌ (§6.2) |
| `recurrenceOnNextLine` | false | false | line order after recurrence (§7.6) |
| `removeScheduledDateOnRecurrence` | false | false | §7.3, §7.4 |
| `useFilenameAsScheduledDate` | false | false | inferred ⏳, never written (§9) |
| statuses | `' '`,`x` core; `/`,`-` custom | same | §5 |

Contents: 1 finding tasks · 2 line anatomy · 3 emoji format · 4 Dataview format ·
5 statuses · 6 status change · 7 recurrence · 8 created date & modal · 9 Obsidian-only features ·
10 rrule text (🔁) · 11 Python porting traps · 12 oracle.

---

## 1. Which lines are tasks

### 1.1 Obsidian decides first

Tasks does **not** scan files with its own regex. For each `.md` file it takes
Obsidian's `metadataCache` `listItems` and only parses entries with
`listItem.task !== undefined` (`src/Obsidian/FileParser.ts:68-125`,
`src/Obsidian/Cache.ts:302-308`). So whether a line is a task depends on
Obsidian's Markdown parser:

- **Not tasks:** lines inside fenced or indented code blocks (including
  Admonition-style code blocks), YAML frontmatter, `%% … %%` and `<!-- … -->`
  comments, and Canvas cards. Only `.md` files are read (docs *Getting Started*
  §"Tasks in Code Blocks / Comments / Canvas / Supported file names").
- **Tasks:** list items in blockquotes and callouts (`> - [ ] x`), and list items
  at any nesting depth.
- A list item must also sit inside a metadata `section`, otherwise it is skipped
  (`FileParser.ts:91-94`).
- Not verified here: Obsidian probably needs the `]` to be followed by
  whitespace or end-of-line before it sets `task`. Tasks' own regex does not need
  that (see 1.2). Check edge cases against `metadataCache` (§12).

omaforge has no metadataCache, so it needs a CommonMark-ish pre-pass that skips
fences, frontmatter and comments. Difftest that pass against
`app.metadataCache.getFileCache(f).listItems` on the test vault.

### 1.2 Then the line regex (`src/Task/TaskRegularExpressions.ts`)

```js
indentationRegex   = /^([\s\t>]*)/                      // :6  includes '>' for blockquotes/callouts
listMarkerRegex    = /([-*+]|[0-9]+[.)])/               // :9  -, *, +, 1., 1)
checkboxRegex      = /\[(.)\]/u                         // :12 exactly one code point (any, incl. space)
afterCheckboxRegex = / *(.*)/u                          // :15
taskRegex = new RegExp(indentation + listMarker + ' +' + checkbox + afterCheckbox, 'u')   // :24-31
//  => /^([\s\t>]*)([-*+]|[0-9]+[.)]) +\[(.)\] *(.*)/u
//     groups: 1 indentation, 2 listMarker, 3 status char, 4 rest
blockLinkRegex     = / \^[a-zA-Z0-9-]+$/u               // :56 needs a leading space
hashTags           = /(^|\s)#[^ !@#$%^&*(),.?":{}|<>]+/g                 // :67
hashTagsFromEnd    = /(^|\s)#[^ !@#$%^&*(),.?":{}|<>]+$/   (no flags)    // :68
listItemRegex      = /^([\s\t>]*)([-*+]|[0-9]+[.)])/    // :51 (Toggle Done on non-tasks)
nonTaskRegex       = /^([\s\t>]*)([-*+]|[0-9]+[.)])? *(\[(.)\])? *(.*)/u   // :40 (Create/Edit modal)
```

`Task.extractTaskComponents` (`src/Task/Task.ts:284-310`):

1. Run `taskRegex`. No match means not a task.
2. `status = StatusRegistry.bySymbolOrCreate(group3)` (§5).
3. `body = group4.trim()`.
4. If `body` matches `blockLinkRegex`, set `blockLink = match[0]` (**with** its
   leading space, e.g. `" ^abc-1"`) and `body = body.replace(blockLinkRegex,'').trim()`.

There is **no `$` anchor** on `taskRegex`, and JS `.` does not match `\r`. On a
CRLF file the `\r` is silently excluded from the body.

### 1.3 Global filter

`Task.fromLine` (`Task.ts:204-226`): when the filter is non-empty and
`!body.includes(globalFilter)` (plain substring test, `src/Config/GlobalFilter.ts`
`includedIn`), the line is **not** a Tasks task. It is then an ordinary list
item. Toggle Done flips it as plain Markdown (§6.5). A tag equal to the global
filter is dropped from `task.tags` (`Task.ts:268`) but stays in the description.
The reference vault has an empty filter, so every checkbox line is a task.

---

## 2. Line anatomy and how a line is rewritten

```
<indentation><listMarker> [<status>] <description><fields…><blockLink><hardBreak>
```

`toFileLineString` (`Task.ts:327-334`):

```js
`${indentation}${listMarker} [${status.symbol}] ${serializer.serialize(task)}${markdownHardBreak}`
```

- Indentation (including `> ` prefixes) and the list marker text (`-`, `*`, `+`,
  `12.`, `3)`) are kept verbatim. **The space between the marker and `[` is
  normalised to exactly one**, and so is the space after `]`.
  `-   [ ]   foo` becomes `- [ ] foo`.
- `markdownHardBreak` (`src/Task/ListItem.ts:292-303`): if the *original* line
  ends with ≥2 spaces, exactly that run of trailing spaces is re-appended.
  Otherwise nothing is appended (a single trailing space is dropped). A new
  recurrence line inherits it, because it is built from the same `originalMarkdown`.
- **Any status change rewrites the whole line canonically** (field order, tag
  position, recurrence text, emoji variants). This happens even when the status
  is unchanged, because the `[this]` path is still serialised. An editor that
  wants to match Tasks must re-serialise too, not patch the checkbox character alone.
- An empty description gives two spaces: `- [ ]  📅 2024-01-01`
  (`' ' + ''` + `' 📅 …'`).

---

## 3. Emoji format (`tasksPluginEmoji`), `src/TaskSerializer/DefaultTaskSerializer.ts`

### 3.1 Symbols and regexes (`:84-117`, built by `fieldRegex` `:64-78`)

Each field regex is `symbol + '️?' + (value ? ' *' + value : '') + '$'`,
with **no `u` flag** (`:77`). Verbatim (from the inline snapshot in
`tests/TaskSerializer/DefaultTaskSerializer.test.ts:61-77`):

```
priorityRegex:      /(🔺|⏫|🔼|🔽|⏬)️?$/
startDateRegex:     /🛫️? *(\d{4}-\d{2}-\d{2})$/
createdDateRegex:   /➕️? *(\d{4}-\d{2}-\d{2})$/
scheduledDateRegex: /(?:⏳|⌛)️? *(\d{4}-\d{2}-\d{2})$/
dueDateRegex:       /(?:📅|📆|🗓)️? *(\d{4}-\d{2}-\d{2})$/
doneDateRegex:      /✅️? *(\d{4}-\d{2}-\d{2})$/
cancelledDateRegex: /❌️? *(\d{4}-\d{2}-\d{2})$/
recurrenceRegex:    /🔁️? *([a-zA-Z0-9, !]+)$/
onCompletionRegex:  /🏁️? *([a-zA-Z]+)$/
dependsOnRegex:     /⛔️? *([a-zA-Z0-9-_]+( *, *[a-zA-Z0-9-_]+ *)*)$/
idRegex:            /🆔️? *([a-zA-Z0-9-_]+)$/
```

(`taskIdRegex = /[a-zA-Z0-9-_]+/` `:59`; the `-` after `0-9` is a literal hyphen.)

| field | written symbol | also read | priority values |
|---|---|---|---|
| priority | — | optional U+FE0F | 🔺 Highest, ⏫ High, 🔼 Medium, 🔽 Low, ⏬ Lowest; none = Normal |
| start | 🛫 | | |
| created | ➕ | | |
| scheduled | ⏳ | ⌛ | |
| due | 📅 | 📆 🗓 | |
| done | ✅ | | |
| cancelled | ❌ | | |
| recurrence | 🔁 | | |
| onCompletion | 🏁 | `keep`/`delete` (case-insensitive; anything else = Ignore, `src/Task/OnCompletion.ts:10-19`) | |
| dependsOn | ⛔ | | |
| id | 🆔 | | |

Priority enum (`src/Task/Priority.ts`): Highest `'0'`, High `'1'`, Medium `'2'`,
None `'3'`, Low `'4'`, Lowest `'5'`. Display names: Highest/High/Medium/Normal/Low/Lowest
(`src/lib/PriorityTools.ts`).

Note: there is **no space requirement before a symbol**. `foo📅2024-01-01` and
`foo⏫` parse. Neither is there one before the value (` *`).

### 3.2 Deserialize: the right-to-left loop (`:299-407`)

Input is the `body` from §1.2, with the block link already removed. Pseudocode,
exact order:

```
line = body; trailingTags = ''; runs = 0
do {
  matched = false
  for each step in this order:            // each: m = line.match(re); if m: set; line = line.replace(re,'').trim(); matched = true
     1 priority     -> parsePriority(m[1])
     2 done date    3 cancelled date   4 due date   5 scheduled date   6 start date   7 created date
     8 recurrence   -> recurrenceRule = m[1].trim()        (text only; parsed after the loop)
     9 onCompletion -> parseOnCompletionValue(m[1])
    10 tag          (hashTagsFromEnd) -> trailingTags = m[0].trim() + (trailingTags ? ' ' + trailingTags : '')
    11 id           -> m[1].trim()
    12 dependsOn    -> m[1].replace(/ /g,'').split(',').filter(x => x !== '')
  runs++
} while (matched && runs <= 20)            // maxRuns = 20  => at most 21 passes (:325, :373)
if recurrenceRule: recurrence = Recurrence.fromText(rule, Occurrence{start, scheduled, due})   // §7.1
if trailingTags:   line += (line.length ? ' ' : '') + trailingTags
description = line
tags = description.match(hashTags).map(trim)     // Task.extractHashtags
```

Consequences:

- Every step is anchored with `$`, so one pass consumes several fields **only
  if they happen to appear in reverse step order**. Otherwise the loop runs
  again. Parsing stops at the first pass where nothing at the end of the line is
  recognised. **Any unrecognised text after a field hides that field and
  everything to its left** (it stays in the description). Only tags and the
  block link may follow fields.
- **Duplicate fields:** each one is removed. Assignments happen right to left,
  so **the leftmost occurrence wins**.
- **Tags interleaved with fields are moved.**
  `Do #a 📅 2024-01-01 #b` parses to description `Do #a #b` and is rewritten as
  `Do #a #b 📅 2024-01-01`. The trailing tags are re-joined with single spaces,
  so the whitespace between them is normalised. Tags inside the description
  (followed by ordinary text) are left alone.
- The recurrence value charset is `[a-zA-Z0-9, !]` only. Rule text containing
  `-`, `/`, `.` or `:` (for example `until 2025-12-31`) **does not match**, and
  stays in the description.
- Dates are read with `moment(str, 'YYYY-MM-DD')`, which is non-strict but flags
  overflow. `2024-02-30` and `2024-13-01` become **invalid** moments: not null,
  and they serialize as the literal `Invalid date` (§3.3).
- The description is whatever is left, after `trim()`. Inner whitespace is
  preserved.
- After parse, `parseTaskSignifiers` (`Task.ts:243-277`) applies the filename
  fallback (§9), trims the tags, and drops the global-filter tag.

### 3.3 Serialize (`:160-242`; order from `src/Layout/TaskLayoutOptions.ts:7-22`)

Components are emitted in this fixed order, each prefixed by **one space**, and
skipped when empty:

```
description, 🆔 id, ⛔ dependsOn, priority, 🔁 rule, 🏁 onCompletion,
➕ created, 🛫 start, ⏳ scheduled, 📅 due, ❌ cancelled, ✅ done, blockLink
```

- description: verbatim, with no leading space (tags are part of it; there is
  no separate tags component).
- dates: `" " + symbol + " " + date.format('YYYY-MM-DD')`. An invalid date
  prints `Invalid date`. Scheduled is skipped when `scheduledDateIsInferred`.
- priority: `" " + emoji`, with no value.
- recurrence: `" 🔁 " + recurrence.toText()` (rrule text, plus `" when done"`, §10).
  **A rule that failed to parse has `recurrence === null` and is omitted. The
  🔁 text is deleted from the line.**
- onCompletion: `" 🏁 keep"` or `" 🏁 delete"`, omitted when Ignore (`''`).
- dependsOn: `" ⛔ " + ids.join(',')`, with no spaces.
- id: `" 🆔 " + id`.
- blockLink: appended as stored (it already starts with a space).
- Canonical symbols are always written: `⌛` becomes `⏳`, `📆`/`🗓` become
  `📅`, and U+FE0F is dropped.

Fully populated example (Dataview equivalent in
`tests/TaskSerializer/DataviewTaskSerializer.test.ts:349-353`):

```
Do exercises #todo #health 🆔 abcdef ⛔ 123456,abc123 🔼 🔁 every day when done 🏁 delete ➕ 2023-07-01 🛫 2023-07-02 ⏳ 2023-07-03 📅 2023-07-04 ❌ 2023-07-06 ✅ 2023-07-05 ^dcf64c
```

---

## 4. Dataview format (`taskFormat: dataview`), `src/TaskSerializer/DataviewTaskSerializer.ts`

The same loop and order as §3, with different symbols and regexes (`:62-95`).
**Only one format is active.** In emoji mode `[due:: …]` is plain description
text, and in Dataview mode `📅 …` is.

| field | key | value regex |
|---|---|---|
| priority | `priority::` | `(highest\|high\|medium\|low\|lowest)` (case-sensitive) |
| start / created / scheduled / due | `start::` `created::` `scheduled::` `due::` | `(\d{4}-\d{2}-\d{2})` |
| done | **`completion::`** | date |
| cancelled | `cancelled::` | date |
| recurrence | `repeat::` | `([a-zA-Z0-9, !]+)` |
| onCompletion | `onCompletion::` | `([a-zA-Z]+)` |
| dependsOn | `dependsOn::` (case-sensitive) | id sequence |
| id | `id::` | `([a-zA-Z0-9-_]+)` |

Each inner `key:: *(value)` is wrapped by `toInlineFieldRegex` (`:16-56`). For
example, due becomes:

```
(?:(?=[^\]]+\])\[|(?=[^)]+\))\() *due:: *(\d{4}-\d{2}-\d{2}) *[)\]](?: *,)?$
```

The field opens with `[` (only if a `]` follows somewhere) or `(` (only if a
`)` follows). Spaces are allowed inside the brackets and after `::`. It closes
with `]` or `)`, and an optional trailing `,` is allowed. Bare `due:: x`
without brackets is not recognised.

Serialize (`:110-123`): each non-empty, non-description, non-blockLink component
becomes **two spaces** + `[` + component.trim() + `]`:
`Do it  [priority:: high]  [repeat:: every day]  [due:: 2023-07-04] ^abc`.
Parsing accepts `(…)` and missing spaces, but writing always uses `[key:: value]`.

---

## 5. Statuses (`src/Statuses/*`)

`StatusType` (`StatusConfiguration.ts`): `TODO`, `DONE`, `IN_PROGRESS`, `ON_HOLD`,
`CANCELLED`, `NON_TASK`, `EMPTY`. A status is
`{symbol, name, nextStatusSymbol, availableAsCommand, type}`.

Built-ins (`Status.ts:23-80`):

| symbol | name | next | type |
|---|---|---|---|
| `' '` | Todo | `x` | TODO |
| `x` | Done | `' '` | DONE |
| `/` | In Progress | `x` | IN_PROGRESS |
| `-` | Cancelled | `' '` | CANCELLED |
| `h` | On Hold | `' '` | ON_HOLD (not registered by default) |
| `Q` | Non-Task | `A` | NON_TASK (not registered by default) |
| `''` | EMPTY | `''` | EMPTY (internal) |

**Registry** (`StatusRegistry.ts`, `src/Config/StatusSettings.ts:170-184`): it
is cleared, then `coreStatuses` and then `customStatuses` from `data.json`
(`statusSettings`) are added in order. **The first entry with a given symbol
wins; later duplicates are ignored** (`add` `:79`). A `type` string that is not
recognised maps to TODO (`Status.ts` `getTypeFromStatusTypeString`).

**Unknown symbols** (`bySymbolOrCreate` `:119`, `createUnknownStatus` `Status.ts:233`):
`{symbol, name:'Unknown', next:'x', type: TODO}`. This includes **`[X]`
(uppercase)** whenever `X` is not configured: Tasks treats `- [X]` as **not
done**, and toggles it to `x` with a done date. (`getTypeForUnknownSymbol`,
which maps X to DONE, is used only by the settings report, not when parsing.)

**Toggle** (`Task.toggle` `:352-362`): `newStatus = getNextStatusOrCreate(status)`.
That is the registered status whose symbol is `status.nextStatusSymbol`. If none
is registered, a new Unknown TODO status with that symbol is used (`:181-187`).

Predicates: `isCompleted()` means `type === DONE` only (`Status.ts:254`).
`Task.isDone` means DONE, CANCELLED or NON_TASK (`Task.ts:544-550`); it is used
for dependencies.

---

## 6. Changing status: `handleNewStatus(newStatus, today = moment())` (`Task.ts:387-429`)

### 6.1 No-op

If `newStatus.identicalTo(this.status)` (all five config fields are equal),
Tasks returns `[this]` and no dates change. The line is still re-serialised (§2).

### 6.2 Done and cancelled dates (`newDate` `:437-457`)

These are computed independently for DONE (✅, `setDoneDate`) and CANCELLED
(❌, `setCancelledDate`):

| new type = T? | old type = T? | result |
|---|---|---|
| yes | no | `today` if the setting is on, else **null** |
| yes | yes | old date kept (even if null) |
| no | — | **null** (the date is removed) |

So: TODO→DONE adds ✅ today. DONE→TODO removes ✅. DONE→CANCELLED removes ✅
and adds ❌. `x`→another DONE-type symbol keeps the ✅. Moving to IN_PROGRESS,
ON_HOLD or NON_TASK removes both. `today` is the local calendar date. Nothing
else changes on the toggled task: created, priority, id, dependsOn, recurrence
text and block link all stay.

### 6.3 Whether a recurrence is created (`:412-429`)

A next occurrence is created only if **all** of these hold:
`newStatus.type === DONE`, `oldStatus.type !== DONE`, the task has a
`recurrence` (a rule that parsed), and `recurrence.next(today)` is non-null.
CANCELLED, IN_PROGRESS and the rest never create one, and neither does
DONE→DONE. Un-completing a task never deletes a previously created next
occurrence. Result: `[nextTask, toggledTask]`. §7 covers the details and §7.6
the output order.

### 6.4 onCompletion (`src/Task/OnCompletion.ts:35-61`, applied in `putRecurrenceInUsersOrder` `Task.ts:525-529`)

Applied **before** any reversal for `recurrenceOnNextLine`. When
`originalTask.onCompletion === 'delete'` **and** the last element (the toggled
task) has type DONE **and** its type differs from the original's, the toggled
task is removed from the result.

- Non-recurring task: the result is `[]`, so **the line is deleted** (newline
  included; `CreateEditorCallback.ts:98`, `File.ts:170`).
- Recurring task: only the new occurrence remains. It carries `🏁 delete` too,
  because the field is copied.
- CANCELLED (or any status that is not DONE) with `🏁 delete` keeps the line.
  `keep` and Ignore never remove anything.

### 6.5 Lines that are not Tasks tasks (`src/Commands/ToggleDone.ts:11-47`)

The Toggle Done command, on a checkbox line that lacks the global filter,
replaces with `$1$2 [x|space] $4`. The status becomes `x` iff it was `' '`,
otherwise `' '`. No dates are added. On a plain list item it inserts `[ ] `
after the marker. On any other line it prepends `- [ ] ` after the
indentation. Only relevant when a global filter is set.

---

## 7. Recurrence in full (`src/Task/Recurrence.ts`, `src/Task/Occurrence.ts`)

### 7.1 Parsing the rule (`Recurrence.fromText` `:15-54`)

```js
match = ruleText.match(/^([a-zA-Z0-9, !]+?)( when done)?$/i)   // null → no recurrence
isolated = match[1].trim(); baseOnToday = match[2] !== undefined   // " when done", any case
options = RRule.parseText(isolated)                                // §10.1; throws or null → no recurrence
ref = occurrence.referenceDate                                     // §7.2
options.dtstart = (!baseOnToday && ref) ? UTCmidnight(ref date) : UTCmidnight(today)
rrule = new RRule(options)          // throws on an invalid dtstart (e.g. due 2024-02-30) → no recurrence
```

Any exception results in `null`. **If parsing fails, the 🔁 field disappears the
next time Tasks writes the line**, because §3.2 already stripped it from the
description and §3.3 writes nothing. Examples that fail: rules that do not start
with `every`, `every two days` (word numbers are tokenised but never accepted),
`every 2nd day`, `every second week`, and any rule whose reference date is
invalid (documented in docs *Recurring Tasks* "Recurrence rule lost…").

The occurrence used here is `{start, scheduled, due}` exactly as parsed. A
filename-inferred scheduled date is **not** included, because it is applied
after deserialize (`Task.ts:257-262`).

### 7.2 Reference date (`Occurrence.ts:42-80`)

The reference date is the first non-null of
`[due, scheduled, start]`, or `[due, start, scheduled]` when
`removeScheduledDateOnRecurrence` is on. "Non-null" does not mean "valid": an
invalid lower-priority date still counts as present.

### 7.3 The next reference date (`Recurrence.next` `:70-121`)

All of this is calendar-date arithmetic. The code converts to UTC midnight so
that rrule never sees a time zone (`:143-168`, `addTimezone` `:261-277`).

- **Normal rule:** `after = endOfDay(ref)` (`ref` = today if there is none),
  `next = rrule.after(after)`. That is the first rule date strictly after the
  reference date, with the rule anchored at `dtstart = ref`.
- **`when done`:** a copy of the rule with `dtstart = today`, and
  `next = first rule date strictly after today`.
- **Monthly clamp** (`:151-158`, `nextAfterMonths` `:175-208`): applies when
  `toText()` matches `/every( \d+)? month(s)?(.*)?/` **and does not contain
  `" on "`** (that is, `every month`, `every 3 months`, `every month when done`).
  If rrule skipped more than N months, Tasks steps `after` back one day at a
  time (re-anchoring dtstart) until it does not. The net effect is **the same
  day-of-month N months later, clamped to that month's last day**: Jan 31 +
  `every month` gives Feb 28 (2022), and 2022-01-31 + `every 3 months` gives
  2022-04-30 (`tests/Task/Recurrence.test.ts:25-130`). Rules that pin the day
  (`on the 31st`) are not clamped and **skip** short months: Jan 31 → Mar 31.
- **Yearly clamp** (`:160-164`, `:215-244`): applies whenever `toText()` matches
  `/every( \d+)? year(s)?(.*)?/` (even with `on`). The year difference must be
  ≤ N, so Feb 29 + `every year` gives Feb 28 and `every 2 years` from 2024-02-29
  gives 2026-02-28. Month-named rules (`every January on the 15th`) contain no
  `year` and are not clamped.
- If rrule has no next date (`for 1 time`, or `until` in the past),
  `rrule.after` returns null, and `moment.utc(null)` is an **invalid** date, not
  null. So `next()` does not return null. Reading the code, the new task's dates
  become `Invalid date`. This is not covered by Tasks' tests, so confirm it with
  the oracle before you rely on it.

### 7.4 Shifting the dates (`Occurrence.next` `:104-158`)

- If the occurrence has **no reference date** (no start, scheduled or due), the
  new task has no dates either. The rule still recurs; Tasks discourages this,
  but it works.
- Otherwise, for each of start, scheduled and due that is non-null:
  `new = nextRef + round(days(date − ref))`. Each date keeps its offset from
  the reference date. An invalid date has offset NaN and becomes `nextRef`
  (`tests/Task/Recurrence.test.ts:157-176`). Null dates stay null.
- `removeScheduledDateOnRecurrence && (start || due)` sets the new scheduled
  date to null. When scheduled is the only date it is kept.
- Done, cancelled and created dates are never shifted (§7.5).

Example (docs): `🔁 every 2 weeks ⏳ 2021-10-28 📅 2021-10-30` gives
`⏳ 2021-11-11 📅 2021-11-13`. Example (`Task.test.ts`):
`🔁 every year when done 📅 1989-12-23` completed on 2023-01-23 gives `📅 2024-01-23`.

### 7.5 The new task (`createNextOccurrence` `:459-491`)

The new task is `{...original, ...nextOccurrence}`, with these overrides:

| field | value on the new line |
|---|---|
| status | `getNextRecurrenceStatusOrCreate(doneStatus)` (below) |
| start/scheduled/due | from §7.4 |
| done ✅, cancelled ❌ | null |
| created ➕ | **today if `setCreatedDate`, else null.** The original's ➕ is *never* copied, even with the setting off (`Task.test.ts:1505-1514`) |
| id 🆔, dependsOn ⛔ | **cleared** |
| blockLink | **cleared** |
| description, tags, priority, 🔁 rule (same text), 🏁, indentation, list marker, hard break | copied |

Next status (`StatusRegistry.ts:202-235`): `n = getNextStatusOrCreate(done)`.
If `n` is TODO, use `n`. Otherwise follow `next` links up to
`registeredStatuses.length − 1` steps and take the first TODO. Failing that,
search the same way for IN_PROGRESS. Failing that, use `bySymbolOrCreate(' ')`.
With default statuses, `x` gives `' '`.

The ➕ uses the real clock even when the modal overrides `today` (§8). The
toggled line keeps its own ➕.

### 7.6 Output order (`putRecurrenceInUsersOrder` `Task.ts:525-529`)

The internal order is `[next, toggled]`. With `recurrenceOnNextLine: false` (the
default), the **new task is written above** the completed one. With `true`, the
list is reversed and the new task goes below. The lines replace the original
line in place, joined with `\n` (`File.ts:170-176`). Example (setCreatedDate on,
today 2023-03-08):

```
- [ ] this is a task 🔁 every day 📅 2021-09-12
→
- [ ] this is a task 🔁 every day ➕ 2023-03-08 📅 2021-09-13
- [x] this is a task 🔁 every day 📅 2021-09-12 ✅ 2023-03-08
```

---

## 8. Created date outside recurrence

Toggling **never** adds ➕ to the task being toggled. ➕ is added only:

- on new recurrences (§7.5), and
- by the *Create or edit task* modal or the API `createTaskLineModal`, when
  `setCreatedDate` is on, the task has no ➕ yet, and the description is empty
  or the global filter is about to be prepended (`src/Commands/CreateOrEditTaskParser.ts:13-59`).
  An existing task with text opened in the modal does **not** get one.

The modal (`src/ui/EditableTask.ts` `applyEdits`) builds the edited task, then
calls `handleNewStatusWithRecurrenceInUsersOrder(status, today)`. `today` is the
✅/❌ date typed into the modal, if any. New ids come from `generateUniqueId`:
`Math.random().toString(36).substring(2, 8)`, a 6-char `[0-9a-z]` id that is
unique among the vault's ids (`src/Task/TaskDependency.ts:3-17`). Ids may
legally contain `A-Z0-9-_`.

---

## 9. Behaviour that needs Obsidian or vault-wide context

| feature | needs | omaforge note |
|---|---|---|
| Which lines are tasks | metadataCache `listItems[].task` (§1.1) | emulate; difftest the edge cases |
| Block links `^id` | nothing to parse or preserve; resolving them is Obsidian's job | keep the `" ^id"` suffix and clear it on the new recurrence |
| Filename as scheduled date | `useFilenameAsScheduledDate` (+ `filenameAsDateFolders`, `filenameAsScheduledDateFormat`); `DateFallback.ts:15-66` | applies only when the task has no start, scheduled or due date. The date is **inferred, never written**, and does not feed recurrence. It is used for queries and urgency. The reference vault has it off |
| `isBlocked`/`isBlocking` (⛔/🆔) | all tasks in the vault (`Task.ts:559-605`) | blocked = has a dependsOn id matching a task that is not done (`isDone` = DONE/CANCELLED/NON_TASK) and the task itself is not done |
| Heading, section, backlink | metadataCache headings/sections | query display only |
| Callout checkbox click in Live Preview | Tasks cannot locate the line; no dates or recurrence get added | an Obsidian limitation; irrelevant to file edits |
| `🏁 delete` removal | none | §6.4 |

---

## 10. rrule.js text: what 🔁 can hold

### 10.1 `parseText` (`rrule/nlp/parsetext.js`, tokens in `rrule/nlp/i18n.js`)

**Tokeniser.** At each position every token regex is tried against the start
of the remaining text. The **longest match** wins, and ties go to the earlier
token in i18n order. `SKIP` (`/^[ \r\n\t]+|^\.$/`) is dropped. If nothing
matches, the input is treated as ended and **the rest of the text is silently
ignored**. All tokens are case-insensitive prefixes **without word boundaries**:

```
number /^[1-9][0-9]*/   nth /^([1-9][0-9]*)(\.|th|nd|rd|st)/i   numberAsText /^(one|two|three)/i (never accepted)
every  day(s) /^days?/  weekday(s) /^weekdays?/  week(s) /^weeks?/  hour(s) minute(s)  month(s) /^months?/  year(s) /^years?/
on /^(on|in)/  at  the  first second third  last  for  time(s)  until /^(un)?til/
monday /^mo(n(day)?)?/ tuesday /^tu(e(s(day)?)?)?/ wednesday /^we(d(n(esday)?)?)?/ thursday /^th(u(r(sday)?)?)?/
friday /^fr(i(day)?)?/ saturday /^sa(t(urday)?)?/ sunday /^su(n(day)?)?/
january /^jan(uary)?/ february /^feb(ruary)?/ march /^mar(ch)?/ april /^apr(il)?/ may /^may/ june /^june?/
july /^july?/ august /^aug(ust)?/ september /^sep(t(ember)?)?/ october /^oct(ober)?/ november /^nov(ember)?/ december /^dec(ember)?/
comma /^(,\s*|(and|or)\s*)+/i            // "and", "or" and "," are all separators
```

**Grammar** (`parsetext.js:85-208`):

```
S     := 'every' [number→interval] ( 'day(s)' AT F
                                   | 'weekday(s)' AT F            → WEEKLY, byweekday MO-FR
                                   | 'week(s)' ON AT F            → WEEKLY
                                   | 'month(s)' ON F | 'year(s)' ON F | 'hour(s)' ON F | 'minute(s)' ON F
                                   | WEEKDAY (comma WEEKDAY)* AT MDAYS F    → WEEKLY byweekday
                                   | MONTH (comma MONTH)* ON F              → YEARLY bymonth )
ON    := ['on'] ['the'] (at least one) ITEM ((comma|'the'|'on') ITEM)*   ; returns silently on the first non-item
ITEM  := NTH WEEKDAY → byweekday nth | NTH ['day(s)'] → bymonthday | WEEKDAY → byweekday
       | 'weekday(s)' → MO-FR | 'week(s)' number (comma number)* → byweekno | MONTH → bymonth
NTH   := 'last'(-1) | 'first'(1) | 'second'['last'](±2) | 'third'['last'](±3) | nth['last'](±n)
AT    := 'at' number (comma number)* → byhour
F     := 'until' <rest of text, via JS Date.parse> | 'for' number → count
```

Accepted examples: `every day`, `every 3 days`, `every weekday`,
`every week on Monday, Friday`, `every Tuesday and Friday`, `every 2 weeks on Mon`,
`every month on the 15th`, `every month on the last`, `every month on the last day`,
`every month on the first Monday`, `every month on the 2nd last Friday`,
`every January on the 15th`, `every April and December on the 1st and 24th`,
`every year`, `every day for 3 times`, `every week until January 1, 2026`.

**Traps:**

- Anything the grammar does not consume is **silently dropped**:
  `every day on Monday` parses as `every day`, `every year on January 15`
  as `every January` (a bare `15` is a `number`, not `nth`), and `every weekend`
  as `every week`.
- **Throws** (so the rule is lost, §7.1): a rule that does not start with `every`,
  `every` alone, word numbers, `every 2nd …`, `every second …`, and `until`
  followed by text that `Date.parse` rejects.

### 10.2 `toText` (`rrule/nlp/totext.js`)

The output is `'every'` followed by `' ' + part` for each part. Tasks appends
`' when done'` (`Recurrence.ts:56-63`). The rules that matter:

- `interval` is printed only when ≠ 1. Units are plural iff `n % 100 !== 1`.
- **DAILY:** `every day`, `every N days` (+ `at H` if byhour).
- **WEEKLY:** if the weekdays are exactly MO-FR: `every weekday` (interval 1)
  or `every N weeks on weekdays`. If all seven days: `every day`/`every N days`.
  Otherwise `every week` / `every N weeks`, then `on <Day>, <Day>` (joined with
  `", "`, never "and", **sorted Monday→Sunday**). For nth weekdays:
  `on the 2nd Tuesday`.
- **MONTHLY:** `every month` / `every N months`. Then
  `on the <nth> and <nth>` (monthdays: positives ascending, then negatives,
  joined `", "` with a final `" and "`), **or** `on weekdays`, **or**
  `on the <nth> <Day>`.
- **YEARLY with months:** `every [N years] <Month> and <Month>` followed by the
  monthday or weekday part. Without months: `every year` / `every N years` [...].
- nth: 1/21/31 → `st`, 2/22 → `nd`, 3/23 → `rd`, otherwise `th`. −1 → `last`,
  −n → `<nth> last`.
- `until`: `until <MonthName> <d>, <yyyy>` using the **UTC** fields of the
  until date. `count`: `for N times` / `for 1 time`.
- `(~ approximate)` is never produced for rules that came from `parseText`.
  `freq` is always among the first keys, so `isFullyConvertible` returns true.

Round-trip table (input in the file → what Tasks writes after any rewrite):

| input | written |
|---|---|
| `every day` / `Every Day` / `every 1 day` | `every day` |
| `every 3 days` | `every 3 days` |
| `every weekday` / `every week on weekdays` | `every weekday` |
| `every 2 weekdays` | `every 2 weeks on weekdays` |
| `every week` | `every week` |
| `every Monday` / `every mon` / `every week on monday` | `every week on Monday` |
| `every Sunday, Monday` / `every week on Monday and Sunday` | `every week on Monday, Sunday` |
| `every week on Monday, Wednesday and Friday` | `every week on Monday, Wednesday, Friday` |
| `every 2 weeks on Tuesday, Friday` | `every 2 weeks on Tuesday, Friday` |
| `every month` / `every 2 months` | `every month` / `every 2 months` |
| `every month on the 1st` / `…the first` / `…the 1.` | `every month on the 1st` |
| `every month on the 1st and 15th` | `every month on the 1st and 15th` |
| `every month on the last` / `…last day` | `every month on the last` |
| `every month on the 2nd last` | `every month on the 2nd last` |
| `every month on the first Monday` | `every month on the 1st Monday` |
| `every month on the last Friday` | `every month on the last Friday` |
| `every 6 months on the 2nd Wednesday` | `every 6 months on the 2nd Wednesday` |
| `every January on the 15th` / `every jan on the 15th` | `every January on the 15th` |
| `every April and December on the 1st and 24th` | unchanged |
| `every year` / `every 2 years` | unchanged |
| `every day for 3 times` | `every day for 3 times` |
| `every week until June 1, 2026` | `every week until May 31, 2026` **when the local zone is ahead of UTC** (e.g. UK summer time). `Date.parse` gives local midnight and toText prints UTC, so each rewrite moves the date back one day. Known bug, docs *Recurring Tasks* "No way to recur until a specific date", issue #1818 |
| `every week when done` / `… WHEN DONE` | `every week when done` |
| `daily`, `every two days`, `every 2nd day` | **removed from the line** |

`for N times` is meaningless in Tasks: each new line re-parses the rule with a
fresh dtstart, so the count restarts. `for 1 time` yields invalid dates (§7.3).
Hourly and minutely rules parse, but the next date is still the next calendar
day after the reference.

---

## 11. Porting traps (JS → Python)

- **`$`:** Python's `$` also matches before a trailing `\n`. Use `\Z`, or make
  sure lines contain no newline.
- **`\d`:** Python's `\d` matches non-ASCII digits. Use `[0-9]` or `re.ASCII` for
  the date regexes.
- **`\s`:** JS includes U+FEFF and Python does not. Python includes
  `\x1c-\x1f` and JS does not. This matters for `indentationRegex` and
  `hashTags`.
- **`.`:** JS `.` excludes `\r` and U+2028/2029. Strip `\r` before matching.
- Emoji: the JS regexes have no `u` flag but match identically on code points.
  `[^ …]` in `hashTags` accepts every astral character in both languages.
- `str.replace(re, '')` in JS (no `g` flag) replaces the **first** match. Every
  field regex here is `$`-anchored, so that is the match at the end.
- moment `YYYY-MM-DD` non-strict parsing: a date is valid iff the month is
  1-12 and the day exists. Year `0000` is accepted. Serialize the invalid ones as
  `Invalid date`.
- rrule: port `parsetext`/`totext` literally (≈400 lines) rather than mapping to
  `dateutil.rrule.rrulestr`. Iteration can use `dateutil.rrule`
  (`wkst=MO`, the same default as rrule.js; it fills missing BYxxx from dtstart
  the same way), with `dtstart = date(ref)` and `after(ref, inc=False)`, plus
  §7.3's clamps. Watch for interval weeks: `every 2 weeks on Monday` anchored
  on a Wednesday gives the Monday **12** days later (week-of-dtstart counting).
- `until` drift (§10.2) depends on the local time zone. To match Tasks
  byte-for-byte, emulate `Date.parse` as local time and print it as UTC.

---

## 12. Oracle for difftests (`tools/obsidian-test eval`)

- Toggle (sync, the exact Toggle Done path including recurrence and onCompletion):
  `app.plugins.plugins['obsidian-tasks-plugin'].apiV1.executeToggleTaskDoneCommand(line, path)`
  (`src/Api/index.ts`, `TasksApiV1.ts`). It returns the replacement text; `''`
  means the line is deleted. It uses the real clock for ✅/➕.
- Parse: `app.plugins.plugins['obsidian-tasks-plugin'].getTasks()`
  (`src/main.ts:115`), which gives `description`, `tags`, `priority`,
  `status.symbol/type`, `dueDate` etc., and `recurrence?.toText()`. Or
  round-trip with `t.toFileLineString()`.
- Task detection: `app.metadataCache.getFileCache(app.vault.getFileByPath(p)).listItems`.
