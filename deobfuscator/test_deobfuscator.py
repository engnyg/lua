import os
import re
import tempfile
import unittest

import deobfuscator as d


class CipherTest(unittest.TestCase):
    def test_known_vectors(self):
        self.assertEqual(d.decrypt(bytes([20, 47, 120, 45, 133]), 7497094208326), b'table')
        self.assertEqual(d.decrypt(bytes([158, 226, 202, 92, 232, 159]), 458501751211), b'random')

    def test_empty(self):
        self.assertEqual(d.decrypt(b'', 123456789012), b'')


class LiteralTest(unittest.TestCase):
    def test_escapes(self):
        self.assertEqual(d.parse_lua_string(r'\20/x-\133'), bytes([20, 47, 120, 45, 133]))
        self.assertEqual(d.parse_lua_string(r'\a\b\f\v\x41\u{48}\z   B'), b'\a\b\f\vAHB')
        self.assertEqual(d.parse_lua_string('a\\\nb'), b'a\nb')
        for bad in (r'\256', r'\x4', r'\q', '\\'):
            with self.assertRaises(ValueError):
                d.parse_lua_string(bad)

    def test_quote_round_trip(self):
        data = bytes(range(256)) + b'"\\\n1'
        q = d.lua_quote(data)
        self.assertTrue(all(32 <= ord(c) < 127 for c in q))
        self.assertEqual(d.parse_lua_string(q[1:-1]), data)
        self.assertEqual(d.lua_quote(b'\x01' + b'2'), r'"\0012"')


def encrypt(plain: bytes, key: int) -> bytes:
    out, prev = bytearray(), 77
    for p, k in zip(plain, d.keystream(key)):
        out.append((p - k - prev) % 256)
        prev = p
    return bytes(out)


class PassTest(unittest.TestCase):
    def lit(self, text, key):
        return d.lua_quote(encrypt(text, key))

    def test_literal_and_prefix_expression(self):
        k = 12345678901234
        src = (f'local a = up0[up1({self.lit(b"x", k)}, {k})]\n'
               f'foo()\n'
               f'up0[up1({self.lit(b"Obj", k)}, {k})]:Close()\n'
               f'return (up0[up1({self.lit(b"s", k)}, {k})]:rep(2))\n')
        out = d.pass_literal(src, d.Decryptor())
        self.assertIn('local a = "x"\n', out)
        self.assertIn(';("Obj"):Close()', out)
        self.assertIn('return (("s"):rep(2))', out)

    def test_register_forms(self):
        k = 22222222222222
        src = (f'f1 = f1({self.lit(b"hi", k)}, {k})\n'
               f'f1 = up2[f1]\n'
               f'v6 = {self.lit(b"yo", k)}\n'
               f'f9 = {k}\n'
               f'local v7 = f9\n'
               f'print(up2[up3(v6, v7)])\n')
        dec = d.Decryptor()
        out = d.pass_register_args(d.pass_register_call(src, dec), dec)
        self.assertIn('f1 = "hi"\n', out)
        self.assertIn('print("yo")', out)

    def test_register_not_across_blocks(self):
        k = 22222222222222
        src = f'v6 = {self.lit(b"yo", k)}\nend\nprint(up2[up3(v6, {k})])\n'
        self.assertEqual(d.pass_register_args(src, d.Decryptor()), src)

    def test_strings_are_skipped(self):
        src = '-- up0[up1("\\1", 12345678901234)]\n'
        self.assertEqual(d.pass_literal(src, d.Decryptor()), src)


class JunkTest(unittest.TestCase):
    def run_junk(self, src):
        return d.remove_junk(src, d.Counter())

    def test_only_whole_pure_statements(self):
        src = ('x = 1\nbit32.rrotate(427, 18)\ny = 2\n'
               'v = 2 < bit32.rrotate(429, 17)\n'
               'local _ = 1 + bit32.bor(2,\n 3)\n'
               'local _ = 29612 + f2(1)\n'
               'local _ = -5 + (bit32.rrotate(string.unpack(">i8", "\\0"), 1) + 3)\n'
               'z = 3\n')
        out = self.run_junk(src)
        self.assertNotIn('bit32.rrotate(427, 18)', out)
        self.assertIn('v = 2 < bit32.rrotate(429, 17)', out)
        self.assertIn('local _ = 1 + bit32.bor(2,', out)
        self.assertIn('local _ = 29612 + f2(1)', out)
        self.assertNotIn('string.unpack', out)

    def test_keeps_statement_before_paren(self):
        src = 'f()\nbit32.band(1, 2)\n(g)()\n'
        self.assertEqual(self.run_junk(src), src)

    def test_empty_function_only_if_unreferenced(self):
        src = 'local function f7()\nend\nlocal function f8()\nend\nreturn f8\n'
        out = self.run_junk(src)
        self.assertNotIn('f7', out)
        self.assertIn('local function f8()', out)

    def test_underscore_read_disables_removal(self):
        src = 'local _ = 5\nprint(_)\n'
        self.assertEqual(self.run_junk(src), src)


class CliTest(unittest.TestCase):
    def test_refuses_to_overwrite(self):
        with tempfile.TemporaryDirectory() as t:
            src = os.path.join(t, 'script')
            with open(src, 'w') as fh:
                fh.write('print(1)\n')
            with self.assertRaises(SystemExit):
                d.main([src, '-o', src])
            with self.assertRaises(SystemExit):
                d.main([src, '-o', os.path.join(t, 'o.txt'), '-s', os.path.join(t, 'o.txt')])
            d.main([src])
            with open(src) as fh:
                self.assertEqual(fh.read(), 'print(1)\n')
            self.assertTrue(os.path.exists(src + '_deobfuscated.lua'))
            self.assertTrue(os.path.exists(src + '_deobfuscated_strings.json'))


if __name__ == '__main__':
    unittest.main()
