import os
import unittest

import optimize as o

HAVE_TOOL = os.path.exists(o.TOOL)


class ArtifactTest(unittest.TestCase):
    def test_restore(self):
        src = ('local function f()\n'
               '\tlocal _ = floor(v % 1 * 4294967296) + floor(v)\n'
               '\tbuf = _G["table.create"](4)\n'
               'end\n'
               'x = _G["table.create"](3)\n'
               '_G["bit32.bxor"](1, 2)\n'
               'up3;(a .. b)\n'
               'f()\n;(nil)()\n'
               's = "_G[\\"table.create\\"]"\n')
        report = {}
        out = o.restore_artifacts(src, report)
        self.assertIn('\tlocal rnd = floor(v % 1 * 4294967296) + floor(v)\n', out)
        self.assertIn('\tbuf = { lo % 256, (lo - lo % 256) / 256, hi % 256, '
                      '(hi - hi % 256) / 256 }', out)
        self.assertIn('x = table.create(3)', out)
        self.assertIn('bit32.bxor(1, 2)', out)
        self.assertIn('up3(a .. b)', out)
        self.assertIn(';(nil)()', out)
        self.assertIn('s = "_G[\\"table.create\\"]"', out)
        # line numbers refer to the output, where the keystream fix added 2 lines
        self.assertEqual(report['artifacts']['table.create'], [7])


class HelperTest(unittest.TestCase):
    def test_lower_camel(self):
        self.assertEqual(o.lower_camel('UICorner'), 'uiCorner')
        self.assertEqual(o.lower_camel('Character'), 'character')
        self.assertEqual(o.lower_camel('HumanoidRootPart'), 'humanoidRootPart')
        self.assertEqual(o.lower_camel('_menu'), '_menu')

    def test_classify(self):
        self.assertEqual(o.classify('return -nil'), 'trap')
        self.assertEqual(o.classify('(nil).c = nil'), 'trap')
        self.assertEqual(o.classify('break'), 'control flow only')
        self.assertEqual(o.classify('t154 = {}'), 'looks live')


@unittest.skipUnless(HAVE_TOOL, 'luau-tool not built')
class ToolTest(unittest.TestCase):
    def test_resolve_scopes(self):
        src = ('local x = 1\nlocal x = x + 1\n'
               'for i = i, 2 do print(i) end\n'
               'repeat local y = 1 until y\nprint(y, {x = x}, a.x)\n')
        names = [(n[2], n[3], n[4]) for n in o.run_tool('resolve', src)['names']]
        self.assertEqual(names[:3], [('x', 0, 1), ('x', 1, 1), ('x', 0, 0)])
        self.assertIn(('i', -1, 0), names)
        y = [n for n in names if n[0] == 'y']
        self.assertEqual([n[1] for n in y], [3, 3, -1])

    def test_predicates(self):
        src = ('local function a()\n\tlocal v1\n\tv1 = not not false\n'
               '\tif v1 then\n\t\treturn -nil\n\tend\n'
               '\trepeat\n\t\tv1 = not not true\n\tuntil v1 and 467\n'
               '\trepeat\n\t\tv1 = not not false\n\tuntil v1\nend\n')
        report = {}
        o.report_predicates(src, report)
        sites = report['opaque_predicates']
        self.assertEqual(sites[0]['literal_reading'], 'condition always false')
        self.assertEqual(sites[0]['dead_lines'], [4, 6])
        self.assertEqual(sites[0]['dead_code'], 'trap')
        self.assertEqual([x['literal_reading'] for x in sites[1:]], ['runs once', 'infinite loop'])

    def rename(self, src, skip=()):
        report = {}
        out = o.auto_rename(src, report, list(skip))
        return out, report['renames']

    def test_rename_rules(self):
        src = ('local function f1(p1)\n'
               '\tlocal v1 = Instance.new("UICorner")\n'
               '\tlocal v2 = p1.Character\n'
               '\tlocal v3 = p1.Humanoid\n'
               '\tv3 = nil\n'
               '\tlocal t1 = { Title = "Auto Queue", Side = "left" }\n'
               '\tlocal t2 = AddSection(p1, t1)\n'
               '\tlocal function f2() end\n'
               '\tgame.RunService.RenderStepped:Connect(f2)\n'
               '\tlocal function f3() end\n'
               '\tp1.Update = f3\n'
               '\treturn v1, v2, t2\n'
               'end\n')
        out, renames = self.rename(src)
        self.assertIn('local uiCorner = Instance.new("UICorner")', out)
        self.assertIn('local character = p1.Character', out)
        self.assertIn('local v3 = p1.Humanoid', out)  # reassigned: kept
        self.assertIn('local autoQueueSection = AddSection(p1, t1)', out)
        self.assertIn(':Connect(onRenderStepped)', out)
        self.assertIn('p1.Update = Update', out)
        self.assertIn('return uiCorner, character, autoQueueSection', out)

    def test_ui_elements(self):
        src = ('local function f1(p1)\n'
               '\tlocal t1 = {\n\t\tLabel = "Auto Save Config",\n\t\tOptions = { "a" },\n\t}\n'
               '\tlocal v1 = AddDropdown4(p1, t1)\n'
               '\tlocal t2 = { Label = "Import", Confirm = true }\n'
               '\tfunction t2.OnClick() end\n'
               '\tAddButton8(p1, t2)\n'
               '\tlocal t3 = { Label = "Twice" }\n'
               '\tAddButton(p1, t3)\n\tAddButton(p1, t3)\n'
               '\treturn v1\n'
               'end\n')
        out, _ = self.rename(src)
        self.assertIn('local autoSaveConfigDropdownOptions = {', out)
        self.assertIn('local autoSaveConfigDropdown = AddDropdown4(p1, autoSaveConfigDropdownOptions)', out)
        self.assertIn('function importButtonOptions.OnClick() end', out)
        self.assertIn('local t3 = { Label = "Twice" }', out)  # used twice: ambiguous

    def test_ui_rows_and_groups(self):
        src = ('local function f1(p1)\n'
               '\tlocal v1 = p1.AddToggle\n'
               '\tlocal t1 = { Label = "FOV Circle" }\n'
               '\tlocal v2 = v1(p1, t1)\n'
               '\tlocal t2 = { Label = "Color Mode" }\n'
               '\tlocal v3 = AddLabel9(p1, t2)\n'
               '\tlocal t3 = { Row = v3.Row, Options = {} }\n'
               '\tlocal v4 = AddDropdown(p1, t3)\n'
               '\tlocal t4 = { Source = v4, Option = "Solid" }\n'
               '\tlocal v5 = AddGroup(p1, t4)\n'
               '\tlocal t5 = { Source = v2 }\n'
               '\tlocal v6 = AddGroup(p1, t5)\n'
               '\treturn v5, v6\n'
               'end\n')
        out, _ = self.rename(src)
        self.assertIn('local fovCircleToggle = addToggle(p1, fovCircleToggleOptions)', out)
        self.assertIn('local colorModeDropdown = AddDropdown(p1, colorModeDropdownOptions)', out)
        self.assertIn('local solidGroup = AddGroup(p1, solidGroupOptions)', out)
        self.assertIn('local fovCircleGroup = AddGroup(p1, fovCircleGroupOptions)', out)

    def test_rename_avoids_capture(self):
        src = ('local function f1(p1)\n'
               '\tlocal v1 = p1.Character\n'
               '\tlocal v2 = p1.Model.Character\n'
               '\tprint(character, v1, v2)\n'
               'end\n')
        out, _ = self.rename(src)
        self.assertIn('print(character, character2, character3)', out)

    def test_manual_names(self):
        src = ('local function f1()\n'
               '\tlocal function f2(p1)\n'
               '\t\tlocal v1 = up0.Players\n'
               '\t\treturn up0, p1, v1\n'
               '\tend\n'
               '\treturn f2\n'
               'end\n')
        report = {}
        out = o.auto_rename(src, report, [], {'f1': {'f2': 'getPlayers'},
                                              'f2': {'p1': 'player', 'up0': 'game_', 'v1': 'players'}})
        self.assertIn('local function getPlayers(player)', out)
        self.assertIn('local players = game_.Players', out)
        self.assertIn('return game_, player, players', out)
        self.assertIn('return getPlayers', out)

    def test_manual_upvalue_is_per_prototype(self):
        src = ('local function f1()\n'
               '\tlocal x = up0.a\n'
               '\tlocal function f2() return up0.b end\n'
               '\treturn x, f2\n'
               'end\n')
        out = o.auto_rename(src, {}, [], {'f1': {'up0': 'outerThing'}})
        self.assertIn('local x = outerThing.a', out)
        self.assertIn('return up0.b', out)

    def test_manual_errors(self):
        src = 'local function f1(p1)\n\tlocal v1 = 1\n\treturn p1, v1\nend\n'
        for table in ({'f1': {'v1': 'p1'}}, {'f1': {'v9': 'x'}}, {'f9': {'v1': 'x'}},
                      {'f1': {'v1': 'end'}}):
            with self.assertRaises(SystemExit):
                o.auto_rename(src, {}, [], table)

    def test_rename_skips_ranges(self):
        src = 'local function f1(p1)\n\tlocal v1 = p1.Character\n\treturn v1\nend\n'
        out, renames = self.rename(src, skip=[(1, 4)])
        self.assertEqual(out, src)
        self.assertEqual(renames, [])


if __name__ == '__main__':
    unittest.main()
