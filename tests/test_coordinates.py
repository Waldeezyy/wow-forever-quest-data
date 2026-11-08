"""Pure offline tests; no Lua execution, game APIs or installed-file writes."""
import copy
import math
from pathlib import Path
import tempfile
import unittest

from coordinates import build_frame_catalog, normalize_location

TIRISFAL = {"c": 0, "left": 3033.333, "right": -1485.417, "top": 3837.5, "bottom": 825}


class NormalizeLocationTests(unittest.TestCase):
    def setUp(self):
        self.catalog = {"era": {"1420": dict(TIRISFAL)}, "live": {}}

    def test_era_axes_corners_and_continent_zero(self):
        a = normalize_location({"map": 1420, "x": 0, "y": 0, "f": "e"}, self.catalog)
        b = normalize_location({"map": 1420, "x": 100, "y": 100, "f": "e"}, self.catalog)
        self.assertEqual(a["world_xy"], {"x": 3837.5, "y": 3033.333})
        self.assertEqual(b["world_xy"], {"x": 825.0, "y": -1485.417})
        self.assertEqual(a["continent_id"], 0)
        self.assertEqual(a["ui_map_id"], 1420)
        self.assertEqual(a["map_id_kind"], "UiMapID")

    def test_known_era_point_is_not_claimed_live(self):
        got = normalize_location({"map": 1420, "x": 30.22, "y": 72.88, "f": "e"}, self.catalog)
        self.assertAlmostEqual(got["world_xy"]["x"], 1641.99)
        self.assertAlmostEqual(got["world_xy"]["y"], 1667.76675)
        self.assertEqual(got["status"], "resolved_era_reference")
        self.assertEqual(got["world_frame"], "era")
        self.assertIsNone(got["live_world_xy"])
        self.assertFalse(got["live_verified"])

    def test_raw_height_radius_and_missingness_preserved_without_mutation(self):
        goal = {"map": 1420, "x": 50, "y": 50, "f": "e", "z": -12.3, "r": 0, "t": "goto"}
        before_goal, before_catalog = copy.deepcopy(goal), copy.deepcopy(self.catalog)
        got = normalize_location(goal, self.catalog)
        self.assertEqual(got["raw"], {key: goal[key] for key in ("map", "x", "y", "f", "z", "r")})
        self.assertNotIn("z", got["world_xy"])
        self.assertEqual(goal, before_goal)
        self.assertEqual(self.catalog, before_catalog)
        absent = normalize_location({"t": "level"}, self.catalog)
        self.assertEqual(absent["status"], "no_location")
        self.assertEqual(absent["present_fields"], [])

    def test_live_point_does_not_borrow_era_bounds(self):
        got = normalize_location({"map": 1420, "x": 50, "y": 50}, self.catalog)
        self.assertEqual(got["status"], "unresolved_live_frame")
        self.assertIsNone(got["world_xy"])
        self.assertIsNone(got["continent_id"])

    def test_explicit_live_catalog_remains_unverified(self):
        self.catalog["live"]["1420"] = {"c": 0, "top": 100, "bottom": 200, "left": 300, "right": 500}
        got = normalize_location({"map": 1420, "x": 25, "y": 50}, self.catalog)
        self.assertEqual(got["live_world_xy"], {"x": 150.0, "y": 350.0})
        self.assertEqual(got["world_frame"], "live")
        self.assertFalse(got["live_verified"])

    def test_unknown_map_and_marker_explicit(self):
        unknown = normalize_location({"map": 9999, "x": 20, "y": 30, "f": "e"}, self.catalog)
        marker = normalize_location({"map": 1420, "x": 20, "y": 30, "f": "surprise"}, self.catalog)
        self.assertEqual(unknown["status"], "unknown_era_frame")
        self.assertEqual(marker["status"], "unsupported_frame")
        self.assertIsNone(unknown["world_xy"])
        self.assertIsNone(marker["world_xy"])

    def test_invalid_numbers_sentinels_and_partial_locations_rejected(self):
        for patch in ({"map": 0}, {"map": True}, {"map": "1420"}, {"x": -1},
                      {"x": 101}, {"x": True}, {"x": math.nan}, {"y": math.inf}, {"y": None}):
            goal = {"map": 1420, "x": 50, "y": 50, "f": "e", **patch}
            with self.subTest(patch=patch):
                got = normalize_location(goal, self.catalog)
                self.assertEqual(got["status"], "invalid_location")
                self.assertIsNone(got["world_xy"])

    def test_bad_bounds_do_not_silently_transform(self):
        for patch in ({"c": None}, {"c": True}, {"bottom": 3837.5}, {"left": math.inf}, {"right": 1_000_000}):
            self.catalog["era"]["1420"] = {**TIRISFAL, **patch}
            with self.subTest(patch=patch):
                self.assertEqual(normalize_location({"map": 1420, "x": 50, "y": 50, "f": "e"}, self.catalog)["status"], "invalid_frame_bounds")

    def test_integer_lua_catalog_keys_and_instance_world_map_id(self):
        cat = {"era": {1459: {"c": 30, "left": 10, "right": -10, "top": 20, "bottom": -20}}}
        got = normalize_location({"map": 1459, "x": 50, "y": 50, "f": "e"}, cat)
        self.assertEqual(got["world_map_id"], 30)
        self.assertEqual(got["world_xy"], {"x": 0.0, "y": 0.0})


class CatalogTests(unittest.TestCase):
    def test_safe_literal_extract_merge_and_source_hashes(self):
        with tempfile.TemporaryDirectory() as directory:
            a, b = (Path(directory) / name for name in ("a.lua", "b.lua"))
            a.write_text('Polestar.RegisterMapFrames({era={[1420]={c=0,left=10,right=-10,top=20,bottom=-20}}}, "guides")', encoding="utf-8")
            b.write_text('Polestar.RegisterMapFrames({era={[1420]={c=0,left=10,right=-10,top=20,bottom=-20}}})', encoding="utf-8")
            cat = build_frame_catalog([a, b], addon_version="fixture")
            self.assertEqual(len(cat["era"]), 1)
            self.assertEqual(len(cat["provenance"]["frame_sources"]["era/1420"]), 2)
            self.assertEqual(len(cat["provenance"]["sources"][0]["sha256"]), 64)
            self.assertEqual(cat["live"], {})

    def test_conflicting_catalog_fails_instead_of_guessing_load_order(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = [Path(directory) / name for name in ("a.lua", "b.lua")]
            for path, top in zip(paths, (20, 21)):
                path.write_text('Polestar.RegisterMapFrames({era={[1420]={c=0,left=10,right=-10,top=%s,bottom=-20}}})' % top, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Conflicting"):
                build_frame_catalog(paths)


if __name__ == "__main__":
    unittest.main()
