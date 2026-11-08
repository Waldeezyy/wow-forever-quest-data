# WoW Forever Quest Data

Data compilation for a bot-specific leveling guide. This repository supplies ordered quest/goal data; bot execution belongs to the consuming developer.

The initial pilot imports Polestar's Undead/Tirisfal guide into portable JSON. It preserves order, dependencies, character conditions, original coordinates and source attribution. An override file removes explicitly excluded quests and records replacement notes. Replacement selection is a reviewed data task, not an automatic nearest-quest decision.

## Scope

- Compile guide content into an explicit, inspectable data contract.
- Maintain bot-specific exclusions and replacement decisions with reasons.
- Preserve coordinate frames, unresolved information and upstream provenance.
- Validate the resulting route data and publish small, reviewable updates.

The repository does not control WoW or implement quest execution, combat, movement, process inspection, authentication changes or anti-cheat functionality.

## Initial status

The repository is being populated with the first compiler and Tirisfal dataset. Data coverage and validation results will be recorded alongside that export. A compiled sample is not a claim that the bot can execute every quest in it.

## Source rights

Polestar's built-in guide pack declares **GPL-3.0-only**. Imported guide content retains its upstream terms and attribution; a format conversion does not grant permission to treat that content as proprietary. Third-party reference facts have additional source notices. No project-wide license has yet been assigned to the newly written tooling; see `NOTICE.md`.

Sources under investigation:

- [Polestar guide format](https://polestar.guide/docs/authors/guide-format)
- [Polestar route generator and JSON outputs](https://polestar.guide/docs/contributors/forge/routes)
- [QuestieDB](https://github.com/Questie/QuestieDB)

Zygor is a possible reference/provider only with appropriate access and content-use permission; no Zygor content is included.
