"""Compile Polestar guide DATA to JSON. Never executes Lua or controls a game."""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re

from coordinates import normalize_location
from lua_data import extract_guide_block, iter_calls
from validate_routes import apply_overrides, validate_guide

DEFAULT_GUIDE = 'forever/horde/undead/01-tirisfal-glades'
CONDITION_KEYS = ('only', 'when', 'optional', 'along', 'skipto', 'closedBy',
                  'minLevel', 'lvl', 'qlvl', 'group', 'escort')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n',
                    encoding='utf-8', newline='\n')


def array(value):
    if value == {} or value is None:
        return []
    if not isinstance(value, list):
        raise ValueError('Expected a positional Lua table, not ' + type(value).__name__)
    return value


def source_block(text, guide_id):
    markers = list(re.finditer(r'^-- Source: ([^\r\n]+)', text, re.M))
    for index, marker in enumerate(markers):
        if marker.group(1).strip().removesuffix('.guide') == guide_id:
            end = markers[index + 1].start() if index + 1 < len(markers) else len(text)
            return text[marker.start():end], text[:marker.start()].count('\n') + 1
    raise ValueError('Guide source marker not found: ' + guide_id)


def location(raw, frames):
    result = normalize_location(raw, frames)
    # Explicit source units for consumers/validation; no live conversion implied.
    result['coordinate_system'] = 'percent'
    result['x'] = raw.get('x')
    result['y'] = raw.get('y')
    result['z'] = raw.get('z')
    return result


def prerequisites(raw):
    if 'pre' not in raw and 'preAll' not in raw:
        return None
    def supplied(key):
        if key not in raw:
            return None
        return [] if raw[key] == {} else deepcopy(raw[key])
    return {'any': supplied('pre'), 'all': supplied('preAll')}


def spawn_areas(raw, frames):
    packed = raw.get('spotsPacked')
    if not isinstance(packed, str) or not packed:
        return []
    result = []
    keys = ('x', 'y', 'z', 'r', 'n', 'alt', 'lvl')
    for index, entry in enumerate(packed.split(';'), 1):
        cells = entry.split(',')
        if len(cells) > len(keys):
            raise ValueError('Unsupported spotsPacked field count: ' + entry)
        values = {}
        for key, cell in zip(keys, cells):
            if cell.strip():
                number = float(cell)
                values[key] = int(number) if number.is_integer() else number
        source = {key: raw[key] for key in ('map', 'f') if key in raw}
        source.update({key: value for key, value in values.items() if key in ('x', 'y', 'z', 'r')})
        result.append({'index': index, 'raw': entry, 'source_fields': values,
                       'location': location(source, frames)})
    return result


def normalize_guide(raw, source, frames):
    guide = {'schema_version': 1, 'id': raw['id'], 'source': source,
             'metadata': {key: deepcopy(value) for key, value in raw.items()
                          if key not in ('steps', 'stepsSrc')}, 'steps': []}
    if 'stepsSrc' in raw and 'steps' not in raw:
        raise ValueError('stepsSrc needs an explicit data-only decoder; it will not be executed.')
    for step_index, step in enumerate(array(raw.get('steps')), 1):
        record = {'index': step_index, 'source_step_index': step_index,
                  'title': step.get('title'), 'note': step.get('note'),
                  'conditions': {key: deepcopy(step[key]) for key in CONDITION_KEYS if key in step},
                  'raw': {key: deepcopy(value) for key, value in step.items() if key != 'goals'},
                  'goals': []}
        for goal_index, goal in enumerate(array(step.get('goals')), 1):
            entry = {'index': goal_index, 'source_goal_index': goal_index,
                     'kind': goal.get('t'), 'quest_id': goal.get('quest'),
                     'objective_index': goal.get('oi'), 'npc_id': goal.get('npc'),
                     'object_id': goal.get('object'), 'item_id': goal.get('item'),
                     'count': goal.get('count'), 'title': goal.get('title'),
                     'prerequisites': prerequisites(goal),
                     'conditions': {key: deepcopy(goal[key]) for key in CONDITION_KEYS if key in goal},
                     'location': location(goal, frames),
                     'spawn_areas': spawn_areas(goal, frames), 'raw': deepcopy(goal)}
            record['goals'].append(entry)
        guide['steps'].append(record)
    return guide


def quest_index(guide):
    index = {}
    for step in guide['steps']:
        for goal in step['goals']:
            qid = goal.get('quest_id')
            if not isinstance(qid, int) or isinstance(qid, bool):
                continue
            row = index.setdefault(qid, {'quest_id': qid, 'titles': [], 'occurrences': []})
            title = goal.get('title')
            if title and title not in row['titles']:
                row['titles'].append(title)
            row['occurrences'].append({'step_index': step['index'], 'goal_index': goal['index'],
                'source_step_index': step.get('source_step_index'),
                'source_goal_index': goal.get('source_goal_index'), 'kind': goal['kind'],
                'replacement_id': step.get('replacement_id'),
                'conditions': deepcopy(goal['conditions']),
                'prerequisites': deepcopy(goal.get('prerequisites'))})
    return [index[key] for key in sorted(index)]


def statistics(guide):
    goals = [goal for step in guide['steps'] for goal in step['goals']]
    return {'steps': len(guide['steps']), 'goals': len(goals),
            'quests': len({g['quest_id'] for g in goals if isinstance(g.get('quest_id'), int)}),
            'goal_kinds': dict(sorted(Counter(g['kind'] for g in goals).items())),
            'location_statuses': dict(sorted(Counter(g.get('location', {}).get('status', 'unknown') for g in goals).items())),
            'spawn_areas': sum(len(g.get('spawn_areas', [])) for g in goals),
            'goals_with_character_or_flow_conditions': sum(bool(g.get('conditions')) for g in goals)}


def input_from_addons(addons, guide_id, snapshot):
    file = addons / 'Polestar_Guides_Horde' / 'Guides.lua'
    original = file.read_bytes()
    selected, start_line = source_block(original.decode('utf-8-sig'), guide_id)
    pack_path = addons / 'Polestar_Guides' / 'Pack.lua'
    pack, _ = next(iter(iter_calls(pack_path.read_text(encoding='utf-8-sig'),
                                  'Polestar.RegisterPack', env={'ADDON': 'Polestar_Guides'})))
    frame_path = addons / 'Polestar_Guides' / 'MapFrames.lua'
    frame_bytes = frame_path.read_bytes()
    frames, _ = next(iter(iter_calls(frame_bytes.decode('utf-8-sig'), 'Polestar.RegisterMapFrames')))
    manifest = {'provider': 'Polestar', 'version': pack.get('version'),
                'pack_format': pack.get('format'), 'license': pack.get('license'),
                'source_guide_id': guide_id, 'guide_source_marker': guide_id + '.guide',
                'original_file': 'Polestar_Guides_Horde/Guides.lua',
                'original_file_sha256': digest(original), 'source_line_start': start_line,
                'upstream_repository': 'https://github.com/fitzforge/polestar',
                'upstream_build_commit': None,
                'frame_source_file': 'Polestar_Guides/MapFrames.lua',
                'frame_source_sha256': digest(frame_bytes)}
    if snapshot:
        snapshot.mkdir(parents=True, exist_ok=True)
        selected = selected.replace('\r\n', '\n').rstrip('\n') + '\n'
        (snapshot / 'tirisfal.lua').write_text(selected, encoding='utf-8', newline='\n')
        # Canonical JSON is the raw registered frame data, not a live API export.
        write_json(snapshot / 'map-frames.json', frames)
        manifest['bundled_guide_sha256'] = digest((snapshot / 'tirisfal.lua').read_bytes())
        manifest['bundled_frames_sha256'] = digest((snapshot / 'map-frames.json').read_bytes())
        write_json(snapshot / 'manifest.json', manifest)
    return selected, manifest, frames


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--addons', type=Path, help='Installed AddOns directory (read-only)')
    mode.add_argument('--source', type=Path, help='Bundled single-guide Lua source snapshot')
    parser.add_argument('--manifest', type=Path)
    parser.add_argument('--frames', type=Path, help='Bundled registered map-frame JSON')
    parser.add_argument('--guide', default=DEFAULT_GUIDE)
    parser.add_argument('--snapshot-source', type=Path)
    parser.add_argument('--overrides', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(argv)
    if args.addons:
        selected, manifest, frames = input_from_addons(args.addons, args.guide, args.snapshot_source)
    else:
        if not args.manifest or not args.frames:
            parser.error('--source requires --manifest and --frames')
        payload = args.source.read_bytes()
        selected = payload.decode('utf-8-sig')
        manifest = json.loads(args.manifest.read_text(encoding='utf-8'))
        frame_payload = args.frames.read_bytes()
        frames = json.loads(frame_payload.decode('utf-8'))
        expected = manifest.get('bundled_guide_sha256')
        if not isinstance(expected, str) or not re.fullmatch(r'[0-9a-f]{64}', expected):
            raise ValueError('Pinned source manifest requires a bundled_guide_sha256 hash.')
        if digest(payload) != expected:
            raise ValueError('Bundled guide hash differs from its manifest; update provenance explicitly.')
        expected_frames = manifest.get('bundled_frames_sha256')
        if not isinstance(expected_frames, str) or not re.fullmatch(r'[0-9a-f]{64}', expected_frames):
            raise ValueError('Pinned source manifest requires a bundled_frames_sha256 hash.')
        if digest(frame_payload) != expected_frames:
            raise ValueError('Bundled frames hash differs from its manifest; update provenance explicitly.')
        if (manifest.get('source_guide_id') != args.guide or
                manifest.get('guide_source_marker') != args.guide + '.guide'):
            raise ValueError('Pinned source manifest guide identity differs from --guide.')
    raw, offset = extract_guide_block(selected)
    if raw.get('id') != args.guide:
        raise ValueError('Selected guide ID does not match --guide')
    source = deepcopy(manifest)
    source['register_call_line'] = manifest.get('source_line_start', 1) + selected[:offset].count('\n')
    guide = normalize_guide(raw, source, frames)
    overrides = json.loads(args.overrides.read_text(encoding='utf-8')) if args.overrides else {}
    filtered, override_report = apply_overrides(guide, overrides)
    issues = validate_guide(filtered)
    # Pre-insertion diagnostics use replacement-local paths/context. Keep them in
    # the override report; the final guide is validated once in its full context.
    issues.extend(override_report.get('dependent_warnings', []))
    report = {'schema_version': 1, 'guide_id': guide['id'], 'source': source,
              'source_stats': statistics(guide), 'compiled_stats': statistics(filtered),
              'validation': {'errors': sum(i['severity'] == 'error' for i in issues),
                             'warnings': sum(i['severity'] == 'warning' for i in issues),
                             'issues': issues}, 'overrides': override_report,
              'execution_validation': 'not performed; this repository compiles data only'}
    for filename, value in (('route.source.json', guide), ('route.json', filtered),
                            ('quest-index.json', quest_index(filtered)), ('report.json', report)):
        write_json(args.out / filename, value)
    print(json.dumps({'guide_id': guide['id'], 'output': str(args.out),
                      **report['compiled_stats'], 'errors': report['validation']['errors'],
                      'warnings': report['validation']['warnings']}))
    return int(report['validation']['errors'] > 0)


if __name__ == '__main__':
    raise SystemExit(main())
