# TaskNotes 4.13.8 on-disk behaviour spec (for omaforge)

What TaskNotes 4.13.8 reads and writes in task notes, extracted from source so
that an external editor can produce byte-compatible files.

**Sources** (citations use these prefixes):

- `src/…:N` — TaskNotes repo at tag 4.13.8 (commit `69535cd`).
- `model/<file>.js:N` — `@tasknotes/model@0.3.0-rc.9` (`dist/esm`), a pinned npm
  dependency (`package.json:94`). **Most of the mapping, date and recurrence logic
  lives here, not in `src/`.** `src/core/fieldMapping.ts` and `src/core/recurrence.ts`
  only re-export it.
- `obsidian app.js` — Obsidian 1.14.4 (`~/.config/obsidian/obsidian-1.14.4.asar`),
  used for YAML serialisation and trash behaviour.

**Reference settings** — the TaskNotes configuration this spec was checked against
(`<vault>/.obsidian/plugins/tasknotes/data.json`); behaviour that depends on a setting
says so: tag identification
with `taskTag: "todo"`, `tasksFolder: "TaskNotes/Tasks"`, `storeTitleInFilename: true`,
`taskFilenameFormat: "zettel"` (ignored because storeTitleInFilename is true),
`moveArchivedTasks: true`, `archiveFolder: "TaskNotes/Archive"`,
`excludedFolders: "Templates, Archive"`, `defaultTaskStatus: "todo"`,
`defaultTaskPriority: "normal"`, `maintainDueDateOffsetInRecurring: false`,
`useFrontmatterMarkdownLinks: false`, `resetCheckboxesOnRecurrence: false`,
`hideCompletedFromOverdue: true`, `taskCreationDefaults.useBodyTemplate: false`,
`userFields: []`. The fieldMapping is the 4.13.8 default (`model/mapping.js:2-38`),
so the snake_case names below are the stock names, not customisations.

Statuses, in array order (the order matters, see §3):

| value | label | isCompleted | order | autoArchive |
|---|---|---|---|---|
| `todo` | Todo | false | 0 | false |
| `in-progress` | In progress | false | 1 | false |
| `done` | Done | true | 2 | false |
| `archived` | Archived | true | 3 | **true** (delay 5 min) |

Priorities (weights): `none` 0, `low` 1, `normal` 2, `high` 3.

Vault `.obsidian/app.json` has no `trashOption` (so it defaults to `"system"`) and has
`alwaysUpdateLinks: true`. Both matter for §5, §6 and §8.

---

## 0. Field name table (frontmatter keys, as mapped in the reference settings)

| internal | frontmatter key | type written |
|---|---|---|
| title | `title` | string (only when the filename can't represent it, §2.3) |
| status | `status` | string (`"true"`/`"false"` are coerced to YAML booleans, `model/mapping.js:522`) |
| priority | `priority` | string |
| due / scheduled | `due` / `scheduled` | `YYYY-MM-DD` or `YYYY-MM-DDTHH:mm` |
| contexts | `contexts` | list of strings |
| projects | `projects` | list of wikilink strings `"[[Note]]"` |
| timeEstimate | `timeEstimate` | integer minutes |
| completedDate | `completedDate` | `YYYY-MM-DD` |
| dateCreated / dateModified | `dateCreated` / `dateModified` | `YYYY-MM-DDTHH:mm:ss.SSS±HH:MM` |
| recurrence | `recurrence` | `DTSTART:…;FREQ=…` string |
| recurrenceAnchor | `recurrence_anchor` | `scheduled` \| `completion` |
| completeInstances | `complete_instances` | list of `YYYY-MM-DD` |
| skippedInstances | `skipped_instances` | list of `YYYY-MM-DD` |
| blockedBy | `blockedBy` | list of `{uid, reltype[, gap]}` maps |
| archiveTag | `archived` | **a tag value inside `tags`, not a property** |
| sortOrder | `tasknotes_manual_order` | LexoRank string |
| timeEntries | `timeEntries` | list of `{startTime, endTime?, description?}` |
| reminders | `reminders` | list of maps |
| others | `recurrence_parent`, `occurrence_date`, `occurrence_materialization`, `occurrence_next_trigger`, `occurrence_template`, `occurrence_past_horizon`, `occurrence_future_horizon`, `pomodoros`, `icsEventId`, `ics_event`, `googleCalendar*` | written only by features you don't need to replicate |

---

## 1. Task identification and loading

### 1.1 Tag method (`src/utils/taskIdentification.ts:33-62`)

A note is a task iff its **frontmatter** is a mapping and some entry of
`frontmatter.tags` matches the task tag:

- **Only the `tags` key is read.** `tag:` (singular) and inline body `#todo` tags are
  ignored (`taskIdentification.ts:58`).
- `getFrontmatterTags(value)` (`src/utils/taskIdentificationFrontmatter.ts:86-109`):
  - list: each element is `String()`ed, then normalised, then de-duplicated with order kept.
  - string: if non-blank, it is treated as **one** tag. It is **not split on commas or
    spaces**.
  - anything else gives `[]`.
- Normalising a tag (`…Frontmatter.ts:68-72`): trim, drop one leading `#` and trim again,
  then replace every whitespace run with `-`. So `"#todo"` becomes `todo`, and
  `"todo, work"` becomes `todo,-work`, which is **not a task**.
- Match (`src/utils/FilterUtils.ts:566-584`, `matchesHierarchicalTagExact`), case-insensitive:
  `tag == "todo"` or `tag.startsWith("todo/")`. So `todo/work` and `TODO` match, but
  `todos` and `work/todo` do not.

### 1.2 Excluded folders (`src/utils/pathExclusions.ts:5-28`)

`"Templates, Archive"` is split on `,`, trimmed, backslashes converted, and leading and
trailing `/` stripped. The result is `["Templates", "Archive"]`. A path is excluded when it
**equals** a folder or **starts with `folder + "/"`**, measured **from the vault root**.
`TaskNotes/Archive/x.md` is therefore **not** excluded. Excluded files are invisible to
`getTaskInfo` (`src/utils/TaskManager.ts:252-261`) and to the dependency index.

### 1.3 What's required to load

Nothing beyond the tag. Defaults applied on read (`src/utils/taskInfoAssembly.ts:23-38`,
`model/mapping.js:278-427`):

- title: frontmatter `title` if it's a non-blank string. Lists are joined with `", "` and
  numbers or bools are `String()`ed. Otherwise the **filename without `.md`**
  (`mapping.js:286-295, 660-662`). A frontmatter title wins even when
  `storeTitleInFilename` is true.
- status: the raw value, normalised against configured statuses by exact value, then a
  unique exact label, then case-insensitive value, then case-insensitive label
  (`mapping.js:609-627`). `"Done"` and `"DONE"` both become `done`, and the label
  `"In progress"` becomes `in-progress`. Unknown values are kept as-is (and are not
  completed). If missing, `defaultTaskStatus` (`todo`) is used.
- priority: normalised the same way. If missing, `"normal"` (hard-coded, not the
  setting).
- `normalizeStringValue` (`mapping.js:632-638`): a blank string becomes unset, a number or
  bool is `String()`ed, and a 1-element list is unwrapped. Any other list or object
  becomes unset.
- contexts and projects: a scalar becomes a 1-element list, and elements are `String()`ed
  (`mapping.js:639-641`).
- timeEstimate: a number, or a numeric string. Anything else becomes unset.
- `archived` = `tags` (normalised) contains `"archived"` (`mapping.js:408-412`).
- complete_instances and skipped_instances: a scalar becomes a list. Non-strings are
  dropped, the date part (before `T` or a space) is taken, entries are validated as real
  calendar dates and de-duplicated (`mapping.js:181-197`).
- `recurrence_anchor`: `scheduled` or `completion`. Any other non-blank value is treated
  as `scheduled` (`mapping.js:326-333`).

### 1.4 Unknown fields

They are ignored when mapping, but **preserved on every write**. TaskNotes always
mutates through `fileManager.processFrontMatter`, which parses the whole block to a JS
object, lets TaskNotes change named keys, and re-serialises **all** of it (§9). The
consequences are:

- every TaskNotes write **re-formats the entire frontmatter**
- **YAML comments are deleted**
- key order is preserved, new keys are appended at the end, and deleted keys vanish

---

## 2. Creation (`src/services/task-service/TaskCreationService.ts:124-345`)

### 2.1 Title sanitising

`rawTitle = title.trim()` (an empty title throws `"Title is required"`).

- **Stored title** (`taskTitleSanitizer.ts:43-57`): trim, collapse `\s+` to one space,
  strip control characters (code ≤31 or 127–159), trim. If the result is empty, use
  `"untitled"`.
- **Filename title** (`taskTitleSanitizer.ts:21-41`): the same, then remove these
  characters: `< > : " / \ | ? * # [ ]`. Then strip leading and trailing `.` runs, then
  trim. If the result is empty, use `"untitled"`. Case and spaces are **kept**:
  `Buy milk` becomes `Buy milk.md`. TaskNotes does not slugify.
- `generateUniqueFilename` re-sanitises with `sanitizeForFilename`
  (`src/utils/filenameGenerator.ts:465-531`), which uses the same character set and adds
  one rule: Windows reserved names (CON, PRN, AUX, NUL, COM1–9, LPT1–9, compared
  case-insensitively) get a `task-` prefix.

### 2.2 Folder and filename collisions (`filenameGenerator.ts:573-643`)

- Folder: `tasksFolder` passed through `processFolderTemplate`. The `{{…}}` date and task
  variables are a no-op for the literal `TaskNotes/Tasks`. The folder is created if it's
  missing.
- `<folder>/<name>.md`, after normalising the path (`\` to `/`, `//` to `/`, and `..`
  removed from the folder). If the path exists, TaskNotes tries **`<name>-2`, `<name>-3`
  … `<name>-999`** (`:616`). There is no `-1` and no space before the number. After that
  it falls back to `<first 50 chars>-<Date.now() base36>`.
- If the **full vault path is longer than 260 chars**, an error is caught and the
  filename becomes `task-<Date.now().toString(36)>` (`:604, :642`).
- Existence check: `vault.getAbstractFileByPath(p) || adapter.exists(p)`. This is
  case-sensitive on Linux.

### 2.3 When `title:` is written (`TaskCreationService.ts:209-215, 327-329`; `filenameGenerator.ts:202-209`)

`titleIsRepresentedByFilename = storeTitleInFilename && finalBasename === filenameTitle && storedTitle === filenameTitle`.

If true, **no `title` key** is written. If false, `title: <storedTitle>` is written as the
**first** key. That happens when sanitising removed characters (`?`, `:`, `#`, `[`,
`/`…), when a `-2` suffix was added, or for `untitled` and `task-…` fallbacks. For
example, `Pay the gas bill? Or switch?` is stored in a file named
`Pay the gas bill Or switch.md` with `title:` set.

### 2.4 Values and key order

Values come from `TaskCreationService.ts:140-251`:

- `status = input || "todo"`
- `priority = input || "normal"`. Both are always written.
- `dateCreated = dateModified = getCurrentTimestamp()`. These are two separate calls, so
  the milliseconds can differ by 1.
- `completedDate`: if non-recurring **and** status is completed, `getCurrentDateString()`.
  Otherwise absent.
- contexts and projects: written only if non-empty.
- `timeEstimate`: written only if `> 0`.
- `blockedBy` and `reminders`: written only if non-empty.
- recurrence: if it doesn't contain `DTSTART:`, DTSTART is prepended (§4.2).

Key order is **insertion order** of `mapTaskToFrontmatter` (`model/mapping.js:428-521`).
Only defined keys are emitted:

```
title?, status, priority, due?, scheduled?, contexts?, projects?, attachments?,
timeEstimate?, completedDate?, recurrence?, recurrence_anchor?, recurrence_parent?,
occurrence_*?, dateCreated, dateModified, tasknotes_manual_order?, timeEntries?,
complete_instances?, skipped_instances? (only if non-empty), blockedBy?, icsEventId?,
googleCalendar*?, reminders?, tags
```

`tags` is **last**. Its value is `[taskTag, ...otherTags]`: the task tag is **prepended**
when it's missing (`TaskCreationService.ts:159-167, 308`), the other tags are normalised
(§1.1), and duplicates are removed.

### 2.5 File content (`TaskCreationService.ts:311-345`)

```
"---\n" + stringifyYaml(frontmatter) + "---\n\n" + (body ? body + "\n" : "")
```

`body`: the body template is off, so it's `details.replace(/\r\n/g,"\n").trimEnd()`.
**An empty body still leaves the blank line after `---`.** `stringifyYaml` output ends in
`\n`. Worked example: create "Buy milk", due 2026-10-10, nothing else.
`TaskNotes/Tasks/Buy milk.md`:

```
---
status: todo
priority: normal
due: 2026-10-10
dateCreated: 2026-10-06T14:03:22.123+01:00
dateModified: 2026-10-06T14:03:22.124+01:00
tags:
  - todo
---

```

Example with a title that isn't representable and a recurrence with no scheduled
date:

```
---
title: Pay the gas bill? Or switch?
status: todo
priority: normal
projects:
  - "[[Household]]"
recurrence: DTSTART:20260907T180147Z;FREQ=MONTHLY
dateCreated: 2026-09-07T18:01:47.811+01:00
dateModified: 2026-09-07T18:01:47.811+01:00
tags:
  - todo
---
```

### 2.6 Timestamp formats (`src/utils/dateUtils.ts:762-796`)

- `getCurrentTimestamp()`: local wall clock with **exactly 3** fractional digits and a
  `±HH:MM` offset (never `Z`). For example `2026-10-06T14:03:22.123+01:00`. Python:
  `datetime.now().astimezone().isoformat(timespec="milliseconds")` gives the identical
  format.
- `getCurrentDateString()`: local `YYYY-MM-DD`. Used for completedDate.
- **Gotcha:** the model's strict datetime regex (`model/recurrence.js:6`) allows only
  `.\d{1,3}` and requires seconds. Existing files written by another tool have
  `dateCreated: '2026-10-05T13:18:06.307340'` (6 digits, no offset). If TaskNotes later
  derives DTSTART from such a dateCreated (recurrence added, no scheduled), it
  **throws**, and the update fails. Always write 3-digit milliseconds.

### 2.7 Defaults applied at creation (`taskCreationDefaults.ts:33-99`)

In the reference settings everything is `none`/empty, so no default due, scheduled, contexts,
projects, tags, recurrence or reminders are applied. Filling in a project from the
parent note happens only when creating from inside a note in Obsidian.

---

## 3. Updates and `dateModified`

TaskNotes has two write paths. Both set `dateModified = getCurrentTimestamp()`.

**A. Single property:** `updateProperty` (`src/services/TaskService.ts:586-746`,
`task-service/taskPropertyUpdate.ts:122-176`). Used by the status dot, context menus and
Kanban drags.

- Writes the frontmatter key mapped to the property, plus `dateModified`.
- `due` or `scheduled` set to a falsy value **deletes the key**.
- `blockedBy`: an empty list deletes the key. Otherwise the entries are serialised
  (§8.3).
- `status` (`taskPropertyUpdate.ts:100-120`). **Non-recurring tasks only:**
  - new status completed: `completedDate = today`, **always overwritten**. So `done` to
    `archived` re-stamps the date.
  - new status not completed: **delete** `completedDate`.
  - recurring tasks: completedDate is never touched.
- `scheduled` on a recurring task, when the *date part* changes: removes every
  `complete_instances` and `skipped_instances` entry `>= newDate`. If a list ends up
  empty, its **key is deleted** (`TaskService.ts:641-671, 714-725`). DTSTART is **not**
  updated on this path.

**B. Multi-field edit:** `updateTask` (`task-service/TaskUpdateService.ts:107-249`,
`taskUpdatePlanning.ts:267-355`). Used by the edit modal.

- If `storeTitleInFilename` and the title changed, the file is **renamed first** to
  `generateUniqueFilename(newTitle)` in the *same folder*. A conflict gets a `-2` suffix,
  and if the new sanitised name equals the current one but the title differs, you get
  `-2` too, because the file itself exists. Then `title:` is deleted if the new basename
  represents it, else written.
- The patch is run through `mapToFrontmatter` and merged in. Undefined values are not
  written, and setting a field to undefined **deletes** it: due, scheduled, contexts
  (also when `[]`), projects (also when `[]`), timeEstimate, completedDate, recurrence,
  blockedBy (`[]`), reminders (`[]`) (`taskUpdatePlanning.ts:386-461`).
- `tags` is always rewritten as normalised tags with the task tag appended if missing.
  `mapTaskToFrontmatter` **appends** the task tag (`mapping.js:502`), unlike creation,
  which prepends it.
- The status/completedDate rule is the same as path A.
- Recurrence side effects (`taskUpdatePlanning.ts:153-218`):
  - recurrence changed: scheduled and due are recomputed as the next occurrence (§4.5),
    and DTSTART is added if missing.
  - recurrence newly added: DTSTART is added.
  - scheduled changed while the rule lacks DTSTART: DTSTART is added.
- Body: if `details` is supplied, the file is rewritten as
  `"---\n" + fmText + "\n---\n\n" + details.trimEnd() + "\n"`. With an empty body it's
  just `"---\n…\n---\n\n"` (`TaskUpdateService.ts:202-215`).

**Writes that do *not* bump dateModified:** manual drag ordering writes only
`tasknotes_manual_order` (`src/bases/sortOrderUtils.ts:552-564`).

**Status dot click** (`src/ui/taskCardActions.ts:41-64`):

- recurring tasks toggle the instance (§4.4)
- other tasks **cycle** statuses by `order`: `todo` → `in-progress` → `done` →
  `archived` → `todo`. Shift+click cycles backwards.

**"Toggle complete" command** (`TaskService.ts:557-565`):

- if the status is completed: set `defaultTaskStatus` (`todo`)
- otherwise: set `getCompletedStatuses()[0]`, the **first completed status in array
  order**, which is `done`.

---

## 4. Recurring tasks

### 4.1 Format

`recurrence` holds a single string, `DTSTART:<v>;<RRULE body>`. The parts are
**semicolon-joined on one line**, which is not RFC 5545 line-separated, and there is no
`RRULE:` prefix. Examples:

- `DTSTART:20261006;FREQ=WEEKLY;BYDAY=MO`
- `DTSTART:20260907T180147Z;FREQ=MONTHLY`
- `DTSTART:20261006;FREQ=DAILY;INTERVAL=2;UNTIL=20261231`

DTSTART takes one of two forms. Parsing uses `/DTSTART:(\d{8}(?:T\d{6}Z?)?)/`
(`model/recurrence.js:362-383`):

- `YYYYMMDD`: date-only
- `YYYYMMDDTHHMMSSZ`: **the `Z` is a lie.** The digits are the *local wall-clock* time
  (`formatDtstartValue`, `recurrence.js:396-408`, uses `getHours()` and so on, then
  appends `Z`).

Everything is evaluated in UTC, so the digits behave as floating wall-clock time.

Rule body: anything `RRule.parseString` accepts (rrule.js 2.8.x). The body is the
string with `DTSTART:[^;]+;?` removed and a leading `;` stripped (`recurrence.js:349-357`).

Legacy and invalid values:

- object-style legacy recurrence (`{frequency: …}`) maps to unset, so it reads as
  **not recurring** (`normalizeStringValue`)
- a string without `FREQ=` (e.g. `daily`) makes `RRule.parseString` throw.
  `isDueByRRule` catches the error and returns **true for every date**, so the task
  shows every day, and next-occurrence falls back to a day-by-day loop. **Never write
  these.**

Default templates are `FREQ=DAILY`, `FREQ=WEEKLY`, `FREQ=MONTHLY`, `FREQ=YEARLY`
(`taskCreationDefaults.ts:23-30`).

### 4.2 Adding DTSTART (`model/recurrence.js:279-293`, wrapper `src/core/recurrence.ts:24-87`)

`source = scheduled || dateCreated`. If neither exists, DTSTART isn't added.

- source has `T\d\d:\d\d`: parse it as a local datetime and emit
  `DTSTART:YYYYMMDDTHHMMSSZ` from its **local** components. The wrapper first turns
  `YYYY-MM-DDTHH:mm` into `…:00` so the strict parser accepts it. A dateCreated with
  `+01:00` is converted to the *current* local zone first.
- otherwise: `DTSTART:YYYYMMDD` from the date.

The result is `"DTSTART:" + v + ";" + recurrence`. It is added in these cases:

- on create
- in `updateTask` when recurrence changes or is added, or when scheduled changes while
  DTSTART is missing
- on instance completion for scheduled-anchor tasks, if missing

Once present, **DTSTART is never moved by rescheduling.** Only completion-anchor
completions rewrite it.

### 4.3 Instances

`complete_instances` and `skipped_instances` are YAML lists of `YYYY-MM-DD` strings,
appended in action order (not sorted). **The task `status` is not changed** by completing
an instance, and completedDate is not touched. "Completed on date D" means
`complete_instances` contains D (`recurrence.js:151-158`).

### 4.4 Completing or skipping an instance

Source: `task-service/taskRecurringPlanning.ts:208-376` (complete) and `:378-493` (skip),
called from `TaskService.ts:1919-2072`.

**1. Target date.** UI callers pass `date(scheduled || due)`, or today if both are absent
(`src/bases/TaskListView.ts:2598-2605`, `kanbanCardActions.ts:106-113`). The fallback
`getRecurringTaskActionDate` uses the scheduled date for scheduled-anchor tasks, else
today as a UTC-midnight date (`taskRecurringPlanning.ts:195-206`). All dates are
UTC-midnight `Date`s representing calendar days.

**2. Instance date.** Scheduled anchor only (`:95-137`): if the target is an rrule
occurrence, use it. Otherwise use the most recent *unprocessed* occurrence in
`[target − searchDays, target]`, where searchDays is
DAILY `max(30, 2i)`, WEEKLY `max(90, 14i)`, MONTHLY `max(400, 62i)`,
YEARLY `max(800, 732i)`, otherwise 365. If none exists, use the next uncompleted
occurrence on or after the target. Completion anchor: the instance is the target date
itself. Call the result `dateStr` (`YYYY-MM-DD`).

**3. Toggle.**

- If `dateStr` is **not** in `complete_instances`, append it and remove it from
  `skipped_instances`.
- If it is, remove it ("uncomplete").
- Skip is the mirror image: add to skipped and remove from complete, or remove from
  skipped.

**4. Completion anchor, on complete only.** Replace DTSTART's date with `dateStr` and
keep any existing `THHMMSSZ` time (`:250-264`).

**5. Advance.** This happens on complete **and** uncomplete, and on skip and unskip.
`floor = max(today, dateStr)` (string compare). The working copy sets
`scheduled := dateStr + (old scheduled's time suffix)` when an owning date was found.
Then `updateToNextScheduledOccurrence(task, maintainDueOffset=false, {today: floor})`
(`model/recurrence.js:235-266`):

- `next = getNextUncompletedOccurrence` (§4.5). If it's null, nothing moves.
- `scheduled = fmt(next)`, plus `"T" + oldScheduled.split("T")[1]` if the old value had a
  time. This is set **even if the task had no scheduled before.**
- due moves **only if** the task has both scheduled and due, and either
  `maintainDueOffset` is set or `due < next`. User setting is false, so it's
  "only if due would fall before the new scheduled". In that case
  `newDue = next + (due − scheduled)`, keeping due's time suffix. Otherwise due is
  unchanged.

**6. Write** (`:321-376`):

- `complete_instances` is created (`[]`) if missing and updated
- `skipped_instances` is **always written, even as `[]`**
- `recurrence` is written only if it changed
- `scheduled` and `due` are written if truthy
- `dateModified`

Skip writes both lists explicitly. The checkbox reset in the body is off in the reference settings.

Recurring tasks are never auto-archived (`AutoArchiveService.ts:98-101`).

### 4.5 Next occurrence

`getNextUncompletedOccurrence(task, {today})` (`model/recurrence.js:231-234, 415-452`).
`today` is `parseDateToUTC(floor)`, i.e. UTC midnight.

- **scheduled anchor** (default when the key is absent):
  `start = DTSTART if DTSTART < today else today`, `end = today + lookAhead days`,
  where lookAhead is DAILY `max(30,2i)`, WEEKLY `max(90,14i)`, MONTHLY `max(400,62i)`,
  YEARLY `max(800,732i)`, otherwise 365. The result is the first occurrence in
  `generateRecurringInstances(start, end)` whose date is not in complete ∪ skipped and
  is `>= today`. If there's none within the window, null.
- **completion anchor**: `start = DTSTART or today`, `end = start + lookAhead`. The
  result is the first occurrence with `occ > DTSTART` (strict), `occ >= today` and date
  not in skipped. Completed instances are not excluded. If DTSTART is older than the
  look-ahead window, this returns null. That's normally avoided because completion
  rewrites DTSTART.
- `generateRecurringInstances(task, s, e)` (`:172-211`):
  `rule.between(UTC 00:00 of s's UTC date, UTC 23:59:59.999 of e's UTC date, inclusive)`.

### 4.6 "Is due on date X" and the rrule rule object

- `createRRule` (`:349-357`): `options = RRule.parseString(body)` and
  `options.dtstart = DTSTART`. If DTSTART is missing it falls back to the date part of
  scheduled, then of dateCreated, at UTC midnight. If none of those exist, there is no
  rule: `isDueByRRule` returns false.
- `isDueByRRule(task, D)` (`:134-150`): returns true if
  `rule.between(D 00:00Z, D 23:59:59.999Z, inc=true)` is non-empty.
- Non-recurring tasks appear on date D if the date part of due or of scheduled equals D.

### 4.7 Porting to python-dateutil (rrule.js-equivalent)

- Parse DTSTART yourself into a `datetime(Y,M,D[,h,m,s], tzinfo=UTC)`. **Use tz-aware
  UTC** with the wall-clock digits.
  - With a naive dtstart, dateutil raises `RRULE UNTIL values must be specified in UTC
    when DTSTART is timezone-aware` for `UNTIL=…Z`.
  - With an aware dtstart, add `Z` semantics to a date-only UNTIL:
    `UNTIL=YYYYMMDD` becomes `YYYYMMDDT000000Z`. That's what rrule.js does, so a
    09:00 occurrence on the UNTIL day is **excluded**.
- `rrulestr(body, dtstart=dt)`, where `body` is the recurrence with `DTSTART:[^;]+;?`
  removed. Use `.between(a, b, inc=True)` and `.after(dt, inc)` with UTC-aware bounds.
- "today" is the **local** calendar date (`getTodayString()`, local), expressed as a
  UTC-midnight datetime. Format occurrences with their UTC date (`formatDateForStorage`
  uses `getUTC*`).
- WEEKLY without BYDAY uses DTSTART's weekday. MONTHLY on the 31st skips short months.
  Both behave the same in dateutil and rrule.js. Check `COUNT` and `BYSETPOS` against
  rrule.js if you rely on them.
- Display text is `RRule.fromString(body).toText()`, e.g. "every week on Monday". It's
  only cosmetic.

---

## 5. Archive and unarchive

Source: `TaskService.ts:1374-1567` and `task-service/taskArchivePlanning.ts`.

Archiving is **a tag, not a status**. `archived` = `tags` contains `archived`.

**Archive** (`taskArchivePlanning.ts:73-103`):

- if `tags` is missing, create `[]`
- if it's a scalar, wrap it as `[scalar]`
- append the literal `"archived"` if it's not present
- set `dateModified`
- **status is unchanged**

Then, with `moveArchivedTasks`, the file is moved to `archiveFolder + "/" + file.name`,
which is `TaskNotes/Archive/<same filename>`.

**Unarchive:**

- if `tags` is a list, remove elements `=== "archived"` (exact raw string, so `#archived`
  isn't removed). If the list becomes empty, **delete `tags`**. A scalar `tags` is left
  alone.
- set `dateModified`
- the file is moved to **`tasksFolder` root** (`TaskNotes/Tasks/<file.name>`), *not* its
  original folder

**Collision:** if the destination path exists, the move is **aborted** with a notice:
"A file named … already exists … Cannot move task to avoid overwriting". The tag change
**is kept**, so the task is archived but stays in place (`TaskService.ts:1418-1453`).
There's no `-2` renaming. The frontmatter is written *before* the move.

The move uses `fileManager.renameFile`. Because `alwaysUpdateLinks` is true, Obsidian
rewrites links to the file across the vault if the shortest linktext changes. Usually
it doesn't change, since the basename stays the same.

**Auto-archive** (`src/services/AutoArchiveService.ts`):

- when status changes **through TaskNotes** to a status with `autoArchive: true`
  (`archived`), and the task is not recurring, TaskNotes appends
  `{taskPath, statusChangeTimestamp, archiveAfterTimestamp: now+5min, statusValue}` to
  `data.json` → `autoArchiveQueue`
- a different status cancels the entry
- the queue is processed at plugin start and every 60 s. An entry is due once
  `now >= archiveAfterTimestamp`. If the status is still `archived` and the task isn't
  archived yet, TaskNotes calls `toggleArchive` (adds the tag and moves the file).

Changes made by an external editor are detected **only while Obsidian is running**
(`src/services/TaskFileLifecycleReconciliationService.ts`):

- TaskNotes takes a snapshot at startup and diffs it on each cache update
- only the first changed field in `[status, title, scheduled, due, priority, recurrence,
  …]` gets side effects

**Edits made while Obsidian is closed are never auto-archived.** omaforge should do the
archive itself, by adding the tag and moving the file, when it sets `status: archived`,
either immediately or after its own 5-minute delay.

Setting `archived` (a completed status) also stamps `completedDate`. The default Bases
views filter on `status != "archived"`, not on the tag (§10).

---

## 6. Delete (`TaskService.ts:1837-1895`)

`app.fileManager.trashFile(file)` honours Obsidian's `trashOption`:

- `"system"`: the OS trash. This is the default and **this vault's** setting, since
  app.json doesn't set it. On Linux that's freedesktop `~/.local/share/Trash`; use
  `gio trash` or `send2trash`.
- `"local"`: `<vault>/.trash/`
- `"none"`: permanent delete

Nothing else is cleaned up. `blockedBy` and `projects` links in other tasks become
unresolved. An unresolved blocker doesn't count as blocking (§8.3).

---

## 7. Dates

**Written formats** (`combineDateAndTime`, `dateUtils.ts:1014-1066`):

- `due` and `scheduled`: `YYYY-MM-DD`, or `YYYY-MM-DDTHH:mm` (local, no seconds, no
  offset)
- `completedDate`: `YYYY-MM-DD`
- instances: `YYYY-MM-DD`

**Accepted on read** (`dateUtils.ts:23-200`, `parseDateToLocalInternal`):

- `YYYY-MM-DD` (local midnight)
- `YYYY-MM-DD Ddd` or a full day name (the day name is ignored)
- `YYYY-MM-DD HH:mm[:ss]` (space separator)
- ISO with `T`, `Z` or an offset (via date-fns `parseISO`)
- ISO week `YYYY-Www` (Monday of that week)
- a bare `THH:mm` throws

**Comparisons** (`dateUtils.ts:1186-1247`):

- *overdue*, date-only: `D < localToday` as calendar dates. Datetime: the instant
  (no offset means local) is before now. If `hideCompletedFromOverdue` is true and the
  status is completed, it's never overdue. Both due and scheduled are checked
  separately (`src/ui/taskCardProperties.ts:818, 876`).
- *today*: same local calendar day, also for datetimes.
- date-part extraction is the text before `T` (`getDatePart`, `dateUtils.ts:873-899`)

**YAML caveat:** Obsidian parses YAML 1.2 (§9), so `due: 2026-10-10` is a **string**.
PyYAML (YAML 1.1) turns it into `datetime.date`, `09:00` into `540`, and `yes`/`no` into
booleans. Use a loader that resolves only the 1.2 core schema (null, bool `true|false`,
int, float, string), or keep scalars as strings.

---

## 8. projects, contexts, timeEstimate, blockedBy, subtasks

### 8.1 contexts

A list of plain strings, stored exactly as given (e.g. `work` or `@dev`).

### 8.2 projects and subtasks

`projects` is a list of link strings. With `useFrontmatterMarkdownLinks: false` they're
wikilinks built by `generateLink` (`src/utils/linkUtils.ts:197-230`) as
`"[[" + metadataCache.fileToLinktext(file, sourcePath, true) + "]]"`.

- Obsidian's default `newLinkFormat` is `shortest`, so this is the **basename** when it's
  unique in the vault, otherwise the vault path without `.md`.
- Plain-text projects are allowed.
- YAML always quotes them: `- "[[Note]]"`.

**Subtask relationship:** task B is a subtask of task A iff B's `projects` is a **list**
containing a wikilink or markdown link that resolves via `getFirstLinkpathDest` to A's
file (`src/services/ProjectSubtasksService.ts:119-160`). Plain text doesn't count, and
neither does a scalar `projects` value. A "project" is any note that's the target of
such a link. Resolution follows Obsidian rules: exact path, then basename, preferring
the closest match. Links are matched in `parseLinkToPath`
(`model/mapping.js:597-608`), which strips `#heading` and `|alias`.

### 8.3 blockedBy and blocking

Written form (`model/mapping.js:587-596`), as a list of maps:

```yaml
blockedBy:
  - uid: "[[Code review PR 123]]"
    reltype: FINISHTOSTART
  - uid: "[[Other]]"
    reltype: STARTTOSTART
    gap: P1D
```

- `uid` is a wikilink. A bare name is wrapped as `[[name]]` on write.
- `reltype` is one of `FINISHTOSTART` (default), `FINISHTOFINISH`, `STARTTOSTART`,
  `STARTTOFINISH`. It's upper-cased on read, and invalid values become the default.
- `gap` is an optional non-blank string, e.g. an ISO 8601 duration.
- On read, a bare string entry `"[[X]]"` becomes `{uid: X, reltype: FINISHTOSTART}`
  (`mapping.js:568-586`).
- `blockedBy` has no inverse field. "Blocking" is **derived**: A blocks B iff B's
  blockedBy resolves to A.
- B `isBlocked` iff at least one resolved blocker has a **non-completed** status
  (`src/utils/DependencyCache.ts:645-650`, status via `isCompletedStatus`). Archive tags
  and recurring-instance completion are ignored. Unresolved links and blockers in
  excluded folders are ignored.

### 8.4 timeEstimate

An integer number of minutes. Written on create only if `> 0`. Deleted on edit when it's
cleared.

---

## 9. YAML serialisation (what processFrontMatter writes)

### 9.1 Serialiser

The serialiser is pulled from the Obsidian 1.14.4 `app.js`: `stringifyYaml = IF(obj)`,
which is eemeli **`yaml` v2** `stringify(obj, null, {nullStr: "", lineWidth: 0, aliasDuplicateObjects: false})`.
`parseYaml` is `yaml.parse(text)` with the default YAML **1.2 core** schema.

### 9.2 How processFrontMatter rewrites the block

`processFrontMatter(file, fn)`:

1. Find the frontmatter. The file must start with `---\r?\n`, and the block closes at the
   first `---` that's at the start of a line and followed by `\r?\n` or end of file.
   Trailing spaces after the closing `---` are not accepted.
2. Parse it and run `fn`. A non-mapping block becomes `{}`. **Invalid YAML throws**, so
   the write fails, and Obsidian doesn't see the note as a task (it has no
   frontmatter).
3. Replace **only the text between the fences** with `stringify(obj)`.
4. If `obj` ends up empty, the whole block is removed.
5. If the file had no frontmatter, `"---\n" + yaml + "---\n"` is prepended.

The body is untouched byte-for-byte.

### 9.3 Formatting rules

These are the observed eemeli v2 rules with the Obsidian options. Mimic them for new or
changed lines.

- `key: value`, with no extra spaces. Mapping indent is 2.
- **Block sequences are indented 2 under the key**:

  ```yaml
  tags:
    - todo
  ```

- A sequence of maps is written as `- uid: …` with following keys at 4 spaces.
- An empty list is `key: []`, an empty map `key: {}`, and null is `key:` with nothing
  after the colon.
- Booleans are `true`/`false`. Numbers are bare.
- No line folding (`lineWidth: 0`). A multi-line string becomes a block literal: `|-`,
  or `|` if it ends in `\n`.
- Strings are **plain** unless one of the conditions below applies. If any does, the
  string is double-quoted with JSON-like escapes. A string that starts with `"` is
  **single-quoted** (`'"x'`).
  - it's empty
  - it has leading or trailing whitespace
  - it starts with `[ { } ! | > ' " % @ \` & * # ,`, or with `- ` or `? `, or equals `-`
  - it contains `: ` or ` #`, or ends with `:`
  - it would resolve as a non-string in YAML 1.2 core: `null`/`Null`/`NULL`/`~`,
    `true`/`True`/`TRUE`/`false`…, ints (`-1`, `+1`, `0x1F`, `0o17`), floats (`1.5`,
    `.5`, `1e3`, `.inf`, `.NaN`)
- Things that **stay plain**:
  - dates and times: `2026-10-06`, `2026-10-06T09:00`,
    `2026-10-02T11:26:44.935+01:00`, `12:30:00`
  - `DTSTART:20260907;FREQ=DAILY`, `FINISHTOSTART`
  - `yes`, `no`, `1_000`, `4.13.8`, `a:b`, `x,`, `a# b`, `?x`, `-x`, `it's`,
    `say "hi"`, `x]`
- Things that get **quoted**: `"[[Note]]"`, `"@dev"`, `"#tag"`, `"1.5"`, `"true"`, and
  any title containing `: `.

### 9.4 Line-preserving editors

Edit only the changed keys' lines. **Append new keys at the end of the block**, which
matches JS insertion order, e.g. `dateModified`/`completedDate` added after `tags`.
Delete lines for removed keys. Use the 2-space-indented `- ` list style. Anything
untouched will be re-normalised by TaskNotes' next write anyway. Watch out for:

- **comments** (`#` lines) are removed by any TaskNotes write
- quote styles from other tools (`'…'`, unindented `- x`) are normalised on TaskNotes'
  next write. That's harmless.

---

## 10. Saved views and the shipped Bases views

### 10.1 `savedViews` in data.json (legacy TaskNotes filter UI)

```json
{"id":"abc123example","name":"Not done",
 "query":{"type":"group","id":"filter_…","conjunction":"and","children":[
   {"type":"condition","id":"filter_…","property":"status","operator":"is","value":"todo"},
   {"type":"condition","id":"filter_…","property":"archived","operator":"is-not-checked","value":null}],
  "sortKey":"due","sortDirection":"asc","groupKey":"none"},
 "visibleProperties":["status","priority","due","scheduled","projects","contexts","tags","blocked","blocking"]}
```

Types are defined at `src/types.ts:46-165`. A group is
`{type:"group", id, conjunction:"and"|"or", children:[node…]}`. The root group also
carries `sortKey`, `sortDirection` (`asc`|`desc`), `groupKey` and an optional
`subgroupKey`.

| property | operators |
|---|---|
| `title` | is, is-not, contains, does-not-contain, is-empty, is-not-empty |
| `path` | contains, does-not-contain, is-empty, is-not-empty |
| `status`, `priority` | is, is-not, is-empty, is-not-empty |
| `tags`, `contexts`, `projects`, `blockedBy` (uids), `blocking` (paths) | contains, does-not-contain, is-empty, is-not-empty |
| `due`, `scheduled`, `completedDate`, `dateCreated`, `dateModified` | is, is-not, is-before, is-after, is-on-or-before, is-on-or-after, is-empty, is-not-empty |
| `archived`, `hasSubtasks`, `status.isCompleted`, `dependencies.isBlocked`, `dependencies.isBlocking` | is-checked, is-not-checked |
| `timeEstimate` | is, is-not, is-greater-than, is-less-than, is-greater-than-or-equal, is-less-than-or-equal |
| `recurrence` | is-empty, is-not-empty |
| `user:<key>` | depends on the user field type (none configured) |

Evaluation rules:

- Date values may be `YYYY-MM-DD` or natural-language `today`, `tomorrow`, `yesterday`,
  `next week`, `last week` (`dateUtils.ts:1614-1623`). Comparison is on date parts.
- `contains` on tags is hierarchical and also matches substrings
  (`FilterUtils.ts:530-554`).
- `is-not-checked` is true when the value is anything except `true`.
- sortKey is one of: due, scheduled, priority, status, title, dateCreated,
  completedDate, tags.
- groupKey is one of: none, priority, context, project, due, scheduled, status, tags,
  completedDate.

### 10.2 Shipped `.base` files (`TaskNotes/Views/*.base`, in Obsidian Bases syntax)

Every file has the top-level filter `file.hasTag("todo")`. That's Obsidian's tag test:
it includes **inline body tags** and nested tags, so it's a superset of TaskNotes'
frontmatter-only rule. The `formulas:` block, about 40 formulas, is duplicated in each
file.

Views, from `tasks-default.base`:

| view | type | filter beyond hasTag | sort / group |
|---|---|---|---|
| Manual Order | tasknotesTaskList | none | `tasknotes_manual_order` DESC, groupBy status ASC |
| All Tasks | tasknotesTaskList | none | `due` ASC |
| Not Blocked | tasknotesTaskList | ACTIVE ∧ (`blockedBy.isEmpty()` ∨ every blocker's `status` ∉ {done, archived}) | `formula.urgencyScore` DESC |
| Today | tasknotesTaskList | ACTIVE ∧ (`date(due)==today()` ∨ `date(scheduled)==today()`) | urgencyScore DESC |
| Overdue | tasknotesTaskList | ACTIVE ∧ `date(due) < today()` | urgencyScore DESC |
| This Week | tasknotesTaskList | ACTIVE ∧ (due ∈ [today, today+7d] ∨ scheduled ∈ [today, today+7d]) | urgencyScore DESC |
| Unscheduled | tasknotesTaskList | ACTIVE ∧ `date(due).isEmpty()` ∧ `date(scheduled).isEmpty()` | status ASC |
| Incomplete | tasknotesTaskList | **none** (name is misleading) | completedDate DESC |

Where:

- `ACTIVE` = `(recurrence.isEmpty() ∧ status != "done" ∧ status != "archived") ∨ (recurrence ∧ (complete_instances.isEmpty() ∨ !complete_instances.contains(today as yyyy-MM-dd)))`.
  It uses literal status values, not isCompleted, and the archive tag is **not**
  excluded.
- `urgencyScore = priorityWeight + max(0, 10 − daysUntilNext)` when there's a date, else
  `priorityWeight`. `priorityWeight` is none 0, low 1, normal 2, high 3, otherwise 999.
  `daysUntilNext` is the minimum of `floor((date(x) − today) / 1 day)` over due and
  scheduled.

Other files:

- `kanban-default.base`: tasknotesKanban, groupBy status, sorted by
  `tasknotes_manual_order` DESC
- `agenda-default.base` and `calendar-default.base`: tasknotesCalendar
  (listWeek / timeGridWeek)
- `mini-calendar-default.base`: dateProperty due, scheduled or `file.ctime`
- `relationships.base` is evaluated against the *current* file (`this`):
  - Subtasks: `note.projects.contains(this.file.asLink())`
  - Projects: `list(this.projects).contains(file.asLink())`
  - Blocked By: `list(this.note.blockedBy).map(value.uid).contains(file.asLink())`
  - Blocking: `list(note.blockedBy).map(value.uid).contains(this.file.asLink())`
- `workflows.base` and `pomodoro-stats.base` are not task views

**Minimal predicate set** that covers every default task view:

- hasTag, hierarchical and frontmatter-only. Accept the small divergence from Bases'
  inline-tag matching.
- `status ==` / `!=` literal
- `isEmpty` / not-empty on recurrence, due, scheduled, blockedBy and complete_instances
- `complete_instances contains today`
- date `==`, `<`, `>=`, `<=` against today and today + 7 days, on date parts
- blockedBy all-resolved-blockers-not-in {done, archived}
- the relationship link predicates above
- sorts:
  - field ASC/DESC: due, status, completedDate, `tasknotes_manual_order` (string compare
    of LexoRank)
  - urgencyScore DESC
- group: by status

The legacy savedView ("Not done": status is todo ∧ not archived-tag) needs `is` and
`is-not-checked`.
