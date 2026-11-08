"""Offline synthetic fixtures for the restricted DATA parser. No Lua runtime."""
import unittest

from lua_data import (LuaDataError, collect_table_bindings, extract_guide_block,
                      iter_calls, parse_value)


class LiteralTests(unittest.TestCase):
    def value(self, text, **kwargs):
        value, end = parse_value(text, **kwargs)
        self.assertEqual(text[end:].strip(), "")
        return value

    def test_scalar_literals(self):
        for source, expected in [("true", True), ("false", False), ("nil", None),
                                 ("42", 42), ("-3", -3), (".25", 0.25),
                                 ("1.5e-2", 0.015), ("-2E+3", -2000),
                                 ("0x10", 16), ("0x1.8p1", 3.0)]:
            with self.subTest(source=source):
                self.assertEqual(self.value(source), expected)

    def test_string_escapes_unicode_and_long_brackets(self):
        self.assertEqual(self.value(r'''"a\n\t\"\\z"'''), 'a\n\t"\\z')
        self.assertEqual(self.value(r'"caf\195\169"'), "café")
        self.assertEqual(self.value(r'"\x41\065"'), "AA")
        self.assertEqual(self.value('"é"'), "é")
        self.assertEqual(self.value('[==[\r\nnot ]] the end\r\n]==]'), 'not ]] the end\n')
        self.assertEqual(self.value('"a\\\nb"'), 'a\nb')
        self.assertEqual(self.value('"a\\z \r\n\t b"'), 'ab')

    def test_list_and_object_and_mixed_table_fidelity(self):
        self.assertEqual(self.value('{1, "x", true, nil,}'), [1, "x", True, None])
        self.assertEqual(self.value('{a=1; ["b"]={2,3}}'), {"a": 1, "b": [2, 3]})
        self.assertEqual(self.value('{[2]="explicit", "one", name="value", "two"}'),
                         {2: "two", 1: "one", "name": "value"})
        self.assertEqual(self.value('{[1]="explicit"}'), {1: "explicit"})
        self.assertEqual(self.value('{}'), {})
        self.assertEqual(self.value('{x=1,x=2}'), {"x": 2})

    def test_comments_separators_and_end_offset(self):
        text = 'prefix -- line\n --[==[ ignored } ]==]\n {x=1,--comment\r y=2}; suffix'
        value, end = parse_value(text, len('prefix'))
        self.assertEqual(value, {"x": 1, "y": 2})
        self.assertEqual(text[end:], '; suffix')
        self.assertEqual(self.value('\ufeff { --empty\n }'), {})

    def test_errors_report_offsets_and_do_not_guess(self):
        invalid = ['1 + 2', 'true and false', '{x=run()}', '{x=1..2}',
                   '{1 2}', '{[true]=1}', '{[nil]=1}', 'not true',
                   'function() end', '{x=os.execute("anything")}',
                   'setmetatable({}, {})', '{x=...}', '1e999', '123abc',
                   '"\\999"', '"\\q"', '"unterminated', '[=[missing', '{']
        for source in invalid:
            with self.subTest(source=source):
                with self.assertRaises(LuaDataError) as error:
                    parse_value(source)
                self.assertIn('offset', str(error.exception))
                self.assertGreaterEqual(error.exception.line, 1)

    def test_depth_limit(self):
        with self.assertRaises(LuaDataError):
            parse_value('{' * 140 + '1' + '}' * 140)


class ReferenceTests(unittest.TestCase):
    def test_parsed_data_references_use_lua_one_based_index(self):
        env = {"records": [{"npc": 1}, {"npc": 2}], "metadata": {"label": "name"},
               "ADDON": "Polestar_Guides"}
        value, _ = parse_value('{one=records[1],two=records[2]["npc"],label=metadata.label,addon=ADDON}', env=env)
        self.assertEqual(value, {"one": {"npc": 1}, "two": 2, "label": "name", "addon": "Polestar_Guides"})
        self.assertEqual(parse_value('records[1].npc', names=env)[0], 1)

    def test_unknown_and_dynamic_reference_rejected(self):
        env = {"records": [1, 2], "key": 1, "fn": lambda: self.fail('must not execute')}
        for source in ['missing', 'records[0]', 'records[3]', 'records[key]',
                       'records[1+1]', 'records()', 'records:method()', 'fn',
                       'fn()', 'records[1]["x"]']:
            with self.subTest(source=source), self.assertRaises(LuaDataError):
                parse_value(source, env=env)

    def test_local_tables_resolved_in_order(self):
        source = '''
        do
          local function register()
            local candidateRecords = {{npc=10}, {npc=20}}
            local candidateLists = {{candidateRecords[2], candidateRecords[1]}}
            Polestar.RegisterGuide({id="fixture",steps={{goals={{t="train",candidates=candidateLists[1]}}}}})
          end
          register()
        end
        '''
        env = collect_table_bindings(source)
        self.assertEqual(env['candidateLists'][0][0]['npc'], 20)
        guide, offset = extract_guide_block(source)
        self.assertEqual(source[offset:offset + len('Polestar.RegisterGuide')], 'Polestar.RegisterGuide')
        self.assertEqual(guide['steps'][0]['goals'][0]['candidates'], [{"npc": 20}, {"npc": 10}])

    def test_no_non_table_local_execution(self):
        source = 'local ignored = dangerous()\nlocal data = {x=1}\nPolestar.RegisterGuide({id="ok",v=data})'
        guide, _ = extract_guide_block(source)
        self.assertEqual(guide['v'], {"x": 1})
        self.assertNotIn('ignored', collect_table_bindings(source))


class CallExtractionTests(unittest.TestCase):
    def test_strings_comments_and_definitions_are_not_calls(self):
        source = '''
          -- Polestar.RegisterGuide({id="comment"})
          local x = "Polestar.RegisterGuide({id='string'})"
          local y = [==[Polestar.RegisterGuide({id="long string"})]==]
          --[=[ Polestar.RegisterGuide({id="long comment"}) ]=]
          function Polestar.RegisterGuide(def) unrelated() end
          other.Polestar.RegisterGuide({id="different callee"})
          Polestar -- comment between callee tokens
            .RegisterGuide({id="actual", literal=") end }"})
        '''
        calls = iter_calls(source, 'Polestar.RegisterGuide')
        self.assertEqual([v['id'] for v, _ in calls], ['actual'])

    def test_first_argument_and_optional_all_arguments(self):
        source = 'Polestar.RegisterMapFrames({era={[1420]={c=0,left=1}}}, "guides")'
        calls = iter_calls(source, 'Polestar.RegisterMapFrames')
        self.assertEqual(calls[0][0]['era'][1420]['c'], 0)
        all_arguments = iter_calls(source, 'Polestar.RegisterMapFrames', all_args=True)[0][0]
        self.assertEqual(all_arguments[1], 'guides')

    def test_pack_env_and_multiple_call_offsets(self):
        source = 'Polestar.RegisterPack({addon=ADDON,id="one"});\nPolestar.RegisterPack({id="two"})'
        calls = iter_calls(source, 'Polestar.RegisterPack', env={"ADDON": "Polestar_Guides"})
        self.assertEqual(calls[0][0]['addon'], 'Polestar_Guides')
        self.assertEqual(source[calls[1][1]:], 'Polestar.RegisterPack({id="two"})')

    def test_unsupported_direct_call_arguments_fail(self):
        for source in ['Polestar.RegisterGuide(makeGuide())',
                       'Polestar.RegisterGuide({id="x"}, run())',
                       'Polestar.RegisterGuide({id="x"} .. suffix)',
                       'Polestar.RegisterGuide()', 'Polestar.RegisterGuide({id="x"},)']:
            with self.subTest(source=source), self.assertRaises(LuaDataError):
                iter_calls(source, 'Polestar.RegisterGuide')

    def test_deferred_steps_are_data_not_code(self):
        guide, _ = extract_guide_block('Polestar.RegisterGuide({id="x",stepsSrc=[=[{{goals={{t="wait",seconds=1}}}}]=]})')
        self.assertIsInstance(guide['stepsSrc'], str)
        steps, end = parse_value(guide['stepsSrc'])
        self.assertEqual(end, len(guide['stepsSrc']))
        self.assertEqual(steps[0]['goals'][0]['seconds'], 1)
        with self.assertRaises(LuaDataError):
            parse_value('return {run()}')


if __name__ == '__main__':
    unittest.main()
