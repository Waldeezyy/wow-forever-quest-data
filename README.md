# WoW Forever: Tirisfal quest guide

**[tirisfal.json](tirisfal.json) is the complete zone data file.** It contains the ordered guide steps, their objectives/actions, coordinates, conditions and quest exclusions. The bot reads this JSON directly. There is nothing to install or run here.

Coverage: Polestar 0.3.4's Horde/Undead Tirisfal guide, source levels 1-13: **66 steps, 247 goals and 79 distinct quest IDs**. Class-specific branches are included, so one character will not do every listed quest.

## File layout

The JSON preserves Polestar's guide fields and adds two editable exclusion fields at the top:

| Field | Meaning |
|---|---|
| `source` | Source addon/version, attribution and original file hash. |
| `exclude_quest_ids` | Quest IDs the bot should skip throughout this guide. Empty by default. |
| `exclusion_notes` | Optional reasons, keyed by quest ID as a JSON string. Informational only. |
| `id`, `zone`, `zoneName` | Guide ID, zone UiMapID and zone name. |
| `faction`, `races`, `minLevel`, `maxLevel` | The guide's intended character/level context. |
| `names`, `written` | Text/token lookup tables used by guide titles and instructions. |
| `steps` | Guide steps in their intended order. |

Each step contains its original title, note, any conditions, and an ordered `goals` array. A goal can be a quest action, objective, travel instruction or supporting action. Both array orders matter.

## Goals and objectives

| Field | Meaning |
|---|---|
| `t` | Action type. This zone uses `accept`, `turnin`, `complete`, `kill`, `collect`, `goto`, `talk`, `interact`, `use`, `buy`, `train`, `sethome` and `getfp`. |
| `quest` | Quest ID directly associated with this action, when supplied. |
| `title` | Quest/action title, when supplied. |
| `oi` | Source objective index. Keep its original numbering. |
| `npc`, `object`, `item`, `spell` | Relevant target/entity IDs, when supplied. |
| `count` | Required quantity, when supplied. Missing does not mean zero. |
| `map`, `x`, `y`, `z`, `f`, `r` | Source location, frame, height and radius fields; see coordinates below. |
| `pre`, `preAll` | Source alternative/grouped prerequisite quest lists. Preserve them separately. |
| `closedBy` | Source quest-completion/closure condition. Preserve its meaning rather than treating it as a location or target. |
| `only`, `class`, `when`, `optional`, `along`, `label` | Character or guide-flow conditions/references, where present. Step-level conditions apply to the enclosed goals too. |
| `candidates` | Source candidate records, including trainer choices where present. |
| `spotsPacked` | Source-packed spawn areas, retained as supplied. |

Additional source fields are retained. Missing requirements are unknown; the file is not a complete quest database. The bot should use its existing quest facts/state handling alongside the ordered guide.

For text such as `{npc:1568}`, look up the token without braces in `names` (`npc:1568`). `written` contains source-rendered instruction variants. Those tables remain in this same file.

## Excluding a quest

Edit the two top-level fields in `tirisfal.json`. For example, to exclude quest 99144 if its escort is unsupported:

```json
"exclude_quest_ids": [99144],
"exclusion_notes": {
  "99144": "Escort unsupported by the bot."
}
```

This is an example edit; the checked-in file has no exclusions enabled.

The bot should skip **every goal whose `quest` matches an excluded ID**, including its accept, objective and turn-in actions. A note alone does not exclude anything. The JSON only declares exclusions; the bot implements that behavior.

Review follow-up requirements and references such as `pre`, `preAll`, `closedBy`, `along` and `when`. Excluding a prerequisite does not make its follow-ups available. Travel goals and instructions without that quest ID also remain; remove or edit them if they no longer serve the route.

## Replacing quests or changing the route

Edit the ordered `steps` and `goals` directly in this file:

1. Exclude or remove the old quest's goals wherever they occur.
2. Insert the replacement's real accept, objective and turn-in goals where they belong in the route. Existing goals show the field format.
3. Supply verified quest/target IDs, locations, quantities and eligibility conditions. A replacement quest ID alone does not describe its objectives.
4. Review affected travel, quest prerequisites, labels and flow references. Keep unrelated goals that share a step.
5. Update titles/notes and the exclusion reason so the next person understands the edit.

There is no separate override file or automatic replacement system. Moving an entry changes its order. Deleting an entry removes it. To disable only a questless travel or interaction action, edit/remove that specific goal.

Preserve JSON syntax: quoted keys, commas between entries and no comments or trailing commas. Put explanations in `exclusion_notes` or the relevant step's `note`.

## Coordinates and conditions

`map` is a UiMapID. `x` and `y` are **map percentages from 0 to 100**. The located goals in this source use `f: "e"`, an **Era reference frame**. These are not verified current-client world coordinates. Source `z`/`r` values are retained without terrain/layer validation. Coordinate conversion and navigation belong to the consuming bot.

Conditions and packed spawn data are preserved as source data. They have not been executed or rewritten into bot-specific rules. Keep class/race branches and source flow references intact unless deliberately changing them.

## Source

Converted from the installed Polestar 0.3.4 guide `forever/horde/undead/01-tirisfal-glades`. All original step/goal fields were retained; the previous generated duplicates and tooling have been removed from the current repository contents.

Upstream: [Polestar](https://github.com/fitzforge/polestar), [guide format](https://polestar.guide/docs/authors/guide-format).

The source pack declares GPL-3.0-only. Preserve [LICENSE](LICENSE), [DATA-NOTICES.txt](DATA-NOTICES.txt) and the JSON's attribution when sharing or reusing it. No paid Zygor guide content is included.

This is a single-zone data starting point. The route and any edits still need validation in the consuming bot.
