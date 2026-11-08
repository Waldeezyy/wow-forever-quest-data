# Normalized route data validation

`validate_routes.py` contains pure Python functions only. It does not execute source Lua or guide conditions, load an addon, contact a service, or access a game/bot process.

## Input

```text
guide { id, source, metadata, steps: [
  { index, title, conditions, goals: [
    { index, kind, quest_id, objective_index, npc_id, object_id,
      item_id, count, prerequisites: { any: [], all: [] },
      conditions, location, raw }
  ] }
] }
```

- `guide.id` is a nonempty string. Each array's `index` values are nonnegative integers, unique and strictly increasing. Both zero-based and one-based input indices work; gaps are valid. Goal indices are local to their step. Optional `source_step_index` and `source_goal_index` preserve provider numbering independently of display order. Entity IDs may repeat across actions, as a quest normally has accept/complete/turn-in goals.
- Normalized `quest_id`, `npc_id`, `object_id`, `item_id` are positive integers when supplied; null means unspecified. `objective_index` is nonnegative when supplied; its provider-specific0/1 convention is not converted. `count` is a positive integer when supplied; null does not become1.
- Explicit prerequisite operators are `any` and `all`, each a list of positive quest IDs. Missing/null lists remain unknown. They are never flattened or converted into an assumed AND/OR expression. With no external quest catalog, a reference outside this guide is a warning, not proof of an invalid prerequisite.
- Optional `metadata.known_quest_ids` is a list of positive IDs from the assembler's audited facts provider. Only when present can the validator flag IDs absent from that supplied catalog. It cannot establish quest existence from the route alone.
- `location` is null/unknown or an object with finite `x`,`y`, optional finite `z`, and positive `map_id` (or `ui_map_id`). A raw zone label is preserved but does not count as a mapped ID. `coordinate_system` can be `normalized` (0..1), `percent` (0..100) or `world` (no artificial range). Missing/other units produce a warning; units and maps are never guessed.
- `raw`, `conditions`, source metadata and unrecognized fields are preserved. Conditions are opaque data; this validator does not interpret them or decide whether a route can execute.

## Results and overrides

`validate_guide(guide) -> list[issue]`, where an issue has `severity`, `code`, JSON-style `path`, `message`, and optional `details`. Errors describe malformed normalized data or references contradicted by a supplied catalog. Warnings describe missing, unknown, unmapped or external facts. Input is never mutated.

`apply_overrides(guide, overrides) -> (new_guide, report)` deep-copies the guide and supports actual user-authored insertion:

```text
overrides {
  exclude_quest_ids: [positive quest IDs],
  replacement_notes: {arbitrary annotations},
  replacements: [
    { id: "unique-override-id", remove_quest_ids: [positive quest IDs],
      after_source_step: original source-step index,
      reason: "why this authored replacement is needed",
      steps: [full normalized step objects with supplied goals/locations/raw] }
  ]
}
```

Processing rules:

1. Resolve anchors against **original** steps' `source_step_index`, falling back to the pre-edit `index` only when the source field is absent. Empty source steps remain anchors. Previously inserted steps marked `replacement_id` are not original anchors.
2. Validate replacement IDs, anchors, positive removal IDs and normalized replacement data before editing. The supplied replacement steps retain their own original source indices (or their supplied `index` as fallback). No coordinates, objectives or quest choices are inferred.
3. Remove every original goal whose own `quest_id` appears in global exclusions or a replacement's removal list. This applies to accept/complete/turn-in and any other goal carrying that exact ID; unassociated goals are not guessed to belong to it. Other goals, raw text and conditions stay.
4. Insert each replacement's authored steps immediately after its original anchor, including an emptied anchor. Multiple replacements on one anchor follow the order of the `replacements` array. Each inserted step gets `replacement_id` provenance. A replacement may remove and reintroduce its **own same quest ID** as an authored correction; original-goal removal never silently deletes newly inserted content.
5. After all edits, assign **display** `step.index =1..N` and each step's `goal.index =1..M`. Preserve existing `source_step_index`/`source_goal_index` everywhere; otherwise retain the original supplied index in those fields. Source indices are local to their source/replacement and may numerically overlap between them; `replacement_id` distinguishes inserted provenance.
6. Report explicit remaining prerequisite references to removed IDs that were not reintroduced by supplied replacement steps. Follow-ups remain unchanged. Opaque conditions/raw expressions are not searched for hidden dependencies. Replacement notes alone remain annotations and insert nothing.

The helper raises `ValueError` for malformed overrides/replacement data, duplicate or already-applied replacement IDs, unknown or ambiguous original anchors, duplicate removal ownership, and conflicts between global exclusions and a replacement's removals or inserted quest IDs. It also rejects one replacement inserting a quest explicitly removed by another. Invalid exclusion lists do not produce a partially edited guide. Informational missing-data warnings in supplied steps and dependent-quest warnings remain explicit in the report.

The report contains `excluded_quest_ids`, `replacement_ids`, `removed_goals` (with original source indices), `inserted_steps` (with reason/anchor/final display index), `replacement_goals_added`, `replacement_notes`, `dependent_warnings` and `issues`. It does not claim a replacement is executable or completes any game goal. The caller should run `validate_guide` on the final data against its audited `metadata.known_quest_ids`; insertion does not auto-declare newly typed IDs as known facts.

The tests use original synthetic fixtures and Python's standard library only. Run `python -m unittest discover -s tests -v` from the repository root.
