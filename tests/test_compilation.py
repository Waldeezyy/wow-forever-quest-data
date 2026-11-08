"""End-to-end data compilation against the pinned upstream Tirisfal snapshot."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'sources' / 'polestar-0.3.4'


class CompilationTests(unittest.TestCase):
    def compile(self, out, override=None, source=None, frames=None, manifest=None):
        args = [sys.executable, str(ROOT / 'compile_polestar.py'),
                '--source', str(source or SOURCE / 'tirisfal.lua'),
                '--manifest', str(manifest or SOURCE / 'manifest.json'),
                '--frames', str(frames or SOURCE / 'map-frames.json'), '--out', str(out)]
        if override:
            args += ['--overrides', str(override)]
        return subprocess.run(args, cwd=ROOT, capture_output=True, text=True)

    def test_pinned_route_rebuild_is_deterministic_and_preserves_frames(self):
        with tempfile.TemporaryDirectory() as folder:
            first, second = Path(folder) / 'a', Path(folder) / 'b'
            for out in (first, second):
                result = self.compile(out)
                self.assertEqual(result.returncode, 0, result.stderr)
            for filename in ('route.source.json', 'route.json', 'quest-index.json', 'report.json'):
                self.assertEqual((first / filename).read_bytes(), (second / filename).read_bytes())
            route = json.loads((first / 'route.json').read_text(encoding='utf-8'))
            report = json.loads((first / 'report.json').read_text(encoding='utf-8'))
            self.assertEqual(report['compiled_stats']['steps'], 66)
            self.assertEqual(report['compiled_stats']['goals'], 247)
            self.assertEqual(report['compiled_stats']['quests'], 79)
            self.assertEqual(report['compiled_stats']['spawn_areas'], 697)
            self.assertEqual(report['validation']['errors'], 0)
            goals = [g for s in route['steps'] for g in s['goals']]
            first_accept = next(g for g in goals if g['kind'] == 'accept')
            self.assertEqual(first_accept['quest_id'], 363)
            self.assertEqual(first_accept['location']['ui_map_id'], 1420)
            self.assertEqual(first_accept['location']['status'], 'resolved_era_reference')
            self.assertEqual(first_accept['location']['coordinate_system'], 'percent')
            self.assertIsNone(first_accept['location']['live_world_xy'])
            self.assertTrue(any(g['raw'].get('candidates') for g in goals))

    def test_excluded_dependencies_are_visible_in_top_level_validation(self):
        with tempfile.TemporaryDirectory() as folder:
            out, config = Path(folder) / 'out', Path(folder) / 'overrides.json'
            config.write_text(json.dumps({'exclude_quest_ids': [364]}), encoding='utf-8')
            result = self.compile(out, config)
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads((out / 'report.json').read_text(encoding='utf-8'))
            dependencies = report['overrides']['dependent_warnings']
            self.assertTrue(dependencies)
            self.assertTrue(all(issue in report['validation']['issues'] for issue in dependencies))

    def test_real_escort_exclusion_removes_all_its_goals_only(self):
        with tempfile.TemporaryDirectory() as folder:
            out, config = Path(folder) / 'out', Path(folder) / 'overrides.json'
            config.write_text(json.dumps({'exclude_quest_ids': [99144]}), encoding='utf-8')
            result = self.compile(out, config)
            self.assertEqual(result.returncode, 0, result.stderr)
            original = json.loads((out / 'route.source.json').read_text(encoding='utf-8'))
            filtered = json.loads((out / 'route.json').read_text(encoding='utf-8'))
            expected = [g['raw'] for s in original['steps'] for g in s['goals'] if g['quest_id'] != 99144]
            actual = [g['raw'] for s in filtered['steps'] for g in s['goals']]
            self.assertEqual(actual, expected)
            self.assertEqual(len(filtered['steps']), len(original['steps']))
            self.assertTrue(any(g['quest_id'] == 99144 for s in original['steps'] for g in s['goals']))
            self.assertFalse(any(g['quest_id'] == 99144 for s in filtered['steps'] for g in s['goals']))

    def test_source_hash_mismatch_rejected_before_outputs(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'changed.lua'
            source.write_bytes((SOURCE / 'tirisfal.lua').read_bytes() + b'\n-- changed\n')
            out = Path(folder) / 'out'
            result = self.compile(out, source=source)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('hash differs', result.stderr)
            self.assertFalse(out.exists())

    def test_documented_replacement_inserts_authored_data_at_original_anchor(self):
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder) / 'out'
            result = self.compile(out, ROOT / 'examples' / 'replacement.demo.json')
            self.assertEqual(result.returncode, 0, result.stderr)
            route = json.loads((out / 'route.json').read_text(encoding='utf-8'))
            original = json.loads((out / 'route.source.json').read_text(encoding='utf-8'))
            report = json.loads((out / 'report.json').read_text(encoding='utf-8'))
            self.assertEqual(len(route['steps']), len(original['steps']) + 1)
            inserted = route['steps'][1]
            self.assertEqual(inserted['replacement_id'], 'demo-replace-escort-with-fake-quest')
            self.assertEqual(inserted['source_step_index'], 10001)
            self.assertEqual(inserted['goals'][0]['quest_id'], 999001)
            self.assertEqual(route['steps'][2]['source_step_index'], 2)
            self.assertEqual([s['index'] for s in route['steps']], list(range(1, 68)))
            self.assertFalse(any(g['quest_id'] == 99144 for s in route['steps'] for g in s['goals']))
            self.assertTrue(any(g['quest_id'] == 99144 for s in original['steps'] for g in s['goals']))
            self.assertEqual(report['overrides']['replacement_goals_added'], 1)
            self.assertEqual(report['overrides']['inserted_steps'][0]['display_index'], 2)
            self.assertEqual(report['validation']['errors'], 0)
            index = json.loads((out / 'quest-index.json').read_text(encoding='utf-8'))
            row = next(q for q in index if q['quest_id'] == 999001)
            self.assertEqual(row['occurrences'][0]['replacement_id'], inserted['replacement_id'])

    def test_unknown_replacement_anchor_fails_before_outputs(self):
        with tempfile.TemporaryDirectory() as folder:
            config = json.loads((ROOT / 'examples' / 'replacement.demo.json').read_text(encoding='utf-8'))
            config['replacements'][0]['after_source_step'] = 999999
            override = Path(folder) / 'bad.json'
            override.write_text(json.dumps(config), encoding='utf-8')
            out = Path(folder) / 'out'
            result = self.compile(out, override)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('not an original source anchor', result.stderr)
            self.assertFalse(out.exists())

    def test_frame_hash_mismatch_rejected_before_outputs(self):
        with tempfile.TemporaryDirectory() as folder:
            frames = Path(folder) / 'frames.json'
            frames.write_bytes((SOURCE / 'map-frames.json').read_bytes() + b'\n')
            out = Path(folder) / 'out'
            result = self.compile(out, frames=frames)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('frames hash differs', result.stderr)
            self.assertFalse(out.exists())

    def test_pinned_manifest_requires_hashes_and_matching_guide_identity(self):
        for field, value, message in (
                ('bundled_guide_sha256', None, 'requires a bundled_guide_sha256'),
                ('bundled_frames_sha256', None, 'requires a bundled_frames_sha256'),
                ('source_guide_id', 'wrong-guide', 'guide identity differs'),
                ('guide_source_marker', 'wrong-guide.guide', 'guide identity differs')):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as folder:
                manifest = json.loads((SOURCE / 'manifest.json').read_text(encoding='utf-8'))
                manifest[field] = value
                path = Path(folder) / 'manifest.json'
                path.write_text(json.dumps(manifest), encoding='utf-8')
                out = Path(folder) / 'out'
                result = self.compile(out, manifest=path)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(message, result.stderr)
                self.assertFalse(out.exists())

    def test_replacement_warnings_use_final_guide_dependency_context(self):
        with tempfile.TemporaryDirectory() as folder:
            config = json.loads((ROOT / 'examples' / 'replacement.demo.json').read_text(encoding='utf-8'))
            config['replacements'][0]['steps'][0]['goals'][0]['prerequisites'] = {'any': [363], 'all': []}
            override = Path(folder) / 'override.json'
            override.write_text(json.dumps(config), encoding='utf-8')
            out = Path(folder) / 'out'
            result = self.compile(out, override)
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads((out / 'report.json').read_text(encoding='utf-8'))
            def refers_to_retained_quest(issue):
                return (issue['code'] == 'external_prerequisite_unverified' and
                        issue.get('details', {}).get('quest_id') == 363)
            self.assertTrue(any(refers_to_retained_quest(i) for i in report['overrides']['issues']))
            self.assertFalse(any(refers_to_retained_quest(i) for i in report['validation']['issues']))


if __name__ == '__main__':
    unittest.main()
