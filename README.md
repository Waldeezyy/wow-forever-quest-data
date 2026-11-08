# WoW Forever quest data

Compile a selected, ordered Polestar guide into inspectable JSON for another developer to consume. The pilot uses the installed **Polestar 0.3.4 Tirisfal guide** and preserves its authored step order, goal fields, conditions and source provenance.

This repository's role is **data compilation and validation**. Its outputs describe a guide; a consuming application implements character-state evaluation, navigation, interactions and execution. The compiler neither evaluates guide conditions nor certifies that a character can complete a route.

The pilot demonstrates the data format for one guide. Its coverage follows the bundled source snapshot; it does not establish a complete, current 1-60 Forever route or verified live coordinates.

Initial coverage: **Tirisfal Glades, Horde/Undead, source levels 1-13**, guide ID `forever/horde/undead/01-tirisfal-glades`. The checked-in build contains **66 ordered steps, 247 goals, 79 unique quest IDs and 697 spawn-area records**. Class/character branches are retained; these totals are not the quest count for one character. The baseline has no active exclusions or replacements.

## Requirements

- **Python 3.11 or newer**, using the Python standard library only.
- A checkout containing the bundled source snapshot for the default reproducible rebuild.
- Optionally, an existing Polestar installation when deliberately refreshing inputs through `--addons`.

No Lua interpreter, WoW installation, account credentials or running game is needed to rebuild from the bundled source. The parser reads a restricted Lua data syntax in Python; it does not execute Lua. Tests use original synthetic fixtures and the selected source snapshot.

## Repository layout

```text
compile_polestar.py               CLI and source/override assembler
lua_data.py                      Restricted static Lua data parser
coordinates.py                   Coordinate preservation and frame conversion
validate_routes.py               Pure validation and override helpers
sources/polestar-0.3.4/           Selected Tirisfal Lua, raw frames and manifest
licenses/                        Upstream Polestar license/data notices
overrides/tirisfal.json           Maintained exclusion/replacement configuration
examples/exclude-escort.json     Real-ID exclusion format example
examples/replacement.demo.json   Fabricated replacement format demonstration
data/tirisfal/route.source.json  Unfiltered normalized source guide
data/tirisfal/route.json         Effective guide after overrides
data/tirisfal/quest-index.json   Quest IDs and their ordered occurrences
data/tirisfal/report.json        Statistics, validation and override audit
docs/data-contract.md            Validation/override API details
tests/                           Offline unit and integration tests
NOTICE.md                        Source rights and tooling license status
```

Edit `overrides/tirisfal.json` for route customizations and regenerate `data/tirisfal/`. Direct edits to generated JSON will be overwritten by the next build.

## Rebuild

### Bundled-source rebuild

Use the checked-in bundled snapshot to reproduce the pilot. This avoids silently changing the result when a locally installed addon updates. Run the CLI from the repository root, inspect its validation report, then compare the regenerated artifact/provenance with the published versions.

```powershell
python compile_polestar.py --source sources/polestar-0.3.4/tirisfal.lua --manifest sources/polestar-0.3.4/manifest.json --frames sources/polestar-0.3.4/map-frames.json --overrides overrides/tirisfal.json --out data/tirisfal
python -m unittest discover -s tests -v
```

The bundled-source mode requires matching SHA-256 hashes for both the selected Lua and frame JSON, plus matching manifest guide identity. It fails before writing outputs when these checks fail. The upstream build commit is unknown and recorded as `null`; the source package version and byte hashes identify this snapshot. The selected Lua is stored with LF line endings and a single final newline.

A successful build writes all four JSON outputs listed above, replacing files with those names in `--out`. Review `report.json` and the diff before accepting changed data. Outputs are deterministic for identical inputs; no build timestamp is embedded.

### Refresh from an installed addon

The CLI's **`--addons`** input points to the **AddOns directory**, for example:

```text
C:\Program Files (x86)\World of Warcraft\_forever_\Interface\AddOns
```

A deliberate refresh reads the selected Polestar guide and frame data, records their relative input paths, SHA-256 hashes and pack version, and produces a new compiled output. Treat a new source hash as a new input version, even when a displayed addon version stays the same. Compare guide identity/order, frame bounds, parser diagnostics, notices and override anchors before adopting it.

Inputs remain read-only. Rebuilding does not install an addon, change the game or bot, attach to a process, send input, download paid guides or read account/WTF data. The output directory is the compiler's workspace, not the installed AddOns directory.

For the initial Tirisfal guide, refresh into separate review directories first:

```powershell
python compile_polestar.py --addons "C:\Program Files (x86)\World of Warcraft\_forever_\Interface\AddOns" --guide forever/horde/undead/01-tirisfal-glades --snapshot-source sources/polestar-refresh --overrides overrides/tirisfal.json --out scratch/tirisfal-refresh
```

This reads `Polestar_Guides_Horde/Guides.lua`, `Polestar_Guides/Pack.lua` and `Polestar_Guides/MapFrames.lua`. The selected snapshot is written as `tirisfal.lua`, with `manifest.json` and `map-frames.json`, under `--snapshot-source`. The current snapshot writer is named for this Tirisfal pilot; additional guides need their own reviewed source/output directories and coverage checks.

The command replaces matching files in the requested snapshot/output directories. Do not point those output flags at your installed addon. To adopt a refresh, review the new source/version/notices and anchors, then update the checked-in snapshot, manifest and outputs together.

## Output schema

The central object is a **guide** with an ordered `steps` array. Source metadata/provenance describes where the guide came from. The normalizer emits selected common fields and retains the source goal object in `raw` so a consumer can inspect details not yet understood by the shared schema.

```text
guide {
  schema_version,
  id,
  source,
  metadata,
  steps: [
    {
      index,
      source_step_index,
      title,
      note,
      conditions,
      raw,
      replacement_id?,
      goals: [
        {
          index,
          source_goal_index,
          kind,
          title,
          quest_id,
          objective_index?,
          npc_id,
          object_id?,
          item_id,
          count,
          prerequisites: null | { any: null | [...], all: null | [...] },
          conditions?,
          location,
          spawn_areas,
          raw
        }
      ]
    }
  ]
}
```

### Fields and identity

| Field | Meaning |
|---|---|
| `id` | The source guide's identity. It is not a quest ID. |
| `index` | **1-based sequential display order** in the final edited array. Step indices are guide-local; goal indices are step-local. They are reassigned after overrides. |
| `source_step_index` | Original source step identity, preserved across exclusions/reordering of display indices. Used by replacement anchors. |
| `source_goal_index` | Original goal identity within its source step. Preserved even when neighboring goals are removed. |
| `title` | Source/user-authored step or goal title. |
| `conditions` | Opaque condition data preserved for a future consumer. The compiler does not run the expressions or decide whether they hold. |
| `kind` | Normalized action/goal kind, such as accepting a quest, doing an objective, turning in a quest or traveling. Inspect `raw` for source-specific detail. |
| `quest_id` | The quest directly addressed by this goal, when explicitly known. It is the field used by exclusions. |
| `objective_index` | Provider-specific objective identity, when present. Its indexing convention is not silently converted. |
| `npc_id` / `object_id` / `item_id` | Explicit entity relationships when the source supplies them; null is unknown/unspecified. |
| `count` | Explicit required count, when supplied. Null is not converted to 1. |
| `prerequisites.any` | Alternative prerequisite quest IDs, kept distinct from grouped prerequisites. |
| `prerequisites.all` | Grouped prerequisite quest IDs. No flattening into an assumed expression. |
| `location` | Source map coordinates and the coordinate result/limitations described below. |
| `spawn_areas` | Decoded `spotsPacked` records with the raw tuple, source fields and normalized location for each area. |
| `raw` | Parsed source goal fields, including fields without a normalized counterpart. This preserves data, not original whitespace; bundled source/hash preserves the original file identity. |
| `replacement_id` | Provenance attached to steps explicitly inserted by a named user-authored replacement. |

Original goals are identified by guide ID + source step/goal indices. Inserted goals also need their `replacement_id`, because authored source indices can overlap the base guide or another replacement. `metadata` preserves provider header fields, including class/race/faction/level context and name/text lookup tables; placeholder titles such as `{npc:1568}` are not necessarily resolved prose.

The same quest can legitimately occur in accept, objective and turn-in goals. Repeated quest IDs do not make those goals duplicates. Use guide/step/goal identity to address a record, not quest ID alone.

Unknown, absent and empty values matter. Missing/null prerequisites are not proof of no requirements, and a coordinate or entity reference absent from the source is not filled with a nearby guess. An empty prerequisite list describes the explicit data available in that list; it does not establish full server-side availability.

Source `pre` maps to `prerequisites.any`, and `preAll` maps to `prerequisites.all`. If only one is supplied, the other stays null. A goal with neither field has `prerequisites: null`.

### Data the consumer still needs

An ordered guide supplies intent and sequence. QuestieDB or another audited facts provider can supply eligibility/objective/location facts. The consuming application separately reconciles current quest progress, completion history, class/race/level, inventory, skills, reputation and actual NPC offers. It also supplies reachable 3D travel and special interaction procedures. A valid JSON guide and a passed schema check do not establish those runtime behaviors.

## Coordinate contract

### Keep these identities separate

- `raw.map` / `ui_map_id` is a **UiMapID**.
- `continent_id` / `world_map_id` is the frame's **`c` world-map identity**, as returned by Polestar's MapToWorld convention. It is not a UiMapID; 0 is a valid value. Some such IDs describe instance maps rather than geographical continents.
- Source `x`/`y` are **map percentages in 0-100**, not world coordinates or fractions in 0-1.
- Normalized `location.coordinate_system` is `"percent"`; top-level `x`/`y` remain source percentages. `location.raw`, `present_fields`, `frame`, `status` and `warnings` preserve the context and missingness.
- Source `z` and `r` are retained without inventing a height, layer or radius transformation. Only XY is transformed here.

### Era reference output

Compiled Polestar goals with **`f="e"`** use the registered **Era map frame**. When that exact UiMapID has documented bounds, the helper computes:

```text
world X = top  + (bottom - top) * map y / 100
world Y = left + (right  - left) * map x / 100
world-map ID = c
```

Note the axis order: horizontal map x affects world Y; vertical map y affects world X.

This is an **`era_reference` coordinate**, not a verified current/live Forever position. In the underlying helper, it appears as:

```text
status = "resolved_era_reference"
frame = "era"
world_frame = "era"
world_xy = {x: ..., y: ...}
live_world_xy = null
live_verified = false
```

The bundled frame JSON contains the raw registered bounds. The manifest records its bundled hash and the original MapFrames file path/hash. This makes the calculation reproducible; it does not verify terrain placement, heights, floors, doors, lifts or walkability in the present game build. In particular, do not use a correct-looking 2D point to infer the correct Undercity surface or lift approach.

### Live coordinates are unsupported by the bundled frame catalog

An absent `f` selects Polestar's **live** frame. The addon normally resolves it through C_Map game APIs. The offline compiler does not call those APIs, and its bundled MapFrames catalog supplies **Era bounds only**. It therefore leaves live-world XY unresolved:

```text
status = "unresolved_live_frame"
frame = "live"
world_xy = null
live_world_xy = null
live_verified = false
```

**It never borrows Era bounds to make an unmarked/live point appear resolved.** Unknown Era map bounds and unsupported frame markers also remain explicit unresolved results. Raw map/x/y/f/z/r are preserved, including their presence/absence information.

The helper can accept a separately supplied, documented live-bounds catalog. Such bounds are input data, not a live observation, and still do not set `live_verified=true`. That extension is not present in the bundled pilot catalog. Do not describe the pilot's Era reference output as automatic Era-to-current-Forever conversion.

## Excluding quests

An override can list exact quest IDs:

```json
{
  "exclude_quest_ids": [101],
  "replacement_notes": {
    "101": "Synthetic example: omit this quest and review its dependencies."
  }
}
```

The example IDs are format examples, not recommendations for the Tirisfal pilot.

Exclusion removes every goal whose **own normalized `quest_id`** is in that list, across action kinds. It preserves other goals, conditions, raw fields and source indices. Empty source steps remain, so source-step anchors stay meaningful. Final display indices are reassigned sequentially.

Remaining explicit `prerequisites.any/all` references to excluded quests receive dependency warnings. The compiler **does not remove follow-ups automatically**, rewrite their requirements, search opaque conditions for hidden dependencies or select a substitute quest. A travel/interact goal with no matching `quest_id` also remains; review whether it still makes sense for the edited route.

The file [examples/exclude-escort.json](examples/exclude-escort.json) provides a real-ID example for quest `99144`; it is an example, not a recommendation to remove it from every route. Try it separately:

```powershell
python compile_polestar.py --source sources/polestar-0.3.4/tirisfal.lua --manifest sources/polestar-0.3.4/manifest.json --frames sources/polestar-0.3.4/map-frames.json --overrides examples/exclude-escort.json --out scratch/exclude-escort
```

`replacement_notes` are annotations. A note alone inserts no route data and cannot replace a removed quest.

## Replacing a quest or route segment

Replacement is an explicit **user-authored data edit**, with this shape:

```text
replacements: [
  {
    id: "unique-replacement-id",
    remove_quest_ids: [positive quest IDs to remove],
    after_source_step: original base source-step index,
    reason: "why this authored replacement exists",
    steps: [complete normalized step objects]
  }
]
```

Each supplied step follows the full normalized step/goal schema above, including valid own `index`, `source_step_index` and `source_goal_index` values. It is not merely a replacement quest ID or free-text instruction. The author supplies the intended accept/objective/turn-in/travel sequence, explicit dependencies, conditions and locations, with unknown fields honestly marked. Supply the complete replacement sequence needed for the intended edit.

The compiler adds `replacement_id` to inserted steps for provenance and preserves their supplied source indices. Those source indices belong to that user-authored replacement; they are not a claim that the inserted steps came from the original Polestar guide. Their final display indices are reassigned after insertion.

### Removal, anchors and ordering

- `remove_quest_ids` removes matching quest goals from the base guide. A replacement may remove and reinsert the **same** quest ID when deliberately correcting its authored steps.
- `after_source_step` addresses the **original base guide's source-step index**, not a renumbered display index and not a step inserted by another replacement. The pre-edit base index is the fallback only when an older record lacks its explicit source index.
- Empty base steps remain, so an anchor still exists after its quest goals are removed.
- Multiple replacements may share an anchor; their insertion order follows their order in the replacements array.
- Source indices are retained. The final guide's displayed step indices and each step's displayed goal indices become 1-based sequential values after all edits.

### Invalid edits fail before mutation

Duplicate replacement IDs, unknown anchors, malformed replacement steps, and conflicting global exclusion/replacement requests are errors. In particular, do not put the same quest ID in global `exclude_quest_ids` and a replacement's removal or inserted-goal IDs. Use that replacement's own `remove_quest_ids` for a replacement operation. This makes the intended edit unambiguous.

Overrides operate on a copy; the original compiled guide remains available for comparison. The report lists removals and insertions and identifies explicit dependencies that still reference removed/excluded quests. A structurally valid replacement can still be incomplete or unsuitable in game and needs review by its author/consumer.

Opaque `only`, `when`, `skipto`, `closedBy` and other flow fields are preserved unchanged. They are not evaluated or remapped to new display indices. Dependency analysis covers explicit `prerequisites.any/all` only; the consumer must interpret provider semantics and review hidden flow/quest-chain effects after edits. There is no XP balance, reachability or optimal-order validation.

**There is no automatic “nearest quest,” XP-equivalent quest, nearby NPC or alternative-route substitution.** That would require a separate planner and live/facts evaluation; it is not implied by the replacement format.

The complete copyable file [examples/replacement.demo.json](examples/replacement.demo.json) demonstrates removing quest `99144` and inserting one authored step after source step `1`. Its quest `999001`, NPC `999002`, location and sequence are **fabricated format examples**, not real playable content. It deliberately does not supply a complete quest lifecycle. It is not enabled in the default override file.

```powershell
python compile_polestar.py --source sources/polestar-0.3.4/tirisfal.lua --manifest sources/polestar-0.3.4/manifest.json --frames sources/polestar-0.3.4/map-frames.json --overrides examples/replacement.demo.json --out scratch/replacement-demo
```

That demonstration produces 67 display steps. The inserted step has display index `2`, `source_step_index: 10001` and a named `replacement_id`; original source step `2` becomes display step `3`. This illustrates why anchors must use the original source index. Replace every fabricated fact, supply the actual accept/objective/turn-in sequence and choose a verified appropriate anchor before adapting it to real content.

## Validation and reports

Validation checks data shape, IDs, indices, finite/ranged coordinates where units are known, and explicit prerequisite references. It reports unknown/unmapped information rather than filling it. A supplied audited facts catalog can support existence checks; without one, an external quest reference is not proof that the quest does not exist.

Inspect each goal and spawn area's `location.status`, `reason`, `warnings` and `live_verified` directly as well. Frame-resolution warnings such as `unresolved_live_frame` are recorded on the location; they are not automatically promoted into `report.validation.issues`. The validator checks goal map/XY/units, not current terrain or the completeness of spawn areas and opaque flow conditions.

An override report includes:

```text
excluded_quest_ids
removed_goals
inserted_steps
replacement_ids
replacement_notes
replacement_goals_added
dependent_warnings
issues
```

Review both errors and warnings. Errors indicate malformed/conflicting inputs that should block accepting the compiled result. Warnings identify missing facts, external dependencies, unresolved coordinates, empty steps or edits that require a human decision. Neither warning-free output nor an existing quest ID proves current availability, route efficiency or execution readiness.

Use display indices when presenting the edited sequence. Use original source indices plus guide/replacement provenance when diagnosing or maintaining overrides. This keeps an override anchored when an earlier quest is excluded and its displayed position changes.

The compiler validates the final guide and returns exit code **0** when there are no structural errors, even if warnings remain; structural errors produce **1**. Invalid source/override inputs fail with a nonzero status. Argument errors also return nonzero. The JSON report is the detailed review artifact; a zero exit code is not a claim of game compatibility.

`report.json` contains `source_stats`, `compiled_stats`, `validation.errors/warnings/issues`, the source manifest and `overrides`. Final validation includes explicit retained-dependency warnings. `overrides.issues` also retains replacement-local prevalidation diagnostics and empty-anchor annotations; these have their own local context and are not added again to the final warning total. Validation paths such as `$.steps[1].goals[0]` use zero-based JSON array positions, independently of the displayed `index` fields.

`quest-index.json` is an array sorted by `quest_id`, with `titles` and `occurrences`. Each occurrence records display/source indices, kind, conditions, prerequisites and `replacement_id` (null for original steps). Use it to locate all actions associated with a quest before editing it.

The checked-in tooling passed **53 offline tests**, including actual pinned-source rebuilds, deterministic outputs, exclusions, replacement insertion, invalid anchors, manifest integrity and dependency-warning propagation. No route was executed in game by these tests.

## Parser scope and source fidelity

The parser handles the restricted compiled-data subset used by the selected Polestar source: literal tables, finite numbers, UTF-8/escaped strings, booleans, nil and already-parsed table aliases with constant lookups. It rejects unsupported expressions/calls instead of running them. It also lexes comments/strings so a comment mentioning a registration function is not imported as a real call.

It is a **static data extractor**, not a Lua interpreter or control-flow/scope simulator. Extraction is restricted to the selected guide's source block. Nil is recorded as JSON null rather than executing Lua table deletion; empty Lua tables have no intrinsic array/object distinction. Positional tables become arrays; keyed/mixed tables preserve their explicit keys. Raw source files/hashes remain the authority for auditing a source detail or extending supported syntax.

Do not silently discard an unsupported construct or replace unresolved data with a guessed default. Add a supported, tested data transformation only after inspecting the actual source semantics and update provenance/schema documentation with it.

## Sources, licensing and attribution

The pilot's ordered instructions originate in Polestar's authored guide data. Its supporting reference values have the provenance and third-party notices distributed with that source. Format conversion does not erase those terms or make all bundled material newly authored by this project.

Keep the repository's LICENSE/NOTICE materials, bundled source notices and generated provenance with distributed outputs. In particular:

- Preserve the original Polestar source identity/version/path and SHA-256 values.
- Preserve the guide/data notices relevant to the selected source, including the MapFrames input notices.
- Distinguish authored guide text/sequence from reference facts, Python compiler code and external runtime consumers; their provenance and applicable terms are not interchangeable.
- Do not assume a source license permits copying paid guides or unrelated route packs. This pilot reads the identified local/bundled Polestar material; it is not a paid-guide downloader or decoder.

Useful upstream references:

- [Polestar contributor guide: Forge routes](https://polestar.guide/docs/contributors/forge/routes) describes Polestar's route tooling and authored route concepts. This pilot compiles the specified bundled/installed source; it does not claim that a Forge judge-improved route was generated locally.
- [Polestar repository](https://github.com/fitzforge/polestar) is the upstream project; see its guide format, map-frame registration and compatibility code for provider semantics.
- [Guide format](https://polestar.guide/docs/authors/guide-format) describes authored guide concepts. This pilot preserves compiled fields rather than reinterpreting them.
- [Content policy](https://polestar.guide/legal/content) and [license exception](https://polestar.guide/docs/reference/license-exception) explain upstream content terms.
- Local source paths and input hashes relevant to this snapshot are recorded in its manifest. Only the selected guide and registered frame data are bundled here; no runtime Map API observation was made.

The imported Polestar pack declares **GPL-3.0-only**. See [NOTICE.md](NOTICE.md), [Polestar license](licenses/Polestar-LICENSE.txt), [upstream data notices](licenses/Polestar-LICENSE-DATA.txt) and the [source manifest](sources/polestar-0.3.4/manifest.json). Preserve these when sharing the data and review applicable terms before incorporating it into another product.

No blanket license has been selected for the newly written Python tooling. That choice must be agreed before downstream incorporation; it does not change upstream guide/data terms. Polestar's exception for certain author-created packs is not a blanket relicensing grant for copied built-in guides.

Questie/QuestieDB and Zygor were investigated as potential sources, but **this initial dataset imports only the identified Polestar material**. It contains no Zygor paid guide data, credentials, game/bot binaries, navigation meshes or execution code.

## Development workflow

1. Reproduce the bundled-source build and inspect its reports before changing source or overrides.
2. Make one explicit data/compiler change. Preserve original source identity or record the new input hash.
3. Run the relevant parser/coordinate/validation/override tests, then rebuild the pilot.
4. Inspect the ordered JSON diff, source indices, override report, unresolved coordinate statuses and notices.
5. Hand the versioned data/report to the execution developer. Record runtime validation separately from compiler/schema tests.

Changes to step interpretation, prerequisite semantics, coordinate frames or override behavior are consumer-visible contract changes. Update this README and fixtures with them; do not silently reinterpret an existing field.
