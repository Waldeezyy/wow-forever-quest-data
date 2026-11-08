"""Pure validation/override helpers for normalized quest-guide data.

No Lua execution, route execution, game/process access, network or file I/O.
Validation reports absent/unmapped facts without inventing replacements.
"""
from __future__ import annotations

from copy import deepcopy
import math

ENTITY_IDS = ("quest_id", "npc_id", "object_id", "item_id")
QUEST_KINDS = {"accept", "complete", "turnin", "turn_in", "objective", "abandon",
               "quest_accept", "quest_complete", "quest_turnin", "quest_turn_in",
               "quest_objective", "quest_abandon"}


def _integer(value, minimum=1):
    return isinstance(value, int) and not isinstance(value, bool) and value >= minimum


def _number(value):
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _issue(issues, severity, code, path, message, **details):
    entry = {"severity": severity, "code": code, "path": path, "message": message}
    if details:
        entry["details"] = details
    issues.append(entry)


def _ordered_indices(items, path, issues):
    seen, previous = set(), None
    for offset, item in enumerate(items):
        here = f"{path}[{offset}]"
        if not isinstance(item, dict):
            _issue(issues, "error", "invalid_record", here, "Expected an object.")
            continue
        value = item.get("index")
        if not _integer(value, 0):
            _issue(issues, "error", "invalid_index", here + ".index",
                   "Index must be a nonnegative integer; original numbering is preserved.")
            continue
        if value in seen:
            _issue(issues, "error", "duplicate_index", here + ".index", "Index repeats within this array.", value=value)
        elif previous is not None and value <= previous:
            _issue(issues, "error", "index_order", here + ".index",
                   "Array order must agree with strictly increasing indices.", previous=previous, value=value)
        seen.add(value)
        previous = value


def _location(location, path, issues):
    if location is None or location == {}:
        _issue(issues, "warning", "unmapped_location", path, "Location is absent/unknown; no coordinates inferred.")
        return
    if not isinstance(location, dict):
        _issue(issues, "error", "invalid_location", path, "Location must be an object or null.")
        return
    map_id = location.get("map_id", location.get("ui_map_id"))
    if map_id is None:
        _issue(issues, "warning", "unmapped_map", path, "No mapped map_id/ui_map_id; source zone text is preserved.")
    elif not _integer(map_id):
        _issue(issues, "error", "invalid_map_id", path + ".map_id", "Mapped map ID must be a positive integer.")
    if location.get("unmapped") is True or location.get("mapped") is False:
        _issue(issues, "warning", "source_marks_unmapped", path, "Source explicitly marks this location unmapped.")
    coords = []
    for name in ("x", "y"):
        value = location.get(name)
        if value is None:
            _issue(issues, "warning", "missing_coordinate", path + "." + name, "Coordinate is unknown.")
        elif not _number(value):
            _issue(issues, "error", "invalid_coordinate", path + "." + name, "Coordinate must be a finite number.")
        else:
            coords.append((name, value))
    if location.get("z") is not None and not _number(location["z"]):
        _issue(issues, "error", "invalid_coordinate", path + ".z", "Optional z must be finite.")
    system = location.get("coordinate_system")
    if system in ("normalized", "percent"):
        maximum = 1 if system == "normalized" else 100
        for name, value in coords:
            if not 0 <= value <= maximum:
                _issue(issues, "error", "coordinate_range", path + "." + name,
                       f"{system} coordinates must lie in0..{maximum}.")
    elif system not in ("world",):
        _issue(issues, "warning", "coordinate_system_unknown", path + ".coordinate_system",
               "Units are unknown; no normalized/percent/world conversion was attempted.")


def _catalog(guide, issues):
    metadata = guide.get("metadata")
    if not isinstance(metadata, dict):
        return None
    values = metadata.get("known_quest_ids")
    if values is None:
        return None
    if not isinstance(values, list):
        _issue(issues, "error", "invalid_quest_catalog", "$.metadata.known_quest_ids", "Quest catalog must be a list of positive IDs.")
        return None
    known = set()
    for index, value in enumerate(values):
        if not _integer(value):
            _issue(issues, "error", "invalid_quest_catalog_id", f"$.metadata.known_quest_ids[{index}]", "Quest ID must be positive.")
        else:
            known.add(value)
    return known


def _all_goals(guide):
    steps = guide.get("steps", []) if isinstance(guide, dict) else []
    if not isinstance(steps, list):
        return
    for step_offset, step in enumerate(steps):
        goals = step.get("goals", []) if isinstance(step, dict) else []
        if isinstance(goals, list):
            for goal_offset, goal in enumerate(goals):
                if isinstance(goal, dict):
                    yield step_offset, goal_offset, goal, f"$.steps[{step_offset}].goals[{goal_offset}]"


def validate_guide(guide):
    """Return structured issues without changing guide or resolving facts.

    Indices may start at0 or1 and have gaps, but must be unique and increasing
    in their own arrays. Repeated entity IDs are expected across route actions.
    Optional metadata.known_quest_ids enables actual quest-reference checks.
    """
    issues = []
    if not isinstance(guide, dict):
        return [{"severity": "error", "code": "invalid_guide", "path": "$", "message": "Guide must be an object."}]
    if not isinstance(guide.get("id"), str) or not guide["id"].strip():
        _issue(issues, "error", "missing_guide_id", "$.id", "Guide needs a nonempty string ID.")
    if not guide.get("source"):
        _issue(issues, "warning", "missing_source", "$.source", "Source provenance is absent/unknown.")
    if not isinstance(guide.get("metadata"), dict):
        _issue(issues, "warning", "missing_metadata", "$.metadata", "Metadata object is absent/unknown.")
    known = _catalog(guide, issues)
    steps = guide.get("steps")
    if not isinstance(steps, list):
        _issue(issues, "error", "invalid_steps", "$.steps", "Steps must be an ordered array.")
        return issues
    if not steps:
        _issue(issues, "warning", "empty_guide", "$.steps", "Guide has no steps.")
    _ordered_indices(steps, "$.steps", issues)
    in_guide = {goal["quest_id"] for _, _, goal, _ in _all_goals(guide) if _integer(goal.get("quest_id"))}
    for step_offset, step in enumerate(steps):
        if not isinstance(step, dict):
            continue
        path = f"$.steps[{step_offset}]"
        goals = step.get("goals")
        if not isinstance(goals, list):
            _issue(issues, "error", "invalid_goals", path + ".goals", "Goals must be an ordered array.")
            continue
        if not goals:
            _issue(issues, "warning", "empty_step", path + ".goals", "Step has no goals; it has not been discarded or renumbered.")
        _ordered_indices(goals, path + ".goals", issues)
        for goal_offset, goal in enumerate(goals):
            if not isinstance(goal, dict):
                continue
            here = path + f".goals[{goal_offset}]"
            kind = goal.get("kind")
            if not isinstance(kind, str) or not kind.strip():
                _issue(issues, "error", "missing_goal_kind", here + ".kind", "Goal kind must be a nonempty string.")
            kind_name = kind if isinstance(kind, str) else None
            for field in ENTITY_IDS:
                value = goal.get(field)
                if value is not None and not _integer(value):
                    _issue(issues, "error", "invalid_entity_id", here + "." + field, "Normalized entity ID must be a positive integer.")
            quest_id = goal.get("quest_id")
            if (kind_name in QUEST_KINDS or goal.get("objective_index") is not None) and quest_id is None:
                _issue(issues, "error", "missing_quest_reference", here + ".quest_id", "Quest goal/objective needs its quest ID; no ID inferred.")
            if _integer(quest_id) and known is not None and quest_id not in known:
                _issue(issues, "error", "unknown_quest_reference", here + ".quest_id", "Quest ID is absent from the supplied catalog.", quest_id=quest_id)
            objective = goal.get("objective_index")
            if objective is not None and not _integer(objective, 0):
                _issue(issues, "error", "invalid_objective_index", here + ".objective_index", "Objective index must be a nonnegative integer when supplied.")
            count = goal.get("count")
            if count is not None and not _integer(count):
                _issue(issues, "error", "invalid_count", here + ".count", "Count must be a positive integer when supplied; null remains unspecified.")
            if "raw" not in goal or goal["raw"] is None:
                _issue(issues, "warning", "missing_raw", here + ".raw", "Original source record/text is absent/unknown.")
            _location(goal.get("location"), here + ".location", issues)
            prerequisites = goal.get("prerequisites")
            if prerequisites is None:
                _issue(issues, "warning", "unknown_prerequisites", here + ".prerequisites", "Prerequisites were not supplied; no empty AND/OR lists inferred.")
                continue
            if not isinstance(prerequisites, dict):
                _issue(issues, "error", "invalid_prerequisites", here + ".prerequisites", "Expected {any: [...], all: [...]} or null.")
                continue
            for operator in prerequisites.keys() - {"any", "all"}:
                _issue(issues, "error", "unknown_prerequisite_operator", here + ".prerequisites." + str(operator), "Only explicit any/all operators are understood.")
            for operator in ("any", "all"):
                values = prerequisites.get(operator)
                subpath = here + ".prerequisites." + operator
                if values is None:
                    _issue(issues, "warning", "unknown_prerequisite_list", subpath, "List absent/unknown; no assumptions about conjunction made.")
                    continue
                if not isinstance(values, list):
                    _issue(issues, "error", "invalid_prerequisite_list", subpath, "Prerequisite any/all values must be arrays.")
                    continue
                seen = set()
                for offset, value in enumerate(values):
                    refpath = subpath + f"[{offset}]"
                    if not _integer(value):
                        _issue(issues, "error", "invalid_prerequisite_id", refpath, "Prerequisite quest ID must be a positive integer.")
                        continue
                    if value in seen:
                        _issue(issues, "warning", "duplicate_prerequisite", refpath, "Repeated prerequisite preserved as supplied.", quest_id=value)
                    seen.add(value)
                    if known is not None and value not in known:
                        _issue(issues, "error", "unknown_prerequisite_reference", refpath, "Prerequisite ID absent from supplied quest catalog.", quest_id=value)
                    elif known is None and value not in in_guide:
                        _issue(issues, "warning", "external_prerequisite_unverified", refpath, "Prerequisite is outside this guide and no quest catalog was supplied; may be legitimate external content.", quest_id=value)
    return issues


def apply_overrides(guide, overrides):
    """Return (edited deep copy, report) for exclusions and authored replacements.

    Invalid/ambiguous overrides raise ValueError. Removals affect original goals
    only; supplied replacement steps are inserted after stable original anchors.
    Display indices become sequential1-based while original source indices stay.
    No replacement content is invented and no dependent quest is auto-pruned.
    """
    if not isinstance(guide, dict) or not isinstance(overrides, dict):
        raise ValueError("Guide and overrides must be objects")

    def ids(values, label):
        if not isinstance(values, list) or any(not _integer(value) for value in values):
            raise ValueError(label + " must be a list of positive quest IDs")
        if len(set(values)) != len(values):
            raise ValueError(label + " contains duplicate quest IDs")
        return set(values)

    def source_indices(step, label):
        if not isinstance(step, dict) or not isinstance(step.get("goals"), list):
            raise ValueError(label + " must be a normalized step object with a goals array")
        value = step.get("source_step_index", step.get("index"))
        if not _integer(value, 0):
            raise ValueError(label + " needs a nonnegative source_step_index or index")
        seen_goals = set()
        for offset, goal in enumerate(step["goals"]):
            if not isinstance(goal, dict):
                raise ValueError(f"{label}.goals[{offset}] must be an object")
            original = goal.get("source_goal_index", goal.get("index"))
            if not _integer(original, 0):
                raise ValueError(f"{label}.goals[{offset}] needs a nonnegative source_goal_index or index")
            if original in seen_goals:
                raise ValueError(label + " has duplicate source_goal_index values")
            seen_goals.add(original)
        return value

    excluded = ids(overrides.get("exclude_quest_ids", []), "exclude_quest_ids")
    notes = overrides.get("replacement_notes", {})
    if not isinstance(notes, dict):
        raise ValueError("replacement_notes must be an object")
    replacements = overrides.get("replacements", [])
    if not isinstance(replacements, list):
        raise ValueError("replacements must be an array")
    original_steps = guide.get("steps")
    if not isinstance(original_steps, list):
        raise ValueError("Guide.steps must be an ordered array")
    anchors, existing_ids = {}, set()
    for offset, step in enumerate(original_steps):
        anchor = source_indices(step, f"Guide.steps[{offset}]")
        prior_override = step.get("replacement_id")
        if prior_override is not None:
            if not isinstance(prior_override, str) or not prior_override.strip():
                raise ValueError("Existing replacement_id provenance must be a nonempty string")
            existing_ids.add(prior_override)
            continue  # inserted steps must never become ORIGINAL source anchors
        if anchor in anchors:
            raise ValueError(f"Ambiguous duplicate original source_step_index: {anchor}")
        anchors[anchor] = offset

    report = {"excluded_quest_ids": sorted(excluded), "replacement_ids": [],
              "removed_goals": [], "inserted_steps": [], "dependent_warnings": [],
              "issues": [], "replacement_notes": deepcopy(notes), "replacement_goals_added": 0,
              "dependency_analysis_scope": "explicit prerequisites.any/all only; opaque conditions/raw are preserved, not interpreted"}
    prepared, replacement_ids, removal_owner = [], set(), {}
    for offset, replacement in enumerate(replacements):
        label = f"replacements[{offset}]"
        if not isinstance(replacement, dict):
            raise ValueError(label + " must be an object")
        identifier = replacement.get("id")
        if not isinstance(identifier, str) or not identifier.strip():
            raise ValueError(label + ".id must be a nonempty string")
        if identifier in replacement_ids or identifier in existing_ids:
            raise ValueError("Duplicate/already-applied replacement id: " + identifier)
        replacement_ids.add(identifier)
        anchor = replacement.get("after_source_step")
        if not _integer(anchor, 0) or anchor not in anchors:
            raise ValueError(f"{label}.after_source_step is not an original source anchor: {anchor!r}")
        reason = replacement.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError(label + ".reason must be a nonempty string")
        removed = ids(replacement.get("remove_quest_ids", []), label + ".remove_quest_ids")
        overlap = excluded & removed
        if overlap:
            raise ValueError(f"{label} removal conflicts with exclude_quest_ids: {sorted(overlap)}")
        for quest_id in removed:
            if quest_id in removal_owner:
                raise ValueError(f"Quest{quest_id} is removed by multiple replacements: {removal_owner[quest_id]}, {identifier}")
            removal_owner[quest_id] = identifier
        supplied_steps = replacement.get("steps")
        if not isinstance(supplied_steps, list) or not supplied_steps:
            raise ValueError(label + ".steps must contain authored normalized steps")
        seen_source = set()
        for step_offset, step in enumerate(supplied_steps):
            original = source_indices(step, f"{label}.steps[{step_offset}]")
            if original in seen_source:
                raise ValueError(label + " has duplicate replacement source_step_index")
            seen_source.add(original)
            if "replacement_id" in step and step["replacement_id"] != identifier:
                raise ValueError(label + " supplied step has conflicting replacement_id provenance")
        # Structural/data validation only. No copied source Lua is evaluated.
        issues = validate_guide({"id": identifier, "source": {"override_id": identifier},
                                 "metadata": {}, "steps": supplied_steps})
        failures = [issue for issue in issues if issue["severity"] == "error"]
        if failures:
            raise ValueError(label + " has invalid replacement data: " + "; ".join(
                issue["code"] + " at " + issue["path"] for issue in failures))
        for issue in issues:
            issue["replacement_id"] = identifier
            report["issues"].append(issue)
        inserted_ids = {goal["quest_id"] for _, _, goal, _ in _all_goals({"steps": supplied_steps})
                        if _integer(goal.get("quest_id"))}
        overlap = excluded & inserted_ids
        if overlap:
            raise ValueError(f"{label} reintroduces globally excluded quest IDs: {sorted(overlap)}")
        prepared.append({"id": identifier, "anchor": anchor, "reason": reason,
                         "removed": removed, "inserted_ids": inserted_ids,
                         "steps": deepcopy(supplied_steps)})
    for replacement in prepared:
        conflicts = {quest_id: removal_owner[quest_id] for quest_id in replacement["inserted_ids"]
                     if quest_id in removal_owner and removal_owner[quest_id] != replacement["id"]}
        if conflicts:
            raise ValueError(f"Replacement{replacement['id']} inserts quests removed by another replacement: {conflicts}")

    # Validation above is complete before the deep-copied data is edited.
    result = deepcopy(guide)
    removed_ids = excluded | set(removal_owner)
    for step_offset, step in enumerate(result["steps"]):
        if "source_step_index" not in step:
            step["source_step_index"] = step["index"]
        retained = []
        for goal_offset, goal in enumerate(step["goals"]):
            if "source_goal_index" not in goal:
                goal["source_goal_index"] = goal["index"]
            value = goal.get("quest_id")
            if _integer(value) and value in removed_ids:
                report["removed_goals"].append({"path_before_override": f"$.steps[{step_offset}].goals[{goal_offset}]",
                    "step_index": step.get("index"), "source_step_index": step["source_step_index"],
                    "goal_index": goal.get("index"), "source_goal_index": goal["source_goal_index"],
                    "kind": goal.get("kind"), "quest_id": value,
                    "reason": "exclusion" if value in excluded else "replacement",
                    "replacement_id": removal_owner.get(value)})
            else:
                retained.append(goal)
        step["goals"] = retained

    by_anchor = {}
    for replacement in prepared:
        report["replacement_ids"].append(replacement["id"])
        by_anchor.setdefault(replacement["anchor"], []).append(replacement)
    edited = []
    for step in result["steps"]:
        edited.append(step)
        if step.get("replacement_id") is not None:
            continue
        for replacement in by_anchor.get(step["source_step_index"], []):
            for inserted in replacement["steps"]:
                if "source_step_index" not in inserted:
                    inserted["source_step_index"] = inserted["index"]
                inserted["replacement_id"] = replacement["id"]
                for goal in inserted["goals"]:
                    if "source_goal_index" not in goal:
                        goal["source_goal_index"] = goal["index"]
                edited.append(inserted)
                report["replacement_goals_added"] += len(inserted["goals"])
                report["inserted_steps"].append({"replacement_id": replacement["id"],
                    "after_source_step": replacement["anchor"], "reason": replacement["reason"],
                    "source_step_index": inserted["source_step_index"], "display_index": len(edited),
                    "goal_count": len(inserted["goals"])})
    result["steps"] = edited
    for step_index, step in enumerate(edited, 1):
        step["index"] = step_index
        for goal_index, goal in enumerate(step["goals"], 1):
            goal["index"] = goal_index
        if not step["goals"]:
            _issue(report["issues"], "warning", "empty_step_retained", f"$.steps[{step_index-1}]",
                   "Empty original step retained as a stable anchor; display index was reassigned.")
    reintroduced = set().union(*(entry["inserted_ids"] for entry in prepared)) if prepared else set()
    unavailable = removed_ids - reintroduced
    for _, _, goal, path in _all_goals(result):
        prerequisites = goal.get("prerequisites")
        if not isinstance(prerequisites, dict):
            continue
        for operator in ("any", "all"):
            refs = prerequisites.get(operator)
            if not isinstance(refs, list):
                continue
            matches = sorted({value for value in refs if _integer(value) and value in unavailable})
            if matches:
                _issue(report["dependent_warnings"], "warning", "excluded_prerequisite_retained",
                       path + ".prerequisites." + operator,
                       "Goal still references removed quest IDs not reintroduced by authored replacements; it was not pruned.",
                       quest_id=goal.get("quest_id"), excluded_prerequisite_ids=matches, operator=operator)
    return result, report
