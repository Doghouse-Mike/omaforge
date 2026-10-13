---
TQ_extra_instructions: not done
board_by: priority
---
# Dashboard

Each ```tasks block below shows up in OmaForge's sidebar under Queries.
This note's `TQ_extra_instructions` property adds `not done` to all of them.

## Due this week
```tasks
due before in 7 days
group by due
```

## By priority
```tasks
view columns by {{query.file.property('board_by')}}
group by heading
```

## Waiting on something
```tasks
is blocked
```

## Errands
```tasks
tags include #errands
sort by due
```
