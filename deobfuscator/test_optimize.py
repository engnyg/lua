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

    def test_rename_avoids_capture(self):
        src = ('local function f1(p1)\n'
               '\tlocal v1 = p1.Character\n'
               '\tlocal v2 = p1.Model.Character\n'
               '\tprint(character, v1, v2)\n'
               'end\n')
        out, _ = self.rename(src)
        self.assertIn('print(character, character2, character3)', out)

    def test_rename_skips_ranges(self):
        src = 'local function f1(p1)\n\tlocal v1 = p1.Character\n\treturn v1\nend\n'
        out, renames = self.rename(src, skip=[(1, 4)])
        self.assertEqual(out, src)
        self.assertEqual(renames, [])


if __name__ == '__main__':
    unittest.main()
