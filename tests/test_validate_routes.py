"""Synthetic data-only contract tests; no addon data or runtime APIs."""
from copy import deepcopy
import unittest

from validate_routes import apply_overrides, validate_guide


def goal(index=0, kind="accept", quest=101):
    return {"index": index, "kind": kind, "quest_id": quest,
            "objective_index": None, "npc_id": None, "object_id": None,
            "item_id": None, "count": None, "prerequisites": {"any": [], "all": []},
            "conditions": {"opaque_source_expression": "preserve verbatim"},
            "location": {"map_id": 42, "x": 40, "y": 60, "coordinate_system": "percent"},
            "raw": {"own_test_source": "synthetic record"}}


def guide():
    return {"id": "synthetic-route", "source": {"name": "own synthetic fixture"},
            "metadata": {"known_quest_ids": [101, 102, 103]},
            "steps": [{"index": 0, "title": "Own fixture", "conditions": ["unchanged"],
                       "goals": [goal(), goal(2, "complete")]}]}


class ValidationTests(unittest.TestCase):
    def codes(self, data):
        return {item["code"] for item in validate_guide(data)}

    def test_valid_repeated_quest_ids_and_noncontiguous_original_indices(self):
        data = guide()
        before = deepcopy(data)
        self.assertEqual(validate_guide(data), [])
        self.assertEqual(data, before)

    def test_duplicate_and_reversed_indices(self):
        data = guide()
        data["steps"].extend([{"index": 0, "goals": []}, {"index": 4, "goals": []}, {"index": 1, "goals": []}])
        data["steps"][0]["goals"].append(goal(2))
        self.assertTrue({"duplicate_index", "index_order"} <= self.codes(data))

    def test_nonpositive_boolean_and_fractional_counts(self):
        for count in (0, -1, True, 1.5, "2"):
            with self.subTest(count=count):
                data = guide()
                data["steps"][0]["goals"][0]["count"] = count
                self.assertIn("invalid_count", self.codes(data))

    def test_any_all_lists_do_not_get_flattened_or_fabricated(self):
        data = guide()
        data["steps"][0]["goals"][0]["prerequisites"] = {"any": [102], "all": [103]}
        self.assertEqual(validate_guide(data), [])
        data["steps"][0]["goals"][0]["prerequisites"] = {"any": "102", "all": [False, 999], "or": []}
        self.assertTrue({"invalid_prerequisite_list", "invalid_prerequisite_id",
                         "unknown_prerequisite_reference", "unknown_prerequisite_operator"} <= self.codes(data))

    def test_unknown_facts_are_reported_without_mutation(self):
        data = guide()
        data["steps"][0]["goals"][0]["location"] = None
        data["steps"][0]["goals"][0]["prerequisites"] = None
        before = deepcopy(data)
        self.assertTrue({"unmapped_location", "unknown_prerequisites"} <= self.codes(data))
        self.assertEqual(data, before)

    def test_coordinate_units_are_explicit_not_inferred(self):
        data = guide()
        location = data["steps"][0]["goals"][0]["location"]
        location.pop("coordinate_system")
        location.pop("map_id")
        location["zone"] = "unmapped source label"
        self.assertTrue({"unmapped_map", "coordinate_system_unknown"} <= self.codes(data))
        self.assertNotIn("coordinate_range", self.codes(data))
        location["coordinate_system"] = "normalized"
        self.assertIn("coordinate_range", self.codes(data))
        location["x"] = float("nan")
        self.assertIn("invalid_coordinate", self.codes(data))

    def test_quest_reference_missing_unknown_and_external(self):
        data = guide()
        data["steps"][0]["goals"][0]["quest_id"] = None
        self.assertIn("missing_quest_reference", self.codes(data))
        data["steps"][0]["goals"][0]["quest_id"] = 999
        self.assertIn("unknown_quest_reference", self.codes(data))
        data["metadata"].pop("known_quest_ids")
        data["steps"][0]["goals"][0]["prerequisites"]["all"] = [1000]
        self.assertIn("external_prerequisite_unverified", self.codes(data))

    def test_malformed_json_like_records_do_not_crash(self):
        for data in (None, [], {}, {"id": "x", "steps": [None]},
                     {"id": "x", "steps": [{"index": 0, "goals": [None, {"index": 1, "kind": []}]}]}):
            with self.subTest(data=data):
                self.assertTrue(validate_guide(data))


class OverrideTests(unittest.TestCase):
    def test_exclude_every_matching_goal_only_and_preserve_dependencies(self):
        data = guide()
        follow = goal(7, "accept", 102)
        follow["prerequisites"] = {"any": [101, 103], "all": [101]}
        data["steps"].append({"index": 5, "title": "Keep follow-up", "conditions": {"raw": "keep"}, "goals": [follow]})
        before = deepcopy(data)
        override = {"exclude_quest_ids": [101], "replacement_notes": {"101": "review manually; do not choose a substitute"}}
        override_before = deepcopy(override)
        modified, report = apply_overrides(data, override)
        self.assertEqual(data, before)
        self.assertEqual(override, override_before)
        self.assertEqual(len(report["removed_goals"]), 2)
        self.assertEqual(modified["steps"][0]["goals"], [])
        self.assertEqual([step["index"] for step in modified["steps"]], [1, 2])
        self.assertEqual([step["source_step_index"] for step in modified["steps"]], [0, 5])
        retained = modified["steps"][1]["goals"][0]
        self.assertEqual(retained["index"], 1)
        self.assertEqual(retained["source_goal_index"], 7)
        self.assertEqual(retained["raw"], follow["raw"])
        self.assertEqual(retained["conditions"], follow["conditions"])
        self.assertEqual(retained["prerequisites"], follow["prerequisites"])
        self.assertEqual(len(report["dependent_warnings"]), 2)
        self.assertEqual(report["replacement_goals_added"], 0)
        self.assertEqual(report["replacement_notes"], override["replacement_notes"])

    def test_malformed_exclusions_fail_without_partial_changes(self):
        data = guide()
        original = deepcopy(data)
        for values in ("101", [101, False], [101, -1], [101, "102"]):
            with self.subTest(values=values):
                with self.assertRaises(ValueError):
                    apply_overrides(data, {"exclude_quest_ids": values})
                self.assertEqual(data, original)

    def replacement(self, identifier="own-route", anchor=0, removed=None, new_quest=102):
        return {"id": identifier, "remove_quest_ids": [101] if removed is None else removed,
                "after_source_step": anchor, "reason": "Original synthetic authored alternative",
                "steps": [{"index": 10, "title": "Supplied alternative", "conditions": {"keep": "step expression"},
                           "goals": [goal(7, "accept", new_quest), goal(9, "turnin", new_quest)]}]}

    def test_real_replacement_inserts_full_authored_data_after_empty_anchor(self):
        data = guide()
        data["steps"].append({"index": 8, "title": "Original next step", "conditions": None,
                              "goals": [goal(4, "accept", 103)]})
        replacement = self.replacement()
        before_data, before_replacement = deepcopy(data), deepcopy(replacement)
        modified, report = apply_overrides(data, {"replacements": [replacement]})
        self.assertEqual(data, before_data)
        self.assertEqual(replacement, before_replacement)
        self.assertEqual([step["index"] for step in modified["steps"]], [1, 2, 3])
        self.assertEqual([step["source_step_index"] for step in modified["steps"]], [0, 10, 8])
        self.assertEqual(modified["steps"][0]["goals"], [])
        inserted = modified["steps"][1]
        self.assertEqual(inserted["replacement_id"], "own-route")
        self.assertEqual(inserted["conditions"], replacement["steps"][0]["conditions"])
        self.assertEqual([goal["index"] for goal in inserted["goals"]], [1, 2])
        self.assertEqual([goal["source_goal_index"] for goal in inserted["goals"]], [7, 9])
        self.assertEqual(inserted["goals"][0]["location"], replacement["steps"][0]["goals"][0]["location"])
        self.assertEqual(inserted["goals"][0]["raw"], replacement["steps"][0]["goals"][0]["raw"])
        self.assertEqual(report["replacement_goals_added"], 2)
        self.assertEqual(report["inserted_steps"][0]["display_index"], 2)
        self.assertEqual(len(report["removed_goals"]), 2)

    def test_anchor_uses_original_source_index_not_current_display_index(self):
        data = guide()
        data["steps"][0]["source_step_index"] = 77
        data["steps"][0]["index"] = 4
        data["steps"][0]["goals"][0]["source_goal_index"] = 88
        modified, _ = apply_overrides(data, {"replacements": [self.replacement(anchor=77, removed=[])]})
        self.assertEqual(modified["steps"][0]["source_step_index"], 77)
        self.assertEqual(modified["steps"][0]["goals"][0]["source_goal_index"], 88)
        with self.assertRaises(ValueError):
            apply_overrides(data, {"replacements": [self.replacement(anchor=4)]})

    def test_multiple_replacements_same_anchor_keep_declared_order(self):
        first = self.replacement("first", removed=[101], new_quest=102)
        second = self.replacement("second", removed=[], new_quest=103)
        modified, report = apply_overrides(guide(), {"replacements": [first, second]})
        self.assertEqual([step.get("replacement_id") for step in modified["steps"]], [None, "first", "second"])
        self.assertEqual(report["replacement_ids"], ["first", "second"])

    def test_invalid_anchor_duplicate_id_and_exclusion_overlap_raise(self):
        examples = [
            {"replacements": [self.replacement(anchor=999)]},
            {"replacements": [self.replacement(), self.replacement()]},
            {"exclude_quest_ids": [101], "replacements": [self.replacement()]},
            {"exclude_quest_ids": [102], "replacements": [self.replacement()]},
        ]
        for overrides in examples:
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                apply_overrides(guide(), overrides)

    def test_invalid_supplied_replacement_data_raises(self):
        replacement = self.replacement()
        replacement["steps"][0]["goals"][0]["count"] = 0
        with self.assertRaises(ValueError):
            apply_overrides(guide(), {"replacements": [replacement]})

    def test_same_quest_authored_correction_does_not_lose_its_supplied_steps(self):
        data = guide()
        follower = goal(0, "accept", 102)
        follower["prerequisites"]["all"] = [101]
        data["steps"].append({"index": 1, "goals": [follower]})
        modified, report = apply_overrides(data, {"replacements": [self.replacement(new_quest=101)]})
        self.assertEqual([goal["quest_id"] for goal in modified["steps"][1]["goals"]], [101, 101])
        self.assertEqual(report["dependent_warnings"], [])

    def test_duplicate_removal_ownership_and_cross_replacement_reintroduction_raise(self):
        with self.assertRaises(ValueError):
            apply_overrides(guide(), {"replacements": [self.replacement("first"), self.replacement("second")]})
        with self.assertRaises(ValueError):
            apply_overrides(guide(), {"replacements": [self.replacement("first", new_quest=102),
                self.replacement("second", removed=[102], new_quest=103)]})

    def test_reapplying_same_replacement_is_not_silently_duplicated(self):
        replacement = self.replacement()
        modified, _ = apply_overrides(guide(), {"replacements": [replacement]})
        with self.assertRaises(ValueError):
            apply_overrides(modified, {"replacements": [replacement]})


if __name__ == "__main__":
    unittest.main()
